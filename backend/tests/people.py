"""Support of the access tests: a stand-in for the sign-in and a small world.

Until DM-150 ``current_identity`` refuses everybody. The tests put
``identity_from_header`` in its place: the Telegram id of the person comes in
the test header ``X-As``; without it -- the real refusal (401). Nothing of
this is in the application: the header exists only here.

``World`` is built through the API as its people would build it: the
superadmin makes projects and appoints admins, admins invite their staff, the
staff accept. Accounts are rows written directly (they are made at the first
sign-in, DM-150).
"""

import uuid
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.testclient import TestClient
from starlette.types import ASGIApp

from app.access.actor import Identity, current_identity
from app.main import create_app
from tests.conftest import SUPERADMIN_ID, execute, settings_for
from tests.failing import inner_app

AS = "X-As"


async def identity_from_header(request: Request) -> Identity:
    """The person of the header ``X-As``; none -- the real refusal."""
    value = request.headers.get(AS)
    if value is None:
        return await current_identity()
    return Identity(telegram_id=int(value))


def access_app(
    database_url: str, redis_url: str, superadmin: int = SUPERADMIN_ID
) -> ASGIApp:
    """The Panel with the stand-in sign-in."""
    served = create_app(settings_for(database_url, redis_url, superadmin))
    inner_app(served).dependency_overrides[current_identity] = identity_from_header
    return served


def add_user(url: str, telegram_id: int, *, deactivated: bool = False) -> uuid.UUID:
    """An account, as the first sign-in will make it."""
    user_id = uuid.uuid4()
    at = "now()" if deactivated else "NULL"
    # The values are the test's own: a UUID, an integer, a keyword.
    execute(
        url,
        "INSERT INTO users (id, telegram_id, first_name, deactivated_at) "  # noqa: S608
        f"VALUES ('{user_id}', {telegram_id}, 'Person {telegram_id}', {at})",
    )
    return user_id


def as_(telegram_id: int) -> dict[str, str]:
    return {AS: str(telegram_id)}


@dataclass
class Person:
    telegram_id: int
    id: uuid.UUID

    @property
    def headers(self) -> dict[str, str]:
        return as_(self.telegram_id)


@dataclass
class World:
    client: TestClient
    url: str
    people: dict[str, Person] = field(default_factory=dict)
    projects: dict[str, uuid.UUID] = field(default_factory=dict)
    invites: dict[str, uuid.UUID] = field(default_factory=dict)
    grants: dict[str, uuid.UUID] = field(default_factory=dict)

    def person(
        self, name: str, telegram_id: int, *, deactivated: bool = False
    ) -> Person:
        user = Person(
            telegram_id, add_user(self.url, telegram_id, deactivated=deactivated)
        )
        self.people[name] = user
        return user

    def call(
        self,
        who: str,
        method: str,
        path: str,
        body: object = None,
        expect: int | None = None,
    ) -> object:
        response = self.client.request(
            method, path, json=body, headers=self.people[who].headers
        )
        if expect is not None:
            assert response.status_code == expect, (method, path, response.text)
        result: object = response.json() if response.content else None
        return result

    def project(self, name: str, kind: str = "product") -> uuid.UUID:
        body = {
            "slug": name,
            "name": name.upper(),
            "kind": kind,
            "repo": f"git@github.com:o/{name}.git",
        }
        made = self.call("super", "POST", "/api/v1/projects", body, expect=201)
        assert isinstance(made, dict)
        self.projects[name] = uuid.UUID(made["id"])
        return self.projects[name]

    def admin(self, project: str, who: str, permissions: list[str]) -> None:
        body = {"user_id": str(self.people[who].id), "permissions": permissions}
        path = f"/api/v1/projects/{self.projects[project]}/admins"
        self.call("super", "POST", path, body, expect=201)

    def invite(
        self, by: str, project: str, permissions: list[str], *, is_admin: bool = False
    ) -> str:
        body = {"permissions": permissions, "is_admin": is_admin}
        path = f"/api/v1/projects/{self.projects[project]}/invites"
        made = self.call(by, "POST", path, body, expect=201)
        assert isinstance(made, dict)
        self.invites[made["token"]] = uuid.UUID(made["invite"]["id"])
        token: str = made["token"]
        return token

    def join(self, who: str, token: str) -> None:
        self.call(who, "POST", "/api/v1/invites/accept", {"token": token}, expect=201)

    def staff(self, by: str, project: str, who: str, permissions: list[str]) -> None:
        self.join(who, self.invite(by, project, permissions))

    def permissions_of(self, project: str, who: str) -> list[str]:
        members = self.call(
            "super", "GET", f"/api/v1/projects/{self.projects[project]}/members"
        )
        assert isinstance(members, list)
        for member in members:
            if member["user"]["id"] == str(self.people[who].id):
                held: list[str] = member["permissions"]
                return held
        raise AssertionError(f"{who} is no member of {project}")


def build_world(access_client: TestClient, migrated_db: str) -> World:
    """Two product projects A and B, a service project S, an archived Z.

    - ``admin_a`` -- admin of A with ``deploy_test`` and ``seeds``;
      ``staff_a`` -- staff of A with ``deploy_test``; ``people_a`` -- staff of
      A with ``people``; ``outsider`` -- an account without any project;
    - ``admin_b`` -- admin of B, ``staff_b`` -- staff of B with ``seeds``, an
      unused invite of B, a Panel grant ``support`` of ``admin_b``;
    - ``admin_s`` -- admin of the service project S;
    - ``admin_a`` is admin of the archived Z as well;
    - ``gone`` -- a deactivated account.
    """
    w = World(access_client, migrated_db)
    w.person("super", SUPERADMIN_ID)
    for number, name in enumerate(
        ["admin_a", "staff_a", "people_a", "outsider", "admin_b", "staff_b", "admin_s"],
        start=11,
    ):
        w.person(name, 7000000000 + number)
    w.person("gone", 7000000099, deactivated=True)
    for name in ("a", "b", "z"):
        w.project(name)
    w.project("s", kind="service")
    w.admin("a", "admin_a", ["deploy_test", "seeds"])
    w.admin("z", "admin_a", ["deploy_test"])
    w.admin("b", "admin_b", ["seeds", "db"])
    w.admin("s", "admin_s", ["servers"])
    w.staff("admin_a", "a", "staff_a", ["deploy_test"])
    w.staff("admin_a", "a", "people_a", ["people"])
    w.staff("admin_b", "b", "staff_b", ["seeds"])
    w.invites["b-pending"] = w.invites[w.invite("admin_b", "b", ["seeds"])]
    made = w.call(
        "super",
        "POST",
        "/api/v1/panel-grants",
        {"user_id": str(w.people["admin_b"].id), "grant": "support"},
        expect=201,
    )
    assert isinstance(made, dict)
    w.grants["admin_b"] = uuid.UUID(made["id"])
    w.call("super", "POST", f"/api/v1/projects/{w.projects['z']}/archive", expect=200)
    return w
