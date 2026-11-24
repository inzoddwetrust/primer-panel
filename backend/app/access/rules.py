"""The access rule of a route: exactly one per route, a closed set of kinds.

Each kind is a FastAPI dependency (an instance of ``Rule``) and the only way a
route learns who acts -- every one reads ``current_actor``. A test walks the
dependencies of every route and holds that each has exactly one rule.

- ``Public`` -- anybody, signed in or not: the browser's navigations of
  sign-in (DM-150);
- ``SessionHolder`` -- whoever holds the request's session cookie, with no
  check of the account behind it: signing out needs no access;
- ``AnyActor`` -- any active person;
- ``Superadmin`` -- the superadmin only (``forbidden`` to anybody else);
- ``ProjectRead`` / ``ProjectWrite`` -- an action in the project of the path's
  ``project_id``:

  * the project is visible to the superadmin and to a person with an active
    membership in it; to anybody else it is ``not_found`` -- a project of
    another line, a service project to people of product projects, a project
    that does not exist: one answer;
  * the permission the rule names, if any, must be in the person's effective
    set (``forbidden`` otherwise); ``superadmin_only`` -- the superadmin alone;
  * a write locks the project's row first (``SELECT ... FOR UPDATE``): every
    writer of the access of one project is serialised by that one lock, the
    first and only one it takes before memberships and invites, so two
    writers of a project cannot deadlock; a write in an archived project is
    ``conflict``.

``Scope`` is what a project rule gives the route: the actor, the project, the
effective permissions and the request's session (the writer's for a write).
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.actor import Actor, current_actor
from app.access.models import Membership
from app.access.permissions import Permission, effective
from app.access.sessions import COOKIE
from app.core.database import get_db_reader, get_db_session
from app.core.errors import ErrorClass, PanelError
from app.projects.models import Project

NOT_FOUND = "Not found"


@dataclass(frozen=True)
class Scope:
    actor: Actor
    project: Project
    is_admin: bool
    permissions: frozenset[Permission]
    session: AsyncSession


class Rule:
    """The kind every access rule is: what the route test looks for."""


class Public(Rule):
    async def __call__(self) -> None:
        return None


class SessionHolder(Rule):
    """The token of the request's session cookie, if any."""

    async def __call__(self, request: Request) -> str | None:
        return request.cookies.get(COOKIE) or None


class AnyActor(Rule):
    async def __call__(self, actor: Annotated[Actor, Depends(current_actor)]) -> Actor:
        return actor


class Superadmin(Rule):
    async def __call__(self, actor: Annotated[Actor, Depends(current_actor)]) -> Actor:
        if not actor.is_superadmin:
            raise PanelError(ErrorClass.FORBIDDEN, "Only the superadmin may do this")
        return actor


async def _scope(
    session: AsyncSession,
    actor: Actor,
    project_id: uuid.UUID,
    *,
    lock: bool,
) -> Scope:
    query = select(Project).where(Project.id == project_id)
    project = await session.scalar(query.with_for_update() if lock else query)
    if project is None:
        raise PanelError(ErrorClass.NOT_FOUND, NOT_FOUND)
    if actor.is_superadmin:
        return Scope(
            actor,
            project,
            False,
            effective((), is_admin=False, is_superadmin=True),
            session,
        )
    membership = await session.scalar(
        select(Membership).where(
            Membership.project_id == project_id,
            Membership.user_id == actor.user_id,
            Membership.revoked_at.is_(None),
        )
    )
    if membership is None:
        raise PanelError(ErrorClass.NOT_FOUND, NOT_FOUND)
    held = effective(
        membership.permissions, is_admin=membership.is_admin, is_superadmin=False
    )
    return Scope(actor, project, membership.is_admin, held, session)


def _allowed(
    scope: Scope, permission: Permission | None, superadmin_only: bool
) -> None:
    if superadmin_only and not scope.actor.is_superadmin:
        raise PanelError(ErrorClass.FORBIDDEN, "Only the superadmin may do this")
    if permission is not None and permission not in scope.permissions:
        raise PanelError(ErrorClass.FORBIDDEN, f"The permission {permission} is needed")


class ProjectRead(Rule):
    """Reading in a project: any member, or the permission named."""

    def __init__(self, permission: Permission | None = None) -> None:
        self.permission = permission

    async def __call__(
        self,
        project_id: uuid.UUID,
        actor: Annotated[Actor, Depends(current_actor)],
        session: Annotated[AsyncSession, Depends(get_db_reader)],
    ) -> Scope:
        scope = await _scope(session, actor, project_id, lock=False)
        _allowed(scope, self.permission, superadmin_only=False)
        return scope


class ProjectWrite(Rule):
    """A change in a project: the permission named, or the superadmin only."""

    def __init__(
        self, permission: Permission | None = None, *, superadmin_only: bool = False
    ) -> None:
        if permission is None and not superadmin_only:
            raise ValueError("a write names its permission or is the superadmin's")
        self.permission = permission
        self.superadmin_only = superadmin_only

    async def __call__(
        self,
        project_id: uuid.UUID,
        actor: Annotated[Actor, Depends(current_actor)],
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> Scope:
        scope = await _scope(session, actor, project_id, lock=True)
        _allowed(scope, self.permission, self.superadmin_only)
        if scope.project.archived_at is not None:
            raise PanelError(ErrorClass.CONFLICT, "The project is archived")
        return scope
