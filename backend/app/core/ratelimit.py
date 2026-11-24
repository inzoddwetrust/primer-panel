"""Rate limits: a fixed window per source, counted in Redis.

Translated from velo ``core/ratelimit.py`` (BE-44, BE-66), with the
``Retry-After`` of aivis ``core/rate_limit.py``.

THE COUNTER. ``INCR``, ``EXPIRE NX`` and ``TTL`` travel in one ``MULTI/EXEC``:
a key is never left counted without a TTL (a source limited for ever), and
the TTL is set on the FIRST hit only -- the window is anchored at it and ends
whole, never slid forward by later hits. ``EXPIRE NX`` needs Redis 7.0+.
The ``TTL`` of the same transaction is what the client waits: ``Retry-After``.

THE SOURCE is ``client_ip`` (``app.core.client_ip``). A source that is not a
routable public address -- loopback, private, link-local, documentation, none
at all -- is passed and never counted: it is our own infrastructure showing
through, and one shared bucket for everybody behind it would take the service
down; a limit that stops helping is chosen over that (velo, lesson 2).

REDIS DOWN: the limit fails CLOSED -- ``unavailable`` (503), the refusal
logged with the class of what failed. A caller that wants it open does not use
this dependency.

``rate_limit(bucket, limit=, window_s=)`` makes a FastAPI dependency; it keeps
no state of its own.
"""

import ipaddress
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.client_ip import client_ip
from app.core.errors import ErrorClass, PanelError
from app.core.state import get_redis

logger = logging.getLogger(__name__)

KEY_PREFIX = "ratelimit"


def limitable_source(source: str | None) -> bool:
    """True only for a routable public address (module docstring)."""
    if not source:
        return False
    try:
        return ipaddress.ip_address(source).is_global
    except ValueError:
        return False


async def count_in_window(redis: Redis, key: str, window_s: int) -> tuple[int, int]:
    """Count one hit of ``key``; the new count and the seconds the window has
    left. One transaction: the TTL is set on the first hit only."""
    pipe = redis.pipeline(transaction=True)
    pipe.incr(key)
    pipe.expire(key, window_s, nx=True)
    pipe.ttl(key)
    count, _, ttl = await pipe.execute()
    return int(count), int(ttl)


def rate_limit(
    bucket: str, *, limit: int, window_s: int
) -> Callable[[Request, Redis], Awaitable[None]]:
    """A dependency refusing the ``limit + 1``-th request of a source in a
    window of ``window_s`` seconds: ``too_many_requests`` with ``Retry-After``."""
    if limit < 1 or window_s < 1:
        raise ValueError(f"limit {limit} and window {window_s} s must be at least 1")

    async def limited(
        request: Request, redis: Annotated[Redis, Depends(get_redis)]
    ) -> None:
        source = client_ip(request)
        if not limitable_source(source):
            return
        key = f"{KEY_PREFIX}:{bucket}:{source}"
        try:
            count, ttl = await count_in_window(redis, key, window_s)
        except RedisError as error:
            logger.warning(
                "rate limit %s cannot count",
                bucket,
                extra={
                    "event": "ratelimit.unavailable",
                    "ctx": {"bucket": bucket, "error": type(error).__name__},
                },
            )
            raise PanelError(
                ErrorClass.UNAVAILABLE, "The limit cannot be counted now"
            ) from error
        if count > limit:
            # The TTL comes from the transaction that set it: 0 is a window
            # ending under a second; the client comes back in one.
            raise PanelError(
                ErrorClass.TOO_MANY_REQUESTS,
                "Too many requests",
                retry_after_s=max(ttl, 1),
            )

    return limited
