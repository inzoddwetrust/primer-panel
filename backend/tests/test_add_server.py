"""A new server (DM-157): the token of the screen, what it says, and where a
box it registers lands.

The SQL of these tests carries the tests' own values only."""
# ruff: noqa: S608

import uuid

from tests.conftest import execute, query_scalar
from tests.fake_box import FakeBox
from tests.people import World

API = "/api/v1/projects"
# What a box may hear from `pridem register`, written out.
BOX_REFUSALS = [
    "token-unknown",
    "token-used",
    "token-expired",
    "name-taken",
    "product-mismatch",
    "protocol-too-old",
    "protocol-too-new",
    "register:already",
]


def issue(world: World, project: str = "a", who: str = "super") -> dict[str, object]:
    made = world.call(
        who, "POST", f"{API}/{world.projects[project]}/registration-tokens", expect=201
    )
    assert isinstance(made, dict)
    return made


def state(
    world: World, project: str, token_id: object, who: str = "super", expect: int = 200
) -> object:
    return world.call(
        who,
        "GET",
        f"{API}/{world.projects[project]}/registration-tokens/{token_id}",
        expect=expect,
    )


def test_a_token_comes_with_the_release_and_its_install(world: World) -> None:
    made = issue(world)
    assert made["release"] == "0.1.10"
    assert made["install_url"] == (
        "https://github.com/inzoddwetrust/primer/releases/download/v0.1.10/install.sh"
    )
    assert made["box_refusals"] == BOX_REFUSALS
    assert len(str(made["token"])) >= 16
    rows = query_scalar(
        world.url,
        "SELECT count(*) FROM audit WHERE action = 'registration_token.create'",
    )
    assert rows == 1
    token = str(made["token"])
    assert (
        query_scalar(
            world.url,
            f"SELECT count(*) FROM audit WHERE details::text LIKE '%{token}%'",
        )
        == 0
    )


def test_probe_DM_157_registered_box_is_in_its_project_only(world: World) -> None:
    """A box registered by the token of a project's screen is a server of that
    project and of no other; the token is spent -- once, and in its hour.

    Changed by DM-157 FIX: the token's project was the last created. Two boxes
    now register by the tokens of two projects -- ``b``, in the middle of
    every order of the Panel's projects, and the service project ``s`` -- so
    no rule that sends every box to one project (the first, the last created,
    the least id) can put both where they belong."""
    boxes = {
        "b": ("velo-dev", "git@github.com:o/b.git"),
        "s": ("meet-dev", "git@github.com:o/s.git"),
    }
    tokens: dict[str, dict[str, object]] = {}
    for project, (name, repo) in boxes.items():
        made = issue(world, project)
        tokens[project] = made
        waiting = state(world, project, made["id"])
        assert waiting == {
            "id": made["id"],
            "expires_at": made["expires_at"],
            "used_at": None,
            "server": None,
        }
        box = FakeBox(world.client)
        assert box.register(str(made["token"]), name, repo).status_code == 201
    for project, (name, _) in boxes.items():
        used = state(world, project, tokens[project]["id"])
        assert isinstance(used, dict)
        assert set(used) == {"id", "expires_at", "used_at", "server"}
        assert used["used_at"] is not None
        assert isinstance(used["server"], dict) and used["server"]["name"] == name
        where = query_scalar(
            world.url, f"SELECT project_id FROM servers WHERE name = '{name}'"
        )
        assert where == world.projects[project], (name, project)

    def names(who: str) -> set[str]:
        rows = world.call(who, "GET", "/api/v1/servers", expect=200)
        assert isinstance(rows, list)
        return {str(row["name"]) for row in rows}

    assert names("admin_b") == {"velo-dev"}
    assert names("admin_s") == {"meet-dev"}
    assert names("admin_a") == set()
    again = FakeBox(world.client).register(
        str(tokens["b"]["token"]), "velo-dev-2", "git@github.com:o/b.git"
    )
    assert (again.status_code, again.json()) == (410, {"code": "token-used"})
    late = issue(world, "b")
    execute(
        world.url,
        "UPDATE registration_tokens SET expires_at = now() - interval '1 second' "
        f"WHERE id = '{late['id']}'",
    )
    gone = FakeBox(world.client).register(
        str(late["token"]), "velo-dev-3", "git@github.com:o/b.git"
    )
    assert (gone.status_code, gone.json()) == (410, {"code": "token-expired"})


def test_a_token_s_state_is_its_project_s(world: World) -> None:
    made = issue(world, "a")
    state(world, "b", made["id"], who="super", expect=404)  # another project's path
    state(world, "a", made["id"], who="admin_b", expect=404)
    state(world, "a", uuid.uuid4(), expect=404)
    state(world, "a", made["id"], who="staff_a", expect=403)  # no servers
