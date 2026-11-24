"""Migrations from a clean database.

Changed by DM-148: the blank's table ``app_settings`` and its bootstrap seed
are gone with the blank's sample; the Panel's first revision has no tables
(``0001``), so the tests here keep the head and the repeat, not the table.
"""

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.database import ALEMBIC_INI, script_head
from tests.conftest import alembic_config, query_scalar


def test_migrations_have_one_head() -> None:
    heads = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_heads()
    assert heads == [script_head()]


def test_a_clean_database_migrates_to_the_head_and_again(clean_db: str) -> None:
    command.upgrade(alembic_config(), "head")
    command.upgrade(alembic_config(), "head")
    assert query_scalar(clean_db, "SELECT version_num FROM alembic_version") == (
        script_head()
    )
