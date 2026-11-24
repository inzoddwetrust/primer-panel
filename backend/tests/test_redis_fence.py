"""The suite refuses a Redis database other than its own (tests/conftest.py).

The stack's live Redis is database 0 (docker-compose.yml); the suite flushes
its database before tests, so a wrong ``REDIS_URL`` must stop it before the
first test touches Redis. Measured on the suite itself: a run given database
0 ends with pytest's exit 2 and the reason; given 15 (this run's), it runs.
"""

import os
import subprocess
import sys

from tests.conftest import BACKEND, TEST_REDIS_DB, redis_db_of

PROBE = "tests/test_health_redis.py::test_redis_down_is_redis_error_and_degraded"


def _suite(redis_url: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "REDIS_URL": redis_url}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", PROBE],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_suite_refuses_any_redis_database_but_its_own(redis_url: str) -> None:
    other = redis_url.rsplit("/", 1)[0] + "/0"
    refused = _suite(other)
    assert refused.returncode == 2, refused.stdout
    assert "its database must be 15" in refused.stdout
    taken = _suite(redis_url)  # the pair: its own database runs the test
    assert taken.returncode == 0, taken.stdout


def test_the_database_number_is_read_from_the_path() -> None:
    assert redis_db_of(f"redis://h:6379/{TEST_REDIS_DB}") == TEST_REDIS_DB
    assert redis_db_of("redis://:p@h:6379/0") == 0
    assert redis_db_of("redis://h:6379") is None
    assert redis_db_of("redis://h:6379/x") is None
