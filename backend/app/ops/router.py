"""The routes of a server's passport (DM-158).

    GET  /api/v1/servers/{id}/passport          any member of the project
    PUT  /api/v1/servers/{id}/passport/field    ``passport``
    PUT  /api/v1/servers/{id}/passport/secret   ``passport``
    POST /api/v1/servers/{id}/passport/apply    ``passport``

- **States of the reading**: ``ready`` (the view of ``app.ops.passport``, the
  commit it was read at as ``base``), ``invalid`` (the same view of a passport
  the pinned machine's loader refuses, with its findings -- paths and codes,
  no values: an edit whose result passes mends it), ``absent`` (no such file in
  ``primer-ops``), ``not-recipient`` (the Panel's age key does not open it --
  its public key is shown, for the owner to add), ``file`` (the server reads
  its passport from a file on the box: an edit here would not reach it -- the
  box of the Panel, R-25, and every box without an ops directory). ``file`` is
  the fact of the box, the newest verified verdict whose ``fetch_passport``
  says ``source: file``; an edit and "apply" answer it 409.
- **An edit** is one commit under the Panel's lock of ``primer-ops`` (a
  Postgres advisory lock: one operation on the clone at a time); its message
  names the server, the version, the path -- never a value -- and the person
  in the trailer ``Edited-By: <user id>``. ``server.name`` and ``server.role``
  are no fields (``FIXED``); the result must pass the pinned machine's loader,
  or the edit is refused 422 with its findings. It carries
  ``base``, the commit the person read: when the server's file differs at the
  head from what it was at ``base``, the edit is refused 409 -- no merge. A
  push the remote refuses (someone pushed past the Panel) is tried again on
  the new head while the file there is still the one of ``base``, three times
  at most.
- **"Apply"** is the command ``update`` of the queue, through the one way in
  (``app.agent.people.enqueue``: not a button, prod's "are you sure?"), with
  the permission ``passport`` (PRIMER-PANEL-TZ-1). It is **applied** when the
  newest green verified verdict whose ``fetch_passport`` read ``primer-ops``
  read the server's file as it is at the head: the same blob at its
  ``ops_commit`` (contract 2, the step's fact).
- No answer, log line or audit row carries a secret's value.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import select, text

from app.access.actions import Action, permission_for
from app.access.permissions import Permission
from app.access.rules import ServerRead, ServerScope, ServerWrite
from app.agent.models import Verdict
from app.agent.people import CommandIn, CommandOut, enqueue
from app.audit.models import ActorKind
from app.audit.service import record
from app.core.errors import ErrorClass, PanelError
from app.core.state import Core, get_core
from app.ops.passport import (
    DamagedError,
    NotRecipientError,
    age_public_key,
    checked,
    decrypted,
    edited,
    is_secret,
    passport_path,
    view,
)
from app.ops.repo import Found, NotAFileError, OpsRepo
from app.ops.run import OpsCommandError
from app.projects.models import ServerRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/servers/{server_id}/passport")

Reading = Annotated[ServerScope, Depends(ServerRead())]
Writing = Annotated[ServerScope, Depends(ServerWrite())]
CoreOf = Annotated[Core, Depends(get_core)]

LOCK_KEY = 158_001
"""The Postgres advisory lock of the Panel's clone of ``primer-ops``."""

PUSH_TRIES = 3
FILE = (
    "the passport of this server is a file on the box: an edit in the Panel "
    "would not reach it"
)
CHANGED = "the passport has changed since {base}: read it again"
NAME = "server.name is the server's name: the box reads its passport by it"
ROLE = (
    "server.role is the owner's to change, not a field: it decides whether a "
    "deploy needs deploy_test or deploy_prod"
)
FIXED = {("server", "name"): NAME, ("server", "role"): ROLE}
"""Fields no edit reaches, by its own path or by one above it (the
dispatcher's word on DM-158 A): the name the box reads its passport by, and
the role that decides the permission of a deploy -- a ``passport`` that made
``prod`` a ``test`` would deploy it with ``deploy_test``."""
COMMIT = re.compile(r"[0-9a-f]{40}")


class FieldIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: str = Field(pattern=COMMIT.pattern)
    path: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    value: JsonValue

    @model_validator(mode="after")
    def _a_value(self) -> "FieldIn":
        if self.value is None:
            raise ValueError("a field is set, not removed")
        return self


class SecretIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: str = Field(pattern=COMMIT.pattern)
    stack: str | None = Field(default=None, min_length=1)
    key: str | None = Field(default=None, min_length=1)
    tls: Literal["cert", "key"] | None = None
    value: str = Field(min_length=1)

    @model_validator(mode="after")
    def _one_place(self) -> "SecretIn":
        named = self.stack is not None and self.key is not None
        if named == (self.tls is not None) or (self.stack is None) != (
            self.key is None
        ):
            raise ValueError("a secret is a stack and a key, or tls")
        return self

    def path(self) -> tuple[str, ...]:
        if self.tls is not None:
            return ("policies", "tls", self.tls)
        return ("asked", str(self.stack), str(self.key))


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool = False


class EditOut(BaseModel):
    commit: str
    version: int


@asynccontextmanager
async def ops_lock(core: Core) -> AsyncIterator[None]:
    """One operation on the clone at a time, in every process of the Panel;
    its own connection, outside any transaction."""
    engine = core.engine.execution_options(isolation_level="AUTOCOMMIT")
    async with engine.connect() as connection:
        await connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
        try:
            yield
        finally:
            await connection.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY}
            )


def _unreachable(error: Exception) -> PanelError:
    what = error.what if isinstance(error, OpsCommandError) else type(error).__name__
    code = error.code if isinstance(error, OpsCommandError) else None
    logger.warning(
        "primer-ops cannot be reached",
        extra={"event": "ops.unreachable", "ctx": {"what": what, "code": code}},
    )
    return PanelError(ErrorClass.UNAVAILABLE, "primer-ops cannot be reached now")


async def _facts(found: ServerScope, wanted: dict[str, object]) -> dict[str, object]:
    """The ``fetch_passport`` fact of the newest verified verdict of the
    server that holds ``wanted``; ``{}`` -- none."""
    contains = {**wanted, "steps": [{"name": "fetch_passport"}]}
    bodies = await found.scope.session.scalars(
        select(Verdict.body)
        .where(
            Verdict.server_id == found.server.id,
            Verdict.verified.is_(True),
            Verdict.body.contains(contains),
        )
        .order_by(Verdict.run_id.desc())
        .limit(1)
    )
    for body in bodies:
        steps = body.get("steps")
        for step in steps if isinstance(steps, list) else []:
            if isinstance(step, dict) and step.get("name") == "fetch_passport":
                verify = step.get("verify")
                if isinstance(verify, dict):
                    return verify
    return {}


async def _is_file(found: ServerScope) -> bool:
    return (await _facts(found, {})).get("source") == "file"


async def _panel_key(repo: OpsRepo) -> str:
    return age_public_key(await asyncio.to_thread(repo.places.age_key.read_text))


def _needs_passport(found: ServerScope, action: Action) -> None:
    needed = permission_for(action, ServerRole(found.server.role))
    if needed is not None and needed not in found.scope.permissions:
        raise PanelError(ErrorClass.FORBIDDEN, f"The permission {needed} is needed")


async def _applied(found: ServerScope, repo: OpsRepo, head: Found) -> dict[str, object]:
    fact = await _facts(
        found,
        {"result": "green", "steps": [{"verify": {"source": "ops"}}]},
    )
    commit = fact.get("ops_commit")
    if not isinstance(commit, str):
        return {"commit": None, "state": "unknown"}
    path = passport_path(found.server.name)
    at = await repo.file(commit, path) if await repo.known(commit) else None
    same = at is not None and at.blob == head.blob
    return {"commit": commit, "state": "applied" if same else "pending"}


@router.get("")
async def read_passport(found: Reading, core: CoreOf) -> dict[str, object]:
    if await _is_file(found):
        return {"state": "file"}
    repo = core.ops
    path = passport_path(found.server.name)
    try:
        async with ops_lock(core):
            panel_key = await _panel_key(repo)
            head = await repo.head()
            current = None if head is None else await repo.file(head, path)
            if head is None or current is None:
                return {"state": "absent", "panel_key": panel_key}
            try:
                plain = checked(
                    repo.places, await decrypted(repo.places, current.content)
                )
            except NotRecipientError:
                return {"state": "not-recipient", "panel_key": panel_key}
            applied = await _applied(found, repo, current)
    except (OpsCommandError, OSError) as error:
        raise _unreachable(error) from error
    except DamagedError as error:
        raise PanelError(
            ErrorClass.INVALID, "not a sops file the Panel decrypts"
        ) from error
    except NotAFileError as error:
        raise PanelError(ErrorClass.INVALID, f"{path} is not a file") from error
    return {
        "state": "invalid" if plain.problems else "ready",
        "base": head,
        "version": plain.version(),
        **view(plain.data),
        "problems": plain.problems,
        "apply": applied,
        "panel_key": panel_key,
    }


