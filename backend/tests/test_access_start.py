"""The access checks at the start of the Panel (app/access/startup.py)."""

import uuid

import pytest
from fastapi.testclient import TestClient

from tests.conftest import client_for, execute, query_scalar
from tests.people import World, access_app


def _membership_with(url: str, permissions: str) -> None:
    user, project = uuid.uuid4(), uuid.uuid4()
    execute(
        url,
        f"INSERT INTO users (id, telegram_id) VALUES ('{user}', 7000000777)",  # noqa: S608
        "INSERT INTO projects (id, slug, name, kind, repo) "  # noqa: S608
        f"VALUES ('{project}', 'q', 'Q', 'product', 'r')",
        "INSERT INTO memberships (id, user_id, project_id, is_admin, permissions, "  # noqa: S608
        f"granted_by) VALUES ('{uuid.uuid4()}', '{user}', '{project}', false, "
        f"'{permissions}', '{user}')",
    )


def test_a_permission_the_code_does_not_know_refuses_the_start(
    migrated_db: str, redis_url: str
) -> None:
    _membership_with(migrated_db, "{seeds,retired_one}")
    app = access_app(migrated_db, redis_url)
    with pytest.raises(RuntimeError, match="retired_one"), TestClient(app):
        pass


def test_a_permission_unknown_in_an_invite_refuses_the_start(
    world: World, migrated_db: str, redis_url: str
) -> None:
    token = world.invite("admin_a", "a", ["seeds"])
    execute(
        migrated_db,
        "UPDATE invites SET permissions = '{seeds,gone_too}' "  # noqa: S608
        f"WHERE id = '{world.invites[token]}'",
    )
    app = access_app(migrated_db, redis_url)
    with pytest.raises(RuntimeError, match="gone_too"), TestClient(app):
        pass


def test_known_permissions_start(migrated_db: str, redis_url: str) -> None:
    """The pair: the same rows with known permissions start the Panel."""
    _membership_with(migrated_db, "{seeds,people}")
    for client in client_for(access_app(migrated_db, redis_url)):
        assert client.get("/ready").status_code == 200


def test_a_row_read_with_an_unknown_permission_fails_loudly(
    world: World, migrated_db: str
) -> None:
    """The second line: written after the start, the value fails its parse --
    a 500, never passed by."""
    execute(
        migrated_db,
        "UPDATE memberships SET permissions = '{retired_one}' "  # noqa: S608
        f"WHERE user_id = '{world.people['staff_a'].id}'",
    )
    answer = world.client.get(
        f"/api/v1/projects/{world.projects['a']}",
        headers=world.people["staff_a"].headers,
    )
    assert answer.status_code == 500
    assert "retired_one" not in answer.text


@pytest.mark.parametrize(
    "state", ["client_not_migrated", "client_off_head", "client_db_down"]
)
def test_without_a_database_at_the_head_the_checks_are_put_off(
    state: str, request: pytest.FixtureRequest
) -> None:
    """The Panel starts; /ready says why it is not ready (protocol 9.5)."""
    client: TestClient = request.getfixturevalue(state)
    assert client.get("/ready").status_code == 503


def test_a_start_off_the_head_records_no_superadmin(
    client_off_head: TestClient, migrated_db: str
) -> None:
    assert client_off_head.get("/health").status_code == 200
    assert query_scalar(migrated_db, "SELECT count(*) FROM audit") == 0
