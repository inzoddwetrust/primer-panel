"""What a box sends, checked before a person sees it (DM-210): the grid around
the probes of ``test_probe_dm_210.py`` -- the page of a key, a notice that
does not read, numbers that are none, moments that are no dates.

The SQL of these tests carries the tests' own values only."""
# ruff: noqa: S608

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.database import make_engine, make_sessions
from app.fleet.reasons import moment
from app.runs import router as runs_router
from app.runs.keys import PAGE_MAX, https_page
from app.runs.router import stream_lines
from tests.conftest import execute, query_scalar
from tests.fake_box import RUN_ID, header_line
from tests.people import World
from tests.test_agent import registered
from tests.test_fleet import fleet, reasons_of, snapshot
from tests.test_fleet import server as fleet_server
from tests.test_key_wait import KEY, PAGE, RUN, notice, wait_of, waiting_run

# --- the page of a key ---------------------------------------------------------

LINKS = [
    "https://github.com/o/velo/settings/keys",
    "https://github.com",
    "https://github.com:443/o/velo?tab=keys#new",
    "https://xn--e1afmkfd.xn--p1ai/keys",
    "https://[2001:db8::1]/keys",
    "https://h/" + "k" * (PAGE_MAX - len("https://h/")),
]
NO_LINKS: list[object] = [
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    " javascript:alert(1)",
    "java\tscript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "http://github.com/o/velo/settings/keys",
    "HTTPS://github.com/o",  # the scheme as it is written, no other
    "https:github.com/o",
    "https:/github.com/o",
    "https://",
    "https:///o/velo",
    "https://user@github.com/o",
    "https://user:secret@github.com/o",
    "https://github.com/o velo",
    "https://github.com/o\nvelo",
    "https://github.com/o\x00",
    "https://github.com/\u202egnp.exe",  # a control of the direction of text
    "https://[not-an-address/keys",
    "//github.com/o/velo",
    "/o/velo/settings/keys",
    "github.com/o/velo",
    "",
    "https://h/" + "k" * (PAGE_MAX - len("https://h/") + 1),
    None,
    5,
    True,
    ["https://github.com/o"],
    {"href": "https://github.com/o"},
]


@pytest.mark.parametrize("page", LINKS)
def test_an_https_address_is_the_link_as_it_came(page: str) -> None:
    assert https_page(page) == page


@pytest.mark.parametrize("page", NO_LINKS, ids=repr)
def test_anything_else_is_no_link(page: object) -> None:
    """Each part of the rule by a value that breaks it alone: the scheme, the
    host, a name before the host, a space, a control character, the length,
    the type. The pair is the list above -- the same function gives a link."""
    assert https_page(page) is None


# --- a notice that does not read ----------------------------------------------

OFF_FORM: list[tuple[str, dict[str, object]]] = [
    ("wait_s a text", {"wait_s": "1800"}),
    ("wait_s a flag", {"wait_s": True}),
    ("wait_s a list", {"wait_s": [1800]}),
    ("write a number", {"write": 1}),
    ("write a text", {"write": "false"}),
    ("again a number", {"again": 0}),
    ("again a text", {"again": "no"}),
    ("repo empty", {"repo": ""}),
    ("repo a number", {"repo": 5}),
    ("key empty", {"key": ""}),
    ("key a list", {"key": [KEY]}),
]


def _routes(world: World, target: object) -> tuple[object, object]:
    page = world.call(
        "admin_a", "GET", f"/api/v1/servers/{target}/runs/{RUN}", expect=200
    )
    assert isinstance(page, dict)
    card = world.call(
        "admin_a", "GET", f"/api/v1/servers/{target}/key-wait", expect=200
    )
    return page["key_wait"], card


@pytest.mark.parametrize(("name", "given"), OFF_FORM, ids=[n for n, _ in OFF_FORM])
def test_a_key_of_another_type_is_no_wait(
    world: World, name: str, given: dict[str, object]
) -> None:
    """No text is taken for a number, no number for a flag, no empty text
    for a repository or a key: no wait, 200 on both routes."""
    target = waiting_run(world, notice(2, **given))
    assert _routes(world, target) == (None, None), name


def test_a_line_without_its_moment_or_its_notice_as_an_object_is_no_wait(
    world: World,
) -> None:
    """Twin SHORTAGE of the line itself: no ``at`` -- no wait. (A ``notice``
    that is no object has no ``kind``: the rule finds no notice at all.)"""
    whole = notice(2)
    del whole["at"]
    target = waiting_run(world)
    execute(
        world.url,
        "INSERT INTO events (run_id, seq, at, body) VALUES "
        f"('{RUN}', 2, '2026-11-26T12:00:02.000Z', '{json.dumps(whole)}'::jsonb)",
    )
    assert _routes(world, target) == (None, None)


