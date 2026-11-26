"""Probes of DM-211, the review of the Panel (PRIMER-PANEL-REVIEW-0001): the
passport and primer-ops -- the paths of an edit, the lock, the decryption off
the file system, the processes, the class of a refusal.

primer-ops is the test's bare repository, the passports are encrypted by the
real ``sops`` (tests/ops.py); the processes are real ones."""
# ruff: noqa: S608 -- the SQL is the tests' own

import asyncio
import os
import signal
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

import app.ops.passport as passport_module
import app.ops.router as router_module
from app.core.database import make_engine
from app.ops.repo import OpsPlaces, OpsRepo
from app.ops.router import LOCK_KEY, _unreachable
from app.ops.run import OpsCommandError, reason_of, run
from tests.conftest import FRONTEND, execute, query_scalar
from tests.failing import inner_app
from tests.ops import PASSPORT, SERVER, OpsSide
from tests.people import World, access_app
from tests.test_passport import _pem, apply, put_field, put_secret, read, server

SECRET = "stand-in-telegram-token-of-the-tests"  # noqa: S105 -- tests/ops.py's stand-in
ARCHIVE = "UPDATE projects SET archived_at = now() WHERE id = '{project}'"
UNARCHIVE = "UPDATE projects SET archived_at = NULL WHERE id = '{project}'"
DETACH = "UPDATE servers SET detached_at = now() WHERE id = '{server}'"

# --- 1. the paths ---------------------------------------------------------------

# Paths the route of a field never reaches, written out: above a secret, under
# a fixed field, the version both ways -- each with a value the machine's
# loader would take, where one exists, so the route and not the loader is
# what refuses; and the route's own word for it.
CERT = (
    "-----BEGIN CERTIFICATE-----\nreplaced-certificate-0010\n"
    "-----END CERTIFICATE-----\n"
)
POLICIES = {
    "ssl": "letsencrypt",
    "gc": {"keep_releases": 2, "builder_cache_budget": "3G", "journal_budget": "200M"},
    "backup": {"enabled": False},
    "timers": {"gc": "daily"},
}
BY_ITS_ROUTE = "a secret is set by /passport/secret"
UNREACHABLE: list[tuple[list[str], object, str]] = [
    (["policies"], POLICIES, BY_ITS_ROUTE),
    (
        ["asked"],
        {"comms": {"TELEGRAM_BOT_TOKEN": "replaced-token-0011-xxxx"}},
        BY_ITS_ROUTE,
    ),
    (
        ["asked", "comms"],
        {"TELEGRAM_BOT_TOKEN": "replaced-token-0012-xxxx"},
        BY_ITS_ROUTE,
    ),
    (["policies", "tls"], {"cert": CERT, "key": CERT}, BY_ITS_ROUTE),
    (["policies", "tls", "cert"], CERT, BY_ITS_ROUTE),
    (
        ["server"],
        {"name": SERVER, "role": "prod", "os": "ubuntu-24.04"},
        "server.name is the server's name",
    ),
    (["server", "name", "x"], "y", "server.name is the server's name"),
    (["server", "role", "x"], "y", "server.role is the owner's to change"),
    (["version", "x"], 9, "the version is the Panel's to raise"),
]


def test_probe_DM_211_no_path_reaches_past_its_route(
    ops_world: World, ops_side: OpsSide
) -> None:
    """Every path above a secret, under or above a fixed field, and the
    version both ways -- 422 by the route's own word, no commit, the secrets
    as they were (the box reads them). The pair: a field beside them goes."""
    provided = PASSPORT.format(name=SERVER).replace(
        "  ssl: letsencrypt\n",
        "  ssl: provided\n  tls:\n    cert: |\n"
        + _pem("CERTIFICATE", "stand-in-certificate")
        + "    key: |\n"
        + _pem("PRIVATE KEY", "stand-in-private-key"),
    )
    before = ops_side.put(SERVER, ops_side.encrypt(provided))
    sid = server(ops_world)
    for path, value, said in UNREACHABLE:
        refused = put_field(ops_world, sid, before, path, value, expect=422)
        assert refused["error"]["message"].startswith(said), path  # type: ignore[index]
        assert ops_side.head() == before, path
    plain = ops_side.as_box(SERVER)
    assert "stand-in-certificate-of-the-tests" in plain
    assert f"TELEGRAM_BOT_TOKEN: {SECRET}" in plain
    put_field(ops_world, sid, before, ["policies", "gc", "keep_releases"], 1)
    assert ops_side.head() != before


