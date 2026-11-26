"""Edits of passports at the same time (gate DM-158, R3; section 0 s.8).

Requests run concurrently through one ASGI application on the live Postgres
and the test's primer-ops, ``ROUNDS`` rounds each, three readings of the
passport beside the edits in every round -- every request of a round works on
the Panel's one clone of primer-ops at once:

- two edits of one passport from the same ``base``: exactly one commit, the
  other exactly 409 -- never a merge, never a 503 of ``git`` tripping over
  itself in the clone, never a 500;
- two edits of two servers' passports from the same head: both commits.

The readings answer 200 every time.
"""

import asyncio
import subprocess

import httpx

from tests.conftest import FRONTEND
from tests.failing import inner_app
from tests.ops import PASSPORT, SERVER, OpsSide
from tests.people import World, access_app
from tests.test_passport import message_of, server

Call = tuple[str, str, dict[str, object] | None]
ROUNDS = 10
READINGS = 3


def race(
    world: World, redis_url: str, side: OpsSide, calls: list[Call]
) -> list[tuple[int, str]]:
    async def run() -> list[tuple[int, str]]:
        served = access_app(world.url, redis_url, ops=(side.url, side.places))
        core = inner_app(served).state.core
        headers = {**FRONTEND, **world.people["super"].headers}
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=served),
                base_url="http://t",
                headers=headers,
            ) as client:
                answers = await asyncio.gather(
                    *(
                        client.request(method, path, json=body)
                        for method, path, body in calls
                    )
                )
        finally:
            await core.engine.dispose()
            await core.redis.aclose()
        return [(answer.status_code, answer.text) for answer in answers]

    return asyncio.run(run())


def _edit(server_id: object, base: str, api: str) -> Call:
    path = f"/api/v1/servers/{server_id}/passport/field"
    return "PUT", path, {"base": base, "path": ["domains", "api"], "value": api}


def _readings(*server_ids: object) -> list[Call]:
    return [
        ("GET", f"/api/v1/servers/{server_id}/passport", None)
        for server_id in server_ids
        for _ in range(READINGS)
    ]


def _commits(side: OpsSide) -> int:
    """The commits of primer-ops' branch."""
    return int(
        subprocess.run(
            ["git", "--git-dir", str(side.remote), "rev-list", "--count", "main"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout
    )


def test_two_edits_of_one_passport(
    ops_world: World, ops_side: OpsSide, redis_url: str
) -> None:
    sid = server(ops_world)
    for number in range(ROUNDS):
        base, commits = ops_side.head(), _commits(ops_side)
        answers = race(
            ops_world,
            redis_url,
            ops_side,
            [
                _edit(sid, base, f"a{number}.example"),
                _edit(sid, base, f"b{number}.example"),
                *_readings(sid),
            ],
        )
        edits, readings = answers[:2], answers[2:]
        assert sorted(status for status, _ in edits) == [200, 409], answers
        assert [status for status, _ in readings] == [200] * READINGS, answers
        assert _commits(ops_side) == commits + 1
        won = 0 if edits[0][0] == 200 else 1
        assert f"api: {'ab'[won]}{number}.example" in ops_side.as_box(SERVER)
        assert f"version: {8 + number}" in ops_side.as_box(SERVER)
        assert message_of(ops_side).startswith(f"passport {SERVER}: v{8 + number},")


def test_two_edits_of_two_passports(
    ops_world: World, ops_side: OpsSide, redis_url: str
) -> None:
    ops_side.put("velo-test-2", ops_side.encrypt(PASSPORT.format(name="velo-test-2")))
    first, second = server(ops_world), server(ops_world, name="velo-test-2")
    for number in range(ROUNDS):
        base, commits = ops_side.head(), _commits(ops_side)
        answers = race(
            ops_world,
            redis_url,
            ops_side,
            [
                _edit(first, base, f"a{number}.example"),
                _edit(second, base, f"b{number}.example"),
                *_readings(first, second),
            ],
        )
        assert [status for status, _ in answers] == [200] * len(answers), answers
        assert _commits(ops_side) == commits + 2
        assert f"api: a{number}.example" in ops_side.as_box(SERVER)
        assert f"api: b{number}.example" in ops_side.as_box("velo-test-2")
