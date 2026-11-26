"""Sign-in through comms and the Panel's sessions, on the grid of DM-150."""

import hashlib
import time
from datetime import UTC, datetime

import httpx
import pytest
from redis import Redis as SyncRedis

from app.access.comms import COMPLETE_TIMEOUT_S, START_TIMEOUT_S, LoginStarted
from app.access.login import COMMS_REFUSAL
from app.access.sessions import SESSION_TTL_S
from tests.comms_fake import (
    COMPLETE_NO_BOT_ACCESS,
    COMPLETE_NULLS,
    COMPLETE_OK,
    COMPLETE_WHOLE_SECOND,
    REFUSALS,
    START_OK,
    START_SAMPLE,
    STATE,
    FakeComms,
)
from tests.conftest import (
    API_HOST,
    SUPERADMIN_ID,
    client_for,
    execute,
    query_scalar,
)
from tests.people import World, access_app
from tests.signin import SignIn, client_of, outcome, signin_app

# The classes the two routes answer, written out here: comms v4.2.0, sections
# 5 and 16 -- and not_found, the option login off (section 3a). Changed by
# DM-161: the form of 24.11 had nine; not_found was off the form.
FORM_CLASSES = {
    "validation",
    "login_unknown",
    "login_expired",
    "login_replayed",
    "provider_refused",
    "provider_unavailable",
    "id_token_invalid",
    "unauthorized",
    "unavailable",
    "not_found",
}
EXPECTED = {
    "login_unknown": "restart",
    "login_expired": "restart",
    "login_replayed": "restart",
    "provider_refused": "restart",
    "provider_unavailable": "try_later",
    "unavailable": "try_later",
    "id_token_invalid": "refused",
    "validation": "defect",
    "unauthorized": "defect",
    "not_found": "unavailable",
}


def _cookie_line(response: httpx.Response, name: str) -> str:
    [line] = [
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(f"{name}=")
    ]
    return line


def test_start_asks_comms_as_the_form_says(signin: SignIn) -> None:
    answer = signin.start("b", invite="invite-token-of-the-test")
    assert answer.status_code == 302
    assert answer.headers["location"].startswith("https://oauth.telegram.org/auth?")
    [(path, body)] = signin.fake.calls
    assert path == "/api/v1/login/start"
    assert body == {
        "provider": "telegram",
        "redirect_uri": f"https://{API_HOST}/auth/telegram/return",
        "bot_access": True,
    }
    assert signin.fake.authorization == ["Bearer test-stand-in-comms-service-token"]
    for name in ("panel_login", "panel_invite"):
        line = _cookie_line(answer, name).lower()
        for part in ("httponly", "secure", "samesite=lax", "path=/auth/telegram"):
            assert part in line, (name, part)
        assert "max-age=600" in line  # the attempt's term: section 16's ten minutes
    assert _cookie_line(answer, "panel_login").startswith(f"panel_login={STATE};")


def test_without_an_invite_no_invite_cookie(signin: SignIn) -> None:
    answer = signin.start("b")
    assert [
        c for c in answer.headers.get_list("set-cookie") if c.startswith("panel_invite")
    ] == []


def test_a_session_cookie_and_the_attempt_wiped(signin: SignIn) -> None:
    signin.fake.person(SUPERADMIN_ID)
    signin.start("b")
    answer = signin.back("b")
    assert outcome(answer) == {"signed_in": "yes"}
    line = _cookie_line(answer, "panel_session").lower()
    for part in (
        "httponly",
        "secure",
        "samesite=lax",
        "path=/",
        f"max-age={SESSION_TTL_S}",
    ):
        assert part in line, part
    wiped = [
        c for c in answer.headers.get_list("set-cookie") if c.startswith("panel_login")
    ]
    assert wiped and "max-age=0" in wiped[0].lower()


def test_every_class_of_comms_is_answered_by_the_table() -> None:
    assert set(COMMS_REFUSAL) == FORM_CLASSES
    assert {name: reason.value for name, reason in COMMS_REFUSAL.items()} == EXPECTED


