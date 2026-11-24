"""A run's page and its stream (DM-156): its state by the box's fields, its
lines as they come, its report as the box sent it, and "repeat".

The SQL of these tests carries the tests' own values only."""
# ruff: noqa: S608

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text

from app.access import sessions as panel_sessions
from app.core.database import make_engine, make_sessions
from app.runs import router as runs_router
from app.runs.router import stream_lines
from tests.conftest import API_HOST, BACKEND, COMMIT, RELEASE, execute, query_scalar
from tests.fake_box import finished_line, header_line, log_line
from tests.people import World

API = "/api/v1/servers"


@pytest.fixture(autouse=True)
def quick_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runs_router, "POLL_S", 0.05)
    monkeypatch.setattr(runs_router, "KEEPALIVE_S", 10.0)


def server(
    world: World, name: str, role: str = "test", project: str = "a"
) -> uuid.UUID:
    server_id = uuid.uuid4()
    execute(
        world.url,
        "INSERT INTO servers (id, project_id, name, role, box_id, box_key_public) "
        f"VALUES ('{server_id}', '{world.projects[project]}', '{name}', '{role}', "
        f"'{uuid.uuid4()}', 'key')",
    )
    return server_id


def heard(
    world: World,
    server_id: uuid.UUID,
    ago: timedelta = timedelta(seconds=5),
    without: tuple[str, ...] = (),
    lock: tuple[str, ...] = (),
) -> None:
    execute(
        world.url,
        "INSERT INTO server_states (server_id, last_heartbeat_at, measured_at, "
        "machine_version, protocol_version, lock_open_by, journals_without_verdict) "
        f"VALUES ('{server_id}', "
        f"now() - interval '{int(ago.total_seconds())} seconds', "
        f"'2026-11-24T12:00:00Z', '0.1.9', 1, '{json.dumps(list(lock))}', "
        f"'{json.dumps(list(without))}')",
    )


def run(
    world: World, server_id: uuid.UUID, run_id: str, *, ended: bool = False
) -> None:
    end = "'2026-11-24T12:00:09Z'" if ended else "NULL"
    execute(
        world.url,
        "INSERT INTO runs (run_id, server_id, verb, started_at, ended_at) "
        f"VALUES ('{run_id}', '{server_id}', 'update', '2026-11-24T12:00:00Z', {end})",
    )


def line(world: World, run_id: str, body: dict[str, object]) -> None:
    execute(
        world.url,
        "INSERT INTO events (run_id, seq, at, body) VALUES "
        f"('{run_id}', {body['seq']}, '{body['at']}', '{json.dumps(body)}'::jsonb)",
    )


def verdict(
    world: World,
    server_id: uuid.UUID,
    run_id: str,
    report: str,
    *,
    verified: bool = True,
) -> None:
    body = {
        "run_id": run_id,
        "result": "green",
        "exit_code": 0,
        "finished": "2026-11-24T12:00:09Z",
    }
    execute(
        world.url,
        "INSERT INTO verdicts (run_id, server_id, body, envelope_signature, verified, "
        f"signed_on_send, report_llm) VALUES ('{run_id}', '{server_id}', "
        f"'{json.dumps(body)}'::jsonb, 's', {str(verified).lower()}, false, "
        f"'{report}')",
    )


def page(
    world: World, who: str, server_id: uuid.UUID, run_id: str
) -> dict[str, object]:
    found = world.call(who, "GET", f"{API}/{server_id}/runs/{run_id}", expect=200)
    assert isinstance(found, dict)
    return found


RUN = "2026-11-24T12:00:00Z-ab12"


def test_probe_DM_156_abandoned_unlike_finished(world: World) -> None:
    """A run finished, abandoned, running or on a silent box -- each its own
    state, by the box's fields: the line run_finished or the verdict; the
    journal left without a verdict with the lock free; the heartbeat."""
    # (name, ended, heard seconds ago, journal without a verdict, lock held)
    cases = [
        ("finished", True, 5, False, False),
        ("abandoned", False, 5, True, False),
        ("running-locked", False, 5, True, True),
        ("running", False, 5, False, True),
        ("silent", False, 95, True, False),
    ]
    got = {}
    for name, ended, ago, without, locked in cases:
        target = server(world, f"s-{name}")
        run_id = f"2026-11-24T12:00:00Z-{uuid.uuid4().hex[:4]}"
        heard(
            world,
            target,
            timedelta(seconds=ago),
            (run_id,) if without else (),
            ("update",) if locked else (),
        )
        run(world, target, run_id, ended=ended)
        got[name] = page(world, "staff_a", target, run_id)["status"]
    assert got == {
        "finished": "finished",
        "abandoned": "abandoned",
        "running-locked": "running",
        "running": "running",
        "silent": "silent",
    }


