"""The Panel's side of the protocol of the agent, against a stand-in box
(DM-153): registration, the box's signature, the heartbeat, the queue,
events, verdicts, history -- and what people do about servers.

The SQL of these tests carries the tests' own values (ids, run ids) only."""
# ruff: noqa: S608

import base64
import json
import time
import uuid
from collections.abc import Mapping

import pytest
from fastapi.routing import APIRoute
from pridem.contract import SCHEMA_DIR
from pridem.protocol import (
    AGENT_PROTOCOL_SCHEMA,
    MESSAGES,
    EventBatch,
    VerdictEnvelope,
    rendered_schema,
    verdict_bytes,
)
from pridem.report.box_snapshot import BoxSnapshot
from pridem.report.schema import Verdict

import app.agent.router as agent_router
from app.agent import queue
from app.agent.router import router
from tests.conftest import API_HOST, execute, query_scalar
from tests.fake_box import (
    RUN_ID,
    FakeBox,
    finished_line,
    header_line,
    log_line,
    verdict,
)
from tests.people import World

API = "/api/v1"
# The codes of contract 4's refusals, written out (not RefusalCode of the code).
CODES = {
    "token-unknown",
    "token-used",
    "token-expired",
    "name-taken",
    "product-mismatch",
    "protocol-too-old",
    "protocol-too-new",
    "clock-skew",
    "signature-bad",
    "box-unknown",
    "run-foreign",
}


@pytest.fixture(autouse=True)
def short_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """The long-poll of the tests waits a fraction of a second."""
    monkeypatch.setattr(queue, "POLL_WINDOW_S", 0.3)
    monkeypatch.setattr(queue, "POLL_PAUSE_S", 0.05)


def token_for(world: World, project: str = "a", who: str = "super") -> str:
    path = f"{API}/projects/{world.projects[project]}/registration-tokens"
    made = world.call(who, "POST", path, expect=201)
    assert isinstance(made, dict)
    token: str = made["token"]
    return token


def registered(world: World, name: str = "velo-test-1", project: str = "a") -> FakeBox:
    box = FakeBox(world.client)
    answer = box.register(
        token_for(world, project), name, f"git@github.com:o/{project}.git"
    )
    assert answer.status_code == 201, answer.text
    return box


def server_of(world: World, box: FakeBox) -> uuid.UUID:
    found = query_scalar(
        world.url, f"SELECT id FROM servers WHERE box_id = '{box.box_id}'"
    )
    assert isinstance(found, uuid.UUID)
    return found


def queue_command(
    world: World,
    server: uuid.UUID,
    verb: str,
    args: Mapping[str, object] | None = None,
    who: str = "admin_a",
    expect: int = 201,
    confirmed: bool = False,
) -> object:
    body = {"verb": verb, "args": dict(args or {}), "confirmed": confirmed}
    return world.call(
        who, "POST", f"{API}/servers/{server}/commands", body, expect=expect
    )


def refused(answer: object, code: str, status: int) -> None:
    assert code in CODES
    assert getattr(answer, "status_code") == status, getattr(answer, "text")  # noqa: B009
    assert getattr(answer, "json")() == {"code": code}  # noqa: B009


def envelope(
    box: FakeBox, run_id: str = RUN_ID, *, good: bool = True, command: str | None = None
) -> VerdictEnvelope:
    """Changed by DM-196: signed by contract 4's verdict_bytes over the verdict
    as an object (DM-140), the verdict carrying ``command`` when given."""
    raw = verdict(run_id, command)
    signed = verdict_bytes(raw) if good else verdict_bytes(raw) + b" "
    return VerdictEnvelope(
        verdict=Verdict.model_validate(raw),
        signature=box.sign(signed),
        report_llm="a report",
        signed_on_send=False,
    )


# --- registration ---------------------------------------------------------------


def test_a_box_registers_by_its_token(world: World) -> None:
    box = FakeBox(world.client)
    answer = box.register(token_for(world), "velo-test-1", "git@github.com:o/a.git")
    assert answer.status_code == 201
    body = answer.json()
    assert body["agent_url"] == f"https://{API_HOST}/agent/v1/"
    assert (body["heartbeat_s"], body["full_state_s"], body["poll_s"]) == (30, 300, 60)
    assert (
        query_scalar(
            world.url,
            f"SELECT project_id FROM servers WHERE box_id = '{box.box_id}'",
        )
        == world.projects["a"]
    )
    assert (
        query_scalar(
            world.url, "SELECT count(*) FROM audit WHERE action = 'server.register'"
        )
        == 1
    )


