"""The schema of people and access: migrations, the models, the audit."""

import asyncio

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.exc import DBAPIError

import app.access.models
import app.agent.models
import app.audit.models
import app.projects.models  # noqa: F401 -- their tables on Base.metadata
from app.core.database import Base, make_engine, script_head
from tests.conftest import alembic_config, execute, query_scalar

AUDIT_ROW = (
    "INSERT INTO audit (id, actor_kind, action, object_kind, object_id, result) "
    "VALUES (gen_random_uuid(), 'system', 'probe', 'x', 'y', 'ok')"
)


def _differences(url: str) -> list[object]:
    async def run() -> list[object]:
        engine = make_engine(url)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(
                    lambda sync: list(
                        compare_metadata(
                            MigrationContext.configure(sync), Base.metadata
                        )
                    )
                )
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_the_migrated_schema_is_the_models(migrated_db: str) -> None:
    assert script_head() == "0003"  # changed by DM-153: the agent's tables
    assert _differences(migrated_db) == []


def test_the_models_differ_from_a_schema_one_revision_back(migrated_db: str) -> None:
    """The pair: the comparison sees tables -- at 0001 they are all missing."""
    command.downgrade(alembic_config(), "0001")
    assert len(_differences(migrated_db)) >= 7


def test_the_migrations_go_down_and_up_again(migrated_db: str) -> None:
    execute(migrated_db, AUDIT_ROW)
    command.downgrade(alembic_config(), "0001")
    assert query_scalar(migrated_db, "SELECT to_regclass('audit')") is None
    assert query_scalar(migrated_db, "SELECT to_regproc('audit_append_only')") is None
    command.upgrade(alembic_config(), "head")
    assert (
        query_scalar(migrated_db, "SELECT version_num FROM alembic_version") == "0003"
    )
    assert _differences(migrated_db) == []


@pytest.mark.parametrize(
    "change",
    ["UPDATE audit SET result = 'no'", "DELETE FROM audit", "TRUNCATE audit"],
)
def test_the_audit_is_only_added_to(migrated_db: str, change: str) -> None:
    execute(migrated_db, AUDIT_ROW)
    with pytest.raises(DBAPIError, match="audit is append only"):
        execute(migrated_db, change)
    assert query_scalar(migrated_db, "SELECT count(*) FROM audit") == 1
    execute(migrated_db, AUDIT_ROW)  # the pair: adding goes on
    assert query_scalar(migrated_db, "SELECT count(*) FROM audit") == 2


def test_one_active_membership_per_person_and_project(migrated_db: str) -> None:
    execute(
        migrated_db,
        "INSERT INTO users (id, telegram_id) VALUES "
        "('00000000-0000-0000-0000-000000000001', 1)",
        "INSERT INTO projects (id, slug, name, kind, repo) VALUES "
        "('00000000-0000-0000-0000-0000000000a1', 'p', 'P', 'product', 'r')",
    )
    row = (
        "INSERT INTO memberships (id, user_id, project_id, is_admin, granted_by, "
        "revoked_at) VALUES (gen_random_uuid(), "
        "'00000000-0000-0000-0000-000000000001', "
        "'00000000-0000-0000-0000-0000000000a1', false, "
        "'00000000-0000-0000-0000-000000000001', {})"
    )
    execute(migrated_db, row.format("now()"), row.format("now()"), row.format("NULL"))
    with pytest.raises(DBAPIError, match="uq_memberships_active"):
        execute(migrated_db, row.format("NULL"))