def test_keys_the_panel_does_not_know_are_passed_over(world: World) -> None:
    """A key the machine adds does not put the wait out, and is not shown."""
    target = waiting_run(world, notice(2, hint="add it as a deploy key", ttl_s=5))
    found = wait_of(world, target)
    assert isinstance(found, dict)
    assert sorted(found) == [
        "again",
        "at",
        "key",
        "page",
        "reason",
        "repo",
        "run_id",
        "state",
        "wait_s",
        "why",
        "write",
    ]
    assert found["page"] == PAGE


def test_why_and_page_of_another_type_are_nothing_not_an_error(world: World) -> None:
    target = waiting_run(
        world, notice(2, why=5, page=["https://github.com"], write=True)
    )
    found = wait_of(world, target)
    assert isinstance(found, dict)
    assert (found["why"], found["page"], found["write"]) == (None, None, True)


@pytest.mark.parametrize(
    ("given", "shown"), [(-5.0, -5.0), (0, 0.0), (1800, 1800.0), (0.5, 0.5)]
)
def test_a_wait_of_any_number_is_shown_as_it_is(
    world: World, given: float, shown: float
) -> None:
    """A negative wait passes the agent's API: it is a wait that ended before
    it began, and is shown so -- no 500, no ``null``. A whole number is a
    number."""
    target = waiting_run(world, notice(2, wait_s=given))
    found = wait_of(world, target)
    assert isinstance(found, dict) and found["wait_s"] == shown
    assert isinstance(found["wait_s"], float)


def test_the_last_notice_unread_is_no_wait_whatever_was_before(world: World) -> None:
    """Twin REPEAT: the wait is the last notice; one that does not read is
    not replaced by the one before it. The pair -- two that read, the last
    is the wait -- is ``test_the_last_notice_is_the_wait``."""
    target = waiting_run(world, notice(2), notice(3, wait_s="soon"))
    assert _routes(world, target) == (None, None)


