"""Sessions of the Panel, in Redis (PRIMER-PANEL-TZ-1 section 3; DM-150).

A session is an opaque token in the cookie ``panel_session`` (HttpOnly,
Secure, SameSite=Lax); Redis holds its sha256 only -- the token itself is
nowhere but in the browser. A session is the person's identity and nothing
more: every request still asks the database what the person may do
(``current_actor``), so a session never outlives an access by permissions.

- **Term** -- ``SESSION_TTL_S``, seven days from the sign-in, not extended.
- **One out** -- ``close``: the key of the session is deleted.
- **All out** -- ``close_all``: one ``INCR`` of the person's epoch. A session
  is valid only while the epoch it was made with is the epoch now; closing
  every session is one atomic command, with no index to read or to clean.
  The epoch key has no term: one integer per person. Redis keeps nothing on
  disk (DM-148): a restart takes sessions and epochs together -- everybody
  signs in again.

Who closes all sessions of a person: revoking the person's membership,
deactivating the person, a new superadmin in the passport (for the previous
one). The closing runs BEFORE the commit of the change of access: Redis down
-- the change is rolled back and answered 503; the commit failing after the
closing -- the person is out and the access is intact, which is harmless.
"""

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis

SESSION_TTL_S = 7 * 24 * 3600
COOKIE = "panel_session"

_SESSION = "panel:session:"
_EPOCH = "panel:epoch:"


@dataclass(frozen=True)
class SessionPerson:
    user_id: uuid.UUID
    telegram_id: int


class _Stored(BaseModel):
    """A session as it is kept in Redis; anything else is no session."""

    user_id: uuid.UUID
    telegram_id: int
    epoch: int


def _session_key(token: str) -> str:
    return _SESSION + hashlib.sha256(token.encode()).hexdigest()


def _epoch_key(user_id: uuid.UUID) -> str:
    return f"{_EPOCH}{user_id}"


async def create(redis: Redis, user_id: uuid.UUID, telegram_id: int) -> str:
    """A new session of the person at the epoch now; its token."""
    token = secrets.token_urlsafe(48)
    epoch = await redis.get(_epoch_key(user_id))
    value = {
        "user_id": str(user_id),
        "telegram_id": telegram_id,
        "epoch": int(epoch or 0),
        "created_at": datetime.now(UTC).isoformat(),
    }
    await redis.set(_session_key(token), json.dumps(value), ex=SESSION_TTL_S)
    return token


async def person_of(redis: Redis, token: str) -> SessionPerson | None:
    """The person of a valid session; ``None`` -- none, out of term or
    closed."""
    raw = await redis.get(_session_key(token))
    if raw is None:
        return None
    try:
        value = _Stored.model_validate_json(raw)
    except ValidationError:
        return None  # damaged: no session (DM-212), never a 500
    epoch = await redis.get(_epoch_key(value.user_id))
    if int(epoch or 0) != value.epoch:
        return None
    return SessionPerson(user_id=value.user_id, telegram_id=value.telegram_id)


async def close(redis: Redis, token: str) -> None:
    """Close one session (sign-out)."""
    await redis.delete(_session_key(token))


async def close_all(redis: Redis, user_id: uuid.UUID) -> None:
    """Close every session of the person: one ``INCR`` of the epoch."""
    await redis.incr(_epoch_key(user_id))
