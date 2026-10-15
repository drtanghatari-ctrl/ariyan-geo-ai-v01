"""
worldcover_store.py -- save-once for ESA WorldCover land-cover reads
(lc-auto-v1, 2026-10-15)

land_cover_flags reads WorldCover 2021 tiles (public Cloud-Optimised
GeoTIFFs, ~99 MB each) with small HTTP Range requests: the header once,
then only the image blocks a candidate window touches. Before lc-auto-v1
those bytes were held in memory for one call only, so the next job in the
same 3 x 3 degree tile downloaded the same blocks again. That broke the
user's save-once rule (2026-10-06: every live-fetched tile/window is saved
into the offline library and fetched only once).

saved_range_get(root) returns an http_get(url, start, end) for
WorldCoverHttpTile that:

  * serves a byte range from disk if it was saved before AND its SHA-256
    still matches the index (a damaged file is re-fetched, never trusted);
  * otherwise reads it live (land_cover_flags._http_range, unchanged) and
    saves the exact bytes received.

The ranges WorldCoverHttpTile asks for are deterministic (the header range,
then the offset/byte-count of each block from the file's own tile table),
so the same block is always the same request. Saving never fails a read: a
full disk or a write error only means the range is fetched live next time.

LAYOUT  <root>/worldcover_library/<TILE>/<start>-<end>.bin   raw bytes
        <root>/worldcover_library/<TILE>/index.json          sha256, bytes,
                                                              url, saved_utc
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

VERSION = "wc-store-v1"
DIRNAME = "worldcover_library"

_lock = threading.Lock()
_TILE_RE = re.compile(r"_([NS]\d{2}[EW]\d{3})_Map\.tif$")


def tile_key(url: str) -> str:
    """'N36E045' from a WorldCover URL; any other URL gets a stable hash
    folder so nothing from two different files is ever mixed."""
    m = _TILE_RE.search(url)
    if m:
        return m.group(1)
    return "url_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _dir(root: str, url: str) -> str:
    return os.path.join(root, DIRNAME, tile_key(url))


def _read_index(d: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(d, "index.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _atomic_write(path: str, data: bytes) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_saved(root: str, url: str, start: int, end: int) -> Optional[bytes]:
    """The saved bytes for this exact range, or None if absent or damaged."""
    d = _dir(root, url)
    name = f"{int(start)}-{int(end)}.bin"
    entry = _read_index(d).get(name)
    if not isinstance(entry, dict):
        return None
    try:
        with open(os.path.join(d, name), "rb") as f:
            data = f.read()
    except OSError:
        return None
    if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
        return None
    return data


def save(root: str, url: str, start: int, end: int, data: bytes) -> bool:
    """Saves the bytes and their index entry. Returns False (never raises)
    if anything goes wrong."""
    try:
        d = _dir(root, url)
        name = f"{int(start)}-{int(end)}.bin"
        with _lock:
            os.makedirs(d, exist_ok=True)
            _atomic_write(os.path.join(d, name), data)
            idx = _read_index(d)
            idx[name] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "url": url,
                "saved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "store_version": VERSION,
            }
            _atomic_write(os.path.join(d, "index.json"),
                          json.dumps(idx, sort_keys=True).encode("utf-8"))
        return True
    except Exception:
        return False


def saved_range_get(
    root: str,
    live: Optional[Callable[[str, int, int], bytes]] = None,
    stats: Optional[Dict[str, int]] = None,
) -> Callable[[str, int, int], bytes]:
    """http_get for WorldCoverHttpTile: disk first, live + save otherwise.
    `stats` (if given) counts "reused", "saved", "live_not_saved"."""
    if live is None:
        import land_cover_flags   # late import: land_cover_flags imports us
        live = land_cover_flags._http_range
    counts = stats if stats is not None else {}
    for k in ("reused", "saved", "live_not_saved"):
        counts.setdefault(k, 0)

    def get(url: str, start: int, end: int) -> bytes:
        data = load_saved(root, url, start, end)
        if data is not None:
            counts["reused"] += 1
            return data
        data = live(url, start, end)          # raises exactly as before
        if save(root, url, start, end, data):
            counts["saved"] += 1
        else:
            counts["live_not_saved"] += 1
        return data

    return get


def library_summary(root: str) -> Dict[str, Any]:
    """Tiles and bytes held, for display/diagnostics."""
    base = os.path.join(root, DIRNAME)
    out: Dict[str, Any] = {"tiles": {}, "ranges": 0, "bytes": 0}
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for t in names:
        idx = _read_index(os.path.join(base, t))
        n = len(idx)
        b = sum(int(e.get("bytes", 0)) for e in idx.values() if isinstance(e, dict))
        out["tiles"][t] = {"ranges": n, "bytes": b}
        out["ranges"] += n
        out["bytes"] += b
    return out
