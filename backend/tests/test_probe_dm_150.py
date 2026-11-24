"""Probes of DM-150: sign-in through comms and the Panel's sessions."""

from tests.comms_fake import STATE
from tests.conftest import SUPERADMIN_ID
from tests.people import World
from tests.signin import SignIn, outcome

OTHER_STATE = "Zq4lR0yXw3nO9sU6tM2dB8eG5hJ7kL1aC4oN6qS9vV2"  # the same length


def test_probe_DM_150_foreign_state_is_refused_without_calling_comms(
    signin: SignIn,
) -> None:
    """The binding of the attempt to the browser is the Panel's: a ``state``
    that is not its cookie's, or no cookie, ends at the Panel -- comms'
    ``complete`` is never called."""
    signin.fake.person(7000000401)
    assert signin.start("own").status_code == 302
    cases = {
        "another state": signin.back("own", state=OTHER_STATE),
        "no cookie": signin.back("stranger_browser"),
        "empty state": signin.back("own", state=""),
        "empty code": signin.back("own", code=""),
    }
    for case, answer in cases.items():
        assert outcome(answer) == {"reason": "foreign_state"}, case
        assert signin.token("own") is None, case
    assert signin.fake.completes() == 0
    # The pair: the browser's own state -- comms is asked, once.
    assert signin.start("own").status_code == 302
    signin.back("own", state=STATE)
    assert signin.fake.completes() == 1


def test_probe_DM_150_revoking_access_closes_every_session(
    world: World, signin: SignIn
) -> None:
    """Two sessions of one person, a revoke -- both closed at once; the
    session of another person of the project stays."""
    token = world.invite("admin_a", "a", ["deploy_test"])
    assert signin.login("phone", 7000000402, invite=token) == {"signed_in": "yes"}
    assert signin.login("laptop", 7000000402) == {"signed_in": "yes"}
    assert signin.login("other", world.people["staff_a"].telegram_id) == {
        "signed_in": "yes"
    }
    for name in ("phone", "laptop", "other"):
        assert signin.me(name).status_code == 200, name
    person = signin.user_id("phone")
    world.call(
        "admin_a",
        "POST",
        f"/api/v1/projects/{world.projects['a']}/members/{person}/revoke",
        expect=200,
    )
    for name in ("phone", "laptop"):
        answer = signin.me(name)
        assert answer.status_code == 401, name
        assert answer.json()["error"]["class"] == "unauthorized"
    assert signin.me("other").status_code == 200  # the pair: another stays


def test_probe_DM_150_stranger_refused_with_own_id_superadmin_without_invite(
    world: World, signin: SignIn
) -> None:
    """A stranger is refused and sees their own Telegram id; the superadmin
    signs in with no invite; an invited person signs in by the invite."""
    assert signin.login("stranger", 7000000403) == {
        "reason": "stranger",
        "telegram_id": "7000000403",
    }
    assert signin.token("stranger") is None
    assert signin.me("stranger").status_code == 401

    assert signin.login("super", SUPERADMIN_ID) == {"signed_in": "yes"}
    me = signin.me("super").json()
    assert me["is_superadmin"] is True
    assert me["user"]["telegram_id"] == SUPERADMIN_ID

    token = world.invite("admin_a", "a", ["seeds"])
    assert signin.login("invited", 7000000404, invite=token) == {"signed_in": "yes"}
    [access] = signin.me("invited").json()["projects"]
    assert access["permissions"] == ["seeds"]