def test_registration_refusals(world: World) -> None:
    box = FakeBox(world.client)
    repo = "git@github.com:o/a.git"
    # Changed by DM-196: a token of contract 4 is at least 16 characters long
    unknown = "no-such-token-0123456789"
    refused(box.register(unknown, "x1", repo), "token-unknown", 404)
    assert box.register("short", "x1", repo).status_code == 422
    token = token_for(world)
    refused(box.register(token, "x1", repo, protocol="2"), "protocol-too-new", 400)
    refused(box.register(token, "x1", repo, protocol=""), "protocol-too-old", 400)
    refused(
        box.register(token, "x1", "git@github.com:o/b.git"), "product-mismatch", 409
    )
    assert box.register(token, "x1", repo).status_code == 201
    refused(FakeBox(world.client).register(token, "x2", repo), "token-used", 410)
    refused(
        FakeBox(world.client).register(token_for(world), "x1", repo), "name-taken", 409
    )
    late = token_for(world)
    execute(
        world.url,
        "UPDATE registration_tokens SET expires_at = now() - interval '1 second' "
        "WHERE used_at IS NULL",
    )
    refused(FakeBox(world.client).register(late, "x3", repo), "token-expired", 410)


def test_a_key_not_of_its_form_is_invalid(world: World) -> None:
    box = FakeBox(world.client)
    body = {
        "token": token_for(world),
        "server_name": "x1",
        "role": "test",
        "product_repo": "git@github.com:o/a.git",
        "machine_version": "0.1.8",
        "box_key_public": base64.b64encode(b"short").decode(),
    }
    answer = box.request(
        "POST",
        "/agent/v1/register",
        json.dumps(body).encode(),
        {"X-Primer-Protocol": "1", "Content-Type": "application/json"},
    )
    assert answer.status_code == 422


def test_only_servers_permission_makes_a_token(world: World) -> None:
    path = f"{API}/projects/{world.projects['a']}/registration-tokens"
    world.call("staff_a", "POST", path, expect=403)
    world.call("admin_a", "POST", path, expect=403)  # admin_a holds no servers
    world.call(
        "admin_s",
        "POST",
        f"{API}/projects/{world.projects['s']}/registration-tokens",
        expect=201,
    )


# --- the box's signature --------------------------------------------------------


def test_probe_DM_153_request_with_bad_signature_refused(world: World) -> None:
    """A request the box's key did not sign is refused ``signature-bad``: a
    signature of something else, a body changed after signing, no headers.
    The pair: the box's own signature passes."""
    box = registered(world)
    beat = {
        "measured_at": "2026-11-24T12:00:00Z",
        "machine_version": "0.1.8",
        "lock_open_by": [],
        "journals_without_verdict": [],
    }
    other = FakeBox(world.client)
    refused(
        box.send("POST", "/heartbeat", beat, signature=other.sign(b"x")),
        "signature-bad",
        401,
    )
    refused(
        box.send(
            "POST",
            "/heartbeat",
            beat,
            body=json.dumps({**beat, "machine_version": "9"}).encode(),
        ),
        "signature-bad",
        401,
    )
    refused(box.send("POST", "/heartbeat", beat, signature=None), "signature-bad", 401)
    refused(
        box.send("POST", "/heartbeat", beat, signature="not base64!"),
        "signature-bad",
        401,
    )
    assert box.send("POST", "/heartbeat", beat).status_code == 204


