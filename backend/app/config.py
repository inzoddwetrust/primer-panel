"""Settings of the running backend, read from the environment at start.

Every field is required and non-empty; a missing or unknown one stops the
start with its name; ``SUPERADMIN_TELEGRAM_ID`` is a positive Telegram id.
``PRIMER_RELEASE`` and ``PRIMER_COMMIT`` are build arguments the image turns
into its environment (contract 3 rule 19).
``DATABASE_URL`` and ``REDIS_URL`` carry passwords: they are ``SecretStr``,
shown as stars in every repr and error.

There is no module-level instance: ``create_app`` builds one and hands it to
the request through ``app.core.state`` (the owner's decision of 24.11: the
blank's form, no global singletons).
"""

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.editions import EDITIONS


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

    @field_validator("edition")
    @classmethod
    def _known_edition(cls, value: str) -> str:
        if value not in EDITIONS:
            raise ValueError(
                f"EDITION {value!r} is not one of {sorted(EDITIONS)} of this backend"
            )
        return value
