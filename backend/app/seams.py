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
  rendered -- none now; comms' (DM-160) come here with its dependency.
"""

import os
from collections.abc import Mapping

PROVIDES: tuple[str, ...] = ("PRODUCT_STORAGE_ADDRESS",)
TAKES: tuple[str, ...] = ()


def requires_satisfied(environ: Mapping[str, str] | None = None) -> bool:
    """Every seam the Panel takes has its value."""
    found = os.environ if environ is None else environ
    return all(found.get(name) for name in TAKES)
