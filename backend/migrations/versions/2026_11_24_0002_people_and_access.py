"""People and access: projects, servers, users, memberships, grants, invites, audit.

PRIMER-PANEL-TZ-1 sections 2, 3 and 5 (DM-149). ``audit`` is append only: a
trigger refuses ``UPDATE``, ``DELETE`` and ``TRUNCATE`` of it. Permissions
are ``text[]`` without a ``CHECK``: the list lives in the code, and a value
the code no longer knows refuses the start of the application.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-24
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY = """
CREATE FUNCTION audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit is append only: % refused', TG_OP;
END;
$$
"""


def _created_at(name: str = "created_at") -> "sa.Column[datetime]":
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.String(63), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("repo", sa.String(300), nullable=False),
        _created_at(),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('product', 'service')", name="ck_projects_kind"),
    )
    op.create_table(
        "servers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False
        ),
        sa.Column("name", sa.String(63), nullable=False, unique=True),
        sa.Column("role", sa.String(16), nullable=False),
        _created_at("registered_at"),
        sa.Column("detached_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "role IN ('test', 'prod', 'preview')", name="ck_servers_role"
        ),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("first_name", sa.String(256)),
        sa.Column("username", sa.String(64)),
        sa.Column(
            "bot_access_granted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        _created_at(),
        sa.Column("deactivated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False
        ),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("servers.id")),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("granted_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        _created_at("granted_at"),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", sa.Uuid(), sa.ForeignKey("users.id")),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_project_id", "memberships", ["project_id"])
    op.create_index(
        "uq_memberships_active",
        "memberships",
        ["user_id", "project_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "panel_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("grant", sa.String(32), nullable=False),
        sa.Column("granted_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        _created_at("granted_at"),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("\"grant\" IN ('support')", name="ck_panel_grants_grant"),
    )
    op.create_index("ix_panel_grants_user_id", "panel_grants", ["user_id"])
    op.create_index(
        "uq_panel_grants_active",
        "panel_grants",
        ["user_id", "grant"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "invites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False
        ),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("servers.id")),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        _created_at(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("used_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_invites_project_id", "invites", ["project_id"])
    op.create_table(
        "audit",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("actor_kind", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("object_kind", sa.String(32), nullable=False),
        sa.Column("object_id", sa.String(64), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_kind IN ('user', 'box', 'system')", name="ck_audit_actor_kind"
        ),
    )
    op.create_index("ix_audit_project_id", "audit", ["project_id"])
    op.execute(APPEND_ONLY)
    op.execute(
        "CREATE TRIGGER audit_no_change BEFORE UPDATE OR DELETE ON audit "
        "FOR EACH ROW EXECUTE FUNCTION audit_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only()"
    )


def downgrade() -> None:
    op.drop_table("audit")
    op.execute("DROP FUNCTION audit_append_only()")
    op.drop_table("invites")
    op.drop_table("panel_grants")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("servers")
    op.drop_table("projects")
