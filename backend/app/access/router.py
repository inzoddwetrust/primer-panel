"""The access API: projects, members, invites, audit, Panel grants.

Every route has exactly one access rule (``app.access.rules``) and learns the
person only through it. An object of a project the person does not see is
``not_found``; a project's object reached through another project's path is
``not_found`` too: each query is bound to the project of the path.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import service
from app.access.actor import Actor
from app.access.models import Invite, Membership, PanelGrant, User
from app.access.permissions import Permission, canonical, effective
from app.access.rules import (
    AnyActor,
    ProjectRead,
    ProjectWrite,
    Scope,
    Superadmin,
)
from app.access.schemas import (
    AcceptIn,
    AdminIn,
    AuditOut,
    InviteCreated,
    InviteIn,
    InviteOut,
    MemberOut,
    MeOut,
    PanelGrantIn,
    PanelGrantOut,
    PermissionsIn,
    PermissionsOut,
    ProjectAccessOut,
    ProjectIn,
    ProjectOut,
    UserOut,
)
from app.audit.models import Audit
from app.config import Settings
from app.core.database import get_db_reader, get_db_session
from app.core.ratelimit import rate_limit
from app.core.state import get_redis, get_settings
from app.projects.models import Project

router = APIRouter(prefix="/api/v1")

Reader = Annotated[AsyncSession, Depends(get_db_reader)]
Writer = Annotated[AsyncSession, Depends(get_db_session)]
RedisClient = Annotated[Redis, Depends(get_redis)]

AsAnyone = Annotated[Actor, Depends(AnyActor())]
AsSuperadmin = Annotated[Actor, Depends(Superadmin())]
MemberReads = Annotated[Scope, Depends(ProjectRead())]
PeopleReads = Annotated[Scope, Depends(ProjectRead(Permission.PEOPLE))]
PeopleWrites = Annotated[Scope, Depends(ProjectWrite(Permission.PEOPLE))]
SuperadminWrites = Annotated[Scope, Depends(ProjectWrite(superadmin_only=True))]


async def _members(session: AsyncSession, project_id: uuid.UUID) -> list[MemberOut]:
    rows = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.project_id == project_id, Membership.revoked_at.is_(None))
        .order_by(Membership.granted_at)
    )
    return [
        MemberOut(
            user=UserOut.model_validate(user),
            is_admin=membership.is_admin,
            permissions=membership.permissions,
            effective=canonical(
                effective(
                    membership.permissions,
                    is_admin=membership.is_admin,
                    is_superadmin=False,
                )
            ),
            granted_by=membership.granted_by,
            granted_at=membership.granted_at,
        )
        for membership, user in rows
    ]


@router.get("/me")
async def me(actor: AsAnyone, session: Reader) -> MeOut:
    user = await session.get_one(User, actor.user_id)
    rows = await session.execute(
        select(Membership, Project)
        .join(Project, Project.id == Membership.project_id)
        .where(Membership.user_id == actor.user_id, Membership.revoked_at.is_(None))
        .order_by(Project.slug)
    )
    projects = [
        ProjectAccessOut(
            project=ProjectOut.model_validate(project),
            is_admin=membership.is_admin,
            permissions=canonical(
                effective(
                    membership.permissions,
                    is_admin=membership.is_admin,
                    is_superadmin=actor.is_superadmin,
                )
            ),
        )
        for membership, project in rows
    ]
    grants = await session.scalars(
        select(PanelGrant.grant).where(
            PanelGrant.user_id == actor.user_id, PanelGrant.revoked_at.is_(None)
        )
    )
    return MeOut(
        user=UserOut.model_validate(user),
        is_superadmin=actor.is_superadmin,
        projects=projects,
        panel_grants=sorted(grants),
    )


@router.get("/permissions")
async def list_permissions(actor: AsAnyone) -> PermissionsOut:
    """Every permission of the code, in its order (DM-152)."""
    return PermissionsOut(permissions=[permission.value for permission in Permission])


@router.get("/projects")
async def list_projects(actor: AsAnyone, session: Reader) -> list[ProjectOut]:
    query = select(Project).order_by(Project.slug)
    if not actor.is_superadmin:
        query = query.join(Membership, Membership.project_id == Project.id).where(
            Membership.user_id == actor.user_id, Membership.revoked_at.is_(None)
        )
    return [ProjectOut.model_validate(p) for p in await session.scalars(query)]


@router.post("/projects", status_code=201)
async def create_project(
    body: ProjectIn, actor: AsSuperadmin, session: Writer
) -> ProjectOut:
    project = await service.create_project(
        session, actor, body.slug, body.name, body.kind.value, body.repo
    )
    return ProjectOut.model_validate(project)


@router.get("/projects/{project_id}")
async def get_project(scope: MemberReads) -> ProjectOut:
    return ProjectOut.model_validate(scope.project)


@router.post("/projects/{project_id}/archive")
async def archive_project(scope: SuperadminWrites) -> ProjectOut:
    return ProjectOut.model_validate(service.archive_project(scope))


@router.get("/projects/{project_id}/members")
async def list_members(scope: MemberReads) -> list[MemberOut]:
    return await _members(scope.session, scope.project.id)


@router.post("/projects/{project_id}/admins", status_code=201)
async def appoint_admin(body: AdminIn, scope: SuperadminWrites) -> list[MemberOut]:
    await service.appoint_admin(scope, body.user_id, body.permissions)
    return await _members(scope.session, scope.project.id)


@router.put("/projects/{project_id}/members/{user_id}/permissions")
async def set_permissions(
    user_id: uuid.UUID, body: PermissionsIn, scope: PeopleWrites
) -> list[MemberOut]:
    await service.set_permissions(scope, user_id, body.permissions)
    return await _members(scope.session, scope.project.id)


@router.post("/projects/{project_id}/members/{user_id}/revoke")
async def revoke_member(
    user_id: uuid.UUID, scope: PeopleWrites, redis: RedisClient
) -> list[MemberOut]:
    await service.revoke_member(scope, user_id, redis)
    return await _members(scope.session, scope.project.id)


@router.post("/projects/{project_id}/invites", status_code=201)
async def create_invite(body: InviteIn, scope: PeopleWrites) -> InviteCreated:
    invite, token = await service.create_invite(
        scope,
        is_admin=body.is_admin,
        permissions=body.permissions,
        ttl_hours=body.ttl_hours,
    )
    return InviteCreated(invite=InviteOut.model_validate(invite), token=token)


@router.get("/projects/{project_id}/invites")
async def list_invites(scope: PeopleReads) -> list[InviteOut]:
    invites = await scope.session.scalars(
        select(Invite)
        .where(Invite.project_id == scope.project.id)
        .order_by(Invite.created_at)
    )
    return [InviteOut.model_validate(invite) for invite in invites]


@router.post("/projects/{project_id}/invites/{invite_id}/revoke")
async def revoke_invite(invite_id: uuid.UUID, scope: PeopleWrites) -> InviteOut:
    return InviteOut.model_validate(await service.revoke_invite(scope, invite_id))


@router.post(
    "/invites/accept",
    status_code=201,
    # a public route: tokens are tried here (DM-212)
    dependencies=[Depends(rate_limit("invite-accept", limit=10, window_s=60))],
)
async def accept_invite(body: AcceptIn, actor: AsAnyone, session: Writer) -> ProjectOut:
    membership = await service.accept_invite(session, actor, body.token)
    project = await session.get(Project, membership.project_id)
    return ProjectOut.model_validate(project)


@router.get("/projects/{project_id}/audit")
async def list_audit(scope: MemberReads) -> list[AuditOut]:
    rows = await scope.session.scalars(
        select(Audit).where(Audit.project_id == scope.project.id).order_by(Audit.at)
    )
    return [AuditOut.model_validate(row) for row in rows]


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: uuid.UUID,
    actor: AsSuperadmin,
    session: Writer,
    redis: RedisClient,
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserOut:
    user = await service.deactivate_user(
        session, actor, user_id, settings.superadmin_telegram_id, redis
    )
    return UserOut.model_validate(user)


@router.get("/users")
async def list_users(actor: AsSuperadmin, session: Reader) -> list[UserOut]:
    users = await session.scalars(select(User).order_by(User.created_at))
    return [UserOut.model_validate(user) for user in users]


@router.get("/panel-grants")
async def list_panel_grants(
    actor: AsSuperadmin, session: Reader
) -> list[PanelGrantOut]:
    grants = await session.scalars(select(PanelGrant).order_by(PanelGrant.granted_at))
    return [PanelGrantOut.model_validate(grant) for grant in grants]


@router.post("/panel-grants", status_code=201)
async def grant_panel(
    body: PanelGrantIn, actor: AsSuperadmin, session: Writer
) -> PanelGrantOut:
    held = await service.grant_panel(session, actor, body.user_id, body.grant)
    return PanelGrantOut.model_validate(held)


@router.post("/panel-grants/{grant_id}/revoke")
async def revoke_panel_grant(
    grant_id: uuid.UUID, actor: AsSuperadmin, session: Writer
) -> PanelGrantOut:
    return PanelGrantOut.model_validate(
        await service.revoke_panel(session, actor, grant_id)
    )
