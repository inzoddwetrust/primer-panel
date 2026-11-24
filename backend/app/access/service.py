"""The rules of access, held by code (PRIMER-PANEL-TZ-1 section 3).

1. An admin of a project is appointed by the superadmin only; the
   superadmin turns on the admin's permissions.
2. An admin -- and staff holding ``people`` -- give staff of the project
   only permissions they hold themselves; admins and their permissions are
   the superadmin's alone.
3. A permission taken from an admin -- explicitly, or by revoking the admin
   -- is taken from every staff member of the project and from every unused
   invite of the project that makes staff, even if another admin still holds
   it (the owner's rule as written, gate DM-149 R7). One transaction, an
   audit row for every person and invite touched.
4. An invite is used once, before its time ends; an invite making an admin
   is the superadmin's alone.
5. Nothing is deleted: access is revoked, an invite used or revoked.

Every write of a project's access runs under the lock of the project's row
(``app.access.rules.ProjectWrite``); accepting an invite takes the same lock
first. A Panel grant takes the lock of the person's row.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.actor import Actor
from app.access.models import Invite, Membership, PanelGrant, User
from app.access.permissions import (
    PanelGrantKind,
    Permission,
    canonical,
    effective,
    parse_permissions,
)
from app.access.rules import NOT_FOUND, Scope
from app.audit.models import ActorKind
from app.audit.service import record
from app.core.errors import ErrorClass, PanelError
from app.projects.models import Project

TOKEN_BYTES = 32


def token_hash(token: str) -> str:
    """The form an invite's token is kept in: sha256, hex."""
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _audit(
    scope: Scope,
    action: str,
    object_kind: str,
    object_id: uuid.UUID | str,
    details: dict[str, object] | None = None,
) -> None:
    record(
        scope.session,
        actor_kind=ActorKind.USER,
        actor_id=scope.actor.user_id,
        project_id=scope.project.id,
        action=action,
        object_kind=object_kind,
        object_id=str(object_id),
        details=details,
    )


def _refuse_beyond_own(scope: Scope, given: frozenset[Permission]) -> None:
    """Rule 2: what is given is what the giver holds (the superadmin -- all)."""
    beyond = given - scope.permissions
    if beyond and not scope.actor.is_superadmin:
        names = ", ".join(canonical(beyond))
        raise PanelError(
            ErrorClass.FORBIDDEN, f"Only permissions you hold can be given: {names}"
        )


async def _active_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None or user.deactivated_at is not None:
        raise PanelError(ErrorClass.NOT_FOUND, NOT_FOUND)
    return user


async def _member(scope: Scope, user_id: uuid.UUID) -> Membership:
    membership = await scope.session.scalar(
        select(Membership).where(
            Membership.project_id == scope.project.id,
            Membership.user_id == user_id,
            Membership.revoked_at.is_(None),
        )
    )
    if membership is None:
        raise PanelError(ErrorClass.NOT_FOUND, NOT_FOUND)
    return membership


async def cascade(
    scope: Scope, removed: frozenset[Permission], admin: uuid.UUID
) -> None:
    """Rule 3: take ``removed`` from every staff member of the project and from
    every unused invite making staff; an audit row for each one touched."""
    if not removed:
        return
    staff = await scope.session.scalars(
        select(Membership).where(
            Membership.project_id == scope.project.id,
            Membership.is_admin.is_(False),
            Membership.revoked_at.is_(None),
        )
    )
    for member in staff:
        held = parse_permissions(member.permissions)
        taken = held & removed
        if not taken:
            continue
        member.permissions = canonical(held - removed)
        _audit(
            scope,
            "member.permissions",
            "membership",
            member.id,
            {
                "user_id": str(member.user_id),
                "removed": canonical(taken),
                "from_admin": str(admin),
            },
        )
    invites = await scope.session.scalars(
        select(Invite).where(
            Invite.project_id == scope.project.id,
            Invite.is_admin.is_(False),
            Invite.used_at.is_(None),
            Invite.revoked_at.is_(None),
        )
    )
    for invite in invites:
        held = parse_permissions(invite.permissions)
        taken = held & removed
        if not taken:
            continue
        invite.permissions = canonical(held - removed)
        _audit(
            scope,
            "invite.permissions",
            "invite",
            invite.id,
            {"removed": canonical(taken), "from_admin": str(admin)},
        )


