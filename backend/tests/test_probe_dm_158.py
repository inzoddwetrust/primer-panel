"""Probes of DM-158: a server's passport in the Panel -- an edit is a commit of
primer-ops the box decrypts; no answer of the API gives a secret's value;
"apply" is the command ``update`` whose green verdict read the edit's commit.

primer-ops is a bare repository of the test, the passports are encrypted by
the real ``sops`` for the Panel's key and a box's (tests/ops.py)."""

import json
import logging
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from pridem.protocol import verdict_bytes
from pridem.stacks.passport import load_passport
from starlette.routing import BaseRoute

from tests.conftest import query_scalar
from tests.failing import inner_app
from tests.fake_box import RUN_ID, verdict
from tests.ops import PASSPORT, SERVER, OpsSide
from tests.people import World
from tests.test_agent import registered, server_of
from tests.test_passport import apply, put_field, put_secret, read, server

MARKER = "MARKER-of-a-secret-DM158-0001"
TLS_MARKER = "MARKER-of-a-tls-key-DM158-0002"


def test_probe_DM_158_edit_is_an_ops_commit_the_box_decrypts(
    ops_world: World, ops_side: OpsSide, tmp_path: Path
) -> None:
    """An edit of a field is one new commit of primer-ops; the box, with its
    own key, reads the new value, the version one up, and the machine's loader
    passes what it reads. The pair: before the edit the box reads the old."""
    sid = server(ops_world)
    base = ops_side.head()
    assert "frontend: test.velo.example" in ops_side.as_box(SERVER)
    made = put_field(ops_world, sid, base, ["domains", "frontend"], "new.velo.example")
    assert made["commit"] == ops_side.head() != base
    plain = ops_side.as_box(SERVER)
    assert "frontend: new.velo.example" in plain
    copy = tmp_path / "passport.yaml"
    copy.write_text(plain)
    passport = load_passport(copy)
    assert passport.version == 8
    assert passport.domains["frontend"] == "new.velo.example"
    assert "frontend: test.velo.example" in ops_side.as_box(SERVER, base)


def _api_routes(routes: list[BaseRoute]) -> list[APIRoute]:
    """Every route of the application, through the routers it includes."""
    found: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            found.append(route)
        inner = getattr(route, "original_router", None)
        if inner is not None:
            found += _api_routes(inner.routes)
    return found


def _value(name: str, found: dict[str, str]) -> str:
    if "server" in name:
        return found["server"]
    if "project" in name:
        return found["project"]
    if "user" in name:
        return found["user"]
    if "run" in name:
        return RUN_ID
    return "00000000-0000-0000-0000-000000000000"


