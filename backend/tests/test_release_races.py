"""Writers of a command and its run at the same time (DM-196): five rounds
each, on the live Postgres, through one ASGI application -- whatever comes
first, the outcome is one of the serial ones and never a 500.

The SQL of these tests carries the tests' own values only."""
# ruff: noqa: S608

import json

import pytest

from app.agent import queue
from tests.conftest import execute, query_scalar
from tests.fake_box import FakeBox, header_line
from tests.people import World
from tests.test_agent import envelope, queue_command, registered, server_of
from tests.test_agent_races import Call, race, signed


@pytest.fixture(autouse=True)
def short_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue, "POLL_WINDOW_S", 0.3)
    monkeypatch.setattr(queue, "POLL_PAUSE_S", 0.05)


def _taken(world: World, box: FakeBox) -> str:
    made = queue_command(world, server_of(world, box), "status", who="super")
    assert isinstance(made, dict)
    assert box.send("GET", "/commands/next").json()["id"] == made["id"]
    return str(made["id"])


def _verdict(box: FakeBox, run_id: str, command: str) -> Call:
    sent = json.loads(
        envelope(box, run_id, command=command).model_dump_json(by_alias=True)
    )
    return signed(box, "POST", f"/runs/{run_id}/verdict", sent)


def _state(world: World, command: str) -> object:
    return query_scalar(world.url, f"SELECT state FROM commands WHERE id = '{command}'")


def test_the_header_and_the_verdict_of_a_run_at_once(
    world: World, migrated_db: str, redis_url: str
) -> None:
    box = registered(world)
    for round_ in range(5):
        command = _taken(world, box)
        run_id = f"2026-11-25T12:00:0{round_}Z-ab1{round_}"
        batch = {"from_seq": 1, "events": [header_line(run_id, command=command)]}
        answers = race(
            migrated_db,
            redis_url,
            [
                signed(box, "POST", f"/runs/{run_id}/events", batch),
                _verdict(box, run_id, command),
            ],
        )
        assert sorted(code for code, _ in answers) == [200, 204], answers
        assert _state(world, command) == "done"
        linked = query_scalar(
            world.url, f"SELECT run_id FROM commands WHERE id = '{command}'"
        )
        assert linked == run_id


def test_an_expiry_by_the_box_s_word_against_a_late_verdict(
    world: World, migrated_db: str, redis_url: str
) -> None:
    """The box said the run died; its verdict comes at the same time as a
    poll that expires the command: done, whatever the order."""
    box = registered(world)
    for round_ in range(5):
        command = _taken(world, box)
        run_id = f"2026-11-25T13:00:0{round_}Z-cd1{round_}"
        batch = {"from_seq": 1, "events": [header_line(run_id, command=command)]}
        assert box.send("POST", f"/runs/{run_id}/events", batch).status_code == 200
        beat = {
            "measured_at": "2026-11-25T13:00:00Z",
            "machine_version": "0.1.10",
            "lock_open_by": [],
            "journals_without_verdict": [run_id],
        }
        assert box.send("POST", "/heartbeat", beat).status_code == 204
        answers = race(
            migrated_db,
            redis_url,
            [signed(box, "GET", "/commands/next"), _verdict(box, run_id, command)],
        )
        assert answers[1][0] == 204, answers
        assert _state(world, command) == "done"
        execute(world.url, "UPDATE server_states SET journals_without_verdict = '[]'")
