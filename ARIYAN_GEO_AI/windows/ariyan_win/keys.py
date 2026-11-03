"""
API keys on the Windows computer (win-w4a, 2026-11-03).

Stored in %APPDATA%\\ARIYAN_GEO_AI\\keys.dat, encrypted with Windows DPAPI
(CryptProtectData, "current user" scope): only the same Windows account on the
same computer can read them back. Values are never shown on screen, written
to logs or put in a project bundle. On a non-Windows system (only used for
development and tests) there is no DPAPI, so saving is refused unless the
caller explicitly allows an unprotected test store.

Keys: OPENTOPOGRAPHY_API_KEY (live DEM / DEM library), COPERNICUS_CLIENT_ID and
COPERNICUS_CLIENT_SECRET (satellite layers), the same three the phone keeps.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
from typing import Dict

NAMES = ("OPENTOPOGRAPHY_API_KEY", "COPERNICUS_CLIENT_ID", "COPERNICUS_CLIENT_SECRET")
_ENTROPY = b"ARIYAN GEO AI keys v1"


def _path() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "ARIYAN_GEO_AI", "keys.dat")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def protected() -> bool:
    return sys.platform == "win32"


def _protect(data: bytes) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    out = _Blob()
    if not crypt32.CryptProtectData(ctypes.byref(_blob(data)), "ARIYAN keys", ctypes.byref(_blob(_ENTROPY)),
                                    None, None, 0x1, ctypes.byref(out)):          # CRYPTPROTECT_UI_FORBIDDEN
        raise OSError("Windows could not encrypt the keys (DPAPI)")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def _unprotect(data: bytes) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    out = _Blob()
    if not crypt32.CryptUnprotectData(ctypes.byref(_blob(data)), None, ctypes.byref(_blob(_ENTROPY)),
                                      None, None, 0x1, ctypes.byref(out)):
        raise OSError("the saved keys belong to another Windows account or computer")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def load(allow_unprotected: bool = False) -> Dict[str, str]:
    try:
        raw = open(_path(), "rb").read()
    except OSError:
        return {}
    try:
        if raw.startswith(b"TEST:"):
            if not allow_unprotected:
                return {}
            data = base64.b64decode(raw[5:])
        else:
            if not protected():
                return {}
            data = _unprotect(raw)
        d = json.loads(data.decode("utf-8"))
        return {k: str(v) for k, v in d.items() if k in NAMES and v}
    except Exception:
        return {}


def save(values: Dict[str, str], allow_unprotected: bool = False) -> None:
    """values: only the names to change; an empty string clears that key."""
    cur = load(allow_unprotected)
    for k, v in values.items():
        if k not in NAMES:
            raise KeyError(k)
        v = (v or "").strip()
        if v:
            cur[k] = v
        else:
            cur.pop(k, None)
    data = json.dumps(cur).encode("utf-8")
    if protected():
        raw = _protect(data)
    elif allow_unprotected:
        raw = b"TEST:" + base64.b64encode(data)
    else:
        raise OSError("keys can only be saved on Windows (DPAPI protection)")
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, p)


def status(allow_unprotected: bool = False) -> Dict[str, bool]:
    k = load(allow_unprotected)
    return {"opentopography": bool(k.get("OPENTOPOGRAPHY_API_KEY")),
            "copernicus": bool(k.get("COPERNICUS_CLIENT_ID") and k.get("COPERNICUS_CLIENT_SECRET"))}


def copernicus(allow_unprotected: bool = False):
    k = load(allow_unprotected)
    return k.get("COPERNICUS_CLIENT_ID", ""), k.get("COPERNICUS_CLIENT_SECRET", "")


def opentopography(allow_unprotected: bool = False) -> str:
    return load(allow_unprotected).get("OPENTOPOGRAPHY_API_KEY", "")
