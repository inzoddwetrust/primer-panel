"""Probe of DM-148: ``primer.yaml`` and the live stack pass machine v0.1.8.

The machine reads the Panel on a box in two places: its loader takes
``primer.yaml``, and after ``up`` its conformance reads what the live app says
of itself -- ``/health``, ``/ready`` and the app's log lines (TZ 11 items
4-5, 8; protocol 9). ``pridem check`` in CI covers the files; this probe
covers the live stack, with the machine's own functions of
``pridem.conformance.stack`` -- the job installs the machine at
``PRIDEM_COMMIT`` beside the backend's lock.

The stack is the product's own ``docker-compose.yml``: the app on the image
the session built, Postgres and Redis as the file pins them; every variable
of the stack gets a stand-in, as ``pridem check`` gives them. The database is
migrated first by the stack's ``migrate``, then the app is started; ``/health``
and ``/ready`` are read from inside the app's container (no port is
published, as on a box) and the log is read after them.

The pair: a ``/health`` with one field taken away is not passed by the same
functions -- the check can be red.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from pridem.conformance.stack import (
    check_health,
    check_logs,
    check_max_body,
    check_ready,
)
from pridem.stacks.schema import Product, load_primer_yaml

from probes.docker import LABEL, ROOT, docker

PROJECT = "panel-probe-dm148"
ENTRY = "primer-panel"

# Stand-ins for every key of env in primer.yaml; no value has the form of a
# real secret.
STACK_ENV = {
    "POSTGRES_PASSWORD": "probe-stand-in-postgres",
    "REDIS_PASSWORD": "probe-stand-in-redis",
    "EDITION": "core",
    "API_BASE_URL": "api.probe.test",
    "LANGUAGES": "en,ru",
    "DEFAULT_LANGUAGE": "en",
}

READ = (
    "import sys, urllib.error, urllib.request\n"
    "try:\n"
    "    r = urllib.request.urlopen('http://127.0.0.1:8000' + sys.argv[1], timeout=5)\n"
    "    print(r.status); print(r.read().decode())\n"
    "except urllib.error.HTTPError as e:\n"
    "    print(e.code); print(e.read().decode())\n"
)


def _compose(files: list[Path], env_file: Path, *args: str) -> str:
    command = ["compose", "-p", PROJECT, "--env-file", str(env_file)]
    for file in files:
        command += ["-f", str(file)]
    return docker(*command, *args).stdout


@pytest.fixture
def stack(backend_runtime: str, tmp_path: Path) -> Iterator[tuple[list[Path], Path]]:
    """The product's compose with the session's app image; removed after."""
    env_file = tmp_path / "stack.env"
    env_file.write_text("".join(f"{k}={v}\n" for k, v in STACK_ENV.items()))
    override = tmp_path / "override.json"
    override.write_text(
        json.dumps(
            {
                "services": {
                    "app": {
                        "image": backend_runtime,
                        "pull_policy": "never",
                        "labels": [LABEL],
                    }
                }
            }
        )
    )
    files = [ROOT / "docker-compose.yml", override]
    try:
        _compose(
            files, env_file, "up", "-d", "--no-build", "--wait", "postgres", "redis"
        )
        _compose(
            files,
            env_file,
            "run",
            "--rm",
            "--no-deps",
            "app",
            "python",
            "-m",
            "alembic",
            "upgrade",
            "head",
        )
        _compose(files, env_file, "up", "-d", "--no-build", "--wait", "app")
        yield files, env_file
    finally:
        _compose(files, env_file, "down", "-v", "--remove-orphans")


def _read(files: list[Path], env_file: Path, path: str) -> tuple[int, bytes]:
    out = _compose(files, env_file, "exec", "-T", "app", "python", "-c", READ, path)
    status, _, body = out.partition("\n")
    return int(status), body.rstrip("\n").encode()


def test_probe_DM_148_passes_the_machine_v0_1_8(
    stack: tuple[list[Path], Path],
) -> None:
    product = load_primer_yaml(ROOT / "primer.yaml")
    assert isinstance(product, Product)
    assert product.name == ENTRY
    stage = product.stacks[ENTRY]
    assert stage.migrate is not None

    files, env_file = stack
    status, health = _read(files, env_file, "/health")
    assert status == 200
    ready, _ = _read(files, env_file, "/ready")
    logs = _compose(
        files, env_file, "logs", "--no-log-prefix", "--no-color", "app"
    ).splitlines()

    problems = [
        *check_health(health, migrate=True, stack_name=product.name),
        *check_ready(ready),
        *check_max_body(product, ENTRY, health),
        *check_logs(logs, stack_name=product.name),
    ]
    assert [problem.line() for problem in problems] == []
    document = json.loads(health)
    assert document["status"] == "ok"
    assert set(document["checks"]) == {"db", "schema", "redis"}
    assert logs

    # The pair: the same functions refuse a /health without one of its fields.
    broken = json.dumps({k: v for k, v in document.items() if k != "checks"})
    assert check_health(broken.encode(), migrate=True, stack_name=product.name)
