"""The state of one application, built by ``create_app``, read by requests.

Nothing of it lives at module level (the owner's decision of 24.11). The
factory builds one ``Core`` and puts it on ``app.state``; a dependency reads it
back from the request, typed: ``app.state`` is untyped, so ``get_core`` checks
what it finds and refuses anything that is not a ``Core``.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.access.comms import CommsClient
from app.config import Settings


@dataclass(frozen=True)
class Core:
    """Everything an application holds for its requests."""

    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    redis: Redis
    # The sign-in module of comms; None until comms is connected (DM-160).
    comms: CommsClient | None


def install(app: FastAPI, core: Core) -> None:
    """Give ``app`` its state."""
    app.state.core = core


def get_core(request: Request) -> Core:
    """The state of the application serving ``request``."""
    core = getattr(request.app.state, "core", None)
    if not isinstance(core, Core):
        raise RuntimeError(
            "the application has no Core: it was not built by create_app"
        )
    return core


def get_settings(core: Annotated[Core, Depends(get_core)]) -> Settings:
    """The settings of the application."""
    return core.settings


def get_redis(core: Annotated[Core, Depends(get_core)]) -> Redis:
    """The Redis client of the application."""
    return core.redis


def get_comms(core: Annotated[Core, Depends(get_core)]) -> CommsClient | None:
    """The comms client of the application, if comms is connected."""
    return core.comms
