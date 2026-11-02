"""
Settings for the Windows app, kept in %APPDATA%\\ARIYAN_GEO_AI\\settings.json.

data_root: the folder that plays the role of the phone's offline_data
(database, backups, libraries). Default: %USERPROFILE%\\ARIYAN_GEO_AI\\offline_data,
the same layout as the phone. The user can choose another folder.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict


def _settings_path() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "ARIYAN_GEO_AI", "settings.json")


def default_data_root() -> str:
    return os.path.join(os.path.expanduser("~"), "ARIYAN_GEO_AI", "offline_data")


def load() -> Dict[str, Any]:
    try:
        with open(_settings_path(), encoding="utf-8") as f:
            s = json.load(f)
            return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def save(s: Dict[str, Any]) -> None:
    p = _settings_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, p)


def data_root() -> str:
    root = load().get("data_root") or default_data_root()
    os.makedirs(root, exist_ok=True)
    return root


def set_data_root(path: str) -> None:
    s = load()
    s["data_root"] = path
    save(s)
