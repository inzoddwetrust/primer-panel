"""Probes of DM-212, the review of the Panel (PRIMER-PANEL-REVIEW-0001): the
sign-in and the public routes -- the limits, the log, the first sign-in, the
form of a run id, comms' settings, a damaged session, the dependencies and
``/health``'s seams."""
# ruff: noqa: S608 -- the tokens and the SQL are the tests' own

import asyncio
import hashlib
import json
import logging
import logging.config
import re
import tomllib
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pridem.stacks.schema import Seam, load_primer_yaml
from pydantic import ValidationError
from redis import Redis

from app.config import Settings
from app.seams import PROVIDES, TAKES, requires_satisfied
from tests.comms_fake import STATE, FakeComms
from tests.conftest import API_HOST, FRONTEND, SUPERADMIN_ID, query_scalar
from tests.failing import inner_app
from tests.fake_box import FakeBox, header_line, log_line
from tests.people import World, access_app
from tests.signin import RETURN, START, SignIn, outcome, signin_app
from tests.test_agent import batch, registered
from tests.test_settings import GOOD

SESSIONS = "panel:session:"
BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

# --- 1. the limits ------------------------------------------------------------------

PROXY = ("172.18.0.5", 40000)  # the machine's nginx: a private peer
LIMITS = {  # route -> its limit a minute, written out
    "start": 20,
    "return": 20,
    "register": 10,
    "accept": 10,
}


@pytest.fixture
def behind_proxy(
    migrated_db: str, redis_url: str, clean_redis: Redis
) -> Iterator[TestClient]:
    """The Panel as its nginx reaches it: the peer is private, the client's
    address comes in ``X-Real-IP``."""
    with TestClient(
        access_app(migrated_db, redis_url), client=PROXY, base_url=f"https://{API_HOST}"
    ) as client:
        yield client


def _call(client: TestClient, route: str, source: str) -> httpx.Response:
    headers = {"X-Real-IP": source, **FRONTEND}
    if route == "start":
        answer = client.get(START, headers=headers, follow_redirects=False)
    elif route == "return":
        params = {"state": "s", "code": "c"}
        answer = client.get(
            RETURN, params=params, headers=headers, follow_redirects=False
        )
    elif route == "register":
        answer = client.post("/agent/v1/register", content=b"{}", headers=headers)
    else:
        answer = client.post(
            "/api/v1/invites/accept", json={"token": "x"}, headers=headers
        )
    assert isinstance(answer, httpx.Response)
    return answer


def _limited(route: str, answer: httpx.Response) -> bool:
    if route in ("start", "return"):
        return answer.status_code == 302 and answer.headers["location"].endswith(
            "#reason=try_later"
        )
    return answer.status_code == 429 and answer.headers.get("retry-after") is not None


@pytest.mark.parametrize("route", sorted(LIMITS))
def test_probe_DM_212_public_routes_answer_their_limit(
    behind_proxy: TestClient, route: str
) -> None:
    """A public address: the limit's requests are answered as the route
    answers them, the next one is refused -- by the sign-in's ``try_later``
    on the browser's two routes, by 429 with ``Retry-After`` on the API's.
    An IPv6 address counts by its ``/64``. The pairs: another ``/64`` has its
    own count; a private address is never counted."""
    limit = LIMITS[route]
    for _ in range(limit):
        assert not _limited(route, _call(behind_proxy, route, "8.8.8.8"))
    refused = _call(behind_proxy, route, "8.8.8.8")
    assert _limited(route, refused), (refused.status_code, refused.headers)
    if route in ("start", "return"):
        assert refused.status_code == 302  # a page of the sign-in, never a 429

    for host in range(limit):  # one /64, many addresses
        _call(behind_proxy, route, f"2a00:1450:4001:81a::{host + 1:x}")
    assert _limited(route, _call(behind_proxy, route, "2a00:1450:4001:81a::ffff"))
    assert not _limited(route, _call(behind_proxy, route, "2a00:1450:4001:81b::1"))

    for _ in range(limit + 2):
        assert not _limited(route, _call(behind_proxy, route, "10.0.0.9"))


# --- 2. the log ---------------------------------------------------------------------

ACCESS = '%s - "%s %s HTTP/%s" %d'  # uvicorn's own line of the access log


