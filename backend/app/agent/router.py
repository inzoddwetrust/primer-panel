"""The paths of the agent, ``/agent/v1/`` (contract 4, ``PRIMER-PANEL-TZ-2``).

Bodies and answers are the models of contract 4 (``pridem.protocol``) --
no copy here: the body is read raw (the signature covers its bytes) and
parsed by the contract's model. Every path but the registration is under the
rule ``BoxSigned``; the registration is ``Public``: the one-time token is its
credential (gate DM-153, R5).
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pridem.protocol import (
    Command as CommandMessage,
)
from pridem.protocol import (
    CommandRefusal,
    EventBatch,
    EventsAccepted,
    Heartbeat,
    HistoryAccepted,
    HistoryBatch,
    RegisterRequest,
    RegisterResponse,
    VerdictEnvelope,
)
from pydantic import BaseModel, ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.rules import Public
from app.agent import queue, runs
from app.agent.box import AgentRefusalError, BoxRequest, BoxSigned, protocol_of
from app.agent.models import Command, CommandState, RegistrationToken, ServerState
from app.agent.signature import KeyFormError, public_key
from app.audit.models import ActorKind
from app.audit.service import record
from app.config import Settings
from app.core.database import get_db_session
from app.core.errors import ErrorClass, PanelError
from app.core.state import Core, get_core, get_settings
from app.projects.models import Project, Server

router = APIRouter(prefix="/agent/v1")

Box = Annotated[BoxRequest, Depends(BoxSigned())]
Anybody = Annotated[None, Depends(Public())]
Writer = Annotated[AsyncSession, Depends(get_db_session)]

HEARTBEAT_S = 30
FULL_STATE_S = 300
POLL_S = 60
"""The intervals the Panel gives a box (``PRIMER-PANEL-TZ-2`` sections 5, 6)."""


def _parsed[M: BaseModel](model: type[M], body: bytes) -> M:
    try:
        return model.model_validate_json(body)
    except ValidationError as error:
        raise PanelError(ErrorClass.INVALID, "the body is not of contract 4") from error


def _moment(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.post("/register", status_code=201)
async def register(
    request: Request,
    _: Anybody,
    session: Writer,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RegisterResponse:
    protocol_of(request)
    asked = _parsed(RegisterRequest, await request.body())
    try:
        public_key(asked.box_key_public)
    except KeyFormError as error:
        raise PanelError(ErrorClass.INVALID, str(error)) from error
    # the token is a secret of contract 4 (SecretStr since v0.1.10)
    digest = hashlib.sha256(asked.token.get_secret_value().encode()).hexdigest()
    token = await session.scalar(
        select(RegistrationToken)
        .where(RegistrationToken.token_hash == digest)
        .with_for_update()
    )
    if token is None:
        raise AgentRefusalError("token-unknown")
    if token.used_at is not None:
        raise AgentRefusalError("token-used")
    if token.expires_at <= datetime.now(UTC):
        raise AgentRefusalError("token-expired")
    taken = await session.scalar(
        select(Server.id).where(Server.name == asked.server_name)
    )
    if taken is not None:
        raise AgentRefusalError("name-taken")
    project = await session.get_one(Project, token.project_id)
    if asked.product_repo != project.repo:
        raise AgentRefusalError("product-mismatch")
    server = Server(
        project_id=project.id,
        name=asked.server_name,
        role=asked.role,
        box_id=str(uuid.uuid4()),
        box_key_public=asked.box_key_public,
    )
    session.add(server)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as error:
        # the name was taken by another registration at the same moment
        raise AgentRefusalError("name-taken") from error
    token.used_at = datetime.now(UTC)
    token.server_id = server.id
    record(
        session,
        actor_kind=ActorKind.BOX,
        actor_id=server.id,
        project_id=project.id,
        action="server.register",
        object_kind="server",
        object_id=str(server.id),
        details={"name": server.name, "role": server.role},
    )
    return RegisterResponse(
        box_id=server.box_id,
        agent_url=f"{settings.api_origin}/agent/v1/",
        heartbeat_s=HEARTBEAT_S,
        full_state_s=FULL_STATE_S,
        poll_s=POLL_S,
    )


@router.post("/heartbeat", status_code=204)
async def heartbeat(box: Box) -> Response:
    beat = _parsed(Heartbeat, box.body)
    values = {
        "last_heartbeat_at": datetime.now(UTC),
        "measured_at": beat.measured_at,
        "machine_version": beat.machine_version,
        "protocol_version": box.protocol,
        "lock_open_by": beat.lock_open_by,
        "journals_without_verdict": beat.journals_without_verdict,
        "last_run_id": beat.last_run_id,
        "updated_at": datetime.now(UTC),
    }
    # by its aliases: the form box-state.v1 is ``schema``, not the model's
    # ``schema_`` (contract 4's BoxSnapshot does not dump by alias itself)
    snapshot = None if beat.state is None else beat.state.model_dump(mode="json")
    statement = insert(ServerState).values(
        server_id=box.server.id, snapshot=snapshot, **values
    )
    # A light heartbeat keeps the last full form; a full one replaces it.
    changed = dict(values)
    if snapshot is not None:
        changed["snapshot"] = snapshot
    await box.session.execute(
        statement.on_conflict_do_update(index_elements=["server_id"], set_=changed)
    )
    return Response(status_code=204)


@router.get("/commands/next", response_model=CommandMessage)
async def next_command(box: Box, core: Annotated[Core, Depends(get_core)]) -> Response:
    server_id = box.server.id
    # the long-poll holds no transaction: the request's session ends here
    await box.session.commit()
    command = await queue.wait_for_command(core.sessions, server_id)
    if command is None:
        return Response(status_code=204)
    if command.taken_at is None:
        raise RuntimeError("a command given without the moment it was taken")
    # expires_at: the end of the time to take it up (PRIMER-PANEL-TZ-2 6, the
    # same EXPIRE_AFTER as the lazy expiry). Contract 4 reads no explicit
    # null: confirmed_at is given only when there is one (changed by DM-196).
    given: dict[str, object] = {
        "id": str(command.id),
        "verb": command.verb,
        "args": command.args,
        "expires_at": _moment(command.taken_at + queue.EXPIRE_AFTER),
    }
    if command.confirmed_at is not None:
        given["confirmed_at"] = _moment(command.confirmed_at)
    message = CommandMessage.model_validate(given)
    return JSONResponse(message.model_dump(mode="json"))


@router.post("/commands/{command_id}/refusal", status_code=204)
async def refuse_command(command_id: uuid.UUID, box: Box) -> Response:
    refusal = _parsed(CommandRefusal, box.body)
    command = await box.session.scalar(
        select(Command).where(Command.id == command_id).with_for_update()
    )
    if command is None or command.server_id != box.server.id:
        raise AgentRefusalError("run-foreign")
    await box.session.execute(
        update(Command)
        .where(Command.id == command_id, Command.state == CommandState.TAKEN.value)
        .values(state=CommandState.REFUSED.value, refusal=refusal.code)
    )
    return Response(status_code=204)


@router.post("/runs/{run_id}/events")
async def events(run_id: str, box: Box) -> EventsAccepted:
    batch = _parsed(EventBatch, box.body)
    last = await runs.keep_events(box.session, box.server.id, run_id, batch)
    return EventsAccepted(last_seq=last)


@router.post("/runs/{run_id}/verdict", status_code=204)
async def verdict(run_id: str, box: Box) -> Response:
    envelope = _parsed(VerdictEnvelope, box.body)
    signed = json.loads(box.body)["verdict"]
    await runs.keep_verdict(box.session, box.server, run_id, envelope, signed)
    return Response(status_code=204)


@router.post("/history")
async def history(box: Box) -> HistoryAccepted:
    batch = _parsed(HistoryBatch, box.body)
    raw = json.loads(box.body)["envelopes"]
    held = [
        await runs.keep_verdict(
            box.session, box.server, envelope.verdict.run_id, envelope, item["verdict"]
        )
        for envelope, item in zip(batch.envelopes, raw, strict=True)
    ]
    return HistoryAccepted(run_ids=held)
