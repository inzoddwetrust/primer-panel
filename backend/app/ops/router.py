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
  says ``source: file``; an edit and "apply" answer it 409. ``damaged``
  (changed by DM-158 B): the file is no sops file the Panel decrypts
  (``reason: sops-damaged``) or the path is no file (``not-a-file``) -- what
  lies in primer-ops is wrong, not the request; an edit and "apply" answer it
  409.
- **An edit** is one commit under the Panel's lock of ``primer-ops`` (a
  Postgres advisory lock: one operation on the clone at a time); its message
  names the server, the version, the path -- never a value -- and the person
  in the trailer ``Edited-By: <user id>``. ``server.name``, ``server.role``,
  ``version`` and the secrets are not the field route's, by their path, one
  under it or one above it (``UNTOUCHABLE``, DM-211); the result must pass the
  pinned machine's loader,
  or the edit is refused 422 with its findings. It carries
  ``base``, the commit the person read: when the server's file differs at the
  head from what it was at ``base``, the edit is refused 409 -- no merge. A
  push the remote refuses (someone pushed past the Panel) is tried again on
  the new head while the file there is still the one of ``base``, three times
  at most.
- **"Apply"** is the command ``update`` of the queue, through the one way in
  (``app.agent.people.enqueue``: not a button, prod's "are you sure?"), with
  the permission ``passport`` (PRIMER-PANEL-TZ-1). Changed by DM-158 B: it
  reads primer-ops first (503 when it is out of reach) and refuses 409 a
  passport the box's ``update`` would fail on -- ``absent``, ``damaged``,
  ``invalid`` (``UNAPPLIABLE``); the permission is asked before anything that
  tells the state. It is **applied** when the
  newest green verified verdict whose ``fetch_passport`` read ``primer-ops``
  read the server's file as it is at the head: the same blob at its
  ``ops_commit`` (contract 2, the step's fact).
- **The database over primer-ops** (DM-211): a route lets its transaction go
  before it waits for the lock -- no connection of the pool and no lock of the
  project's row is held while ``git``, ``ssh`` or ``sops`` run -- and takes
  the project again (``write_scope``, locked, read anew) in the transaction
  that writes: an edit before its push, "apply" where it queues. The lock is
  waited for ``OPS_WAIT_S`` at most: ``primer-ops is busy`` (503). A refusal of
  ``git`` answers 503 with the class of its cause, never what it said.
- No answer, log line or audit row carries a secret's value.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.access.actions import Action, permission_for
from app.access.permissions import Permission
from app.access.rules import ServerRead, ServerScope, ServerWrite, write_scope
from app.agent.models import Verdict
from app.agent.people import CommandIn, CommandOut, enqueue
from app.audit.models import ActorKind
from app.audit.service import record
from app.core.errors import ErrorClass, PanelError
from app.core.state import Core, get_core
from app.ops.passport import (
    DamagedError,
    NotRecipientError,
    Plain,
    age_public_key,
    checked,
    decrypted,
    edited,
    is_secret,
    passport_path,
    touches,
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
TRY_LOCK = text("SELECT pg_try_advisory_lock(:k)")
UNLOCK = text("SELECT pg_advisory_unlock(:k)")
OPS_WAIT_S = 10.0
"""How long a request waits for the lock of ``primer-ops`` (DM-211)."""
OPS_POLL_S = 0.2

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
DAMAGED = "the passport in primer-ops is damaged ({reason}): mend it in primer-ops"
UNAPPLIABLE = {
    "absent": "no passport of this server in primer-ops: the box would fail on it",
    "damaged": DAMAGED,
    "invalid": "the machine refuses this passport: the box would fail on it",
}
"""What "apply" refuses before the queue: the box's ``update`` would fail on
it anyway (the dispatcher's word on DM-158 B). ``not-recipient`` is not here:
the box's key may open what the Panel's does not."""
BY_ITS_ROUTE = "a secret is set by /passport/secret"
VERSION = "the version is the Panel's to raise"
UNTOUCHABLE: dict[tuple[str, ...], str] = {
    ("asked",): BY_ITS_ROUTE,
    ("policies", "tls"): BY_ITS_ROUTE,
    ("server", "name"): NAME,
    ("server", "role"): ROLE,
    ("version",): VERSION,
}
"""What the route of a field never reaches -- by the path itself, one under
it or one above it (``touches``; changed by DM-211: ``["policies"]`` would
replace ``policies.tls`` whole, ``["server", "role", "x"]`` would make the role
a mapping): the secrets go by their own route; the name the box reads its
passport by and the role that decides the permission of a deploy are the
owner's (DM-158 A); the version is the Panel's to raise."""
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
    """One operation on the clone at a time, in every process of the Panel
    (changed by DM-211): the lock is tried on a short connection of its own,
    again every ``OPS_POLL_S`` until ``OPS_WAIT_S`` -- a request that waits
    holds no connection of the pool -- then ``primer-ops is busy`` (503, the
    log line ``ops.busy``). The connection that took it holds it to the end;
    the unlock is shielded from a cancellation, and a connection whose unlock
    failed is invalidated: Postgres frees the lock of a session that ends, so
    it never goes back to the pool held."""
    engine = core.engine.execution_options(isolation_level="AUTOCOMMIT")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + OPS_WAIT_S
    while True:
        connection = await engine.connect()
        try:
            got = await connection.scalar(TRY_LOCK, {"k": LOCK_KEY})
        except BaseException:
            await asyncio.shield(connection.close())
            raise
        if got:
            break
        await connection.close()
        if loop.time() >= deadline:
            logger.warning(
                "primer-ops is busy",
                extra={"event": "ops.busy", "ctx": {"waited_s": OPS_WAIT_S}},
            )
            raise PanelError(ErrorClass.UNAVAILABLE, "primer-ops is busy")
        await asyncio.sleep(OPS_POLL_S)
    try:
        yield
    finally:
        await asyncio.shield(_unlock(connection))


async def _unlock(connection: AsyncConnection) -> None:
    try:
        await connection.execute(UNLOCK, {"k": LOCK_KEY})
    except Exception:
        await connection.invalidate()
    await connection.close()


def _unreachable(error: Exception) -> PanelError:
    """503 with the class of the cause -- never a line of what ``git``,
    ``ssh`` or ``sops`` said (DM-211); a fault of the container itself (a
    full ``/tmp``, a key file missing) is ``other``."""
    if isinstance(error, OpsCommandError):
        what, code, reason = error.what, error.code, error.reason
    else:
        what, code, reason = type(error).__name__, None, "other"
    logger.warning(
        "primer-ops cannot be reached",
        extra={
            "event": "ops.unreachable",
            "ctx": {"what": what, "code": code, "reason": reason},
        },
    )
    return PanelError(
        ErrorClass.UNAVAILABLE, f"primer-ops cannot be reached now ({reason})"
    )


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


async def _again(found: ServerScope, action: Action) -> ServerScope:
    """The scope taken again after a let-go transaction (DM-211): the project
    read anew and locked -- archived, the server gone or the permission taken
    meanwhile is refused here, in the transaction that writes."""
    again = await write_scope(found.scope.session, found.scope.actor, found.server.id)
    _needs_passport(again, action)
    return again


def _needs_passport(found: ServerScope, action: Action) -> None:
    needed = permission_for(action, ServerRole(found.server.role))
    if needed is not None and needed not in found.scope.permissions:
        raise PanelError(ErrorClass.FORBIDDEN, f"The permission {needed} is needed")


async def _applied_fact(found: ServerScope) -> dict[str, object]:
    return await _facts(
        found,
        {"result": "green", "steps": [{"verify": {"source": "ops"}}]},
    )


async def _applied(
    fact: dict[str, object], server: str, repo: OpsRepo, head: Found
) -> dict[str, object]:
    commit = fact.get("ops_commit")
    if not isinstance(commit, str):
        return {"commit": None, "state": "unknown"}
    path = passport_path(server)
    at = await repo.file(commit, path) if await repo.known(commit) else None
    same = at is not None and at.blob == head.blob
    return {"commit": commit, "state": "applied" if same else "pending"}


@dataclass(frozen=True)
class Seen:
    """A server's passport as primer-ops holds it at the head: its state of
    the reading, and what the state has."""

    state: str
    head: str | None = None
    current: Found | None = None
    plain: Plain | None = None
    reason: str | None = None


async def _seen(repo: OpsRepo, server: str) -> Seen:
    """The passport at the head, read under the lock (the caller's)."""
    head = await repo.head()
    if head is None:
        return Seen("absent")
    try:
        current = await repo.file(head, passport_path(server))
    except NotAFileError:
        return Seen("damaged", head, reason="not-a-file")
    if current is None:
        return Seen("absent", head)
    try:
        plain = checked(await decrypted(repo.places, current.content))
    except NotRecipientError:
        return Seen("not-recipient", head, current)
    except DamagedError:
        return Seen("damaged", head, current, reason="sops-damaged")
    state = "invalid" if plain.problems else "ready"
    return Seen(state, head, current, plain)


@router.get("")
async def read_passport(found: Reading, core: CoreOf) -> dict[str, object]:
    if await _is_file(found):
        return {"state": "file"}
    fact = await _applied_fact(found)
    server = found.server.name
    # no connection held over primer-ops; a rollback expires what it loaded
    await found.scope.session.rollback()
    repo = core.ops
    try:
        async with ops_lock(core):
            panel_key = await _panel_key(repo)
            seen = await _seen(repo, server)
            if seen.plain is None or seen.current is None:
                answer: dict[str, object] = {"state": seen.state}
                if seen.reason is not None:
                    answer.update(reason=seen.reason, base=seen.head)
                return {**answer, "panel_key": panel_key}
            applied = await _applied(fact, server, repo, seen.current)
    except (OpsCommandError, OSError) as error:
        raise _unreachable(error) from error
    return {
        "state": seen.state,
        "base": seen.head,
        "version": seen.plain.version(),
        **view(seen.plain.data),
        "problems": seen.plain.problems,
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
    session = found.scope.session
    await session.commit()  # the project's row and the connection let go
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
            before = checked(await decrypted(repo.places, current.content))
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
            after = checked(await decrypted(repo.places, content))
            if after.problems:
                raise PanelError(
                    ErrorClass.INVALID,
                    f"the passport is refused: {'; '.join(after.problems)}",
                )
            # taken again before the push: archived, gone or without the
            # permission now -- refused while primer-ops is still as it was
            found = await _again(found, Action.PASSPORT_EDIT)
            await session.commit()
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
            ErrorClass.CONFLICT, DAMAGED.format(reason="sops-damaged")
        ) from error
    except NotAFileError as error:
        raise PanelError(
            ErrorClass.CONFLICT, DAMAGED.format(reason="not-a-file")
        ) from error
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
    for root, why in UNTOUCHABLE.items():
        if touches(path, root):
            raise PanelError(ErrorClass.INVALID, why)
    return await _edit(found, core, body.base, path, body.value)


@router.put("/secret")
async def edit_secret(body: SecretIn, found: Writing, core: CoreOf) -> EditOut:
    return await _edit(found, core, body.base, body.path(), body.value)


@router.post("/apply", status_code=201)
async def apply_passport(body: ApplyIn, found: Writing, core: CoreOf) -> CommandOut:
    _needs_passport(found, Action.PASSPORT_APPLY)
    if await _is_file(found):
        raise PanelError(ErrorClass.CONFLICT, FILE)
    await found.scope.session.commit()  # no lock of the project over primer-ops
    try:
        async with ops_lock(core):
            seen = await _seen(core.ops, found.server.name)
    except (OpsCommandError, OSError) as error:
        raise _unreachable(error) from error
    if seen.state in UNAPPLIABLE:
        why = UNAPPLIABLE[seen.state].format(reason=seen.reason)
        raise PanelError(ErrorClass.CONFLICT, why)
    found = await _again(found, Action.PASSPORT_APPLY)
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
