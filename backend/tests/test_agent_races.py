"""Writers of the agent's rows at the same time (gate DM-153, section 0 s.8).

Requests run concurrently against the live Postgres through one ASGI
application, five rounds each: two polls of one server, two registrations by
one token, two batches of the same events, two verdicts of one run. Whatever
comes first, the outcome is one of the serial ones and never a 500.
"""

import asyncio
import json

import httpx
import pytest

from app.agent import queue
from tests.conftest import FRONTEND, execute, query_scalar
from tests.failing import inner_app
from tests.fake_box import AGENT, FakeBox, header_line, log_line
from tests.people import World, access_app
from tests.test_agent import envelope, queue_command, registered, server_of, token_for

Call = tuple[str, str, bytes, dict[str, str]]


@pytest.fixture(autouse=True)
def short_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue, "POLL_WINDOW_S", 0.3)
    monkeypatch.setattr(queue, "POLL_PAUSE_S", 0.05)


def signed(box: FakeBox, method: str, path: str, message: object = None) -> Call:
    body = b"" if message is None else json.dumps(message).encode()
    return method, AGENT + path, body, box.headers(method, AGENT + path, body)


def race(url: str, redis_url: str, calls: list[Call]) -> list[tuple[int, str]]:
    async def run() -> list[tuple[int, str]]:
        served = access_app(url, redis_url)
        core = inner_app(served).state.core
        transport = httpx.ASGITransport(app=served)
        try:
            async with httpx.AsyncClient(
                transport=transport, base_url="http://t", headers=FRONTEND
            ) as client:
                answers = await asyncio.gather(
                    *(
                        client.request(method, path, content=body, headers=headers)
                        for method, path, body, headers in calls
                    )
                )
        finally:
            await core.engine.dispose()
            await core.redis.aclose()
        return [(answer.status_code, answer.text) for answer in answers]

    return asyncio.run(run())


def test_two_polls_of_one_server(
    world: World, migrated_db: str, redis_url: str
) -> None:
    box = registered(world)
    server = server_of(world, box)
    for round_ in range(5):
        queue_command(world, server, "status", who="super")
        queue_command(world, server, "state", who="super")
        answers = race(
            migrated_db,
            redis_url,
            [
                signed(box, "GET", "/commands/next"),
                signed(box, "GET", "/commands/next"),
            ],
        )
        assert sorted(code for code, _ in answers) == [200, 204], (round_, answers)
        taken = query_scalar(
            migrated_db,
            f"SELECT count(*) FROM commands WHERE server_id = '{server}' "  # noqa: S608
            "AND state = 'taken'",
        )
        assert taken == 1
        # the round ends: what is left of it is cancelled
        execute(
            migrated_db,
            f"UPDATE commands SET state = 'canceled' WHERE server_id = '{server}' "  # noqa: S608
            "AND state IN ('taken', 'queued')",
        )


def test_two_registrations_by_one_token(
    world: World, migrated_db: str, redis_url: str
) -> None:
    for round_ in range(5):
        token = token_for(world)
        calls: list[Call] = []
        for name in (f"r{round_}-a", f"r{round_}-b"):
            box = FakeBox(world.client)
            body = json.dumps(
                {
                    "token": token,
                    "server_name": name,
                    "role": "test",
                    "product_repo": "git@github.com:o/a.git",
                    "machine_version": "0.1.8",
                    "box_key_public": box.public,
                }
            ).encode()
            calls.append(
                ("POST", AGENT + "/register", body, {"X-Primer-Protocol": "1"})
            )
        answers = race(migrated_db, redis_url, calls)
        assert sorted(code for code, _ in answers) == [201, 410], answers
        assert '{"code":"token-used"}' in [text for _, text in answers]


def test_the_same_events_and_verdict_twice(
    world: World, migrated_db: str, redis_url: str
) -> None:
    box = registered(world)
    for round_ in range(5):
        run_id = f"2026-11-24T12:00:0{round_}Z-ab1{round_}"
        lines = [header_line(run_id), log_line(2)]
        batch = {"from_seq": 1, "events": lines}
        answers = race(
            migrated_db,
            redis_url,
            [
                signed(box, "POST", f"/runs/{run_id}/events", batch),
                signed(box, "POST", f"/runs/{run_id}/events", batch),
            ],
        )
        assert [code for code, _ in answers] == [200, 200], answers
        sent = json.loads(envelope(box, run_id).model_dump_json(by_alias=True))
        answers = race(
            migrated_db,
            redis_url,
            [
                signed(box, "POST", f"/runs/{run_id}/verdict", sent),
                signed(box, "POST", f"/runs/{run_id}/verdict", sent),
            ],
        )
        assert [code for code, _ in answers] == [204, 204], answers
        assert (
            query_scalar(
                migrated_db,
                f"SELECT count(*) FROM events WHERE run_id = '{run_id}'",  # noqa: S608
            )
            == 2
        )
        assert (
            query_scalar(
                migrated_db,
                f"SELECT count(*) FROM verdicts WHERE run_id = '{run_id}'",  # noqa: S608
            )
            == 1
        )


def test_a_poll_against_the_expiry_of_a_reader(
    world: World, migrated_db: str, redis_url: str
) -> None:
    """The lazy expiry runs in the box's poll and in a person's list at once:
    the old taken command expires once, the next one is given."""
    box = registered(world)
    server = server_of(world, box)
    staff = world.people["staff_a"].headers
    for round_ in range(5):
        old = queue_command(world, server, "status", who="super")
        new = queue_command(world, server, "state", who="super")
        assert isinstance(old, dict) and isinstance(new, dict)
        execute(
            migrated_db,
            "UPDATE commands SET state = 'taken', "  # noqa: S608
            f"taken_at = now() - interval '11 minutes' WHERE id = '{old['id']}'",
        )
        reader: Call = ("GET", f"/api/v1/servers/{server}/commands", b"", staff)
        answers = race(
            migrated_db, redis_url, [signed(box, "GET", "/commands/next"), reader]
        )
        assert answers[0][0] == 200, (round_, answers)
        assert json.loads(answers[0][1])["id"] == new["id"]
        assert answers[1][0] == 200
        assert (
            query_scalar(
                migrated_db,
                f"SELECT state FROM commands WHERE id = '{old['id']}'",  # noqa: S608
            )
            == "expired"
        )
        execute(
            migrated_db,
            f"UPDATE commands SET state = 'canceled' WHERE id = '{new['id']}'",  # noqa: S608
        )
