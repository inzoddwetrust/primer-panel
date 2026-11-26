"""A passport of ``primer-ops`` as the Panel reads and edits it (DM-158).

- **Nothing decrypted on a disk** (DM-211): ``scratch`` holds the encrypted
  file only -- what ``sops`` reads and what ``sops set`` writes; a value comes
  to ``sops`` on stdin; the decryption is ``sops``' stdout, and the machine's
  loader reads it from a ``memfd``.
- **Reading** -- ``sops --decrypt`` with the Panel's age key; the Panel is a
  recipient of every passport it edits (TZ 0.7.41 O). A file the key does not
  open is ``NotRecipientError``; a file that is not sops' is ``DamagedError`` (the
  machine's exit codes of ``sops`` 3.13.3, ``pridem.steps.passport``).
- **The view** holds no secret: the leaves of ``asked`` and ``policies.tls``
  (contract 1 rules 5 and 12) are named, never valued -- ``set``, or
  ``switched_off`` for the literal of an option that is off (contract 3 rule
  39, not a secret).
- **An edit** is ``sops set`` with the value on stdin, never in argv, then the
  passport's ``version`` up by one (contract 1 rule 7) -- the file keeps its
  recipients: the boxes' keys stay as they were, the Panel needs none of them
  (measured on ``sops`` 3.13.3 at the gate). The result is checked by the
  pinned machine's loader before it is committed.
- **The rules of fields that are not obvious** (TZ §19 p.1) -- the Panel's
  table ``RULES``: the machine's model holds the limit, not the rule.
"""

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pridem.stacks.loader import ContractError, load_yaml_mapping
from pridem.stacks.passport import load_passport

from app.ops.repo import OpsPlaces
from app.ops.run import run

PASSPORTS = "passports"
SWITCHED_OFF = "primer-switched-off"
SOPS_TIMEOUT_S = 30.0
NOT_RECIPIENT = 128
DAMAGED = (1, 25)
SECRET_ROOTS = (("asked",), ("policies", "tls"))
"""The subtrees whose leaves are secrets (contract 1 rules 5 and 12)."""


def touches(path: tuple[str, ...], root: tuple[str, ...]) -> bool:
    """``path`` is ``root``, under it or above it: a value set there reaches
    ``root`` (a path above it replaces the whole subtree, DM-211)."""
    return path[: len(root)] == root or root[: len(path)] == path


RULES: dict[tuple[str, ...], str] = {
    ("policies", "gc", "keep_releases"): "keep_releases",
}
"""A field that is not obvious and the key of its rule's text (TZ §19 p.1):
``keep_releases: 1`` removes the directory of the previous release (contract 1
rule 16)."""

Path_ = tuple[str, ...]


class NotRecipientError(Exception):
    """The Panel's age key does not open the file."""


class DamagedError(Exception):
    """The file is not a sops file the Panel can decrypt."""


def passport_path(server: str) -> str:
    """Where a server's passport lives in ``primer-ops`` (contract 1 §3)."""
    return f"{PASSPORTS}/{server}.yaml"


def is_secret(path: Path_) -> bool:
    return any(path[: len(root)] == root for root in SECRET_ROOTS)


@contextmanager
def _scratch(places: OpsPlaces, content: bytes) -> Iterator[Path]:
    """``content`` in a file of its own, 0600, removed after."""
    folder = places.home / "scratch"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(suffix=".yaml", dir=folder)
    try:
        os.write(handle, content)
    finally:
        os.close(handle)
    try:
        yield Path(name)
    finally:
        Path(name).unlink(missing_ok=True)


def _env(places: OpsPlaces) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(places.home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "SOPS_AGE_KEY_FILE": str(places.age_key),
    }


async def decrypted(places: OpsPlaces, content: bytes) -> bytes:
    """The YAML of a sops file, decrypted with the Panel's key."""
    with _scratch(places, content) as file:
        ran = await run(
            [
                "sops",
                "--decrypt",
                "--input-type",
                "yaml",
                "--output-type",
                "yaml",
                str(file),
            ],
            what="sops decrypt",
            env=_env(places),
            timeout_s=SOPS_TIMEOUT_S,
            expect=(0, NOT_RECIPIENT, *DAMAGED),
        )
    if ran.code == NOT_RECIPIENT:
        raise NotRecipientError
    if ran.code in DAMAGED:
        raise DamagedError
    return ran.stdout


@dataclass(frozen=True)
class Plain:
    """A decrypted passport and what the pinned machine's loader says of it:
    ``problems`` -- where and which check, never what the file says (the
    machine's own form, ``pridem.steps.passport``); empty -- it passes.

    ``data`` is the file's mapping as it is, passing or not (empty when it is
    no YAML mapping at all): a passport the loader refuses is shown and can be
    mended from the Panel (the dispatcher's word on DM-158 A)."""

    data: dict[str, object]
    problems: list[str]

    def version(self) -> int | None:
        found = self.data.get("version")
        return found if isinstance(found, int) and not isinstance(found, bool) else None

    def server(self, field: str) -> object:
        found = self.data.get("server")
        return found.get(field) if isinstance(found, dict) else None


