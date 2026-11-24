"""Sign-in through comms, and sign-out (DM-150; TZ 0.7.41 N).

The browser's navigations, on the API's host:

1. ``GET /auth/telegram/start[?invite=<token>]`` -- comms' ``start`` with the
   return address ``https://<DOMAIN_API>/auth/telegram/return`` and
   ``bot_access: true``. The answer's ``state`` goes into the Panel's own
   cookie ``panel_login``; an invite's token into ``panel_invite``. Both
   HttpOnly, Secure, SameSite=Lax, on the path of the return, for the term
   of comms' attempt. Then 302 to Telegram.
2. ``GET /auth/telegram/return?code&state`` -- the ``state`` of the address is
   compared with the cookie's BEFORE comms is called; no cookie or another
   ``state`` -- refused, comms is not called (the binding of the attempt to
   the browser is the Panel's, the form of comms, step 6). Then comms'
   ``complete``; then the Panel decides by ``telegram.id`` (``decide``) and
   makes the session.
3. ``POST /auth/logout`` -- the request's session is closed.

Every end of a navigation is a 302 to the frontend: ``/`` signed in, or
``/login#reason=<LoginRefusal>[&telegram_id=<id>]``. The fragment never
reaches a server or an access log; the page shows the person their Telegram
id (the owner's decision of 23.11). The cookies of the attempt are wiped at
every end of the return.

``decide`` -- in order: the superadmin (the passport's id) -- an account is
made if there is none, no invite needed; an invite in the cookie -- the
account is made or updated and the invite accepted (DM-149); an active
account with a membership or a Panel grant; a deactivated account --
refused; anybody else -- refused with their id. The profile (first name,
username, ``bot_access_granted``) is updated at every sign-in.
"""

import hmac
import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import sessions
from app.access.actor import Actor
from app.access.comms import (
    CommsClient,
    CommsOffFormError,
    CommsRefusedError,
    CommsUnreachableError,
    LoginResult,
    seconds_until,
)
from app.access.models import Membership, PanelGrant, User
from app.access.rules import Public, SessionHolder
from app.access.service import accept_invite
from app.audit.models import ActorKind
from app.audit.service import record
from app.config import Settings
from app.core.database import get_db_session
from app.core.errors import ErrorClass, PanelError
from app.core.state import get_comms, get_redis, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")

RETURN_PATH = "/auth/telegram/return"
LOGIN_COOKIE = "panel_login"
INVITE_COOKIE = "panel_invite"
ATTEMPT_PATH = "/auth/telegram"


class LoginRefusal(StrEnum):
    """Why a sign-in ended without a session: the frontend's words for it."""

    RESTART = "restart"
    TRY_LATER = "try_later"
    REFUSED = "refused"
    DEFECT = "defect"
    UNAVAILABLE = "unavailable"
    FOREIGN_STATE = "foreign_state"
    STRANGER = "stranger"
    DEACTIVATED = "deactivated"
    INVITE_INVALID = "invite_invalid"


COMMS_REFUSAL: dict[str, LoginRefusal] = {
    "login_unknown": LoginRefusal.RESTART,
    "login_expired": LoginRefusal.RESTART,
    "login_replayed": LoginRefusal.RESTART,
    "provider_refused": LoginRefusal.RESTART,
    "provider_unavailable": LoginRefusal.TRY_LATER,
    "unavailable": LoginRefusal.TRY_LATER,
    "id_token_invalid": LoginRefusal.REFUSED,
    "validation": LoginRefusal.DEFECT,
    "unauthorized": LoginRefusal.DEFECT,
}
"""Each class of refusal of comms (the form, section 6) and the Panel's answer."""

Settings_ = Annotated[Settings, Depends(get_settings)]
Comms = Annotated[CommsClient | None, Depends(get_comms)]
RedisClient = Annotated[Redis, Depends(get_redis)]
Writer = Annotated[AsyncSession, Depends(get_db_session)]
Anybody = Annotated[None, Depends(Public())]


def _set(response: Response, name: str, value: str, max_age: int, path: str) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path=path,
        secure=True,
        httponly=True,
        samesite="lax",
    )


def _wipe_attempt(response: Response) -> None:
    for name in (LOGIN_COOKIE, INVITE_COOKIE):
        response.delete_cookie(
            name, path=ATTEMPT_PATH, secure=True, httponly=True, samesite="lax"
        )


def refused(
    settings: Settings, reason: LoginRefusal, telegram_id: int | None = None
) -> RedirectResponse:
    """302 to the frontend's page of refusal, the reason in the fragment."""
    fragment = f"reason={reason.value}"
    if telegram_id is not None:
        fragment += f"&telegram_id={telegram_id}"
    response = RedirectResponse(f"{settings.frontend_origin}/login#{fragment}", 302)
    _wipe_attempt(response)
    return response


@router.get("/telegram/start")
async def start(
    _: Anybody, settings: Settings_, comms: Comms, invite: str | None = None
) -> RedirectResponse:
    if comms is None:
        logger.warning(
            "sign-in asked, comms is not connected",
            extra={"event": "login.comms_not_connected"},
        )
        return refused(settings, LoginRefusal.UNAVAILABLE)
    try:
        started = await comms.start(settings.api_origin + RETURN_PATH)
    except CommsRefusedError as error:
        return _comms_refused(settings, error.error_class)
    except CommsUnreachableError:
        return refused(settings, LoginRefusal.TRY_LATER)
    except CommsOffFormError:
        logger.error(
            "comms' start is off its form", extra={"event": "login.comms_off_form"}
        )
        return refused(settings, LoginRefusal.DEFECT)
    response = RedirectResponse(started.authorize_url, 302)
    term = min(seconds_until(started.expires_at, datetime.now(UTC)), 600)
    _set(response, LOGIN_COOKIE, started.state, term, ATTEMPT_PATH)
    if invite:
        _set(response, INVITE_COOKIE, invite, term, ATTEMPT_PATH)
    return response


