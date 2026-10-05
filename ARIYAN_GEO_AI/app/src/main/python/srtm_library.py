"""
srtm_library.py -- ARIYAN GEO AI offline DEM tile library (lib-v1, 2026-10-05)

WHAT
  Keeps 1-degree GeoTIFF tiles of SRTMGL1 and COP30 (OpenTopography globaldem)
  on the device and cuts Pass 2 windows out of them locally, so a Pass 2
  candidate (main window, up to 2 stability shifts, COP30 cross-check) needs
  0 live calls once its area's tiles are present.

WHY THE CUT IS EXACT (proven 2026-10-05, bde-v2/v3/v4/v4b)
  * Both products sit on one global lattice: cell = 1/3600 deg, cell centres
    on whole arc-seconds, so cell k's left edge is at (k - 0.5)/3600 deg.
  * Rule GDAL (stated before inspection, confirmed 10/10 SRTM + 7/7 COP30):
        first = floor(lo + 0.001), count = floor(hi - lo + 0.5)
    with lo/hi = window edges in lattice cell units, both axes.
  * Values: SRTM tile = LZW int16 whole metres, COP30 tile = LZW float32
    (exact float32 = the AAIGrid text). 0 mismatches against the live AAIGrid.

SAFETY
  * Near-tie windows (lo within 0.002 cell of a rule boundary, or width
    within 0.002 cell of .5) are NOT cut: cut_window returns None with
    reason "near_tie" and the caller makes the live request as before.
  * Every tile's SHA-256 is recorded at download and re-checked at load;
    a changed file is refused (reason "sha_mismatch"), never used.
  * Windows not fully inside one tile -> None ("not_in_library").
  * spot_check() makes ONE live AAIGrid request and compares cell-by-cell;
    run once per job before trusting the library for that job.

LAYOUT   <offline_root>/dem_library/<DEMTYPE>/N32E048.tif  + index.json
Pure Python + numpy, no GDAL.
"""

import hashlib
import json
import math
import os
import struct
import threading
import time
import zlib
from collections import OrderedDict
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

VERSION = "lib-v1"
ARCSEC = 1.0 / 3600.0
TILE_MARGIN_DEG = 0.01
TIE_EPS = 0.002
SUPPORTED_DEMTYPES = ("SRTMGL1", "COP30")
BASE_URL = "https://portal.opentopography.org/API/globaldem"
_lock = threading.RLock()
_cache: "OrderedDict[str, TileReader]" = OrderedDict()
_CACHE_MAX = 4


class LibraryError(Exception):
    pass


# ---------------------------------------------------------------- GeoTIFF ----
def _lzw_decode(buf: bytes) -> bytes:
    """TIFF LZW (MSB-first, early change)."""
    out = bytearray()
    n_bits = len(buf) * 8
    pos = 0
    width = 9
    table: List[bytes] = []
    prev: Optional[bytes] = None
    while True:
        if pos + width > n_bits:
            break
        byte_i = pos >> 3
        chunk = int.from_bytes(buf[byte_i:byte_i + 3].ljust(3, b"\0"), "big")
        code = (chunk >> (24 - (pos & 7) - width)) & ((1 << width) - 1)
        pos += width
        if code == 256:
            table = [bytes([i]) for i in range(256)] + [b"", b""]
            width = 9
            prev = None
            continue
        if code == 257:
            break
        if prev is None:
            entry = table[code]
            out += entry
            prev = entry
            continue
        if code < len(table):
            entry = table[code]
            table.append(prev + entry[:1])
        else:
            entry = prev + prev[:1]
            table.append(entry)
        out += entry
        prev = entry
        if len(table) + 1 >= (1 << width) and width < 12:
            width += 1
    return bytes(out)


def _tags(d: bytes):
    bo = "<" if d[:2] == b"II" else ">"
    if struct.unpack(bo + "H", d[2:4])[0] != 42:
        raise LibraryError("not a classic TIFF")
    off = struct.unpack(bo + "I", d[4:8])[0]
    n = struct.unpack(bo + "H", d[off:off + 2])[0]
    size = {1: 1, 2: 1, 3: 2, 4: 4, 11: 4, 12: 8, 16: 8}
    fmt = {1: "B", 3: "H", 4: "I", 11: "f", 12: "d", 16: "Q"}
    tags = {}
    for i in range(n):
        t, ty, c = struct.unpack(bo + "HHI", d[off + 2 + 12 * i:off + 10 + 12 * i])
        v = d[off + 10 + 12 * i:off + 14 + 12 * i]
        nb = size.get(ty, 1) * c
        raw = v[:nb] if nb <= 4 else d[struct.unpack(bo + "I", v)[0]:][:nb]
        tags[t] = raw.rstrip(b"\0").decode("ascii", "replace") if ty == 2 \
            else struct.unpack(bo + fmt[ty] * c, raw)
    return bo, tags