def _problems(error: ContractError) -> list[str]:
    return [f"{p.path or '<root>'} [{p.code}]" for p in error.problems]


@contextmanager
def _in_memory(text: bytes) -> Iterator[Path]:
    """``text`` as a file with no place on a disk (DM-211): a ``memfd`` the
    loader reads by ``/proc/self/fd/<n>``, closed after -- it goes with the
    process, nothing of it is left in ``scratch`` or anywhere."""
    handle = os.memfd_create("passport", os.MFD_CLOEXEC)
    try:
        rest = memoryview(text)
        while rest:
            rest = rest[os.write(handle, rest) :]
        yield Path(f"/proc/self/fd/{handle}")
    finally:
        os.close(handle)


def checked(text: bytes) -> Plain:
    """A decrypted passport through the pinned machine's loader, read from
    memory: the decryption never touches the file system (DM-211)."""
    with _in_memory(text) as file:
        try:
            data = load_yaml_mapping(file)
        except ContractError as error:
            return Plain({}, _problems(error))
        try:
            load_passport(file)
        except ContractError as error:
            return Plain(data, _problems(error))
        return Plain(data, [])


def _leaves(node: object, prefix: Path_) -> list[tuple[Path_, object]]:
    if isinstance(node, dict) and node:
        found: list[tuple[Path_, object]] = []
        for key, value in node.items():
            found += _leaves(value, (*prefix, str(key)))
        return found
    return [(prefix, node)]


def _state(value: object) -> str:
    return "switched_off" if value == SWITCHED_OFF else "set"


def view(data: dict[str, object]) -> dict[str, object]:
    """The passport without a secret's value: the plain fields, the secrets
    by name and state, the rules of the fields that are not obvious."""
    fields: list[dict[str, object]] = []
    secrets: list[dict[str, object]] = []
    tls: list[dict[str, object]] = []
    shown: set[Path_] = set()
    for path, value in _leaves(data, ()):
        if not is_secret(path):
            fields.append({"path": list(path), "value": value})
            shown.add(path)
        elif len(path) == 3 and path[0] == "asked":
            secrets.append({"stack": path[1], "key": path[2], "state": _state(value)})
        elif len(path) == 3:
            tls.append({"key": path[2], "state": _state(value)})
        # else: a leaf of a secret subtree at another depth (an empty
        # mapping, or a form the loader refuses) -- never shown
    rules = [
        {"path": list(path), "rule": rule}
        for path, rule in RULES.items()
        if path in shown
    ]
    return {"fields": fields, "secrets": secrets, "tls": tls, "rules": rules}


def _index(path: Path_) -> str:
    return "".join(f"[{json.dumps(part)}]" for part in path)


async def edited(
    places: OpsPlaces, content: bytes, changes: list[tuple[Path_, object]]
) -> bytes:
    """The sops file with ``changes`` set by ``sops set``, each value on
    stdin; its recipients as they were."""
    with _scratch(places, content) as file:
        for path, value in changes:
            await run(
                [
                    "sops",
                    "set",
                    "--value-stdin",
                    "--input-type",
                    "yaml",
                    "--output-type",
                    "yaml",
                    str(file),
                    _index(path),
                ],
                what="sops set",
                env=_env(places),
                timeout_s=SOPS_TIMEOUT_S,
                stdin=json.dumps(value).encode(),
            )
        return file.read_bytes()


_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values: list[int]) -> int:
    generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    check = 1
    for value in values:
        top = check >> 25
        check = (check & 0x1FFFFFF) << 5 ^ value
        for i in range(5):
            check ^= generator[i] if (top >> i) & 1 else 0
    return check


def _expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convert(data: list[int], source: int, target: int, pad: bool) -> list[int]:
    acc, bits, out = 0, 0, []
    for value in data:
        acc = (acc << source) | value
        bits += source
        while bits >= target:
            bits -= target
            out.append((acc >> bits) & ((1 << target) - 1))
    if pad and bits:
        out.append((acc << (target - bits)) & ((1 << target) - 1))
    elif not pad and (bits >= source or (acc << (target - bits)) & ((1 << target) - 1)):
        raise ValueError("not a key of age")
    return out


def age_public_key(secret: str) -> str:
    """The recipient of an age identity (``age-keygen -y``): bech32 of the
    X25519 public key -- the one thing of the Panel's key it shows."""
    line = next(
        (s.strip() for s in secret.splitlines() if s.startswith("AGE-SECRET-KEY-1")),
        "",
    )
    hrp, _, rest = line.lower().rpartition("1")
    words = [_CHARSET.index(c) for c in rest] if hrp == "age-secret-key-" else []
    if len(words) < 7 or _polymod(_expand(hrp) + words) != 1:
        raise ValueError("not a key of age")
    raw = bytes(_convert(words[:-6], 5, 8, False))
    public = (
        X25519PrivateKey.from_private_bytes(raw)
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    data = _convert(list(public), 8, 5, True)
    check = _polymod([*_expand("age"), *data, 0, 0, 0, 0, 0, 0]) ^ 1
    tail = [(check >> 5 * (5 - i)) & 31 for i in range(6)]
    return "age1" + "".join(_CHARSET[d] for d in [*data, *tail])
