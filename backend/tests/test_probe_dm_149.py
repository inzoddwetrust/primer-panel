"""Probes of DM-149: people and access of the Panel (PRIMER-PANEL-TZ-1 s. 3)."""

import uuid
from collections.abc import Iterable
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from pridem.verbs import VERBS

from app.access.actions import ACTION_PERMISSION, MACHINE_VERBS, Action, ByRole
from app.access.actor import current_actor, current_identity
from app.access.login import router as login_router
from app.access.permissions import ALL, Permission
from app.access.router import router
from app.access.rules import AnyActor, Rule
from app.agent.people import router as servers_router
from app.agent.router import router as agent_router
from app.fleet.router import router as fleet_router
from tests.conftest import SUPERADMIN_ID, client_for, query_scalar
from tests.people import World, access_app

API = "/api/v1"

Request = tuple[str, str, object]
"""Method, path, body."""


def _foreign_cases(w: World) -> dict[tuple[str, str], list[Request]]:
    """Every route of the API, and its requests at objects of another project:
    each must be "not found" -- or, for a route with no object of a project,
    the line the table says (``_NO_OBJECT``)."""
    a, b, s = w.projects["a"], w.projects["b"], w.projects["s"]
    staff_b = w.people["staff_b"].id
    invite_b = w.invites["b-pending"]
    member_body: dict[str, list[str]] = {"permissions": []}
    return {
        ("GET", "/projects/{project_id}"): [
            ("GET", f"/projects/{b}", None),
            ("GET", f"/projects/{s}", None),
            ("GET", f"/projects/{uuid.uuid4()}", None),
        ],
        ("POST", "/projects/{project_id}/archive"): [
            ("POST", f"/projects/{b}/archive", None)
        ],
        ("GET", "/projects/{project_id}/members"): [
            ("GET", f"/projects/{b}/members", None),
            ("GET", f"/projects/{s}/members", None),
        ],
        ("POST", "/projects/{project_id}/admins"): [
            (
                "POST",
                f"/projects/{b}/admins",
                {"user_id": str(staff_b), "permissions": []},
            )
        ],
        ("PUT", "/projects/{project_id}/members/{user_id}/permissions"): [
            ("PUT", f"/projects/{b}/members/{staff_b}/permissions", member_body),
            ("PUT", f"/projects/{a}/members/{staff_b}/permissions", member_body),
        ],
        ("POST", "/projects/{project_id}/members/{user_id}/revoke"): [
            ("POST", f"/projects/{b}/members/{staff_b}/revoke", None),
            ("POST", f"/projects/{a}/members/{staff_b}/revoke", None),
        ],
        ("POST", "/projects/{project_id}/invites"): [
            ("POST", f"/projects/{b}/invites", {"permissions": []})
        ],
        ("GET", "/projects/{project_id}/invites"): [
            ("GET", f"/projects/{b}/invites", None)
        ],
        ("POST", "/projects/{project_id}/invites/{invite_id}/revoke"): [
            ("POST", f"/projects/{b}/invites/{invite_b}/revoke", None),
            ("POST", f"/projects/{a}/invites/{invite_b}/revoke", None),
        ],
        ("GET", "/projects/{project_id}/audit"): [
            ("GET", f"/projects/{b}/audit", None)
        ],
        ("POST", "/invites/accept"): [
            ("POST", "/invites/accept", {"token": "not-a-token-of-any-invite"})
        ],
    }


def _no_object_cases(w: World) -> dict[tuple[str, str], tuple[str, str, object, int]]:
    """Routes with no object of a project: what a person of project A meets
    there -- nothing of B in the answer, and the superadmin's routes refused."""
    staff_b = str(w.people["staff_b"].id)
    project = {"slug": "x", "name": "X", "kind": "product", "repo": "r"}
    grant = {"user_id": staff_b, "grant": "support"}
    return {
        ("GET", "/me"): ("GET", "/me", None, 200),
        # Added by DM-152: the closed list of permissions, no object.
        ("GET", "/permissions"): ("GET", "/permissions", None, 200),
        ("GET", "/projects"): ("GET", "/projects", None, 200),
        ("POST", "/projects"): ("POST", "/projects", project, 403),
        ("GET", "/users"): ("GET", "/users", None, 403),
        ("GET", "/panel-grants"): ("GET", "/panel-grants", None, 403),
        ("POST", "/panel-grants"): ("POST", "/panel-grants", grant, 403),
        ("POST", "/panel-grants/{grant_id}/revoke"): (
            "POST",
            f"/panel-grants/{w.grants['admin_b']}/revoke",
            None,
            403,
        ),
        # Added by DM-150: the superadmin's alone, as the grants.
        ("POST", "/users/{user_id}/deactivate"): (
            "POST",
            f"/users/{staff_b}/deactivate",
            None,
            403,
        ),
    }


def _routes() -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for route in router.routes:
        assert isinstance(route, APIRoute)
        for method in route.methods or ():
            out.add((method, route.path.removeprefix(API)))
    return out