async def create_project(
    session: AsyncSession, actor: Actor, slug: str, name: str, kind: str, repo: str
) -> Project:
    taken = await session.scalar(select(Project.id).where(Project.slug == slug))
    if taken is not None:
        raise PanelError(ErrorClass.CONFLICT, f"The project {slug} exists")
    project = Project(slug=slug, name=name, kind=kind, repo=repo)
    session.add(project)
    await session.flush()
    record(
        session,
        actor_kind=ActorKind.USER,
        actor_id=actor.user_id,
        project_id=project.id,
        action="project.create",
        object_kind="project",
        object_id=str(project.id),
        details={"slug": slug, "kind": kind},
    )
    return project


def archive_project(scope: Scope) -> Project:
    scope.project.archived_at = _now()
    _audit(scope, "project.archive", "project", scope.project.id)
    return scope.project


async def appoint_admin(
    scope: Scope, user_id: uuid.UUID, permissions: list[Permission]
) -> Membership:
    """Rule 1: the superadmin makes a person an admin of the project."""
    await _active_user(scope.session, user_id)
    exists = await scope.session.scalar(
        select(Membership.id).where(
            Membership.project_id == scope.project.id,
            Membership.user_id == user_id,
            Membership.revoked_at.is_(None),
        )
    )
    if exists is not None:
        raise PanelError(ErrorClass.CONFLICT, "The person has access to the project")
    membership = Membership(
        user_id=user_id,
        project_id=scope.project.id,
        is_admin=True,
        permissions=canonical(permissions),
        granted_by=scope.actor.user_id,
    )
    scope.session.add(membership)
    await scope.session.flush()
    _audit(
        scope,
        "member.admin",
        "membership",
        membership.id,
        {"user_id": str(user_id), "permissions": canonical(permissions)},
    )
    return membership


async def set_permissions(
    scope: Scope, user_id: uuid.UUID, permissions: list[Permission]
) -> Membership:
    """Rules 1-3: the full set of a member's permissions."""
    member = await _member(scope, user_id)
    if member.is_admin and not scope.actor.is_superadmin:
        raise PanelError(ErrorClass.FORBIDDEN, "Only the superadmin changes an admin")
    old = parse_permissions(member.permissions)
    new = frozenset(permissions)
    if new == old:
        return member
    _refuse_beyond_own(scope, new - old)
    member.permissions = canonical(new)
    _audit(
        scope,
        "member.permissions",
        "membership",
        member.id,
        {
            "user_id": str(user_id),
            "added": canonical(new - old),
            "removed": canonical(old - new),
        },
    )
    if member.is_admin:
        await cascade(scope, old - new, user_id)
    return member


async def revoke_member(scope: Scope, user_id: uuid.UUID) -> Membership:
    """Revoke a member's access; an admin's -- the superadmin's alone, and his
    permissions go from the staff with him (rule 3)."""
    member = await _member(scope, user_id)
    if member.is_admin and not scope.actor.is_superadmin:
        raise PanelError(ErrorClass.FORBIDDEN, "Only the superadmin revokes an admin")
    member.revoked_at = _now()
    member.revoked_by = scope.actor.user_id
    _audit(scope, "member.revoke", "membership", member.id, {"user_id": str(user_id)})
    if member.is_admin:
        held = effective(member.permissions, is_admin=True, is_superadmin=False)
        await cascade(scope, held, user_id)
    return member


async def create_invite(
    scope: Scope, *, is_admin: bool, permissions: list[Permission], ttl_hours: int
) -> tuple[Invite, str]:
    """Rule 4: a one-time invite with its time; the token is returned once."""
    if is_admin and not scope.actor.is_superadmin:
        raise PanelError(ErrorClass.FORBIDDEN, "Only the superadmin invites an admin")
    _refuse_beyond_own(scope, frozenset(permissions))
    token = secrets.token_urlsafe(TOKEN_BYTES)
    invite = Invite(
        token_hash=token_hash(token),
        project_id=scope.project.id,
        is_admin=is_admin,
        permissions=canonical(permissions),
        created_by=scope.actor.user_id,
        expires_at=_now() + timedelta(hours=ttl_hours),
    )
    scope.session.add(invite)
    await scope.session.flush()
    _audit(
        scope,
        "invite.create",
        "invite",
        invite.id,
        {
            "is_admin": is_admin,
            "permissions": canonical(permissions),
            "expires_at": invite.expires_at.isoformat(),
        },
    )
    return invite, token


