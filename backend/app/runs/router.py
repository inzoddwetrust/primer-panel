"""A run's page and its stream (DM-156).

- ``GET /api/v1/servers/{server_id}/runs/{run_id}`` -- the run, its state
  (``app.runs.status``), its verdict, the report for an LLM the box sent in
  the envelope (``report_llm``, byte for byte -- the Panel builds none, R-15)
  and what "repeat" queues, if anything.
- ``GET /api/v1/streams/servers/{server_id}/runs/{run_id}`` -- its lines as
  server-sent events, as they come: ``id`` is the line's ``seq``,
  ``event: line`` its body as the box sent it; ``event: status`` when the
  state changes; a keepalive comment every ``KEEPALIVE_S``. It goes on from
  ``Last-Event-ID``; only lines one after another are sent -- a gap waits for
  its line (PRIMER-PANEL-TZ-2 7). It closes when the run is finished or
  abandoned, or when the client goes. Every ask of the database is a short
  session of its own, once a ``POLL_S``: the request's session closed before
  the first byte; no transaction lives while the stream does. The path
  ``/api/v1/streams/`` has its own knobs on the route (``primer.yaml``:
  ``buffering: false``, ``read_timeout: 120s``, DM-147).

"Repeat" queues the verb and the arguments of the run's journal header --
only when its verb is a verb of the registry and its arguments, ``confirm``
aside, pass that verb's model: the machine writes some headers in a form of
their own (``db reset``, ``ssl renew``, ``seed --list``), and the Panel does
not translate them. A destructive one asks the name again (R-18). Changed by
DM-202: and only when the verb with them is a button
(``app.agent.verbs.not_a_button``) -- a header of ``register``, or of a run
given a file of the box (``--passport``), offers no repeat the queue refuses.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pridem.verbs import VERBS
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.access.rules import ServerRead, ServerScope
from app.agent.models import Event, Run, ServerState, Verdict
from app.agent.verbs import (
    CONFIRM,
    destructive,
    needed_permission,
    needs_sure,
    not_a_button,
)
from app.core.errors import ErrorClass, PanelError
from app.core.state import Core, get_core
from app.runs.status import ENDED, RunStatus, run_status

router = APIRouter(prefix="/api/v1")

POLL_S = 1.0
KEEPALIVE_S = 15.0

AboutServer = Annotated[ServerScope, Depends(ServerRead())]


class VerdictRef(BaseModel):
    result: str
    exit_code: int
    finished: str
    verified: bool


class Repeat(BaseModel):
    verb: str
    args: dict[str, object]
    sure: bool
    name: bool


class RunPage(BaseModel):
    run_id: str
    server_name: str
    verb: str | None
    actor: dict[str, object] | None
    started_at: str | None
    ended_at: str | None
    outcome: str | None
    status: RunStatus
    verdict: VerdictRef | None
    report_llm: str | None
    repeat: Repeat | None
    last_seq: int


async def _state_of(session: AsyncSession, server_id: uuid.UUID, run: Run) -> RunStatus:
    state = await session.get(ServerState, server_id)
    return run_status(
        run_id=run.run_id,
        ended=run.ended_at is not None,
        heartbeat_at=None if state is None else state.last_heartbeat_at,
        journals_without_verdict=[]
        if state is None
        else state.journals_without_verdict,
        lock_open_by=[] if state is None else state.lock_open_by,
        now=datetime.now(UTC),
    )


async def _run(session: AsyncSession, server_id: uuid.UUID, run_id: str) -> Run:
    run = await session.get(Run, run_id)
    if run is None or run.server_id != server_id:
        raise PanelError(ErrorClass.NOT_FOUND, "Not found")
    return run


def _repeat(found: ServerScope, header: dict[str, object] | None) -> Repeat | None:
    if header is None:
        return None
    verb, given = header.get("verb"), header.get("args")
    if not isinstance(verb, str) or verb not in VERBS or not isinstance(given, dict):
        return None
    args = {str(key): value for key, value in given.items() if key != CONFIRM}
    try:
        VERBS[verb].args.model_validate(args)
    except ValidationError:
        return None
    if not_a_button(verb, args) is not None:
        return None
    role = found.server.role
    needed = needed_permission(verb, args, role)
    if needed is not None and needed not in found.scope.permissions:
        return None
    original = {str(key): value for key, value in given.items()}
    return Repeat(
        verb=verb,
        args=args,
        sure=needs_sure(verb, args, role),
        name=destructive(verb, original),
    )


async def _gapless(
    session: AsyncSession, run_id: str, after: int
) -> list[tuple[int, object]]:
    rows = await session.execute(
        select(Event.seq, Event.body)
        .where(Event.run_id == run_id, Event.seq > after)
        .order_by(Event.seq)
    )
    lines: list[tuple[int, object]] = []
    expected = after + 1
    for seq, body in rows.all():
        if seq != expected:
            break
        lines.append((seq, body))
        expected += 1
    return lines


@router.get("/servers/{server_id}/runs/{run_id}")
async def run_page(run_id: str, found: AboutServer) -> RunPage:
    session = found.scope.session
    run = await _run(session, found.server.id, run_id)
    verdict = await session.get(Verdict, run_id)
    header = await session.scalar(
        select(Event.body).where(Event.run_id == run_id, Event.seq == 1)
    )
    lines = await _gapless(session, run_id, 0)
    body = None if verdict is None else verdict.body
    return RunPage(
        run_id=run.run_id,
        server_name=found.server.name,
        verb=run.verb,
        actor=run.actor,
        started_at=run.started_at,
        ended_at=run.ended_at,
        outcome=run.outcome,
        status=await _state_of(session, found.server.id, run),
        verdict=None
        if body is None or verdict is None
        else VerdictRef(
            result=str(body.get("result")),
            exit_code=int(str(body.get("exit_code"))),
            finished=str(body.get("finished")),
            verified=verdict.verified,
        ),
        report_llm=None if verdict is None else verdict.report_llm,
        repeat=_repeat(found, header),
        last_seq=len(lines),
    )


def _event(name: str, data: object, seq: int | None = None) -> str:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    head = f"id: {seq}\n" if seq is not None else ""
    return f"{head}event: {name}\ndata: {text}\n\n"


async def stream_lines(
    sessions: async_sessionmaker[AsyncSession],
    server_id: uuid.UUID,
    run_id: str,
    after: int,
    gone: Callable[[], Coroutine[object, object, bool]],
) -> AsyncIterator[str]:
    """The run's lines after ``after``, as they come (module docstring)."""
    sent = after
    shown: RunStatus | None = None
    quiet = 0.0
    while True:
        async with sessions() as session:
            run = await _run(session, server_id, run_id)
            lines = await _gapless(session, run_id, sent)
            status = await _state_of(session, server_id, run)
        for seq, body in lines:
            yield _event("line", body, seq)
            sent = seq
        if status != shown:
            yield _event("status", {"status": status.value, "last_seq": sent})
            shown = status
        if status in ENDED and not lines:
            return
        if await gone():
            return
        await asyncio.sleep(POLL_S)
        quiet += POLL_S
        if quiet >= KEEPALIVE_S:
            yield ": keepalive\n\n"
            quiet = 0.0


@router.get("/streams/servers/{server_id}/runs/{run_id}")
async def run_stream(
    run_id: str,
    request: Request,
    found: AboutServer,
    core: Annotated[Core, Depends(get_core)],
) -> StreamingResponse:
    await _run(found.scope.session, found.server.id, run_id)
    given = request.headers.get("last-event-id", "")
    after = int(given) if given.isascii() and given.isdigit() else 0
    return StreamingResponse(
        stream_lines(
            core.sessions, found.server.id, run_id, after, request.is_disconnected
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
