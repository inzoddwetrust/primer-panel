"""Runs, their events and verdicts as boxes send them (``PRIMER-PANEL-TZ-2``
sections 7--9).

- **Events** are the lines of a run's journal, kept by ``(run_id, seq)``: a
  repeated line changes nothing (the first one stays; a repeat with another
  body is a defect of the box, logged). The answer is the last ``seq`` the
  Panel holds with no gap before it -- the agent goes on from the next. The
  header line (``seq`` 1) names the run's verb, actor and start; the line
  ``run_finished`` its end and result.
- **A verdict** is kept once per ``run_id``, its envelope's signature checked
  (``app.agent.signature``): one that does not hold is kept with
  ``verified: false`` -- red in the fleet, never silent. A verdict with no run
  yet (``history``, a run of the console) makes its run.
- **A run is its box's**: a ``run_id`` the Panel holds for another server is
  ``box-unknown`` to this one (gate DM-153, R8).
"""

import logging
import uuid
from datetime import UTC, datetime

from pridem.protocol import EventBatch, VerdictEnvelope
from pridem.state import HeaderLine, RunFinishedLine
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.box import AgentRefusalError
from app.agent.models import Event, Run, Verdict
from app.agent.signature import public_key, verdict_holds
from app.core.errors import ErrorClass, PanelError
from app.projects.models import Server

logger = logging.getLogger(__name__)


def _moment(value: str | datetime) -> str:
    """A moment of contract 2 as its JSON form."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return value


async def _run_of(session: AsyncSession, server_id: uuid.UUID, run_id: str) -> Run:
    """The run, made if new, locked; another server's -- ``box-unknown``."""
    await session.execute(
        insert(Run)
        .values(run_id=run_id, server_id=server_id)
        .on_conflict_do_nothing(index_elements=["run_id"])
    )
    run = await session.scalar(
        select(Run).where(Run.run_id == run_id).with_for_update()
    )
    if run is None or run.server_id != server_id:
        raise AgentRefusalError("box-unknown")
    return run


async def last_seq(session: AsyncSession, run_id: str) -> int:
    """The last ``seq`` held with no gap before it (0 -- none)."""
    held = await session.scalars(
        select(Event.seq).where(Event.run_id == run_id).order_by(Event.seq)
    )
    last = 0
    for seq in held:
        if seq != last + 1:
            break
        last = seq
    return last


async def keep_events(
    session: AsyncSession, server_id: uuid.UUID, run_id: str, batch: EventBatch
) -> int:
    run = await _run_of(session, server_id, run_id)
    for line in batch.events:
        body = line.model_dump(mode="json")
        if isinstance(line, HeaderLine):
            if line.run_id != run_id:
                raise PanelError(ErrorClass.INVALID, "the header names another run")
            run.verb = run.verb or line.verb
            run.actor = run.actor or line.actor.model_dump(mode="json")
            run.started_at = run.started_at or _moment(line.started)
        if isinstance(line, RunFinishedLine):
            run.ended_at = run.ended_at or line.at
            run.outcome = run.outcome or line.result
        kept = await session.scalar(
            insert(Event)
            .values(run_id=run_id, seq=line.seq, at=line.at, body=body)
            .on_conflict_do_nothing(index_elements=["run_id", "seq"])
            .returning(Event.seq)
        )
        if kept is None:
            held = await session.scalar(
                select(Event.body).where(Event.run_id == run_id, Event.seq == line.seq)
            )
            if held != body:
                logger.warning(
                    "a repeated line of a journal differs from the one kept",
                    extra={
                        "event": "agent.event_differs",
                        "ctx": {"run_id": run_id, "seq": line.seq},
                    },
                )
    await session.flush()
    return await last_seq(session, run_id)


async def keep_verdict(
    session: AsyncSession, server: Server, run_id: str, envelope: VerdictEnvelope
) -> str:
    verdict = envelope.verdict
    if verdict.run_id != run_id:
        raise PanelError(ErrorClass.INVALID, "the verdict names another run")
    run = await _run_of(session, server.id, run_id)
    run.verb = run.verb or verdict.verb
    run.actor = run.actor or verdict.actor.model_dump(mode="json")
    run.started_at = run.started_at or _moment(verdict.started)
    run.ended_at = run.ended_at or _moment(verdict.finished)
    run.outcome = run.outcome or verdict.result
    verified = verdict_holds(
        public_key(server.box_key_public), envelope.signature, verdict
    )
    await session.execute(
        insert(Verdict)
        .values(
            run_id=run_id,
            server_id=server.id,
            body=verdict.model_dump(mode="json"),
            envelope_signature=envelope.signature,
            verified=verified,
            signed_on_send=envelope.signed_on_send,
            report_llm=envelope.report_llm,
        )
        .on_conflict_do_nothing(index_elements=["run_id"])
    )
    if not verified:
        logger.warning(
            "a verdict whose signature does not hold, kept unverified",
            extra={"event": "agent.verdict_unverified", "ctx": {"run_id": run_id}},
        )
    return run_id
