"""A stand-in of comms' sign-in module, by its form (comms v4.2, 24.11).

The answers are LITERALS -- the samples of appendix A of the form and one
answer per class of refusal of its section 6 -- never made by the code that
parses them: the parse is tested against what comms sends, not against
itself. Times come in both forms the form names: with ``Z`` (the samples) and
with an offset and fractions of a second (comms' word of 24.11).

The stand-in counts its calls and keeps the bodies it got: the probe "a
foreign ``state`` -- refused without calling comms" reads the count.
"""

import json

import httpx

STATE = "Yp3kQ9xWv2mN8rT5sL1cA7dF4gH6jK0zB3nM5pR8tU1"
AUTHORIZE = (
    "https://oauth.telegram.org/auth?client_id=7000000001&redirect_uri=https%3A%2F%2F"
    "primer.team%2Fauth%2Ftelegram%2Freturn&response_type=code&scope=openid+profile+"
    "telegram%3Abot_access&state=Yp3kQ9xWv2mN8rT5sL1cA7dF4gH6jK0zB3nM5pR8tU1"
    "&code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    "&code_challenge_method=S256"
)

# appendix A, start, 200 -- the term far ahead, so the cookie lives
START_OK = (
    '{"state":"' + STATE + '","authorize_url":"' + AUTHORIZE + '",'
    '"expires_at":"2099-12-01T10:10:00Z"}'
)
START_OK_OFFSET = (
    '{"state":"' + STATE + '","authorize_url":"' + AUTHORIZE + '",'
    '"expires_at":"2099-12-01T10:10:00.123456+00:00"}'
)

# appendix A, complete, 200 -- the person's id in place of 123456789
COMPLETE_OK = (
    '{"provider":"telegram","subject":"{ID}","verified_at":"2026-12-01T10:03:12Z",'
    '"telegram":{"id":{ID},"first_name":"Анна","last_name":null,"username":"anna",'
    '"photo_url":null,"bot_access_granted":true}}'
)
COMPLETE_OK_OFFSET = (
    '{"provider":"telegram","subject":"{ID}",'
    '"verified_at":"2026-12-01T10:03:12.123456+00:00",'
    '"telegram":{"id":{ID},"first_name":"Анна","last_name":null,"username":"anna",'
    '"photo_url":null,"bot_access_granted":false},"added_in_a_minor":"ignored"}'
)

# section 6 of the form: every class, its status and a body of the form
REFUSALS: dict[str, tuple[int, str]] = {
    "validation": (
        422,
        '{"error":{"class":"validation","message":"body is not valid"}}',
    ),
    "login_unknown": (
        404,
        '{"error":{"class":"login_unknown","message":"no such login"}}',
    ),
    "login_expired": (
        410,
        '{"error":{"class":"login_expired",'
        '"message":"this login expired: start a new one"}}',
    ),
    "login_replayed": (
        409,
        '{"error":{"class":"login_replayed",'
        '"message":"this login was already completed"}}',
    ),
    "provider_refused": (
        422,
        '{"error":{"class":"provider_refused","message":"telegram refused the code"}}',
    ),
    "provider_unavailable": (
        503,
        '{"error":{"class":"provider_unavailable",'
        '"message":"telegram did not answer"}}',
    ),
    "id_token_invalid": (
        502,
        '{"error":{"class":"id_token_invalid","message":"the id_token did not pass"}}',
    ),
    "unauthorized": (
        401,
        '{"error":{"class":"unauthorized","message":"service token"}}',
    ),
    "unavailable": (503, '{"error":{"class":"unavailable","message":"try again"}}'),
}


class FakeComms:
    """Two routes of the form; what each answers is set by the test."""

    def __init__(self) -> None:
        self.start = (200, START_OK)
        self.complete = (200, COMPLETE_OK.replace("{ID}", "123456789"))
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.silent = False
        self.authorization: list[str] = []

    def person(self, telegram_id: int, template: str = COMPLETE_OK) -> None:
        self.complete = (200, template.replace("{ID}", str(telegram_id)))

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.calls.append((request.url.path, body))
        self.authorization.append(request.headers.get("authorization", ""))
        if self.silent:
            raise httpx.ReadTimeout("comms is silent", request=request)
        if request.url.path == "/api/v1/login/start":
            status, text = self.start
        elif request.url.path == "/api/v1/login/complete":
            status, text = self.complete
        else:
            status, text = 404, '{"error":{"class":"not_found","message":"no route"}}'
        return httpx.Response(
            status, content=text.encode(), headers={"content-type": "application/json"}
        )

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def completes(self) -> int:
        return sum(1 for path, _ in self.calls if path.endswith("/complete"))
