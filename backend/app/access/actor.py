"""Who acts: ``current_identity`` and ``current_actor``.

``current_identity`` is the one place a route learns who is there: the
Telegram id of a confirmed person, read from the Panel's session (DM-150,
``app.access.sessions``): the cookie ``panel_session`` names a valid session
or the request is ``unauthorized``. Redis not answering is ``unavailable``
(503): no session is ever taken without it. There is no sign-in by a header.

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

from fastapi import Depends, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select

from app.access import sessions
from app.access.models import User
from app.core.errors import ErrorClass, PanelError
from app.core.state import Core, get_core, get_redis


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


async def current_identity(
    request: Request, redis: Annotated[Redis, Depends(get_redis)]
) -> Identity:
    """The person of the request's session."""
    token = request.cookies.get(sessions.COOKIE)
    if not token:
        raise PanelError(ErrorClass.UNAUTHORIZED, "Sign in")
    try:
        person = await sessions.person_of(redis, token)
    except RedisError as error:
        raise PanelError(ErrorClass.UNAVAILABLE, "Sessions are unavailable") from error
    if person is None:
        raise PanelError(ErrorClass.UNAUTHORIZED, "Sign in")
    return Identity(telegram_id=person.telegram_id)


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
