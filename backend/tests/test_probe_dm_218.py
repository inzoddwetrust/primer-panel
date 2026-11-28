"""The probe of DM-218: the machine updates itself from the Panel.

The button ``self-update`` on a server's card -> a command with a tag of the
releases the Panel knows -> the box's agent takes it, its run ends green ->
the next heartbeat carries the new machine: the fleet shows it and the server
is not behind any more. Today the releases with the verb are one, the pin
itself (``v0.1.12``); the probe takes the table as data -- two releases, the
Panel pinned on the upper, the box on the lower -- since a real box below the
first release has no such verb and is refused before the queue. The real
table is held by its own test, written out.

The box is ``tests.fake_box``: a box of contract 4, signing every request.
The SQL of these tests carries the tests' own values only."""
# ruff: noqa: S608

import pytest
from pridem.protocol import verdict_bytes

from app.agent import queue, verbs
from app.fleet import reasons
from app.fleet import router as fleet_router
from tests.conftest import query_scalar
from tests.fake_box import RUN_ID, FakeBox, header_line, verdict
from tests.people import World
from tests.test_agent import queue_command, registered, server_of
from tests.test_fleet import reasons_of

LOWER, UPPER = "0.1.12", "0.1.13"
RELEASES = (f"v{LOWER}", f"v{UPPER}")


@pytest.fixture(autouse=True)
def short_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue, "POLL_WINDOW_S", 0.3)
    monkeypatch.setattr(queue, "POLL_PAUSE_S", 0.05)


def two_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    """The releases with ``self-update`` as data: two, the Panel pinned on the
    last -- the table's own rule."""
    monkeypatch.setattr(verbs, "MACHINE_RELEASES", RELEASES)
    monkeypatch.setattr(reasons, "PINNED_RELEASE", UPPER)
    monkeypatch.setattr(fleet_router, "PINNED_RELEASE", UPPER)


def beat(box: FakeBox, version: str) -> None:
    body = {
        "measured_at": "2026-11-28T12:00:00Z",
        "machine_version": version,
        "lock_open_by": [],
        "journals_without_verdict": [],
    }
    assert box.send("POST", "/heartbeat", body).status_code == 204


def row(world: World, name: str) -> dict[str, object]:
    found = world.call("super", "GET", "/api/v1/servers", expect=200)
    assert isinstance(found, list)
    [mine] = [server for server in found if server["name"] == name]
    assert isinstance(mine, dict)
    return mine


def self_update_button(
    world: World, who: str, box: FakeBox
) -> dict[str, object] | None:
    found = world.call(who, "GET", f"/api/v1/servers/{server_of(world, box)}/verbs")
    assert isinstance(found, list)
    mine = [button for button in found if button["verb"] == "self-update"]
    return mine[0] if mine else None


def test_probe_dm_218_self_update_from_the_button_to_the_new_heartbeat(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The button is the superadmin's (``servers``), not the staff's of
    ``deploy_test``; its one field is ``tag``, the releases as its choices,
    no ``source``; it asks "are you sure?" by ``tag`` below the box's
    machine. Queued with the upper tag, the box takes the command with that
    tag alone; its run ends green with its verdict; the next heartbeat says
    the upper release. The fleet shows it, and ``machine-behind`` -- there
    before, while the box said the lower -- is gone."""
    two_releases(monkeypatch)
    box = registered(world, "velo-test-1")
    beat(box, LOWER)
    before = row(world, "velo-test-1")
    assert before["machine_version"] == LOWER
    assert reasons_of(before) == ["machine-behind"]

    button = self_update_button(world, "super", box)
    assert button is not None
    assert button["schema"] == {
        "type": "object",
        "properties": {
            "tag": {"title": "Tag", "type": "string", "enum": ["v0.1.12", "v0.1.13"]}
        },
        "required": ["tag"],
    }
    assert (button["positionals"], button["sure_below"]) == (["tag"], "tag")
    assert (button["name"], button["sure"]) == ("never", False)
    assert self_update_button(world, "staff_a", box) is None  # deploy_test only

    made = queue_command(
        world, server_of(world, box), "self-update", {"tag": "v0.1.13"}, who="super"
    )
    assert isinstance(made, dict)
    given = box.send("GET", "/commands/next")
    assert given.status_code == 200
    command = given.json()
    assert (command["id"], command["verb"], command["args"]) == (
        made["id"],
        "self-update",
        {"tag": "v0.1.13"},
    )

    header = header_line(verb="self-update", command=str(made["id"]))
    header["args"] = {"tag": "v0.1.13"}
    sent = box.send(
        "POST", f"/runs/{RUN_ID}/events", {"from_seq": 1, "events": [header]}
    )
    assert sent.status_code == 200
    raw = verdict(command=str(made["id"]))
    raw.update(
        verb="self-update",
        args={"tag": "v0.1.13"},
        composition_before={"pridem": LOWER},
        composition_after={"pridem": LOWER},
    )
    envelope = {
        "verdict": raw,
        "signature": box.sign(verdict_bytes(raw)),
        "report_llm": "a report",
        "signed_on_send": False,
    }
    assert box.send("POST", f"/runs/{RUN_ID}/verdict", envelope).status_code == 204
    state = f"SELECT state FROM commands WHERE id = '{made['id']}'"
    assert query_scalar(world.url, state) == "done"

    beat(box, UPPER)  # the agent of the new machine, up again
    after = row(world, "velo-test-1")
    assert after["machine_version"] == UPPER
    assert reasons_of(after) == []


def test_the_releases_the_panel_knows_are_written_out() -> None:
    """The real table, written out: one release with ``self-update`` -- the
    Panel's own pin, the last of it."""
    import pridem

    assert verbs.MACHINE_RELEASES == ("v0.1.12",)
    assert verbs.MACHINE_RELEASES[-1] == f"v{pridem.__version__}"