def _unread(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    return [
        record.ctx  # type: ignore[attr-defined]
        for record in caplog.records
        if getattr(record, "event", "") == event
    ]


def test_an_unread_notice_is_logged_by_its_fields_and_no_value(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="app.runs.keys")
    target = waiting_run(world, notice(2, wait_s="soon", repo=None))
    assert _routes(world, target) == (None, None)
    said = _unread(caplog, "runs.notice_off_form")
    assert (
        said
        == [{"run_id": RUN, "seq": 2, "fields": ["notice.repo", "notice.wait_s"]}] * 2
    )  # the run's page and the card's route: a request, a line
    assert KEY not in caplog.text and "soon" not in caplog.text


async def _parts(stream: AsyncIterator[str], count: int) -> list[str]:
    return [await asyncio.wait_for(anext(stream), 5) for _ in range(count)]


def test_the_stream_goes_on_past_an_unread_notice_and_logs_it_once(
    world: World,
    migrated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The stream asks for the wait at every poll. A notice that does not
    read: the lines go on, no ``event: key``, no end of the stream -- and one
    line of the log for it over many polls, not one a poll. The pair: a
    notice that reads, later in the same stream, is said as ``key``."""
    monkeypatch.setattr(runs_router, "POLL_S", 0.05)
    monkeypatch.setattr(runs_router, "KEEPALIVE_S", 10.0)
    caplog.set_level(logging.WARNING, logger="app.runs.keys")
    target = waiting_run(world, notice(2, again="yes"))

    async def scenario() -> list[str]:
        engine = make_engine(migrated_db)
        sessions = make_sessions(engine)

        async def write(body: dict[str, object]) -> None:
            async with sessions() as session, session.begin():
                await session.execute(
                    text(
                        "INSERT INTO events (run_id, seq, at, body) VALUES "
                        f"('{RUN}', {body['seq']}, '{body['at']}', "
                        f"'{json.dumps(body)}'::jsonb)"
                    )
                )

        async def never() -> bool:
            return False

        stream = stream_lines(sessions, target, RUN, 0, never)
        got: list[str] = []
        try:
            got += await _parts(stream, 3)  # the header, the notice, the state
            # the stream polls only while it is read: read on, with nothing
            # new for ten polls, then the notice that reads
            rest = asyncio.create_task(_parts(stream, 2))
            await asyncio.sleep(0.5)
            assert not rest.done()
            await write(notice(3))
            got += await rest  # the line, then the key
        finally:
            await engine.dispose()
        return got

    got = asyncio.run(scenario())
    kinds = [part.split("event: ")[1].split("\n")[0] for part in got]
    assert kinds == ["line", "line", "status", "line", "key"]
    [key] = [
        json.loads(part.split("data: ")[1]) for part in got if "event: key" in part
    ]
    assert key["state"] == "waiting" and key["at"] == "2026-11-26T12:00:03.000Z"
    assert _unread(caplog, "runs.notice_off_form") == [
        {"run_id": RUN, "seq": 2, "fields": ["notice.again"]}
    ]


# --- numbers that are none, at the agent's door -----------------------------------


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e400", "-1e400"])
def test_a_number_that_is_none_is_refused_not_a_500(world: World, number: str) -> None:
    """``wait_s: NaN`` reads by the model of contract 4 and cannot be kept in
    a table of JSON: it was a 500 of ``POST …/events``, at every retry of the
    box. It is a body not of the contract -- 422, nothing kept. The pair: a
    negative number is one -- 200, kept."""
    box = registered(world)
    path = f"/runs/{RUN_ID}/events"
    assert (
        box.send("POST", path, {"from_seq": 1, "events": [header_line()]}).status_code
        == 200
    )
    line = notice(2)
    body = json.dumps({"from_seq": 2, "events": [line]}).replace("1800.0", number)
    assert number in body
    answer = box.send("POST", path, body.encode())
    assert answer.status_code == 422, answer.text
    assert answer.json()["error"]["class"] == "invalid"
    count = f"SELECT count(*) FROM events WHERE run_id = '{RUN_ID}'"
    assert query_scalar(world.url, count) == 1
    good = json.dumps({"from_seq": 2, "events": [line]}).replace("1800.0", "-5.0")
    assert box.send("POST", path, good.encode()).json() == {"last_seq": 2}
    assert query_scalar(world.url, count) == 2


# --- moments that are no dates ---------------------------------------------------

NO_DATES = [
    "2026-13-45T99:99:99Z",
    "2026-02-30T00:00:00Z",
    "2026-11-24T24:00:00Z",
    "2026-11-24T10:60:00Z",
    "0000-01-01T00:00:00Z",
]


@pytest.mark.parametrize("value", NO_DATES)
def test_a_text_of_the_form_of_a_moment_that_is_no_date(value: str) -> None:
    assert moment(value) is None


def test_a_moment_is_read_as_utc() -> None:
    assert moment("2026-11-24T10:42:07Z") == datetime(
        2026, 11, 24, 10, 42, 7, tzinfo=UTC
    )


@pytest.mark.parametrize("value", NO_DATES)
def test_an_end_that_is_no_date_is_no_data(
    world: World, value: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Not red for the certificate, no ``ssl`` on the page, one line of the
    log naming the server and the field -- for every way a text of the form
    is no date."""
    caplog.set_level(logging.WARNING, logger="app.fleet.router")
    state = snapshot()
    ssl = state["ssl"]
    assert isinstance(ssl, dict)
    ssl["expires"] = value
    odd = fleet_server(world, "odd", state=state)
    [row] = fleet(world)
    assert reasons_of(row) == [] and row["ssl"] is None
    assert _unread(caplog, "fleet.ssl_moment_unread") == [
        {"server_id": str(odd), "fields": ["expires"]}
    ]
    assert value not in caplog.text


def test_a_start_of_renewal_that_is_no_date_leaves_the_end(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    """The end reads and is far: not due; the start of renewal that is no
    date is not shown, the end is. The pair: the end has come -- due by the
    end, whatever the start is."""
    caplog.set_level(logging.WARNING, logger="app.fleet.router")
    state = snapshot(expires_in=timedelta(days=60))
    ssl = state["ssl"]
    assert isinstance(ssl, dict)
    ssl["renews_from"] = "2026-02-30T00:00:00Z"
    fleet_server(world, "a-far", state=state)
    ended = snapshot(expires_in=timedelta(days=-1))
    ended_ssl = ended["ssl"]
    assert isinstance(ended_ssl, dict)
    ended_ssl["renews_from"] = "2026-02-30T00:00:00Z"
    fleet_server(world, "b-ended", state=ended)
    rows = {str(row["name"]): row for row in fleet(world)}
    far = rows["a-far"]["ssl"]
    assert isinstance(far, dict)
    assert (reasons_of(rows["a-far"]), far["renews_from"]) == ([], None)
    assert far["expires"] == ssl["expires"]
    assert reasons_of(rows["b-ended"]) == ["ssl-due"]
    said = _unread(caplog, "fleet.ssl_moment_unread")
    assert [each["fields"] for each in said] == [["renews_from"], ["renews_from"]]
