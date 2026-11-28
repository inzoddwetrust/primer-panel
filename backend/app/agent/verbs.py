"""The verbs of the machine as the Panel offers them (DM-155): the buttons of a
server's card and the rules a command meets before the queue -- all here, the
page holds none (R-18, R-19).

- **What is not a button is not queued** (DM-202): one rule, ``not_a_button``,
  decides for a verb with its arguments, and the buttons, the queue and the
  "repeat" of a run's page ask it. A button is a verb of the pinned release's
  registry (``VERBS``) whose run ends with a verdict -- the machine's own
  marks, ``Verb.verdict`` and the values of a field that write none
  (``Verb.no_verdict``, DM-198) -- and not of ``NOT_A_BUTTON``; its
  arguments are the fields of its form, what it presets and ``confirm``, a
  field with choices one of them. The buttons come in the machine's groups
  (``pridem.verbs.GROUPS``, the registry's order inside one) and only when
  the person holds the permission on the server's role. ``ssl`` is one
  button, ``ssl renew``.
- **Its form** is the JSON Schema of the verb's own argument model, without
  the box's file paths (``BOX_PATHS``: the agent knows its box's files, the
  Panel does not), without a field only tier 3 gives (``HIDDEN``), without
  what a button presets, without ``confirm`` -- the name the person types,
  not a field -- and without a value of a field that writes no verdict
  (``db``'s ``connect``).
- **Destructive** -- the machine's mark (``Verb.destroys``, DM-198):
  ``destroy``, ``reinstall``, ``db restore``/``reset``, the resets of ``seed``;
  a project verb's mark is its ``primer.yaml``'s, which the Panel has not
  (``Destructive.declared``): given ``confirm``, it is taken as destructive.
  Confirmed by the server's name, typed exactly (R-18; the machine's
  ``--confirm``).
- **On ``prod``** every action but reading is confirmed ("are you sure?").
- **``self-update``** (DM-218, PRIMER-PANEL-TZ-2 12): its ``tag`` is one of
  ``MACHINE_RELEASES``, the releases of the machine the Panel knows; a tag
  below the box's machine is a rollback, confirmed ("are you sure?") on any
  role (``rolls_back``); a box whose machine is below the first release with
  the verb, or not known, is refused before the queue (``no_self_update``):
  its agent has no such verb.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from packaging.version import InvalidVersion, Version
from pridem.verbs import GROUPS, VERBS

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

HIDDEN: Mapping[str, frozenset[str]] = {"self-update": frozenset({"source"})}
"""Fields of a verb no button has: ``self-update``'s ``source`` (``--from``) is
an ``install.sh`` by ``file://`` or loopback ``http://`` -- tier 3's, never a
box's of the Panel."""

SELF_UPDATE = "self-update"
TAG = "tag"
MACHINE_RELEASES: tuple[str, ...] = ("v0.1.12",)
"""The releases of the machine a box can be updated to from the Panel
(DM-218): those that have ``self-update``, from the first, ``v0.1.12``
(DM-163), to the Panel's own pin, which is the last -- a box below the first
has no such verb, and one turned below it would have none to come back by.
Every raise of the Panel's pin adds its row; no other source, no network."""

NameMode = Literal["always", "when", "ask", "never"]


def _version(text: object) -> Version | None:
    if not isinstance(text, str):
        return None
    try:
        return Version(text.removeprefix("v"))
    except InvalidVersion:
        return None


def destructive(verb: str, args: Mapping[str, object]) -> bool:
    """Whether the command is destructive: the machine's mark; a project
    verb's -- given ``confirm``."""
    found = VERBS[verb].destroys(args)
    if found is None:  # declared by the product's primer.yaml
        return args.get(CONFIRM) is not None
    return found


def no_self_update(verb: str, machine_version: str | None) -> str | None:
    """Why the box cannot run ``self-update``: its machine is below the first
    release with the verb, or not known (no heartbeat); ``None`` -- it can,
    or the verb is another."""
    if verb != SELF_UPDATE:
        return None
    first = _version(MACHINE_RELEASES[0])
    found = _version(machine_version)
    if found is None:
        return "the machine of this server is not known -- update it from the console"
    if first is not None and found < first:
        return (
            f"the machine of this server is {machine_version}, with no self-update "
            f"(from {MACHINE_RELEASES[0]}) -- update it from the console"
        )
    return None


def rolls_back(
    verb: str, args: Mapping[str, object], machine_version: str | None
) -> bool:
    """A ``self-update`` to a tag below the box's machine: a rollback."""
    if verb != SELF_UPDATE:
        return False
    tag, found = _version(args.get(TAG)), _version(machine_version)
    return tag is not None and found is not None and tag < found


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
    sure_below: str | None
    """The field whose release below the box's machine is confirmed ("are you
    sure?"): ``tag`` of ``self-update``; ``None`` -- none."""


def _fields(
    verb: str, preset: Mapping[str, object]
) -> tuple[dict[str, object], list[str]]:
    """The fields of a button's form and the required ones among them."""
    schema = VERBS[verb].args.model_json_schema()
    hidden = BOX_PATHS | {CONFIRM} | set(preset) | HIDDEN.get(verb, frozenset())
    properties = schema.get("properties", {})
    kept = {name: field for name, field in properties.items() if name not in hidden}
    for name, silent in VERBS[verb].no_verdict:  # the machine's mark (DM-198)
        field = kept.get(name)
        if isinstance(field, dict):  # a preset field is hidden already
            values = [given for given in field["enum"] if given not in silent]
            kept[name] = {**field, "enum": values}
    if verb == SELF_UPDATE and isinstance(kept.get(TAG), dict):
        kept[TAG] = {**kept[TAG], "enum": list(MACHINE_RELEASES)}
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
    silent = VERBS[verb].without_verdict(args)  # the machine's mark (DM-198)
    if silent is not None:
        return f"{silent} is no button: it writes no verdict"
    preset = next(variant for variant in _variants(verb) if _matches(variant, args))
    fields, _ = _fields(verb, preset)
    allowed = set(fields) | set(preset) | {CONFIRM}
    stray = sorted(set(args) - allowed)
    if stray:
        return f"{stray[0]} is no field of the button {verb}"
    for name, field in fields.items():
        choices = field.get("enum") if isinstance(field, dict) else None
        if name in args and isinstance(choices, list) and args[name] not in choices:
            return f"{args[name]} is no choice of {name} of the button {verb}"
    return None


def buttons(role: str, held: frozenset[Permission]) -> list[Button]:
    """The buttons a person holding ``held`` has on a server of ``role``:
    every verb and variant ``not_a_button`` passes (changed by DM-202)."""
    found: list[Button] = []
    ordered = sorted(VERBS.items(), key=lambda item: GROUPS.index(item[1].group))
    for name, verb in ordered:  # the registry's order inside a group (stable)
        for preset in _variants(name):
            if not_a_button(name, preset) is not None:
                continue
            needed = needed_permission(name, preset, role)
            if needed is not None and needed not in held:
                continue
            mark = verb.destructive  # the machine's mark (DM-198)
            mode: NameMode
            if mark.always:
                mode = "always"
            elif mark.when:
                mode = "when"
            elif mark.declared:
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
                        field: list(values) for field, values in mark.when
                    },
                    sure_below=TAG if name == SELF_UPDATE else None,
                )
            )
    return found