def test_the_report_is_the_box_s_byte_for_byte(world: World) -> None:
    target = server(world, "velo-a")
    heard(world, target)
    run(world, target, RUN, ended=True)
    report = "  # Report\\n\\nsecret-looking: s3cr3t-marker  \\n"
    verdict(world, target, RUN, report.replace("\\n", "\n"), verified=False)
    found = page(world, "staff_a", target, RUN)
    assert found["report_llm"] == "  # Report\n\nsecret-looking: s3cr3t-marker  \n"
    assert found["verdict"] == {
        "result": "green",
        "exit_code": 0,
        "finished": "2026-11-24T12:00:09Z",
        "verified": False,
    }
    assert found["status"] == "finished"


def test_repeat_where_the_header_is_the_verb_s(world: World) -> None:
    target = server(world, "velo-a")
    heard(world, target)
    cases: list[tuple[str, dict[str, object], object]] = [
        (
            "update",
            {"tries": ["velo=1.2.3"]},
            {
                "verb": "update",
                "args": {"tries": ["velo=1.2.3"]},
                "sure": False,
                "name": False,
            },
        ),
        ("db reset", {"stack": "velo", "confirm": "velo-a"}, None),
        ("seed", {"list": True}, None),
        (
            "destroy",
            {"confirm": "velo-a"},
            {"verb": "destroy", "args": {}, "sure": False, "name": True},
        ),
    ]
    for number, (verb, args, expected) in enumerate(cases):
        run_id = f"2026-11-24T12:00:0{number}Z-ab1{number}"
        run(world, target, run_id)
        header = {**header_line(run_id, verb), "args": args}
        line(world, run_id, header)
        assert page(world, "super", target, run_id)["repeat"] == expected, verb
    # no permission for the verb -- no repeat
    assert page(world, "staff_a", target, "2026-11-24T12:00:03Z-ab13")["repeat"] is None
    # prod asks "are you sure?"
    prod = server(world, "velo-prod", "prod")
    heard(world, prod)
    run(world, prod, "2026-11-24T13:00:00Z-cd01")
    line(
        world,
        "2026-11-24T13:00:00Z-cd01",
        {**header_line("2026-11-24T13:00:00Z-cd01", "update"), "args": {}},
    )
    repeat = page(world, "super", prod, "2026-11-24T13:00:00Z-cd01")["repeat"]
    assert isinstance(repeat, dict) and repeat["sure"] is True


def test_a_foreign_run_is_not_found(world: World) -> None:
    mine, other = server(world, "velo-a"), server(world, "velo-a2")
    run(world, other, RUN)
    world.call("admin_b", "GET", f"{API}/{other}/runs/{RUN}", expect=404)
    world.call(
        "staff_a", "GET", f"{API}/{mine}/runs/{RUN}", expect=404
    )  # not this server's
    world.call(
        "admin_b", "GET", f"/api/v1/streams/servers/{other}/runs/{RUN}", expect=404
    )
    world.call(
        "staff_a", "GET", f"/api/v1/streams/servers/{mine}/runs/{RUN}", expect=404
    )


def test_a_finished_run_s_stream_is_whole_and_closes(world: World) -> None:
    target = server(world, "velo-a")
    heard(world, target)
    run(world, target, RUN, ended=True)
    for body in (header_line(), log_line(2), finished_line(3)):
        line(world, RUN, body)
    answer = world.client.get(
        f"/api/v1/streams/servers/{target}/runs/{RUN}",
        headers=world.people["staff_a"].headers,
    )
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("text/event-stream")
    assert answer.headers["cache-control"] == "no-cache"
    ids = [
        part.split("\n")[0]
        for part in answer.text.split("\n\n")
        if part.startswith("id:")
    ]
    assert ids == ["id: 1", "id: 2", "id: 3"]
    assert 'event: status\ndata: {"status":"finished","last_seq":3}' in answer.text
    # Last-Event-ID goes on after it
    again = world.client.get(
        f"/api/v1/streams/servers/{target}/runs/{RUN}",
        headers={**world.people["staff_a"].headers, "Last-Event-ID": "2"},
    )
    assert [
        p.split("\n")[0] for p in again.text.split("\n\n") if p.startswith("id:")
    ] == ["id: 3"]


async def _take(stream: AsyncIterator[str], count: int) -> list[str]:
    """The next ``count`` parts, each within 5 s -- a stream that holds its
    lines back fails here, not by hanging."""
    return [await asyncio.wait_for(anext(stream), 5) for _ in range(count)]


async def _rest(stream: AsyncIterator[str]) -> list[str]:
    """Every part to the stream's end, within 5 s."""

    async def drain() -> list[str]:
        return [part async for part in stream]

    return await asyncio.wait_for(drain(), 5)