def _without_ids(w: World, path: str) -> str:
    """The same path with every id of project B, S and their objects replaced by
    an id of nothing: what an object that does not exist gets."""
    known = [
        w.projects["b"],
        w.projects["s"],
        w.people["staff_b"].id,
        w.invites["b-pending"],
    ]
    for value in known:
        path = path.replace(str(value), str(uuid.uuid4()))
    return path


def test_probe_DM_149_foreign_object_is_not_found_on_every_route(world: World) -> None:
    """A person of project A meets an object of project B (or of the service
    project S) exactly as an object that does not exist: one answer. Who holds
    the action's permission in A -- ``admin_a``, ``people_a`` -- gets
    ``not_found``; who does not -- ``staff_a`` -- the same refusal as for
    nothing at all. Routes with no object of a project show nothing of B.

    Changed by DM-152: the list of permissions is a route with no object.
    """
    cases = _foreign_cases(world)
    no_object = _no_object_cases(world)
    assert set(cases) | set(no_object) == _routes()
    assert not set(cases) & set(no_object)
    not_found = {"error": {"class": "not_found", "message": "Not found"}}
    leaks = [str(world.projects["b"]), str(world.projects["s"]), "staff_b"]
    for who in ("admin_a", "people_a", "staff_a"):
        headers = world.people[who].headers
        for route, requests in cases.items():
            for method, path, body in requests:
                answer = world.client.request(
                    method, API + path, json=body, headers=headers
                )
                nothing = world.client.request(
                    method, API + _without_ids(world, path), json=body, headers=headers
                )
                assert (answer.status_code, answer.json()) == (
                    nothing.status_code,
                    nothing.json(),
                ), (who, route, path)
                if who != "staff_a" or f"/projects/{world.projects['a']}/" not in path:
                    assert answer.json() == not_found, (who, route, path, answer.text)
        for route, (method, path, body, code) in no_object.items():
            answer = world.client.request(
                method, API + path, json=body, headers=headers
            )
            assert answer.status_code == code, (who, route, answer.text)
            for leak in leaks:
                assert leak not in answer.text, (who, route)
    # The pair: the same requests of a person of B find B's objects.
    for method, path, body in cases[("GET", "/projects/{project_id}/members")][:1]:
        answer = world.client.request(
            method, API + path, json=body, headers=world.people["admin_b"].headers
        )
        assert answer.status_code == 200


def _rules(dependant: Dependant) -> list[Rule]:
    found: list[Rule] = []
    for sub in dependant.dependencies:
        if isinstance(sub.call, Rule):
            found.append(sub.call)
        found += _rules(sub)
    return found


def _identity_outside_actor(dependant: Dependant, under_actor: bool = False) -> bool:
    for sub in dependant.dependencies:
        if sub.call is current_identity and not under_actor:
            return True
        if _identity_outside_actor(sub, under_actor or sub.call is current_actor):
            return True
    return False


def _rules_of(routes: Iterable[object]) -> dict[str, int]:
    """The number of access rules of every route, by ``METHOD path``."""
    return {
        f"{method} {route.path}": len(_rules(route.dependant))
        for route in routes
        if isinstance(route, APIRoute)
        for method in sorted(route.methods or ())
    }


def test_probe_DM_149_every_action_has_a_permission() -> None:
    """Changed by DM-153: the rules are walked on the routers of servers and of
    the agent too; the verbs are the pinned machine's (``state`` added).
    Changed by DM-154: and on the fleet's."""
    # The machine's verbs are actions, each with its permission or READ.
    assert {action.value for action in MACHINE_VERBS} == set(VERBS)
    assert set(ACTION_PERMISSION) == set(Action)
    used: set[Permission] = set()
    for needed in ACTION_PERMISSION.values():
        if isinstance(needed, ByRole):
            used |= {needed.test, needed.prod}
        elif needed is not None:
            used.add(needed)
    assert used == ALL

    # Every route of the API has exactly one access rule, and the person comes
    # to it only through current_actor. Changed by DM-150: every router of the
    # application -- the routes of sign-in too.
    # Changed by DM-153: the routers of servers and of the agent too.
    every = [
        *router.routes,
        *login_router.routes,
        *servers_router.routes,
        *agent_router.routes,
        *fleet_router.routes,
    ]
    counted = _rules_of(every)
    assert len(counted) == len(_routes()) + 3 + 3 + 7 + 1
    assert set(counted.values()) == {1}, counted
    for route in every:
        assert isinstance(route, APIRoute)
        assert not _identity_outside_actor(route.dependant), route.path

    # The pair: a route without a rule, or with two, is seen.
    bare = FastAPI()
    one = AnyActor()

    @bare.get("/bare")
    async def bare_route() -> None:
        return None

    @bare.get("/twice")
    async def twice(
        first: Annotated[object, Depends(one)],
        second: Annotated[object, Depends(AnyActor())],
    ) -> None:
        return None

    @bare.get("/sideways")
    async def sideways(
        who: Annotated[object, Depends(current_identity)],
        rule: Annotated[object, Depends(one)],
    ) -> None:
        return None

    assert _rules_of(bare.routes) == {
        "GET /bare": 0,
        "GET /twice": 2,
        "GET /sideways": 1,
    }
    sideways_route = next(
        r for r in bare.routes if isinstance(r, APIRoute) and r.path == "/sideways"
    )
    assert _identity_outside_actor(sideways_route.dependant)


