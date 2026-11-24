"""The product's factory with one route that fails, for the server's tests.

``uvicorn --factory tests.failing:create_failing_app`` serves the Panel as
``app.main:create_app`` builds it, plus ``FAILING_PATH``, which raises: the
Panel itself has no route that fails, and the failure of a request is what
its ``500`` and its log line are tested on.

Changed by DM-148: the reach into the factory's FastAPI app is ``inner_app``,
shared with the tests that add routes of their own.
"""

from fastapi import FastAPI
from starlette.types import ASGIApp

from app.main import create_app
from primer_report import RequestIdMiddleware

FAILING_FACTORY = "tests.failing:create_failing_app"
FAILING_PATH = "/probe/failing"
FAILING_MESSAGE = "a request the application fails"


def inner_app(served: ASGIApp) -> FastAPI:
    """The FastAPI app ``create_app`` wrapped in the request-id middleware."""
    inner = served.app if isinstance(served, RequestIdMiddleware) else served
    if not isinstance(inner, FastAPI):
        raise TypeError(f"create_app gave {type(served).__name__}, no FastAPI app")
    return inner


def create_failing_app() -> ASGIApp:
    """``create_app()`` with ``FAILING_PATH`` added to its FastAPI app."""
    served = create_app()

    @inner_app(served).get(FAILING_PATH)
    async def failing() -> None:
        raise RuntimeError(FAILING_MESSAGE)

    return served
