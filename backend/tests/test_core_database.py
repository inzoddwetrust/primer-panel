"""ORM sessions of a request: the write transaction and the reader.

Translated from velo (``core/database.py``, BE-83) and aivis (the reader at
``scope="function"``) onto the blank's form: the sessionmaker is the
application's (``app.core.state``), never a module's.
"""

from collections.abc import Iterator
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_reader, get_db_session
from app.core.errors import ErrorClass, PanelError
from app.main import create_app
from tests.conftest import client_for, execute, query_scalar, settings_for
from tests.failing import inner_app

Writer = Annotated[AsyncSession, Depends(get_db_session)]
Reader = Annotated[AsyncSession, Depends(get_db_reader)]

# One row per id; checked at COMMIT, not at the insert: a second insert of
# an id passes the flush and fails the commit.
TABLE = (
    "CREATE TABLE probe_rows (id integer, "
    "CONSTRAINT probe_once UNIQUE (id) DEFERRABLE INITIALLY DEFERRED)"
)


async def _insert(session: AsyncSession, row: int) -> None:
    await session.execute(text("INSERT INTO probe_rows (id) VALUES (:id)"), {"id": row})


@pytest.fixture
def client(migrated_db: str, redis_url: str) -> Iterator[TestClient]:
    execute(migrated_db, TABLE)
    served = create_app(settings_for(migrated_db, redis_url))
    app = inner_app(served)

    @app.post("/write/{row}")
    async def write(row: int, session: Writer) -> dict[str, bool]:
        await _insert(session, row)
        return {"written": True}

    @app.post("/write-twice")
    async def write_twice(session: Writer) -> dict[str, bool]:
        await _insert(session, 5)
        await _insert(session, 5)
        await session.flush()  # the deferred constraint lets it pass here
        return {"written": True}

    @app.post("/write-then-refuse")
    async def write_then_refuse(session: Writer) -> None:
        await _insert(session, 7)
        await session.flush()
        raise PanelError(ErrorClass.CONFLICT, "refused after the write")

    @app.post("/read/{row}")
    async def read(row: int, session: Reader) -> dict[str, bool]:
        await _insert(session, row)
        return {"written": True}

    @app.get("/same")
    async def same(first: Writer, second: Writer) -> dict[str, bool]:
        return {"same": first is second}

    yield from client_for(served)


def _rows(url: str) -> object:
    return query_scalar(url, "SELECT count(*) FROM probe_rows")


def test_a_write_is_committed_when_the_endpoint_returns(
    client: TestClient, migrated_db: str
) -> None:
    assert client.post("/write/1").json() == {"written": True}
    assert _rows(migrated_db) == 1


def test_a_failed_commit_is_an_error_response_not_a_200(
    client: TestClient, migrated_db: str
) -> None:
    """The commit runs before the response is sent: the client hears of it."""
    response = client.post("/write-twice")
    assert response.status_code == 500
    assert response.json()["error"]["class"] == "internal"
    assert _rows(migrated_db) == 0


def test_an_endpoint_that_raises_rolls_its_writes_back(
    client: TestClient, migrated_db: str
) -> None:
    response = client.post("/write-then-refuse")
    assert response.status_code == 409
    assert response.json()["error"]["class"] == "conflict"
    assert _rows(migrated_db) == 0


def test_the_reader_never_commits(client: TestClient, migrated_db: str) -> None:
    """Pair: the same insert through the writer stays, through the reader not."""
    assert client.post("/read/3").status_code == 200
    assert _rows(migrated_db) == 0
    assert client.post("/write/3").status_code == 200
    assert _rows(migrated_db) == 1


def test_a_request_has_one_write_session(client: TestClient) -> None:
    """Twin REPEAT: two parameters asking for it get the same session."""
    assert client.get("/same").json() == {"same": True}
