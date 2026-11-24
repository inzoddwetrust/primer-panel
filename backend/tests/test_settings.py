"""The backend refuses to start on a missing or unknown environment.

Changed by DM-148: ``DATABASE_URL`` and ``REDIS_URL`` are fields of the
settings now -- required, non-empty, and never shown.

Changed by DM-149: ``SUPERADMIN_TELEGRAM_ID`` -- required, a positive integer.
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
    ],
)
def test_an_unknown_or_empty_value_names_its_variable(name: str, value: str) -> None:
    with pytest.raises(ValidationError, match=name):
        Settings.model_validate({**GOOD, name: value})


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