# --- 2. the lock ------------------------------------------------------------------


async def _held(url: str) -> tuple[object, object]:
    """The lock of primer-ops, taken by a connection of the test's own."""
    engine = make_engine(url)
    connection = await engine.connect()
    await connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
    return engine, connection


def test_probe_DM_211_a_busy_lock_answers_503_and_ready_stays(
    ops_world: World,
    ops_side: OpsSide,
    redis_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lock held elsewhere: twenty readings at once -- more than the pool
    of 15 -- each 503 ``primer-ops is busy`` after the wait, and ``/ready``
    answers 200 meanwhile, at once: no waiting request holds a connection. The
    pair: the lock let go, the reading is 200."""
    monkeypatch.setattr(router_module, "OPS_WAIT_S", 1.0)
    sid = server(ops_world)
    path = f"/api/v1/servers/{sid}/passport"

    async def scenario() -> tuple[list[tuple[int, str]], tuple[int, float], int]:
        engine, connection = await _held(ops_world.url)
        served = access_app(
            ops_world.url, redis_url, ops=(ops_side.url, ops_side.places)
        )
        core = inner_app(served).state.core
        headers = {**FRONTEND, **ops_world.people["super"].headers}
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=served),
                base_url="http://t",
                headers=headers,
            ) as client:

                async def ready() -> tuple[int, float]:
                    await asyncio.sleep(0.3)  # the twenty are waiting by now
                    started = time.monotonic()
                    answer = await client.get("/ready")
                    return answer.status_code, time.monotonic() - started

                waiting = asyncio.gather(*(client.get(path) for _ in range(20)))
                answers, readiness = await asyncio.wait_for(
                    asyncio.gather(waiting, ready()), 10
                )
                await connection.execute(  # type: ignore[attr-defined]
                    text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY}
                )
                after = await client.get(path)
        finally:
            await connection.close()  # type: ignore[attr-defined]
            await engine.dispose()  # type: ignore[attr-defined]
            await core.engine.dispose()
            await core.redis.aclose()
        return (
            [(a.status_code, a.json()["error"]["message"]) for a in answers],
            readiness,
            after.status_code,
        )

    answers, (ready_status, ready_s), after = asyncio.run(scenario())
    assert answers == [(503, "primer-ops is busy")] * 20
    assert ready_status == 200 and ready_s < 2.0, ready_s
    assert after == 200


def test_a_lock_whose_session_ends_is_free(migrated_db: str) -> None:
    """Postgres frees the advisory lock of a session that ends -- the ground
    of ``invalidate()`` on a failed unlock (the reviewer's ``[uncertain]``)."""

    async def scenario() -> tuple[bool, bool]:
        engine, connection = await _held(migrated_db)
        other = make_engine(migrated_db)
        try:
            async with other.connect() as probe:
                taken = await probe.scalar(
                    text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}
                )
            await connection.invalidate()  # type: ignore[attr-defined]
            await connection.close()  # type: ignore[attr-defined]
            async with other.connect() as probe:
                free = await probe.scalar(
                    text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}
                )
                await probe.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY}
                )
        finally:
            await engine.dispose()  # type: ignore[attr-defined]
            await other.dispose()
        return bool(taken), bool(free)

    assert asyncio.run(scenario()) == (False, True)