@pytest.mark.parametrize("error_class", sorted(FORM_CLASSES))
def test_a_refusal_of_comms_ends_in_its_answer(
    signin: SignIn, error_class: str
) -> None:
    signin.start("b")
    signin.fake.complete = REFUSALS[error_class]
    assert outcome(signin.back("b")) == {"reason": EXPECTED[error_class]}
    assert signin.token("b") is None


@pytest.mark.parametrize("error_class", ["login_unknown", "unauthorized"])
def test_a_refusal_at_the_start(signin: SignIn, error_class: str) -> None:
    signin.fake.start = REFUSALS[error_class]
    assert outcome(signin.start("b")) == {"reason": EXPECTED[error_class]}


def test_comms_silent_is_try_later(signin: SignIn) -> None:
    assert COMPLETE_TIMEOUT_S >= 25  # section 16's word
    assert START_TIMEOUT_S <= COMPLETE_TIMEOUT_S
    signin.start("b")
    signin.fake.silent = True
    assert outcome(signin.back("b")) == {"reason": "try_later"}


@pytest.mark.parametrize(
    "reply",
    [
        (200, '{"provider":"telegram"}'),
        (
            200,
            COMPLETE_OK.replace('"subject": "123456789"', '"subject": "2"'),
        ),
        (
            200,
            COMPLETE_OK.replace('"provider": "telegram"', '"provider": "x"'),
        ),
        (
            200,
            COMPLETE_OK.replace(
                "2026-12-01T10:03:12.654321+00:00", "2026-12-01T10:03:12.654321"
            ),
        ),
        (200, COMPLETE_OK.replace('"id": 123456789', '"id": "123456789"')),
        (200, COMPLETE_OK.replace('    "last_name": null,\n', "")),
        (200, "not json"),
        (418, '{"error":{"class":"teapot","message":"x"}}'),
        (500, "<html>"),
    ],
    ids=[
        "no-telegram",
        "subject-not-id",
        "provider",
        "naive-time",
        "id-a-string",
        "a-key-absent",
        "not-json",
        "unknown-class",
        "not-the-form",
    ],
)
def test_an_answer_off_the_form_is_a_defect(
    signin: SignIn, reply: tuple[int, str]
) -> None:
    signin.start("b")
    signin.fake.complete = reply
    assert outcome(signin.back("b")) == {"reason": "defect"}


def test_a_start_off_the_form_is_a_defect(signin: SignIn) -> None:
    signin.fake.start = (200, START_OK.replace("https://oauth", "http://oauth"))
    assert outcome(signin.start("b")) == {"reason": "defect"}


def test_times_with_and_without_a_fraction_are_taken(signin: SignIn) -> None:
    """Changed by DM-161: comms v4.2.0 writes +00:00 only, the fraction unless
    it is zero (section 16) -- the samples have one, the edit none."""
    for sample in (COMPLETE_OK, COMPLETE_WHOLE_SECOND):
        signin.fake.person(SUPERADMIN_ID, sample)
        assert signin.start("b").status_code == 302
        assert outcome(signin.back("b")) == {"signed_in": "yes"}
        me = signin.me("b").json()
        assert me["user"]["first_name"] == "Anna"


def test_the_profile_is_kept_at_every_sign_in(signin: SignIn, migrated_db: str) -> None:
    signin.fake.person(SUPERADMIN_ID, COMPLETE_NO_BOT_ACCESS)  # the live 24.11
    signin.start("b")
    signin.back("b")
    assert query_scalar(migrated_db, "SELECT bot_access_granted FROM users") is False
    signin.login("b", SUPERADMIN_ID)  # the sample: bot access true, username anna
    assert query_scalar(migrated_db, "SELECT bot_access_granted FROM users") is True
    assert query_scalar(migrated_db, "SELECT username FROM users") == "anna"
    assert query_scalar(migrated_db, "SELECT count(*) FROM users") == 1


