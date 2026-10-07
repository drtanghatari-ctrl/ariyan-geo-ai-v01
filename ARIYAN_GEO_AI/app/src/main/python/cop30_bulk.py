"""
cop30_bulk.py -- ARIYAN GEO AI: COP30 windows cut from the BULK Copernicus
tiles (offline_data/<country>/dem/N32_E048.tif). cop-bulk-v1, 2026-10-07.

WHY
  Pass 1 already reads these bulk Copernicus GLO-30 tiles. Pass 2's COP30
  cross-check was fetching the same cells again from OpenTopography (live,
  or as a 55 MB library tile). csc-v1 (cop_store_compare.py, run on the
  device 2026-10-07) proved the two copies identical for N32E048:
    * both PixelIsPoint, pixel 1/3600 deg, lattices aligned (offset 36.0000
      px = the library's 0.01 deg margin, fraction 0.0000),
    * 12,960,000 of 12,960,000 cells identical (0 mismatches); every +-1 px
      shift differs almost everywhere (up to 214 m), so the alignment is
      unambiguous.
  The bulk file on the device has sha256 ecbebfaf8dfea443..., the same bytes
  as the public AWS object Copernicus_DSM_COG_10_N32_00_E048_00_DEM.tif.

LATTICE (same global lattice as srtm_library.py)
  Global column k = cell centred on lon k/3600; global row k = cell centred
  on lat 90 - k/3600. A bulk tile for (lat_floor la, lon_floor lo) has
  pixel (0,0) centred on (lat la+1, lon lo), so
      global col = lo*3600 + local col,   global row = (89-la)*3600 + local row.
  Neighbouring bulk tiles therefore abut with no gap and no overlap, and a
  window that crosses a degree line is assembled from 2-4 files (the
  library could not do this; it refused straddling windows).

WHICH WINDOW (identical to srtm_library.cut_window)
  Rule GDAL via srtm_library.window_indices(); near-tie windows are NOT cut
  (reason "near_tie") and the caller carries on exactly as before.

SAFETY
  * A bulk file is used only if its georeferencing is exactly the lattice
    above: 3600 x 3600, pixel 1/3600 deg both axes, tiepoint pixel (0,0) at
    (lo, la+1), GTRasterTypeGeoKey = 2 (PixelIsPoint). Anything else ->
    reason "bulk_lattice_differs", never a guess (Copernicus tiles north of
    50 deg have wider pixels and are refused here).
  * Every file that supplies cells is hashed (SHA-256, re-hashed whenever
    its size or mtime changes) and returned so the provenance ledger records
    it as a FILE source; provenance_check re-hashes it later.
  * Cells <= -1000 m become NaN (no-data), so the existing NODATA guard in
    dem_source_mobile refuses the window exactly as it would a live one.
  * A missing file anywhere in the window -> None ("bulk_tile_missing").
Pure Python + numpy, reads through geotiff_cog_reader.CopernicusDemTile.
"""

import hashlib
import math
import os
import threading
from typing import Dict, List, Optional, Tuple

import numpy as np

VERSION = "cop-bulk-v1"
ARCSEC = 1.0 / 3600.0
TILE_PX = 3600
_GEOKEY_RASTER_TYPE = 1025
_TAG_GEOKEY_DIRECTORY = 34735
_lock = threading.Lock()
_sha_cache: Dict[str, Tuple[int, int, str]] = {}
_lattice_cache: Dict[tuple, Tuple[int, int, Optional[str]]] = {}


def bulk_tile_id(lat_floor: int, lon_floor: int) -> str:
    """offline_dem_store's file naming, e.g. N32_E048."""
    return (f"{'N' if lat_floor >= 0 else 'S'}{abs(lat_floor):02d}_"
            f"{'E' if lon_floor >= 0 else 'W'}{abs(lon_floor):03d}")


def bulk_tile_path(root: str, lat_floor: int, lon_floor: int) -> Optional[str]:
    """First <root>/<folder>/dem/<id>.tif that exists (folders in name
    order, dem_library skipped), or None."""
    name = bulk_tile_id(lat_floor, lon_floor) + ".tif"
    try:
        folders = sorted(os.listdir(root))
    except OSError:
        return None
    for d in folders:
        if d == "dem_library":
            continue
        p = os.path.join(root, d, "dem", name)
        if os.path.isfile(p):
            return p
    return None


