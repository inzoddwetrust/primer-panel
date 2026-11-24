"""Probe of DM-148: no global singletons in the Panel's code.

The owner's decision of 24.11: the blank's form -- an application factory,
no global singletons; the core taken from velo and aivis is translated, not
copied with its module-level engine, sessions, Redis client and settings.
The fence is ``tests/singletons.py``; this probe runs it on the tree and, as
its pair, on a copy of the tree with one planted.
"""

import shutil
from pathlib import Path

from tests.singletons import AREA, BACKEND, findings, selftest


def test_probe_DM_148_no_global_singletons(tmp_path: Path) -> None:
    found, modules = findings(BACKEND)
    assert found == []
    assert modules >= len(AREA)

    # The pair: the same scan of a copy with the velo form planted finds it.
    for part in AREA:
        shutil.copytree(BACKEND / part, tmp_path / part)
    planted = tmp_path / "app" / "core" / "database.py"
    planted.write_text(
        planted.read_text(encoding="utf-8")
        + "\n_engine = create_async_engine('postgresql+asyncpg://x')\n",
        encoding="utf-8",
    )
    found, _ = findings(tmp_path)
    assert found == [
        "app/core/database.py:"
        f"{planted.read_text(encoding='utf-8').count(chr(10))}: "
        "create_async_engine() at import time"
    ]

    # Every form of the class, each planted on its own, is found.
    assert selftest() == []