def test_a_second_return_of_one_attempt(signin: SignIn) -> None:
    """Twin REPEAT: the first return wipes the attempt; the second is foreign,
    and comms is not asked again."""
    signin.fake.person(SUPERADMIN_ID)
    signin.start("b")
    signin.back("b")
    assert outcome(signin.back("b")) == {"reason": "foreign_state"}
    assert signin.fake.completes() == 1


def test_comms_not_connected_is_unavailable(migrated_db: str, redis_url: str) -> None:
    fake = FakeComms()
    with client_of(signin_app(migrated_db, redis_url, fake, comms=False)) as client:
        answer = client.get("/auth/telegram/start")
        assert outcome(answer) == {"reason": "unavailable"}
    assert fake.calls == []


def test_a_member_signs_in_without_an_invite(world: World, signin: SignIn) -> None:
    staff = world.people["staff_a"].telegram_id
    assert signin.login("b", staff) == {"signed_in": "yes"}
    assert {p["project"]["slug"] for p in signin.me("b").json()["projects"]} == {"a"}


def test_a_deactivated_person_is_refused_with_the_id(
    world: World, signin: SignIn
) -> None:
    gone = world.people["gone"].telegram_id
    assert signin.login("b", gone) == {
        "reason": "deactivated",
        "telegram_id": str(gone),
    }
    assert signin.token("b") is None


def test_an_invite_that_gives_nothing(world: World, signin: SignIn) -> None:
    assert signin.login("b", 7000000501, invite="no-such-invite") == {
        "reason": "invite_invalid",
        "telegram_id": "7000000501",
    }
    # A member with an invite of a project they are in: signed in, the invite
    # stays unused.
    token = world.invite("admin_a", "a", ["seeds"])
    staff = world.people["staff_a"].telegram_id
    assert signin.login("c", staff, invite=token) == {"signed_in": "yes"}
    invites = world.call(
        "admin_a", "GET", f"/api/v1/projects/{world.projects['a']}/invites"
    )
    assert isinstance(invites, list)
    [row] = [i for i in invites if i["id"] == str(world.invites[token])]
    assert row["used_at"] is None


def test_a_stranger_with_a_bad_invite_leaves_no_account(
    signin: SignIn, migrated_db: str
) -> None:
    signin.login("b", 7000000502, invite="no-such-invite")
    assert (
        query_scalar(
            migrated_db, "SELECT count(*) FROM users WHERE telegram_id = 7000000502"
        )
        == 0
    )


def test_sign_in_and_refusal_are_in_the_audit(signin: SignIn, migrated_db: str) -> None:
    signin.login("b", SUPERADMIN_ID)
    signin.login("c", 7000000503)
    rows = query_scalar(
        migrated_db,
        "SELECT json_agg(json_build_array(action, object_id, details) ORDER BY at) "
        "FROM audit WHERE action LIKE 'login%'",
    )
    assert isinstance(rows, list)
    assert [row[0] for row in rows] == ["login", "login.refused"]
    assert rows[1][1:] == ["7000000503", {"reason": "stranger"}]


def test_sign_out_closes_the_session(signin: SignIn) -> None:
    signin.login("b", SUPERADMIN_ID)
    token = signin.token("b")
    assert token
    answer = signin.request("b", "POST", "/auth/logout")
    assert answer.status_code == 204
    assert "max-age=0" in _cookie_line(answer, "panel_session").lower()
    # the old token, sent again, names no session
    signin.jars["b"].set("panel_session", token, domain=API_HOST)
    assert signin.me("b").status_code == 401
    assert signin.request("b", "POST", "/auth/logout").status_code == 204  # twin REPEAT
    assert signin.request("fresh", "POST", "/auth/logout").status_code == 204


