"""What people do about servers in the API (DM-153): a registration token, a
command in a server's queue, the server's commands.

- **A registration token** -- one-time, an hour (``PRIMER-PANEL-TZ-2`` 4),
  the permission ``servers``; shown once, kept as its sha256.
- **A command** is a verb of the machine the Panel runs (``pridem.verbs.VERBS``
  of the pinned release) for one server, checked before the queue:
  the verb is in the registry; its arguments pass the verb's own model; the
  person holds the action's permission (``app.access.actions``: by the verb
  and the server's role -- ``ssl`` with ``action: status`` is reading); a
  destructive command (``app.agent.verbs``) comes confirmed and its
  ``confirm`` is the server's name, typed exactly (R-18); on ``prod`` every
  action but reading comes confirmed. Then it is ``queued``, with an audit
  row. Changed by DM-155: the rules of verbs moved to ``app.agent.verbs``.
- **What a server's card reads** (DM-155): its runs, the last first, and the
  buttons the person has on it (``app.agent.verbs.buttons``).
- **A server of a project the person does not see is "not found"**, as every
  object of the Panel (DM-149).
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from pridem.verbs import VERBS
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.access.permissions import Permission
from app.access.rules import ProjectWrite, Scope, ServerRead, ServerScope, ServerWrite
from app.agent.models import Command, CommandState, RegistrationToken, Run, Verdict
from app.agent.queue import expire_taken
from app.agent.verbs import CONFIRM, buttons, destructive, needed_permission, needs_sure
from app.audit.models import ActorKind
from app.audit.service import record
from app.core.errors import ErrorClass, PanelError
from app.core.state import Core, get_core

router = APIRouter(prefix="/api/v1")

TOKEN_TTL = timedelta(hours=1)

ServersWrites = Annotated[Scope, Depends(ProjectWrite(Permission.SERVERS))]
OnServer = Annotated[ServerScope, Depends(ServerWrite())]
AboutServer = Annotated[ServerScope, Depends(ServerRead())]


class TokenCreated(BaseModel):
    id: uuid.UUID
    token: str
    expires_at: datetime


class CommandIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verb: str = Field(min_length=1, max_length=64)
    args: dict[str, object] = {}
    confirmed: bool = False


class CommandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    server_id: uuid.UUID
    verb: str
    args: dict[str, object]
    state: str
    requested_by: uuid.UUID
    requested_at: datetime
    confirmed_at: datetime | None
    taken_at: datetime | None
    refusal: str | None


@router.post("/projects/{project_id}/registration-tokens", status_code=201)
async def create_registration_token(scope: ServersWrites) -> TokenCreated:
    token = secrets.token_urlsafe(32)
    row = RegistrationToken(
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        project_id=scope.project.id,
        created_by=scope.actor.user_id,
        expires_at=datetime.now(UTC) + TOKEN_TTL,
    )
    scope.session.add(row)
    await scope.session.flush()
    record(
        scope.session,
        actor_kind=ActorKind.USER,
        actor_id=scope.actor.user_id,
        project_id=scope.project.id,
        action="registration_token.create",
        object_kind="registration_token",
        object_id=str(row.id),
        details={"expires_at": row.expires_at.isoformat()},
    )
    return TokenCreated(id=row.id, token=token, expires_at=row.expires_at)


@router.post("/servers/{server_id}/commands", status_code=201)
async def queue_command(body: CommandIn, found: OnServer) -> CommandOut:
    scope, server = found.scope, found.server
    verb = VERBS.get(body.verb)
    if verb is None:
        raise PanelError(ErrorClass.INVALID, f"{body.verb} is no verb of the machine")
    try:
        verb.args.model_validate(body.args)
    except ValidationError as error:
        raise PanelError(ErrorClass.INVALID, f"the arguments of {body.verb}") from error
    needed = needed_permission(body.verb, body.args, server.role)
    if needed is not None and needed not in scope.permissions:
        raise PanelError(ErrorClass.FORBIDDEN, f"The permission {needed} is needed")
    # Changed by DM-155: the destructive actions are the table of
    # app.agent.verbs (db restore and the resets of seed too), confirmed by
    # the server's name typed exactly; on prod every action but reading is
    # confirmed ("are you sure?", R-18).
    is_destructive = destructive(body.verb, body.args)
    if is_destructive:
        if not body.confirmed:
            raise PanelError(
                ErrorClass.CONFLICT, "A destructive command is confirmed first"
            )
        if body.args.get(CONFIRM) != server.name:
            raise PanelError(ErrorClass.INVALID, "confirm is the server's name")
    elif body.args.get(CONFIRM) is not None:
        raise PanelError(ErrorClass.INVALID, "confirm goes with a destructive command")
    if needs_sure(body.verb, body.args, server.role) and not body.confirmed:
        raise PanelError(ErrorClass.CONFLICT, "A command on prod is confirmed first")
    await expire_taken(scope.session, server.id)
    command = Command(
        server_id=server.id,
        verb=body.verb,
        args=body.args,
        requested_by=scope.actor.user_id,
        confirmed_at=datetime.now(UTC) if is_destructive else None,
        state=CommandState.QUEUED.value,
    )
    scope.session.add(command)
    await scope.session.flush()
    await scope.session.refresh(command)
    record(
        scope.session,
        actor_kind=ActorKind.USER,
        actor_id=scope.actor.user_id,
        project_id=scope.project.id,
        action="command.queue",
        object_kind="command",
        object_id=str(command.id),
        details={
            "server_id": str(server.id),
            "verb": body.verb,
            "confirmed": body.confirmed,
        },
    )
    return CommandOut.model_validate(command)


@router.get("/servers/{server_id}/commands")
async def list_commands(
    found: AboutServer, core: Annotated[Core, Depends(get_core)]
) -> list[CommandOut]:
    async with core.sessions() as session, session.begin():
        await expire_taken(session, found.server.id)
    rows = await found.scope.session.scalars(
        select(Command)
        .where(Command.server_id == found.server.id)
        .order_by(Command.requested_at)
    )
    return [CommandOut.model_validate(row) for row in rows]


RUNS_SHOWN = 50


class RunOut(BaseModel):
    run_id: str
    verb: str | None
    actor: dict[str, object] | None
    started_at: str | None
    ended_at: str | None
    outcome: str | None
    verdict: dict[str, object] | None
    running: bool


@router.get("/servers/{server_id}/runs")
async def list_runs(found: AboutServer) -> list[RunOut]:
    """The server's last runs, the last first; a run with no end and no
    verdict is running."""
    rows = await found.scope.session.execute(
        select(Run, Verdict.body["result"].astext, Verdict.verified)
        .outerjoin(Verdict, Verdict.run_id == Run.run_id)
        .where(Run.server_id == found.server.id)
        .order_by(Run.started_at.desc().nulls_last(), Run.run_id.desc())
        .limit(RUNS_SHOWN)
    )
    return [
        RunOut(
            run_id=run.run_id,
            verb=run.verb,
            actor=run.actor,
            started_at=run.started_at,
            ended_at=run.ended_at,
            outcome=run.outcome,
            verdict=None
            if result is None
            else {"result": result, "verified": verified},
            running=run.ended_at is None and result is None,
        )
        for run, result, verified in rows.all()
    ]


class ButtonOut(BaseModel):
    verb: str
    preset: dict[str, object]
    schema_: dict[str, object] = Field(serialization_alias="schema")
    positionals: list[str]
    sure: bool
    name: str
    destructive_options: dict[str, list[object]]


@router.get("/servers/{server_id}/verbs", response_model_by_alias=True)
async def list_buttons(found: AboutServer) -> list[ButtonOut]:
    """The buttons the person has on the server (``app.agent.verbs``)."""
    return [
        ButtonOut(
            verb=button.verb,
            preset=button.preset,
            schema_=button.schema,
            positionals=button.positionals,
            sure=button.sure,
            name=button.name,
            destructive_options=button.destructive_options,
        )
        for button in buttons(found.server.role, found.scope.permissions)
    ]
