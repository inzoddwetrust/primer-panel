"""The verbs of the machine as the Panel offers them (DM-155): the buttons of a
server's card and the rules a command meets before the queue -- all here, the
page holds none (R-18, R-19).

- **What is not a button is not queued** (DM-202): one rule, ``not_a_button``,
  decides for a verb with its arguments, and the buttons, the queue and the
  "repeat" of a run's page ask it. A button is a verb of the pinned release's
  registry (``VERBS``) that ends with a verdict -- the machine's own mark
  ``Verb.verdict``, less the values of a field that write none
  (``NO_VERDICT_VARIANTS``) -- and not of ``NOT_A_BUTTON``; its arguments are
  the fields of its form, what it presets and ``confirm``. The buttons come in
  the registry's order -- the machine has no groups -- and only when the
  person holds the permission on the server's role. ``ssl`` is one button,
  ``ssl renew``.
- **Its form** is the JSON Schema of the verb's own argument model, without
  the box's file paths (``BOX_PATHS``: the agent knows its box's files, the
  Panel does not), without what a button presets, without ``confirm`` --
  the name the person types, not a field -- and without a value of a field
  that writes no verdict (``db``'s ``connect``).
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

NOT_A_BUTTON: Mapping[str, str] = {
    "check": "it reads a repository at a path, not a box",
    "register": "its one-time token is in the box's environment",
}
"""Verbs of the machine a command of the queue cannot run (changed by DM-196):
``check`` reads a repository at a path, not a box; ``register`` takes its
one-time token from the box's environment (``PRIDEM_REGISTER_TOKEN``, DM-139),
which no command of the queue carries. With a verdict both, so the agent
would run them: the Panel is the only bar (DM-202)."""

NO_VERDICT_VARIANTS: Mapping[str, tuple[Mapping[str, object], ...]] = {
    "ssl": ({"action": "status"},),
    "db": ({"action": "connect"},),
}
"""Values of a field that write no verdict, though the machine marks its verb
as one that does (DM-202): ``Verb.verdict`` is a mark on the whole verb.

- ``ssl status`` reads, as ``state``: no lock, no journal, no verdict; the
  machine refuses ``--command`` to it in its own branch (``ssl.py``
  ``_status``) and the agent (DM-141) refuses it ``verb-unknown``.
- ``db connect`` is ``psql`` on a terminal, no verdict and no lock, as
  ``logs`` (``data.py`` ``_connect``); under the agent the machine refuses
  it: the runner hands no terminal.

Each is one field and one value: a button never presets it, its form never
offers it."""

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
    member. Changed by DM-202: ``ssl status`` is no button, so a command never
    asks its permission (it read as any member's)."""
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


def _fields(
    verb: str, preset: Mapping[str, object]
) -> tuple[dict[str, object], list[str]]:
    """The fields of a button's form and the required ones among them."""
    schema = VERBS[verb].args.model_json_schema()
    hidden = BOX_PATHS | {CONFIRM} | set(preset)
    properties = schema.get("properties", {})
    kept = {name: field for name, field in properties.items() if name not in hidden}
    for cut in NO_VERDICT_VARIANTS.get(verb, ()):  # changed by DM-202
        for name, value in cut.items():
            field = kept.get(name)
            if isinstance(field, dict):  # a preset field is hidden already
                values = [given for given in field["enum"] if given != value]
                kept[name] = {**field, "enum": values}
    required = [name for name in schema.get("required", []) if name not in hidden]
    return kept, required


def _form(verb: str, preset: Mapping[str, object]) -> dict[str, object]:
    kept, required = _fields(verb, preset)
    form: dict[str, object] = {"type": "object", "properties": kept}
    if required:
        form["required"] = required
    return form


def _variants(verb: str) -> list[dict[str, object]]:
    if verb == "ssl":
        return [{"action": "status"}, {"action": "renew"}]
    return [{}]


def _matches(variant: Mapping[str, object], args: Mapping[str, object]) -> bool:
    return all(args.get(name) == value for name, value in variant.items())


def not_a_button(verb: str, args: Mapping[str, object]) -> str | None:
    """Why ``verb`` with ``args`` is no button of the Panel; ``None`` -- it is
    one (DM-202). Asked after the verb's model has passed ``args`` (a
    ``confirm`` the verb does not take is refused there), before the
    permission: what is not a button does not tell which permission a button
    would need."""
    if verb in NOT_A_BUTTON:
        return f"{verb} is no button: {NOT_A_BUTTON[verb]}"
    if not VERBS[verb].verdict:
        return f"{verb} is no button: it writes no verdict"
    for cut in NO_VERDICT_VARIANTS.get(verb, ()):
        if _matches(cut, args):
            words = " ".join(str(value) for value in cut.values())
            return f"{verb} {words} is no button: it writes no verdict"
    preset = next(variant for variant in _variants(verb) if _matches(variant, args))
    fields, _ = _fields(verb, preset)
    allowed = set(fields) | set(preset) | {CONFIRM}
    stray = sorted(set(args) - allowed)
    if stray:
        return f"{stray[0]} is no field of the button {verb}"
    return None


def buttons(role: str, held: frozenset[Permission]) -> list[Button]:
    """The buttons a person holding ``held`` has on a server of ``role``:
    every verb and variant ``not_a_button`` passes (changed by DM-202)."""
    found: list[Button] = []
    for name, verb in VERBS.items():
        for preset in _variants(name):
            if not_a_button(name, preset) is not None:
                continue
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
