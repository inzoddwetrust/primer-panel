"""Requests from another site: CORS for the Panel's frontend, and the refusal
of a changing request that does not come from it (DM-151).

The frontend (``https://<DOMAIN_FRONTEND>``) and the API
(``https://<DOMAIN_API>``) are two origins of one site: the session cookie is
``SameSite=Lax`` and goes with the frontend's requests, so the browser must
be told the frontend may read the answers (CORS with credentials) -- and only
the frontend: no ``*``, and ``X-Request-ID`` exposed for the error it shows.

``OriginGuard`` refuses a changing request -- ``POST``, ``PUT``, ``PATCH``,
``DELETE`` -- to the paths of ``GUARDED`` whose ``Origin`` is not exactly the
frontend's, absent included: ``forbidden`` (403), before any route runs. A
browser sends ``Origin`` with every such request; a page of another site
cannot forge it. Reading (``GET``) and the CORS preflight (``OPTIONS``) are
not checked; neither are the browser's navigations of sign-in
(``/auth/telegram/*``), ``/health`` and ``/ready`` (the machine) and the
future agent's API, which a box calls with its signature, not a browser.
"""

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import ErrorClass, error_response

UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})

GUARDED_PREFIXES = ("/api/v1/",)
GUARDED_PATHS = frozenset({"/auth/logout"})
"""The paths a changing request must come from the frontend to: every path
under ``/api/v1/`` and the sign-out. A test holds them against the routes."""

EXPOSED = ["X-Request-ID"]
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
HEADERS = ["Content-Type"]


def guarded(path: str) -> bool:
    return path in GUARDED_PATHS or path.startswith(GUARDED_PREFIXES)


class OriginGuard:
    """Refuse a changing request to a guarded path from another origin."""

    def __init__(self, app: ASGIApp, frontend_origin: str) -> None:
        self.app = app
        self.frontend_origin = frontend_origin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] in UNSAFE
            and guarded(scope["path"])
            and self._origin(scope) != self.frontend_origin
        ):
            response = error_response(
                ErrorClass.FORBIDDEN, "Request from another origin"
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _origin(scope: Scope) -> str | None:
        for name, value in scope.get("headers", []):
            if name == b"origin":
                return bytes(value).decode("latin-1")
        return None
