"""Redis: the client of one application and the ``redis`` check of ``/health``.

The client is built by ``create_app`` (one connection pool per application)
and closed in its lifespan; requests reach it through ``app.core.state``.
Every connect and every read gives up after ``CHECK_TIMEOUT_S``: a hung
connection does not hold a request for ever (velo BE-44). Replies are
decoded to ``str``.
"""

from redis.asyncio import ConnectionPool, Redis

from primer_report import CHECK_TIMEOUT_S

REDIS = "redis"
"""The name of the Redis check in ``/health.checks``."""


def make_redis(url: str) -> Redis:
    """A client on its own pool; nothing connects until it is used."""
    pool = ConnectionPool.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=CHECK_TIMEOUT_S,
        socket_timeout=CHECK_TIMEOUT_S,
    )
    return Redis(connection_pool=pool)


async def ping(client: Redis) -> bool:
    """The ``redis`` check: ``PING`` answered ``PONG``."""
    answer = await client.ping()
    return answer is True