def _stat_key(path: str) -> Tuple[int, int]:
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


def file_sha256(path: str) -> str:
    size, mtime = _stat_key(path)
    with _lock:
        hit = _sha_cache.get(path)
        if hit and hit[0] == size and hit[1] == mtime:
            return hit[2]
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    with _lock:
        _sha_cache[path] = (size, mtime, digest)
    return digest


def _raster_type(path: str) -> Optional[int]:
    import geotiff_cog_reader as gcr
    with open(path, "rb") as f:
        head = f.read(8)
        bo = "<" if head[:2] == b"II" else ">"
        import struct
        (ifd,) = struct.unpack(bo + "I", head[4:8])
        tags = gcr._read_ifd(f, bo, ifd)
    keys = tags.get(_TAG_GEOKEY_DIRECTORY)
    if not keys:
        return None
    for i in range(keys[3]):
        kid, _loc, _cnt, val = keys[4 + 4 * i: 8 + 4 * i]
        if kid == _GEOKEY_RASTER_TYPE:
            return int(val)
    return None


def lattice_problem(path: str, lat_floor: int, lon_floor: int) -> Optional[str]:
    """None if the file sits exactly on the global 1-arcsec lattice as
    described in the module docstring; otherwise a short reason."""
    size, mtime = _stat_key(path)
    key = (path, lat_floor, lon_floor)
    with _lock:
        hit = _lattice_cache.get(key)
        if hit and hit[0] == size and hit[1] == mtime:
            return hit[2]
    import offline_dem_store
    try:
        g = offline_dem_store._get_cached_tile(path).georef()
        rt = _raster_type(path)
        problem = None
        if g["width"] != TILE_PX or g["height"] != TILE_PX:
            problem = f"size {g['width']}x{g['height']}"
        elif abs(g["scale_x"] - ARCSEC) > 1e-12 or abs(g["scale_y"] - ARCSEC) > 1e-12:
            problem = "pixel size not 1 arcsec"
        elif g["tie_col"] != 0 or g["tie_row"] != 0:
            problem = "tiepoint not at pixel (0,0)"
        elif abs(g["tie_lon"] - lon_floor) > 1e-9 or abs(g["tie_lat"] - (lat_floor + 1)) > 1e-9:
            problem = f"tiepoint at ({g['tie_lat']}, {g['tie_lon']})"
        elif rt != 2:
            problem = f"raster type {rt} (need 2 = PixelIsPoint)"
    except Exception as exc:
        problem = f"unreadable: {type(exc).__name__}: {exc}"[:200]
    with _lock:
        _lattice_cache[key] = (size, mtime, problem)
    return problem


def covered(root: str, lat_floor: int, lon_floor: int) -> Optional[str]:
    """Path of a usable bulk tile for this degree, or None. Cheap after the
    first call per file (lattice result cached on size + mtime)."""
    p = bulk_tile_path(root, lat_floor, lon_floor)
    if p is None or lattice_problem(p, lat_floor, lon_floor) is not None:
        return None
    return p


