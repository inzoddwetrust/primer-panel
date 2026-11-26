"""A server's passport in the Panel, on the grid of DM-158: reading, an edit of
a field and of a secret, the refusals, "apply" and its state.

The ops repository is a real bare repository of the test, the passports are
encrypted by the real ``sops`` (tests/ops.py); nothing of ``git`` or ``sops`` is
faked but where a test says so.
"""
# ruff: noqa: S608, S105 -- the SQL and the stand-in secrets are the tests' own

import base64
import hashlib
import json
import uuid
from collections.abc import Callable, Coroutine, Mapping

import pytest

from app.ops.passport import age_public_key
from app.ops.repo import OpsRepo, known_hosts
from app.ops.run import Ran
from app.ops.run import run as real_run
from tests.conftest import execute, query_scalar
from tests.ops import PASSPORT, SERVER, OpsSide
from tests.people import World

API = "/api/v1/servers"
SECRET = "stand-in-telegram-token-of-the-tests"


def server(
    world: World, name: str = SERVER, role: str = "test", project: str = "a"
) -> uuid.UUID:
    server_id = uuid.uuid4()
    execute(
        world.url,
        "INSERT INTO servers (id, project_id, name, role, box_id, box_key_public) "
        f"VALUES ('{server_id}', '{world.projects[project]}', '{name}', '{role}', "
        f"'{uuid.uuid4()}', 'key')",
    )
    return server_id


def read(
    world: World, server_id: uuid.UUID, who: str = "super", expect: int = 200
) -> dict[str, object]:
    found = world.call(who, "GET", f"{API}/{server_id}/passport", expect=expect)
    assert isinstance(found, dict)
    return found


def put_field(
    world: World,
    server_id: uuid.UUID,
    base: object,
    path: list[str],
    value: object,
    who: str = "super",
    expect: int = 200,
) -> dict[str, object]:
    body = {"base": base, "path": path, "value": value}
    found = world.call(
        who, "PUT", f"{API}/{server_id}/passport/field", body, expect=expect
    )
    assert isinstance(found, dict)
    return found


def put_secret(
    world: World,
    server_id: uuid.UUID,
    base: object,
    value: str,
    *,
    stack: str | None = None,
    key: str | None = None,
    tls: str | None = None,
    who: str = "super",
    expect: int = 200,
) -> dict[str, object]:
    body: dict[str, object] = {"base": base, "value": value}
    for name, given in (("stack", stack), ("key", key), ("tls", tls)):
        if given is not None:
            body[name] = given
    found = world.call(
        who, "PUT", f"{API}/{server_id}/passport/secret", body, expect=expect
    )
    assert isinstance(found, dict)
    return found


def apply(
    world: World,
    server_id: uuid.UUID,
    who: str = "super",
    confirmed: bool = False,
    expect: int = 201,
) -> dict[str, object]:
    found = world.call(
        who,
        "POST",
        f"{API}/{server_id}/passport/apply",
        {"confirmed": confirmed},
        expect=expect,
    )
    assert isinstance(found, dict)
    return found


def verdict_row(
    world: World,
    server_id: uuid.UUID,
    run_id: str,
    fact: Mapping[str, object],
    *,
    result: str = "green",
    verified: bool = True,
) -> None:
    """A verdict of the server whose ``fetch_passport`` read ``fact``."""
    step = {
        "stack": "pridem-passport",
        "name": "fetch_passport",
        "phase": "main",
        "order": 3,
        "status": "ok",
        "verify": fact,
    }
    body = json.dumps({"run_id": run_id, "result": result, "steps": [step]})
    execute(
        world.url,
        f"INSERT INTO runs (run_id, server_id) VALUES ('{run_id}', '{server_id}')",
    )
    execute(
        world.url,
        "INSERT INTO verdicts (run_id, server_id, body, envelope_signature, "
        "verified, signed_on_send, report_llm) VALUES "
        f"('{run_id}', '{server_id}', $${body}$$::jsonb, 'sig', {verified}, "
        "false, '')",
    )


