"""The Panel's one boundary of subprocess (DM-158): ``git`` and ``sops`` for
``primer-ops``, nothing else.

A command runs with the environment it is given and no other, in a process
group of its own (``git`` starts ``ssh``, ``ssh`` its ``ProxyCommand``). An
exit code outside ``expect`` is ``OpsCommandError`` -- never quiet.

- **A timeout or a cancellation** (the client went away) kills the group and
  waits for the leader; a group already gone is no error -- the command ended
  between the timeout and the kill (``ProcessLookupError``, DM-211). A
  cancellation goes on up; a timeout is ``timed out`` with the reason
  ``timeout``: what held it is not known. A command that ends by itself is not
  killed after: its pid may be another's by then.
- **What a failure carries** is what ran (``git fetch``), the code and the
  class of the cause read from stderr (``reason_of``: ``REASONS``) -- never a
  line of it: neither a path to a key nor anything a tool echoes leaves the
  process. On DM-160 the class is the one diagnosis of the access to
  ``primer-ops``.
"""

import asyncio
import os
import signal
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass

REASONS = ("host-key", "publickey", "dns", "network", "timeout", "other")
"""The classes of a refusal of ``git``, ``ssh`` or ``sops`` (DM-211)."""

SIGNS: tuple[tuple[str, tuple[bytes, ...]], ...] = (
    (
        "host-key",
        (
            b"Host key verification failed",
            b"REMOTE HOST IDENTIFICATION HAS CHANGED",
            b"host key is known for",
        ),
    ),
    (
        "publickey",
        (
            b"Permission denied (publickey",
            b"Repository not found",
            b"Load key",
            b"The key you are authenticating with has been marked as read only",
        ),
    ),
    (
        "dns",
        (
            b"Could not resolve hostname",
            b"Name or service not known",
            b"Temporary failure in name resolution",
        ),
    ),
    (
        "network",
        (
            b"Connection refused",
            b"Connection timed out",
            b"Network is unreachable",
            b"No route to host",
            b"Connection reset",
            b"Connection closed by",
            b"kex_exchange_identification",
            b"connect: ",
        ),
    ),
)
"""What OpenSSH, ``git`` and ``app.ops.connect`` say of each class, in the
order they are asked: a failed name ends in a closed connection too, so
``dns`` is asked before ``network``."""


def reason_of(stderr: bytes) -> str:
    """The class of a refusal by what the tool said; ``other`` -- none."""
    for reason, signs in SIGNS:
        if any(sign in stderr for sign in signs):
            return reason
    return "other"


@dataclass(frozen=True)
class Ran:
    code: int
    stdout: bytes


class OpsCommandError(Exception):
    """A command of ``git`` or ``sops`` that ended otherwise than expected."""

    def __init__(self, what: str, code: int | None, reason: str) -> None:
        said = "timed out" if code is None else f"exit code {code}"
        super().__init__(f"{what}: {said} ({reason})")
        self.what = what
        self.code = code
        self.reason = reason


async def run(
    argv: Sequence[str],
    *,
    what: str,
    env: Mapping[str, str],
    timeout_s: float,
    stdin: bytes = b"",
    expect: tuple[int, ...] = (0,),
) -> Ran:
    """``argv`` run to its end; its exit code and stdout. ``what`` names it in
    a failure (``git fetch``, ``sops decrypt``)."""
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(env),
        start_new_session=True,
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(stdin), timeout_s)
    except TimeoutError:
        await asyncio.shield(_end(process))
        raise OpsCommandError(what, None, "timeout") from None
    except asyncio.CancelledError:
        await asyncio.shield(_end(process))
        raise
    code = process.returncode
    if code is None or code not in expect:
        raise OpsCommandError(what, code, reason_of(err))
    return Ran(code, out)


async def _end(process: asyncio.subprocess.Process) -> None:
    """The group killed, the leader waited for; a group already gone is no
    error (the leader was reaped as it ended)."""
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    await process.wait()
