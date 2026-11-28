"""A server's card (DM-155): its head, its runs, its buttons -- and the rules a
command of a button meets before the queue.

The SQL of these tests carries the tests' own values only."""
# ruff: noqa: S608

import uuid
from collections.abc import Mapping

from tests.conftest import execute, query_scalar
from tests.people import World

API = "/api/v1/servers"


def server(
    world: World, name: str, role: str = "test", project: str = "a"
) -> uuid.UUID:
    server_id = uuid.uuid4()
    execute(
        world.url,
        "INSERT INTO servers (id, project_id, name, role, box_id, box_key_public) "
        f"VALUES ('{server_id}', '{world.projects[project]}', '{name}', '{role}', "
        f"'{uuid.uuid4()}', 'key')",
    )
    return server_id


def labels(world: World, who: str, server_id: uuid.UUID) -> list[str]:
    found = world.call(who, "GET", f"{API}/{server_id}/verbs", expect=200)
    assert isinstance(found, list)
    return [
        f"{b['verb']}:{b['preset']['action']}" if b["preset"] else b["verb"]
        for b in found
    ]


def queue(
    world: World,
    server_id: uuid.UUID,
    verb: str,
    args: Mapping[str, object] | None = None,
    *,
    confirmed: bool = False,
    who: str = "super",
    expect: int = 201,
) -> object:
    body = {"verb": verb, "args": dict(args or {}), "confirmed": confirmed}
    path = f"{API}/{server_id}/commands"
    return world.call(who, "POST", path, body, expect=expect)


def commands(world: World) -> object:
    return query_scalar(world.url, "SELECT count(*) FROM commands")


# The buttons, written out (not VERBS of the code): the pinned release v0.1.12
# (changed by DM-218): ``self-update`` is one, and they come in the machine's
# groups -- server, deploy, data, host, project -- the registry's order inside
# a group.
READING = ["status"]
DEPLOY = [
    "doctor",
    "start",
    "stop",
    "restart",
    "install",
    "update",
    "deploy",
    "rollback",
    "gc",
    "ssl:renew",
]
ALL_BUTTONS = [
    "status",
    "self-update",
    "doctor",
    "start",
    "stop",
    "restart",
    "install",
    "update",
    "deploy",
    "rollback",
    "reinstall",
    "destroy",
    "db",
    "backup",
    "seed",
    "gc",
    "ssl:renew",
    "verb",
]


# What is not a button, written out (not VERBS of the code): the pinned release
# (v0.1.12 since DM-218, the same list as v0.1.10) -- the verbs without a
# verdict, the values of a field that write none and NOT_A_BUTTON (DM-202), as
# labels and as commands.
NOT_BUTTONS = [
    "version",
    "state",
    "report",
    "logs",
    "ssl:status",
    "db:connect",
    "check",
    "register",
]
NOT_BUTTON_COMMANDS: list[tuple[str, dict[str, object]]] = [
    ("version", {}),
    ("state", {}),
    ("report", {"run_id": "2026-11-24T12:00:00Z-ab12"}),
    ("logs", {"stack": "velo"}),
    ("ssl", {"action": "status"}),
    ("db", {"action": "connect", "stack": "velo"}),
    ("check", {"path": "/srv/velo"}),
    ("register", {}),
]


def offered(world: World, who: str, server_id: uuid.UUID) -> set[str]:
    """What a person's buttons offer: each button's label, and its verb with
    every value its form offers for ``action``."""
    found = world.call(who, "GET", f"{API}/{server_id}/verbs", expect=200)
    assert isinstance(found, list)
    offers = set(labels(world, who, server_id))
    for button in found:
        action = button["schema"]["properties"].get("action")
        if action is not None:
            offers |= {f"{button['verb']}:{value}" for value in action["enum"]}
    return offers


def test_probe_DM_155_no_button_without_permission(world: World) -> None:
    """A person has the buttons of the permissions they hold on the server's
    role, nothing more. The pair: the superadmin has every verb of a box.

    Changed by DM-202, by the dispatcher's word on its gate: a button is a verb
    that ends with a verdict -- ``version``, ``state``, ``report``, ``logs``
    and ``ssl status`` are no buttons any more, so ``READING`` is ``status``
    alone and the lists are of the pinned release v0.1.10.

    Changed by DM-218, by the dispatcher's word on its gate (R6): the pin is
    v0.1.12 -- ``self-update`` is a button, of ``servers`` (the superadmin's
    list has it, the staff's of ``deploy_test`` has not), and the buttons come
    in the machine's groups. The assertions are as they were."""
    test, prod = server(world, "velo-test"), server(world, "velo-prod", "prod")
    staff = labels(world, "staff_a", test)  # deploy_test
    assert sorted(staff) == sorted(READING + DEPLOY)
    assert labels(world, "staff_a", prod) == READING  # no deploy_prod
    assert labels(world, "people_a", test) == READING  # only people
    assert labels(world, "super", prod) == ALL_BUTTONS
    assert "check" not in labels(world, "super", test)


