"""The backend refuses to start on a missing or unknown environment.

Changed by DM-148: ``DATABASE_URL`` and ``REDIS_URL`` are fields of the
settings now -- required, non-empty, and never shown.

Changed by DM-149: ``SUPERADMIN_TELEGRAM_ID`` -- required, a positive integer.

Changed by DM-150: ``DOMAIN_FRONTEND`` and ``DOMAIN_API`` -- required host
names; ``COMMS_API_URL`` and ``COMMS_SERVICE_TOKEN`` -- optional until DM-160.

Changed by DM-158: ``OPS_REPO`` -- required, ``ssh.github.com:443`` or
``file://`` only.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings
from tests.conftest import COMMIT, RELEASE

DATABASE = "postgresql+asyncpg://panel:invented-password-0001@db:5432/panel"
REDIS = "redis://:invented-password-0002@redis:6379/0"
GOOD = {
    "EDITION": "core",
    "PRIMER_RELEASE": RELEASE,
    "PRIMER_COMMIT": COMMIT,
    "DATABASE_URL": DATABASE,
    "REDIS_URL": REDIS,
    "SUPERADMIN_TELEGRAM_ID": "7000000001",
    "DOMAIN_FRONTEND": "primer.team",
    "DOMAIN_API": "api.primer.team",
    "OPS_REPO": "ssh://git@ssh.github.com:443/inzoddwetrust/primer-ops.git",
}


def test_the_environment_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in GOOD.items():
        monkeypatch.setenv(name, value)
    settings = Settings()
    assert (settings.edition, settings.release, settings.commit) == (
        "core",
        RELEASE,
        COMMIT,
    )
    assert settings.database_url.get_secret_value() == DATABASE
    assert settings.redis_url.get_secret_value() == REDIS
    assert settings.superadmin_telegram_id == 7000000001
    assert settings.frontend_origin == "https://primer.team"
    assert settings.api_origin == "https://api.primer.team"
    assert settings.comms_connected is False


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EDITION", "school"),
        ("EDITION", ""),
        ("PRIMER_RELEASE", ""),
        ("PRIMER_COMMIT", ""),
        ("DATABASE_URL", ""),
        ("REDIS_URL", ""),
        ("SUPERADMIN_TELEGRAM_ID", ""),
        ("SUPERADMIN_TELEGRAM_ID", "0"),
        ("SUPERADMIN_TELEGRAM_ID", "-5"),
        ("SUPERADMIN_TELEGRAM_ID", "abc"),
        ("DOMAIN_FRONTEND", "https://primer.team"),
        ("DOMAIN_FRONTEND", "primer.team/x"),
        ("DOMAIN_API", "api.primer.team:443"),
        ("DOMAIN_API", "localhost"),
        ("DOMAIN_API", "API.primer.team"),
        ("COMMS_API_URL", "comms:8000"),
        ("OPS_REPO", ""),
        ("OPS_REPO", "git@github.com:inzoddwetrust/primer-ops.git"),
        ("OPS_REPO", "ssh://git@github.com/inzoddwetrust/primer-ops.git"),
        ("OPS_REPO", "ssh://git@ssh.github.com:22/inzoddwetrust/primer-ops.git"),
        ("OPS_REPO", "ssh://git@gitlab.com:443/o/primer-ops.git"),
        ("OPS_REPO", "https://github.com/inzoddwetrust/primer-ops.git"),
    ],
)
def test_an_unknown_or_empty_value_names_its_variable(name: str, value: str) -> None:
    with pytest.raises(ValidationError, match=name):
        Settings.model_validate({**GOOD, name: value})


def test_comms_is_connected_with_both_its_values() -> None:
    """Changed by DM-212: one of the two is a refusal of the start, not a
    sign-in quietly off -- neither is comms not connected."""
    both = {
        **GOOD,
        "COMMS_API_URL": "http://comms-comms-app:8000",
        "COMMS_SERVICE_TOKEN": "invented-service-token-0001",
    }
    assert Settings.model_validate(both).comms_connected is True
    assert Settings.model_validate(GOOD).comms_connected is False
    for one in ("COMMS_API_URL", "COMMS_SERVICE_TOKEN"):
        with pytest.raises(ValidationError, match="both or neither"):
            Settings.model_validate({**GOOD, one: both[one]})


@pytest.mark.parametrize("name", sorted(GOOD))
def test_a_missing_variable_is_named(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    for other, value in GOOD.items():
        if other == name:
            monkeypatch.delenv(other, raising=False)
        else:
            monkeypatch.setenv(other, value)
    with pytest.raises(ValidationError, match=name):
        Settings()


def test_the_urls_are_never_shown() -> None:
    """Both URLs carry a password: neither repr nor an error shows them."""
    settings = Settings.model_validate(GOOD)
    shown = f"{settings!r} {settings}"
    assert "invented-password-0001" not in shown
    assert "invented-password-0002" not in shown
    try:
        Settings.model_validate({**GOOD, "EDITION": "school"})
    except ValidationError as error:
        assert "invented-password" not in str(error)
    else:
        raise AssertionError("an unknown edition was taken")
