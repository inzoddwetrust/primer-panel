"""A primer-ops of the tests (DM-158): a bare repository on disk, reached by
``file://``, with passports encrypted by the real ``sops`` for two
recipients -- the Panel's age key and a box's -- as the owner's ops repository
is. The keys are made by ``age-keygen`` for each test.

``OpsSide`` is also the other writers of the repository: a commit "past the
Panel" goes from its own work tree, and the box reads a passport back with its
own key, never the Panel's.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.ops.repo import OpsPlaces

SERVER = "velo-test-1"

# A passport of contract 1, written out; the secrets are stand-ins of the
# tests, none in the form of a real key.
PASSPORT = """schema: 1
version: 7
server:
  name: {name}
  role: test
  os: ubuntu-24.04
product:
  repo: git@github.com:o/a.git
  ref: main
domains:
  frontend: test.velo.example
  api: api-test.velo.example
access:
  mode: deploy-keys
asked:
  comms:
    TELEGRAM_BOT_TOKEN: stand-in-telegram-token-of-the-tests
    MAILGUN_API_KEY: primer-switched-off
params:
  comms:
    MAIL_DOMAIN: primer-switched-off
policies:
  ssl: letsencrypt
  gc:
    keep_releases: 2
    builder_cache_budget: 3G
    journal_budget: 200M
  backup:
    enabled: false
  timers:
    gc: daily
packages: {{}}
cloud: {{}}
"""


def _run(*argv: str, cwd: Path | None = None, stdin: bytes = b"") -> bytes:
    return subprocess.run(
        argv, cwd=cwd, input=stdin, capture_output=True, check=True
    ).stdout


def age_key(path: Path) -> str:
    """A new age identity at ``path``; its recipient."""
    _run("age-keygen", "-o", str(path))
    return _run("age-keygen", "-y", str(path)).decode().strip()


@dataclass
class OpsSide:
    root: Path
    places: OpsPlaces
    panel_public: str
    box_key: Path
    box_public: str

    @property
    def remote(self) -> Path:
        return self.root / "primer-ops.git"

    @property
    def work(self) -> Path:
        return self.root / "work"

    @property
    def url(self) -> str:
        return f"file://{self.remote}"

    def encrypt(self, text: str, recipients: list[str] | None = None) -> bytes:
        """``text`` as sops writes it for the Panel and the box."""
        plain = self.root / "plain.yaml"
        plain.write_text(text)
        try:
            keys = ",".join(recipients or [self.panel_public, self.box_public])
            return _run(
                "sops",
                "--encrypt",
                "--age",
                keys,
                "--input-type",
                "yaml",
                "--output-type",
                "yaml",
                str(plain),
            )
        finally:
            plain.unlink()

    def put(self, name: str, content: bytes) -> str:
        """``passports/<name>.yaml`` committed and pushed past the Panel."""
        _run("git", "pull", "--quiet", "origin", "main", cwd=self.work)
        file = self.work / "passports" / f"{name}.yaml"
        file.parent.mkdir(exist_ok=True)
        file.write_bytes(content)
        _run("git", "add", "-A", cwd=self.work)
        _run("git", "commit", "--quiet", "-m", f"owner: {name}", cwd=self.work)
        _run("git", "push", "--quiet", "origin", "HEAD:main", cwd=self.work)
        return self.head()

    def head(self) -> str:
        return (
            _run("git", "--git-dir", str(self.remote), "rev-parse", "main")
            .decode()
            .strip()
        )

    def raw(self, name: str, commit: str = "main") -> bytes:
        return _run(
            "git",
            "--git-dir",
            str(self.remote),
            "show",
            f"{commit}:passports/{name}.yaml",
        )

    def as_box(self, name: str, commit: str = "main") -> str:
        """The passport as the box reads it: decrypted with the box's key."""
        cipher = self.root / "cipher.yaml"
        cipher.write_bytes(self.raw(name, commit))
        try:
            return subprocess.run(
                [
                    "sops",
                    "--decrypt",
                    "--input-type",
                    "yaml",
                    "--output-type",
                    "yaml",
                    str(cipher),
                ],
                capture_output=True,
                check=True,
                env={"SOPS_AGE_KEY_FILE": str(self.box_key), "PATH": _path()},
            ).stdout.decode()
        finally:
            cipher.unlink()


def _path() -> str:
    return os.environ.get("PATH", "/usr/bin:/bin")


def make_ops(root: Path) -> OpsSide:
    """An ops repository with one passport, of ``SERVER``."""
    keys = root / "keys"
    keys.mkdir()
    places = OpsPlaces(
        home=root / "panel-ops",
        write_key=keys / "ops-write.key",
        age_key=keys / "ops-age.key",
    )
    side = OpsSide(
        root=root,
        places=places,
        panel_public=age_key(places.age_key),
        box_key=keys / "box.key",
        box_public="",
    )
    side.box_public = age_key(side.box_key)
    places.write_key.write_text("not used by file://\n")
    _run("git", "init", "--quiet", "--bare", "--initial-branch=main", str(side.remote))
    _run("git", "init", "--quiet", "--initial-branch=main", str(side.work))
    for name, value in (("user.name", "Owner"), ("user.email", "owner@example.test")):
        _run("git", "config", name, value, cwd=side.work)
    _run("git", "remote", "add", "origin", str(side.remote), cwd=side.work)
    (side.work / "README").write_text("primer-ops of the tests\n")
    _run("git", "add", "-A", cwd=side.work)
    _run("git", "commit", "--quiet", "-m", "start", cwd=side.work)
    _run("git", "push", "--quiet", "origin", "HEAD:main", cwd=side.work)
    side.put(SERVER, side.encrypt(PASSPORT.format(name=SERVER)))
    return side
