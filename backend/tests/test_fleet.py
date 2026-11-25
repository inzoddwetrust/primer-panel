"""The fleet (DM-154): the servers a person sees, red first, every field from
what the box sent.

Changed by DM-196: the Panel's machine is v0.1.10 -- the versions of the
boxes here (current, behind, newer) follow it.

The SQL of these tests carries the tests' own values only."""
# ruff: noqa: S608

import json
import uuid
from datetime import UTC, datetime, timedelta

from tests.conftest import execute
from tests.people import World

API = "/api/v1/servers"
# The reasons and their seniority, written out (gate DM-154, R3).
SENIORITY = [
    "no-heartbeat",
    "verdict-unverified",
    "verdict-red",
    "service-unhealthy",
    "machine-behind",
    "ssl-due",
]


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot(
    *,
    health: str = "healthy",
    renews_in: timedelta | None = timedelta(days=30),
    expires_in: timedelta = timedelta(days=60),
    mode: str = "letsencrypt",
) -> dict[str, object]:
    now = datetime.now(UTC)
    renews: object = (
        _stamp(now + renews_in)
        if renews_in is not None
        else {"unmeasured": "renewed-by-passport"}
    )
    return {
        "schema": 1,
        "measured_at": _stamp(now),
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
                            {"service": "app", "state": "running", "health": health},
                            {
                                "service": "frontend",
                                "state": "running",
                                "health": "healthy",
                            },
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
        "ssl": {
            "mode": mode,
            "expires": _stamp(now + expires_in),
            "self_signed": False,
            "renews_from": renews,
            "domains": [],
        },
    }


def server(
    world: World,
    name: str,
    project: str = "a",
    *,
    heard: timedelta | None = timedelta(seconds=5),
    version: str = "0.1.10",
    state: dict[str, object] | None = None,
    verdicts: tuple[tuple[str, str, bool], ...] | list[tuple[str, str, bool]] = (),
    detached: bool = False,
) -> uuid.UUID:
    """A registered server; its last heartbeat ``heard`` ago (``None`` -- never),
    the full state ``state`` and verdicts ``(finished, result, verified)``."""
    server_id = uuid.uuid4()
    execute(
        world.url,
        "INSERT INTO servers "
        "(id, project_id, name, role, box_id, box_key_public, detached_at) "
        f"VALUES ('{server_id}', '{world.projects[project]}', '{name}', 'test', "
        f"'{uuid.uuid4()}', 'key', {'now()' if detached else 'NULL'})",
    )
    if heard is not None:
        body = "NULL" if state is None else f"'{json.dumps(state)}'::jsonb"
        execute(
            world.url,
            "INSERT INTO server_states (server_id, last_heartbeat_at, measured_at, "
            "machine_version, protocol_version, lock_open_by, "
            f"journals_without_verdict, snapshot) VALUES ('{server_id}', "
            f"now() - interval '{int(heard.total_seconds())} seconds', "
            f"'2026-11-24T12:00:00Z', '{version}', 1, '[]', '[]', {body})",
        )
    for number, (finished, result, verified) in enumerate(verdicts):
        run_id = f"2026-11-24T12:00:{number:02d}Z-{uuid.uuid4().hex[:4]}"
        verdict = {
            "run_id": run_id,
            "verb": "update",
            "finished": finished,
            "result": result,
        }
        execute(
            world.url,
            f"INSERT INTO runs (run_id, server_id) VALUES ('{run_id}', '{server_id}')",
            "INSERT INTO verdicts (run_id, server_id, body, envelope_signature, "
            f"verified, signed_on_send, report_llm) VALUES ('{run_id}', "
            f"'{server_id}', '{json.dumps(verdict)}'::jsonb, 'sig', "
            f"{str(verified).lower()}, false, '')",
        )
    return server_id


def fleet(world: World, who: str = "super") -> list[dict[str, object]]:
    answer = world.call(who, "GET", API, expect=200)
    assert isinstance(answer, list)
    return answer


def reasons_of(row: dict[str, object]) -> list[str]:
    found = row["reasons"]
    assert isinstance(found, list)
    return [str(reason) for reason in found]


GREEN = [("2026-11-24T11:00:00Z", "green", True)]


def test_probe_DM_154_red_first_for_every_kind(world: World) -> None:
    """A server for every kind of red and one green: the order of the fleet --
    more reasons first, then the most senior one, then the name. The names run
    against the seniority, so the order cannot come from them."""
    behind, due = "0.1.9", snapshot(renews_in=timedelta(days=-1))
    server(world, "a-ssl", state=due, verdicts=GREEN)
    server(world, "b-behind", version=behind, state=snapshot(), verdicts=GREEN)
    server(world, "c-unhealthy", state=snapshot(health="unhealthy"), verdicts=GREEN)
    red = [("2026-11-24T11:00:00Z", "red", True)]
    server(world, "d-red", state=snapshot(), verdicts=red)
    forged = [("2026-11-24T11:00:00Z", "green", False)]
    server(world, "e-unverified", state=snapshot(), verdicts=forged)
    silent = timedelta(seconds=91)
    server(world, "f-silent", heard=silent, state=snapshot(), verdicts=GREEN)
    server(world, "g-never", heard=None, verdicts=GREEN)
    server(world, "0-green", state=snapshot(), verdicts=GREEN)
    server(world, "x-two", version=behind, state=due, verdicts=GREEN)
    server(world, "y-two-senior", heard=silent, version=behind, verdicts=GREEN)
    got = [(row["name"], reasons_of(row)) for row in fleet(world)]
    assert got == [
        ("y-two-senior", ["no-heartbeat", "machine-behind"]),
        ("x-two", ["machine-behind", "ssl-due"]),
        ("f-silent", ["no-heartbeat"]),
        ("g-never", ["no-heartbeat"]),
        ("e-unverified", ["verdict-unverified"]),
        ("d-red", ["verdict-red"]),
        ("c-unhealthy", ["service-unhealthy"]),
        ("b-behind", ["machine-behind"]),
        ("a-ssl", ["ssl-due"]),
        ("0-green", []),
    ]
    # every kind of red is in the closed list, in its seniority
    kinds = sorted(
        {reason for _, found in got for reason in found}, key=SENIORITY.index
    )
    assert kinds == SENIORITY