def passer(world: World) -> str:
    """A person of project A with ``passport`` alone."""
    world.person("pass_a", 7000000777)
    world.join("pass_a", world.invite("super", "a", ["passport"]))
    return "pass_a"


def message_of(side: OpsSide) -> str:
    import subprocess

    return subprocess.run(
        ["git", "--git-dir", str(side.remote), "log", "-1", "--format=%B", "main"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout


# --- reading ----------------------------------------------------------------------


def test_reading_names_the_secrets_and_shows_none(
    ops_world: World, ops_side: OpsSide
) -> None:
    sid = server(ops_world)
    found = read(ops_world, sid)
    assert found["state"] == "ready"
    assert found["base"] == ops_side.head()
    assert found["version"] == 7
    assert found["secrets"] == [
        {"stack": "comms", "key": "TELEGRAM_BOT_TOKEN", "state": "set"},
        {"stack": "comms", "key": "MAILGUN_API_KEY", "state": "switched_off"},
    ]
    assert found["tls"] == []
    assert found["problems"] == []
    assert {"path": ["domains", "frontend"], "value": "test.velo.example"} in (
        found["fields"]  # type: ignore[operator]
    )
    assert found["rules"] == [
        {"path": ["policies", "gc", "keep_releases"], "rule": "keep_releases"}
    ]
    assert found["apply"] == {"commit": None, "state": "unknown"}
    assert found["panel_key"] == ops_side.panel_public
    assert SECRET not in json.dumps(found)


def test_any_member_reads_a_stranger_does_not(
    ops_world: World, ops_side: OpsSide
) -> None:
    sid = server(ops_world)
    read(ops_world, sid, who="people_a")
    for who in ("admin_b", "outsider"):
        read(ops_world, sid, who=who, expect=404)


def test_a_passport_not_in_ops_is_absent(ops_world: World, ops_side: OpsSide) -> None:
    sid = server(ops_world, name="velo-test-2")
    found = read(ops_world, sid)
    assert found == {"state": "absent", "panel_key": ops_side.panel_public}
    base = ops_side.head()
    put_field(ops_world, sid, base, ["domains", "frontend"], "x.example", expect=404)


def test_a_passport_not_for_the_panel_s_key(
    ops_world: World, ops_side: OpsSide
) -> None:
    text = PASSPORT.format(name=SERVER)
    base = ops_side.put(SERVER, ops_side.encrypt(text, [ops_side.box_public]))
    sid = server(ops_world)
    found = read(ops_world, sid)
    assert found == {"state": "not-recipient", "panel_key": ops_side.panel_public}
    put_field(ops_world, sid, base, ["domains", "frontend"], "x.example", expect=409)


def test_a_passport_the_machine_refuses_is_shown_and_mended(
    ops_world: World, ops_side: OpsSide
) -> None:
    broken = PASSPORT.format(name=SERVER).replace(
        "keep_releases: 2", "keep_releases: 0"
    )
    ops_side.put(SERVER, ops_side.encrypt(broken))
    sid = server(ops_world)
    found = read(ops_world, sid)
    assert found["state"] == "invalid"
    problems = found["problems"]
    assert isinstance(problems, list) and problems
    assert all(p.startswith("policies.gc.keep_releases [") for p in problems)
    assert SECRET not in json.dumps(found)
    # an edit that leaves it refused is refused; the one that mends it passes
    base = found["base"]
    put_field(ops_world, sid, base, ["domains", "api"], "a.example", expect=422)
    put_field(ops_world, sid, base, ["policies", "gc", "keep_releases"], 1)
    assert read(ops_world, sid)["state"] == "ready"


def _pem(kind: str, body: str) -> str:
    """A PEM block of stand-in text, indented as a block scalar of ``tls``."""
    return "".join(
        f"      {line}\n"
        for line in (
            f"-----BEGIN {kind}-----",
            f"{body}-of-the-tests",
            f"-----END {kind}-----",
        )
    )


def test_tls_is_named_and_never_shown(ops_world: World, ops_side: OpsSide) -> None:
    provided = PASSPORT.format(name=SERVER).replace(
        "  ssl: letsencrypt\n",
        "  ssl: provided\n  tls:\n    cert: |\n"
        + _pem("CERTIFICATE", "stand-in-certificate")
        + "    key: |\n"
        + _pem("PRIVATE KEY", "stand-in-private-key"),
    )
    ops_side.put(SERVER, ops_side.encrypt(provided))
    sid = server(ops_world)
    found = read(ops_world, sid)
    assert found["tls"] == [
        {"key": "cert", "state": "set"},
        {"key": "key", "state": "set"},
    ]
    text = json.dumps(found)
    assert "stand-in-certificate" not in text and "stand-in-private-key" not in text
    cert = (
        "-----BEGIN CERTIFICATE-----\na-new-certificate-0001\n"
        "-----END CERTIFICATE-----\n"
    )
    put_secret(ops_world, sid, found["base"], cert, tls="cert")
    assert "a-new-certificate-0001" in ops_side.as_box(SERVER)
    assert "a-new-certificate-0001" not in json.dumps(read(ops_world, sid))


def test_ops_out_of_reach_is_unavailable(world: World) -> None:
    """The world's Panel has an address of primer-ops where nothing is: it
    started, and the passport answers 503 -- the pair of the image's probe."""
    sid = server(world)
    read(world, sid, expect=503)
    put_field(world, sid, "0" * 40, ["domains", "api"], "a.example", expect=503)


# --- edits ------------------------------------------------------------------------


def test_an_edit_is_one_commit_the_box_reads(
    ops_world: World, ops_side: OpsSide
) -> None:
    sid = server(ops_world)
    base = ops_side.head()
    made = put_field(ops_world, sid, base, ["domains", "frontend"], "new.velo.example")
    assert made == {"commit": ops_side.head(), "version": 8}
    plain = ops_side.as_box(SERVER)
    assert "frontend: new.velo.example" in plain
    assert "version: 8" in plain
    user = ops_world.people["super"].id
    assert message_of(ops_side) == (
        f"passport {SERVER}: v8, field domains.frontend\n\nEdited-By: {user}\n\n"
    )
    assert (
        query_scalar(
            ops_world.url,
            "SELECT details->>'path' FROM audit WHERE action = 'passport.edit'",
        )
        == "domains.frontend"
    )


def test_a_secret_is_replaced_and_given_back_nowhere(
    ops_world: World, ops_side: OpsSide
) -> None:
    sid = server(ops_world)
    value = "replaced-telegram-token-0002"
    made = put_secret(
        ops_world,
        sid,
        ops_side.head(),
        value,
        stack="comms",
        key="TELEGRAM_BOT_TOKEN",
    )
    assert set(made) == {"commit", "version"}
    assert f"TELEGRAM_BOT_TOKEN: {value}" in ops_side.as_box(SERVER)
    assert value not in message_of(ops_side)
    assert value.encode() not in ops_side.raw(SERVER)  # sops holds it encrypted
    # a key of a stack the passport had none of is added
    put_secret(
        ops_world, sid, ops_side.head(), "new-key-of-velo-0003", stack="velo", key="K"
    )
    assert "K: new-key-of-velo-0003" in ops_side.as_box(SERVER)


def test_a_secret_goes_to_sops_by_stdin(
    ops_world: World, ops_side: OpsSide, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[list[str], bytes]] = []

    async def spy(argv: list[str], **kwargs: object) -> Ran:
        stdin = kwargs.get("stdin", b"")
        seen.append((list(argv), stdin if isinstance(stdin, bytes) else b""))
        return await real_run(argv, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("app.ops.passport.run", spy)
    sid = server(ops_world)
    value = "replaced-telegram-token-0004"
    put_secret(
        ops_world, sid, ops_side.head(), value, stack="comms", key="TELEGRAM_BOT_TOKEN"
    )
    sets = [(argv, stdin) for argv, stdin in seen if argv[1] == "set"]
    assert sets, "sops set ran"
    assert all(value not in " ".join(argv) for argv, _ in seen)
    assert json.dumps(value).encode() in [stdin for _, stdin in sets]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["asked", "comms", "TELEGRAM_BOT_TOKEN"], "by-the-field-route-0005"),
        (["policies", "tls", "cert"], "by-the-field-route-0006"),
        (["version"], 99),
        (["domains", "api"], None),
    ],
    ids=["asked", "tls", "version", "null"],
)
def test_what_a_field_is_not(
    ops_world: World, ops_side: OpsSide, path: list[str], value: object
) -> None:
    sid = server(ops_world)
    before = ops_side.head()
    put_field(ops_world, sid, before, path, value, expect=422)
    assert ops_side.head() == before


