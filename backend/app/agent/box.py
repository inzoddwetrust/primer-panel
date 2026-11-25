"""Who sends a request of the agent: the box, by its signature (DM-153).

The paths of the agent (``/agent/v1/``) have no session and no check of
``Origin`` (``app.core.origin``): a box is no browser. A request is the box's
when its headers sign it (``PRIMER-PANEL-TZ-2`` section 3) -- checked in
order, the first that fails answers:

1. the headers of contract 4 are there and of their form (``signed_headers``:
   one exception, ``HeaderMissing``, since v0.1.10) -- else ``signature-bad``;
2. the version of ``X-Primer-Protocol`` is read (``accepts``: N and N-1) --
   else ``protocol-too-old`` / ``protocol-too-new``;
3. ``X-Primer-Box`` names a registered server, not detached -- else
   ``box-unknown``;
4. ``X-Primer-Time`` is within 300 s of the Panel's clock -- else
   ``clock-skew``;
5. the signature holds for the method, the path, the time and the raw body
   -- else ``signature-bad``.

A refusal of the protocol is its own body, ``Refusal {code}`` of contract 4
-- a closed list, no text -- with the status of ``STATUS``. A body that is
not of the contract's form is the box's defect: the Panel's ``invalid``
(422), there is no code of the contract for it.
"""

import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pridem.protocol import (
    PROTOCOL_HEADER,
    HeaderMissing,
    Refusal,
    RefusalCode,
    accepts,
    signed_headers,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.rules import Rule
from app.agent.signature import public_key, request_holds
from app.core.database import get_db_session
from app.projects.models import Server

CLOCK_WINDOW_S = 300

STATUS: dict[str, int] = {
    "signature-bad": 401,
    "clock-skew": 401,
    "box-unknown": 403,
    "run-foreign": 403,
    "protocol-too-old": 400,
    "protocol-too-new": 400,
    "token-unknown": 404,
    "token-used": 410,
    "token-expired": 410,
    "name-taken": 409,
    "product-mismatch": 409,
}
"""The status of each refusal of contract 4 (gate DM-153, R15)."""


class AgentRefusalError(Exception):
    """A refusal of the protocol: answered ``Refusal {code}``."""

    def __init__(self, code: RefusalCode) -> None:
        super().__init__(code)
        self.code: RefusalCode = code


async def _refused(_: Request, error: Exception) -> JSONResponse:
    # registered for AgentRefusalError alone (install_agent_refusals)
    code: RefusalCode = (
        error.code if isinstance(error, AgentRefusalError) else "signature-bad"
    )
    body = Refusal(code=code).model_dump(mode="json")
    return JSONResponse(body, status_code=STATUS[code])


def install_agent_refusals(app: FastAPI) -> None:
    app.add_exception_handler(AgentRefusalError, _refused)


def protocol_of(request: Request) -> int:
    """The version of the request's protocol, read -- else the refusal. A
    request with no version, or not a whole number, speaks none the Panel
    reads: ``protocol-too-old``."""
    value = request.headers.get(PROTOCOL_HEADER, "")
    if not value.isascii() or not value.isdigit():
        raise AgentRefusalError("protocol-too-old")
    version = int(value)
    refusal = accepts(version)
    if refusal is not None:
        raise AgentRefusalError(refusal)
    return version


@dataclass(frozen=True)
class BoxRequest:
    """A request the box's key signed: its server, its version, its body."""

    server: Server
    protocol: int
    body: bytes
    session: AsyncSession


class BoxSigned(Rule):
    """The access rule of the agent's paths: the box's signature."""

    async def __call__(
        self,
        request: Request,
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> BoxRequest:
        try:
            headers = signed_headers(dict(request.headers))
        except HeaderMissing as error:
            raise AgentRefusalError("signature-bad") from error
        refusal = accepts(headers.protocol)
        if refusal is not None:
            raise AgentRefusalError(refusal)
        server = await session.scalar(
            select(Server).where(Server.box_id == headers.box)
        )
        if server is None or server.detached_at is not None:
            raise AgentRefusalError("box-unknown")
        if abs(time.time() - headers.time) > CLOCK_WINDOW_S:
            raise AgentRefusalError("clock-skew")
        body = await request.body()
        path = request.scope.get("raw_path", request.url.path.encode())
        holds = request_holds(
            public_key(server.box_key_public),
            headers.signature,
            method=request.method,
            path=bytes(path).decode("latin-1"),
            time=headers.time,
            body=body,
        )
        if not holds:
            raise AgentRefusalError("signature-bad")
        return BoxRequest(server, headers.protocol, body, session)