def test_the_term_of_a_session(signin: SignIn, clean_redis: SyncRedis) -> None:
    assert SESSION_TTL_S == 7 * 24 * 3600
    signin.login("b", SUPERADMIN_ID)
    token = signin.token("b")
    assert token
    key = "panel:session:" + hashlib.sha256(token.encode()).hexdigest()
    ttl = clean_redis.ttl(key)
    assert isinstance(ttl, int)
    assert SESSION_TTL_S - 60 < ttl <= SESSION_TTL_S
    clean_redis.pexpire(key, 1)  # the term ends
    time.sleep(0.05)
    assert signin.me("b").status_code == 401


def test_the_token_is_nowhere_in_redis(signin: SignIn, clean_redis: SyncRedis) -> None:
    signin.login("b", SUPERADMIN_ID)
    token = signin.token("b")
    assert token
    keys = [str(key) for key in clean_redis.scan_iter("*")]
    values = [
        str(clean_redis.get(key)) for key in keys if clean_redis.type(key) == "string"
    ]
    assert keys
    assert not [text for text in keys + values if token in text]
    digest = hashlib.sha256(token.encode()).hexdigest()
    assert [key for key in keys if digest in key]  # the pair: its hash is there


def test_a_request_without_a_session_is_unauthorized(signin: SignIn) -> None:
    assert signin.me("nobody").status_code == 401
    signin.jars["forged"] = httpx.Cookies()
    signin.jars["forged"].set("panel_session", "forged-token", domain=API_HOST)
    assert signin.me("forged").status_code == 401


def test_redis_down_closes_the_door(
    migrated_db: str, unreachable_redis_url: str
) -> None:
    fake = FakeComms()
    fake.person(SUPERADMIN_ID)
    with client_of(signin_app(migrated_db, unreachable_redis_url, fake)) as client:
        client.cookies.set("panel_session", "some-token", domain=API_HOST)
        answer = client.get("/api/v1/me")
        assert answer.status_code == 503
        assert answer.json()["error"]["class"] == "unavailable"
        assert client.post("/auth/logout").status_code == 503
        client.cookies.clear()
        client.get("/auth/telegram/start")
        assert outcome(
            client.get("/auth/telegram/return", params={"state": STATE, "code": "c"})
        ) == {"reason": "try_later"}
    assert (
        query_scalar(migrated_db, "SELECT count(*) FROM audit WHERE action = 'login'")
        == 0
    )


def test_deactivating_closes_every_session(
    world: World, signin: SignIn, migrated_db: str
) -> None:
    staff = world.people["staff_a"]
    signin.login("one", staff.telegram_id)
    signin.login("two", staff.telegram_id)
    path = f"/api/v1/users/{staff.id}/deactivate"
    world.call("super", "POST", path, expect=200)
    world.call("super", "POST", path, expect=200)  # twin REPEAT: no second row
    assert (
        query_scalar(
            migrated_db, "SELECT count(*) FROM audit WHERE action = 'user.deactivate'"
        )
        == 1
    )
    for name in ("one", "two"):
        assert signin.me(name).status_code == 401
    assert signin.login("three", staff.telegram_id) == {
        "reason": "deactivated",
        "telegram_id": str(staff.telegram_id),
    }
    super_id = world.people["super"].id
    world.call("super", "POST", f"/api/v1/users/{super_id}/deactivate", expect=409)


def test_revoking_with_redis_down_changes_nothing(
    world: World, migrated_db: str, unreachable_redis_url: str
) -> None:
    staff = world.people["staff_a"].id
    path = f"/api/v1/projects/{world.projects['a']}/members/{staff}/revoke"
    for client in client_for(access_app(migrated_db, unreachable_redis_url)):
        answer = client.post(path, headers=world.people["admin_a"].headers)
        assert answer.status_code == 503
    assert world.permissions_of("a", "staff_a") == ["deploy_test"]
    assert (
        query_scalar(
            migrated_db, "SELECT count(*) FROM audit WHERE action = 'member.revoke'"
        )
        == 0
    )


