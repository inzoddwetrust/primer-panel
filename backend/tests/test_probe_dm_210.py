"""The probes of DM-210 (PRIMER-PANEL-REVIEW-0001): what a box sends reaches a
person only checked, and one box's crooked data takes no screen down.

- ``page`` of a ``key_needed`` is an ``https`` address or nothing;
- a ``key_needed`` that does not read is no wait, and every route that reads
  it answers 200;
- an SSL moment that has the form of one and is no date leaves the fleet up.

The probe of the page's paths is the frontend's (``src/api/paths.spec.ts``).
The SQL of these tests carries the tests' own values only."""
# ruff: noqa: S608

import uuid
from datetime import timedelta

from tests.conftest import execute
from tests.people import World
from tests.test_fleet import fleet, reasons_of, snapshot
from tests.test_fleet import server as fleet_server
from tests.test_key_wait import KEY, PAGE, RUN, notice, wait_of, waiting_run

JS = "javascript:alert(document.cookie)"


def _wait(world: World, target: uuid.UUID) -> dict[str, object]:
    found = wait_of(world, target)
    assert isinstance(found, dict), found
    return found


def test_probe_dm_210_page_is_https_or_none(world: World) -> None:
    """The agent's API takes ``page: "javascript:…"`` -- contract 4 types it
    as any text -- and the page of the Panel makes a link of ``page``. So the
    run's page, the card's route and nothing else give a ``page`` that is not
    an ``https`` address: ``javascript:``, ``data:``, ``http:`` are ``null``
    and the rest of the wait is as it was. The pair, in the same run: the
    notice after it, with the address of GitHub, gives that address."""
    for seq, crooked in enumerate(
        (JS, "data:text/html,<script>alert(1)</script>", "http://github.com/o/velo"),
        start=2,
    ):
        target = waiting_run(world, notice(seq, page=crooked))
        found = _wait(world, target)
        assert found["page"] is None, crooked
        assert (found["key"], found["state"]) == (KEY, "waiting")
        card = world.call("admin_a", "GET", f"/api/v1/servers/{target}/key-wait")
        assert isinstance(card, dict) and card["page"] is None, crooked
        _forget(world)
    target = waiting_run(world, notice(2, page=JS), notice(3))
    assert (
        _wait(world, target)["page"]
        == PAGE
        == "https://github.com/o/velo/settings/keys"
    )


def _forget(world: World) -> None:
    """The run of ``waiting_run`` off the table: the next case writes it anew."""
    execute(
        world.url,
        f"DELETE FROM events WHERE run_id = '{RUN}'",
        f"DELETE FROM runs WHERE run_id = '{RUN}'",
        "DELETE FROM server_states",
        "DELETE FROM servers",
    )


def test_probe_dm_210_notice_off_form_is_no_wait(world: World) -> None:
    """A ``key_needed`` in the table without a key the wait is made of -- a
    line taken by another pin of the machine: it outlives the pin. The run's
    page answers 200 with ``key_wait: null`` and the card's route 200 with
    ``null`` -- no 500 -- for each of the five keys left out, one at a time.
    The pair: the same line whole is the wait."""
    for missing in ("repo", "key", "write", "wait_s", "again"):
        target = waiting_run(world, notice(2, **{missing: None}))
        page = world.call(
            "admin_a", "GET", f"/api/v1/servers/{target}/runs/{RUN}", expect=200
        )
        assert isinstance(page, dict) and page["key_wait"] is None, missing
        card = world.call(
            "admin_a", "GET", f"/api/v1/servers/{target}/key-wait", expect=200
        )
        assert card is None, missing
        _forget(world)
    target = waiting_run(world, notice(2))
    assert _wait(world, target)["repo"] == "git@github.com:o/velo.git"


def test_probe_dm_210_ssl_date_that_is_no_date_leaves_the_fleet_up(
    world: World,
) -> None:
    """``2026-13-45T99:99:99Z`` has the form of a moment of ``box-state.v1``
    -- the snapshot reads -- and is no date. The fleet answers 200 with every
    server in it; the box that sent it is not red for its certificate and has
    no ``ssl`` (no data), its other facts are there; the card of that server
    answers 200 too. The pair: a server beside it whose certificate is due is
    red for it, with its ``ssl``."""
    crooked = snapshot()
    ssl = crooked["ssl"]
    assert isinstance(ssl, dict)
    ssl["expires"] = "2026-13-45T99:99:99Z"
    odd = fleet_server(world, "a-odd", state=crooked)
    fleet_server(world, "b-due", state=snapshot(renews_in=timedelta(days=-1)))
    rows = {str(row["name"]): row for row in fleet(world)}
    assert sorted(rows) == ["a-odd", "b-due"]
    assert reasons_of(rows["a-odd"]) == [] and rows["a-odd"]["ssl"] is None
    assert rows["a-odd"]["health"] == {
        "healthy": 2,
        "unhealthy": 0,
        "starting": 0,
        "none": 0,
    }
    assert reasons_of(rows["b-due"]) == ["ssl-due"]
    due = rows["b-due"]["ssl"]
    assert isinstance(due, dict) and due["mode"] == "letsencrypt"
    card = world.call("super", "GET", f"/api/v1/servers/{odd}", expect=200)
    assert isinstance(card, dict) and card["ssl"] is None and card["reasons"] == []