def test_a_failed_unlock_leaves_no_lock_in_the_pool(
    ops_world: World, ops_side: OpsSide, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unlock fails: its connection is invalidated, the lock is free for
    another session at once -- none of the pool's connections keeps it."""
    monkeypatch.setattr(router_module, "UNLOCK", text("SELECT no_such_function(:k)"))
    sid = server(ops_world)
    read(ops_world, sid)

    async def free() -> bool:
        other = make_engine(ops_world.url)
        try:
            async with other.connect() as probe:
                got = await probe.scalar(
                    text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}
                )
                await probe.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY}
                )
        finally:
            await other.dispose()
        return bool(got)

    assert asyncio.run(free())


def test_an_edit_takes_the_project_again_before_the_push(
    ops_world: World, ops_side: OpsSide, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The project is archived after the rule let its transaction go: the
    edit, taken again before the push, is refused 409 and primer-ops is as it
    was; nothing is audited. The pair: the same edit in a live project goes."""
    sid = server(ops_world)
    base = ops_side.head()
    put_field(ops_world, sid, base, ["domains", "api"], "a.example")  # the pair
    base = ops_side.head()
    monkeypatch.setattr(router_module, "checked", _archiving(ops_world))
    refused = put_field(
        ops_world, sid, base, ["domains", "api"], "b.example", expect=409
    )
    assert "archived" in refused["error"]["message"]  # type: ignore[index]
    assert ops_side.head() == base
    assert (
        query_scalar(
            ops_world.url, "SELECT count(*) FROM audit WHERE action = 'passport.edit'"
        )
        == 1
    )


def test_an_edit_of_a_server_detached_meanwhile_is_not_found(
    ops_world: World, ops_side: OpsSide, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server detached while its passport is edited: taken again before
    the push, it is not found -- primer-ops as it was."""
    sid = server(ops_world)
    base = ops_side.head()
    real = passport_module.checked
    calls: list[bool] = []

    def detaching(text_: bytes) -> object:
        if calls:
            _in_thread(execute, ops_world.url, DETACH.format(server=sid))
        calls.append(True)
        return real(text_)

    monkeypatch.setattr(router_module, "checked", detaching)
    put_field(ops_world, sid, base, ["domains", "api"], "b.example", expect=404)
    assert ops_side.head() == base


def _in_thread(call: Callable[[str, str], None], url: str, statement: str) -> None:
    with ThreadPoolExecutor(1) as pool:
        pool.submit(call, url, statement).result()


def _archiving(world: World) -> object:
    """``checked`` that archives the project at its second call -- the
    passport after the edit, before the push."""
    real = passport_module.checked
    calls: list[bool] = []

    def checked(text_: bytes) -> object:
        if calls:  # inside the app's loop: the helper's own loop in a thread
            _in_thread(execute, world.url, ARCHIVE.format(project=world.projects["a"]))
        calls.append(True)
        return real(text_)

    return checked


def test_apply_takes_the_project_again_before_it_queues(
    ops_world: World, ops_side: OpsSide, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The project archived while "apply" read primer-ops: refused in the
    transaction that would queue -- no command. A permission taken meanwhile
    -- 403. The pair: a live project with the permission queues."""
    sid = server(ops_world)
    world = ops_world
    world.person("pass_a", 7000000777)
    world.join("pass_a", world.invite("super", "a", ["passport"]))

    real = router_module._seen

    async def revoking(repo: OpsRepo, name: str) -> object:
        await asyncio.to_thread(
            execute,
            world.url,
            "UPDATE memberships SET permissions = '{}'::text[] WHERE user_id = "
            f"'{world.people['pass_a'].id}'",
        )
        return await real(repo, name)

    monkeypatch.setattr(router_module, "_seen", revoking)
    apply(world, sid, "pass_a", expect=403)
    monkeypatch.setattr(router_module, "_seen", real)

    async def archiving(repo: OpsRepo, name: str) -> object:
        await asyncio.to_thread(
            execute,
            world.url,
            ARCHIVE.format(project=world.projects["a"]),
        )
        return await real(repo, name)

    monkeypatch.setattr(router_module, "_seen", archiving)
    refused = apply(world, sid, expect=409)
    assert "archived" in refused["error"]["message"]  # type: ignore[index]
    assert query_scalar(world.url, "SELECT count(*) FROM commands") == 0
    monkeypatch.setattr(router_module, "_seen", real)
    execute(
        world.url,
        UNARCHIVE.format(project=world.projects["a"]),
    )
    apply(world, sid)
    assert query_scalar(world.url, "SELECT count(*) FROM commands") == 1


# --- 3. the decryption off the file system --------------------------------------------


def _memfds() -> list[str]:
    """The ``memfd`` of a passport the process still has open."""
    found: list[str] = []
    for entry in Path("/proc/self/fd").iterdir():
        with suppress(OSError):
            if "memfd:passport" in os.readlink(entry):
                found.append(entry.name)
    return found


def test_probe_DM_211_scratch_is_in_memory(
    ops_world: World, ops_side: OpsSide, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reading, an edit of a secret and an edit the machine's loader
    refuses: the loader reads every passport from ``/proc/self/fd/...`` (a
    ``memfd``), never a file of ``scratch``; while it reads, no file of
    ``scratch`` holds a secret in the clear; after, the ``memfd`` is closed."""
    seen: list[str] = []
    clear: list[str] = []
    scratch = ops_side.places.home / "scratch"
    real = getattr(passport_module, "load_passport")  # noqa: B009

    def loader(file: Path) -> object:
        seen.append(str(file))
        for each in scratch.glob("*") if scratch.exists() else []:
            if SECRET.encode() in each.read_bytes():
                clear.append(each.name)
        return real(file)

    monkeypatch.setattr(passport_module, "load_passport", loader)
    sid = server(ops_world)
    read(ops_world, sid)
    put_secret(
        ops_world,
        sid,
        ops_side.head(),
        "replaced-telegram-token-0009",
        stack="comms",
        key="TELEGRAM_BOT_TOKEN",
    )
    put_secret(
        ops_world, sid, ops_side.head(), "tiny", stack="comms", key="X", expect=422
    )
    assert seen and all(path.startswith("/proc/self/fd/") for path in seen), seen
    assert clear == []
    assert _memfds() == []  # each closed after its loader
    assert list(scratch.glob("*")) == []


# --- 4. the processes ----------------------------------------------------------------


def _live(pgid: int) -> list[int]:
    """The processes of a group that are not zombies."""
    found: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        fields = stat.rsplit(")", 1)[1].split()
        if int(fields[2]) == pgid and fields[0] != "Z":
            found.append(int(entry.name))
    return found


@pytest.fixture
def leader(tmp_path: Path) -> Iterator[tuple[list[str], Path]]:
    """A command that leaves a child behind in its group, and the file it
    names its group in; whatever a test leaves alive is killed after."""
    file = tmp_path / "pgid"
    argv = ["sh", "-c", f"echo $$ > {file}; sleep 30 & sleep 30"]
    yield argv, file
    if file.exists() and file.read_text().strip():
        with suppress(ProcessLookupError):
            os.killpg(int(file.read_text()), signal.SIGKILL)


def _pgid(file: Path) -> int:
    for _ in range(50):
        if file.exists() and file.read_text().strip():
            return int(file.read_text())
        time.sleep(0.02)
    raise AssertionError("the command never named its group")


def test_probe_DM_211_no_child_outlives_its_command(
    leader: tuple[list[str], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timeout and a cancellation leave no process of the command's group
    alive; a group already gone at the kill is no error -- the timeout says
    ``timed out``, not ``ProcessLookupError``."""
    argv, file = leader
    env = {"PATH": os.environ["PATH"]}

    with pytest.raises(OpsCommandError) as caught:
        asyncio.run(run(argv, what="sh", env=env, timeout_s=0.5))
    assert (caught.value.code, caught.value.reason) == (None, "timeout")
    time.sleep(0.1)
    assert _live(_pgid(file)) == []

    file.write_text("")

    async def cancelled() -> None:
        task = asyncio.create_task(run(argv, what="sh", env=env, timeout_s=30))
        await asyncio.sleep(0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancelled())
    time.sleep(0.1)
    assert _live(_pgid(file)) == []

    file.write_text("")
    killpg = os.killpg

    def gone(pgid: int, sig: int) -> None:
        killpg(pgid, sig)  # the group is killed -- and said to be gone already
        raise ProcessLookupError(pgid)

    monkeypatch.setattr("app.ops.run.os.killpg", gone)
    with pytest.raises(OpsCommandError, match="timed out"):
        asyncio.run(run(argv, what="sh", env=env, timeout_s=0.5))


# --- 5. the class of a refusal --------------------------------------------------------

# What the tools say of each class, written out (OpenSSH 9.6, git, the
# ProxyCommand app.ops.connect; measured on the gate where it could be).
SAID = {
    "host-key": (
        b"No ED25519 host key is known for [ssh.github.com]:443 and you have "
        b"requested strict checking.\r\nHost key verification failed.\r\n"
        b"fatal: Could not read from remote repository.\n"
    ),
    "publickey": (
        b"git@ssh.github.com: Permission denied (publickey).\r\n"
        b"fatal: Could not read from remote repository.\n"
    ),
    "dns": (
        b"connect: [Errno -2] Name or service not known\r\n"
        b"Connection closed by UNKNOWN port 65535\r\nfatal: Could not read\n"
    ),
    "network": (
        b"connect: [Errno 111] Connection refused\r\n"
        b"Connection closed by UNKNOWN port 65535\r\nfatal: Could not read\n"
    ),
    "other": b"error: unknown option `wat'\n",
}


@pytest.mark.parametrize("reason", sorted(SAID))
def test_a_refusal_is_read_by_its_class(reason: str) -> None:
    assert reason_of(SAID[reason]) == reason


def test_probe_DM_211_a_refusal_of_git_says_its_class_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A live ``git`` through the Panel's ssh and ``ProxyCommand``: a refused
    connection is ``network``, a name that does not resolve is ``dns``; what
    they said is in no error and no log line -- the 503 names the class only.
    The pair: a stderr marker of a failing command stays out too."""
    key = tmp_path / "key"
    key.write_text("not a key\n")
    key.chmod(0o600)
    os.environ.setdefault("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    found: dict[str, OpsCommandError] = {}
    for reason, address in (
        ("network", "ssh://git@127.0.0.1:1/o/r.git"),
        ("dns", "ssh://git@nonexistent.invalid:443/o/r.git"),
    ):
        places = OpsPlaces(  # a clone of its own: its remote is its address
            home=tmp_path / reason, write_key=key, age_key=tmp_path / "age"
        )
        with pytest.raises(OpsCommandError) as caught:
            asyncio.run(OpsRepo(address, places).head())
        assert caught.value.reason == reason, address
        found[reason] = caught.value
    marker = "MARKER-of-stderr-DM211"
    with pytest.raises(OpsCommandError) as caught:
        asyncio.run(
            run(
                ["sh", "-c", f"echo {marker} >&2; exit 3"],
                what="sh",
                env={"PATH": os.environ["PATH"]},
                timeout_s=5,
            )
        )
    found["other"] = caught.value
    for error in found.values():
        answer = _unreachable(error)
        assert answer.message == f"primer-ops cannot be reached now ({error.reason})"
        for said in ("Connection refused", "Name or service", marker):
            assert said not in str(error) and said not in answer.message
    for record in caplog.records:
        for said in ("Connection refused", "Name or service", marker):
            assert said not in record.getMessage()
            assert said not in str(record.__dict__)
    reasons = [r.__dict__.get("ctx", {}).get("reason") for r in caplog.records]
    assert reasons == ["network", "dns", "other"]
