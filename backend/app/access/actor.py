"""Who acts: ``current_identity`` and ``current_actor``.

``current_identity`` is the one place a route learns who is there: the
Telegram id of a confirmed person. Until the Panel's sign-in exists (DM-150:
sessions over the identity of comms) it refuses every request with
``unauthorized``; tests put a stand-in in its place. There is no temporary
sign-in by a header: such a hole would live to production.

``current_actor`` turns the identity into the person of the Panel:

- no account for the id -- ``forbidden`` (the account is made at the first
  sign-in, DM-150);
- a deactivated account -- ``forbidden``;
- the superadmin's mark is computed on every request: the account's Telegram
  id equals ``SUPERADMIN_TELEGRAM_ID`` of the Panel's passport. The mark is
  stored nowhere: a new id in the passport takes it from the old account on
  its next request.

The account is read in a short session of its own, closed before the route
runs (one connection at a time per request).
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select

from app.access.models import User
from app.core.errors import ErrorClass, PanelError
from app.core.state import Core, get_core


@dataclass(frozen=True)
class Identity:
    """A confirmed person: the Telegram id the sign-in vouches for."""

    telegram_id: int


@dataclass(frozen=True)
class Actor:
    """The person of the Panel acting in this request."""

    user_id: uuid.UUID
    telegram_id: int
    is_superadmin: bool


async def current_identity() -> Identity:
    """The person signed in; until DM-150 -- nobody."""
    raise PanelError(ErrorClass.UNAUTHORIZED, "Sign-in is not available yet")


async def current_actor(
    identity: Annotated[Identity, Depends(current_identity)],
    core: Annotated[Core, Depends(get_core)],
) -> Actor:
    """The active account of the identity, with its superadmin's mark."""
    async with core.sessions() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == identity.telegram_id)
        )
    if user is None:
        raise PanelError(ErrorClass.FORBIDDEN, "No account in the Panel")
    if user.deactivated_at is not None:
        raise PanelError(ErrorClass.FORBIDDEN, "The account is deactivated")
    return Actor(
        user_id=user.id,
        telegram_id=user.telegram_id,
        is_superadmin=user.telegram_id == core.settings.superadmin_telegram_id,
    )
