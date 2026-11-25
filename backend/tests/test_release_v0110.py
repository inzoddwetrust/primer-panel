"""The Panel on the machine's release v0.1.10 (DM-196): a command and its run,
the signature of an envelope by contract 4's own function, the previous
release's messages, and the forms contract 4 holds now.

The SQL of these tests carries the tests' own values only."""
# ruff: noqa: S608

import ast
import json
import uuid
from datetime import datetime, timedelta

import pytest
from pridem.protocol import RegisterResponse, verdict_bytes
from pydantic import ValidationError

from app.agent import queue
from app.config import Settings
from tests.conftest import BACKEND, execute, query_scalar
from tests.fake_box import RUN_ID, FakeBox, header_line, log_line
from tests.people import World
from tests.test_agent import envelope, queue_command, registered, server_of

# A verdict of v0.1.9 as such a box writes it -- no ``command`` -- written out,
# with a text in Cyrillic: the bytes of its signature are the object's own.
PREVIOUS_VERDICT: dict[str, object] = {
    "schema": 1,
    "run_id": "2026-11-24T12:00:00Z-ab12",
    "verb": "status",
    "args": {"note": "проверка"},
    "actor": {"type": "engineer", "via": "local"},
    "started": "2026-11-24T12:00:00Z",
    "finished": "2026-11-24T12:00:05Z",
    "exit_code": 0,
    "result": "green",
    "composition_before": {"pridem": "0.1.9"},
    "composition_after": {"pridem": "0.1.9"},
    "steps": [],
    "report": {"failures": [], "incomplete": []},
}


@pytest.fixture(autouse=True)
def short_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue, "POLL_WINDOW_S", 0.3)
    monkeypatch.setattr(queue, "POLL_PAUSE_S", 0.05)


def taken(world: World, box: FakeBox, verb: str = "status") -> str:
    """A command of the box's server, queued and taken by the box."""
    made = queue_command(world, server_of(world, box), verb, who="super")
    assert isinstance(made, dict)
    answer = box.send("GET", "/commands/next")
    assert answer.json()["id"] == made["id"]
    return str(made["id"])


def state_of(world: World, command_id: str) -> object:
    return query_scalar(
        world.url, f"SELECT state FROM commands WHERE id = '{command_id}'"
    )


def signed(box: FakeBox, raw: dict[str, object], run_id: str) -> dict[str, object]:
    return {
        "verdict": raw,
        "signature": box.sign(verdict_bytes(raw)),  # type: ignore[arg-type]
        "report_llm": "a report",
        "signed_on_send": False,
    }


def test_probe_DM_196_command_taken_to_done_by_its_verdict(world: World) -> None:
    """A verdict naming its command links the run to it, and the command is
    done; the run and the command point at each other."""
    box = registered(world)
    command = taken(world, box)
    assert state_of(world, command) == "taken"
    answer = box.send("POST", f"/runs/{RUN_ID}/verdict", envelope(box, command=command))
    assert answer.status_code == 204
    assert state_of(world, command) == "done"
    assert (
        query_scalar(world.url, f"SELECT run_id FROM commands WHERE id = '{command}'")
        == RUN_ID
    )
    assert (
        str(
            query_scalar(
                world.url, f"SELECT command_id FROM runs WHERE run_id = '{RUN_ID}'"
            )
        )
        == command
    )
    # a repeat changes nothing
    box.send("POST", f"/runs/{RUN_ID}/verdict", envelope(box, command=command))
    assert state_of(world, command) == "done"


def test_the_header_links_first_and_the_run_does_not_expire(world: World) -> None:
    box = registered(world)
    command = taken(world, box)
    line = header_line(command=command)
    box.send("POST", f"/runs/{RUN_ID}/events", {"from_seq": 1, "events": [line]})
    assert (
        query_scalar(world.url, f"SELECT run_id FROM commands WHERE id = '{command}'")
        == RUN_ID
    )
    execute(
        world.url,
        "UPDATE commands SET taken_at = now() - interval '11 minutes' "
        f"WHERE id = '{command}'",
    )
    assert box.send("GET", "/commands/next").status_code == 204
    assert state_of(world, command) == "taken"  # running: linked, not expired


