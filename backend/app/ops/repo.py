"""``primer-ops`` for the Panel (DM-158): a bare clone in the container.

The truth is the ops repository on GitHub; the clone is a cache of the
container, made again when it is gone. Every operation of the Panel on it
holds the lock of ``app.ops.router`` -- one at a time in the Panel.

- **The address** is ``OPS_REPO`` (``app.config``): ``ssh.github.com:443`` or
  ``file://``. Over ssh the host's keys are GitHub's, taken from the pinned
  machine (``pridem.steps.keys.GITHUB_HOST_KEYS``, the one source the pin
  guards) and written as ``[ssh.github.com]:443`` -- ``StrictHostKeyChecking
  yes``, no global file; the way out is ``app.ops.connect``.
- **The write key** -- a deploy key of ``primer-ops`` with write access -- and
  the Panel's **age key** are files of the stack (contract 3, ``asked`` with
  ``file``, DM-145): ``OpsPlaces``.
- **A commit** of the Panel changes one file and nothing else: its tree is the
  parent's with that one blob replaced, built in an index of its own; there is
  no work tree.
"""

import os
import secrets
import shlex
import sys
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from pridem.steps.keys import GITHUB_HOST_KEYS

from app.ops.run import Ran, run

BRANCH = "main"
"""The branch of ``primer-ops`` the boxes read (the machine's ``OpsSource``)."""

GIT_TIMEOUT_S = 60.0
SSH_HOST = "[ssh.github.com]:443"
COMMITTER = ("Primer Panel", "panel@primer.team")


@dataclass(frozen=True)
class OpsPlaces:
    """Where the Panel keeps its clone and finds its two keys (the paths of
    ``primer.yaml``: ``OPS_WRITE_KEY`` and ``OPS_AGE_KEY``)."""

    home: Path = field(default=Path("/tmp/panel-ops"))  # noqa: S108 -- the container's own
    write_key: Path = field(default=Path("/run/panel/ops-write.key"))
    age_key: Path = field(default=Path("/run/panel/ops-age.key"))


def known_hosts() -> str:
    """The ``known_hosts`` of the Panel: GitHub's keys on ``ssh.github.com:443``."""
    return "".join(f"{SSH_HOST} {key}\n" for key in GITHUB_HOST_KEYS)


@dataclass(frozen=True)
class Found:
    """A file of the ops repository at a commit."""

    blob: str
    content: bytes


class NotAFileError(Exception):
    """The path names a symlink, a directory or a submodule, not a file."""


class OpsRepo:
    """The Panel's clone of ``primer-ops``."""

    def __init__(self, address: str, places: OpsPlaces) -> None:
        self.address = address
        self.places = places

    @property
    def _bare(self) -> Path:
        return self.places.home / "ops.git"

    def _ssh(self) -> str:
        proxy = shlex.join([sys.executable, "-m", "app.ops.connect"]) + " %h %p"
        return shlex.join(
            [
                "ssh",
                "-F",
                "none",
                "-i",
                str(self.places.write_key),
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "GlobalKnownHostsFile=none",
                "-o",
                f"UserKnownHostsFile={self.places.home / 'known_hosts'}",
                "-o",
                f"ProxyCommand={proxy}",
            ]
        )

    def env(self) -> dict[str, str]:
        """The whole environment of ``git``: nothing of the Panel's own but
        the way out and the Python path the ``ProxyCommand`` needs."""
        found = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(self.places.home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_SSH_COMMAND": self._ssh(),
            "GIT_AUTHOR_NAME": COMMITTER[0],
            "GIT_AUTHOR_EMAIL": COMMITTER[1],
            "GIT_COMMITTER_NAME": COMMITTER[0],
            "GIT_COMMITTER_EMAIL": COMMITTER[1],
        }
        for name in ("HTTPS_PROXY", "https_proxy", "PYTHONPATH"):
            if name in os.environ:
                found[name] = os.environ[name]
        return found

    async def _git(
        self,
        what: str,
        *args: str,
        stdin: bytes = b"",
        expect: tuple[int, ...] = (0,),
        index: Path | None = None,
    ) -> Ran:
        env = self.env()
        if index is not None:
            env["GIT_INDEX_FILE"] = str(index)
        return await run(
            ["git", "--git-dir", str(self._bare), *args],
            what=f"git {what}",
            env=env,
            timeout_s=GIT_TIMEOUT_S,
            stdin=stdin,
            expect=expect,
        )

    async def _ready(self) -> None:
        """The clone and the host keys, made when they are not there."""
        home = self.places.home
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        hosts = home / "known_hosts"
        hosts.write_text(known_hosts())
        hosts.chmod(0o600)
        if (self._bare / "HEAD").exists():
            return
        await run(
            ["git", "init", "--bare", str(self._bare)],
            what="git init",
            env=self.env(),
            timeout_s=GIT_TIMEOUT_S,
        )
        await self._git("remote", "remote", "add", "origin", self.address)

    async def head(self) -> str | None:
        """The branch's commit on the remote, fetched; ``None`` -- no branch."""
        await self._ready()
        ref = f"refs/heads/{BRANCH}"
        listed = await self._git("ls-remote", "ls-remote", "origin", ref)
        if not listed.stdout.strip():
            return None
        await self._git(
            "fetch", "fetch", "origin", f"+{ref}:refs/remotes/origin/{BRANCH}"
        )
        found = await self._git(
            "rev-parse", "rev-parse", "--verify", f"refs/remotes/origin/{BRANCH}"
        )
        return found.stdout.decode().strip()

    async def known(self, commit: str) -> bool:
        """``commit`` is a commit of the clone."""
        found = await self._git(
            "cat-file",
            "cat-file",
            "-e",
            f"{commit}^{{commit}}",
            expect=(0, 1, 128),
        )
        return found.code == 0

    async def file(self, commit: str, path: str) -> Found | None:
        """``path`` at ``commit``; ``None`` -- not there."""
        listed = await self._git("ls-tree", "ls-tree", commit, "--", path)
        line = listed.stdout.decode().strip()
        if not line:
            return None
        meta, _, _ = line.partition("\t")
        mode, kind, blob = meta.split()
        if mode != "100644" or kind != "blob":
            raise NotAFileError(path)
        content = await self._git("cat-file", "cat-file", "blob", blob)
        return Found(blob, content.stdout)

    async def commit(self, parent: str, path: str, content: bytes, message: str) -> str:
        """A commit on ``parent`` whose tree differs in ``path`` alone."""
        blob = await self._git(
            "hash-object", "hash-object", "-w", "--stdin", stdin=content
        )
        index = self.places.home / f"index.{secrets.token_hex(8)}"
        try:
            await self._git("read-tree", "read-tree", parent, index=index)
            entry = f"100644,{blob.stdout.decode().strip()},{path}"
            await self._git(
                "update-index",
                "update-index",
                "--add",
                "--cacheinfo",
                entry,
                index=index,
            )
            tree = await self._git("write-tree", "write-tree", index=index)
        finally:
            with suppress(FileNotFoundError):
                os.remove(index)
        made = await self._git(
            "commit-tree",
            "commit-tree",
            tree.stdout.decode().strip(),
            "-p",
            parent,
            "-F",
            "-",
            stdin=message.encode(),
        )
        return made.stdout.decode().strip()

    async def push(self, commit: str) -> bool:
        """``commit`` onto the branch; ``False`` -- refused: the branch moved."""
        pushed = await self._git(
            "push", "push", "origin", f"{commit}:refs/heads/{BRANCH}", expect=(0, 1)
        )
        return pushed.code == 0
