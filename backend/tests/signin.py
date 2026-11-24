"""Support of the sign-in tests: the Panel with a stand-in of comms, and
browsers that sign in through it with real sessions (DM-150).

One ``TestClient`` on the API's host over https -- the cookies of sign-in and
of the session are ``Secure`` -- serves every browser: one event loop for the
application's pool of connections (two clients of one application would use
its pooled connections from two loops). A browser is a jar of cookies of its
own, put on the client for its requests. Nothing follows a redirect by
itself: every 302 of sign-in is read as it is.
"""

import uuid
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlsplit

import httpx
from fastapi.testclient import TestClient
from starlette.types import ASGIApp

from app.access.sessions import COOKIE
from app.main import create_app
from tests.comms_fake import STATE, FakeComms
from tests.conftest import (
    API_HOST,
    FRONTEND,
    FRONTEND_HOST,
    SUPERADMIN_ID,
    settings_for,
)

START = "/auth/telegram/start"
RETURN = "/auth/telegram/return"


def signin_app(
    url: str,
    redis_url: str,
    fake: FakeComms,
    superadmin: int = SUPERADMIN_ID,
    *,
    comms: bool = True,
) -> ASGIApp:
    settings = settings_for(url, redis_url, superadmin, comms=comms)
    return create_app(settings, comms_transport=fake.transport)


def client_of(app: ASGIApp) -> TestClient:
    """The client of the browsers, on the API's host.

    Changed by DM-151, on the dispatcher's word 24.11: requests carry the
    frontend's Origin."""
    return TestClient(
        app,
        base_url=f"https://{API_HOST}",
        follow_redirects=False,
        headers=FRONTEND,
    )


def outcome(response: httpx.Response) -> dict[str, str]:
    """Where a navigation of sign-in ends: ``signed_in``, or the fragment of the
    page of refusal (``reason`` and maybe ``telegram_id``)."""
    assert response.status_code == 302, response.text
    location = urlsplit(response.headers["location"])
    assert location.netloc == FRONTEND_HOST, location
    if location.path == "/":
        return {"signed_in": "yes"}
    assert location.path == "/login"
    assert not location.query
    return dict(parse_qsl(location.fragment))


@dataclass
class SignIn:
    client: TestClient
    fake: FakeComms
    jars: dict[str, httpx.Cookies] = field(default_factory=dict)

    def request(
        self, name: str, method: str, path: str, **kwargs: object
    ) -> httpx.Response:
        """A request of the browser ``name``, with its cookies."""
        self.client.cookies = self.jars.setdefault(name, httpx.Cookies())
        response: httpx.Response = self.client.request(method, path, **kwargs)  # type: ignore[arg-type]
        self.jars[name] = httpx.Cookies(self.client.cookies)
        return response

    def start(self, name: str, invite: str | None = None) -> httpx.Response:
        params = {"invite": invite} if invite is not None else {}
        return self.request(name, "GET", START, params=params)

    def back(
        self, name: str, state: str = STATE, code: str = "code-from-telegram"
    ) -> httpx.Response:
        params = {"state": state, "code": code}
        return self.request(name, "GET", RETURN, params=params)

    def login(
        self, name: str, telegram_id: int, invite: str | None = None
    ) -> dict[str, str]:
        self.fake.person(telegram_id)
        started = self.start(name, invite)
        assert started.status_code == 302, started.text
        return outcome(self.back(name))

    def token(self, name: str) -> str | None:
        value: str | None = self.jars.setdefault(name, httpx.Cookies()).get(COOKIE)
        return value

    def me(self, name: str) -> httpx.Response:
        return self.request(name, "GET", "/api/v1/me")

    def user_id(self, name: str) -> uuid.UUID:
        answer = self.me(name)
        assert answer.status_code == 200, answer.text
        return uuid.UUID(answer.json()["user"]["id"])
