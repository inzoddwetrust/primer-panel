"""The access API on its grid: who acts, which project, which object."""

import pytest
from fastapi.testclient import TestClient

from app.access import service
from app.audit.service import record
from tests.conftest import execute, query_scalar
from tests.people import World, as_

API = "/api/v1"


def _audit_count(url: str, action: str) -> object:
    return query_scalar(
        url,
        f"SELECT count(*) FROM audit WHERE action = '{action}'",  # noqa: S608
    )


def _member_path(world: World, project: str, who: str, tail: str) -> str:
    user = world.people[who].id
    return f"{API}/projects/{world.projects[project]}/members/{user}/{tail}"


def test_nobody_signed_in_is_unauthorized_everywhere(world: World) -> None:
    """Until DM-150 there is no sign-in: every route answers 401."""
    a = world.projects["a"]
    for method, path in [
        ("GET", "/me"),
        ("GET", "/projects"),
        ("GET", f"/projects/{a}"),
        ("POST", f"/projects/{a}/invites"),
        ("POST", "/invites/accept"),
        ("GET", "/users"),
    ]:
        answer = world.client.request(method, API + path, json={})
        assert answer.status_code == 401, path
        assert answer.json()["error"]["class"] == "unauthorized"


def test_an_account_deactivated_or_unknown_is_forbidden(world: World) -> None:
    a = world.projects["a"]
    for headers in (world.people["gone"].headers, as_(7000000555)):
        for path in ("/me", f"/projects/{a}"):
            answer = world.client.get(API + path, headers=headers)
            assert answer.status_code == 403, path
    outsider = world.people["outsider"].headers
    assert world.client.get(API + "/me", headers=outsider).status_code == 200


