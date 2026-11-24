"""The Panel's copies of what boxes say (PRIMER-PANEL-TZ-1 sections 2 and 4).

- ``ServerState`` -- one row per server, rewritten by every heartbeat: when it
  was heard, its versions, its lock, the journals without a verdict and the
  full form ``box-state.v1`` when the heartbeat carries it;
- ``RegistrationToken`` -- one-time, an hour, the sha256 kept, never the token;
- ``Command`` -- a verb of the machine for one server, put in the queue by a
  person: ``queued`` -> ``taken`` -> ``done`` / ``refused`` / ``expired`` /
  ``canceled``; one ``taken`` per server, held by a partial unique index;
- ``Run``, ``Event``, ``Verdict`` -- the run, the lines of its journal by
  ``(run_id, seq)`` and its verdict in the box's envelope. They outlive the
  box; a verdict whose signature does not hold is kept with ``verified:
  false``.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CommandState(StrEnum):
    QUEUED = "queued"
    TAKEN = "taken"
    DONE = "done"
    REFUSED = "refused"
    EXPIRED = "expired"
    CANCELED = "canceled"


class ServerState(Base):
    __tablename__ = "server_states"

    server_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("servers.id"), primary_key=True
    )
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    measured_at: Mapped[str] = mapped_column(String(32))
    machine_version: Mapped[str] = mapped_column(String(64))
    protocol_version: Mapped[int] = mapped_column(Integer)
    lock_open_by: Mapped[list[str]] = mapped_column(JSONB)
    journals_without_verdict: Mapped[list[str]] = mapped_column(JSONB)
    last_run_id: Mapped[str | None] = mapped_column(String(32))
    snapshot: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RegistrationToken(Base):
    __tablename__ = "registration_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    server_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("servers.id"))


class Command(Base):
    __tablename__ = "commands"
    __table_args__ = (
        CheckConstraint(
            "state IN ('queued', 'taken', 'done', 'refused', 'expired', 'canceled')",
            name="ck_commands_state",
        ),
        Index(
            "uq_commands_one_taken",
            "server_id",
            unique=True,
            postgresql_where=text("state = 'taken'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id"), index=True)
    verb: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict[str, object]] = mapped_column(JSONB)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16))
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[str | None] = mapped_column(String(32))
    refusal: Mapped[str | None] = mapped_column(String(32))


class Run(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id"), index=True)
    command_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("commands.id"))
    verb: Mapped[str | None] = mapped_column(String(64))
    actor: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    started_at: Mapped[str | None] = mapped_column(String(32))
    ended_at: Mapped[str | None] = mapped_column(String(32))
    outcome: Mapped[str | None] = mapped_column(String(16))


class Event(Base):
    __tablename__ = "events"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[str] = mapped_column(String(32))
    body: Mapped[dict[str, object]] = mapped_column(JSONB)


class Verdict(Base):
    __tablename__ = "verdicts"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), primary_key=True)
    server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("servers.id"), index=True)
    body: Mapped[dict[str, object]] = mapped_column(JSONB)
    envelope_signature: Mapped[str] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean)
    signed_on_send: Mapped[bool] = mapped_column(Boolean)
    report_llm: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
