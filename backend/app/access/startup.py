"""Checks of the access at the start of the application.

Run by the lifespan before the first request, when the database answers and
stands at the migrations' head; otherwise they are put off to the next start
-- the application still starts and ``/ready`` is red by ``db`` or ``schema``
(protocol 9.5), and the second line below still holds.

1. **A permission the code does not know refuses the start** (TZ-1 section 3;
   gate DM-149 R4): one query reads the distinct values of
   ``memberships.permissions`` and ``invites.permissions``; a value outside
   ``Permission`` raises with its name, and uvicorn stops. It can only come
   from a permission removed from the code without its migration. The second
   line: a row read with it fails its parse (``parse_permissions``).
2. **The superadmin is recorded in the audit when it changes** (gate R3): the
   last ``superadmin.set`` row of the audit says whose Telegram id the
   passport named at a start; another id now -- a new row with the previous
   and the new one. The mark itself is computed per request and stored
   nowhere (``app.access.actor``).
"""

import asyncio
import logging

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.access.models import Invite, Membership
from app.access.permissions import Permission
from app.audit.models import ActorKind, Audit
from app.audit.service import record
from app.config import Settings
from app.core.database import make_sessions, read_revision
from primer_report import CHECK_TIMEOUT_S

logger = logging.getLogger(__name__)

SUPERADMIN_SET = "superadmin.set"


async def unknown_permissions(session: AsyncSession) -> list[str]:
    """Values of the database's permissions that ``Permission`` does not hold."""
    stored = select(func.unnest(Membership.permissions)).union(
        select(func.unnest(Invite.permissions))
    )
    known = {permission.value for permission in Permission}
    return sorted(set(await session.scalars(stored)) - known)


async def record_superadmin(session: AsyncSession, telegram_id: int) -> bool:
    """Add a ``superadmin.set`` row when the passport names another id than the
    last row says; ``True`` if a row was added."""
    last = await session.scalar(
        select(Audit.details)
        .where(Audit.action == SUPERADMIN_SET)
        .order_by(Audit.at.desc())
        .limit(1)
    )
    previous = None if last is None else last.get("telegram_id")
    if previous == telegram_id:
        return False
    record(
        session,
        actor_kind=ActorKind.SYSTEM,
        actor_id=None,
        project_id=None,
        action=SUPERADMIN_SET,
        object_kind="superadmin",
        object_id=str(telegram_id),
        details={"telegram_id": telegram_id, "previous": previous},
    )
    return True


async def check_at_start(engine: AsyncEngine, settings: Settings, head: str) -> None:
    """The checks above, or a line saying why they are put off."""
    try:
        revision = await asyncio.wait_for(read_revision(engine), CHECK_TIMEOUT_S)
    except (OSError, SQLAlchemyError, LookupError, TimeoutError) as error:
        logger.warning(
            "access checks put off: the database is not read",
            extra={
                "event": "access.start_checks_put_off",
                "ctx": {"error": type(error).__name__},
            },
        )
        return
    if revision != head:
        logger.warning(
            "access checks put off: the database is at %s, not %s",
            revision,
            head,
            extra={
                "event": "access.start_checks_put_off",
                "ctx": {"revision": revision},
            },
        )
        return
    async with make_sessions(engine)() as session, session.begin():
        unknown = await unknown_permissions(session)
        if unknown:
            names = ", ".join(unknown)
            raise RuntimeError(
                f"permissions in the database unknown to the code: {names}"
            )
        if await record_superadmin(session, settings.superadmin_telegram_id):
            logger.info(
                "the superadmin of the passport is recorded",
                extra={"event": "access.superadmin_set"},
            )
