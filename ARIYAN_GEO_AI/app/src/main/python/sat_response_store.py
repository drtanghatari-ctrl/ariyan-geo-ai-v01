"""
sat_response_store.py -- save-once for Copernicus satellite answers (sat-v1, 2026-10-06)

The NDVI, Thermal, Optical and SAR checks ask the Copernicus Data Space
Sentinel Hub APIs for STATISTICS (small JSON answers), one POST per box.
While a sweep (Pass 1) or a refinement (Pass 2) runs, this module is
ARMED for that thread and every such answer is:

  * read back from disk if the identical request was answered before
    (same URL, same request body byte-for-byte; SHA-256 re-checked), or
  * fetched live as before and then saved, exactly as received.

WHY "THE SAME DAY". Each check asks for "the last N days up to now", and
"now" used to carry hours/minutes/seconds, so no two requests were ever
identical and nothing could be reused. While armed, anchor_now() returns
the START of the current UTC day instead, so every check made on the same
UTC day sends the identical window and is answered once. A day later the
window moves forward one day and fresh imagery is fetched -- the honest
behaviour for data that keeps arriving. Cost: at most the last <24 h of
acquisitions are left out of a 90/180-day window (Sentinel revisit is ~5
days). When NOT armed (single investigations from the main screen) the
old to-the-second behaviour is unchanged.

Never cached: OAuth token calls, non-POST calls, failed calls (they raise
before anything is saved). Saving never fails a check.

PROVENANCE. A served answer is recorded by provenance_ledger as a FILE
source (path + SHA-256), not as a new live call: take_hit() tells the
ledger's wrapper that the last call on this thread came from disk.

LAYOUT  <root>/sat_library/<KIND>/<key>.json   (raw answer bytes)
        <root>/sat_library/<KIND>/index.json   (sha256, url, bytes, saved_utc)
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

VERSION = "sat-v1"
_tl = threading.local()
_lock = threading.Lock()


def arm(root: str) -> None:
    _tl.store = {"root": root, "hits": 0, "saved": 0, "by_kind": {}}
    _tl.last_hit = None


def disarm() -> Optional[dict]:
    s = getattr(_tl, "store", None)
    _tl.store = None
    _tl.last_hit = None
    return None if s is None else summary(s)


def current() -> Optional[dict]:
    s = getattr(_tl, "store", None)
    return None if s is None else summary(s)


def summary(s: dict) -> dict:
    return {"reused": s["hits"], "saved": s["saved"], "by_kind": dict(s["by_kind"])}


def anchor_now() -> datetime:
    now = datetime.now(timezone.utc)
    if getattr(_tl, "store", None) is None:
        return now
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def take_hit() -> Optional[dict]:
    """Pop the 'served from disk' marker of this thread's last call."""
    h = getattr(_tl, "last_hit", None)
    _tl.last_hit = None
    return h


def _is_token_url(url: str) -> bool:
    low = (url or "").lower()
    return low.rstrip("/").endswith("/token") or "openid-connect" in low or "/oauth" in low


def request_key(url: str, body: bytes) -> str:
    return hashlib.sha256(url.encode() + b"\n" + body).hexdigest()[:32]


def _dir(root, kind):
    return os.path.join(root, "sat_library", kind)


def _index(root, kind) -> Dict[str, dict]:
    try:
        with open(os.path.join(_dir(root, kind), "index.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _bump(s, kind, field):
    k = s["by_kind"].setdefault(kind, {"reused": 0, "saved": 0})
    k[field] += 1


def through(kind: str, req, timeout, live: Callable) -> str:
    """Called by each source module's _urlopen_with_hard_deadline."""
    _tl.last_hit = None
    s = getattr(_tl, "store", None)
    url = getattr(req, "full_url", "") or ""
    body = getattr(req, "data", None)
    method = req.get_method() if hasattr(req, "get_method") else "GET"
    if (s is None or method != "POST" or not isinstance(body, (bytes, bytearray))
            or _is_token_url(url)):
        return live(req, timeout)
    root = s["root"]
    key = request_key(url, bytes(body))
    path = os.path.join(_dir(root, kind), key + ".json")
    meta = _index(root, kind).get(key)
    if meta is not None:
        try:
            with open(path, "rb") as f:
                data = f.read()
            if hashlib.sha256(data).hexdigest() == meta["sha256"]:
                s["hits"] += 1
                _bump(s, kind, "reused")
                _tl.last_hit = {"path": path, "name": f"{kind}/{key}.json",
                                "sha256": meta["sha256"], "saved_utc": meta.get("saved_utc")}
                return data.decode("utf-8")
        except (OSError, KeyError):
            pass                       # unreadable / tampered -> fetch again
    text = live(req, timeout)
    try:
        raw = text.encode("utf-8")
        os.makedirs(_dir(root, kind), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, path)
        with _lock:
            idx = _index(root, kind)
            idx[key] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                        "url": url.split("?")[0],
                        "saved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "store_version": VERSION}
            itmp = os.path.join(_dir(root, kind), "index.json.part")
            with open(itmp, "w") as f:
                json.dump(idx, f)
            os.replace(itmp, os.path.join(_dir(root, kind), "index.json"))
        s["saved"] += 1
        _bump(s, kind, "saved")
    except Exception:
        pass
    return text