def test_probe_DM_154_foreign_server_not_in_fleet(world: World) -> None:
    """A server of a project the person is not a member of is not in their
    fleet; their own -- product and service alike -- are."""
    server(world, "velo-a", "a", state=snapshot())
    server(world, "velo-b", "b", state=snapshot())
    server(world, "meet-s", "s", state=snapshot())
    server(world, "gone", "a", detached=True)
    assert {row["name"] for row in fleet(world, "admin_a")} == {"velo-a"}
    assert {row["name"] for row in fleet(world, "admin_s")} == {"meet-s"}
    assert {row["name"] for row in fleet(world, "admin_b")} == {"velo-b"}
    assert fleet(world, "outsider") == []
    assert {row["name"] for row in fleet(world)} == {"velo-a", "velo-b", "meet-s"}


def test_no_data_is_null_never_zero(world: World) -> None:
    server(world, "bare", heard=None)
    [row] = fleet(world)
    for field in (
        "heartbeat_at",
        "machine_version",
        "verdict",
        "stacks",
        "health",
        "ssl",
        "measured_at",
    ):
        assert row[field] is None, field
    assert row["machine_release"] == "0.1.10"
    server(world, "light", state=None)  # a heartbeat, no full form yet
    light = next(r for r in fleet(world) if r["name"] == "light")
    assert light["machine_version"] == "0.1.10" and light["health"] is None


def test_the_facts_of_a_full_form(world: World) -> None:
    server(world, "full", state=snapshot(health="starting"), verdicts=GREEN)
    [row] = fleet(world)
    assert row["stacks"] == [{"stack": "velo", "release": "v1.2.0"}]
    assert row["health"] == {"healthy": 1, "unhealthy": 0, "starting": 1, "none": 0}
    assert row["reasons"] == []  # starting is not unhealthy
    assert isinstance(row["ssl"], dict) and row["ssl"]["mode"] == "letsencrypt"


def test_the_last_verdict_is_the_last_finished(world: World) -> None:
    """History may bring an older verdict after a newer one: the last is by
    ``finished``, not by arrival. ``incomplete`` is not red."""
    server(
        world,
        "late",
        state=snapshot(),
        verdicts=[
            ("2026-11-24T12:00:00Z", "incomplete", True),
            ("2026-11-24T10:00:00Z", "red", True),
        ],
    )
    [row] = fleet(world)
    assert isinstance(row["verdict"], dict)
    assert (row["verdict"]["result"], row["verdict"]["finished"]) == (
        "incomplete",
        "2026-11-24T12:00:00Z",
    )
    assert row["reasons"] == []


def test_versions_are_compared_as_versions(world: World) -> None:
    server(world, "newer", version="0.1.11", state=snapshot())
    server(world, "odd", version="not-a-version", state=snapshot())
    rows = {row["name"]: row["reasons"] for row in fleet(world)}
    assert rows == {"newer": [], "odd": []}


def test_a_certificate_due_by_the_machine_s_moment(world: World) -> None:
    server(
        world,
        "renew-now",
        state=snapshot(renews_in=timedelta(seconds=-5), expires_in=timedelta(days=29)),
    )
    server(
        world,
        "provided-ok",
        state=snapshot(renews_in=None, mode="provided", expires_in=timedelta(days=3)),
    )
    server(
        world,
        "provided-gone",
        state=snapshot(
            renews_in=None, mode="provided", expires_in=timedelta(seconds=-5)
        ),
    )
    rows = {row["name"]: row["reasons"] for row in fleet(world)}
    assert rows == {
        "renew-now": ["ssl-due"],
        "provided-gone": ["ssl-due"],
        "provided-ok": [],
    }


def test_heartbeat_at_the_edge(world: World) -> None:
    server(world, "fresh", heard=timedelta(seconds=85), state=snapshot())
    server(world, "stale", heard=timedelta(seconds=95), state=snapshot())
    rows = {row["name"]: row["reasons"] for row in fleet(world)}
    assert rows == {"stale": ["no-heartbeat"], "fresh": []}


def test_a_full_heartbeat_reaches_the_fleet(world: World) -> None:
    """End to end: the box sends its full state in a heartbeat (contract 4),
    the fleet shows it -- the form the Panel keeps is the form it reads."""
    from tests.test_agent import registered

    box = registered(world, "velo-e2e")
    beat = {
        "measured_at": "2026-11-24T12:00:00Z",
        "machine_version": "0.1.10",
        "lock_open_by": [],
        "journals_without_verdict": [],
        "state": snapshot(health="unhealthy"),
    }
    assert box.send("POST", "/heartbeat", beat).status_code == 204
    [row] = fleet(world)
    assert row["health"] == {"healthy": 1, "unhealthy": 1, "starting": 0, "none": 0}
    assert reasons_of(row) == ["service-unhealthy"]
