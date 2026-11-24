"""The protocol of the agent: the box's identity, its state, registration
tokens, commands, runs, events and verdicts (DM-153).

``servers`` gets the box's identity -- the ``box_id`` the Panel minted and the
public half of its key; no server has been registered before this revision
(the table has no rows to fill). One ``taken`` command per server is a
partial unique index.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("servers", sa.Column("box_id", sa.String(64), nullable=False))
    op.add_column("servers", sa.Column("box_key_public", sa.String(64), nullable=False))
    op.create_unique_constraint("servers_box_id_key", "servers", ["box_id"])
    op.create_table(
        "server_states",
        sa.Column(
            "server_id", sa.Uuid(), sa.ForeignKey("servers.id"), primary_key=True
        ),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("measured_at", sa.String(32), nullable=False),
        sa.Column("machine_version", sa.String(64), nullable=False),
        sa.Column("protocol_version", sa.Integer(), nullable=False),
        sa.Column("lock_open_by", postgresql.JSONB(), nullable=False),
        sa.Column("journals_without_verdict", postgresql.JSONB(), nullable=False),
        sa.Column("last_run_id", sa.String(32)),
        sa.Column("snapshot", postgresql.JSONB()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "registration_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("servers.id")),
    )
    op.create_index(
        "ix_registration_tokens_project_id", "registration_tokens", ["project_id"]
    )
    op.create_table(
        "commands",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("servers.id"), nullable=False),
        sa.Column("verb", sa.String(64), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True)),
        sa.Column("run_id", sa.String(32)),
        sa.Column("refusal", sa.String(32)),
        sa.CheckConstraint(
            "state IN ('queued', 'taken', 'done', 'refused', 'expired', 'canceled')",
            name="ck_commands_state",
        ),
    )
    op.create_index("ix_commands_server_id", "commands", ["server_id"])
    op.create_index(
        "uq_commands_one_taken",
        "commands",
        ["server_id"],
        unique=True,
        postgresql_where=sa.text("state = 'taken'"),
    )
    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(32), primary_key=True),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("servers.id"), nullable=False),
        sa.Column("command_id", sa.Uuid(), sa.ForeignKey("commands.id")),
        sa.Column("verb", sa.String(64)),
        sa.Column("actor", postgresql.JSONB()),
        sa.Column("started_at", sa.String(32)),
        sa.Column("ended_at", sa.String(32)),
        sa.Column("outcome", sa.String(16)),
    )
    op.create_index("ix_runs_server_id", "runs", ["server_id"])
    op.create_table(
        "events",
        sa.Column(
            "run_id", sa.String(32), sa.ForeignKey("runs.run_id"), primary_key=True
        ),
        sa.Column("seq", sa.Integer(), primary_key=True),
        sa.Column("at", sa.String(32), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "verdicts",
        sa.Column(
            "run_id", sa.String(32), sa.ForeignKey("runs.run_id"), primary_key=True
        ),
        sa.Column("server_id", sa.Uuid(), sa.ForeignKey("servers.id"), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.Column("envelope_signature", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("signed_on_send", sa.Boolean(), nullable=False),
        sa.Column("report_llm", sa.Text(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_verdicts_server_id", "verdicts", ["server_id"])


def downgrade() -> None:
    op.drop_table("verdicts")
    op.drop_table("events")
    op.drop_table("runs")
    op.drop_table("commands")
    op.drop_table("registration_tokens")
    op.drop_table("server_states")
    op.drop_constraint("servers_box_id_key", "servers")
    op.drop_column("servers", "box_key_public")
    op.drop_column("servers", "box_id")
