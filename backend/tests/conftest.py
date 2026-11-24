"""Fixtures: the test database and Redis in a known state, settings, the app.

The suite runs only against a database whose name ends with ``_test`` and a
Redis database numbered ``TEST_REDIS_DB``: the names are the last guard
against a wrong ``DATABASE_URL`` or ``REDIS_URL`` (the live Redis of the stack
is database 0, docker-compose.yml). The suite runs in the Panel's CI only
(primer.yaml declares no ``test``: the owner's decision of 22.11).

Changed by DM-148: the app takes its database and Redis from ``Settings``
(``create_app(settings)``), so the clients are built from settings, not from a
second URL argument; Redis is a fixture of its own, flushed per test.
"""

import asyncio
import os
import socket
from collections.abc import Awaitable, Callable, Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import JsonValue
from redis import ConnectionPool, Redis
from sqlalchemy import text
from sqlalchemy.engine import make_url
from starlette.types import ASGIApp

from app.config import Settings
from app.core.database import ALEMBIC_INI, at_head, make_engine
from app.main import create_app

if TYPE_CHECKING:
    from tests.people import World
    from tests.signin import SignIn
from primer_report import Limits, PrimerReport, Seams

BACKEND = Path(__file__).resolve().parent.parent

RELEASE = "v0.0.0-test"
COMMIT = "0123456789abcdef0123456789abcdef01234567"

# Nothing listens on port 1 of the loopback: a connect is refused at once.
UNREACHABLE_PORT = 1

# Protocol 9.5: how long one check may take, written out here and not
# imported, so a longer timeout in the code fails the bounds of the tests.
PROTOCOL_CHECK_TIMEOUT_S = 2.0

# The Redis database of the suite; the stack's live one is 0.
TEST_REDIS_DB = 15

# The Telegram id the suite's passport names the superadmin by (DM-149).
SUPERADMIN_ID = 7000000001


@pytest.fixture(scope="session")
def test_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.exit("DATABASE_URL is not set", returncode=2)
    name = make_url(url).database or ""
    if not name.endswith("_test"):
        pytest.exit(
            f"refusing to run against database {name!r}: its name must end with _test",
            returncode=2,
        )
    return url


def redis_db_of(url: str) -> int | None:
    """The database number of a Redis URL's path; ``None`` if it names none."""
    path = urlsplit(url).path.strip("/")
    return int(path) if path.isdigit() else None


@pytest.fixture(scope="session")
def redis_url() -> str:
    url = os.environ.get("REDIS_URL", "")
    if not url:
        pytest.exit("REDIS_URL is not set", returncode=2)
    if redis_db_of(url) != TEST_REDIS_DB:
        pytest.exit(
            f"refusing to run against Redis {url!r}: its database must be "
            f"{TEST_REDIS_DB}",
            returncode=2,
        )
    return url


def redis_client(url: str) -> Redis:
    return Redis(connection_pool=ConnectionPool.from_url(url, decode_responses=True))


@pytest.fixture
def clean_redis(redis_url: str) -> Iterator[Redis]:
    """The suite's Redis database, empty."""
    client = redis_client(redis_url)
    client.flushdb()
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def unreachable_redis_url(redis_url: str) -> str:
    return f"redis://127.0.0.1:{UNREACHABLE_PORT}/{TEST_REDIS_DB}"


@pytest.fixture
def silent_redis_url() -> Iterator[str]:
    """A Redis that takes the connection and never answers (as ``silent_url``)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(8)
        port: int = sock.getsockname()[1]
        yield f"redis://127.0.0.1:{port}/{TEST_REDIS_DB}"


@pytest.fixture
def unreachable_url(test_url: str) -> str:
    return (
        make_url(test_url)
        .set(host="127.0.0.1", port=UNREACHABLE_PORT)
        .render_as_string(hide_password=False)
    )


@pytest.fixture
def silent_url(test_url: str) -> Iterator[str]:
    """A database that takes the connection and never says a word.

    The socket listens and is never read: the kernel completes the handshake
    from its backlog, the client sends its startup message and waits for the
    server's greeting, which never comes -- the same on every host.
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(8)
        port: int = sock.getsockname()[1]
        yield (
            make_url(test_url)
            .set(host="127.0.0.1", port=port)
            .render_as_string(hide_password=False)
        )


def execute(url: str, *statements: str) -> None:
    async def run() -> None:
        engine = make_engine(url)
        try:
            async with engine.begin() as conn:
                for statement in statements:
                    await conn.execute(text(statement))
        finally:
            await engine.dispose()

    asyncio.run(run())


def alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["configure_logging"] = False
    return config


