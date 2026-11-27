"""Probe of DM-203: the seam PRODUCT_STORAGE_ADDRESS is whole with comms.

comms v4.2.0 asks every product for the point of its object storage, whatever
the options (its ``requires``; section 15 of its ``INTEGRATION.md``): a
product without it is stopped by the machine's plan at ``seams_check``
(``half-seam``). The Panel's ``primer.yaml`` -- this repository's -- is taken
into a copy with comms as a dependency of its edition and the options
``telegram`` and ``login`` (the dependency itself is DM-160's), and the
pinned machine's own functions of ``seams_check`` read it with comms' seam,
written out here from ``aivis-one/comms@5a193eb`` (v4.2.0): no network in CI.
The value of the seam is the machine's, and it passes comms' rule of
``storage_address_problem`` (``app/core/channels.py`` there), written out too.

Changed by DM-160, by the dispatcher's word: comms is the Panel's dependency
now, in its edition, with both options -- the probe reads ``primer.yaml`` of
this repository as it is, no copy built; the pair (no ``provides``) is the
same file without its ``provides``. Every assertion stays as it was.
DM-160: the Panel takes two seams of comms and gives it its profile; the
literal carries what comms says of them -- its ``env`` of the three seams,
``accepts.profile`` and ``provides``, from the same source, ``5a193eb``.
"""

import re
from pathlib import Path

from pridem.stacks import seams
from pridem.stacks.schema import Product, Service, load_primer_yaml

PANEL = Path(__file__).resolve().parents[2] / "primer.yaml"

# comms v4.2.0, the part of its primer.yaml its seam with a product stands on,
# written out (aivis-one/comms@5a193eb).
COMMS = """schema: 1
name: comms
kind: service
options: [telegram, email, llm, login]
stacks:
  comms:
    compose: deploy/docker-compose.yml
    app: { service: comms-app, port: 8000, health: /health, ready: /ready }
env:
  COMMS_API_URL: { source: address }
  COMMS_SERVICE_TOKEN: { source: minted }
  PRODUCT_STORAGE_ADDRESS: { source: seam, from: product }
accepts:
  profile:
    validate: "comms validate --profile <dir>"
    env: TEMPLATES_DIR
    services: [comms-app, comms-worker, comms-consumer]
requires:
  - PRODUCT_STORAGE_ADDRESS
provides:
  - COMMS_API_URL
  - COMMS_SERVICE_TOKEN
report: { health: /health, ready: /ready, logs: json, junit: true }
"""

# comms' rule of the seam (storage_address_problem), written out: <host>:<port>,
# a lower-case name without a trailing dot, a port 1..65535 without a zero
# first, no scheme.
HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\Z")
PORT = re.compile(r"[1-9][0-9]{0,4}\Z")

VALUE = "panel-storage-panel-storage:9000"
ON = frozenset({"telegram", "login"})

# The Panel's whole ``provides``: its one entry, with the key above it (a key
# left with no entry is an explicit null, which the loader refuses).
PROVIDED = re.compile(
    r"^provides:[^\n]*\n(?:  #[^\n]*\n)*"
    r"  PRODUCT_STORAGE_ADDRESS: \{ stack: panel-storage, endpoint: files \}\n",
    re.MULTILINE,
)


def _copy(tmp: Path, text: str) -> tuple[Product, dict[str, Service]]:
    """``text`` -- the repository's primer.yaml as it is, or without its
    ``provides`` -- and comms' literal, through the machine's loader."""
    (tmp / "primer.yaml").write_text(text)
    (tmp / "comms.yaml").write_text(COMMS)
    product = load_primer_yaml(tmp / "primer.yaml")
    comms = load_primer_yaml(tmp / "comms.yaml")
    assert isinstance(product, Product) and isinstance(comms, Service)
    return product, {"comms": comms}


def _findings(product: Product, services: dict[str, Service]) -> dict[str, list[str]]:
    """Every function of the machine's ``seams_check`` (``steps/env.py``)."""
    edition = "core"
    return {
        "half_seams": seams.half_seams(product, services, edition, on=ON),
        "seams_under_option": seams.seams_under_option(
            product, services, edition, on=ON
        ),
        "network_collisions": seams.network_collisions(
            seams.pairs(product, services, edition, on=ON)
        ),
        "outside_edition": seams.outside_edition(product, edition, on=ON),
        "routes_on_co_located": seams.routes_on_co_located(
            product, services, edition, on=ON
        ),
        "unaccepted": seams.unaccepted(product, services, edition, on=ON),
    }


def _address(value: str) -> bool:
    host, sep, port = value.rpartition(":")
    return (
        bool(sep)
        and HOST.match(host) is not None
        and PORT.match(port) is not None
        and int(port) <= 65535
    )


def test_probe_DM_203_seam_is_whole_with_comms(tmp_path: Path) -> None:
    """No half seam, nothing else of ``seams_check``; one pair, the storage's
    point for comms; the value is ``host:port`` by comms' rule. The pair: the
    same copy without the Panel's ``provides`` is a half seam."""
    text = PANEL.read_text()
    product, services = _copy(tmp_path, text)
    assert {name: found for name, found in _findings(product, services).items()} == {
        "half_seams": [],
        "seams_under_option": [],
        "network_collisions": [],
        "outside_edition": [],
        "routes_on_co_located": [],
        "unaccepted": [],
    }
    [pair] = seams.pairs(product, services, "core", on=ON)
    assert (pair.provider, pair.endpoint, pair.consumer, pair.variable) == (
        "panel-storage",
        "files",
        "comms",
        "PRODUCT_STORAGE_ADDRESS",
    )
    value = seams.product_value(product, None, "PRODUCT_STORAGE_ADDRESS")  # type: ignore[arg-type]
    assert value == VALUE
    assert _address(value)

    without, count = PROVIDED.subn("", text)
    assert count == 1 and "\nprovides:" not in without
    half, services = _copy(tmp_path, without)
    assert seams.half_seams(half, services, "core", on=ON) == [
        "comms.PRODUCT_STORAGE_ADDRESS: the product does not provide it"
    ]


def test_comms_rule_of_the_address_is_written_out() -> None:
    """The literal of comms' rule refuses what comms refuses."""
    for value in (VALUE, "10.0.0.1:9000", "a:1", "a:65535"):
        assert _address(value), value
    for value in (
        "http://panel-storage-panel-storage:9000",
        "Panel-storage:9000",
        "panel-storage.:9000",
        "panel-storage:09000",
        "panel-storage:65536",
        "panel-storage",
    ):
        assert not _address(value), value


def test_the_storage_entry_keeps_its_files_and_stays_inside() -> None:
    """The entry ``panel-storage``: ``persistent`` (its volume survives
    ``destroy`` and ``reinstall``), its point ``files`` on its own service, its
    root secret minted at 40, and no route of the host to it."""
    product = load_primer_yaml(PANEL)
    assert isinstance(product, Product)
    entry = product.stacks["panel-storage"]
    assert entry.persistent is True
    assert {
        name: (p.service, p.port, p.scheme) for name, p in entry.expose.items()
    } == {"files": ("panel-storage", 9000, "http")}
    secret = product.env["RUSTFS_SECRET_KEY"]
    assert (secret.source, getattr(secret, "length", None)) == ("minted", 40)
    assert product.host is not None
    assert all(
        not route.to.startswith("panel-storage")
        for route in product.host.routes.values()
    )