def test_the_order_of_the_checks_of_a_request(world: World) -> None:
    box = registered(world)
    beat = {
        "measured_at": "2026-11-24T12:00:00Z",
        "machine_version": "0.1.8",
        "lock_open_by": [],
        "journals_without_verdict": [],
    }
    refused(box.send("POST", "/heartbeat", beat, protocol="2"), "protocol-too-new", 400)
    refused(box.send("POST", "/heartbeat", beat, box="no-such-box"), "box-unknown", 403)
    now = int(time.time())
    refused(box.send("POST", "/heartbeat", beat, at=now - 301), "clock-skew", 401)
    refused(box.send("POST", "/heartbeat", beat, at=now + 301), "clock-skew", 401)
    assert box.send("POST", "/heartbeat", beat, at=now - 290).status_code == 204
    execute(
        world.url,
        f"UPDATE servers SET detached_at = now() WHERE box_id = '{box.box_id}'",
    )
    refused(box.send("POST", "/heartbeat", beat), "box-unknown", 403)


def test_a_heartbeat_keeps_the_state_of_the_box(world: World) -> None:
    box = registered(world)
    beat = {
        "measured_at": "2026-11-24T12:00:00Z",
        "machine_version": "0.1.8",
        "lock_open_by": ["update"],
        "journals_without_verdict": [RUN_ID],
    }
    assert box.send("POST", "/heartbeat", beat).status_code == 204
    assert (
        box.send("POST", "/heartbeat", {**beat, "machine_version": "0.1.9"}).status_code
        == 204
    )
    server = server_of(world, box)
    assert (
        query_scalar(
            world.url,
            f"SELECT machine_version FROM server_states WHERE server_id = '{server}'",
        )
        == "0.1.9"
    )
    assert (
        query_scalar(
            world.url,
            f"SELECT protocol_version FROM server_states WHERE server_id = '{server}'",
        )
        == 1
    )
    answer = box.send("POST", "/heartbeat", {**beat, "unknown": 1})
    assert answer.status_code == 422  # strict: a field the contract does not know


FULL_STATE: dict[str, object] = {
    "schema": 1,
    "measured_at": "2026-11-24T12:00:00Z",
    "machine": {"version": "0.1.9"},
    "passport": {"version": 3},
    "lock_open_by": [],
    "journals_without_verdict": [],
    "stacks": [
        {
            "stack": "velo",
            "release": "v1.2.0",
            "entries": [
                {
                    "entry": "velo",
                    "persistent": False,
                    "services": [
                        {"service": "app", "state": "running", "health": "unhealthy"}
                    ],
                }
            ],
        }
    ],
    "machine_stacks": [],
    "resources": {
        "disk": [],
        "memory": {"unmeasured": "meminfo-unreadable"},
        "swap": {"unmeasured": "meminfo-unreadable"},
        "images": {"unmeasured": "docker-unreachable"},
    },
    "ssl": {"unmeasured": "no-certificate"},
}
"""A full ``box-state.v1``, as the box measures it (DM-136)."""


def test_a_full_heartbeat_is_kept_in_the_form_it_came(world: World) -> None:
    """Added by DM-153 FIX: the full state of a heartbeat is kept as
    ``box-state.v1`` (``schema``, not the model's ``schema_``) and reads back
    by contract 4's own model."""
    box = registered(world)
    beat = {
        "measured_at": "2026-11-24T12:00:00Z",
        "machine_version": "0.1.9",
        "lock_open_by": [],
        "journals_without_verdict": [],
        "state": FULL_STATE,
    }
    assert box.send("POST", "/heartbeat", beat).status_code == 204
    server = server_of(world, box)
    kept = query_scalar(
        world.url, f"SELECT snapshot FROM server_states WHERE server_id = '{server}'"
    )
    assert isinstance(kept, dict)
    assert kept == FULL_STATE
    assert BoxSnapshot.model_validate(kept).stacks != []
    # a light heartbeat after it keeps the full form
    light = {key: value for key, value in beat.items() if key != "state"}
    assert box.send("POST", "/heartbeat", light).status_code == 204
    again = query_scalar(
        world.url, f"SELECT snapshot FROM server_states WHERE server_id = '{server}'"
    )
    assert again == FULL_STATE


# --- the queue ------------------------------------------------------------------


