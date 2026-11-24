"""The queue of commands of a server (``PRIMER-PANEL-TZ-2`` section 6).

Giving a command is taking it: the oldest ``queued`` command of the server
becomes ``taken`` in the same short transaction that reads it (``SELECT ...
FOR UPDATE SKIP LOCKED``), and only when the server has no ``taken`` one -- a
partial unique index holds "one ``taken`` per server" even against a race.
The long-poll waits WITHOUT a transaction: it asks again every
``POLL_PAUSE_S`` seconds for up to ``POLL_WINDOW_S`` (under the agent's 60 s
and nginx's 90 s, DM-147), then answers 204.

Commands do not repeat themselves: a ``taken`` one is ``expired`` once
``EXPIRE_AFTER`` has passed since it was taken -- lazily, wherever the
server's commands are read (the box's next poll, the list of a person, a new
command), no process in the background.

KNOWN CEILING -- a taken command ends only refused or expired:

1. Mechanics: no message of contract 4 carries the command's id (the verdict
   and the journal do not, DM-138), so a run cannot be tied to the command
   that started it; a ``taken`` command is ended by the agent's refusal or
   by ``expire_taken`` ten minutes after it was taken. A server takes at most
   one command in ten minutes.
2. Status: acknowledged by design (gate DM-153, R7).
3. Task: DM-138 -- the command's id in the journal's header and the verdict.
4. Unfreeze trigger: the header line or the verdict of contract 2 carries
   the command's id.
5. Agreed fix: the run of that id links ``runs.command_id`` and
   ``commands.run_id``; its verdict makes the command ``done``; ``expire_taken``
   keeps only commands no run took up.
6. Rejected: "the first new run after ``taken_at`` is the command's" -- a run
   of the console or a timer in that window would be counted as it.
"""

import asyncio
import logging
import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.models import Command, CommandState

logger = logging.getLogger(__name__)

EXPIRE_AFTER = timedelta(minutes=10)
POLL_WINDOW_S = 55.0
POLL_PAUSE_S = 1.0


async def expire_taken(session: AsyncSession, server_id: uuid.UUID) -> None:
    """The server's ``taken`` commands older than ``EXPIRE_AFTER``: expired."""
    await session.execute(
        update(Command)
        .where(
            Command.server_id == server_id,
            Command.state == CommandState.TAKEN.value,
            Command.taken_at < func.now() - EXPIRE_AFTER,
        )
        .values(state=CommandState.EXPIRED.value)
    )


async def take_next(session: AsyncSession, server_id: uuid.UUID) -> Command | None:
    """Take the server's oldest queued command, in the caller's transaction;
    ``None`` -- nothing to give, or a command of the server is taken."""
    await expire_taken(session, server_id)
    busy = await session.scalar(
        select(Command.id).where(
            Command.server_id == server_id, Command.state == CommandState.TAKEN.value
        )
    )
    if busy is not None:
        return None
    command = await session.scalar(
        select(Command)
        .where(
            Command.server_id == server_id, Command.state == CommandState.QUEUED.value
        )
        .order_by(Command.requested_at, Command.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if command is None:
        return None
    command.state = CommandState.TAKEN.value
    command.taken_at = await session.scalar(select(func.now()))
    await session.flush()
    return command


async def wait_for_command(
    sessions: async_sessionmaker[AsyncSession], server_id: uuid.UUID
) -> Command | None:
    """The long-poll: ask every ``POLL_PAUSE_S`` until a command is taken or
    ``POLL_WINDOW_S`` passes. Each ask is its own short transaction."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + POLL_WINDOW_S
    while True:
        try:
            async with sessions() as session, session.begin():
                command = await take_next(session, server_id)
        except IntegrityError:
            # another ask of the same server took one first: the index of
            # "one taken per server" refused this one -- nothing to give
            logger.info(
                "a poll of the server lost the race for a command",
                extra={
                    "event": "agent.take_raced",
                    "ctx": {"server_id": str(server_id)},
                },
            )
            command = None
        if command is not None:
            return command
        if loop.time() + POLL_PAUSE_S > deadline:
            return None
        await asyncio.sleep(POLL_PAUSE_S)