def test_the_description_of_the_api_is_not_served(access_client: TestClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        answer = access_client.get(path)
        assert answer.status_code == 404, path
        assert answer.json()["error"]["class"] == "not_found"


def test_the_superadmin_sees_every_project_a_person_only_his(world: World) -> None:
    every = world.call("super", "GET", API + "/projects", expect=200)
    assert isinstance(every, list)
    assert {p["slug"] for p in every} == {"a", "b", "s", "z"}
    own = world.call("admin_a", "GET", API + "/projects", expect=200)
    assert isinstance(own, list)
    assert {p["slug"] for p in own} == {"a", "z"}
    assert world.call("outsider", "GET", API + "/projects", expect=200) == []


def test_a_service_project_is_its_people_s_alone(world: World) -> None:
    s = world.projects["s"]
    world.call("admin_a", "GET", f"{API}/projects/{s}", expect=404)
    world.call("admin_b", "GET", f"{API}/projects/{s}", expect=404)
    world.call("admin_s", "GET", f"{API}/projects/{s}", expect=200)
    world.call("super", "GET", f"{API}/projects/{s}", expect=200)


def test_an_archived_project_is_read_not_written(world: World) -> None:
    z = world.projects["z"]
    world.call("admin_a", "GET", f"{API}/projects/{z}", expect=200)
    path = f"{API}/projects/{z}/invites"
    world.call("admin_a", "POST", path, {"permissions": []}, expect=409)
    body = {"user_id": str(world.people["outsider"].id), "permissions": []}
    world.call("super", "POST", f"{API}/projects/{z}/admins", body, expect=409)


def test_an_invite_to_a_project_archived_since_is_refused(world: World) -> None:
    token = world.invite("admin_a", "a", ["deploy_test"])
    world.call(
        "super", "POST", f"{API}/projects/{world.projects['a']}/archive", expect=200
    )
    body = {"token": token}
    world.call("outsider", "POST", API + "/invites/accept", body, expect=409)


def test_only_the_superadmin_makes_projects_and_admins(world: World) -> None:
    body = {"slug": "n", "name": "N", "kind": "service", "repo": "git@h:o/n.git"}
    world.call("admin_a", "POST", API + "/projects", body, expect=403)
    world.call("super", "POST", API + "/projects", body, expect=201)
    world.call("super", "POST", API + "/projects", body, expect=409)  # slug taken
    path = f"{API}/projects/{world.projects['a']}/admins"
    appoint = {"user_id": str(world.people["outsider"].id), "permissions": ["db"]}
    world.call("admin_a", "POST", path, appoint, expect=403)
    world.call("super", "POST", path, appoint, expect=201)
    world.call("super", "POST", path, appoint, expect=409)
    gone = {"user_id": str(world.people["gone"].id), "permissions": []}
    world.call("super", "POST", path, gone, expect=404)


@pytest.mark.parametrize(
    "body",
    [
        {
            "permissions": ["deploy_test"],
            "server_id": "00000000-0000-0000-0000-000000000001",
        },
        {"permissions": ["ops"]},
        {"permissions": ["seeds", "seeds"]},
        {"permissions": ["seeds"], "ttl_hours": 0},
        {"permissions": ["seeds"], "ttl_hours": 721},
    ],
    ids=["server-id", "unknown", "twice", "ttl-zero", "ttl-over"],
)
def test_a_body_off_the_list_is_invalid(world: World, body: dict[str, object]) -> None:
    path = f"{API}/projects/{world.projects['a']}/invites"
    answer = world.call("admin_a", "POST", path, body, expect=422)
    assert isinstance(answer, dict)
    assert answer["error"]["class"] == "invalid"


def test_an_admin_never_changes_an_admin(world: World) -> None:
    body = {"permissions": ["deploy_test"]}
    path = _member_path(world, "a", "admin_a", "permissions")
    world.call("people_a", "PUT", path, body, expect=403)
    world.call("admin_a", "PUT", path, body, expect=403)
    world.call(
        "admin_a", "POST", _member_path(world, "a", "admin_a", "revoke"), expect=403
    )


def test_staff_without_people_manages_nobody(world: World) -> None:
    a = world.projects["a"]
    world.call(
        "staff_a",
        "POST",
        f"{API}/projects/{a}/invites",
        {"permissions": []},
        expect=403,
    )
    world.call(
        "staff_a", "POST", _member_path(world, "a", "people_a", "revoke"), expect=403
    )
    world.call("staff_a", "GET", f"{API}/projects/{a}/members", expect=200)
    world.call("staff_a", "GET", f"{API}/projects/{a}/audit", expect=200)
    world.call("staff_a", "GET", f"{API}/projects/{a}/invites", expect=403)


def test_an_invite_is_used_once(world: World, migrated_db: str) -> None:
    token = world.invite("people_a", "a", ["people"])
    world.join("outsider", token)
    assert world.permissions_of("a", "outsider") == ["people"]
    # Twin REPEAT: the same token again, by anybody -- nothing.
    body = {"token": token}
    world.call("staff_b", "POST", API + "/invites/accept", body, expect=404)
    world.call("outsider", "POST", API + "/invites/accept", body, expect=404)
    assert _audit_count(migrated_db, "invite.accept") == 4  # 3 of the world, 1 here


def test_an_invite_out_of_time_or_revoked_is_not_found(
    world: World, migrated_db: str
) -> None:
    late = world.invite("admin_a", "a", ["seeds"])
    execute(
        migrated_db,
        "UPDATE invites SET expires_at = now() - interval '1 second' "  # noqa: S608
        f"WHERE id = '{world.invites[late]}'",
    )
    world.call("outsider", "POST", API + "/invites/accept", {"token": late}, expect=404)
    revoked = world.invite("admin_a", "a", ["seeds"])
    a = world.projects["a"]
    path = f"{API}/projects/{a}/invites/{world.invites[revoked]}/revoke"
    world.call("admin_a", "POST", path, expect=200)
    world.call("admin_a", "POST", path, expect=200)  # twin REPEAT: no second row
    assert _audit_count(migrated_db, "invite.revoke") == 1
    body = {"token": revoked}
    world.call("outsider", "POST", API + "/invites/accept", body, expect=404)
    world.call("outsider", "POST", API + "/invites/accept", {"token": ""}, expect=422)
    assert world.call("outsider", "GET", API + "/projects") == []


def test_a_used_invite_is_not_revoked(world: World) -> None:
    token = world.invite("admin_a", "a", [])
    world.join("outsider", token)
    a = world.projects["a"]
    path = f"{API}/projects/{a}/invites/{world.invites[token]}/revoke"
    world.call("admin_a", "POST", path, expect=409)


def test_an_invite_making_an_admin_is_the_superadmin_s(world: World) -> None:
    a = world.projects["a"]
    body = {"permissions": [], "is_admin": True}
    world.call("admin_a", "POST", f"{API}/projects/{a}/invites", body, expect=403)
    world.call("people_a", "POST", f"{API}/projects/{a}/invites", body, expect=403)
    token = world.invite("super", "a", ["db"], is_admin=True)
    world.join("outsider", token)
    me = world.call("outsider", "GET", API + "/me", expect=200)
    assert isinstance(me, dict)
    [access] = me["projects"]
    assert access["is_admin"] is True
    assert access["permissions"] == ["db", "people"]  # people: always the admin's


def test_a_member_accepting_another_invite_keeps_it_unused(world: World) -> None:
    token = world.invite("admin_a", "a", ["seeds"])
    body = {"token": token}
    world.call("staff_a", "POST", API + "/invites/accept", body, expect=409)
    a = world.projects["a"]
    invites = world.call("admin_a", "GET", f"{API}/projects/{a}/invites")
    assert isinstance(invites, list)
    [row] = [i for i in invites if i["id"] == str(world.invites[token])]
    assert row["used_at"] is None


def test_the_token_is_kept_only_as_its_hash(world: World, migrated_db: str) -> None:
    token = world.invite("admin_a", "a", ["seeds"])
    tables = query_scalar(
        migrated_db,
        "SELECT string_agg(tablename, ',') FROM pg_tables WHERE schemaname = 'public'",
    )
    assert isinstance(tables, str)

    def holding(value: str) -> list[str]:
        return [
            table
            for table in sorted(tables.split(","))
            if query_scalar(
                migrated_db,
                f"SELECT count(*) FROM {table} t WHERE t::text LIKE '%{value}%'",  # noqa: S608
            )
        ]

    assert holding(token) == []
    assert holding(service.token_hash(token)) == ["invites"]  # the pair: it is found
    a = world.projects["a"]
    listed = world.call("admin_a", "GET", f"{API}/projects/{a}/invites")
    assert token not in str(listed)


def test_revoking_an_admin_takes_his_permissions_from_the_staff(world: World) -> None:
    """Gate R7 (b): the whole of the admin's set, ``people`` too."""
    world.call(
        "super", "POST", _member_path(world, "a", "admin_a", "revoke"), expect=200
    )
    assert world.permissions_of("a", "staff_a") == []
    assert world.permissions_of("a", "people_a") == []
    world.call("admin_a", "GET", f"{API}/projects/{world.projects['a']}", expect=404)


def test_two_admins_lose_a_permission_together_at_the_staff(world: World) -> None:
    """Gate R7 (a): taken from one admin, taken from all the staff, though the
    second admin still holds it."""
    world.admin("a", "outsider", ["deploy_test"])
    path = _member_path(world, "a", "admin_a", "permissions")
    world.call("super", "PUT", path, {"permissions": ["seeds"]}, expect=200)
    assert world.permissions_of("a", "outsider") == ["deploy_test"]
    assert world.permissions_of("a", "staff_a") == []


def test_an_admin_invite_keeps_its_permissions(world: World, migrated_db: str) -> None:
    """Gate R7 (c): the cascade takes from invites making staff only."""
    admin_invite = world.invite("super", "a", ["seeds"], is_admin=True)
    path = _member_path(world, "a", "admin_a", "permissions")
    world.call("super", "PUT", path, {"permissions": ["deploy_test"]}, expect=200)
    held = query_scalar(
        migrated_db,
        f"SELECT permissions FROM invites WHERE id = '{world.invites[admin_invite]}'",  # noqa: S608
    )
    assert held == ["seeds"]


def test_a_cascade_failing_in_the_middle_changes_nothing(
    world: World, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gate R7: one transaction -- the third row of the audit fails, and the
    admin, the staff and the audit stay as they were."""
    people = _member_path(world, "a", "people_a", "permissions")
    world.call(
        "admin_a", "PUT", people, {"permissions": ["seeds", "people"]}, expect=200
    )
    before = query_scalar(migrated_db, "SELECT count(*) FROM audit")
    calls: list[object] = []

    def failing(*args: object, **kwargs: object) -> None:
        calls.append(kwargs.get("action"))
        if len(calls) == 3:
            raise RuntimeError("the audit fails in the middle of the cascade")
        record(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service, "record", failing)
    path = _member_path(world, "a", "admin_a", "permissions")
    answer = world.client.put(
        path, json={"permissions": []}, headers=world.people["super"].headers
    )
    assert answer.status_code == 500
    assert calls == ["member.permissions", "member.permissions", "member.permissions"]
    assert world.permissions_of("a", "admin_a") == ["deploy_test", "seeds"]
    assert world.permissions_of("a", "staff_a") == ["deploy_test"]
    assert world.permissions_of("a", "people_a") == ["seeds", "people"]
    assert query_scalar(migrated_db, "SELECT count(*) FROM audit") == before


def test_the_same_set_again_writes_nothing(world: World, migrated_db: str) -> None:
    path = _member_path(world, "a", "staff_a", "permissions")
    before = _audit_count(migrated_db, "member.permissions")
    world.call("admin_a", "PUT", path, {"permissions": ["deploy_test"]}, expect=200)
    assert _audit_count(migrated_db, "member.permissions") == before


def test_staff_with_people_revokes_staff(world: World) -> None:
    path = _member_path(world, "a", "staff_a", "revoke")
    world.call("people_a", "POST", path, expect=200)
    world.call("staff_a", "GET", f"{API}/projects/{world.projects['a']}", expect=404)
    world.call("people_a", "POST", path, expect=404)  # twin REPEAT: no member now


def test_panel_grants_are_the_superadmin_s(world: World, migrated_db: str) -> None:
    body = {"user_id": str(world.people["admin_b"].id), "grant": "support"}
    world.call("super", "POST", API + "/panel-grants", body, expect=409)
    world.call("admin_b", "POST", API + "/panel-grants", body, expect=403)
    world.call("admin_b", "GET", API + "/panel-grants", expect=403)
    world.call("super", "GET", API + "/users", expect=200)
    path = f"{API}/panel-grants/{world.grants['admin_b']}/revoke"
    world.call("super", "POST", path, expect=200)
    world.call("super", "POST", path, expect=200)
    assert _audit_count(migrated_db, "panel_grant.revoke") == 1
    me = world.call("admin_b", "GET", API + "/me")
    assert isinstance(me, dict)
    assert me["panel_grants"] == []
    body = {"user_id": str(world.people["admin_b"].id), "grant": "everything"}
    world.call("super", "POST", API + "/panel-grants", body, expect=422)


def test_the_audit_names_every_change_of_access(world: World) -> None:
    rows = world.call("admin_a", "GET", f"{API}/projects/{world.projects['a']}/audit")
    assert isinstance(rows, list)
    assert [row["action"] for row in rows] == [
        "project.create",
        "member.admin",
        "invite.create",
        "invite.accept",
        "invite.create",
        "invite.accept",
    ]
    assert {row["actor_kind"] for row in rows} == {"user"}
