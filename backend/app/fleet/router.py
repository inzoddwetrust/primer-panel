"""``GET /api/v1/servers``: the fleet (DM-154).

The servers of the projects a person sees (the superadmin, every project;
anybody else, the projects of an active membership -- product and service
alike), not detached; each with the facts its box sent and the reasons it is
red (``app.fleet.reasons``), in the order of the fleet: the page shows them as
they come. A field with no data is ``null`` -- never a made-up value.

The last full ``box-state.v1`` is read by contract 4's own model
(``BoxSnapshot``); one that does not read is no data, logged.
"""

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pridem.report.box_snapshot import BoxSnapshot, Unmeasured
from pydantic import BaseModel, ValidationError
from sqlalchemy import TIMESTAMP, cast, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.actor import Actor
from app.access.models import Membership
from app.access.rules import AnyActor, ServerRead, ServerScope
from app.agent.models import ServerState, Verdict
from app.core.database import get_db_reader
from app.fleet.reasons import (
    PINNED_RELEASE,
    LastVerdict,
    RedReason,
    moment,
    order_key,
    reasons,
    services,
    stacks,
)
from app.projects.models import Project, Server

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


class ProjectRef(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    kind: str


class VerdictRef(BaseModel):
    run_id: str
    verb: str
    result: str
    finished: str
    verified: bool


class StackRef(BaseModel):
    stack: str
    release: str | None


class Health(BaseModel):
    healthy: int
    unhealthy: int
    starting: int
    none: int


class SslRef(BaseModel):
    mode: str
    expires: str
    renews_from: str | None


class FleetServer(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    project: ProjectRef
    heartbeat_at: datetime | None
    machine_version: str | None
    machine_release: str
    verdict: VerdictRef | None
    stacks: list[StackRef] | None
    health: Health | None
    ssl: SslRef | None
    measured_at: str | None
    reasons: list[RedReason]


def _snapshot(
    server_id: uuid.UUID, raw: dict[str, object] | None
) -> BoxSnapshot | None:
    if raw is None:
        return None
    try:
        return BoxSnapshot.model_validate(raw)
    except ValidationError:
        logger.warning(
            "a full state of a box that does not read",
            extra={
                "event": "fleet.snapshot_unread",
                "ctx": {"server_id": str(server_id)},
            },
        )
        return None


def _health(snapshot: BoxSnapshot | None) -> Health | None:
    found = services(snapshot)
    if found is None:
        return None
    return Health(
        healthy=found.count("healthy"),
        unhealthy=found.count("unhealthy"),
        starting=found.count("starting"),
        none=found.count("none"),
    )


def _ssl(server_id: uuid.UUID, snapshot: BoxSnapshot | None) -> SslRef | None:
    """The certificate as the page shows it; an end that is no date -- no
    data, logged (DM-210): the page shows a person no text of the box's that
    the Panel could not read. A start of renewal that is none -- the end
    alone."""
    if snapshot is None or isinstance(snapshot.ssl, Unmeasured):
        return None
    ssl = snapshot.ssl
    renews = ssl.renews_from if isinstance(ssl.renews_from, str) else None
    unread = [
        name
        for name, value in (("expires", ssl.expires), ("renews_from", renews))
        if value is not None and moment(value) is None
    ]
    if unread:
        logger.warning(
            "a moment of a certificate that is no date",
            extra={
                "event": "fleet.ssl_moment_unread",
                "ctx": {"server_id": str(server_id), "fields": unread},
            },
        )
    if "expires" in unread:
        return None
    if "renews_from" in unread:
        renews = None
    return SslRef(mode=ssl.mode, expires=ssl.expires, renews_from=renews)


@router.get("/servers")
async def fleet(
    actor: Annotated[Actor, Depends(AnyActor())],
    session: Annotated[AsyncSession, Depends(get_db_reader)],
) -> list[FleetServer]:
    query = (
        select(Server, Project, ServerState)
        .join(Project, Project.id == Server.project_id)
        .outerjoin(ServerState, ServerState.server_id == Server.id)
        .where(Server.detached_at.is_(None))
    )
    if not actor.is_superadmin:
        seen = select(Membership.project_id).where(
            Membership.user_id == actor.user_id, Membership.revoked_at.is_(None)
        )
        query = query.where(Server.project_id.in_(seen))
    rows = [(s, p, st) for s, p, st in (await session.execute(query)).all()]
    fleet = await describe(session, rows)
    fleet.sort(key=lambda each: order_key(each.name, each.reasons))
    return fleet


@router.get("/servers/{server_id}")
async def server_card(
    found: Annotated[ServerScope, Depends(ServerRead())],
) -> FleetServer:
    """The head of a server's card (DM-155): the fleet's row of one server."""
    state = await found.scope.session.get(ServerState, found.server.id)
    [head] = await describe(
        found.scope.session, [(found.server, found.scope.project, state)]
    )
    return head


async def describe(
    session: AsyncSession, rows: Sequence[tuple[Server, Project, ServerState | None]]
) -> list[FleetServer]:
    """Every server of ``rows`` as the fleet shows it (changed by DM-155: one
    builder for the fleet and a server's card)."""
    ids = [server.id for server, _, _ in rows]
    finished = cast(Verdict.body["finished"].astext, TIMESTAMP(timezone=True))
    last = await session.execute(
        select(
            Verdict.server_id,
            Verdict.run_id,
            Verdict.body["verb"].astext,
            Verdict.body["result"].astext,
            Verdict.body["finished"].astext,
            Verdict.verified,
        )
        .where(Verdict.server_id.in_(ids))
        .ext(distinct_on(Verdict.server_id))
        .order_by(Verdict.server_id, finished.desc(), Verdict.run_id.desc())
    )
    verdicts = {
        server_id: VerdictRef(
            run_id=run_id, verb=verb, result=result, finished=ended, verified=verified
        )
        for server_id, run_id, verb, result, ended, verified in last.all()
    }
    now = datetime.now(UTC)
    fleet: list[FleetServer] = []
    for server, project, state in rows:
        snapshot = _snapshot(server.id, None if state is None else state.snapshot)
        verdict = verdicts.get(server.id)
        found = reasons(
            heartbeat_at=None if state is None else state.last_heartbeat_at,
            machine_version=None if state is None else state.machine_version,
            verdict=None
            if verdict is None
            else LastVerdict(verdict.result, verdict.verified),
            snapshot=snapshot,
            now=now,
        )
        parts = stacks(snapshot)
        fleet.append(
            FleetServer(
                id=server.id,
                name=server.name,
                role=server.role,
                project=ProjectRef(
                    id=project.id,
                    slug=project.slug,
                    name=project.name,
                    kind=project.kind,
                ),
                heartbeat_at=None if state is None else state.last_heartbeat_at,
                machine_version=None if state is None else state.machine_version,
                machine_release=PINNED_RELEASE,
                verdict=verdict,
                stacks=None
                if parts is None
                else [
                    StackRef(
                        stack=part.stack,
                        release=part.release if isinstance(part.release, str) else None,
                    )
                    for part in parts
                ],
                health=_health(snapshot),
                ssl=_ssl(server.id, snapshot),
                measured_at=None if snapshot is None else snapshot.measured_at,
                reasons=found,
            )
        )
    return fleet
