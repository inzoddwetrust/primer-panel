"""The verbs of the machine as the Panel offers them (DM-155): the buttons of a
server's card and the rules a command meets before the queue -- all here, the
page holds none (R-18, R-19).

- **A button** is a verb of the pinned release's registry (``VERBS``), in its
  order -- the machine has no groups -- but those of ``NOT_A_BUTTON``; and
  only when the person holds its permission on the server's role. ``Verb.box`` does not
  tell it: it says whether a verb takes the box's lock -- ``state`` reads a
  box without it. ``ssl`` is two buttons:
  ``ssl status`` (reading) and ``ssl renew``.
- **Its form** is the JSON Schema of the verb's own argument model, without
  the box's file paths (``BOX_PATHS``: the agent knows its box's files, the
  Panel does not), without what a button presets and without ``confirm`` --
  the name the person types, not a field.
- **Destructive** -- ``destroy``, ``reinstall``, ``db restore``/``reset``,
  the resets of ``seed`` and a project verb given ``confirm``: confirmed by
  the server's name, typed exactly (R-18; the machine's ``--confirm``).
- **On ``prod``** every action but reading is confirmed ("are you sure?").

KNOWN CEILING -- the machine's destructive actions are a table in the Panel:

1. Mechanics: the machine's registry names no destructive action as data --
   the rule is in the bodies of its verbs (``_confirmed``, the resets of
   ``seed``). The Panel keeps ``DESTRUCTIVE_ALWAYS`` and
   ``DESTRUCTIVE_WHEN`` from reading them (v0.1.9); a new destructive
   action of the machine is not destructive here until the table names it.
   A project verb's destructiveness lives in its ``primer.yaml``, which the
   Panel has not: given ``confirm``, it is taken as destructive.
2. Status: acknowledged by design (gate DM-155, R4).
3. Task: a card of the machine (the dispatcher's): a destructive mark and a
   group on ``Verb``.
4. Unfreeze trigger: ``pridem.verbs.Verb`` carries whether an action is
   destructive.
5. Agreed fix: the table goes; ``destructive`` reads the machine's mark.
6. Rejected: "destructive is a command given ``confirm``" (DM-153) -- it let
   ``db restore`` with no name into the queue.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pridem.verbs import VERBS

from app.access.actions import Action, permission_for
from app.access.permissions import Permission
from app.projects.models import ServerRole

BOX_PATHS = frozenset({"passport", "ops", "server"})
"""Arguments that are files of the box (``--passport``, ``--ops``,
``--server``): never in the Panel's forms."""

CONFIRM = "confirm"

NOT_A_BUTTON = frozenset({"check", "register"})
"""Verbs of the machine a command of the queue cannot run (changed by DM-196):
``check`` reads a repository at a path, not a box; ``register`` takes its
one-time token from the box's environment (``PRIDEM_REGISTER_TOKEN``, DM-139),
which no command of the queue carries."""

DESTRUCTIVE_ALWAYS = frozenset({"destroy", "reinstall"})
DESTRUCTIVE_WHEN: Mapping[str, Mapping[str, tuple[object, ...]]] = {
    "db": {"action": ("restore", "reset")},
    "seed": {"reset": (True,), "reset_only": (True,), "reset_all": (True,)},
}
"""A verb destructive when an argument has one of these values."""

NameMode = Literal["always", "when", "ask", "never"]


def destructive(verb: str, args: Mapping[str, object]) -> bool:
    if verb in DESTRUCTIVE_ALWAYS:
        return True
    for field, values in DESTRUCTIVE_WHEN.get(verb, {}).items():
        if args.get(field) in values:
            return True
    return verb == "verb" and args.get(CONFIRM) is not None


def needed_permission(
    verb: str, args: Mapping[str, object], role: str
) -> Permission | None:
    """The permission a command needs on a server of ``role``; ``None`` -- any
    member. ``ssl status`` reads (PRIMER-PANEL-TZ-1 1.1)."""
    if verb == "ssl" and args.get("action") == "status":
        return None
    return permission_for(Action(verb), ServerRole(role))


def needs_sure(verb: str, args: Mapping[str, object], role: str) -> bool:
    """ "Are you sure?": on ``prod``, every action but reading (R-18)."""
    return (
        role == ServerRole.PROD.value
        and needed_permission(verb, args, role) is not None
    )


@dataclass(frozen=True)
class Button:
    verb: str
    preset: dict[str, object]
    schema: dict[str, object]
    positionals: list[str]
    sure: bool
    name: NameMode
    destructive_options: dict[str, list[object]]


def _form(verb: str, preset: Mapping[str, object]) -> dict[str, object]:
    schema = VERBS[verb].args.model_json_schema()
    hidden = BOX_PATHS | {CONFIRM} | set(preset)
    properties = schema.get("properties", {})
    kept = {name: field for name, field in properties.items() if name not in hidden}
    required = [name for name in schema.get("required", []) if name not in hidden]
    form: dict[str, object] = {"type": "object", "properties": kept}
    if required:
        form["required"] = required
    return form


def _variants(verb: str) -> list[dict[str, object]]:
    if verb == "ssl":
        return [{"action": "status"}, {"action": "renew"}]
    return [{}]


def buttons(role: str, held: frozenset[Permission]) -> list[Button]:
    """The buttons a person holding ``held`` has on a server of ``role``."""
    found: list[Button] = []
    for name, verb in VERBS.items():
        if name in NOT_A_BUTTON:
            continue
        for preset in _variants(name):
            needed = needed_permission(name, preset, role)
            if needed is not None and needed not in held:
                continue
            mode: NameMode
            if name in DESTRUCTIVE_ALWAYS:
                mode = "always"
            elif name in DESTRUCTIVE_WHEN:
                mode = "when"
            elif name == "verb":
                mode = "ask"
            else:
                mode = "never"
            found.append(
                Button(
                    verb=name,
                    preset=dict(preset),
                    schema=_form(name, preset),
                    positionals=[p for p in verb.positionals if p not in preset],
                    sure=needs_sure(name, preset, role),
                    name=mode,
                    destructive_options={
                        field: list(values)
                        for field, values in DESTRUCTIVE_WHEN.get(name, {}).items()
                    },
                )
            )
    return found
