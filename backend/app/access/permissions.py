"""The closed list of permissions -- one per action of the Panel.

PRIMER-PANEL-TZ-1 section 3: the list lives in the code, who holds what lives
in the database. A permission is a checkbox of a person in a project; a new
one is off for everybody. ``people`` is always on for an admin of the
project (``effective``). The superadmin's mark is no permission: it is
computed -- the person whose Telegram id the Panel's passport names -- and
holds every permission, the future ones too.

A value in the database that this list does not hold refuses the start of
the application (``app.access.startup``); a row read with one fails at the
parse (``parse_permissions``), never passing it by.
"""

from collections.abc import Iterable
from enum import StrEnum


class Permission(StrEnum):
    DEPLOY_TEST = "deploy_test"
    DEPLOY_PROD = "deploy_prod"
    SEEDS = "seeds"
    DB = "db"
    PASSPORT = "passport"
    DESTRUCTIVE = "destructive"
    PROJECT_VERBS = "project_verbs"
    SERVERS = "servers"
    PEOPLE = "people"


class PanelGrantKind(StrEnum):
    """Grants of the Panel's level, given by the superadmin only."""

    SUPPORT = "support"


ALL: frozenset[Permission] = frozenset(Permission)


def canonical(permissions: Iterable[Permission]) -> list[str]:
    """The set in the order of the list: one form for the database and answers."""
    given = set(permissions)
    return [permission.value for permission in Permission if permission in given]


def parse_permissions(values: Iterable[str]) -> frozenset[Permission]:
    """Values of the database as permissions; an unknown one raises with its
    name."""
    out: set[Permission] = set()
    for value in values:
        try:
            out.add(Permission(value))
        except ValueError:
            raise ValueError(f"unknown permission {value!r} in the database") from None
    return frozenset(out)


def effective(
    stored: Iterable[str], *, is_admin: bool, is_superadmin: bool
) -> frozenset[Permission]:
    """What a person may do in a project: everything for the superadmin;
    ``people`` always for an admin; otherwise what is stored."""
    if is_superadmin:
        return ALL
    held = parse_permissions(stored)
    return held | {Permission.PEOPLE} if is_admin else held
