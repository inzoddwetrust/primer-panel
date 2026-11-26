"""The Panel's one boundary of subprocess (DM-158): ``git`` and ``sops`` for
``primer-ops``, nothing else.

A command runs with the environment it is given and no other, in a process
group of its own: a timeout kills the group (``git`` starts ``ssh``). An exit
code outside ``expect`` is ``OpsCommandError`` -- never quiet. What a failure
carries is what ran (``git fetch``) and the code: its output is not read
into an error or a log line, so neither a path to a key nor anything a tool
echoes leaves the process.
"""

import asyncio
import os
import signal
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Ran:
    code: int
    stdout: bytes


class OpsCommandError(Exception):
    """A command of ``git`` or ``sops`` that ended otherwise than expected."""

    def __init__(self, what: str, code: int | None) -> None:
        said = "timed out" if code is None else f"exit code {code}"
        super().__init__(f"{what}: {said}")
        self.what = what
        self.code = code


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
        out, _ = await asyncio.wait_for(process.communicate(stdin), timeout_s)
    except TimeoutError:
        os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
        raise OpsCommandError(what, None) from None
    code = process.returncode
    if code is None or code not in expect:
        raise OpsCommandError(what, code)
    return Ran(code, out)
