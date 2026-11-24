"""Probes of DM-151: CORS for the Panel's frontend alone, and the refusal of a
changing request from another origin (``app.core.origin``).

Changed by DM-151 FIX: the methods that must be guarded are written out here
(``GUARDED_METHODS``), not taken from the code they check.
"""

import uuid

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.access.login import router as login_router
from app.access.router import router as access_router
from app.core.origin import UNSAFE, guarded
from tests.conftest import FRONTEND_ORIGIN, query_scalar
from tests.people import World

FOREIGN = "https://evil.example.test"
LOOKALIKE = FRONTEND_ORIGIN + ".evil.example.test"  # the frontend's origin as a prefix
REFUSED = {"error": {"class": "forbidden", "message": "Request from another origin"}}

# The changing methods, written out: every one of them must come from the
# frontend (gate DM-151, R3). Not UNSAFE of the code -- the expectation is
# not the code it checks.
GUARDED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _unsafe_routes() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for route in [*access_router.routes, *login_router.routes]:
        assert isinstance(route, APIRoute)
        for method in sorted(route.methods or ()):
            if method in GUARDED_METHODS:
                out.append((method, route.path))
    return out


def _concrete(path: str) -> str:
    """The path with an id of nothing in place of every parameter."""
    for name in ("project_id", "user_id", "invite_id", "grant_id"):
        path = path.replace("{" + name + "}", str(uuid.uuid4()))
    return path


def test_probe_DM_151_cors_only_for_own_frontend(access_client: TestClient) -> None:
    """The frontend's preflight and answers carry CORS with credentials and the
    request id exposed; another site's carry nothing that lets it read."""
    preflight = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    own = access_client.options(
        "/api/v1/projects", headers={**preflight, "Origin": FRONTEND_ORIGIN}
    )
    assert own.status_code == 200
    assert own.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert own.headers["access-control-allow-credentials"] == "true"
    for origin in (FOREIGN, LOOKALIKE):
        other = access_client.options(
            "/api/v1/projects", headers={**preflight, "Origin": origin}
        )
        assert "access-control-allow-origin" not in other.headers, origin
    answer = access_client.get("/api/v1/me", headers={"Origin": FRONTEND_ORIGIN})
    assert answer.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert answer.headers["access-control-allow-credentials"] == "true"
    assert "x-request-id" in answer.headers["access-control-expose-headers"].lower()
    answer = access_client.get("/api/v1/me", headers={"Origin": FOREIGN})
    assert "access-control-allow-origin" not in answer.headers
    assert answer.headers.get("access-control-allow-origin") != "*"


def test_probe_DM_151_unsafe_method_with_foreign_origin_refused(
    world: World, migrated_db: str
) -> None:
    """Every changing route of the API and the sign-out: another origin, a
    lookalike or none at all -- 403 before the route runs, nothing written.
    The pair: the frontend's origin reaches the route."""
    routes = _unsafe_routes()
    assert routes
    assert all(guarded(path) for _, path in routes)
    before = query_scalar(migrated_db, "SELECT count(*) FROM audit")
    superadmin = world.people["super"].headers
    for method, path in routes:
        concrete = _concrete(path)
        for origin in (FOREIGN, LOOKALIKE, None):
            headers = {
                key: value for key, value in superadmin.items() if key != "Origin"
            }
            if origin is not None:
                headers["Origin"] = origin
            client = world.client
            saved = client.headers.pop("Origin", None)
            try:
                answer = client.request(method, concrete, json={}, headers=headers)
            finally:
                if saved is not None:
                    client.headers["Origin"] = saved
            assert answer.status_code == 403, (method, path, origin)
            assert answer.json() == REFUSED, (method, path, origin)
        own = world.client.request(
            method,
            concrete,
            json={},
            headers={**superadmin, "Origin": FRONTEND_ORIGIN},
        )
        assert "Request from another origin" not in own.text, (method, path)
        assert own.status_code in (204, 404, 422), (method, path, own.text)
    # Every guarded method, the ones no route has yet too: the guard answers
    # before routing, so a method without its route is refused, not 405.
    for method in sorted(GUARDED_METHODS):
        for path in ("/api/v1/projects", "/auth/logout"):
            answer = world.client.request(
                method,
                path,
                json={},
                headers={**world.people["super"].headers, "Origin": FOREIGN},
            )
            assert answer.status_code == 403, (method, path)
            assert answer.json() == REFUSED, (method, path)
    # The pair holds no write: the refused requests wrote nothing; the own
    # ones met objects of nothing (404) or bodies off the API (422).
    assert query_scalar(migrated_db, "SELECT count(*) FROM audit") == before


def test_reading_and_navigations_are_not_guarded(world: World) -> None:
    answer = world.client.get(
        "/api/v1/me", headers={**world.people["admin_a"].headers, "Origin": FOREIGN}
    )
    assert answer.status_code == 200
    assert not guarded("/auth/telegram/start")
    assert not guarded("/auth/telegram/return")
    assert not guarded("/health")
    assert not guarded("/agent/v1/heartbeat")


@pytest.mark.parametrize("path", ["/api/v1/projects", "/auth/logout"])
def test_an_empty_origin_is_refused(world: World, path: str) -> None:
    answer = world.client.post(
        path, json={}, headers={**world.people["super"].headers, "Origin": ""}
    )
    assert answer.json() == REFUSED


def test_the_code_guards_exactly_the_changing_methods() -> None:
    assert UNSAFE == GUARDED_METHODS
