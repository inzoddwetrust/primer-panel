"""What the screens of access read besides DM-149 (DM-152): the closed list of
permissions and a member's effective set."""

from tests.people import World

API = "/api/v1"

# The nine of the first version, in the code's order, written out here.
FIRST_VERSION = [
    "deploy_test",
    "deploy_prod",
    "seeds",
    "db",
    "passport",
    "destructive",
    "project_verbs",
    "servers",
    "people",
]


def test_every_person_reads_the_list_of_permissions_in_order(world: World) -> None:
    for who in ("super", "admin_a", "staff_a", "outsider"):
        answer = world.call(who, "GET", f"{API}/permissions", expect=200)
        assert answer == {"permissions": FIRST_VERSION}, who


def test_a_member_s_effective_set_beside_the_stored_one(world: World) -> None:
    members = world.call(
        "admin_a", "GET", f"{API}/projects/{world.projects['a']}/members"
    )
    assert isinstance(members, list)
    rows = {
        member["user"]["telegram_id"]: (member["permissions"], member["effective"])
        for member in members
    }
    admin, staff = world.people["admin_a"], world.people["staff_a"]
    # the admin: people is always his, stored nowhere
    assert rows[admin.telegram_id] == (
        ["deploy_test", "seeds"],
        ["deploy_test", "seeds", "people"],
    )
    # the staff: what is stored is what is held
    assert rows[staff.telegram_id] == (["deploy_test"], ["deploy_test"])