@pytest.fixture
def clean_db(test_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """An empty public schema: no tables, no alembic_version."""
    monkeypatch.setenv("DATABASE_URL", test_url)
    execute(test_url, "DROP SCHEMA public CASCADE", "CREATE SCHEMA public")
    return test_url


@pytest.fixture
def migrated_db(clean_db: str) -> str:
    """The schema at the head of the migrations."""
    command.upgrade(alembic_config(), "head")
    return clean_db


def query_scalar(url: str, statement: str) -> object:
    async def run() -> object:
        engine = make_engine(url)
        try:
            async with engine.connect() as conn:
                return await conn.scalar(text(statement))
        finally:
            await engine.dispose()

    return asyncio.run(run())


# The hosts of the suite's passport (DM-150).
FRONTEND_HOST = "panel.example.test"
API_HOST = "api.panel.example.test"
COMMS_URL = "http://comms.test"


def settings_for(
    database_url: str,
    redis_url: str,
    superadmin: int = SUPERADMIN_ID,
    *,
    comms: bool = False,
) -> Settings:
    """Settings of a test app on the given database and Redis.

    Changed by DM-149: the superadmin's Telegram id, ``SUPERADMIN_ID`` unless
    a test names another.

    Changed by DM-150: the hosts of the frontend and the API; with ``comms``,
    the address and the service token of comms' sign-in module."""
    values: dict[str, object] = {
        "EDITION": "core",
        "PRIMER_RELEASE": RELEASE,
        "PRIMER_COMMIT": COMMIT,
        "DATABASE_URL": database_url,
        "REDIS_URL": redis_url,
        "SUPERADMIN_TELEGRAM_ID": superadmin,
        "DOMAIN_FRONTEND": FRONTEND_HOST,
        "DOMAIN_API": API_HOST,
    }
    if comms:
        values["COMMS_API_URL"] = COMMS_URL
        values["COMMS_SERVICE_TOKEN"] = "test-stand-in-comms-service-token"  # noqa: S105
    return Settings.model_validate(values)


@pytest.fixture
def settings(test_url: str, redis_url: str) -> Settings:
    return settings_for(test_url, redis_url)


def client_for(app: ASGIApp) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client_at_head(
    migrated_db: str, redis_url: str, clean_redis: Redis
) -> Iterator[TestClient]:
    yield from client_for(create_app(settings_for(migrated_db, redis_url)))


@pytest.fixture
def client_not_migrated(clean_db: str, redis_url: str) -> Iterator[TestClient]:
    yield from client_for(create_app(settings_for(clean_db, redis_url)))


@pytest.fixture
def client_off_head(migrated_db: str, redis_url: str) -> Iterator[TestClient]:
    """Marked by alembic, at a revision that is not the head."""
    execute(migrated_db, "UPDATE alembic_version SET version_num = '0000'")
    yield from client_for(create_app(settings_for(migrated_db, redis_url)))


@pytest.fixture
def client_redis_down(
    migrated_db: str, unreachable_redis_url: str
) -> Iterator[TestClient]:
    """The database at the head, Redis refusing every connection."""
    yield from client_for(create_app(settings_for(migrated_db, unreachable_redis_url)))


def report_app(
    db: Callable[[], Awaitable[str]] | None = None,
    *,
    head: str | None = None,
    checks: Mapping[str, Callable[[], Awaitable[bool]]] | None = None,
    details: Callable[[], Mapping[str, JsonValue]] | None = None,
) -> ASGIApp:
    """An app with a ``PrimerReport`` of the given checks and nothing else."""
    return PrimerReport(
        service="panel",
        release=RELEASE,
        commit=COMMIT,
        edition="core",
        modules=[],
        limits=Limits(max_upload_mb=1),
        seams=Seams(provides=[], requires_satisfied=True),
        db=db,
        head_checks={"schema": at_head(head)} if head is not None else None,
        checks=checks,
        details=details,
    ).install(FastAPI())


@pytest.fixture
def client_db_down(unreachable_url: str, redis_url: str) -> Iterator[TestClient]:
    yield from client_for(create_app(settings_for(unreachable_url, redis_url)))


@pytest.fixture
def access_client(migrated_db: str, redis_url: str) -> Iterator[TestClient]:
    """The Panel at the head, with the stand-in sign-in of tests/people.py.

    Added by DM-149."""
    from tests.people import access_app

    yield from client_for(access_app(migrated_db, redis_url))


@pytest.fixture
def world(access_client: TestClient, migrated_db: str) -> "World":
    """Projects, admins, staff, invites and grants (tests/people.py).

    Added by DM-149."""
    from tests.people import build_world

    return build_world(access_client, migrated_db)


@pytest.fixture
def signin(migrated_db: str, redis_url: str, clean_redis: Redis) -> Iterator["SignIn"]:
    """The Panel with a stand-in of comms; browsers signing in through it.

    Added by DM-150."""
    from tests.comms_fake import FakeComms
    from tests.signin import SignIn, client_of, signin_app

    fake = FakeComms()
    with client_of(signin_app(migrated_db, redis_url, fake)) as client:
        yield SignIn(client, fake)