def test_the_queue_gives_one_command_at_a_time(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    """One command taken per server; the polls that find one taken give
    nothing without touching the index (no race to lose when alone)."""
    caplog.set_level("INFO", logger="app.agent.queue")
    box = registered(world)
    server = server_of(world, box)
    assert box.send("GET", "/commands/next").status_code == 204
    # Changed by DM-202: a file of the box is no field of a button
    first = queue_command(world, server, "update", {"tries": ["velo=1.2.3"]})
    second = queue_command(world, server, "status")
    assert isinstance(first, dict) and isinstance(second, dict)
    given = box.send("GET", "/commands/next")
    assert given.status_code == 200
    # Changed by DM-196: a command carries the end of its time to be taken
    expires = given.json().pop("expires_at")
    assert given.json() == {
        "id": first["id"],
        "verb": "update",
        "args": {"tries": ["velo=1.2.3"]},
        "expires_at": expires,
    }
    assert box.send("GET", "/commands/next").status_code == 204  # one taken per server
    refusal = box.send(
        "POST", f"/commands/{first['id']}/refusal", {"code": "args-refused"}
    )
    assert refusal.status_code == 204
    assert (
        box.send(
            "POST", f"/commands/{first['id']}/refusal", {"code": "args-refused"}
        ).status_code
        == 204
    )
    assert box.send("GET", "/commands/next").json()["id"] == second["id"]
    raced = [r for r in caplog.records if getattr(r, "event", "") == "agent.take_raced"]
    assert raced == []
    listed = world.call(
        "staff_a", "GET", f"{API}/servers/{server}/commands", expect=200
    )
    assert isinstance(listed, list)
    assert [(c["verb"], c["state"], c["refusal"]) for c in listed] == [
        ("update", "refused", "args-refused"),
        ("status", "taken", None),
    ]


def test_a_taken_command_expires_after_ten_minutes(world: World) -> None:
    box = registered(world)
    server = server_of(world, box)
    first = queue_command(world, server, "status")
    second = queue_command(world, server, "doctor")  # DM-202: state is no button
    assert isinstance(first, dict) and isinstance(second, dict)
    assert box.send("GET", "/commands/next").json()["id"] == first["id"]
    execute(
        world.url,
        "UPDATE commands SET taken_at = now() - interval '9 minutes' "
        f"WHERE id = '{first['id']}'",
    )
    assert box.send("GET", "/commands/next").status_code == 204  # not yet
    execute(
        world.url,
        "UPDATE commands SET taken_at = now() - interval '11 minutes' "
        f"WHERE id = '{first['id']}'",
    )
    assert box.send("GET", "/commands/next").json()["id"] == second["id"]
    assert (
        query_scalar(
            world.url, f"SELECT state FROM commands WHERE id = '{first['id']}'"
        )
        == "expired"
    )


def test_a_command_of_another_box_is_not_this_box_s(world: World) -> None:
    mine, other = registered(world, "velo-test-1"), registered(world, "velo-test-2")
    command = queue_command(world, server_of(world, other), "status")
    assert isinstance(command, dict)
    refused(
        mine.send(
            "POST", f"/commands/{command['id']}/refusal", {"code": "verb-unknown"}
        ),
        "run-foreign",  # changed by DM-196: contract 4's code (box-unknown before)
        403,
    )


def test_probe_DM_153_one_taken_command_per_server(world: World) -> None:
    """The database holds "one taken per server": a second taken command of
    the server is refused by its index, whoever writes it.

    Changed by DM-202, by the dispatcher's word on its gate: ``state`` is no
    button and is not queued, so the second command is ``doctor`` -- the probe
    is of the queue, not of the verb."""
    box = registered(world)
    server = server_of(world, box)
    for verb in ("status", "doctor"):
        queue_command(world, server, verb)
    assert box.send("GET", "/commands/next").status_code == 200
    with pytest.raises(Exception, match="uq_commands_one_taken"):
        execute(
            world.url,
            "UPDATE commands SET state = 'taken', taken_at = now() "
            f"WHERE server_id = '{server}' AND state = 'queued'",
        )
    assert (
        query_scalar(
            world.url,
            "SELECT count(*) FROM commands "
            f"WHERE server_id = '{server}' AND state = 'taken'",
        )
        == 1
    )


# --- people and commands --------------------------------------------------------


def test_probe_DM_153_command_without_permission_refused_before_queue(
    world: World,
) -> None:
    """A person without the action's permission is refused, and no command
    is queued. The pair: with it, the command is queued."""
    box = registered(world)
    server = server_of(world, box)
    queue_command(world, server, "seed", {"list_": True}, who="staff_a", expect=403)
    queue_command(world, server, "update", who="people_a", expect=403)
    assert query_scalar(world.url, "SELECT count(*) FROM commands") == 0
    made = queue_command(world, server, "update", who="staff_a")  # deploy_test
    assert isinstance(made, dict) and made["state"] == "queued"
    assert (
        query_scalar(
            world.url, "SELECT count(*) FROM audit WHERE action = 'command.queue'"
        )
        == 1
    )


def test_reading_verbs_are_any_member_s(world: World) -> None:
    """Changed by DM-202: of the reading verbs only ``status`` is a button
    (``state`` and ``ssl status`` write no verdict)."""
    server = server_of(world, registered(world))
    queue_command(world, server, "status", who="people_a")
    queue_command(world, server, "ssl", {"action": "renew"}, who="people_a", expect=403)


def test_a_command_off_the_machine_is_invalid(world: World) -> None:
    server = server_of(world, registered(world))
    queue_command(world, server, "self-destruct", who="super", expect=422)
    queue_command(world, server, "ssl", {"action": "melt"}, who="super", expect=422)
    queue_command(world, server, "status", {"extra": 1}, who="super", expect=422)


def test_a_destructive_command_comes_confirmed_by_the_server_s_name(
    world: World,
) -> None:
    server = server_of(world, registered(world))
    queue_command(world, server, "destroy", who="super", expect=409)
    queue_command(
        world,
        server,
        "db",
        {"action": "reset", "stack": "velo", "confirm": "velo-test-1"},
        who="super",
        expect=409,
    )
    queue_command(
        world,
        server,
        "db",
        {"action": "reset", "stack": "velo", "confirm": "other"},
        who="super",
        expect=422,
        confirmed=True,
    )
    made = queue_command(
        world,
        server,
        "destroy",
        {"confirm": "velo-test-1"},
        who="super",
        confirmed=True,
    )
    assert isinstance(made, dict) and made["confirmed_at"] is not None
    plain = queue_command(world, server, "status", who="super", confirmed=True)
    assert isinstance(plain, dict) and plain["confirmed_at"] is None


def test_probe_DM_153_foreign_project_server_not_found(world: World) -> None:
    """A server of a project the person does not see is "not found" on every
    route of people about servers. The pair: the project's own member sees it."""
    server = server_of(world, registered(world, "velo-test-1", project="a"))
    world.call("admin_b", "GET", f"{API}/servers/{server}/commands", expect=404)
    queue_command(world, server, "status", who="admin_b", expect=404)
    queue_command(world, server, "status", who="admin_s", expect=404)
    world.call(
        "admin_b",
        "POST",
        f"{API}/projects/{world.projects['a']}/registration-tokens",
        expect=404,
    )
    world.call("staff_a", "GET", f"{API}/servers/{server}/commands", expect=200)
    world.call("staff_a", "GET", f"{API}/servers/{uuid.uuid4()}/commands", expect=404)


# --- events, verdicts, history --------------------------------------------------


def batch(lines: list[dict[str, object]]) -> dict[str, object]:
    return {"from_seq": lines[0]["seq"], "events": lines}


def test_probe_DM_153_events_without_gap_or_duplicate_on_repeat(world: World) -> None:
    """Lines are kept by (run_id, seq) once; the answer is the last seq held
    with no gap before it."""
    box = registered(world)
    path = f"/runs/{RUN_ID}/events"
    first = [header_line(), log_line(2), log_line(3)]
    assert box.send("POST", path, batch(first)).json() == {"last_seq": 3}
    assert box.send("POST", path, batch(first)).json() == {"last_seq": 3}  # repeat
    assert box.send("POST", path, batch([log_line(5), log_line(6)])).json() == {
        "last_seq": 3
    }  # gap
    assert box.send("POST", path, batch([log_line(4)])).json() == {
        "last_seq": 6
    }  # gap filled
    assert box.send("POST", path, batch([finished_line(7)])).json() == {"last_seq": 7}
    seqs = query_scalar(
        world.url,
        f"SELECT json_agg(seq ORDER BY seq) FROM events WHERE run_id = '{RUN_ID}'",
    )
    assert seqs == [1, 2, 3, 4, 5, 6, 7]
    run = query_scalar(
        world.url,
        f"SELECT json_build_array(verb, outcome) FROM runs WHERE run_id = '{RUN_ID}'",
    )
    assert run == ["status", "green"]
    # a repeat with another body keeps the first
    changed = {**log_line(2), "line": "rewritten"}
    box.send("POST", path, batch([changed]))
    body = query_scalar(
        world.url,
        f"SELECT body->>'line' FROM events WHERE run_id = '{RUN_ID}' AND seq = 2",
    )
    assert body == "line 2"


def test_a_run_is_its_box_s(world: World) -> None:
    mine, other = registered(world, "velo-test-1"), registered(world, "velo-test-2")
    assert (
        mine.send("POST", f"/runs/{RUN_ID}/events", batch([header_line()])).status_code
        == 200
    )
    refused(
        other.send("POST", f"/runs/{RUN_ID}/events", batch([log_line(2)])),
        "run-foreign",  # changed by DM-196: contract 4's code (box-unknown before)
        403,
    )
    refused(
        other.send("POST", f"/runs/{RUN_ID}/verdict", envelope(other)),
        "run-foreign",
        403,
    )
    answer = mine.send(
        "POST", "/runs/2026-11-24T12:00:01Z-cd34/events", batch([header_line()])
    )
    assert answer.status_code == 422  # the header names another run


def test_probe_DM_153_envelope_with_bad_signature_kept_unverified(world: World) -> None:
    """A verdict whose envelope's signature does not hold is kept, with
    verified false -- red, never silent. The pair: a good one is verified."""
    box = registered(world)
    bad_run = "2026-11-24T12:00:09Z-ee99"
    assert (
        box.send(
            "POST", f"/runs/{bad_run}/verdict", envelope(box, bad_run, good=False)
        ).status_code
        == 204
    )
    assert box.send("POST", f"/runs/{RUN_ID}/verdict", envelope(box)).status_code == 204
    kept = query_scalar(
        world.url, "SELECT json_object_agg(run_id, verified) FROM verdicts"
    )
    assert kept == {bad_run: False, RUN_ID: True}
    # a repeat changes nothing; the verdict made its run
    assert (
        box.send(
            "POST", f"/runs/{RUN_ID}/verdict", envelope(box, good=False)
        ).status_code
        == 204
    )
    assert (
        query_scalar(
            world.url, f"SELECT verified FROM verdicts WHERE run_id = '{RUN_ID}'"
        )
        is True
    )
    assert (
        query_scalar(world.url, f"SELECT outcome FROM runs WHERE run_id = '{bad_run}'")
        == "green"
    )


def test_history_answers_the_runs_held(world: World) -> None:
    box = registered(world)
    runs = ["2026-11-24T11:00:00Z-aa01", "2026-11-24T11:00:01Z-aa02"]
    sent = {
        "envelopes": [
            json.loads(envelope(box, r).model_dump_json(by_alias=True)) for r in runs
        ]
    }
    assert box.send("POST", "/history", sent).json() == {"run_ids": runs}
    assert box.send("POST", "/history", sent).json() == {"run_ids": runs}  # repeat
    assert box.send("POST", "/history", {"envelopes": []}).json() == {"run_ids": []}
    assert query_scalar(world.url, "SELECT count(*) FROM verdicts") == 2


# --- the contract ---------------------------------------------------------------


def test_the_messages_are_contract_4_s_export() -> None:
    """The schema of the pinned machine's models is its exported file, and
    the agent's paths answer with those very classes -- no copy."""
    assert rendered_schema() == (SCHEMA_DIR / AGENT_PROTOCOL_SCHEMA).read_text(
        encoding="utf-8"
    )
    answers = {
        route.response_model
        for route in router.routes
        if isinstance(route, APIRoute) and route.response_model is not None
    }
    assert answers and answers <= set(MESSAGES)
    module = vars(agent_router)
    for name in (
        "RegisterRequest",
        "Heartbeat",
        "CommandRefusal",
        "EventBatch",
        "VerdictEnvelope",
        "HistoryBatch",
    ):
        assert module[name] in MESSAGES, name
    assert module["EventBatch"] is EventBatch