def _read_region(path: str, r: int, nr: int, c: int, nc: int) -> np.ndarray:
    """Local rows r..r+nr-1, cols c..c+nc-1 of one bulk file, float64."""
    import offline_dem_store
    t = offline_dem_store._get_cached_tile(path)
    lay = t._layout
    tw, tl = lay.tile_width, lay.tile_length
    out = np.empty((nr, nc), dtype=np.float64)
    for br in range(r // tl, (r + nr - 1) // tl + 1):
        for bc in range(c // tw, (c + nc - 1) // tw + 1):
            block = t._get_decoded_tile(br * t._tiles_across + bc)
            y0, y1 = max(r, br * tl), min(r + nr, (br + 1) * tl)
            x0, x1 = max(c, bc * tw), min(c + nc, (bc + 1) * tw)
            out[y0 - r:y1 - r, x0 - c:x1 - c] = block[y0 - br * tl:y1 - br * tl,
                                                      x0 - bc * tw:x1 - bc * tw]
    return out


def _spans(first: int, count: int) -> List[Tuple[int, int, int, int]]:
    """Split global [first, first+count) by 3600-px blocks ->
    (block index, local start, length, offset in output)."""
    out, k = [], first
    while k < first + count:
        b = k // TILE_PX
        n = min(first + count, (b + 1) * TILE_PX) - k
        out.append((b, k - b * TILE_PX, n, k - first))
        k += n
    return out


def cut_window(root: str, south: float, north: float, west: float,
               east: float) -> Tuple[Optional[dict], str]:
    """-> (grid dict, "ok") or (None, reason). Same grid dict shape as
    srtm_library.cut_window, plus "bulk_files": [{path, name, sha256}].
    Never raises for ordinary misses."""
    import srtm_library
    try:
        r0, nr, c0, nc, tie = srtm_library.window_indices(south, north, west, east)
        if tie:
            return None, "near_tie"
        if nr <= 0 or nc <= 0:
            return None, "empty_window"
        values = np.empty((nr, nc), dtype=np.float64)
        files = []
        for rb, rl, rn, ro in _spans(r0, nr):
            la = 89 - rb
            for cb, cl, cn, co in _spans(c0, nc):
                lo = cb  # global col k is centred on lon k/3600 (k < 0 west)
                path = bulk_tile_path(root, la, lo)
                if path is None:
                    return None, f"bulk_tile_missing {bulk_tile_id(la, lo)}"
                why = lattice_problem(path, la, lo)
                if why is not None:
                    return None, f"bulk_lattice_differs {bulk_tile_id(la, lo)}: {why}"
                values[ro:ro + rn, co:co + cn] = _read_region(path, rl, rn, cl, cn)
                files.append({"path": path, "name": bulk_tile_id(la, lo),
                              "sha256": file_sha256(path)})
    except Exception as exc:  # never let the bulk store break a fetch
        return None, f"bulk_error: {type(exc).__name__}: {exc}"[:200]
    values[values <= -1000] = np.nan
    names = "+".join(f["name"] for f in files)
    return {"values": values, "ncols": nc, "nrows": nr,
            "xll": (c0 - 0.5) * ARCSEC, "yll": 90.0 - (r0 + nr - 0.5) * ARCSEC,
            "cellsize": ARCSEC, "cell_is_center": False, "nodata_value": None,
            "library_tile": names, "library_sha256": files[0]["sha256"],
            "library_version": VERSION, "bulk_files": files}, "ok"


def spot_check(root: str, south, north, west, east, api_key: str,
               timeout_s: float = 120.0) -> dict:
    """ONE live COP30 AAIGrid request; must equal the bulk cut cell by cell."""
    import srtm_library
    g, why = cut_window(root, south, north, west, east)
    if g is None:
        return {"ok": False, "reason": why}
    from ascii_grid import parse_ascii_grid
    raw = srtm_library._http_get({"demtype": "COP30", "south": south, "north": north,
                                  "west": west, "east": east, "outputFormat": "AAIGrid",
                                  "API_Key": api_key}, timeout_s)
    live = parse_ascii_grid(raw.decode("ascii", "replace"))
    same_shape = live.values.shape == g["values"].shape
    same_origin = (abs(live.xll - g["xll"]) < 1e-3 * ARCSEC
                   and abs(live.yll - g["yll"]) < 1e-3 * ARCSEC)
    mism = None
    if same_shape:
        a = live.values.astype(np.float32)
        b = g["values"].astype(np.float32)
        mism = int(np.sum(~((a == b) | (np.isnan(a) & np.isnan(b)))))
    ok = bool(same_shape and same_origin and mism == 0)
    return {"ok": ok, "demtype": "COP30", "source": "bulk", "tile": g["library_tile"],
            "shape_live": list(live.values.shape), "shape_lib": list(g["values"].shape),
            "origin_match": same_origin, "mismatches": mism,
            "live_sha256": hashlib.sha256(raw).hexdigest(), "library_version": VERSION}