def test_probe_DM_158_no_answer_gives_a_secret(
    ops_world: World, ops_side: OpsSide, caplog: pytest.LogCaptureFixture
) -> None:
    """A secret and a tls key written through the Panel: every GET route of the
    application, its path filled, as the superadmin and as a member with
    ``passport``, answers without either value -- body and headers -- and
    neither is in the answers of the edits, a log line, the audit or the
    message of the commit. The pair: the box decrypts both."""
    caplog.set_level(logging.DEBUG)
    provided = PASSPORT.format(name=SERVER).replace(
        "  ssl: letsencrypt\n",
        "  ssl: provided\n  tls:\n    cert: |\n"
        "      -----BEGIN CERTIFICATE-----\n      stand-in-certificate-0003\n"
        "      -----END CERTIFICATE-----\n    key: |\n"
        "      -----BEGIN PRIVATE KEY-----\n      stand-in-private-key-0004\n"
        "      -----END PRIVATE KEY-----\n",
    )
    ops_side.put(SERVER, ops_side.encrypt(provided))
    sid = server(ops_world)
    ops_world.person("pass_a", 7000000777)
    ops_world.join("pass_a", ops_world.invite("super", "a", ["passport"]))
    answers: list[str] = []
    made = put_secret(
        ops_world, sid, ops_side.head(), MARKER, stack="comms", key="TELEGRAM_BOT_TOKEN"
    )
    answers.append(json.dumps(made))
    key = f"-----BEGIN PRIVATE KEY-----\n{TLS_MARKER}\n-----END PRIVATE KEY-----\n"
    made = put_secret(ops_world, sid, ops_side.head(), key, tls="key", who="pass_a")
    answers.append(json.dumps(made))
    refused = put_secret(
        ops_world, sid, "0" * 40, MARKER, stack="comms", key="X", expect=409
    )
    answers.append(json.dumps(refused))

    gets = [
        route
        for route in _api_routes(inner_app(ops_world.client.app).routes)
        if "GET" in (route.methods or set())
    ]
    found = {
        "server": str(sid),
        "project": str(ops_world.projects["a"]),
        "user": str(ops_world.people["super"].id),
    }
    walked = 0
    for route in gets:
        path = re.sub(
            r"\{([^}]+)\}", lambda m: _value(m.group(1), found), route.path_format
        )
        for who in ("super", "pass_a"):
            response = ops_world.client.get(path, headers=ops_world.people[who].headers)
            answers.append(response.text)
            answers.append(json.dumps(dict(response.headers)))
            walked += 1
    assert len(gets) >= 21 and walked == 2 * len(gets)  # every GET, both people
    passport = ops_world.call("super", "GET", f"/api/v1/servers/{sid}/passport")
    assert isinstance(passport, dict) and passport["state"] == "ready"

    for value in (MARKER, TLS_MARKER):
        for answer in answers:
            assert value not in answer
        for record in caplog.records:
            assert value not in record.getMessage()
            assert value not in json.dumps(record.__dict__, default=str)
    messages = subprocess.run(
        ["git", "--git-dir", str(ops_side.remote), "log", "--format=%B", "main"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    assert MARKER not in messages and TLS_MARKER not in messages
    rows = query_scalar(ops_world.url, "SELECT json_agg(details)::text FROM audit")
    assert isinstance(rows, str)
    assert "asked.comms.TELEGRAM_BOT_TOKEN" in rows  # the edits are audited
    assert MARKER not in rows and TLS_MARKER not in rows

    # the pair: both are there, for the box
    plain = ops_side.as_box(SERVER)
    assert f"TELEGRAM_BOT_TOKEN: {MARKER}" in plain
    assert TLS_MARKER in plain


def test_probe_DM_158_apply_is_an_update_on_the_edit_commit(
    ops_world: World, ops_side: OpsSide
) -> None:
    """ "Apply" queues ``update``; the box takes it and its green verdict names
    the command and reads primer-ops at the edit's commit -- the passport is
    applied. The pair: a green ``update`` that read the commit before the edit
    leaves it pending."""
    box = registered(ops_world, name=SERVER)
    sid = server_of(ops_world, box)
    before = ops_side.head()
    put_field(ops_world, sid, before, ["domains", "api"], "new-api.velo.example")
    edit = ops_side.head()

    def send(run_id: str, ops_commit: str, command: str | None) -> None:
        raw = verdict(run_id, command)
        raw["verb"] = "update"
        raw["steps"] = [
            {
                "stack": "pridem-passport",
                "name": "fetch_passport",
                "phase": "main",
                "order": 3,
                "status": "ok",
                "verify": {"source": "ops", "server": SERVER, "ops_commit": ops_commit},
            }
        ]
        envelope = {
            "verdict": raw,
            "signature": box.sign(verdict_bytes(raw)),
            "report_llm": "a report",
            "signed_on_send": False,
        }
        answer = box.send("POST", f"/runs/{run_id}/verdict", envelope)
        assert answer.status_code == 204, answer.text

    send("2026-11-26T10:00:00Z-aa01", before, None)
    assert read(ops_world, sid)["apply"] == {"commit": before, "state": "pending"}

    made = apply(ops_world, sid)
    command = box.send("GET", "/commands/next").json()
    assert (command["id"], command["verb"], command["args"]) == (
        made["id"],
        "update",
        {},
    )
    send("2026-11-26T11:00:00Z-aa02", edit, str(made["id"]))
    assert read(ops_world, sid)["apply"] == {"commit": edit, "state": "applied"}
    state = ops_world.call("super", "GET", f"/api/v1/servers/{sid}/commands")
    assert isinstance(state, list)
    assert [c["state"] for c in state if c["id"] == made["id"]] == ["done"]
