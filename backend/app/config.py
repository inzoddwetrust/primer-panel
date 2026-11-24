"""Settings of the running backend, read from the environment at start.

Every field is required and non-empty; a missing or unknown one stops the
start with its name; ``SUPERADMIN_TELEGRAM_ID`` is a positive Telegram id.
``PRIMER_RELEASE`` and ``PRIMER_COMMIT`` are build arguments the image turns
into its environment (contract 3 rule 19).
``DATABASE_URL`` and ``REDIS_URL`` carry passwords: they are ``SecretStr``,
shown as stars in every repr and error.

``DOMAIN_FRONTEND`` and ``DOMAIN_API`` are the hosts of the passport's
``domains.frontend`` and ``domains.api``: host names, no scheme, port or path.
Sign-in returns the browser to the API's host and sends it on to the
frontend's (DM-150).

``COMMS_API_URL`` and ``COMMS_SERVICE_TOKEN`` -- the sign-in module of comms
-- are optional until comms is a dependency of the Panel (DM-160 makes them
required seams ``from: comms``); without them sign-in answers ``unavailable``.

There is no module-level instance: ``create_app`` builds one and hands it to
the request through ``app.core.state`` (the owner's decision of 24.11: the
blank's form, no global singletons).
"""

import re

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.editions import EDITIONS

_HOST = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
)


class Settings(BaseSettings):
    """The environment of the app container."""

    model_config = SettingsConfigDict(populate_by_name=True, extra="ignore")

    edition: str = Field(validation_alias="EDITION", min_length=1)
    release: str = Field(validation_alias="PRIMER_RELEASE", min_length=1)
    commit: str = Field(validation_alias="PRIMER_COMMIT", min_length=1)
    database_url: SecretStr = Field(validation_alias="DATABASE_URL", min_length=1)
    redis_url: SecretStr = Field(validation_alias="REDIS_URL", min_length=1)
    # The Telegram id of the Panel's one superadmin: a param of the Panel's
    # passport (PRIMER-PANEL-TZ-1 section 3); not a secret.
    superadmin_telegram_id: int = Field(
        validation_alias="SUPERADMIN_TELEGRAM_ID", gt=0, le=2**63 - 1
    )
    domain_frontend: str = Field(validation_alias="DOMAIN_FRONTEND")
    domain_api: str = Field(validation_alias="DOMAIN_API")
    comms_api_url: str | None = Field(default=None, validation_alias="COMMS_API_URL")
    comms_service_token: SecretStr | None = Field(
        default=None, validation_alias="COMMS_SERVICE_TOKEN"
    )

    @field_validator("domain_frontend", "domain_api")
    @classmethod
    def _host_name(cls, value: str) -> str:
        if not _HOST.fullmatch(value):
            raise ValueError(f"{value!r} is not a host name: no scheme, port or path")
        return value

    @field_validator("comms_api_url")
    @classmethod
    def _comms_url(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"https?://[^\s/?#]+/?", value):
            raise ValueError("COMMS_API_URL is the origin of comms' API, http(s)")
        return value

    @property
    def frontend_origin(self) -> str:
        return f"https://{self.domain_frontend}"

    @property
    def api_origin(self) -> str:
        return f"https://{self.domain_api}"

    @property
    def comms_connected(self) -> bool:
        return bool(self.comms_api_url) and self.comms_service_token is not None

    @field_validator("edition")
    @classmethod
    def _known_edition(cls, value: str) -> str:
        if value not in EDITIONS:
            raise ValueError(
                f"EDITION {value!r} is not one of {sorted(EDITIONS)} of this backend"
            )
        return value