def test_a_secret_is_one_place(ops_world: World, ops_side: OpsSide) -> None:
    sid = server(ops_world)
    base = ops_side.head()
    put_secret(ops_world, sid, base, "value-of-the-test-0007", expect=422)
    put_secret(
        ops_world,
        sid,
        base,
        "value-of-the-test-0007",
        stack="comms",
        key="K",
        tls="cert",
        expect=422,
    )
    put_secret(
        ops_world, sid, base, "value-of-the-test-0007", stack="comms", expect=422
    )


def test_an_edit_the_machine_refuses_commits_nothing(
    ops_world: World, ops_side: OpsSide
) -> None:
    sid = server(ops_world)
    before = ops_side.head()
    refused = put_secret(
        ops_world,
        sid,
        before,
        "tiny-0008",
        stack="comms",
        key="TELEGRAM_BOT_TOKEN",
        expect=422,
    )
    message = refused["error"]["message"]  # type: ignore[index]
    assert "asked.comms.TELEGRAM_BOT_TOKEN [" in message
    assert "tiny-0008" not in message
    assert ops_side.head() == before


@pytest.mark.parametrize(
    ("path", "value", "why"),
    [
        (["server", "name"], "velo-test-9", "server.name is the server's name"),
        (["server", "role"], "prod", "server.role is the owner's to change"),
        (["server"], {"name": SERVER}, "server.name is the server's name"),
    ],
    ids=["name", "role", "server"],
)
def test_the_name_and_the_role_are_not_fields(
    ops_world: World, ops_side: OpsSide, path: list[str], value: object, why: str
) -> None:
    """The name the box reads its passport by and the role that decides the
    permission of a deploy are no fields, by their path or by one above."""
    sid = server(ops_world)
    before = ops_side.head()
    refused = put_field(ops_world, sid, before, path, value, expect=422)
    assert refused["error"]["message"].startswith(why)  # type: ignore[index]
    assert ops_side.head() == before
    # the pair: another field of server goes
    put_field(ops_world, sid, before, ["server", "os"], "ubuntu-24.04")


