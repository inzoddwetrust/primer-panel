"""The permissions in the code: the list, the effective set, the table."""

import pytest

from app.access.actions import ACTION_PERMISSION, Action, permission_for
from app.access.permissions import (
    ALL,
    Permission,
    canonical,
    effective,
    parse_permissions,
)
from app.projects.models import ServerRole

# The nine of the first version (TZ-1 section 3), written out here.
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


def test_the_list_is_the_nine_of_the_first_version() -> None:
    assert [permission.value for permission in Permission] == FIRST_VERSION


def test_the_effective_set() -> None:
    assert effective([], is_admin=False, is_superadmin=True) == ALL
    assert effective(["seeds"], is_admin=True, is_superadmin=False) == {
        Permission.SEEDS,
        Permission.PEOPLE,
    }
    assert effective(["seeds"], is_admin=False, is_superadmin=False) == {
        Permission.SEEDS
    }
    assert effective([], is_admin=False, is_superadmin=False) == frozenset()


def test_an_unknown_value_is_named() -> None:
    with pytest.raises(ValueError, match="retired_one"):
        parse_permissions(["seeds", "retired_one"])


def test_the_canonical_order_is_the_list_s() -> None:
    assert canonical([Permission.PEOPLE, Permission.SEEDS, Permission.PEOPLE]) == [
        "seeds",
        "people",
    ]


@pytest.mark.parametrize(
    ("action", "role", "needed"),
    [
        (Action.UPDATE, ServerRole.TEST, Permission.DEPLOY_TEST),
        (Action.UPDATE, ServerRole.PREVIEW, Permission.DEPLOY_TEST),
        (Action.UPDATE, ServerRole.PROD, Permission.DEPLOY_PROD),
        (Action.DESTROY, ServerRole.PROD, Permission.DESTRUCTIVE),
        (Action.STATUS, ServerRole.PROD, None),
        (Action.PEOPLE_INVITE, ServerRole.TEST, Permission.PEOPLE),
    ],
)
def test_the_permission_of_an_action_on_a_role(
    action: Action, role: ServerRole, needed: Permission | None
) -> None:
    assert permission_for(action, role) is needed


def test_the_tz_table_is_kept() -> None:
    """The rows TZ-1 section 3 names, as it names them."""
    deploy = {"install", "update", "restart", "doctor", "logs"}
    for action in Action:
        if action.value in deploy:
            assert permission_for(action, ServerRole.TEST) is Permission.DEPLOY_TEST
    assert ACTION_PERMISSION[Action.SEED] is Permission.SEEDS
    assert ACTION_PERMISSION[Action.VERB] is Permission.PROJECT_VERBS
    # Changed by DM-153: ``state`` reads (DM-136, the pinned machine).
    assert {a.value for a, p in ACTION_PERMISSION.items() if p is None} == {
        "version",
        "status",
        "state",
        "check",
        "report",
    }