def test_probe_DM_155_destructive_never_queued_unconfirmed(world: World) -> None:
    """Every destructive action without its confirmation stays out of the
    queue; with a name not exactly the server's -- refused. The pair: typed
    exactly and confirmed, it is queued."""
    target = server(world, "velo-test")
    unconfirmed: list[tuple[str, dict[str, object]]] = [
        ("destroy", {}),
        ("reinstall", {}),
        ("db", {"action": "restore", "stack": "velo", "dump": "d1"}),
        ("db", {"action": "reset", "stack": "velo"}),
        ("seed", {"stack": "velo", "reset": True}),
        ("seed", {"stack": "velo", "reset_only": True}),
        ("seed", {"reset_all": True, "stack": "velo"}),
    ]
    for verb, args in unconfirmed:
        queue(world, target, verb, args, expect=409)
        queue(world, target, verb, {**args, "confirm": "velo-test"}, expect=409)
    for wrong in ("Velo-test", " velo-test", "velo-test ", "velo-tes"):
        args = {"action": "restore", "stack": "velo", "dump": "d1", "confirm": wrong}
        queue(world, target, "db", args, confirmed=True, expect=422)
    assert commands(world) == 0
    args = {"action": "restore", "stack": "velo", "dump": "d1", "confirm": "velo-test"}
    made = queue(world, target, "db", args, confirmed=True)
    assert isinstance(made, dict) and made["confirmed_at"] is not None
    assert commands(world) == 1


def test_a_project_verb_with_a_name_is_destructive(world: World) -> None:
    target = server(world, "velo-test")
    queue(world, target, "verb", {"name": "wipe", "confirm": "velo-test"}, expect=409)
    made = queue(
        world, target, "verb", {"name": "wipe", "confirm": "velo-test"}, confirmed=True
    )
    assert isinstance(made, dict) and made["confirmed_at"] is not None
    plain = queue(world, target, "verb", {"name": "hello"})
    assert isinstance(plain, dict) and plain["confirmed_at"] is None


def test_a_name_with_nothing_destructive_is_refused(world: World) -> None:
    target = server(world, "velo-test")
    args = {"action": "dump", "stack": "velo", "confirm": "velo-test"}
    queue(world, target, "db", args, confirmed=True, expect=422)


def test_prod_asks_are_you_sure_but_for_reading(world: World) -> None:
    prod = server(world, "velo-prod", "prod")
    queue(world, prod, "update", expect=409)
    queue(world, prod, "doctor", expect=409)
    made = queue(world, prod, "update", confirmed=True)
    assert isinstance(made, dict) and made["confirmed_at"] is None
    # Changed by DM-202: of the reading verbs only status is a button
    queue(world, prod, "status")
    test = server(world, "velo-test")
    queue(world, test, "update")  # test: no confirmation


def test_a_form_carries_no_file_of_the_box(world: World) -> None:
    target = server(world, "velo-test")
    found = world.call("super", "GET", f"{API}/{target}/verbs", expect=200)
    assert isinstance(found, list)
    forms = {
        (b["verb"], b["preset"].get("action")): set(b["schema"]["properties"])
        for b in found
    }
    assert forms[("update", None)] == {"tries"}
    assert forms[("reinstall", None)] == {"new_secrets"}
    assert forms[("destroy", None)] == {"all"}
    assert forms[("db", None)] == {"action", "stack", "dump"}
    assert forms[("ssl", "renew")] == set()  # changed by DM-202: status is none
    marks = {b["verb"]: (b["name"], b["destructive_options"]) for b in found}
    assert marks["destroy"] == ("always", {})
    assert marks["db"] == ("when", {"action": ["restore", "reset"]})
    assert marks["seed"] == (
        "when",
        {"reset": [True], "reset_only": [True], "reset_all": [True]},
    )
    assert marks["verb"] == ("ask", {})
    assert marks["update"] == ("never", {})


def test_a_foreign_server_s_card_is_not_found(world: World) -> None:
    target = server(world, "velo-a")
    for path in ("", "/runs", "/verbs"):
        world.call("admin_b", "GET", f"{API}/{target}{path}", expect=404)
        world.call("staff_a", "GET", f"{API}/{target}{path}", expect=200)