def test_an_edit_needs_passport(ops_world: World, ops_side: OpsSide) -> None:
    sid = server(ops_world)
    base = ops_side.head()
    put_field(ops_world, sid, base, ["domains", "api"], "a.example", "staff_a", 403)
    put_field(ops_world, sid, base, ["domains", "api"], "b.example", "admin_b", 404)
    who = passer(ops_world)
    put_field(ops_world, sid, base, ["domains", "api"], "c.example", who)


# --- the races of an edit, serially ------------------------------------------------


def test_a_stale_base_is_refused(ops_world: World, ops_side: OpsSide) -> None:
    sid = server(ops_world)
    old = ops_side.head()
    put_field(ops_world, sid, old, ["domains", "api"], "a.example")
    put_field(ops_world, sid, old, ["domains", "api"], "b.example", expect=409)
    put_field(ops_world, sid, "f" * 40, ["domains", "api"], "b.example", expect=409)
    assert "api: a.example" in ops_side.as_box(SERVER)


def test_a_base_older_by_another_file_only_goes(
    ops_world: World, ops_side: OpsSide
) -> None:
    sid = server(ops_world)
    old = ops_side.head()
    other = PASSPORT.format(name="velo-test-2")
    ops_side.put("velo-test-2", ops_side.encrypt(other))
    made = put_field(ops_world, sid, old, ["domains", "api"], "a.example")
    assert made["commit"] == ops_side.head()
    assert "version: 7" in ops_side.as_box("velo-test-2")


