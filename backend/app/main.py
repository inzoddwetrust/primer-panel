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
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp

from app.access.comms import CommsClient
from app.access.login import router as login_router
from app.access.router import router as access_router
from app.access.startup import check_at_start
from app.agent.box import install_agent_refusals
from app.agent.people import router as servers_router
from app.agent.router import router as agent_router
from app.config import Settings
from app.core.database import (
    at_head,
    make_engine,
    make_sessions,
    read_revision,
    script_head,
)
from app.core.errors import install_error_handlers
from app.core.origin import EXPOSED, HEADERS, METHODS, OriginGuard
from app.core.redis import REDIS, make_redis, ping
from app.core.state import Core, install
from app.editions import EDITIONS
from app.fleet.router import router as fleet_router
from app.ops.repo import OpsPlaces, OpsRepo
from app.ops.router import router as passport_router
from app.runs.router import router as runs_router
from app.seams import PROVIDES, requires_satisfied
from primer_report import Limits, PrimerReport, Seams

SERVICE = "primer-panel"

# The largest request body the backend accepts, reported in /health.limits
# for the machine to compare with routes.api.max_body of primer.yaml.
MAX_UPLOAD_MB = 1

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    comms_transport: httpx.AsyncBaseTransport | None = None,
    ops_places: OpsPlaces | None = None,
) -> ASGIApp:
    """Build the app; the settings default to the environment.

    ``comms_transport`` is the seam of the tests: a stand-in of comms' sign-in
    module by its form. The application itself has none (DM-150).
    ``ops_places`` -- where the clone of primer-ops and its two keys are; the
    stack's own paths unless a test names others (DM-158)."""
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
        ops=OpsRepo(settings.ops_repo, ops_places or OpsPlaces()),
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
    # The last added is the outermost: CORS answers the preflight and puts
    # its headers on every answer to the frontend, the guard's refusal too.
    app.add_middleware(OriginGuard, frontend_origin=settings.frontend_origin)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=METHODS,
        allow_headers=HEADERS,
        expose_headers=EXPOSED,
    )
    app.include_router(access_router)
    app.include_router(login_router)
    app.include_router(servers_router)
    app.include_router(agent_router)
    app.include_router(fleet_router)
    app.include_router(runs_router)
    app.include_router(passport_router)
    install_agent_refusals(app)
    report = PrimerReport(
        service=SERVICE,
        release=settings.release,
        commit=settings.commit,
        edition=settings.edition,
        modules=list(EDITIONS[settings.edition]),
        limits=Limits(max_upload_mb=MAX_UPLOAD_MB),
        # What primer.yaml provides and whether the seams it takes have their
        # values: app/seams.py, held equal to primer.yaml by a test (DM-212)
        seams=Seams(provides=list(PROVIDES), requires_satisfied=requires_satisfied()),
        db=partial(read_revision, engine),
        head_checks={"schema": at_head(head)},
        checks={REDIS: partial(ping, redis)},
        details=lambda: {"script_head": head},
    )
    return report.install(app)