def test_the_head_is_the_fleet_s_row(world: World) -> None:
    target = server(world, "velo-a")
    head = world.call("staff_a", "GET", f"{API}/{target}", expect=200)
    fleet = world.call("staff_a", "GET", API, expect=200)
    assert isinstance(fleet, list)
    assert head == fleet[0]


def test_the_runs_last_first_and_one_running(world: World) -> None:
    target = server(world, "velo-a")
    for run_id, started, ended in (
        ("2026-11-24T10:00:00Z-aa01", "2026-11-24T10:00:00Z", "2026-11-24T10:01:00Z"),
        ("2026-11-24T12:00:00Z-aa02", "2026-11-24T12:00:00Z", None),
    ):
        end = "NULL" if ended is None else f"'{ended}'"
        execute(
            world.url,
            "INSERT INTO runs (run_id, server_id, verb, started_at, ended_at) "
            f"VALUES ('{run_id}', '{target}', 'update', '{started}', {end})",
        )
    execute(
        world.url,
        "INSERT INTO verdicts (run_id, server_id, body, envelope_signature, verified, "
        "signed_on_send, report_llm) VALUES ('2026-11-24T10:00:00Z-aa01', "
        f"'{target}', '{{\"result\": \"green\"}}'::jsonb, 's', false, false, '')",
    )
    runs = world.call("staff_a", "GET", f"{API}/{target}/runs", expect=200)
    assert isinstance(runs, list)
    assert [(r["run_id"], r["running"], r["verdict"]) for r in runs] == [
        ("2026-11-24T12:00:00Z-aa02", True, None),
        ("2026-11-24T10:00:00Z-aa01", False, {"result": "green", "verified": False}),
    ]


def test_db_s_form_offers_no_connect(world: World) -> None:
    """``db connect`` writes no verdict (DM-202): the form of the button
    ``db`` does not offer it."""
    target = server(world, "velo-test")
    found = world.call("super", "GET", f"{API}/{target}/verbs", expect=200)
    assert isinstance(found, list)
    (db,) = [b for b in found if b["verb"] == "db"]
    action = db["schema"]["properties"]["action"]
    assert action["enum"] == ["dump", "restore", "reset", "migrate"]


def test_a_non_button_does_not_tell_the_permission(world: World) -> None:
    """What is not a button is refused as that before the permission: 422,
    not 403 (DM-202). The pair: a button without its permission is 403."""
    target = server(world, "velo-test")
    queue(world, target, "logs", {"stack": "velo"}, who="people_a", expect=422)
    queue(world, target, "register", who="staff_a", expect=422)
    queue(world, target, "update", who="people_a", expect=403)
    assert commands(world) == 0


def test_a_file_of_the_box_is_no_field_of_a_button(world: World) -> None:
    """A form hides the box's files; the queue refuses them too (DM-202). The
    pair: a field of the form is queued."""
    target = server(world, "velo-test")
    for field in ("passport", "ops", "server"):
        refused = queue(world, target, "update", {field: "/opt/x.yaml"}, expect=422)
        assert isinstance(refused, dict)
        message = refused["error"]["message"]
        assert message == f"{field} is no field of the button update"
    assert commands(world) == 0
    queue(world, target, "update", {"tries": ["velo=1.2.3"]})
    assert commands(world) == 1


def test_probe_DM_202_not_a_button_is_not_queued(world: World) -> None:
    """What is not a button is neither a button nor a command: the eight of
    the pinned release written out, absent from the superadmin's buttons --
    every permission held -- and refused ``invalid`` before the queue, on
    ``test`` and on ``prod``. The pair: a plain button, a preset one and a
    value of a form are offered and queued."""
    test, prod = server(world, "velo-test"), server(world, "velo-prod", "prod")
    for target in (test, prod):
        assert offered(world, "super", target) & set(NOT_BUTTONS) == set()
    assert {"status", "ssl:renew", "db:dump"} <= offered(world, "super", test)
    for verb, args in NOT_BUTTON_COMMANDS:
        for target, confirmed in ((test, False), (prod, True)):
            refused = queue(world, target, verb, args, confirmed=confirmed, expect=422)
            assert isinstance(refused, dict)
            assert "is no button" in refused["error"]["message"], verb
    assert commands(world) == 0
    buttons: list[tuple[str, dict[str, object]]] = [
        ("status", {}),
        ("ssl", {"action": "renew"}),
        ("db", {"action": "dump", "stack": "velo"}),
    ]
    for verb, given in buttons:
        queue(world, test, verb, given)
    assert commands(world) == 3
