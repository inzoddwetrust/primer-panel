"""A run waiting for a key to a repository (DM-159): the one rule, read from
the run's own lines the Panel keeps -- no ask of GitHub, nothing sent to the
box: the box goes on by itself once the key works.

The machine (``pridem.steps.keys``, ``v0.1.10``) writes a ``notice``
``key_needed`` (contract 2, Additions 1.28) when a step waits for a deploy key
or a write key to work, or when a fresh key is refused again (``again``). A
notice names no step: the step that waits is the step that runs, and the wait
is over when that step ends -- ``wait_for_access`` writes no line while it
waits. So:

- the last ``key_needed`` of the run opens the wait (``waiting``);
- the first ``step_finished`` after it closes it: ``ok`` -- ``granted``, any
  other -- ``not_granted`` with the code of its reason (``no-access``);
- ``run_finished`` closes a wait nothing closed (``ended``).

The public key is shown to everybody who sees the server: it is no secret
(the owner's word of 26.11, DM-159).
"""

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Event, Run, Verdict


class KeyWait(BaseModel):
    run_id: str
    repo: str
    key: str
    page: str | None
    write: bool
    why: str | None
    wait_s: float
    again: bool
    at: str
    state: Literal["waiting", "granted", "not_granted", "ended"]
    reason: str | None


def _mapping(value: object) -> dict[str, object]:
    """A line's object: contract 4's model passed it into the table."""
    if not isinstance(value, dict):
        raise TypeError("a notice of the journal is an object")
    return value


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


async def key_wait(session: AsyncSession, run_id: str) -> KeyWait | None:
    """The run's last wait for a key, and how it stands; ``None`` -- none."""
    found = (
        await session.execute(
            select(Event.seq, Event.body)
            .where(
                Event.run_id == run_id,
                Event.body["event"].astext == "notice",
                Event.body["notice"]["kind"].astext == "key_needed",
            )
            .order_by(Event.seq.desc())
            .limit(1)
        )
    ).first()
    if found is None:
        return None
    seq, body = found
    notice = _mapping(body.get("notice"))
    after = await session.scalar(
        select(Event.body)
        .where(
            Event.run_id == run_id,
            Event.seq > seq,
            Event.body["event"].astext.in_(("step_finished", "run_finished")),
        )
        .order_by(Event.seq)
        .limit(1)
    )
    state: Literal["waiting", "granted", "not_granted", "ended"] = "waiting"
    reason: str | None = None
    if after is not None and after.get("event") == "run_finished":
        state = "ended"
    elif after is not None:
        state = "granted" if after.get("status") == "ok" else "not_granted"
        given = after.get("reason")
        if isinstance(given, dict) and isinstance(given.get("code"), str):
            reason = given["code"]
    return KeyWait(
        run_id=run_id,
        repo=str(notice["repo"]),
        key=str(notice["key"]),
        page=_text(notice.get("page")),
        write=bool(notice["write"]),
        why=_text(notice.get("why")),
        wait_s=float(str(notice["wait_s"])),
        again=bool(notice["again"]),
        at=str(body["at"]),
        state=state,
        reason=reason,
    )


async def running_run(session: AsyncSession, server_id: object) -> str | None:
    """The server's last run with no end and no verdict -- the rule of
    ``running`` of the card's runs (``app.agent.people.list_runs``)."""
    return await session.scalar(
        select(Run.run_id)
        .outerjoin(Verdict, Verdict.run_id == Run.run_id)
        .where(
            Run.server_id == server_id,
            Run.ended_at.is_(None),
            Verdict.run_id.is_(None),
        )
        .order_by(Run.started_at.desc().nulls_last(), Run.run_id.desc())
        .limit(1)
    )