def _heartbeat(box: FakeBox, without: list[str], lock: list[str]) -> None:
    beat = {
        "measured_at": "2026-11-25T12:00:00Z",
        "machine_version": "0.1.10",
        "lock_open_by": lock,
        "journals_without_verdict": without,
    }
    assert box.send("POST", "/heartbeat", beat).status_code == 204


def test_a_command_whose_run_died_expires_by_the_box_s_word(world: World) -> None:
    """Its journal without a verdict and the lock free: expired. Each part of
    the rule on its own does not expire it. A verdict that comes later makes
    it done."""
    box = registered(world)
    command = taken(world, box)
    line = header_line(command=command)
    box.send("POST", f"/runs/{RUN_ID}/events", {"from_seq": 1, "events": [line]})
    _heartbeat(box, [RUN_ID], ["pid 7 (pridem)"])  # the lock held: may be running
    box.send("GET", "/commands/next")
    assert state_of(world, command) == "taken"
    _heartbeat(box, [], [])  # the journal not left: not dead
    box.send("GET", "/commands/next")
    assert state_of(world, command) == "taken"
    _heartbeat(box, [RUN_ID], [])
    box.send("GET", "/commands/next")
    assert state_of(world, command) == "expired"
    box.send("POST", f"/runs/{RUN_ID}/verdict", envelope(box, command=command))
    assert state_of(world, command) == "done"


def test_an_unlinked_command_waits_its_ten_minutes(world: World) -> None:
    """The rule of a dead run is for a command with a run: one no run took up
    expires by its ten minutes only, whatever the box says of its lock."""
    box = registered(world)
    command = taken(world, box)
    _heartbeat(box, [RUN_ID], [])
    queue_command(world, server_of(world, box), "state", who="super")
    assert state_of(world, command) == "taken"


def test_a_command_is_given_with_the_end_of_its_time(world: World) -> None:
    box = registered(world)
    made = queue_command(world, server_of(world, box), "status", who="super")
    assert isinstance(made, dict)
    answer = box.send("GET", "/commands/next").json()
    taken_at = query_scalar(
        world.url, f"SELECT taken_at FROM commands WHERE id = '{made['id']}'"
    )
    assert isinstance(taken_at, datetime)
    expires = datetime.fromisoformat(answer["expires_at"].replace("Z", "+00:00"))
    assert abs(expires - (taken_at + timedelta(minutes=10))) < timedelta(seconds=1)
    assert "confirmed_at" not in answer


def test_probe_DM_196_foreign_command_is_run_foreign(world: World) -> None:
    """A run naming a command of another server is refused run-foreign, and
    nothing is written; a command the Panel does not have links nothing."""
    mine, other = registered(world, "velo-test-1"), registered(world, "velo-test-2")
    theirs = taken(world, other)
    line = header_line(command=theirs)
    answer = mine.send(
        "POST", f"/runs/{RUN_ID}/events", {"from_seq": 1, "events": [line]}
    )
    assert (answer.status_code, answer.json()) == (403, {"code": "run-foreign"})
    answer = mine.send(
        "POST", f"/runs/{RUN_ID}/verdict", envelope(mine, command=theirs)
    )
    assert (answer.status_code, answer.json()) == (403, {"code": "run-foreign"})
    assert state_of(world, theirs) == "taken"
    assert query_scalar(world.url, "SELECT count(*) FROM verdicts") == 0
    # the pair: a command nobody has -- the run is kept, unlinked
    nobody = str(uuid.uuid4())
    answer = mine.send(
        "POST", f"/runs/{RUN_ID}/verdict", envelope(mine, command=nobody)
    )
    assert answer.status_code == 204
    assert (
        query_scalar(
            world.url, f"SELECT command_id FROM runs WHERE run_id = '{RUN_ID}'"
        )
        is None
    )


