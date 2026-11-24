"""The one form of every error: ``{"error": {"class", "message"}}``."""

from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.errors import STATUS, ErrorClass, PanelError
from app.main import create_app
from tests.conftest import client_for, settings_for
from tests.failing import inner_app

# The closed list, written out here and not taken from the code: a class the
# code gains or loses must fail this list, not follow it.
CLASSES = {
    "bad_request": 400,
    "invalid": 422,
    "unauthorized": 401,
    "forbidden": 403,
    "not_found": 404,
    "method_not_allowed": 405,
    "conflict": 409,
    "too_many_requests": 429,
    "unavailable": 503,
    "internal": 500,
}
FAILURE_DETAIL = "invented-detail-of-a-failure-0001"


@pytest.fixture
def client(test_url: str, redis_url: str) -> Iterator[TestClient]:
    served = create_app(settings_for(test_url, redis_url))
    app = inner_app(served)

    @app.get("/raise/{name}")
    async def raise_class(name: str) -> None:
        raise PanelError(ErrorClass(name), f"refused as {name}")

    @app.get("/wait")
    async def wait() -> None:
        raise PanelError(ErrorClass.TOO_MANY_REQUESTS, "wait", retry_after_s=17)

    @app.get("/number/{n}")
    async def number(n: int) -> dict[str, int]:
        return {"n": n}

    @app.get("/teapot")
    async def teapot() -> None:
        raise HTTPException(status_code=418, detail=FAILURE_DETAIL)

    @app.get("/fails")
    async def fails() -> None:
        raise RuntimeError(FAILURE_DETAIL)

    yield from client_for(served)


def test_the_classes_are_the_closed_list() -> None:
    assert {c.value: STATUS[c] for c in ErrorClass} == CLASSES


@pytest.mark.parametrize("name", sorted(CLASSES))
def test_a_panel_error_answers_in_the_form(client: TestClient, name: str) -> None:
    response = client.get(f"/raise/{name}")
    assert response.status_code == CLASSES[name]
    assert response.json() == {
        "error": {"class": name, "message": f"refused as {name}"}
    }
    assert "retry-after" not in response.headers


def test_a_429_says_when_to_come_back(client: TestClient) -> None:
    response = client.get("/wait")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "17"
    assert response.json()["error"]["class"] == "too_many_requests"


def test_a_request_off_the_api_is_invalid_by_place_not_value(
    client: TestClient,
) -> None:
    response = client.get("/number/invented-value-0001")
    assert response.status_code == 422
    body = response.json()
    assert list(body) == ["error"]
    assert body["error"]["class"] == "invalid"
    assert "path.n" in body["error"]["message"]
    assert "invented-value-0001" not in response.text


def test_an_unknown_path_is_not_found(client: TestClient) -> None:
    response = client.get("/no/such/path")
    assert response.status_code == 404
    assert response.json() == {"error": {"class": "not_found", "message": "Not found"}}


def test_a_method_the_route_does_not_take(client: TestClient) -> None:
    response = client.post("/wait")
    assert response.status_code == 405
    assert response.json()["error"]["class"] == "method_not_allowed"
    assert response.headers["allow"] == "GET"


def test_a_status_of_no_class_keeps_its_code_and_hides_its_detail(
    client: TestClient,
) -> None:
    response = client.get("/teapot")
    assert response.status_code == 418
    assert response.json() == {
        "error": {"class": "bad_request", "message": "Bad request"}
    }
    assert FAILURE_DETAIL not in response.text


def test_an_unhandled_failure_is_internal_and_says_nothing_of_itself(
    client: TestClient,
) -> None:
    """The 500 is the form with a fixed phrase and the request's id; the
    exception's text stays out (its one log line: tests/test_logs.py)."""
    response = client.get("/fails", headers={"X-Request-ID": "errors-500"})
    assert response.status_code == 500
    assert response.json() == {
        "error": {"class": "internal", "message": "Internal server error"}
    }
    assert FAILURE_DETAIL not in response.text
    assert response.headers["x-request-id"] == "errors-500"


def test_an_error_says_what_went_wrong() -> None:
    """Twin EMPTY: no message, no error; a wait under a second is no wait."""
    with pytest.raises(ValueError, match="message is empty"):
        PanelError(ErrorClass.CONFLICT, "")
    with pytest.raises(ValueError, match="whole second"):
        PanelError(ErrorClass.TOO_MANY_REQUESTS, "wait", retry_after_s=0)
