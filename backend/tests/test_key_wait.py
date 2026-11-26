"""A run waiting for a key to a repository, on the grid of DM-159: the rule of
``app.runs.keys`` over the run's lines, the run's page, the card's route and
the stream's ``event: key``."""
# ruff: noqa: S608 -- the SQL is the tests' own

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import text

from app.core.database import make_engine, make_sessions
from app.runs.router import stream_lines
from tests.conftest import execute
from tests.fake_box import header_line, log_line
from tests.people import World
from tests.test_runs import heard, line, page, run, server

RUN = "2026-11-26T12:00:00Z-ab12"
KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9"
    "GKJl pridem github.com-o-velo"
)
PAGE = "https://github.com/o/velo/settings/keys"


def notice(seq: int, **given: object) -> dict[str, object]:
    """A line ``notice`` ``key_needed`` of contract 2, written out."""
    body: dict[str, object] = {
        "kind": "key_needed",
        "repo": "git@github.com:o/velo.git",
        "key": KEY,
        "page": PAGE,
        "write": False,
        "wait_s": 1800.0,
        "again": False,
    }
    body.update(given)
    present = {k: v for k, v in body.items() if v is not None}
    return {
        "event": "notice",
        "seq": seq,
        "at": f"2026-11-26T12:00:{seq:02d}.000Z",
        "notice": present,
    }


def finished_step(seq: int, status: str = "ok") -> dict[str, object]:
    body: dict[str, object] = {
        "event": "step_finished",
        "seq": seq,
        "at": f"2026-11-26T12:00:{seq:02d}.000Z",
        "phase": "main",
        "stack": "pridem-sources",
        "name": "deploy_key",
        "order": 1,
        "status": status,
        "verify": {"repo": "git@github.com:o/velo.git"} if status == "ok" else {},
    }
    if status != "ok":
        body["reason"] = {"code": "deploy_key:no-access", "repo": "x", "wait_s": 1800}
    return body


def run_finished(seq: int) -> dict[str, object]:
    return {
        "event": "run_finished",
        "seq": seq,
        "at": f"2026-11-26T12:00:{seq:02d}.000Z",
        "exit_code": 1,
        "result": "red",
    }


def waiting_run(world: World, *lines: dict[str, object]) -> uuid.UUID:
    target = server(world, "velo-a")
    heard(world, target)
    run(world, target, RUN)
    line(world, RUN, {**header_line(RUN), "at": "2026-11-26T12:00:01.000Z"})
    for body in lines:
        line(world, RUN, body)
    return target


def wait_of(world: World, target: uuid.UUID, who: str = "admin_a") -> object:
    return page(world, who, target, RUN)["key_wait"]


def test_no_notice_no_wait(world: World) -> None:
    target = waiting_run(world, log_line(2))
    assert wait_of(world, target) is None
    assert world.call("admin_a", "GET", f"/api/v1/servers/{target}/key-wait") is None


def test_a_notice_opens_the_wait(world: World) -> None:
    target = waiting_run(world, log_line(2), notice(3), log_line(4))
    assert wait_of(world, target) == {
        "run_id": RUN,
        "repo": "git@github.com:o/velo.git",
        "key": KEY,
        "page": PAGE,
        "write": False,
        "why": None,
        "wait_s": 1800.0,
        "again": False,
        "at": "2026-11-26T12:00:03.000Z",
        "state": "waiting",
        "reason": None,
    }


def test_the_first_finished_step_after_it_closes_it(world: World) -> None:
    target = waiting_run(world, notice(2), log_line(3), finished_step(4, "ok"))
    found = wait_of(world, target)
    assert isinstance(found, dict)
    assert (found["state"], found["reason"]) == ("granted", None)


def test_a_failed_step_is_a_key_that_did_not_come(world: World) -> None:
    target = waiting_run(world, notice(2), finished_step(3, "failed"))
    found = wait_of(world, target)
    assert isinstance(found, dict)
    assert (found["state"], found["reason"]) == ("not_granted", "deploy_key:no-access")


def test_the_end_of_the_run_closes_an_open_wait(world: World) -> None:
    target = waiting_run(world, notice(2), log_line(3), run_finished(4))
    found = wait_of(world, target)
    assert isinstance(found, dict) and found["state"] == "ended"


def test_the_last_notice_is_the_wait(world: World) -> None:
    """Two repositories, one after the other: the second is the wait; a step
    finished before it closes nothing of it."""
    target = waiting_run(
        world,
        notice(2),
        finished_step(3),
        notice(4, repo="git@github.com:o/comms.git", page=None, again=True),
    )
    found = wait_of(world, target)
    assert isinstance(found, dict)
    assert (found["repo"], found["page"], found["again"], found["state"]) == (
        "git@github.com:o/comms.git",
        None,
        True,
        "waiting",
    )


def test_a_write_key(world: World) -> None:
    target = waiting_run(
        world, notice(2, write=True, why="types of the frontend", wait_s=0.0)
    )
    found = wait_of(world, target)
    assert isinstance(found, dict)
    assert (found["write"], found["why"], found["wait_s"]) == (
        True,
        "types of the frontend",
        0.0,
    )


