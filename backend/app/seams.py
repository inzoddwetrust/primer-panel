"""The seams of the Panel, as its ``/health`` says them (DM-212).

The deploy machine checks every seam of a box live (``seams_verify``): a name
a service ``requires`` of the product is among ``/health.seams.provides`` of
the product, else ``provide-not-live``; a stack that takes seams says
``requires_satisfied``. The image is one for every box and has no
``primer.yaml`` -- its build context is ``backend/`` -- so the lists live here,
and a test holds them equal to the ``primer.yaml`` of the same commit through
the pinned machine's loader (``tests/test_probe_dm_212.py``): a drift is red
in CI, before a build, never on a box.

- ``PROVIDES`` -- the names of ``provides`` of ``primer.yaml``;
- ``TAKES`` -- the keys of its ``env`` of ``source: seam``. ``requires_satisfied``
  is true when each of them has its value in the environment the machine
  rendered: comms' sign-in module, the address of its API and its token
  (DM-160). The machine renders them before the Panel's first ``up``.
"""

from collections.abc import Mapping

from app.config import Settings

PROVIDES: tuple[str, ...] = ("PRODUCT_STORAGE_ADDRESS",)
TAKES: tuple[str, ...] = ("COMMS_API_URL", "COMMS_SERVICE_TOKEN")


def requires_satisfied(given: Mapping[str, object]) -> bool:
    """Every seam the Panel takes has its value, by its variable's name."""
    return all(given.get(name) for name in TAKES)


def settings_values(settings: Settings) -> dict[str, object]:
    """The settings by the names of their variables (``OPS_REPO``,
    ``COMMS_API_URL``): what the machine rendered and the Panel took."""
    found: dict[str, object] = {}
    for name, field in type(settings).model_fields.items():
        alias = field.validation_alias
        if isinstance(alias, str):
            found[alias] = getattr(settings, name)
    return found
