"""Probe of DM-203: the volume of the Panel's object storage survives the
recreation of its container.

The storage's compose file (``docker-compose.storage.yml``), as the machine
runs an entry: its own project, its value from an env file. An object is
written through the S3 API of RustFS -- ``curl --aws-sigv4`` inside the
storage's own container: it has no port on the host -- the container is
recreated, the object is read back. The volume is the named one of the file,
not the anonymous one the image declares (``VOLUME /data``): compose keeps an
anonymous volume over a recreation too, so the name is what tells a volume
the file owns from one it merely inherited. The pair: after ``down -v`` the
object is gone -- the data was in the volume, not in the container.
"""

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from probes.docker import ROOT, docker

PROJECT = "panel-probe-storage"
COMPOSE = ROOT / "docker-compose.storage.yml"
LOGIN = "panel-storage-root"  # the constant of the compose file
SECRET = "stand-in-secret-of-the-storage-probe-0001"  # noqa: S105 -- a stand-in
MARKER = "the Panel's storage probe, DM-203"
OBJECT = "probe-bucket/marker.txt"


@pytest.fixture
def env_file(daemon: None, tmp_path: Path) -> Iterator[Path]:
    file = tmp_path / "storage.env"
    file.write_text(f"RUSTFS_SECRET_KEY={SECRET}\n")
    yield file
    _compose(file, "down", "-v", check=False)


def _compose(
    env: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return docker(
        "compose",
        "-f",
        str(COMPOSE),
        "-p",
        PROJECT,
        "--env-file",
        str(env),
        *args,
        check=check,
    )


def _s3(
    env: Path, method: str, path: str, *body: str
) -> subprocess.CompletedProcess[str]:
    """One request of the S3 API, signed, from inside the storage's container."""
    data = ["--data-binary", body[0]] if body else []
    return _compose(
        env,
        "exec",
        "-T",
        "panel-storage",
        "curl",
        "-fsS",
        "--aws-sigv4",
        "aws:amz:us-east-1:s3",
        "--user",
        f"{LOGIN}:{SECRET}",
        "-X",
        method,
        *data,
        f"http://localhost:9000/{path}",
        check=False,
    )


def _container(env: Path) -> str:
    return _compose(env, "ps", "-q", "panel-storage").stdout.strip()


def test_probe_DM_203_storage_volume_survives_recreate(env_file: Path) -> None:
    _compose(env_file, "up", "-d", "--wait")
    first = _container(env_file)
    mounts = json.loads(docker("inspect", first).stdout)[0]["Mounts"]
    [data] = [m for m in mounts if m["Destination"] == "/data"]
    assert (data["Type"], data["Name"]) == ("volume", f"{PROJECT}_panel_storage_data")

    made = _s3(env_file, "PUT", "probe-bucket")
    assert made.returncode == 0, made.stderr
    put = _s3(env_file, "PUT", OBJECT, MARKER)
    assert put.returncode == 0, put.stderr

    _compose(env_file, "up", "-d", "--force-recreate", "--wait")
    assert _container(env_file) not in ("", first)
    read = _s3(env_file, "GET", OBJECT)
    assert (read.returncode, read.stdout) == (0, MARKER), read.stderr

    # the pair: with its volume removed, the object is gone
    _compose(env_file, "down", "-v")
    _compose(env_file, "up", "-d", "--wait")
    gone = _s3(env_file, "GET", OBJECT)
    assert gone.returncode != 0 and MARKER not in gone.stdout


def test_the_storage_volume_is_the_file_s_own(env_file: Path) -> None:
    """``/data`` of the storage is the named volume of the compose file, as
    compose will run it: the image's own ``VOLUME`` would be anonymous."""
    config = json.loads(_compose(env_file, "config", "--format", "json").stdout)
    volumes = config["services"]["panel-storage"]["volumes"]
    assert [(v["type"], v["source"], v["target"]) for v in volumes] == [
        ("volume", "panel_storage_data", "/data")
    ]
    assert "panel_storage_data" in config["volumes"]
