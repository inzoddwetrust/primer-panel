"""Sign-in against revoking and deactivating, at the same time (gate DM-150, s.8).

A return of sign-in and a change of access run concurrently against the live
Postgres and Redis. Whatever comes first, the person ends with no access:
a session made at an old epoch is dead at birth; a session made after the
epoch moved, by a decision taken before the revoke committed, names a person
the database gives nothing -- the window the gate named.

Changed by DM-151, on the dispatcher's word 24.11: requests carry the
frontend's Origin.
"""

import asyncio
import uuid
from collections.abc import Awaitable

import httpx

from tests.comms_fake import STATE, FakeComms
from tests.conftest import API_HOST, FRONTEND
from tests.failing import inner_app
from tests.people import World, access_app
from tests.signin import RETURN, START, SignIn, signin_app


async def _close(*apps: object) -> None:
    for app in apps:
        core = inner_app(app).state.core  # type: ignore[arg-type]
        await core.engine.dispose()
        await core.redis.aclose()
        if core.comms is not None:
            await core.comms.aclose()


def _race(
    url: str,
    redis_url: str,
    telegram_id: int,
    browsers: int,
    change: tuple[dict[str, str], str],
) -> list[tuple[int, object]]:
    """``browsers`` returns of sign-in of the person and one change of access,
    at once; then what each browser's ``/me`` answers."""

    async def run() -> list[tuple[int, object]]:
        fake = FakeComms()
        fake.person(telegram_id)
        signed = signin_app(url, redis_url, fake)
        access = access_app(url, redis_url)
        clients = [
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=signed),
                base_url=f"https://{API_HOST}",
                headers=FRONTEND,
            )
            for _ in range(browsers)
        ]
        admin = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=access),
            base_url="http://t",
            headers=FRONTEND,
        )
        try:
            for client in clients:
                await client.get(START)
            headers, path = change
            steps: list[Awaitable[httpx.Response]] = [
                client.get(RETURN, params={"state": STATE, "code": "c"})
                for client in clients
            ]
            steps.append(admin.post(path, headers=headers))
            answers = await asyncio.gather(*steps)
            assert answers[-1].status_code == 200, answers[-1].text
            out: list[tuple[int, object]] = []
            for client in clients:
                me = await client.get("/api/v1/me")
                out.append((me.status_code, me.json()))
            return out
        finally:
            for client in (*clients, admin):
                await client.aclose()
            await _close(signed, access)

    return asyncio.run(run())


def _member(world: World, signin: SignIn, name: str, telegram_id: int) -> uuid.UUID:
    token = world.invite("admin_a", "a", ["deploy_test"])
    assert signin.login(name, telegram_id, invite=token) == {"signed_in": "yes"}
    return signin.user_id(name)


def test_a_sign_in_against_a_revoke(
    world: World, signin: SignIn, migrated_db: str, redis_url: str
) -> None:
    for round_ in range(5):
        telegram_id = 7000000700 + round_
        person = _member(world, signin, f"r{round_}", telegram_id)
        path = f"/api/v1/projects/{world.projects['a']}/members/{person}/revoke"
        [me] = _race(
            migrated_db,
            redis_url,
            telegram_id,
            1,
            (world.people["admin_a"].headers, path),
        )
        status, body = me
        if status == 200:  # the named window: a live session, nothing behind it
            assert isinstance(body, dict)
            assert body["projects"] == []
        else:
            assert status == 401, body
        assert signin.me(f"r{round_}").status_code == 401  # the session before
        path = f"/api/v1/projects/{world.projects['a']}/members"
        members = world.call("super", "GET", path)
        assert str(person) not in str(members)


def test_two_sign_ins_against_a_deactivation(
    world: World, signin: SignIn, migrated_db: str, redis_url: str
) -> None:
    for round_ in range(5):
        telegram_id = 7000000800 + round_
        person = _member(world, signin, f"d{round_}", telegram_id)
        path = f"/api/v1/users/{person}/deactivate"
        answers = _race(
            migrated_db,
            redis_url,
            telegram_id,
            2,
            (world.people["super"].headers, path),
        )
        assert {status for status, _ in answers} <= {401, 403}, answers
        assert signin.me(f"d{round_}").status_code == 401
