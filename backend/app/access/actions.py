"""Every action of the Panel and the permission it needs (TZ-1 section 3).

One permission per action, in one table. An action is a verb of the deploy
machine -- the Panel runs them on servers through its queue -- or an action
of the Panel itself. ``READ`` actions are open to every member of the
project. The verbs are the machine's registry ``pridem.verbs.VERBS`` of the
release the Panel drives (pinned in CI); a test holds the two equal, so a
verb a new machine adds turns it red until the table names its permission.

The deploy verbs need ``deploy_test`` on a server of role ``test`` or
``preview`` and ``deploy_prod`` on ``prod`` (``ByRole``). The confirmation of
a destructive action stays whatever the permissions (TZ-1 section 3, rule 4).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from app.access.permissions import Permission
from app.projects.models import ServerRole


class Action(StrEnum):
    # Verbs of the deploy machine at the pinned commit (pridem.verbs.VERBS);
    # ``state`` came with DM-136 (changed by DM-153).
    VERSION = "version"
    STATUS = "status"
    STATE = "state"
    CHECK = "check"
    REPORT = "report"
    INSTALL = "install"
    UPDATE = "update"
    DEPLOY = "deploy"
    ROLLBACK = "rollback"
    DOCTOR = "doctor"
    RESTART = "restart"
    START = "start"
    STOP = "stop"
    LOGS = "logs"
    GC = "gc"
    REGISTER = "register"
    SSL = "ssl"
    SEED = "seed"
    DB = "db"
    BACKUP = "backup"
    REINSTALL = "reinstall"
    DESTROY = "destroy"
    VERB = "verb"
    SELF_UPDATE = "self-update"  # the machine updates itself (DM-163, DM-218)
    # Actions of the Panel.
    PASSPORT_EDIT = "passport.edit"
    PASSPORT_APPLY = "passport.apply"
    SERVER_ADD = "server.add"
    SERVER_DETACH = "server.detach"
    PEOPLE_INVITE = "people.invite"
    PEOPLE_GRANT = "people.grant"
    PEOPLE_REVOKE = "people.revoke"


MACHINE_VERBS: frozenset[Action] = frozenset(
    action for action in Action if "." not in action.value
)


@dataclass(frozen=True)
class ByRole:
    """A permission that depends on the role of the server acted on."""

    test: Permission
    prod: Permission

    def on(self, role: ServerRole) -> Permission:
        return self.prod if role is ServerRole.PROD else self.test


READ = None
"""Open to every member of the project."""

DEPLOY = ByRole(test=Permission.DEPLOY_TEST, prod=Permission.DEPLOY_PROD)

ACTION_PERMISSION: Mapping[Action, Permission | ByRole | None] = {
    Action.VERSION: READ,
    Action.STATUS: READ,
    Action.STATE: READ,
    Action.CHECK: READ,
    Action.REPORT: READ,
    Action.INSTALL: DEPLOY,
    Action.UPDATE: DEPLOY,
    Action.DEPLOY: DEPLOY,
    Action.ROLLBACK: DEPLOY,
    Action.DOCTOR: DEPLOY,
    Action.RESTART: DEPLOY,
    Action.START: DEPLOY,
    Action.STOP: DEPLOY,
    Action.LOGS: DEPLOY,
    Action.GC: DEPLOY,
    # The box's registration in the Panel (DM-139, changed by DM-196): who
    # issues the token registers the box; not a button (app.agent.verbs).
    Action.REGISTER: Permission.SERVERS,
    Action.SSL: DEPLOY,
    Action.SEED: Permission.SEEDS,
    Action.DB: Permission.DB,
    Action.BACKUP: Permission.DB,
    Action.REINSTALL: Permission.DESTRUCTIVE,
    Action.DESTROY: Permission.DESTRUCTIVE,
    Action.VERB: Permission.PROJECT_VERBS,
    # The machine's own release (DM-218): who installs the machine on a box by
    # its first contact -- the token of "add a server" -- updates it, on any
    # role.
    Action.SELF_UPDATE: Permission.SERVERS,
    Action.PASSPORT_EDIT: Permission.PASSPORT,
    Action.PASSPORT_APPLY: Permission.PASSPORT,
    Action.SERVER_ADD: Permission.SERVERS,
    Action.SERVER_DETACH: Permission.SERVERS,
    Action.PEOPLE_INVITE: Permission.PEOPLE,
    Action.PEOPLE_GRANT: Permission.PEOPLE,
    Action.PEOPLE_REVOKE: Permission.PEOPLE,
}


def permission_for(action: Action, role: ServerRole) -> Permission | None:
    """The permission ``action`` needs on a server of ``role``; ``None`` -- any
    member."""
    needed = ACTION_PERMISSION[action]
    if isinstance(needed, ByRole):
        return needed.on(role)
    return needed