def _pushing_first(
    ops_side: OpsSide, name: str
) -> Callable[[OpsRepo, str], Coroutine[object, object, bool]]:
    real = OpsRepo.push
    done: list[bool] = []

    async def push(self: OpsRepo, commit: str) -> bool:
        if not done:
            done.append(True)
            ops_side.put(name, ops_side.encrypt(PASSPORT.format(name=name)))
        return await real(self, commit)

    return push


def test_a_push_past_the_panel_is_tried_again(
    ops_world: World, ops_side: OpsSide, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Someone pushes another file between the Panel's fetch and its push:
    the push is refused, the Panel commits again on the new head."""
    monkeypatch.setattr(OpsRepo, "push", _pushing_first(ops_side, "velo-test-2"))
    sid = server(ops_world)
    made = put_field(ops_world, sid, ops_side.head(), ["domains", "api"], "a.example")
    assert made["commit"] == ops_side.head()
    assert "api: a.example" in ops_side.as_box(SERVER)
    assert "version: 7" in ops_side.as_box("velo-test-2")


def test_a_push_past_the_panel_of_the_same_file_is_refused(
    ops_world: World, ops_side: OpsSide, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(OpsRepo, "push", _pushing_first(ops_side, SERVER))
    sid = server(ops_world)
    before = ops_side.head()
    put_field(ops_world, sid, before, ["domains", "api"], "a.example", expect=409)
    assert "api: api-test.velo.example" in ops_side.as_box(SERVER)


# --- a passport from a file ----------------------------------------------------------


def test_a_server_on_a_passport_file(ops_world: World, ops_side: OpsSide) -> None:
    sid = server(ops_world)
    verdict_row(ops_world, sid, "2026-11-26T10:00:00Z-aa01", {"source": "ops"})
    verdict_row(ops_world, sid, "2026-11-26T11:00:00Z-aa02", {"source": "file"})
    assert read(ops_world, sid) == {"state": "file"}
    base = ops_side.head()
    refused = put_field(
        ops_world, sid, base, ["domains", "api"], "a.example", expect=409
    )
    assert "a file on the box" in refused["error"]["message"]  # type: ignore[index]
    apply(ops_world, sid, expect=409)
    assert ops_side.head() == base
    # the pair: the newest fact says ops again
    verdict_row(ops_world, sid, "2026-11-26T12:00:00Z-aa03", {"source": "ops"})
    assert read(ops_world, sid)["state"] == "ready"


def test_no_permission_is_told_before_the_file(
    ops_world: World, ops_side: OpsSide
) -> None:
    """Without ``passport`` the refusal is 403 before anything that tells the
    server's state: not the 409 of a passport from a file. The pair: with it,
    the 409."""
    sid = server(ops_world)
    verdict_row(ops_world, sid, "2026-11-26T11:00:00Z-aa02", {"source": "file"})
    base = ops_side.head()
    put_field(ops_world, sid, base, ["domains", "api"], "a.example", "staff_a", 403)
    apply(ops_world, sid, "staff_a", expect=403)
    who = passer(ops_world)
    put_field(ops_world, sid, base, ["domains", "api"], "a.example", who, 409)
    apply(ops_world, sid, who, expect=409)


def test_an_unverified_fact_of_a_file_counts_nothing(
    ops_world: World, ops_side: OpsSide
) -> None:
    sid = server(ops_world)
    verdict_row(
        ops_world, sid, "2026-11-26T11:00:00Z-aa02", {"source": "file"}, verified=False
    )
    assert read(ops_world, sid)["state"] == "ready"


# --- apply --------------------------------------------------------------------------


def test_apply_is_the_command_update(ops_world: World, ops_side: OpsSide) -> None:
    sid = server(ops_world)
    who = passer(ops_world)
    made = apply(ops_world, sid, who)
    assert (made["verb"], made["args"]) == ("update", {})
    apply(ops_world, sid, "staff_a", expect=403)  # deploy_test, not passport
    apply(ops_world, sid, "admin_b", expect=404)
    assert (
        query_scalar(
            ops_world.url, "SELECT count(*) FROM audit WHERE action = 'passport.apply'"
        )
        == 1
    )


def test_apply_on_prod_is_confirmed_first(ops_world: World, ops_side: OpsSide) -> None:
    sid = server(ops_world, role="prod")
    apply(ops_world, sid, expect=409)
    apply(ops_world, sid, confirmed=True)


def test_the_state_of_apply(ops_world: World, ops_side: OpsSide) -> None:
    sid = server(ops_world)
    old = ops_side.head()
    put_field(ops_world, sid, old, ["domains", "api"], "a.example")
    new = ops_side.head()
    verdict_row(
        ops_world,
        sid,
        "2026-11-26T10:00:00Z-aa01",
        {"source": "ops", "ops_commit": old},
    )
    assert read(ops_world, sid)["apply"] == {"commit": old, "state": "pending"}
    # a red verdict and an unverified one do not apply it
    fact = {"source": "ops", "ops_commit": new}
    verdict_row(ops_world, sid, "2026-11-26T11:00:00Z-aa02", fact, result="red")
    verdict_row(ops_world, sid, "2026-11-26T11:30:00Z-aa03", fact, verified=False)
    assert read(ops_world, sid)["apply"] == {"commit": old, "state": "pending"}
    verdict_row(ops_world, sid, "2026-11-26T12:00:00Z-aa04", fact)
    assert read(ops_world, sid)["apply"] == {"commit": new, "state": "applied"}
    # a later edit of another file keeps it applied: the server's file is the same
    ops_side.put("velo-test-2", ops_side.encrypt(PASSPORT.format(name="velo-test-2")))
    assert read(ops_world, sid)["apply"] == {"commit": new, "state": "applied"}


# --- the parts ----------------------------------------------------------------------


def test_the_panel_s_age_key_is_shown_by_its_recipient(ops_side: OpsSide) -> None:
    secret = ops_side.places.age_key.read_text()
    assert age_public_key(secret) == ops_side.panel_public
    assert age_public_key(ops_side.box_key.read_text()) == ops_side.box_public
    with pytest.raises(ValueError, match="not a key of age"):
        age_public_key(secret.replace("AGE-SECRET-KEY-1", "AGE-SECRET-KEY-2"))


# GitHub's published SHA256 fingerprints, written out (not the code's keys).
GITHUB_FINGERPRINTS = {
    "ssh-rsa": "uNiVztksCsDhcc0u9e8BujQXVUpKZIDTMczCvj3tD2s",
    "ecdsa-sha2-nistp256": "p2QAMXNIC1TJYWeIOttrVc98/R1BUFWu3/LiyKgUfQM",
    "ssh-ed25519": "+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU",
}


def test_the_host_keys_are_github_s_on_port_443() -> None:
    found: dict[str, str] = {}
    for line in known_hosts().splitlines():
        host, kind, blob = line.split()
        assert host == "[ssh.github.com]:443"
        digest = hashlib.sha256(base64.b64decode(blob)).digest()
        found[kind] = base64.b64encode(digest).decode().rstrip("=")
    assert found == GITHUB_FINGERPRINTS


def test_the_ssh_of_git(ops_side: OpsSide) -> None:
    """The form of ssh's command: the host's keys strictly, the Panel's file
    only, its write key only, out through the proxy."""
    places = ops_side.places
    env = OpsRepo("file:///x", places).env()
    ssh = env["GIT_SSH_COMMAND"]
    for part in (
        "ssh -F none ",
        f"-i {places.write_key} ",
        "-o IdentitiesOnly=yes ",
        "-o BatchMode=yes ",
        "-o StrictHostKeyChecking=yes ",
        "-o GlobalKnownHostsFile=none ",
        f"-o UserKnownHostsFile={places.home / 'known_hosts'} ",
        "-m app.ops.connect %h %p",
    ):
        assert part in ssh, part
    assert "accept-new" not in ssh
