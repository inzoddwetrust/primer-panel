"""The ``redis`` check of ``/health``: Redis is a check the stack cannot work
without (protocol 9.1), so a Redis that is down or silent is ``error`` and
the stack ``degraded`` -- in time, with 200."""

import time

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import PROTOCOL_CHECK_TIMEOUT_S, client_for, settings_for


def test_redis_down_is_redis_error_and_degraded(
    client_redis_down: TestClient, client_at_head: TestClient
) -> None:
    """Pair: the same app with Redis up is ``ok``."""
    assert client_at_head.get("/health").json()["checks"]["redis"] == "ok"
    response = client_redis_down.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["checks"] == {"db": "ok", "schema": "ok", "redis": "error"}
    assert body["status"] == "degraded"
    ready = client_redis_down.get("/ready")
    assert (ready.status_code, ready.json()["failing"]) == (503, ["redis"])


def test_a_silent_redis_is_given_up_on_within_the_check(
    migrated_db: str, silent_redis_url: str
) -> None:
    for client in client_for(create_app(settings_for(migrated_db, silent_redis_url))):
        started = time.monotonic()
        body = client.get("/health").json()
        elapsed = time.monotonic() - started
        assert body["checks"]["redis"] == "error"
        assert body["checks"]["db"] == "ok"
        assert elapsed < PROTOCOL_CHECK_TIMEOUT_S + 1.5
