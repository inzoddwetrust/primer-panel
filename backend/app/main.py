"""The ASGI application: ``uvicorn --factory app.main:create_app``.

The factory builds the application's state -- settings, the database engine
and its sessions, the Redis client (``app.core.state.Core``) -- puts it on
the app, and returns the app inside the request-id middleware of
``primer_report`` (``PrimerReport.install``), not the ``FastAPI`` object.
The lifespan runs the access checks of ``app.access.startup`` before the
first request and disposes of the engine and closes Redis at the end.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

import httpx
from fastapi import FastAPI
from starlette.types import ASGIApp

from app.access.comms import CommsClient
from app.access.login import router as login_router
from app.access.router import router as access_router
from app.access.startup import check_at_start
from app.config import Settings
from app.core.database import (
    at_head,
    make_engine,
    make_sessions,
    read_revision,
    script_head,
)
from app.core.errors import install_error_handlers
from app.core.redis import REDIS, make_redis, ping
from app.core.state import Core, install
from app.editions import EDITIONS
from primer_report import Limits, PrimerReport, Seams

SERVICE = "primer-panel"

# The largest request body the backend accepts, reported in /health.limits
# for the machine to compare with routes.api.max_body of primer.yaml.
MAX_UPLOAD_MB = 1

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    comms_transport: httpx.AsyncBaseTransport | None = None,
) -> ASGIApp:
    """Build the app; the settings default to the environment.

    ``comms_transport`` is the seam of the tests: a stand-in of comms' sign-in
    module by its form. The application itself has none (DM-150)."""
    settings = settings or Settings()
    engine = make_engine(settings.database_url.get_secret_value())
    redis = make_redis(settings.redis_url.get_secret_value())
    comms = None
    if settings.comms_api_url and settings.comms_service_token is not None:
        comms = CommsClient(
            settings.comms_api_url,
            settings.comms_service_token.get_secret_value(),
            comms_transport,
        )
    core = Core(
        settings=settings,
        engine=engine,
        sessions=make_sessions(engine),
        redis=redis,
        comms=comms,
    )
    head = script_head()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "edition %s, migrations head %s",
            settings.edition,
            head,
            extra={
                "event": "app.started",
                "ctx": {"edition": settings.edition, "script_head": head},
            },
        )
        try:
            await check_at_start(engine, redis, settings, head)
            yield
        finally:
            await engine.dispose()
            await redis.aclose()
            if comms is not None:
                await comms.aclose()

    # No /docs, /redoc or /openapi.json: the API's own description is not
    # served on the API's domain (DM-149).
    app = FastAPI(
        title=SERVICE,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    install(app, core)
    install_error_handlers(app)
    app.include_router(access_router)
    app.include_router(login_router)
    report = PrimerReport(
        service=SERVICE,
        release=settings.release,
        commit=settings.commit,
        edition=settings.edition,
        modules=list(EDITIONS[settings.edition]),
        limits=Limits(max_upload_mb=MAX_UPLOAD_MB),
        # The Panel provides nothing to a service and requires nothing yet.
        seams=Seams(provides=[], requires_satisfied=True),
        db=partial(read_revision, engine),
        head_checks={"schema": at_head(head)},
        checks={REDIS: partial(ping, redis)},
        details=lambda: {"script_head": head},
    )
    return report.install(app)