async def _edit(
    found: ServerScope,
    core: Core,
    base: str,
    path: tuple[str, ...],
    value: JsonValue,
) -> EditOut:
    _needs_passport(found, Action.PASSPORT_EDIT)
    if await _is_file(found):
        raise PanelError(ErrorClass.CONFLICT, FILE)
    repo = core.ops
    server = found.server.name
    where = passport_path(server)
    try:
        async with ops_lock(core):
            head = await repo.head()
            current = None if head is None else await repo.file(head, where)
            if head is None or current is None:
                raise PanelError(ErrorClass.NOT_FOUND, f"no {where} in primer-ops")
            read = await repo.file(base, where) if await repo.known(base) else None
            if read is None or read.blob != current.blob:
                raise PanelError(ErrorClass.CONFLICT, CHANGED.format(base=base))
            before = checked(repo.places, await decrypted(repo.places, current.content))
            version = before.version()
            if version is None:
                raise PanelError(
                    ErrorClass.INVALID, "the passport has no version to raise"
                )
            content = await edited(
                repo.places,
                current.content,
                [(path, value), (("version",), version + 1)],
            )
            after = checked(repo.places, await decrypted(repo.places, content))
            if after.problems:
                raise PanelError(
                    ErrorClass.INVALID,
                    f"the passport is refused: {'; '.join(after.problems)}",
                )
            what = "secret" if is_secret(path) else "field"
            message = (
                f"passport {server}: v{version + 1}, {what} {'.'.join(path)}\n"
                f"\nEdited-By: {found.scope.actor.user_id}\n"
            )
            for _ in range(PUSH_TRIES):
                commit = await repo.commit(head, where, content, message)
                if await repo.push(commit):
                    break
                head = await repo.head()
                moved = None if head is None else await repo.file(head, where)
                if head is None or moved is None or moved.blob != current.blob:
                    raise PanelError(ErrorClass.CONFLICT, CHANGED.format(base=base))
            else:
                raise PanelError(ErrorClass.CONFLICT, CHANGED.format(base=base))
    except (OpsCommandError, OSError) as error:
        raise _unreachable(error) from error
    except NotRecipientError as error:
        raise PanelError(
            ErrorClass.CONFLICT, "the Panel's age key does not open this passport"
        ) from error
    except DamagedError as error:
        raise PanelError(
            ErrorClass.INVALID, "not a sops file the Panel decrypts"
        ) from error
    except NotAFileError as error:
        raise PanelError(ErrorClass.INVALID, f"{where} is not a file") from error
    record(
        found.scope.session,
        actor_kind=ActorKind.USER,
        actor_id=found.scope.actor.user_id,
        project_id=found.scope.project.id,
        action="passport.edit",
        object_kind="server",
        object_id=str(found.server.id),
        details={"commit": commit, "path": ".".join(path), "version": version + 1},
    )
    return EditOut(commit=commit, version=version + 1)


@router.put("/field")
async def edit_field(body: FieldIn, found: Writing, core: CoreOf) -> EditOut:
    path = tuple(body.path)
    if is_secret(path):
        raise PanelError(ErrorClass.INVALID, "a secret is set by /passport/secret")
    if path == ("version",):
        raise PanelError(ErrorClass.INVALID, "the version is the Panel's to raise")
    for fixed, why in FIXED.items():
        if fixed[: len(path)] == path:
            raise PanelError(ErrorClass.INVALID, why)
    return await _edit(found, core, body.base, path, body.value)


@router.put("/secret")
async def edit_secret(body: SecretIn, found: Writing, core: CoreOf) -> EditOut:
    return await _edit(found, core, body.base, body.path(), body.value)


@router.post("/apply", status_code=201)
async def apply_passport(body: ApplyIn, found: Writing) -> CommandOut:
    _needs_passport(found, Action.PASSPORT_APPLY)
    if await _is_file(found):
        raise PanelError(ErrorClass.CONFLICT, FILE)
    command = await enqueue(
        found,
        CommandIn(verb="update", args={}, confirmed=body.confirmed),
        lambda _verb, _args, _role: Permission.PASSPORT,
    )
    record(
        found.scope.session,
        actor_kind=ActorKind.USER,
        actor_id=found.scope.actor.user_id,
        project_id=found.scope.project.id,
        action="passport.apply",
        object_kind="command",
        object_id=str(command.id),
        details={"server_id": str(found.server.id)},
    )
    return CommandOut.model_validate(command)
