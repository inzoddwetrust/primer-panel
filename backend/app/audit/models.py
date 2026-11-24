"""``Audit``: append only (PRIMER-PANEL-TZ-1 section 5).

A row says who did what to which object, with what result, and the details
-- never the value of a secret (no token, no key). Rows are only added: the
code has no path that updates or deletes one, and the database refuses it --
a trigger of migration ``0002`` raises on ``UPDATE``, ``DELETE`` and
``TRUNCATE``.

``at`` is ``clock_timestamp()``: rows of one transaction keep their order.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ActorKind(StrEnum):
    USER = "user"
    BOX = "box"
    SYSTEM = "system"


class Audit(Base):
    __tablename__ = "audit"
    __table_args__ = (
        CheckConstraint(
            "actor_kind IN ('user', 'box', 'system')", name="ck_audit_actor_kind"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )
    actor_kind: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[uuid.UUID | None] = mapped_column()
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    object_kind: Mapped[str] = mapped_column(String(32))
    object_id: Mapped[str] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(16))
    details: Mapped[dict[str, object]] = mapped_column(
        JSONB(), server_default=text("'{}'::jsonb")
    )
