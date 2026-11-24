"""The initial revision: no tables yet.

It exists so that a migrated database has a revision: ``/health`` reports
``alembic_head`` and the machine refuses ``null`` for a stack that declares
``migrate`` (conformance ``alembic-head-null``). The tables come with the
Panel's people and access (DM-149).

Revision ID: 0001
Revises:
Create Date: 2026-11-24
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
