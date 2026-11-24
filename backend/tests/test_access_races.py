"""Writers of one project's access at the same time (gate DM-149, section 0 s.8).

Two requests run concurrently against the live Postgres through one ASGI
application. Changed by DM-151, on the dispatcher's word 24.11: requests carry
the frontend's Origin. Every writer takes the project's row first (``ProjectWrite``,
``accept_invite``), so the outcome is one of the serial orders and never a
deadlock (a 500).
"""

import asyncio
import uuid

import httpx

from tests.conftest import FRONTEND, query_scalar
from tests.failing import inner_app
from tests.people import World, access_app

API = "/api/v1"

Call = tuple[dict[str, str], str, str, object]


def _race(url: str, redis_url: str, calls: list[Call]) -> list[int]:
    """Send ``calls`` at once; their status codes, in order."""

    async def run() -> list[int]:
        served = access_app(url, redis_url)
        core = inner_app(served).state.core
        transport = httpx.ASGITransport(app=served)
        try:
            async with httpx.AsyncClient(
                transport=transport, base_url="http://t", headers=FRONTEND
            ) as client:
                answers = await asyncio.gather(
                    *(
                        client.request(method, path, json=body, headers=headers)
                        for headers, method, path, body in calls
                    )
                )
        finally:
            await core.engine.dispose()
            await core.redis.aclose()
        return [answer.status_code for answer in answers]

    return asyncio.run(run())


def _accepts_of(url: str, invite: uuid.UUID) -> object:
    return query_scalar(
        url,
        "SELECT count(*) FROM audit WHERE action = 'invite.accept' "  # noqa: S608
        f"AND object_id = '{invite}'",
    )


def test_two_accepts_of_one_invite(
    world: World, migrated_db: str, redis_url: str
) -> None:
    """One invite, two people at once: one of them joins, the other meets
    "not found"; the invite is accepted once."""
    for round_ in range(5):
        token = world.invite("admin_a", "a", ["seeds"])
        first = world.person(f"p{round_}", 7000000200 + round_)
        second = world.person(f"q{round_}", 7000000300 + round_)
        body = {"token": token}
        codes = _race(
            migrated_db,
            redis_url,
            [
                (first.headers, "POST", API + "/invites/accept", body),
                (second.headers, "POST", API + "/invites/accept", body),
            ],
        )
        assert sorted(codes) == [201, 404], codes
        assert _accepts_of(migrated_db, world.invites[token]) == 1


def test_accept_against_revoke(world: World, migrated_db: str, redis_url: str) -> None:
    for round_ in range(5):
        token = world.invite("admin_a", "a", [])
        joiner = world.person(f"j{round_}", 7000000400 + round_)
        a = world.projects["a"]
        codes = _race(
            migrated_db,
            redis_url,
            [
                (joiner.headers, "POST", API + "/invites/accept", {"token": token}),
                (
                    world.people["admin_a"].headers,
                    "POST",
                    f"{API}/projects/{a}/invites/{world.invites[token]}/revoke",
                    None,
                ),
            ],
        )
        assert codes in ([201, 409], [404, 200]), codes


def test_a_cascade_against_an_accept(
    world: World, migrated_db: str, redis_url: str
) -> None:
    """Whatever comes first, no staff of A holds ``seeds`` after both."""
    a = world.projects["a"]
    admin = world.people["admin_a"]
    path = f"{API}/projects/{a}/members/{admin.id}/permissions"
    for round_ in range(5):
        world.call(
            "super", "PUT", path, {"permissions": ["deploy_test", "seeds"]}, expect=200
        )
        token = world.invite("admin_a", "a", ["seeds", "deploy_test"])
        world.person(f"c{round_}", 7000000500 + round_)
        joiner = world.people[f"c{round_}"]
        codes = _race(
            migrated_db,
            redis_url,
            [
                (joiner.headers, "POST", API + "/invites/accept", {"token": token}),
                (
                    world.people["super"].headers,
                    "PUT",
                    path,
                    {"permissions": ["deploy_test"]},
                ),
            ],
        )
        assert codes == [201, 200], codes
        assert world.permissions_of("a", f"c{round_}") == ["deploy_test"]


def test_two_changes_of_one_member(
    world: World, migrated_db: str, redis_url: str
) -> None:
    staff = world.people["staff_a"].id
    path = f"{API}/projects/{world.projects['a']}/members/{staff}/permissions"
    before = query_scalar(
        migrated_db, "SELECT count(*) FROM audit WHERE action = 'member.permissions'"
    )
    headers = world.people["admin_a"].headers
    codes = _race(
        migrated_db,
        redis_url,
        [
            (headers, "PUT", path, {"permissions": ["seeds"]}),
            (headers, "PUT", path, {"permissions": ["deploy_test", "seeds"]}),
        ],
    )
    assert codes == [200, 200]
    assert world.permissions_of("a", "staff_a") in (["seeds"], ["deploy_test", "seeds"])
    after = query_scalar(
        migrated_db, "SELECT count(*) FROM audit WHERE action = 'member.permissions'"
    )
    assert isinstance(before, int)
    assert after == before + 2