def test_a_new_superadmin_closes_the_sessions_of_the_previous(
    signin: SignIn, migrated_db: str, redis_url: str
) -> None:
    signin.login("old", SUPERADMIN_ID)
    assert signin.me("old").status_code == 200
    successor = 7000000600
    with client_of(signin_app(migrated_db, redis_url, FakeComms(), successor)):
        pass  # a start of the Panel with another id in the passport
    assert signin.me("old").status_code == 401
    rows = query_scalar(
        migrated_db,
        "SELECT json_agg(details ORDER BY at) FROM audit "
        "WHERE action = 'superadmin.set'",
    )
    assert rows == [
        {"telegram_id": SUPERADMIN_ID, "previous": None},
        {"telegram_id": successor, "previous": SUPERADMIN_ID},
    ]


def test_a_new_superadmin_with_redis_down_is_put_off(
    migrated_db: str, unreachable_redis_url: str, redis_url: str
) -> None:
    with client_of(signin_app(migrated_db, redis_url, FakeComms())):
        pass  # the first superadmin is recorded
    execute(
        migrated_db,
        "INSERT INTO users (id, telegram_id) "  # noqa: S608
        f"VALUES (gen_random_uuid(), {SUPERADMIN_ID})",
    )
    with client_of(
        signin_app(migrated_db, unreachable_redis_url, FakeComms(), 7000000601)
    ):
        pass
    assert (
        query_scalar(
            migrated_db, "SELECT count(*) FROM audit WHERE action = 'superadmin.set'"
        )
        == 1
    )


def test_the_sample_of_start_word_for_word_is_read() -> None:
    """The sample of section 16 as it stands, its 2026 too, is read by the
    client; the flow's ``START_OK`` differs from it by the year alone (the
    cookie's term turns on ``expires_at``). Added by DM-161."""
    started = LoginStarted.model_validate_json(START_SAMPLE)
    assert started.state == STATE
    assert started.expires_at == datetime(2026, 12, 1, 10, 10, 0, 482913, tzinfo=UTC)
    year = "2099-12-01T10:10:00.482913+00:00"
    assert START_SAMPLE.replace("2026-12-01T10:10:00.482913+00:00", year) == START_OK


@pytest.mark.parametrize("route", ["start", "complete"])
def test_comms_login_off_is_unavailable_and_logged(
    signin: SignIn, route: str, caplog: pytest.LogCaptureFixture
) -> None:
    """comms' option login off: both routes are 404 not_found (section 3a).
    The person reads "unavailable", as with comms not connected; the log says
    why. The pair: comms not connected says it under its own event. Added by
    DM-161."""
    caplog.set_level("WARNING", logger="app.access.login")
    if route == "start":
        signin.fake.start = REFUSALS["not_found"]
        answer = signin.start("b")
    else:
        signin.start("b")
        signin.fake.complete = REFUSALS["not_found"]
        answer = signin.back("b")
    assert outcome(answer) == {"reason": "unavailable"}
    events = [getattr(r, "event", "") for r in caplog.records]
    assert events == ["login.comms_login_off"]
    assert signin.token("b") is None


def test_an_unavailable_complete_is_not_repeated(signin: SignIn) -> None:
    """``unavailable`` of ``complete`` leaves unknown whether the attempt was
    taken (section 16); the Panel does not repeat it -- the person begins
    again. Added by DM-161."""
    signin.start("b")
    signin.fake.complete = REFUSALS["unavailable"]
    assert outcome(signin.back("b")) == {"reason": "try_later"}
    assert signin.fake.completes() == 1


def test_a_person_with_every_null_signs_in(signin: SignIn, migrated_db: str) -> None:
    """Names and photo ``null`` (section 16: a value that may be null is
    null, an empty string too): the sign-in goes on, the profile is empty.
    Added by DM-161."""
    signin.fake.person(SUPERADMIN_ID, COMPLETE_NULLS)
    signin.start("b")
    assert outcome(signin.back("b")) == {"signed_in": "yes"}
    assert query_scalar(migrated_db, "SELECT first_name FROM users") is None
    assert query_scalar(migrated_db, "SELECT username FROM users") is None