async def revoke_invite(scope: Scope, invite_id: uuid.UUID) -> Invite:
    invite = await scope.session.scalar(
        select(Invite).where(
            Invite.id == invite_id, Invite.project_id == scope.project.id
        )
    )
    if invite is None:
        raise PanelError(ErrorClass.NOT_FOUND, NOT_FOUND)
    if invite.used_at is not None:
        raise PanelError(ErrorClass.CONFLICT, "The invite is used")
    if invite.revoked_at is None:
        invite.revoked_at = _now()
        _audit(scope, "invite.revoke", "invite", invite.id)
    return invite


async def accept_invite(session: AsyncSession, actor: Actor, token: str) -> Membership:
    """Rule 4: the invite gives its access once. An unknown, used, revoked or
    expired token is one answer -- ``not_found``."""
    digest = token_hash(token)
    project_id = await session.scalar(
        select(Invite.project_id).where(Invite.token_hash == digest)
    )
    if project_id is None:
        raise PanelError(ErrorClass.NOT_FOUND, NOT_FOUND)
    # The project's row first, as every writer of its access.
    project = await session.scalar(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    invite = await session.scalar(
        select(Invite).where(Invite.token_hash == digest).with_for_update()
    )
    if (
        project is None
        or invite is None
        or invite.used_at is not None
        or invite.revoked_at is not None
        or invite.expires_at <= _now()
    ):
        raise PanelError(ErrorClass.NOT_FOUND, NOT_FOUND)
    if project.archived_at is not None:
        raise PanelError(ErrorClass.CONFLICT, "The project is archived")
    exists = await session.scalar(
        select(Membership.id).where(
            Membership.project_id == project.id,
            Membership.user_id == actor.user_id,
            Membership.revoked_at.is_(None),
        )
    )
    if exists is not None:
        raise PanelError(ErrorClass.CONFLICT, "You have access to the project")
    membership = Membership(
        user_id=actor.user_id,
        project_id=project.id,
        is_admin=invite.is_admin,
        permissions=canonical(parse_permissions(invite.permissions)),
        granted_by=invite.created_by,
    )
    session.add(membership)
    invite.used_at = _now()
    invite.used_by = actor.user_id
    await session.flush()
    record(
        session,
        actor_kind=ActorKind.USER,
        actor_id=actor.user_id,
        project_id=project.id,
        action="invite.accept",
        object_kind="invite",
        object_id=str(invite.id),
        details={"membership_id": str(membership.id), "is_admin": invite.is_admin},
    )
    return membership


async def grant_panel(
    session: AsyncSession, actor: Actor, user_id: uuid.UUID, grant: PanelGrantKind
) -> PanelGrant:
    user = await session.scalar(
        select(User).where(User.id == user_id).with_for_update()
    )
    if user is None or user.deactivated_at is not None:
        raise PanelError(ErrorClass.NOT_FOUND, NOT_FOUND)
    exists = await session.scalar(
        select(PanelGrant.id).where(
            PanelGrant.user_id == user_id,
            PanelGrant.grant == grant.value,
            PanelGrant.revoked_at.is_(None),
        )
    )
    if exists is not None:
        raise PanelError(ErrorClass.CONFLICT, f"The person holds {grant}")
    held = PanelGrant(user_id=user_id, grant=grant.value, granted_by=actor.user_id)
    session.add(held)
    await session.flush()
    record(
        session,
        actor_kind=ActorKind.USER,
        actor_id=actor.user_id,
        project_id=None,
        action="panel_grant.grant",
        object_kind="panel_grant",
        object_id=str(held.id),
        details={"user_id": str(user_id), "grant": grant.value},
    )
    return held


async def revoke_panel(
    session: AsyncSession, actor: Actor, grant_id: uuid.UUID
) -> PanelGrant:
    held = await session.get(PanelGrant, grant_id)
    if held is None:
        raise PanelError(ErrorClass.NOT_FOUND, NOT_FOUND)
    await session.scalar(
        select(User.id).where(User.id == held.user_id).with_for_update()
    )
    await session.refresh(held)
    if held.revoked_at is None:
        held.revoked_at = _now()
        record(
            session,
            actor_kind=ActorKind.USER,
            actor_id=actor.user_id,
            project_id=None,
            action="panel_grant.revoke",
            object_kind="panel_grant",
            object_id=str(held.id),
            details={"user_id": str(held.user_id), "grant": held.grant},
        )
    return held
