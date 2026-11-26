"""A stand-in of comms' sign-in module, by its contract: ``deploy/INTEGRATION.md``
of comms ``v4.2.0`` (``aivis-one/comms@5a193eb``), section 16 (changed by
DM-161).

The answers are LITERALS -- the samples of section 16 as its text gives
them, and its six refusals -- never made by the code that parses them: the
parse is tested against what comms sends, not against itself. A variant of
a sample is an edit of the sample's text, named where it is made; a person's
id goes in by replacing the text ``123456789``. The refusals section 16 gives
no body for -- ``validation``, ``unauthorized``, ``unavailable``,
``not_found`` -- are the common form of section 5 (``app/api/errors.py``
``error_response`` of comms), their messages written here.

The stand-in counts its calls and keeps the bodies it got: the probe "a
foreign ``state`` -- refused without calling comms" reads the count.
"""

import json

import httpx

SAMPLE_ID = "123456789"
"""The person's id of the sample of ``complete``."""

# section 16, `start` -- 200, word for word
START_SAMPLE = """{
  "state": "Yp3kQ9xWv2mN8rT5sL1cA7dF4gH6jK0zB3nM5pR8tU1",
  "authorize_url": "https://oauth.telegram.org/auth?client_id=7000000001&redirect_uri=https%3A%2F%2Fproduct.example.org%2Fauth%2Ftelegram%2Freturn&response_type=code&scope=openid+profile+telegram%3Abot_access&state=Yp3kQ9xWv2mN8rT5sL1cA7dF4gH6jK0zB3nM5pR8tU1&code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM&code_challenge_method=S256",
  "expires_at": "2026-12-01T10:10:00.482913+00:00"
}"""

STATE = "Yp3kQ9xWv2mN8rT5sL1cA7dF4gH6jK0zB3nM5pR8tU1"
"""The sample's ``state``."""

START_EXPIRES = "2026-12-01T10:10:00.482913+00:00"
START_OK = START_SAMPLE.replace(START_EXPIRES, "2099-12-01T10:10:00.482913+00:00")
"""The sample of ``start`` with only the year of ``expires_at`` changed: the
Panel keeps the cookie of the attempt for ``min(expires_at - now, 600 s)``,
so with the sample's 2026 the term would turn on the clock, not on the
code."""

# section 16, `complete` -- 200, word for word
COMPLETE_OK = """{
  "provider": "telegram",
  "subject": "123456789",
  "verified_at": "2026-12-01T10:03:12.654321+00:00",
  "telegram": {
    "id": 123456789,
    "first_name": "Anna",
    "last_name": null,
    "username": "anna",
    "photo_url": "https://t.me/i/userpic/320/anna.jpg",
    "bot_access_granted": true
  }
}"""

# edit: bot_access_granted false -- what Telegram gave on the live sign-in of
# 24.11.2026 (section 16)
COMPLETE_NO_BOT_ACCESS = COMPLETE_OK.replace(
    '"bot_access_granted": true', '"bot_access_granted": false'
)
# edit: every value that may be null is null (section 16)
COMPLETE_NULLS = (
    COMPLETE_OK.replace('"first_name": "Anna"', '"first_name": null')
    .replace('"username": "anna"', '"username": null')
    .replace('"photo_url": "https://t.me/i/userpic/320/anna.jpg"', '"photo_url": null')
)
# edit: verified_at with no fraction -- a fraction that is zero is not written
COMPLETE_WHOLE_SECOND = COMPLETE_OK.replace(
    "2026-12-01T10:03:12.654321+00:00", "2026-12-01T10:03:12+00:00"
)

# Each class, its status (section 5) and its body.
REFUSALS: dict[str, tuple[int, str]] = {
    # section 16, "Refusals of a sign-in" -- word for word
    "login_unknown": (
        404,
        '{"error": {"class": "login_unknown", '
        '"message": "the sign-in is not known; begin it again"}}',
    ),
    "login_expired": (
        410,
        '{"error": {"class": "login_expired", '
        '"message": "the sign-in has expired; begin it again"}}',
    ),
    "login_replayed": (
        409,
        '{"error": {"class": "login_replayed", '
        '"message": "the sign-in was completed already; begin it again"}}',
    ),
    "provider_refused": (
        422,
        '{"error": {"class": "provider_refused", '
        '"message": "Telegram refused the sign-in; begin it again"}}',
    ),
    "provider_unavailable": (
        503,
        '{"error": {"class": "provider_unavailable", '
        '"message": "Telegram could not be asked; begin the sign-in again later"}}',
    ),
    "id_token_invalid": (
        502,
        '{"error": {"class": "id_token_invalid", '
        '"message": "Telegram\'s answer did not prove the person"}}',
    ),
    # not a sample of section 16: the common form of section 5, the
    # messages are this file's
    "validation": (
        422,
        '{"error": {"class": "validation", "message": "the request is invalid", '
        '"fields": [{"loc": ["body", "state"], "message": "invalid"}]}}',
    ),
    # not a sample of section 16 (section 5's form, this file's message)
    "unauthorized": (
        401,
        '{"error": {"class": "unauthorized", "message": "the service token"}}',
    ),
    # not a sample of section 16 (section 5's form, this file's message)
    "unavailable": (
        503,
        '{"error": {"class": "unavailable", "message": "try again"}}',
    ),
    # not a sample of section 16: the option login is off (section 3a), the
    # route unknown (section 5's form, this file's message)
    "not_found": (404, '{"error": {"class": "not_found", "message": "Not Found"}}'),
}
RETRY_AFTER = {REFUSALS["unavailable"][1]: "1"}
"""comms' ``Retry-After`` by the body it goes with (``app/api/errors.py``
``_RETRY_AFTER``: ``unavailable``)."""


class FakeComms:
    """The two routes of section 16; what each answers is set by the test."""

    def __init__(self) -> None:
        self.start = (200, START_OK)
        self.complete = (200, COMPLETE_OK)
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.silent = False
        self.authorization: list[str] = []

    def person(self, telegram_id: int, sample: str = COMPLETE_OK) -> None:
        """``complete`` answers ``sample`` with the person's id put in."""
        self.complete = (200, sample.replace(SAMPLE_ID, str(telegram_id)))

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
            status, text = REFUSALS["not_found"]
        headers = {"content-type": "application/json"}
        if text in RETRY_AFTER:
            headers["retry-after"] = RETRY_AFTER[text]
        return httpx.Response(status, content=text.encode(), headers=headers)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def completes(self) -> int:
        return sum(1 for path, _ in self.calls if path.endswith("/complete"))
