"""
Where the ARIYAN Python core lives, so `import mission_control` etc. load the
SAME .py files the phone runs (the provenance ledger hashes those files, so they
must stay plain .py sources, never frozen into the .exe).

* Installed (.exe built by PyInstaller): <install dir>/_internal/ariyan_core
* From source: <repo>/ARIYAN_GEO_AI/app/src/main/python
"""
from __future__ import annotations

import os
import sys


def core_dir() -> str:
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return os.path.join(frozen, "ariyan_core")
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "app", "src", "main", "python"))


def install() -> str:
    d = core_dir()
    if not os.path.isfile(os.path.join(d, "mission_control.py")):
        raise RuntimeError("ARIYAN core not found at " + d)
    if d not in sys.path:
        sys.path.insert(0, d)
    return d


def core_modules() -> list:
    """Every core module name (used by the self-test to import them all)."""
    d = core_dir()
    return sorted(n[:-3] for n in os.listdir(d) if n.endswith(".py") and not n.startswith("_"))