def test_the_card_reads_the_running_run(world: World) -> None:
    """The card's route: the server's running run; a run that ended, or a run
    of another server, is not its."""
    target = waiting_run(world, notice(2))
    found = world.call("admin_a", "GET", f"/api/v1/servers/{target}/key-wait")
    assert isinstance(found, dict) and found["key"] == KEY
    execute(world.url, f"UPDATE runs SET ended_at = 'x' WHERE run_id = '{RUN}'")
    assert world.call("admin_a", "GET", f"/api/v1/servers/{target}/key-wait") is None
    other = server(world, "velo-b")
    assert world.call("admin_a", "GET", f"/api/v1/servers/{other}/key-wait") is None


async def _parts(stream: AsyncIterator[str], count: int) -> list[str]:
    return [await asyncio.wait_for(anext(stream), 5) for _ in range(count)]


def test_the_stream_says_the_wait_when_it_changes(
    world: World, migrated_db: str
) -> None:
    """``event: key`` when a wait opens and when it closes, once each; a run
    that never waits says none (the stream of DM-156 is as it was)."""
    target = waiting_run(world)

    async def scenario() -> list[str]:
        engine = make_engine(migrated_db)
        sessions = make_sessions(engine)

        async def write(body: dict[str, object]) -> None:
            async with sessions() as session, session.begin():
                await session.execute(
                    text(
                        "INSERT INTO events (run_id, seq, at, body) VALUES "
                        f"('{RUN}', {body['seq']}, '{body['at']}', "
                        f"'{json.dumps(body)}'::jsonb)"
                    )
                )

        async def never() -> bool:
            return False

        stream = stream_lines(sessions, target, RUN, 0, never)
        got: list[str] = []
        try:
            got += await _parts(stream, 2)  # the header, the state -- no key
            await write(notice(2))
            got += await _parts(stream, 2)  # the line, then the key
            await write(log_line(3))
            got += await _parts(stream, 1)  # a line only: the key is the same
            await write(finished_step(4))
            got += await _parts(stream, 2)  # the line, then the key again
        finally:
            await engine.dispose()
        return got

    got = asyncio.run(scenario())
    kinds = [part.split("event: ")[1].split("\n")[0] for part in got]
    assert kinds == ["line", "status", "line", "key", "line", "line", "key"]
    keys = [json.loads(part.split("data: ")[1]) for part in got if "event: key" in part]
    assert [k["state"] for k in keys] == ["waiting", "granted"]


def other_step(seq: int, status: str) -> dict[str, object]:
    """A step after the key's, of another stack and name."""
    body = {
        **finished_step(seq, status),
        "stack": "velo",
        "name": "build" if status == "ok" else "tests",
        "order": 7,
    }
    if status == "ok":
        body["verify"] = {"image_id": "sha256:0"}
    else:
        body["reason"] = {"code": "command-failed", "argv": ["x"], "exit_code": 1}
    return body


def _key_of_the_stream(target: uuid.UUID, migrated_db: str) -> list[dict[str, object]]:
    """The first ``event: key`` the stream says of the whole run, read from its
    start."""

    async def scenario() -> list[dict[str, object]]:
        engine = make_engine(migrated_db)

        async def never() -> bool:
            return False

        said: list[dict[str, object]] = []
        try:
            stream = stream_lines(make_sessions(engine), target, RUN, 0, never)
            # the whole run is written: its lines, the state, then the key --
            # one poll says it all; a key never said ends in a timeout here
            while not said:
                part = await asyncio.wait_for(anext(stream), 5)
                if part.startswith("event: key"):
                    said.append(json.loads(part.split("data: ")[1]))
            return said
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


def test_the_first_closing_line_after_the_notice_decides(
    world: World, migrated_db: str
) -> None:
    """A run as a box writes it: the key's step ends, other steps go on -- one
    ``ok``, one ``failed`` -- and the run ends. The wait is decided by the
    first closing line after the notice, not by the last of the run: the key
    came (``granted``), on the run's page and in the stream's ``event: key``.
    FIX DM-159: before it every case had one closing line, the first was the
    last."""
    target = waiting_run(
        world,
        notice(2),
        finished_step(3, "ok"),
        other_step(4, "ok"),
        other_step(5, "failed"),
        run_finished(6),
    )
    found = wait_of(world, target)
    assert isinstance(found, dict)
    assert (found["state"], found["reason"]) == ("granted", None)
    told = _key_of_the_stream(target, migrated_db)
    assert [(k["state"], k["reason"]) for k in told] == [("granted", None)]


def test_a_key_that_did_not_come_stays_so_whatever_follows(
    world: World, migrated_db: str
) -> None:
    """The pair: the key's step fails, a later step goes ``ok``, the run ends
    -- the wait is ``not_granted`` with the key step's reason."""
    target = waiting_run(
        world,
        notice(2),
        finished_step(3, "failed"),
        other_step(4, "ok"),
        run_finished(5),
    )
    found = wait_of(world, target)
    assert isinstance(found, dict)
    assert (found["state"], found["reason"]) == ("not_granted", "deploy_key:no-access")
    told = _key_of_the_stream(target, migrated_db)
    assert [(k["state"], k["reason"]) for k in told] == [
        ("not_granted", "deploy_key:no-access")
    ]
