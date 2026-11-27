"""Probes of DM-160: the Panel on primer.team -- comms its dependency (the
options telegram and login, the seams of its sign-in, primer.lock, the
profile), the sample of the passport file, and ``/health`` honest about the
seams it takes.

What the live box does is the owner's steps (the report); what a test can
hold is the form: written out here, read through the pinned machine's
loaders."""

from pathlib import Path

from pridem.stacks.loader import load_yaml_mapping
from pridem.stacks.lock import check_lock, load_primer_lock
from pridem.stacks.passport import load_passport
from pridem.stacks.schema import Product, Seam, load_primer_yaml

from app.main import create_app
from tests.conftest import client_for, settings_for

REPO = Path(__file__).resolve().parents[2]

# comms v4.3.0, as primer.lock fixes it, written out
COMMS = ("4.3.0", "v4.3.0", "690fb8d9f635c81604f006d55e9f34ef3410b6a6")
# the chat baseline comms emits itself (its INTEGRATION.md section 3; the
# owner's word of 25.11), written out
CHAT_TYPES = ["msg.participant_message", "msg.support_message", "msg.thread_closed"]


def _product() -> Product:
    product = load_primer_yaml(REPO / "primer.yaml")
    assert isinstance(product, Product)
    return product


def test_probe_DM_160_comms_is_the_panel_s_dependency() -> None:
    """comms by its range and its profile, in the edition; both options and
    both required; the two seams of its sign-in from comms. The pair: the
    lock is in the range, at the tag's commit."""
    product = _product()
    comms = product.dependencies["comms"]
    assert comms.repo == "git@github.com:aivis-one/comms.git"
    assert comms.version == ">=4.3,<5"
    assert dict(comms.data) == {"profile": "comms-profile"}
    assert list(product.editions["core"].services) == ["comms"]
    assert list(product.options) == ["telegram", "login"]
    assert list(product.options_required) == ["telegram", "login"]
    seams = {k: v.from_ for k, v in product.env.items() if isinstance(v, Seam)}
    assert seams == {"COMMS_API_URL": "comms", "COMMS_SERVICE_TOKEN": "comms"}
    lock = load_primer_lock(REPO / "primer.lock")
    locked = lock.dependencies["comms"]
    assert (locked.version, locked.tag, locked.commit) == COMMS
    assert check_lock(product, lock) == []


def test_probe_DM_160_the_profile_has_the_chat_baseline() -> None:
    """Each of comms' three msg.* types, with a category that is not empty
    (comms refuses a profile without one; CI runs ``comms validate``)."""
    profile = load_yaml_mapping(REPO / "comms-profile" / "types.yaml")
    assert profile["version"] == 2
    types = profile["types"]
    assert isinstance(types, dict) and sorted(types) == CHAT_TYPES
    for name in CHAT_TYPES:
        record = types[name]
        assert isinstance(record, dict), name
        category = record.get("category")
        assert isinstance(category, str) and category, name


def test_probe_DM_160_the_passport_sample_has_no_value() -> None:
    """The sample of the passport file passes the pinned machine's loader as
    it stands; every asked value is a placeholder, never a value; the two
    keys are blocks that end with a newline (OpenSSH reads no key without
    one); the questions of the Panel and of comms are all there."""
    sample = REPO / "deploy" / "panel-passport.example.yaml"
    passport = load_passport(sample)
    assert passport.options == ["telegram", "login"]
    asked = {
        stack: {key: value.get_secret_value() for key, value in keys.items()}
        for stack, keys in passport.asked.items()
    }
    assert sorted(asked["primer-panel"]) == ["OPS_AGE_KEY", "OPS_WRITE_KEY"]
    assert sorted(asked["comms"]) == [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_LOGIN_CLIENT_SECRET",
    ]
    for keys in asked.values():
        for value in keys.values():
            assert value.startswith("<"), value
    text = sample.read_text()
    for key in ("OPS_WRITE_KEY", "OPS_AGE_KEY"):
        assert asked["primer-panel"][key].endswith("\n"), key
        assert f"    {key}: |\n" in text, key
    params = passport.params
    assert sorted(params["primer-panel"]) == ["OPS_REPO", "SUPERADMIN_TELEGRAM_ID"]
    assert params["comms"] == {"TELEGRAM_LINK_HOST": "t.me"}


def test_probe_DM_160_health_is_satisfied_with_both_seams(
    migrated_db: str, redis_url: str
) -> None:
    """With comms' two seams given, ``/health`` says the seams are satisfied;
    the machine's ``seams_verify`` reads it after the Panel's ``up``. The pair:
    without them -- not."""
    for comms, satisfied in ((True, True), (False, False)):
        app = create_app(settings_for(migrated_db, redis_url, comms=comms))
        for client in client_for(app):
            seams = client.get("/health").json()["seams"]
            assert seams["requires_satisfied"] is satisfied
