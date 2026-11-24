"""Bodies and answers of the access API.

Every body is closed: an unknown field -- ``server_id`` among them, which the
first version does not give (TZ-1 section 3) -- is ``invalid``. Permissions
are the closed list (``Permission``): a value outside it is ``invalid``, a
repeated one too. Answers carry no token and no hash: the token of an invite
is shown once, in the answer that creates it.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.access.permissions import PanelGrantKind, Permission
from app.projects.models import ProjectKind

SLUG = r"^[a-z0-9][a-z0-9-]{0,62}$"
INVITE_TTL_HOURS_DEFAULT = 168
INVITE_TTL_HOURS_MAX = 720


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _distinct(values: list[Permission]) -> list[Permission]:
    if len(set(values)) != len(values):
        raise ValueError("a permission is named twice")
    return values


class ProjectIn(Body):
    slug: str = Field(pattern=SLUG)
    name: str = Field(min_length=1, max_length=200)
    kind: ProjectKind
    repo: str = Field(min_length=1, max_length=300, pattern=r"^\S+$")


class PermissionsIn(Body):
    permissions: list[Permission]

    _distinct = field_validator("permissions")(_distinct)


class AdminIn(PermissionsIn):
    user_id: uuid.UUID


class InviteIn(PermissionsIn):
    is_admin: bool = False
    ttl_hours: int = Field(
        default=INVITE_TTL_HOURS_DEFAULT, ge=1, le=INVITE_TTL_HOURS_MAX
    )


class AcceptIn(Body):
    token: str = Field(min_length=1, max_length=200)


class PanelGrantIn(Body):
    user_id: uuid.UUID
    grant: PanelGrantKind


class Answer(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectOut(Answer):
    id: uuid.UUID
    slug: str
    name: str
    kind: str
    repo: str
    created_at: datetime
    archived_at: datetime | None


class UserOut(Answer):
    id: uuid.UUID
    telegram_id: int
    first_name: str | None
    username: str | None
    created_at: datetime
    deactivated_at: datetime | None


class MemberOut(Answer):
    """A member: ``permissions`` -- what is stored (what a change sets);
    ``effective`` -- what the member may do, ``people`` always for an admin
    (``app.access.permissions.effective``; changed by DM-152)."""

    user: UserOut
    is_admin: bool
    permissions: list[str]
    effective: list[str]
    granted_by: uuid.UUID
    granted_at: datetime


class PermissionsOut(Answer):
    """The closed list of permissions, in the code's order (DM-152): the
    columns of the screens of access, a new permission included."""

    permissions: list[str]


class InviteOut(Answer):
    id: uuid.UUID
    project_id: uuid.UUID
    is_admin: bool
    permissions: list[str]
    created_by: uuid.UUID
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None
    used_by: uuid.UUID | None
    revoked_at: datetime | None


class InviteCreated(Answer):
    invite: InviteOut
    token: str


class AuditOut(Answer):
    id: uuid.UUID
    at: datetime
    actor_kind: str
    actor_id: uuid.UUID | None
    project_id: uuid.UUID | None
    action: str
    object_kind: str
    object_id: str
    result: str
    details: dict[str, object]


class PanelGrantOut(Answer):
    id: uuid.UUID
    user_id: uuid.UUID
    grant: str
    granted_by: uuid.UUID
    granted_at: datetime
    revoked_at: datetime | None


class ProjectAccessOut(Answer):
    project: ProjectOut
    is_admin: bool
    permissions: list[str]


class MeOut(Answer):
    user: UserOut
    is_superadmin: bool
    projects: list[ProjectAccessOut]
    panel_grants: list[str]
