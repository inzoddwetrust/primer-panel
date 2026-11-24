"""Errors of the API: one form for every refusal and failure.

FORM. Every error body is ``{"error": {"class": <class>, "message": <text>}}``
-- the form of comms' sign-in module (24.11, section 6), so a client of the
Panel and of comms reads one shape. A program reads ``class``; ``message`` is
for a person and is never parsed.

CLASSES are a closed list (``ErrorClass``), each with its HTTP status; a new
class is a change of this file and of its tests.

WHERE AN ERROR COMES FROM, and the handler for each:

- ``PanelError`` raised by the code: its class, its message; a 429 carries
  ``Retry-After`` when the error knows when to come back;
- a request that does not match the API (FastAPI's validation): ``invalid``,
  with the places of the fields at fault -- never their values;
- Starlette's own ``HTTPException`` (an unknown path, a method the route
  does not take, ...): the class of its status, a fixed phrase, its headers
  (``Allow`` of a 405);
- any other exception: ``internal`` with a fixed phrase -- the text of the
  exception never reaches the client. It is not logged here: the request-id
  middleware writes the one ``request.failed`` line of it, inside the request
  (``primer_report.logs``).
"""

from collections.abc import Mapping
from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorClass(StrEnum):
    """The closed list of error classes, as the client reads them."""

    BAD_REQUEST = "bad_request"
    INVALID = "invalid"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    CONFLICT = "conflict"
    TOO_MANY_REQUESTS = "too_many_requests"
    UNAVAILABLE = "unavailable"
    INTERNAL = "internal"


STATUS: dict[ErrorClass, int] = {
    ErrorClass.BAD_REQUEST: 400,
    ErrorClass.INVALID: 422,
    ErrorClass.UNAUTHORIZED: 401,
    ErrorClass.FORBIDDEN: 403,
    ErrorClass.NOT_FOUND: 404,
    ErrorClass.METHOD_NOT_ALLOWED: 405,
    ErrorClass.CONFLICT: 409,
    ErrorClass.TOO_MANY_REQUESTS: 429,
    ErrorClass.UNAVAILABLE: 503,
    ErrorClass.INTERNAL: 500,
}

PHRASE: dict[ErrorClass, str] = {
    ErrorClass.BAD_REQUEST: "Bad request",
    ErrorClass.INVALID: "The request does not match the API",
    ErrorClass.UNAUTHORIZED: "Authentication required",
    ErrorClass.FORBIDDEN: "Action not allowed",
    ErrorClass.NOT_FOUND: "Not found",
    ErrorClass.METHOD_NOT_ALLOWED: "Method not allowed",
    ErrorClass.CONFLICT: "Conflict with the current state",
    ErrorClass.TOO_MANY_REQUESTS: "Too many requests",
    ErrorClass.UNAVAILABLE: "Temporarily unavailable",
    ErrorClass.INTERNAL: "Internal server error",
}
"""The fixed phrase of each class, for errors that carry no message of ours."""

_BY_STATUS = {status: error_class for error_class, status in STATUS.items()}


class PanelError(Exception):
    """An error of the Panel's code, answered in the one form.

    ``retry_after_s`` -- seconds until the client may come back (a 429);
    sent as ``Retry-After``.
    """

    def __init__(
        self,
        error_class: ErrorClass,
        message: str,
        *,
        retry_after_s: int | None = None,
    ) -> None:
        if not message:
            raise ValueError("a PanelError says what went wrong: message is empty")
        if retry_after_s is not None and retry_after_s < 1:
            raise ValueError(f"retry_after_s {retry_after_s} is not a whole second")
        super().__init__(message)
        self.error_class = error_class
        self.message = message
        self.retry_after_s = retry_after_s

    @property
    def status_code(self) -> int:
        return STATUS[self.error_class]


def error_response(
    error_class: ErrorClass,
    message: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """The response of one error, in the one form."""
    return JSONResponse(
        status_code=STATUS[error_class],
        content={"error": {"class": error_class.value, "message": message}},
        headers=headers,
    )


def class_of_status(status: int) -> ErrorClass:
    """The class of an HTTP status no code of ours chose: its own, else by range."""
    known = _BY_STATUS.get(status)
    if known is not None:
        return known
    return ErrorClass.INTERNAL if status >= 500 else ErrorClass.BAD_REQUEST


async def _panel_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, PanelError):  # registered for PanelError only
        raise exc
    headers = None
    if exc.retry_after_s is not None:
        headers = {"Retry-After": str(exc.retry_after_s)}
    return error_response(exc.error_class, exc.message, headers)


async def _invalid(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # registered for it only
        raise exc
    places = sorted(
        {
            ".".join(str(part) for part in error.get("loc", ()))
            for error in exc.errors()
            if isinstance(error, dict)
        }
    )
    message = PHRASE[ErrorClass.INVALID]
    if places:
        message = f"{message}: {', '.join(places)}"
    return error_response(ErrorClass.INVALID, message)


async def _http(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # registered for it only
        raise exc
    error_class = class_of_status(exc.status_code)
    response = error_response(error_class, PHRASE[error_class], exc.headers)
    response.status_code = exc.status_code
    return response


async def _unhandled(_: Request, __: Exception) -> JSONResponse:
    return error_response(ErrorClass.INTERNAL, PHRASE[ErrorClass.INTERNAL])


def install_error_handlers(app: FastAPI) -> None:
    """Answer every error of ``app`` in the one form (module docstring)."""
    app.add_exception_handler(PanelError, _panel_error)
    app.add_exception_handler(RequestValidationError, _invalid)
    app.add_exception_handler(StarletteHTTPException, _http)
    app.add_exception_handler(Exception, _unhandled)
