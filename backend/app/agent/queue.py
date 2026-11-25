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

A command and its run (DM-138, changed by DM-196): the box runs a command as
``pridem --json --command <id> <verb>``, and the id comes back in the run's
journal header and in its verdict. Whichever comes first links the two
(``link``): ``commands.run_id`` and ``runs.command_id``. A ``taken`` command
with its run is running; its verdict makes it ``done`` (``finish``) -- the
result of the run is the verdict's own. A command the Panel does not have is
not linked (a run of the console, another Panel): the run is kept, a line
logged. A command of another server is ``run-foreign``.

Expiry, lazily, wherever the server's commands are read:

- a ``taken`` command no run took up, ``EXPIRE_AFTER`` after it was taken;
- a ``taken`` command whose run died: the box says its journal is left
  without a verdict and nobody holds the lock (``app.runs.status.dead``, the
  rule of an ``abandoned`` run). Only the box's own fields tell it: while
  another command holds the lock, a dead run and a running one look the same,
  and the command waits -- until the lock is free, or until the next command
  under the lock gives the dead run its verdict (``recover``).

A verdict that comes after an expiry still makes the command ``done``: the
fact wins.
"""

import asyncio
import logging
import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.box import AgentRefusalError
from app.agent.models import Command, CommandState, Run, ServerState
from app.runs.status import dead

logger = logging.getLogger(__name__)

EXPIRE_AFTER = timedelta(minutes=10)
POLL_WINDOW_S = 55.0
POLL_PAUSE_S = 1.0


async def expire_taken(session: AsyncSession, server_id: uuid.UUID) -> None:
    """The server's ``taken`` commands that will not end: expired (module
    docstring)."""
    await session.execute(
        update(Command)
        .where(
            Command.server_id == server_id,
            Command.state == CommandState.TAKEN.value,
            Command.run_id.is_(None),
            Command.taken_at < func.now() - EXPIRE_AFTER,
        )
        .values(state=CommandState.EXPIRED.value)
    )
    state = await session.get(ServerState, server_id)
    if state is None:
        return
    running = await session.execute(
        select(Command.id, Command.run_id).where(
            Command.server_id == server_id,
            Command.state == CommandState.TAKEN.value,
            Command.run_id.is_not(None),
        )
    )
    gone = [
        command_id
        for command_id, run_id in running.all()
        if run_id is not None
        and dead(run_id, state.journals_without_verdict, state.lock_open_by)
    ]
    if gone:
        # a guarded write: a verdict that made one done meanwhile stays done
        await session.execute(
            update(Command)
            .where(Command.id.in_(gone), Command.state == CommandState.TAKEN.value)
            .values(state=CommandState.EXPIRED.value)
        )


async def link(
    session: AsyncSession, server_id: uuid.UUID, run: Run, command_id: str
) -> None:
    """Link a run to the command it names (module docstring); the run's row
    is locked by the caller, the command's is locked here -- the run first."""
    try:
        key = uuid.UUID(command_id)
    except ValueError:
        key = None
    command = (
        None
        if key is None
        else await session.scalar(
            select(Command).where(Command.id == key).with_for_update()
        )
    )
    if command is None:
        logger.warning(
            "a run names a command the Panel does not have",
            extra={
                "event": "agent.command_unknown",
                "ctx": {"run_id": run.run_id, "command": command_id},
            },
        )
        return
    if command.server_id != server_id:
        raise AgentRefusalError("run-foreign")
    if command.run_id is None:
        command.run_id = run.run_id
    if run.command_id is None and command.run_id == run.run_id:
        run.command_id = command.id


async def finish(session: AsyncSession, run: Run) -> None:
    """The run's verdict came: its command is done (module docstring)."""
    if run.command_id is None:
        return
    command = await session.scalar(
        select(Command).where(Command.id == run.command_id).with_for_update()
    )
    if command is not None and command.run_id == run.run_id:
        command.state = CommandState.DONE.value


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