class TileReader:
    """Parses a GeoTIFF header once and decodes only the internal blocks a
    window touches (a full 1-degree COP30 tile is ~13 M cells; decoding it
    all in pure Python would take minutes on a phone)."""

    def __init__(self, data: bytes):
        bo, t = _tags(data)
        self.data = data
        self.W, self.H = t[256][0], t[257][0]
        bits, fmt_code = t[258][0], t.get(339, (1,))[0]
        self.comp = t.get(259, (1,))[0]
        self.pred = t.get(317, (1,))[0]
        if t.get(277, (1,))[0] != 1:
            raise LibraryError("multi-band TIFF")
        if self.comp not in (1, 5, 8, 32946):
            raise LibraryError(f"unsupported compression {self.comp}")
        if self.pred not in (1, 2):
            raise LibraryError(f"unsupported predictor {self.pred}")
        code = {(16, 2): "i2", (16, 1): "u2", (32, 3): "f4", (32, 2): "i4"}.get((bits, fmt_code))
        if code is None:
            raise LibraryError(f"unsupported sample type bits={bits} format={fmt_code}")
        self.dt = np.dtype(bo + code)
        self.tiled = 322 in t
        if self.tiled:
            self.bw, self.bh = t[322][0], t[323][0]
            self.offs, self.cnts = t[324], t[325]
        else:
            self.bw, self.bh = self.W, t.get(278, (self.H,))[0]
            self.offs, self.cnts = t[273], t[279]
        self.across = (self.W + self.bw - 1) // self.bw
        nod = t.get(42113)
        self.nodata = float(nod) if nod not in (None, "") else None
        scale = t[33550]
        if abs(scale[0] - ARCSEC) > 1e-12 or abs(scale[1] - ARCSEC) > 1e-12:
            raise LibraryError("tile not on the 1 arc-second lattice")
        tie_x, tie_y = t[33922][3], t[33922][4]
        gk = t.get(34735, ())
        point = any(gk[i] == 1025 and gk[i + 3] == 2 for i in range(4, len(gk), 4))
        half = 0.5 if point else 0.0
        cx = tie_x * 3600 - half + 0.5
        ry = (90.0 - tie_y) * 3600 - half + 0.5
        if abs(cx - round(cx)) > 1e-3 or abs(ry - round(ry)) > 1e-3:
            raise LibraryError("tile origin off the lattice")
        self.col0, self.row0 = int(round(cx)), int(round(ry))
        self._blocks: Dict[int, np.ndarray] = {}

    def _block(self, k: int) -> np.ndarray:
        b = self._blocks.get(k)
        if b is not None:
            return b
        raw = self.data[self.offs[k]:self.offs[k] + self.cnts[k]]
        if self.comp == 5:
            raw = _lzw_decode(raw)
        elif self.comp in (8, 32946):
            raw = zlib.decompress(raw)
        rows = self.bh if self.tiled else min(self.bh, self.H - k * self.bh)
        need = self.bw * rows * self.dt.itemsize
        if len(raw) < need:
            raise LibraryError(f"block {k} short ({len(raw)} < {need} bytes)")
        b = np.frombuffer(raw[:need], self.dt).reshape(rows, self.bw)
        if self.pred == 2:
            b = np.cumsum(b, axis=1, dtype=self.dt)
        if len(self._blocks) > 64:
            self._blocks.clear()
        self._blocks[k] = b
        return b

    def read(self, r: int, nr: int, c: int, nc: int) -> np.ndarray:
        """Tile-local window -> float64, NODATA as nan."""
        if r < 0 or c < 0 or r + nr > self.H or c + nc > self.W:
            raise LibraryError("window outside tile")
        out = np.empty((nr, nc), np.float64)
        for br in range(r // self.bh, (r + nr - 1) // self.bh + 1):
            for bc in range(c // self.bw, (c + nc - 1) // self.bw + 1):
                blk = self._block(br * self.across + bc)
                y0, y1 = max(r, br * self.bh), min(r + nr, br * self.bh + blk.shape[0])
                x0, x1 = max(c, bc * self.bw), min(c + nc, (bc + 1) * self.bw)
                out[y0 - r:y1 - r, x0 - c:x1 - c] = blk[y0 - br * self.bh:y1 - br * self.bh,
                                                         x0 - bc * self.bw:x1 - bc * self.bw]
        if self.nodata is not None:
            out[out == self.nodata] = np.nan
        return out


def decode_geotiff(data: bytes) -> Tuple[np.ndarray, int, int]:
    """Whole raster -> (values, global first column, global first row).
    Global lattice: column k = cell whose left edge is at lon (k - 0.5)/3600;
    row k = cell whose top edge is at lat 90 - (k - 0.5)/3600."""
    tr = TileReader(data)
    return tr.read(0, tr.H, 0, tr.W), tr.col0, tr.row0


# --------------------------------------------------------------- the rule ----
def _axis(lo: float, hi: float) -> Tuple[int, int, bool]:
    first = math.floor(lo + 0.001)
    count = int(math.floor(hi - lo + 0.5))
    f = (lo + 0.001) % 1.0
    w = (hi - lo) % 1.0
    tie = f < TIE_EPS or f > 1 - TIE_EPS or abs(w - 0.5) < TIE_EPS
    return first, count, tie


def window_indices(south: float, north: float, west: float, east: float):
    """Global (row0, nrows, col0, ncols, near_tie) per Rule GDAL."""
    c0, nc, tc = _axis(west * 3600 + 0.5, east * 3600 + 0.5)
    r0, nr, tr = _axis((90.0 - north) * 3600 + 0.5, (90.0 - south) * 3600 + 0.5)
    return r0, nr, c0, nc, (tc or tr)


# -------------------------------------------------------------- the store ----
def _dir(root: str, demtype: str) -> str:
    if demtype not in SUPPORTED_DEMTYPES:
        raise LibraryError(f"demtype {demtype} not in library")
    return os.path.join(root, "dem_library", demtype)


def tile_name(lat_floor: int, lon_floor: int) -> str:
    return (f"{'N' if lat_floor >= 0 else 'S'}{abs(lat_floor):02d}"
            f"{'E' if lon_floor >= 0 else 'W'}{abs(lon_floor):03d}")


def _index_path(root, demtype):
    return os.path.join(_dir(root, demtype), "index.json")


def load_index(root: str, demtype: str) -> Dict[str, dict]:
    p = _index_path(root, demtype)
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f)


def _save_index(root, demtype, idx):
    p = _index_path(root, demtype)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(idx, f, indent=1, sort_keys=True)
    os.replace(tmp, p)


def _load_tile(root: str, demtype: str, name: str, meta: dict):
    key = f"{demtype}/{name}"
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    path = os.path.join(_dir(root, demtype), name + ".tif")
    with open(path, "rb") as f:
        data = f.read()
    if hashlib.sha256(data).hexdigest() != meta["sha256"]:
        raise LibraryError(f"sha_mismatch {key}")
    entry = TileReader(data)
    with _lock:
        _cache[key] = entry
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return entry


def tiles_for_box(south, north, west, east) -> List[Tuple[int, int]]:
    return [(la, lo) for la in range(math.floor(south), math.floor(north) + 1)
            for lo in range(math.floor(west), math.floor(east) + 1)]


def cut_window(root: str, demtype: str, south: float, north: float,
               west: float, east: float) -> Tuple[Optional[dict], str]:
    """-> (grid dict compatible with ascii_grid.AsciiGrid fields, "ok") or
    (None, reason). Never raises for ordinary misses."""
    r0, nr, c0, nc, tie = window_indices(south, north, west, east)
    if tie:
        return None, "near_tie"
    try:
        idx = load_index(root, demtype)
    except (LibraryError, OSError, ValueError) as e:
        return None, f"index_error: {e}"
    for name, meta in idx.items():
        if not (meta["row0"] <= r0 and r0 + nr <= meta["row0"] + meta["nrows"]
                and meta["col0"] <= c0 and c0 + nc <= meta["col0"] + meta["ncols"]):
            continue
        try:
            rd = _load_tile(root, demtype, name, meta)
            sub = rd.read(r0 - rd.row0, nr, c0 - rd.col0, nc)
        except (LibraryError, OSError) as e:
            return None, str(e)
        return {"values": sub, "ncols": nc, "nrows": nr,
                "xll": (c0 - 0.5) * ARCSEC, "yll": 90.0 - (r0 + nr - 0.5) * ARCSEC,
                "cellsize": ARCSEC, "cell_is_center": False, "nodata_value": None,
                "library_tile": name, "library_sha256": meta["sha256"],
                "library_version": VERSION}, "ok"
    return None, "not_in_library"


def as_ascii_grid(g: dict):
    from ascii_grid import AsciiGrid
    return AsciiGrid(values=g["values"], ncols=g["ncols"], nrows=g["nrows"],
                     xll=g["xll"], yll=g["yll"], cellsize=g["cellsize"],
                     cell_is_center=False, nodata_value=None)


# ------------------------------------------------------------ downloading ----
def _http_get(params: dict, timeout_s: float) -> bytes:
    import requests
    r = requests.get(BASE_URL, params=params, timeout=timeout_s)
    if r.status_code != 200:
        body = (r.text or "")[:200]
        if r.status_code in (401, 429) and ("rate limit" in body.lower() or "api calls" in body.lower()
                                             or r.status_code == 429):
            raise LibraryError("quota: " + body)
        raise LibraryError(f"HTTP {r.status_code}: {body}")
    return r.content


def download_tile(root: str, demtype: str, lat_floor: int, lon_floor: int,
                  api_key: str, timeout_s: float = 300.0) -> dict:
    """ONE live call. Saves <name>.tif, verifies it decodes, records SHA-256."""
    d = _dir(root, demtype)
    os.makedirs(d, exist_ok=True)
    name = tile_name(lat_floor, lon_floor)
    params = {"demtype": demtype,
              "south": lat_floor - TILE_MARGIN_DEG, "north": lat_floor + 1 + TILE_MARGIN_DEG,
              "west": lon_floor - TILE_MARGIN_DEG, "east": lon_floor + 1 + TILE_MARGIN_DEG,
              "outputFormat": "GTiff", "API_Key": api_key}
    data = _http_get(params, timeout_s)
    rd = TileReader(data)  # refuse anything we cannot read
    rd.read(rd.H // 2, 1, rd.W // 2, 1)
    c0, r0 = rd.col0, rd.row0
    path = os.path.join(d, name + ".tif")
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    meta = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "col0": c0, "row0": r0, "nrows": rd.H, "ncols": rd.W, "demtype": demtype,
            "downloaded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "library_version": VERSION}
    with _lock:
        idx = load_index(root, demtype)
        idx[name] = meta
        _save_index(root, demtype, idx)
        _cache.pop(f"{demtype}/{name}", None)
    return {"tile": name, **meta}


def missing_tiles(root: str, demtype: str, south, north, west, east) -> List[Tuple[int, int]]:
    idx = load_index(root, demtype)
    return [t for t in tiles_for_box(south - TILE_MARGIN_DEG, north + TILE_MARGIN_DEG,
                                     west - TILE_MARGIN_DEG, east + TILE_MARGIN_DEG)
            if tile_name(*t) not in idx]


def ensure_tiles(root: str, demtypes, south, north, west, east, api_key: str,
                 max_calls: int, on_live_call: Optional[Callable[[str], bool]] = None) -> dict:
    """Downloads missing tiles for the box (+ margin), at most max_calls.
    on_live_call(label) is asked BEFORE each call; returning False stops
    (the 40/day budget lives in the caller). Stops cleanly on quota."""
    report = {"downloaded": [], "failed": [], "stopped": None, "calls": 0}
    for dt in demtypes:
        for la, lo in missing_tiles(root, dt, south, north, west, east):
            label = f"{dt}/{tile_name(la, lo)}"
            if report["calls"] >= max_calls:
                report["stopped"] = "max_calls"
                return report
            if on_live_call is not None and not on_live_call(label):
                report["stopped"] = "budget"
                return report
            report["calls"] += 1
            try:
                report["downloaded"].append(download_tile(root, dt, la, lo, api_key))
            except LibraryError as e:
                report["failed"].append({"tile": label, "error": str(e)[:300]})
                if str(e).startswith("quota"):
                    report["stopped"] = "quota"
                    return report
            except Exception as e:  # network etc.: record, carry on
                report["failed"].append({"tile": label, "error": f"{type(e).__name__}: {e}"[:300]})
    return report


def spot_check(root: str, demtype: str, south, north, west, east, api_key: str,
               timeout_s: float = 120.0) -> dict:
    """ONE live AAIGrid request; must equal the library cut cell-by-cell."""
    lib, why = cut_window(root, demtype, south, north, west, east)
    if lib is None:
        return {"ok": False, "reason": why}
    from ascii_grid import parse_ascii_grid
    raw = _http_get({"demtype": demtype, "south": south, "north": north, "west": west,
                     "east": east, "outputFormat": "AAIGrid", "API_Key": api_key}, timeout_s)
    live = parse_ascii_grid(raw.decode("ascii", "replace"))
    same_shape = live.values.shape == lib["values"].shape
    same_origin = (abs(live.xll - lib["xll"]) < 1e-3 * ARCSEC
                   and abs(live.yll - lib["yll"]) < 1e-3 * ARCSEC)
    mism = None
    if same_shape:
        a, b = live.values, lib["values"]
        mism = int(np.sum(~((a == b) | (np.isnan(a) & np.isnan(b)))))
    ok = bool(same_shape and same_origin and mism == 0)
    return {"ok": ok, "demtype": demtype, "tile": lib["library_tile"],
            "shape_live": list(live.values.shape), "shape_lib": list(lib["values"].shape),
            "origin_match": same_origin, "mismatches": mism,
            "live_sha256": hashlib.sha256(raw).hexdigest(), "library_version": VERSION}
