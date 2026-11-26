"""Probes of DM-161: the three ways of a sign-in on a stand-in of comms that
answers the samples of section 16 of comms v4.2.0 (``tests/comms_fake.py``:
the samples word for word, a person's id put in by replacing the text).

Each probe reads back what the Panel took from the sample -- ``Anna``,
``anna``, the bot's access ``true`` -- so a stand-in off the samples, or a
Panel that read another field, is red here.

The SQL of these probes carries the tests' own values only."""
# ruff: noqa: S608

from tests.conftest import SUPERADMIN_ID, query_scalar
from tests.people import World
from tests.signin import SignIn


def _profile(url: str, telegram_id: int) -> object:
    return query_scalar(
        url,
        "SELECT first_name || '/' || username || '/' || bot_access_granted::text "
        f"FROM users WHERE telegram_id = {telegram_id}",
    )


def test_probe_DM_161_superadmin_signs_in_without_invite(
    signin: SignIn, migrated_db: str
) -> None:
    """The superadmin's id signs in with no invite. The pair: another id with
    no invite is a stranger."""
    assert signin.login("super", SUPERADMIN_ID) == {"signed_in": "yes"}
    me = signin.me("super").json()
    assert me["is_superadmin"] is True
    assert me["user"]["telegram_id"] == SUPERADMIN_ID
    assert _profile(migrated_db, SUPERADMIN_ID) == "Anna/anna/true"
    assert signin.login("other", 7000000501) == {
        "reason": "stranger",
        "telegram_id": "7000000501",
    }


def test_probe_DM_161_invited_signs_in_by_the_link(
    world: World, signin: SignIn, migrated_db: str
) -> None:
    """A person invited by a link signs in and holds the invite's
    permissions. The pair: the same id before the invite is a stranger."""
    assert signin.login("before", 7000000502) == {
        "reason": "stranger",
        "telegram_id": "7000000502",
    }
    token = world.invite("admin_a", "a", ["seeds"])
    assert signin.login("invited", 7000000502, invite=token) == {"signed_in": "yes"}
    [access] = signin.me("invited").json()["projects"]
    assert access["permissions"] == ["seeds"]
    assert _profile(migrated_db, 7000000502) == "Anna/anna/true"


def test_probe_DM_161_stranger_refused_with_own_id(
    signin: SignIn, migrated_db: str
) -> None:
    """An id the Panel does not know is refused, with that id on the page;
    no session, no account. The pair: the superadmin on the same sample
    signs in."""
    assert signin.login("stranger", 7000000503) == {
        "reason": "stranger",
        "telegram_id": "7000000503",
    }
    assert signin.token("stranger") is None
    assert signin.me("stranger").status_code == 401
    assert (
        query_scalar(
            migrated_db, "SELECT count(*) FROM users WHERE telegram_id = 7000000503"
        )
        == 0
    )
    assert signin.login("super", SUPERADMIN_ID) == {"signed_in": "yes"}