def test_probe_DM_156_sse_by_parts(world: World, migrated_db: str) -> None:
    """The stream gives each line as it comes, not at the end: a line written
    is a part; the next line, the next part; a gap waits for its line; the
    line run_finished ends it."""
    target = server(world, "velo-a")
    heard(world, target)
    run(world, target, RUN)
    line(world, RUN, header_line())

    async def scenario() -> list[list[str]]:
        engine = make_engine(migrated_db)
        sessions = make_sessions(engine)

        async def write(sql: str) -> None:
            async with sessions() as session, session.begin():
                await session.execute(text(sql))

        async def never() -> bool:
            return False

        def event(body: dict[str, object]) -> str:
            return (
                "INSERT INTO events (run_id, seq, at, body) VALUES "
                f"('{RUN}', {body['seq']}, '{body['at']}', '{json.dumps(body)}'::jsonb)"
            )

        parts: list[list[str]] = []
        stream = stream_lines(sessions, target, RUN, 0, never)
        try:
            parts.append(await _take(stream, 2))  # the header, then the state
            await write(event(log_line(2)))
            parts.append(await _take(stream, 1))
            await write(event(log_line(4)))  # a gap: 3 is missing
            waiting = asyncio.create_task(_take(stream, 2))
            await asyncio.sleep(0.3)  # the stream asks several times over the gap
            await write(event(log_line(3)))
            parts.append(await waiting)
            await write(event(finished_line(5)))
            await write(f"UPDATE runs SET ended_at = 'x' WHERE run_id = '{RUN}'")
            parts.append(await _rest(stream))
        finally:
            await engine.dispose()
        return parts

    parts = asyncio.run(scenario())
    heads = [[p.split("\n")[0] for p in group] for group in parts]
    assert heads == [
        ["id: 1", "event: status"],
        ["id: 2"],
        ["id: 3", "id: 4"],
        ["id: 5", "event: status"],
    ]
    assert '"status":"running"' in parts[0][1]
    assert '"status":"finished"' in parts[3][1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_probe_DM_156_sse_by_parts_over_tcp(
    world: World, migrated_db: str, redis_url: str
) -> None:
    """End to end: the image's server, a real session, the stream read over
    TCP -- a line written while the run goes on arrives before the run ends;
    no transaction stays open while the stream does."""
    target = server(world, "velo-a")
    heard(world, target)
    run(world, target, RUN)
    line(world, RUN, header_line())
    superadmin = world.people["super"]

    async def session() -> str:
        client = Redis.from_url(redis_url)
        try:
            return await panel_sessions.create(
                client, superadmin.id, superadmin.telegram_id
            )
        finally:
            await client.aclose()

    token = asyncio.run(session())
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    env.update(
        DATABASE_URL=migrated_db,
        REDIS_URL=redis_url,
        EDITION="core",
        SUPERADMIN_TELEGRAM_ID=str(superadmin.telegram_id),
        DOMAIN_FRONTEND="panel.example.test",
        DOMAIN_API=API_HOST,
        PRIMER_RELEASE=RELEASE,
        PRIMER_COMMIT=COMMIT,
    )
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "--factory",
        "app.main:create_app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-config",
        "logging.json",
    ]
    proc = subprocess.Popen(
        command,
        cwd=BACKEND,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if httpx.get(f"{base}/health", timeout=1).status_code in (200, 503):
                    break
            except httpx.TransportError:
                time.sleep(0.1)
        url = f"{base}/api/v1/streams/servers/{target}/runs/{RUN}"
        got: list[tuple[str, bool]] = []
        in_transaction: list[object] = []
        buffer = ""
        cookies = {"panel_session": token}
        with httpx.stream("GET", url, cookies=cookies, timeout=10) as answer:
            assert answer.status_code == 200
            for part in answer.iter_text():
                buffer += part
                while "\n\n" in buffer:
                    event, buffer = buffer.split("\n\n", 1)
                    head = event.split("\n")[0]
                    ended = query_scalar(
                        world.url,
                        f"SELECT ended_at IS NOT NULL FROM runs WHERE run_id = '{RUN}'",
                    )
                    got.append((head, bool(ended)))
                    in_transaction.append(
                        query_scalar(
                            world.url,
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname = current_database() "
                            "AND state = 'idle in transaction'",
                        )
                    )
                    if head == "id: 1":
                        line(world, RUN, log_line(2))
                    elif head == "id: 2":
                        line(world, RUN, finished_line(3))
                        execute(
                            world.url,
                            f"UPDATE runs SET ended_at = 'x' WHERE run_id = '{RUN}'",
                        )
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    lines = [(head, ended) for head, ended in got if head.startswith("id:")]
    assert lines[:2] == [("id: 1", False), ("id: 2", False)]  # before the run ended
    assert lines[2][0] == "id: 3"
    assert set(in_transaction) == {0}
