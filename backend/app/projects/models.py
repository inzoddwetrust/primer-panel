"""``Project`` and ``Server`` (PRIMER-PANEL-TZ-1 section 2).

A project is the line of visibility: every row of the Panel's own data
belongs to exactly one project, and a row of a project the person has no
access to is "not found". A project is of one of two kinds: ``product`` --
one product with all its instances -- or ``service`` -- a shared external
service on its own servers; people of product projects have no access to a
service project.

A server is an instance. Here it is the minimal row an access record can
point at (``memberships.server_id``); registration, the box's key and its
state come with DM-152. Nothing is deleted: a project is archived, a server
detached.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProjectKind(StrEnum):
    PRODUCT = "product"
    SERVICE = "service"


class ServerRole(StrEnum):
    """The role of a server, as its passport names it (contract 1)."""

    TEST = "test"
    PROD = "prod"
    PREVIEW = "preview"


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("kind IN ('product', 'service')", name="ck_projects_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))
    repo: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Server(Base):
    __tablename__ = "servers"
    __table_args__ = (
        CheckConstraint("role IN ('test', 'prod', 'preview')", name="ck_servers_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(63), unique=True)
    role: Mapped[str] = mapped_column(String(16))
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    detached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
