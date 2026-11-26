"""Probes of DM-159: a run waiting for a key to a repository -- seen with its
key and the page of the repository's deploy keys on the run's page, in its
stream and on the server's card; the wait goes by itself when the run's next
step ends; everybody who sees the server sees it, a stranger sees nothing.

The lines come the way a box sends them: signed batches of contract 4 on
``/agent/v1/runs/<run_id>/events``, through its models."""

import asyncio
import json

import pytest

from app.agent import queue
from app.core.database import make_engine, make_sessions
from app.runs.router import stream_lines
from tests.fake_box import FakeBox, header_line, log_line
from tests.people import World
from tests.test_agent import batch, registered, server_of
from tests.test_key_wait import KEY, PAGE, finished_step, notice, run_finished

API = "/api/v1/servers"


@pytest.fixture(autouse=True)
def short_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue, "POLL_WINDOW_S", 0.3)
    monkeypatch.setattr(queue, "POLL_PAUSE_S", 0.05)


def send(box: FakeBox, run_id: str, lines: list[dict[str, object]]) -> None:
    answer = box.send("POST", f"/runs/{run_id}/events", batch(lines))
    assert answer.status_code == 200, answer.text


def start(box: FakeBox, run_id: str) -> None:
    """A run of the box that minted a key and waits for it: the console's
    block -- the key printed as a line -- and the notice."""
    send(
        box,
        run_id,
        [
            {**header_line(run_id, verb="install"), "at": "2026-11-26T12:00:01.000Z"},
            {**log_line(2), "line": KEY},
            notice(3),
        ],
    )


def test_probe_DM_159_key_wait_is_shown_with_key_and_page(
    world: World, migrated_db: str
) -> None:
    """The run's page, the card's route and the stream's ``event: key`` each
    carry the repository, the whole key and its page. The pair: a run of the
    same server with no notice has no wait."""
    box = registered(world)
    target = server_of(world, box)
    quiet = "2026-11-26T11:00:00Z-aa00"
    send(box, quiet, [header_line(quiet), log_line(2)])
    found = world.call("admin_a", "GET", f"{API}/{target}/runs/{quiet}", expect=200)
    assert isinstance(found, dict) and found["key_wait"] is None

    run_id = "2026-11-26T12:00:00Z-ab12"
    start(box, run_id)
    found = world.call("admin_a", "GET", f"{API}/{target}/runs/{run_id}", expect=200)
    assert isinstance(found, dict)
    wait = found["key_wait"]
    assert (wait["repo"], wait["key"], wait["page"], wait["write"], wait["state"]) == (
        "git@github.com:o/velo.git",
        KEY,
        PAGE,
        False,
        "waiting",
    )
    card = world.call("admin_a", "GET", f"{API}/{target}/key-wait", expect=200)
    assert card == wait

    async def told() -> dict[str, object]:
        engine = make_engine(migrated_db)

        async def never() -> bool:
            return False

        try:
            stream = stream_lines(make_sessions(engine), target, run_id, 0, never)
            for _ in range(6):
                part = await asyncio.wait_for(anext(stream), 5)
                if part.startswith("event: key"):
                    data: dict[str, object] = json.loads(part.split("data: ")[1])
                    return data
            raise AssertionError("no event: key")
        finally:
            await engine.dispose()

    assert asyncio.run(told()) == wait


def test_probe_DM_159_key_wait_goes_by_itself(world: World) -> None:
    """The box goes on once the key works: its step ends ``ok``, and the wait
    is ``granted`` on the run's page and the card -- the Panel sent nothing.
    The pair: a step that ends ``failed`` is a key that did not come; a run
    that ends while it waits -- ``ended``."""
    box = registered(world)
    target = server_of(world, box)
    cases = {
        "2026-11-26T12:00:00Z-ab01": (finished_step(4, "ok"), "granted"),
        "2026-11-26T12:00:00Z-ab02": (finished_step(4, "failed"), "not_granted"),
        "2026-11-26T12:00:00Z-ab03": (run_finished(4), "ended"),
    }
    for run_id, (closing, state) in cases.items():
        start(box, run_id)
        page = f"{API}/{target}/runs/{run_id}"
        found = world.call("admin_a", "GET", page, expect=200)
        assert isinstance(found, dict) and found["key_wait"]["state"] == "waiting"
        send(box, run_id, [closing])
        found = world.call("admin_a", "GET", page, expect=200)
        assert isinstance(found, dict) and found["key_wait"]["state"] == state, run_id
    assert box.send("GET", "/commands/next").status_code == 204  # nothing queued


def test_probe_DM_159_every_member_sees_it_a_stranger_does_not(world: World) -> None:
    """A member of the server's project without a single permission sees the
    wait with the key and the page, on the run's page and the card; a person
    of another project -- 404 on both."""
    world.person("bare_a", 7000000888)
    world.join("bare_a", world.invite("super", "a", []))
    box = registered(world)
    target = server_of(world, box)
    run_id = "2026-11-26T12:00:00Z-ab12"
    start(box, run_id)
    found = world.call("bare_a", "GET", f"{API}/{target}/runs/{run_id}", expect=200)
    assert isinstance(found, dict)
    assert (found["key_wait"]["key"], found["key_wait"]["page"]) == (KEY, PAGE)
    card = world.call("bare_a", "GET", f"{API}/{target}/key-wait", expect=200)
    assert isinstance(card, dict) and card["key"] == KEY
    for who in ("admin_b", "outsider"):
        world.call(who, "GET", f"{API}/{target}/runs/{run_id}", expect=404)
        world.call(who, "GET", f"{API}/{target}/key-wait", expect=404)
