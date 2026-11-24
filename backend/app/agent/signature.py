"""Signatures of a box: of every request it sends, and of a verdict's envelope.

The box signs with its ed25519 key (``PRIMER-PANEL-TZ-2`` section 3); the
Panel holds the public half only, ``box_key_public``: base64 of the raw 32
bytes of the key. A signature is base64 of its raw 64 bytes.

- A request: ``signing_string`` of contract 4 (``pridem.protocol``) -- the
  method, the path as sent (no query), the time of ``X-Primer-Time`` and the
  SHA-256 of the body -- in UTF-8.
- A verdict's envelope: ``verdict_bytes`` below.

KNOWN CEILING -- the bytes of a verdict's signature live in the Panel:

1. Mechanics: contract 4 says the envelope carries "the verdict's signature
   with the box's key" and not what is signed; the machine signs nothing yet
   (DM-140). The Panel checks the signature over ``verdict_bytes``: the
   verdict as contract 2 dumps it to JSON, keys sorted, ``,`` and ``:`` with
   no spaces, UTF-8 (``ensure_ascii=False``). A box signing other bytes gets
   every verdict kept with ``verified: false``.
2. Status: acknowledged by design (gate DM-153, R6).
3. Task: DM-140 -- the machine signs exactly these bytes and takes this
   function into contract 4.
4. Unfreeze trigger: ``pridem.protocol`` names the bytes of a verdict's
   signature (a function beside ``signing_string``).
5. Agreed fix: this function is deleted and the Panel calls contract 4's.
6. Rejected: the bytes of ``history/<run_id>.json`` as the file holds them --
   the Panel receives the verdict parsed inside the envelope's JSON, not the
   file; checking no signature until DM-140 -- every verdict red with no way
   to tell a forged one.
"""

import base64
import binascii
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pridem.protocol import signing_string
from pridem.report.schema import Verdict

KEY_BYTES = 32


class KeyFormError(ValueError):
    """``box_key_public`` is not base64 of a raw 32-byte ed25519 key."""


def public_key(value: str) -> Ed25519PublicKey:
    """The box's public key from its form in the registration."""
    try:
        raw = base64.b64decode(value, validate=True)
    except binascii.Error as error:
        raise KeyFormError("box_key_public is not base64") from error
    if len(raw) != KEY_BYTES:
        raise KeyFormError(f"box_key_public is not {KEY_BYTES} bytes")
    return Ed25519PublicKey.from_public_bytes(raw)


def _holds(key: Ed25519PublicKey, signature: str, message: bytes) -> bool:
    try:
        raw = base64.b64decode(signature, validate=True)
        key.verify(raw, message)
    except (binascii.Error, InvalidSignature):
        return False
    return True


def request_holds(
    key: Ed25519PublicKey,
    signature: str,
    *,
    method: str,
    path: str,
    time: int,
    body: bytes,
) -> bool:
    """The request's signature holds for its method, path, time and body."""
    message = signing_string(method, path, time, body).encode()
    return _holds(key, signature, message)


def verdict_bytes(verdict: Verdict) -> bytes:
    """What a verdict's envelope signs (module docstring: KNOWN CEILING)."""
    dumped = verdict.model_dump(mode="json")
    text = json.dumps(dumped, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode()


def verdict_holds(key: Ed25519PublicKey, signature: str, verdict: Verdict) -> bool:
    """The envelope's signature holds for its verdict."""
    return _holds(key, signature, verdict_bytes(verdict))
