"""Rate limits: a fixed window per source in Redis, ``Retry-After``, closed."""

import asyncio
import logging
import time
from collections.abc import Iterator

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from redis import Redis as SyncRedis

from app.core.ratelimit import KEY_PREFIX, count_in_window, limitable_source, rate_limit
from app.core.redis import make_redis
from app.main import create_app
from tests.conftest import settings_for
from tests.failing import inner_app

PROXY = ("172.18.0.5", 40000)  # the machine's nginx: X-Real-IP is taken
LIMIT = 2
WINDOW_S = 60


def _client(url: str, redis_url: str, window_s: int = WINDOW_S) -> Iterator[TestClient]:
    served = create_app(settings_for(url, redis_url))
    limited = rate_limit("probe", limit=LIMIT, window_s=window_s)

    @inner_app(served).get("/limited", dependencies=[Depends(limited)])
    async def limited_route() -> dict[str, bool]:
        return {"served": True}

    with TestClient(served, client=PROXY) as client:
        yield client


@pytest.fixture
def client(
    test_url: str, redis_url: str, clean_redis: SyncRedis
) -> Iterator[TestClient]:
    yield from _client(test_url, redis_url)


def _from(source: str) -> dict[str, str]:
    return {"X-Real-IP": source}


def _keys(redis: SyncRedis) -> set[str]:
    return {str(key) for key in redis.scan_iter(f"{KEY_PREFIX}:*")}


@pytest.mark.parametrize(
    ("source", "limitable"),
    [
        ("93.184.216.34", True),
        ("2606:4700::1111", True),
        ("127.0.0.1", False),
        ("10.0.0.7", False),
        ("172.18.0.5", False),
        ("169.254.1.1", False),
        ("203.0.113.9", False),
        ("not-an-address", False),
        ("", False),
        (None, False),
    ],
)
def test_only_a_routable_public_address_is_limited(
    source: str | None, limitable: bool
) -> None:
    assert limitable_source(source) is limitable


def test_the_window_is_set_on_the_first_hit_only(
    redis_url: str, clean_redis: SyncRedis
) -> None:
    """Lesson 1 of velo: later hits never slide the window forward."""

    async def hits() -> list[tuple[int, int]]:
        client = make_redis(redis_url)
        try:
            first = await count_in_window(client, "k", 60)
            await client.expire("k", 3)  # the window is ending
            second = await count_in_window(client, "k", 60)
            return [first, second]
        finally:
            await client.aclose()

    (count1, ttl1), (count2, ttl2) = asyncio.run(hits())
    assert (count1, ttl1) == (1, 60)
    assert count2 == 2
    assert 0 <= ttl2 <= 3


def test_under_at_and_over_the_limit(
    client: TestClient, clean_redis: SyncRedis
) -> None:
    for _ in range(LIMIT):
        assert client.get("/limited", headers=_from("93.184.216.34")).status_code == 200
    # The window has 7 s left: Retry-After is what is left, not the window.
    clean_redis.expire(f"{KEY_PREFIX}:probe:93.184.216.34", 7)
    response = client.get("/limited", headers=_from("93.184.216.34"))
    assert response.status_code == 429
    assert response.json()["error"]["class"] == "too_many_requests"
    assert response.headers["retry-after"] in {"6", "7"}
    # Another source has its own window.
    assert client.get("/limited", headers=_from("93.184.216.35")).status_code == 200
    assert _keys(clean_redis) == {
        f"{KEY_PREFIX}:probe:93.184.216.34",
        f"{KEY_PREFIX}:probe:93.184.216.35",
    }


def test_a_window_ending_under_a_second_asks_for_one(
    client: TestClient, clean_redis: SyncRedis
) -> None:
    """Twin EMPTY: the TTL read is 0 -- the client is told one second."""
    key = f"{KEY_PREFIX}:probe:93.184.216.34"
    for _ in range(LIMIT):
        client.get("/limited", headers=_from("93.184.216.34"))
    clean_redis.pexpire(key, 400)
    response = client.get("/limited", headers=_from("93.184.216.34"))
    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"


def test_our_own_infrastructure_is_never_counted(
    client: TestClient, clean_redis: SyncRedis
) -> None:
    """No X-Real-IP: the source is the proxy's private address -- passed, no
    key written. Pair: a public source behind the same proxy is counted."""
    for _ in range(LIMIT + 3):
        assert client.get("/limited").status_code == 200
    assert _keys(clean_redis) == set()
    client.get("/limited", headers=_from("93.184.216.34"))
    assert _keys(clean_redis) == {f"{KEY_PREFIX}:probe:93.184.216.34"}


def test_a_new_window_counts_from_zero(
    test_url: str, redis_url: str, clean_redis: SyncRedis
) -> None:
    for client in _client(test_url, redis_url, window_s=1):
        for _ in range(LIMIT):
            client.get("/limited", headers=_from("93.184.216.34"))
        assert client.get("/limited", headers=_from("93.184.216.34")).status_code == 429
        time.sleep(1.2)
        assert client.get("/limited", headers=_from("93.184.216.34")).status_code == 200


def test_redis_down_closes_the_limit(
    test_url: str, unreachable_redis_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="app.core.ratelimit")
    for client in _client(test_url, unreachable_redis_url):
        response = client.get("/limited", headers=_from("93.184.216.34"))
        assert response.status_code == 503
        assert response.json()["error"]["class"] == "unavailable"
    events = [getattr(r, "event", None) for r in caplog.records]
    assert events == ["ratelimit.unavailable"]


@pytest.mark.parametrize(("limit", "window_s"), [(0, 60), (2, 0)])
def test_a_limit_or_window_under_one_is_refused(limit: int, window_s: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        rate_limit("probe", limit=limit, window_s=window_s)
