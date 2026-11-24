"""The sign-in module of comms v4.2, as the Panel calls it.

comms vouches for who came (Telegram OpenID Connect with PKCE, its own
attempt of ten minutes); everything else -- sessions, invites, refusing a
stranger, permissions -- is the Panel's (the owner's decision of 24.11). The
form is comms' "form of the sign-in module" (24.11, order 3): two calls on
``COMMS_API_URL`` with ``Authorization: Bearer <COMMS_SERVICE_TOKEN>``.

- ``start`` -- ``{provider: telegram, redirect_uri, bot_access: true}`` ->
  ``{state, authorize_url, expires_at}``;
- ``complete`` -- ``{state, code}`` -> the result: ``provider``, ``subject``
  (the Telegram id as a string), ``verified_at``, ``telegram`` (``id``,
  names, ``bot_access_granted``).

A refusal is ``{"error": {"class", "message"}}``; the Panel reads the class,
never the message. Three outcomes besides the answer, each its exception:
``CommsRefusedError`` (a class of the form), ``CommsUnreachableError`` (timeout, no
connection) and ``CommsOffFormError`` (an answer the form does not describe).

Fields comms may add in a minor version are ignored; the fields the Panel
reads are checked strictly. Times are ISO 8601 with an offset -- with
``Z`` or with ``+00:00`` and fractions of a second: both are taken.

The client is built by ``create_app`` -- one per application -- and closed
in its lifespan. ``transport`` is the seam of the tests: a stand-in of comms
by the form, which lives in the tests only.
"""

from datetime import datetime
from typing import Literal

import httpx
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

START_TIMEOUT_S = 10.0
COMPLETE_TIMEOUT_S = 30.0
"""Not less than 25 s: the form's word for ``complete``."""

COMMS_CLASSES = frozenset(
    {
        "validation",
        "login_unknown",
        "login_expired",
        "login_replayed",
        "provider_refused",
        "provider_unavailable",
        "id_token_invalid",
        "unauthorized",
        "unavailable",
    }
)
"""The classes of refusal of the form, section 6."""


class CommsRefusedError(Exception):
    def __init__(self, error_class: str) -> None:
        super().__init__(error_class)
        self.error_class = error_class


class CommsUnreachableError(Exception):
    pass


class CommsOffFormError(Exception):
    pass


class _Answer(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class LoginStarted(_Answer):
    state: str = Field(min_length=1)
    authorize_url: str = Field(pattern=r"^https://")
    expires_at: AwareDatetime


class TelegramPerson(_Answer):
    id: int = Field(ge=1, le=2**63 - 1, strict=True)
    first_name: str | None
    last_name: str | None
    username: str | None
    photo_url: str | None
    bot_access_granted: bool = Field(strict=True)

    @field_validator("photo_url")
    @classmethod
    def _https(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("https://"):
            raise ValueError("photo_url is https only")
        return value


class LoginResult(_Answer):
    provider: Literal["telegram"]
    subject: str
    verified_at: AwareDatetime
    telegram: TelegramPerson

    @model_validator(mode="after")
    def _subject_is_the_id(self) -> "LoginResult":
        if self.subject != str(self.telegram.id):
            raise ValueError("subject is not telegram.id")
        return self


class _Refusal(_Answer):
    error_class: str = Field(alias="class")


class _RefusalBody(_Answer):
    error: _Refusal


class CommsClient:
    """Calls of the Panel to comms' sign-in module."""

    def __init__(
        self,
        api_url: str,
        service_token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=api_url,
            headers={"Authorization": f"Bearer {service_token}"},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, body: dict[str, object], limit_s: float) -> bytes:
        try:
            response = await self._client.post(path, json=body, timeout=limit_s)
        except httpx.TimeoutException as error:
            raise CommsUnreachableError(f"{path}: no answer in {limit_s} s") from error
        except httpx.TransportError as error:
            raise CommsUnreachableError(f"{path}: {type(error).__name__}") from error
        if response.status_code == 200:
            return response.content
        try:
            refusal = _RefusalBody.model_validate_json(response.content)
        except ValidationError as error:
            raise CommsOffFormError(
                f"{path}: {response.status_code} off the form"
            ) from error
        if refusal.error.error_class not in COMMS_CLASSES:
            raise CommsOffFormError(
                f"{path}: unknown class {refusal.error.error_class!r}"
            )
        raise CommsRefusedError(refusal.error.error_class)

    async def start(self, redirect_uri: str) -> LoginStarted:
        body: dict[str, object] = {
            "provider": "telegram",
            "redirect_uri": redirect_uri,
            "bot_access": True,
        }
        raw = await self._post("/api/v1/login/start", body, START_TIMEOUT_S)
        try:
            return LoginStarted.model_validate_json(raw)
        except ValidationError as error:
            raise CommsOffFormError("start: the answer is off the form") from error

    async def complete(self, state: str, code: str) -> LoginResult:
        body: dict[str, object] = {"state": state, "code": code}
        raw = await self._post("/api/v1/login/complete", body, COMPLETE_TIMEOUT_S)
        try:
            return LoginResult.model_validate_json(raw)
        except ValidationError as error:
            raise CommsOffFormError("complete: the answer is off the form") from error


def seconds_until(moment: datetime, now: datetime) -> int:
    """Whole seconds from ``now`` to ``moment``, never below one."""
    return max(1, int((moment - now).total_seconds()))