def _superadmin_rows(url: str) -> object:
    return query_scalar(
        url,
        "SELECT json_agg(details ORDER BY at) FROM audit "
        "WHERE action = 'superadmin.set'",
    )


def test_probe_DM_149_superadmin_is_exactly_the_passport_id(
    world: World, migrated_db: str, redis_url: str
) -> None:
    old, new = world.people["super"], world.people["admin_a"]
    b = world.projects["b"]
    for who, mark in (("super", True), ("admin_a", False)):
        me = world.call(who, "GET", "/api/v1/me", expect=200)
        assert isinstance(me, dict)
        assert me["is_superadmin"] is mark
    world.call("admin_a", "GET", f"/api/v1/projects/{b}", expect=404)
    assert _superadmin_rows(migrated_db) == [
        {"telegram_id": SUPERADMIN_ID, "previous": None}
    ]

    # The passport names another id: a new start of the Panel.
    for client in client_for(access_app(migrated_db, redis_url, new.telegram_id)):
        assert client.get("/api/v1/me", headers=new.headers).json()["is_superadmin"]
        assert (
            client.get(f"/api/v1/projects/{b}", headers=new.headers).status_code == 200
        )
        body = {"slug": "n", "name": "N", "kind": "product", "repo": "r"}
        assert (
            client.post("/api/v1/projects", json=body, headers=new.headers).status_code
            == 201
        )
        gone = client.get("/api/v1/me", headers=old.headers).json()
        assert gone["is_superadmin"] is False
        assert (
            client.get(f"/api/v1/projects/{b}", headers=old.headers).status_code == 404
        )
        body = {"slug": "m", "name": "M", "kind": "product", "repo": "r"}
        assert (
            client.post("/api/v1/projects", json=body, headers=old.headers).status_code
            == 403
        )
    assert _superadmin_rows(migrated_db) == [
        {"telegram_id": SUPERADMIN_ID, "previous": None},
        {"telegram_id": new.telegram_id, "previous": SUPERADMIN_ID},
    ]
    # Twin REPEAT: the same id at the next start adds no row.
    for _client in client_for(access_app(migrated_db, redis_url, new.telegram_id)):
        pass
    rows = _superadmin_rows(migrated_db)
    assert isinstance(rows, list)
    assert len(rows) == 2


def test_probe_DM_149_admin_grants_only_own_and_revoked_leaves_staff(
    world: World, migrated_db: str
) -> None:
    a, b = world.projects["a"], world.projects["b"]
    staff_a, people_a = world.people["staff_a"].id, world.people["people_a"].id

    def put(who: str, user: uuid.UUID, held: list[str], code: int) -> None:
        path = f"/api/v1/projects/{a}/members/{user}/permissions"
        world.call(who, "PUT", path, {"permissions": held}, expect=code)

    # admin_a holds deploy_test, seeds (and people): deploy_prod is not his.
    put("admin_a", staff_a, ["deploy_test", "deploy_prod"], 403)
    world.call(
        "admin_a",
        "POST",
        f"/api/v1/projects/{a}/invites",
        {"permissions": ["deploy_prod"]},
        expect=403,
    )
    put("admin_a", staff_a, ["deploy_test", "seeds"], 200)  # the pair: his own
    put("people_a", staff_a, ["deploy_test", "seeds", "db"], 403)
    assert world.permissions_of("a", "staff_a") == ["deploy_test", "seeds"]
    pending = world.invite("admin_a", "a", ["seeds", "deploy_test"])

    # The superadmin takes seeds from the admin: from his staff and invites too.
    admin = world.people["admin_a"].id
    put("super", admin, ["deploy_test"], 200)
    assert world.permissions_of("a", "admin_a") == ["deploy_test"]
    assert world.permissions_of("a", "staff_a") == ["deploy_test"]
    invite_row = query_scalar(
        migrated_db,
        f"SELECT permissions FROM invites WHERE id = '{world.invites[pending]}'",  # noqa: S608
    )
    assert invite_row == ["deploy_test"]
    cascaded = query_scalar(
        migrated_db,
        "SELECT count(*) FROM audit WHERE details->>'from_admin' = "  # noqa: S608
        f"'{admin}' AND details->'removed' = '[\"seeds\"]'::jsonb",
    )
    assert cascaded == 2  # staff_a and the invite; people_a held no seeds
    assert world.permissions_of("a", "people_a") == ["people"]
    assert people_a
    assert world.permissions_of("b", "staff_b") == ["seeds"]  # B is untouched
    assert b