def test_probe_DM_196_panel_reads_the_previous_release(world: World) -> None:
    """A box of v0.1.9 -- a verdict and a journal with no ``command`` -- is
    read by the Panel of v0.1.10: kept, its signature holds, nothing linked."""
    box = registered(world)
    command = taken(world, box)
    header = header_line()  # v0.1.9's header: no command
    assert "command" not in header
    answer = box.send(
        "POST",
        f"/runs/{RUN_ID}/events",
        {"from_seq": 1, "events": [header, log_line(2)]},
    )
    assert answer.json() == {"last_seq": 2}
    answer = box.send(
        "POST", f"/runs/{RUN_ID}/verdict", signed(box, PREVIOUS_VERDICT, RUN_ID)
    )
    assert answer.status_code == 204
    assert (
        query_scalar(
            world.url, f"SELECT verified FROM verdicts WHERE run_id = '{RUN_ID}'"
        )
        is True
    )
    assert state_of(world, command) == "taken"
    body = query_scalar(
        world.url, f"SELECT body FROM verdicts WHERE run_id = '{RUN_ID}'"
    )
    assert body == PREVIOUS_VERDICT


def test_probe_DM_196_signature_by_the_contract(world: World) -> None:
    """The envelope is checked by contract 4's verdict_bytes over the object:
    a signature over another canonical form (ASCII escapes) does not hold; the
    Panel has no function of its own for these bytes."""
    box = registered(world)
    raw = PREVIOUS_VERDICT
    ascii_form = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    assert ascii_form != verdict_bytes(raw)  # type: ignore[arg-type]
    other = {**signed(box, raw, RUN_ID), "signature": box.sign(ascii_form)}
    run_b = "2026-11-24T12:00:01Z-cd34"
    box.send("POST", f"/runs/{RUN_ID}/verdict", other)
    box.send(
        "POST", f"/runs/{run_b}/verdict", signed(box, {**raw, "run_id": run_b}, run_b)
    )
    kept = query_scalar(
        world.url, "SELECT json_object_agg(run_id, verified) FROM verdicts"
    )
    assert kept == {RUN_ID: False, run_b: True}
    for path in (BACKEND / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        own = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        assert "verdict_bytes" not in own, path


def test_contract_4_s_forms_the_panel_gives(world: World) -> None:
    box = FakeBox(world.client)
    path = f"/api/v1/projects/{world.projects['a']}/registration-tokens"
    made = world.call("super", "POST", path, expect=201)
    assert isinstance(made, dict)
    answer = box.register(str(made["token"]), "velo-test-1", "git@github.com:o/a.git")
    form = RegisterResponse.model_validate(answer.json())
    assert (form.heartbeat_s, form.full_state_s, form.poll_s) == (30, 300, 60)
    for bad in (
        "http://api.example.test/agent/v1/",
        "https://api.example.test:8443/agent/v1/",
    ):
        with pytest.raises(ValidationError):
            RegisterResponse.model_validate({**answer.json(), "agent_url": bad})
    for host in ("api.example.test:8443", "http://api.example.test"):
        with pytest.raises(ValidationError):
            Settings.model_validate({"DOMAIN_API": host})


def test_the_heartbeat_keeps_box_state_by_its_aliases(world: World) -> None:
    """Changed by DM-196: BoxSnapshot of v0.1.10 writes ``schema`` itself; the
    round trip of FIX DM-153 still holds (tests/test_agent.py)."""
    from tests.test_agent import FULL_STATE

    box = registered(world)
    beat = {
        "measured_at": "2026-11-25T12:00:00Z",
        "machine_version": "0.1.10",
        "lock_open_by": [],
        "journals_without_verdict": [],
        "state": FULL_STATE,
    }
    assert box.send("POST", "/heartbeat", beat).status_code == 204
    kept = query_scalar(world.url, "SELECT snapshot->>'schema' FROM server_states")
    assert kept == "1"