def test_probe_DM_212_no_token_in_the_log(
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server's own ``logging.json``: a line of the access log with an
    invite's token, a sign-in's code and state keeps none of their values,
    neither in what the formatter writes nor in the record a handler gets
    (``caplog`` on the access log). The pair: another parameter stays."""
    monkeypatch.setenv("PRIMER_RELEASE", "v0.0.0-probe")
    root = logging.getLogger()
    kept = list(root.handlers)
    access = logging.getLogger("uvicorn.access")
    logging.config.dictConfig(json.loads((BACKEND / "logging.json").read_text()))
    access.addHandler(caplog.handler)
    try:
        for path in (
            "/auth/telegram/start?invite=INVITE-TOKEN-OF-THE-PROBE",
            "/auth/telegram/return?code=CODE-OF-THE-PROBE&state=STATE-OF-THE-PROBE",
            "/api/v1/servers?page=2",
        ):
            access.info(ACCESS, "8.8.8.8:1", "GET", path, "1.1", 302)
    finally:
        access.removeHandler(caplog.handler)
        for logger in (access, logging.getLogger("uvicorn")):
            logger.handlers.clear()
            logger.filters.clear()
        root.handlers[:] = kept
    written = capsys.readouterr().out
    seen = " ".join(record.getMessage() for record in caplog.records)
    for secret in ("INVITE-TOKEN", "CODE-OF-THE", "STATE-OF-THE"):
        assert secret not in written and secret not in seen, secret
    assert "invite=<hidden>" in written and "state=<hidden>" in seen
    assert "page=2" in written and "page=2" in seen


# --- 3. the first sign-in -----------------------------------------------------------


def test_probe_DM_212_two_first_sign_ins_one_user(
    migrated_db: str, redis_url: str, clean_redis: Redis
) -> None:
    """Two first sign-ins of one Telegram id at once, five rounds, a new id
    each: both returns are signed in, one row of ``users``."""

    async def round_(superadmin: int) -> list[dict[str, str]]:
        fake = FakeComms()
        fake.person(superadmin)
        served = signin_app(migrated_db, redis_url, fake, superadmin)
        clients = [
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=served),
                base_url=f"https://{API_HOST}",
                headers=FRONTEND,
            )
            for _ in range(2)
        ]
        try:
            for client in clients:
                await client.get(START)
            answers = await asyncio.gather(
                *(
                    client.get(RETURN, params={"state": STATE, "code": "c"})
                    for client in clients
                )
            )
        finally:
            for client in clients:
                await client.aclose()
            core = inner_app(served).state.core
            await core.engine.dispose()
            await core.redis.aclose()
            if core.comms is not None:
                await core.comms.aclose()
        return [outcome(answer) for answer in answers]

    for number in range(5):
        superadmin = 7000005000 + number
        places = asyncio.run(round_(superadmin))
        assert places == [{"signed_in": "yes"}] * 2, places
        assert (
            query_scalar(
                migrated_db,
                f"SELECT count(*) FROM users WHERE telegram_id = {superadmin}",
            )
            == 1
        )


# --- 4. the form of a run id --------------------------------------------------------

# Run ids, written out: the machine's form, and others.
GOOD_RUN = "2026-11-26T12:00:00Z-ab12"
OTHER_RUNS = [
    "2026-11-26T12:00:00Z-ab12-and-a-tail-past-the-column",
    "2026-11-26T12:00:00Z-ab12x",
    "2026-11-26T12:00:00Z-AB12",
    "x",
]


def test_probe_DM_212_run_id_of_another_form_is_422(world: World) -> None:
    """A signed box sends lines and a verdict under a run id of another form:
    422 on both routes by the form of the path -- before the lines are kept
    under a key too long for its column (a batch of log lines alone has no
    header to tell the run) -- nothing kept. The pair: the machine's form is
    accepted."""
    box: FakeBox = registered(world)
    for run_id in OTHER_RUNS:
        lines = box.send("POST", f"/runs/{run_id}/events", batch([log_line(1)]))
        verdict = box.send("POST", f"/runs/{run_id}/verdict", {})
        for answer in (lines, verdict):
            assert answer.status_code == 422, (run_id, answer.text)
            assert "path" in answer.json()["error"]["message"], answer.text
    assert query_scalar(world.url, "SELECT count(*) FROM runs") == 0
    good = box.send("POST", f"/runs/{GOOD_RUN}/events", batch([header_line(GOOD_RUN)]))
    assert good.status_code == 200, good.text


# --- 5. comms' settings -------------------------------------------------------------


def test_probe_DM_212_half_of_comms_stops_the_start() -> None:
    """One of comms' two settings without the other refuses the start, by
    both names. The pairs: both, or neither, start."""
    comms = {
        "COMMS_API_URL": "http://comms-comms-app:8000",
        "COMMS_SERVICE_TOKEN": "invented-service-token-0002",
    }
    for one in comms:
        with pytest.raises(ValidationError) as refused:
            Settings.model_validate({**GOOD, one: comms[one]})
        said = str(refused.value)
        assert "COMMS_API_URL" in said and "COMMS_SERVICE_TOKEN" in said
    assert Settings.model_validate({**GOOD, **comms}).comms_connected
    assert not Settings.model_validate(GOOD).comms_connected


# --- 6. a damaged session -----------------------------------------------------------


def test_probe_DM_212_a_damaged_session_is_401(signin: SignIn, redis_url: str) -> None:
    """A session Redis holds damaged -- not JSON, a key missing, a user id
    that is no UUID -- is no session: 401, not 500. The pair: the session as
    the sign-in kept it is the person."""
    assert signin.login("b", SUPERADMIN_ID) == {"signed_in": "yes"}
    token = signin.token("b")
    assert token is not None
    key = SESSIONS + hashlib.sha256(token.encode()).hexdigest()
    redis = Redis.from_url(redis_url)
    try:
        kept = redis.get(key)
        assert isinstance(kept, bytes)
        user_id = json.loads(kept)["user_id"]
        for damaged in (
            b"{not json",
            json.dumps({"user_id": user_id, "epoch": 0}).encode(),
            json.dumps({"user_id": "no-uuid", "telegram_id": 1, "epoch": 0}).encode(),
        ):
            redis.set(key, damaged)
            answer = signin.me("b")
            assert answer.status_code == 401, (damaged, answer.text)
        redis.set(key, kept)
        assert signin.me("b").status_code == 200
    finally:
        redis.close()


# --- 7, 8. README and the dependencies ----------------------------------------------


def test_the_readme_says_the_machine_and_the_limits() -> None:
    """README, written out where it was false (DM-212): the pinned machine, the
    page ``/`` (the fleet) and ``/me``, the limits of R1 of the gate. Changed
    by DM-218: the pinned machine is v0.1.12."""
    text = (REPO / "README.md").read_text()
    assert "release v0.1.12" in text and "release v0.1.10" not in text
    assert "`/me` -- the person of" in text
    for said in ("20 each", "10 each", "`/64`", "try_later", "429"):
        assert said in text, said


def test_the_dependencies_are_declared_once() -> None:
    """``packaging`` is declared; ``httpx`` has one range (DM-212)."""
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text())["project"]
    every = [*project["dependencies"], *project["optional-dependencies"]["dev"]]
    names = [re.split(r"[<>=\[ @]", entry, maxsplit=1)[0] for entry in every]
    assert names.count("httpx") == 1 and names.count("packaging") == 1
    for lock in ("requirements.lock", "requirements-dev.lock"):
        assert "packaging==26.3" in (BACKEND / lock).read_text()


# --- 9. /health's seams -------------------------------------------------------------


def test_probe_DM_212_health_provides_what_primer_yaml_does(
    world: World,
) -> None:
    """``/health.seams.provides`` is the list ``provides`` of the
    ``primer.yaml`` of the same commit -- written out here, and read by the
    pinned machine's loader -- and ``requires_satisfied`` is true by the
    seams the Panel takes, none. The machine's ``seams_verify`` reads these
    two (``provide-not-live``)."""
    product = load_primer_yaml(REPO / "primer.yaml")
    declared = sorted(product.provides)
    taken = sorted(k for k, v in product.env.items() if isinstance(v, Seam))
    assert declared == ["PRODUCT_STORAGE_ADDRESS"]
    # Changed by DM-160, by the dispatcher's word on its gate: the Panel takes
    # comms' two seams -- requires_satisfied is true once both have values
    assert sorted(PROVIDES) == declared
    assert sorted(TAKES) == taken == ["COMMS_API_URL", "COMMS_SERVICE_TOKEN"]
    seams = world.client.get("/health").json()["seams"]
    assert seams == {"provides": declared, "requires_satisfied": False}


def test_requires_satisfied_is_counted() -> None:
    """A seam taken and empty is not satisfied; given, it is."""
    assert requires_satisfied({}) is False
    assert requires_satisfied({"COMMS_API_URL": "http://comms-comms-app:8000"}) is False
    given = {"COMMS_API_URL": "http://comms-comms-app:8000", "COMMS_SERVICE_TOKEN": "t"}
    assert requires_satisfied(given) is True
