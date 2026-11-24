"""The database: its URL, the engine, ORM sessions, what ``/health`` measures.

ENGINE. ``make_engine`` builds a pooled engine; ``create_app`` makes one per
application and ``/health`` reads through the same one. A connect attempt
gives up no later than a health check does; the values of a statement are kept
out of the text of its errors (they may be people's data, protocol 9.4).

SESSIONS (velo ``core/database.py``, aivis for the reader). Two dependencies,
each on the sessionmaker of the application's state:

- ``get_db_session`` -- read-write: the transaction is committed when the
  endpoint returns, BEFORE the first byte of the response is sent, and rolled
  back when it raises. A failed commit reaches the client as an error
  response, never as a 200 whose writes were rolled back. That is why the
  transaction sits behind ``Depends(..., scope="function")``: a yield
  dependency of the default scope would commit after the response was sent.
  Every ``get_db_session`` of a request is one session (one cache key).
- ``get_db_reader`` -- read-only: always rolled back, also before the response,
  so the connection is back in the pool before the first byte.

A dependency built on a session must not use it after the endpoint returns:
by then it is committed and closed. The same holds for background tasks and
a streaming body.

MIGRATIONS read ``DATABASE_URL`` themselves (``database_url``): alembic runs
in its own process (``migrate`` of primer.yaml), not through the app.
"""

import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Annotated

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.state import Core, get_core
from primer_report import CHECK_TIMEOUT_S

ALEMBIC_INI = Path(__file__).resolve().parent.parent.parent / "alembic.ini"

# A connect attempt gives up no later than a health check does.
CONNECT_TIMEOUT_S = CHECK_TIMEOUT_S

# The pool of one process. The Panel is one uvicorn process; long requests
# (agents, the browser) are to come, so the pool is not NullPool.
POOL_SIZE = 5
POOL_OVERFLOW = 10
POOL_RECYCLE_S = 1800


class Base(DeclarativeBase):
    """Base class of every ORM model of the Panel."""


def database_url() -> str:
    """``DATABASE_URL`` of the environment, for alembic; absent or empty stops
    with its name. The app takes it from ``Settings``."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def make_engine(url: str) -> AsyncEngine:
    """A pooled engine that fails fast on connect and hides statement values."""
    return create_async_engine(
        url,
        pool_size=POOL_SIZE,
        max_overflow=POOL_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=POOL_RECYCLE_S,
        hide_parameters=True,
        connect_args={"timeout": CONNECT_TIMEOUT_S},
    )


def make_sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """The session factory of ``engine``: objects stay readable after commit."""
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def _transaction(
    core: Annotated[Core, Depends(get_core)],
) -> AsyncIterator[AsyncSession]:
    """The request's write transaction: commit on return, rollback on error.

    Consumed only through ``get_db_session``, which declares it with
    ``scope="function"``; nothing else depends on it: a second declaration
    with another scope is another cache key, a second session in the request.
    """
    session = core.sessions()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db_session(
    session: Annotated[AsyncSession, Depends(_transaction, scope="function")],
) -> AsyncSession:
    """The read-write session of the request (module docstring)."""
    return session


async def _read_transaction(
    core: Annotated[Core, Depends(get_core)],
) -> AsyncIterator[AsyncSession]:
    """The request's read-only session: always rolled back.

    Consumed only through ``get_db_reader`` (``scope="function"``, as above).
    """
    session = core.sessions()
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()


async def get_db_reader(
    session: Annotated[AsyncSession, Depends(_read_transaction, scope="function")],
) -> AsyncSession:
    """The read-only session of the request (module docstring)."""
    return session


def script_head() -> str:
    """The single head revision of the migrations shipped with this code."""
    config = Config(str(ALEMBIC_INI))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("the migrations have no head revision")
    return head


async def read_revision(engine: AsyncEngine) -> str:
    """The database's revision, in one query -- the ``db`` check of ``/health``.

    No ``alembic_version`` (a clean database) and an empty one both raise:
    a revision that cannot be read is ``db: error`` (protocol 9.5).
    """
    async with engine.connect() as conn:
        revision = await conn.scalar(text("SELECT version_num FROM alembic_version"))
    if not isinstance(revision, str) or not revision:
        raise LookupError("alembic_version holds no revision")
    return revision


def at_head(head: str) -> Callable[[str], bool]:
    """The ``schema`` check: the revision read is ``head``."""

    def judge(revision: str) -> bool:
        return revision == head

    return judge
