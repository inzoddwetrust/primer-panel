"""The compose file refuses to run with any variable of the stack missing.

Changed by DM-148: the variables are the Panel's -- the blank's three seams of
its service are gone, ``REDIS_PASSWORD`` came with Redis.

Changed by DM-149: ``SUPERADMIN_TELEGRAM_ID`` (a param of the passport).
Changed by DM-150: ``DOMAIN_FRONTEND`` and ``DOMAIN_API``.
Changed by DM-158: ``OPS_REPO`` (a param of the passport).
Changed by DM-160: ``COMMS_API_URL`` and ``COMMS_SERVICE_TOKEN`` (seams of
comms).
"""

from pathlib import Path

from probes.docker import ROOT, docker

STACK_ENV = {
    "POSTGRES_PASSWORD": "probe-password",
    "REDIS_PASSWORD": "probe-redis-password",
    "EDITION": "core",
    "API_BASE_URL": "api.probe.test",
    "LANGUAGES": "en,ru",
    "DEFAULT_LANGUAGE": "en",
    "SUPERADMIN_TELEGRAM_ID": "7000000001",
    "DOMAIN_FRONTEND": "panel.probe.test",
    "DOMAIN_API": "api.panel.probe.test",
    "OPS_REPO": "file:///nonexistent/primer-ops-of-the-probe",
    "COMMS_API_URL": "http://comms-comms-app:8000",
    "COMMS_SERVICE_TOKEN": "stand-in-service-token-of-the-probe",
}


def _config(env_file: Path) -> tuple[int, str]:
    result = docker(
        "compose",
        "-f",
        str(ROOT / "docker-compose.yml"),
        "-p",
        "panel-probe",
        "--env-file",
        str(env_file),
        "config",
        "-q",
        check=False,
    )
    return result.returncode, result.stderr


def test_compose_needs_every_variable_of_the_stack(
    daemon: None, tmp_path: Path
) -> None:
    full = tmp_path / "full.env"
    full.write_text("".join(f"{k}={v}\n" for k, v in STACK_ENV.items()))
    assert _config(full) == (0, "")
    for missing in STACK_ENV:
        partial = tmp_path / f"without-{missing}.env"
        partial.write_text(
            "".join(f"{k}={v}\n" for k, v in STACK_ENV.items() if k != missing)
        )
        code, err = _config(partial)
        assert code != 0
        assert missing in err
