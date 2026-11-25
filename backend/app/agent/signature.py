"""Signatures of a box: of every request it sends, and of a verdict's envelope.

The box signs with its ed25519 key (``PRIMER-PANEL-TZ-2`` section 3); the
Panel holds the public half only, ``box_key_public``: base64 of the raw 32
bytes of the key. A signature is base64 of its raw 64 bytes.

- A request: ``signing_string`` of contract 4 (``pridem.protocol``) -- the
  method, the path as sent (no query), the time of ``X-Primer-Time`` and the
  SHA-256 of the body -- in UTF-8.
- A verdict's envelope: ``verdict_bytes`` of contract 4 over the verdict as
  the envelope's JSON carries it -- the object, not a model of it: the box
  signs the object of ``history/`` (DM-140). Changed by DM-196: the Panel's
  own copy of these bytes (DM-153, KNOWN CEILING) is gone.
"""

import base64
import binascii
from collections.abc import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pridem.events import Json
from pridem.protocol import signing_string, verdict_bytes

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


def verdict_holds(
    key: Ed25519PublicKey, signature: str, verdict: Mapping[str, Json]
) -> bool:
    """The envelope's signature holds for its verdict, the JSON object as the
    envelope carries it."""
    return _holds(key, signature, verdict_bytes(verdict))