def _comms_refused(settings: Settings, error_class: str) -> RedirectResponse:
    reason = COMMS_REFUSAL[error_class]
    if reason is LoginRefusal.DEFECT:
        logger.error(
            "comms refused the Panel itself",
            extra={"event": "login.comms_refused", "ctx": {"class": error_class}},
        )
    return refused(settings, reason)


async def _person(session: AsyncSession, result: LoginResult) -> User:
    """The account of the person comms vouched for, made or updated."""
    person = result.telegram
    user = await session.scalar(
        select(User).where(User.telegram_id == person.id).with_for_update()
    )
    if user is None:
        user = User(telegram_id=person.id)
        session.add(user)
    user.first_name = person.first_name
    user.username = person.username
    user.bot_access_granted = person.bot_access_granted
    await session.flush()
    return user


async def _has_access(session: AsyncSession, user_id: uuid.UUID) -> bool:
    member = exists().where(
        Membership.user_id == user_id, Membership.revoked_at.is_(None)
    )
    grant = exists().where(
        PanelGrant.user_id == user_id, PanelGrant.revoked_at.is_(None)
    )
    return bool(await session.scalar(select(member | grant)))


async def decide(
    session: AsyncSession,
    settings: Settings,
    result: LoginResult,
    invite: str | None,
) -> User | LoginRefusal:
    """The account to sign in, or why not (module docstring)."""
    telegram_id = result.telegram.id
    known = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    # Read now: a rolled-back savepoint below expires the loaded objects.
    known_id = None if known is None else known.id
    if known is not None and known.deactivated_at is not None:
        return LoginRefusal.DEACTIVATED
    if telegram_id == settings.superadmin_telegram_id:
        return await _person(session, result)
    if invite:
        try:
            async with session.begin_nested():
                user = await _person(session, result)
                actor = Actor(
                    user_id=user.id, telegram_id=telegram_id, is_superadmin=False
                )
                await accept_invite(session, actor, invite)
            return user
        except PanelError:
            pass  # the invite gives nothing: the account may still have access
    if known_id is not None and await _has_access(session, known_id):
        return await _person(session, result)
    return LoginRefusal.INVITE_INVALID if invite else LoginRefusal.STRANGER


@router.get(RETURN_PATH.removeprefix("/auth"))
async def finish(
    request: Request,
    _: Anybody,
    settings: Settings_,
    comms: Comms,
    session: Writer,
    redis: RedisClient,
) -> RedirectResponse:
    given = request.query_params.get("state", "")
    code = request.query_params.get("code", "")
    kept = request.cookies.get(LOGIN_COOKIE, "")
    if not given or not code or not kept or not hmac.compare_digest(given, kept):
        logger.warning(
            "a return without its attempt", extra={"event": "login.foreign_state"}
        )
        return refused(settings, LoginRefusal.FOREIGN_STATE)
    if comms is None:
        return refused(settings, LoginRefusal.UNAVAILABLE)
    try:
        result = await comms.complete(given, code)
    except CommsRefusedError as error:
        return _comms_refused(settings, error.error_class)
    except CommsUnreachableError:
        return refused(settings, LoginRefusal.TRY_LATER)
    except CommsOffFormError:
        logger.error(
            "comms' complete is off its form", extra={"event": "login.comms_off_form"}
        )
        return refused(settings, LoginRefusal.DEFECT)
    decided = await decide(
        session, settings, result, request.cookies.get(INVITE_COOKIE)
    )
    telegram_id = result.telegram.id
    if isinstance(decided, LoginRefusal):
        record(
            session,
            actor_kind=ActorKind.SYSTEM,
            actor_id=None,
            project_id=None,
            action="login.refused",
            object_kind="telegram",
            object_id=str(telegram_id),
            details={"reason": decided.value},
        )
        return refused(settings, decided, telegram_id)
    try:
        token = await sessions.create(redis, decided.id, telegram_id)
    except RedisError:
        await session.rollback()
        return refused(settings, LoginRefusal.TRY_LATER)
    record(
        session,
        actor_kind=ActorKind.USER,
        actor_id=decided.id,
        project_id=None,
        action="login",
        object_kind="user",
        object_id=str(decided.id),
    )
    response = RedirectResponse(f"{settings.frontend_origin}/", 302)
    _wipe_attempt(response)
    _set(response, sessions.COOKIE, token, sessions.SESSION_TTL_S, "/")
    return response


@router.post("/logout", status_code=204)
async def logout(
    token: Annotated[str | None, Depends(SessionHolder())], redis: RedisClient
) -> Response:
    if token:
        try:
            await sessions.close(redis, token)
        except RedisError as error:
            raise PanelError(
                ErrorClass.UNAVAILABLE, "Sessions are unavailable"
            ) from error
    response = Response(status_code=204)
    response.delete_cookie(
        sessions.COOKIE, path="/", secure=True, httponly=True, samesite="lax"
    )
    return response
