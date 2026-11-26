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

The box is below the Panel (DM-210): what a line of its journal says reaches
a person only checked.

- ``page`` becomes a link in the person's browser, so it is an ``https``
  address or nothing (``https_page``): the model of contract 4 takes any text
  for it, ``javascript:`` too.
- The notice is read by a model of the Panel's own (``_Notice``), not by
  indexing. The agent's API takes a line only by the model of the machine's
  pinned release, but a line outlives the pin it was taken by: after a pin
  that changes the notice, the lines of before are still in the table. One
  that does not read is no wait -- ``None`` and a line of the log
  (``runs.notice_off_form``) -- never a 500 of the run's page, of the card or
  of the stream. Keys the model does not name are passed over: a key the
  machine adds does not put the wait out.
"""

import logging
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Event, Run, Verdict

logger = logging.getLogger(__name__)

PAGE_MAX = 2048
"""The longest ``page`` that is a link: an address, not a text."""


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


class _Notice(BaseModel):
    """A ``key_needed`` as the Panel reads it out of its table: every key the
    wait is made of, each of its own type -- no text for a number, no number
    for a flag. ``page`` and ``why`` are whatever came: ``https_page`` and
    ``_text`` take them. ``wait_s`` is any number that is one (a wait that
    ended before it began is shown as it is), never ``NaN`` or an infinity."""

    model_config = ConfigDict(extra="ignore")

    repo: Annotated[StrictStr, Field(min_length=1)]
    key: Annotated[StrictStr, Field(min_length=1)]
    page: object = None
    write: StrictBool
    why: object = None
    wait_s: Annotated[StrictFloat | StrictInt, Field(allow_inf_nan=False)]
    again: StrictBool


class _NoticeLine(BaseModel):
    """The line of the notice: its moment and the notice."""

    model_config = ConfigDict(extra="ignore")

    at: StrictStr
    notice: _Notice


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def https_page(value: object) -> str | None:
    """``value`` as an address a person may be sent to, or ``None``: a text
    of at most ``PAGE_MAX``, with no space and no control character in it, of
    the scheme ``https`` exactly, with a host and with no name or password
    before it. Anything else the box wrote -- ``javascript:``, ``data:``,
    ``http:`` -- is no link (DM-210)."""
    if not isinstance(value, str) or not 0 < len(value) <= PAGE_MAX:
        return None
    if any(char.isspace() or not char.isprintable() for char in value):
        return None
    if not value.startswith("https://"):
        return None
    try:
        parts = urlsplit(value)
        host = parts.hostname
    except ValueError:
        return None
    if not host:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    return value


async def key_wait(
    session: AsyncSession, run_id: str, *, said: set[int] | None = None
) -> KeyWait | None:
    """The run's last wait for a key, and how it stands; ``None`` -- none, or
    a notice that does not read. ``said`` -- the lines one reader has already
    logged as unread (the stream asks again every poll): a ``seq`` in it is
    not logged twice."""
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
    try:
        line = _NoticeLine.model_validate(body)
    except ValidationError as error:
        if said is None or seq not in said:
            # the field, not the branch of its type: ``notice.wait_s``
            fields = sorted(
                {".".join(str(part) for part in e["loc"][:2]) for e in error.errors()}
            )
            logger.warning(
                "a notice of a key that does not read",
                extra={
                    "event": "runs.notice_off_form",
                    "ctx": {"run_id": run_id, "seq": seq, "fields": fields},
                },
            )
        if said is not None:
            said.add(seq)
        return None
    notice = line.notice
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
        repo=notice.repo,
        key=notice.key,
        page=https_page(notice.page),
        write=notice.write,
        why=_text(notice.why),
        wait_s=float(notice.wait_s),
        again=notice.again,
        at=line.at,
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
