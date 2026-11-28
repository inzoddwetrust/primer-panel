"""``self-update`` from the Panel (DM-218): the grid around its probe -- the
box that cannot run it, the tag that is no release of the table, the field
only tier 3 gives, a rollback, the repeat of a run.

The SQL of these tests carries the tests' own values only."""

import pytest

from app.agent import verbs
from tests.conftest import execute, query_scalar
from tests.fake_box import RUN_ID, header_line
from tests.people import World
from tests.test_agent import queue_command, registered, server_of
from tests.test_probe_dm_218 import LOWER, UPPER, beat, short_poll, two_releases

__all__ = ["short_poll"]

CONSOLE = "update it from the console"


def commands(world: World) -> object:
    return query_scalar(world.url, "SELECT count(*) FROM commands")


def refused(answer: object) -> str:
    assert isinstance(answer, dict)
    error = answer["error"]
    assert isinstance(error, dict) and error["class"] == "invalid", answer
    return str(error["message"])


@pytest.mark.parametrize("version", ["0.1.10", "0.1.11", "0.1.11.1", "0.0.99"])
def test_a_box_below_the_first_release_with_the_verb_is_refused(
    world: World, version: str
) -> None:
    """Its agent has no ``self-update``: refused before the queue, saying the
    box's machine and the console. The pair: the box on the first release is
    queued."""
    box = registered(world)
    beat(box, version)
    server = server_of(world, box)
    message = refused(
        queue_command(
            world, server, "self-update", {"tag": "v0.1.12"}, who="super", expect=422
        )
    )
    assert message == (
        f"the machine of this server is {version}, with no self-update "
        f"(from v0.1.12) -- {CONSOLE}"
    )
    assert commands(world) == 0
    beat(box, "0.1.12")
    queue_command(world, server, "self-update", {"tag": "v0.1.12"}, who="super")
    assert commands(world) == 1


@pytest.mark.parametrize("version", [None, "not-a-version"])
def test_a_box_whose_machine_is_not_known_is_refused(
    world: World, version: str | None
) -> None:
    """No heartbeat yet, or a version that is none: not known -- refused. (An
    empty version is contract 4's to refuse at the heartbeat.)"""
    box = registered(world)
    if version is not None:
        beat(box, version)
    message = refused(
        queue_command(
            world,
            server_of(world, box),
            "self-update",
            {"tag": "v0.1.12"},
            who="super",
            expect=422,
        )
    )
    assert message == f"the machine of this server is not known -- {CONSOLE}"
    assert commands(world) == 0


@pytest.mark.parametrize(
    "tag", ["v0.1.11", "v0.1.13", "0.1.12", "v0.1.12 ", "latest", "", 12]
)
def test_a_tag_that_is_no_release_of_the_table_is_refused(
    world: World, tag: object
) -> None:
    box = registered(world)
    beat(box, "0.1.12")
    answer = queue_command(
        world,
        server_of(world, box),
        "self-update",
        {"tag": tag},
        who="super",
        expect=422,
    )
    refused(answer)
    assert commands(world) == 0


def test_the_field_of_tier_3_is_no_field_of_the_button(world: World) -> None:
    """``source`` (``--from``) passes the machine's model with a loopback
    address -- and is no field of the button: refused."""
    box = registered(world)
    beat(box, "0.1.12")
    args = {"tag": "v0.1.12", "source": "http://127.0.0.1:8080/install.sh"}
    message = refused(
        queue_command(
            world, server_of(world, box), "self-update", args, who="super", expect=422
        )
    )
    assert message == "source is no field of the button self-update"
    assert commands(world) == 0


def test_no_tag_is_refused(world: World) -> None:
    box = registered(world)
    beat(box, "0.1.12")
    refused(
        queue_command(
            world, server_of(world, box), "self-update", {}, who="super", expect=422
        )
    )


def test_self_update_is_of_the_permission_servers_on_any_role(world: World) -> None:
    """``deploy_test`` is not enough; the superadmin holds ``servers``."""
    box = registered(world)
    beat(box, "0.1.12")
    server = server_of(world, box)
    answer = queue_command(
        world, server, "self-update", {"tag": "v0.1.12"}, who="staff_a", expect=403
    )
    assert isinstance(answer, dict) and "servers" in str(answer["error"]["message"])
    queue_command(world, server, "self-update", {"tag": "v0.1.12"}, who="super")


def test_a_rollback_is_confirmed_on_any_role(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tag below the box's machine: "are you sure?" first, on ``test`` too
    -- unconfirmed it is a conflict and nothing is queued; confirmed it is
    queued with no ``confirmed_at`` (it is not destructive: no name). The
    pair: the same tag on a box at it, and a tag above, need nothing."""
    two_releases(monkeypatch)
    box = registered(world)
    beat(box, UPPER)
    server = server_of(world, box)
    down = {"tag": f"v{LOWER}"}
    queue_command(world, server, "self-update", down, who="super", expect=409)
    assert commands(world) == 0
    made = queue_command(
        world, server, "self-update", down, who="super", confirmed=True
    )
    assert isinstance(made, dict) and made["confirmed_at"] is None
    execute(world.url, "DELETE FROM commands")
    beat(box, LOWER)
    queue_command(world, server, "self-update", down, who="super")  # the same
    execute(world.url, "DELETE FROM commands")
    queue_command(world, server, "self-update", {"tag": f"v{UPPER}"}, who="super")


def test_the_repeat_of_a_self_update_asks_for_a_rollback(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run of ``self-update v0.1.12`` on a box at v0.1.13 now: its repeat is
    a rollback, ``sure``; the box back at v0.1.12 -- not."""
    two_releases(monkeypatch)
    box = registered(world)
    beat(box, UPPER)
    header = header_line(verb="self-update")
    header["args"] = {"tag": f"v{LOWER}"}
    assert (
        box.send(
            "POST", f"/runs/{RUN_ID}/events", {"from_seq": 1, "events": [header]}
        ).status_code
        == 200
    )
    page = f"/api/v1/servers/{server_of(world, box)}/runs/{RUN_ID}"
    found = world.call("super", "GET", page, expect=200)
    assert isinstance(found, dict)
    assert found["repeat"] == {
        "verb": "self-update",
        "args": {"tag": "v0.1.12"},
        "sure": True,
        "name": False,
    }
    beat(box, LOWER)
    found = world.call("super", "GET", page, expect=200)
    assert isinstance(found, dict) and found["repeat"]["sure"] is False


@pytest.mark.parametrize(
    ("args", "machine", "back"),
    [
        ({"tag": "v0.1.12"}, "0.1.13", True),
        ({"tag": "v0.1.12"}, "0.1.12", False),
        ({"tag": "v0.1.13"}, "0.1.12", False),
        ({"tag": "v0.1.12"}, None, False),
        ({"tag": "v0.1.12"}, "odd", False),
        ({"tag": "odd"}, "0.1.13", False),
        ({}, "0.1.13", False),
    ],
)
def test_rolls_back_by_versions_not_texts(
    args: dict[str, object], machine: str | None, back: bool
) -> None:
    assert verbs.rolls_back("self-update", args, machine) is back
    assert verbs.rolls_back("update", args, machine) is False


def test_no_self_update_says_nothing_of_another_verb() -> None:
    assert verbs.no_self_update("update", None) is None
    assert verbs.no_self_update("self-update", "0.1.12") is None
    assert verbs.no_self_update("self-update", "0.1.13") is None
