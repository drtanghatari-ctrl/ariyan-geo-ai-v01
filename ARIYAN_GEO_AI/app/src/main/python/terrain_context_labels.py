"""
terrain_context_labels.py

Part of ARIYAN GEO AI -- F3 terrain context labels (added 2026-09-30,
parameters approved by the user BEFORE any known site was looked at).

VERSIONS
- f3-v1 (2026-09-30): shape + Mountain flag. Tested on job 273d33
  (Persepolis cluster): the Mountain flag fired on 317 of 782 candidates
  and on 6 of 7 recorded sites, including the flat-plain Bakun mounds
  (median slope 0.4 deg) -- because "range > 150 m within 2 km" catches
  anything near a mountain edge. So it can never be a rejection rule.
  f3-v1 rows already in the database are kept untouched.
- f3-v2 (THIS VERSION, parameters APPROVED and FROZEN by the user on
  2026-09-30 before any data of its test job was seen): shape rules are
  unchanged; the Mountain flag is replaced by two separate labels:
    * HILLSIDE: median Horn slope within HILLSIDE_RADIUS_M (250 m) >
      HILLSIDE_MEDIAN_SLOPE_DEG (10 deg). Unknown if less than
      HILLSIDE_MIN_VALID_FRACTION (90%) of the 250 m disc has DEM data.
      The candidate for a future auto-Rejected rule -- but ONLY after it
      passes the pre-registered tests below. Until then a label only.
    * NEAR MOUNTAINS: exactly the old f3-v1 Mountain rule (range > 150 m
      or median slope > 15 deg within 2 km). Context only, never a rule.
  PRE-REGISTERED TEST (fixed before any data was seen):
    test job = Kangavar valley, 34.430-34.555 N / 47.990-48.090 E, 1000 m
    tiles, DEM-only offline-first (offline tiles N34_E047, N34_E048).
    1. PRIMARY: Hillside = Yes at <= 1 of the recorded gazetteer site
       points inside the scanned area -> PASS; otherwise FAIL and Hillside
       stays a label only permanently.
    2. USEFULNESS: share of candidates with Hillside = Yes is reported
       (< 5% = harmless but not worth automating).
    3. COMPARISON: the Near-mountains rate on the same sites and
       candidates is reported beside it.
    4. Even on PASS, Hillside becomes an auto-rule only after a second
       fresh job (Susiana plain, 32.12-32.28 N / 48.38-48.60 E), and only
       for mound/tell searches -- never fortress/cliff/rock-relief ones.
    5. Bonus: Calibrate... on the Kangavar job, pre-registered p < 0.05.
  The report prints the check-1 count on EVERY job for information; it is
  the pre-registered decision only on the Kangavar job. Any further change
  = f3-v3, tested on another new job.

WHAT THIS DOES
For every candidate on the DONE tiles of one Wide-Area Search job it reads
the surrounding ground from the OFFLINE Copernicus DEM GLO-30 library only
(no network, no live fetch) and records two plain descriptions:

1. SHAPE, from a Local Relief Model (Hesse 2010; the "local relief" idea
   taken from the 2026-09-29 terrain-processing handoff document):
       local_relief = elevation - mean elevation within LOCAL_RELIEF_RADIUS_M
   The broad slope of the land is subtracted, so a small mound stands out
   as positive relief and a hollow as negative relief. Inside a window of
   +/- SHAPE_HALF_WINDOW_M around the candidate:
     - Ring: the candidate cell is NOT raised (relief < threshold) and one
       connected group of raised cells lies around it, at 45-250 m, in at
       least RING_MIN_SECTORS of 8 compass sectors.
     - otherwise the SEED is the cell with the largest |relief| >= threshold
       among the candidate cell and its 8 neighbours (one cell of tolerance,
       because the candidate point and the DEM pixel lattice do not line up
       exactly). The PATCH is every 8-connected cell of the same sign with
       |relief| >= threshold that joins the seed.
         - Too small to shape: patch smaller than MIN_SHAPE_CELLS cells
         - Linear: elongation >= LINEAR_ELONGATION
         - Mound (positive) / Depression (negative): otherwise
     - No shape: no cell near the candidate reaches the threshold.
   Elongation = sqrt(largest / smallest second moment of the patch treated
   as an AREA (each cell adds its own dx^2/12, dy^2/12)), so a solid L x W
   rectangle reads exactly L/W.
2. HILLSIDE (f3-v2), within HILLSIDE_RADIUS_M of the candidate:
   Yes if the median slope (Horn 1981, the same formula
   terrain_derivatives.py uses) > HILLSIDE_MEDIAN_SLOPE_DEG; No if not;
   Unknown if less than HILLSIDE_MIN_VALID_FRACTION of the disc has DEM
   data. A LABEL ONLY for now (see VERSIONS).
3. NEAR MOUNTAINS (the f3-v1 Mountain flag, unchanged), within
   NEAR_MOUNTAINS_RADIUS_M of the candidate:
   Yes if elevation range > NEAR_MOUNTAINS_RELIEF_M or median slope >
   NEAR_MOUNTAINS_MEDIAN_SLOPE_DEG; No if neither and at least
   MIN_VALID_FRACTION of the disc has DEM data; Unknown otherwise.
   Context only: it never rejects anything and never will.

WHAT THIS IS NOT
- Not evidence of a site. It is DERIVED from the same DEM the detector
  already used and adds no new information -- it only describes the shape
  of the ground. Stored as evidence_type TERRAIN_CONTEXT, relation
  'neutral'. Never changes a candidate's status, score or confidence.
- Not fine detail. GLO-30 cells are about 27 x 31 m at 30 N, so the shape
  window is only ~23 x 21 cells and anything narrower than ~3 cells
  (~90 m) is honestly reported as "Too small to shape", not guessed.
- Not a Surfer-style picture. The handoff's colour/hillshade reconstruction
  is a display feature for later (Phase 6); nothing here is tuned to look
  like a reference image.

HANDOFF PARTS TAKEN (2026-09-30): local relief; NoData never filled (cells
without data stay NaN and are excluded, and a window that cannot be read
is reported, never faked); every parameter and the method version stored
with each label; SHA-256 of every DEM file used, for provenance; sanity
tests on flat / single-peak / ridge / valley grids (run in the sandbox,
not stored as data). Parts NOT taken: the Kotlin rewrite (the scientific
core stays in Python), the Surfer look-alike tuning, the 2-point gradient
(Horn, already used by the app, is more robust).

RE-RUN: idempotent. A candidate that already has a TERRAIN_CONTEXT entry
from the SAME method version is skipped; a new method version would add a
new entry beside the old one (history is never overwritten).

Writes: one TERRAIN_CONTEXT evidence_link per newly labelled candidate
(one transaction) and exactly one timeline_event
(TERRAIN_CONTEXT_LABELS_RUN). Refuses jobs marked CORRUPTED.
Existing entries of an older method version (f3-v1) are neither changed
nor counted as "already labelled"; f3-v2 adds its own entry beside them.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import grand_project_db as db
import grand_project_review as review
import known_sites
import offline_country_registry as countries
import offline_dem_store

METHOD_VERSION = "f3-v2"
EVIDENCE_TYPE = "TERRAIN_CONTEXT"

# ---- Shape parameters approved 2026-09-30 (f3-v1), unchanged in f3-v2 ----
SHAPE_HALF_WINDOW_M = 300.0        # ~600 x 600 m shape window
LOCAL_RELIEF_RADIUS_M = 150.0      # mean-elevation disc radius
RELIEF_THRESHOLD_M = 1.5           # |local relief| needed to count as shape
MIN_SHAPE_CELLS = 3                # smaller patches -> "Too small to shape"
LINEAR_ELONGATION = 3.0            # length/width at or above -> "Linear"
RING_INNER_M = 45.0                # ring search annulus
RING_OUTER_M = 250.0
RING_MIN_SECTORS = 6               # of 8 compass sectors
SEED_SEARCH_CELLS = 1              # candidate cell + its 8 neighbours
# ---- Near mountains = the f3-v1 Mountain flag, unchanged; context only ----
NEAR_MOUNTAINS_RADIUS_M = 2000.0
NEAR_MOUNTAINS_RELIEF_M = 150.0
NEAR_MOUNTAINS_MEDIAN_SLOPE_DEG = 15.0
MIN_VALID_FRACTION = 0.9           # DEM coverage needed to say "No"
# ---- Hillside, NEW in f3-v2, approved and frozen 2026-09-30 ----
HILLSIDE_RADIUS_M = 250.0
HILLSIDE_MEDIAN_SLOPE_DEG = 10.0   # Yes when the median slope is ABOVE this
HILLSIDE_MIN_VALID_FRACTION = 0.9  # below this DEM coverage -> Unknown
# ---- Pre-registered f3-v2 decision numbers (reported, never auto-applied) ----
PREREG_MAX_HILLSIDE_SITES = 1      # PASS if Hillside=Yes at <= 1 site point
PREREG_MIN_USEFUL_SHARE = 0.05     # < 5% of candidates = not worth automating
MIN_DISC_FRACTION = 0.5            # local relief needs half its disc present
NODATA_BELOW_M = -1000.0           # below the lowest land on Earth -> NoData

_M_PER_DEG_LAT = 111320.0

SHAPES = ("Mound", "Depression", "Linear", "Ring", "Too small to shape", "No shape")


class TerrainLabelError(Exception):
    pass


def parameters() -> Dict[str, Any]:
    return {
        "method_version": METHOD_VERSION,
        "shape_half_window_m": SHAPE_HALF_WINDOW_M,
        "local_relief_radius_m": LOCAL_RELIEF_RADIUS_M,
        "relief_threshold_m": RELIEF_THRESHOLD_M,
        "min_shape_cells": MIN_SHAPE_CELLS,
        "linear_elongation": LINEAR_ELONGATION,
        "ring_annulus_m": [RING_INNER_M, RING_OUTER_M],
        "ring_min_sectors_of_8": RING_MIN_SECTORS,
        "seed_search_cells": SEED_SEARCH_CELLS,
        "hillside_radius_m": HILLSIDE_RADIUS_M,
        "hillside_median_slope_deg": HILLSIDE_MEDIAN_SLOPE_DEG,
        "hillside_min_valid_fraction": HILLSIDE_MIN_VALID_FRACTION,
        "near_mountains_radius_m": NEAR_MOUNTAINS_RADIUS_M,
        "near_mountains_relief_m": NEAR_MOUNTAINS_RELIEF_M,
        "near_mountains_median_slope_deg": NEAR_MOUNTAINS_MEDIAN_SLOPE_DEG,
        "min_valid_fraction": MIN_VALID_FRACTION,
    }


# =========================== DEM WINDOW READING ===========================

_sha_cache: Dict[Tuple[str, int, float], str] = {}


def _file_sha256(path: str) -> str:
    st = os.stat(path)
    key = (path, st.st_size, st.st_mtime)
    cached = _sha_cache.get(key)
    if cached is None:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        cached = h.hexdigest()
        _sha_cache[key] = cached
    return cached


def read_window(storage_folder: str, offline_data_root: str, lat: float, lon: float,
                half_m: float) -> Dict[str, Any]:
    """Reads a square window of +/- half_m around (lat, lon) on the DEM's own
    pixel lattice (that of the tile holding the centre; neighbouring
    Copernicus tiles share the same lattice). Row 0 is the NORTH edge.
    Returns {"z", "dx_m", "dy_m", "ci", "cj", "files_used", "files_missing"}
    or {"error"} when the centre's own tile is not in the library.
    Cells with no data stay NaN -- nothing is filled in."""
    centre_path = offline_dem_store.local_tile_path(storage_folder, offline_data_root, lat, lon)
    if not os.path.isfile(centre_path):
        return {"error": "offline DEM tile %s is not in the library" % os.path.basename(centre_path)}
    g = offline_dem_store._get_cached_tile(centre_path).georef()
    sx, sy = g["scale_x"], g["scale_y"]
    col_c = round(g["tie_col"] + (lon - g["tie_lon"]) / sx)
    row_c = round(g["tie_row"] + (g["tie_lat"] - lat) / sy)
    lat_c = g["tie_lat"] - (row_c - g["tie_row"]) * sy
    lon_c = g["tie_lon"] + (col_c - g["tie_col"]) * sx
    dy = sy * _M_PER_DEG_LAT
    dx = sx * _M_PER_DEG_LAT * math.cos(math.radians(lat_c))
    ny = int(math.ceil(half_m / dy))
    nx = int(math.ceil(half_m / dx))
    ks = np.arange(-ny, ny + 1)
    ls = np.arange(-nx, nx + 1)
    lats = lat_c - ks * sy
    lons = lon_c + ls * sx
    LON, LAT = np.meshgrid(lons, lats)
    z = np.full(LON.shape, np.nan, dtype=np.float64)
    files_used: List[str] = []
    files_missing: List[str] = []
    pad = max(sx, sy)
    for tlat in range(int(math.floor(lats.min() - pad)), int(math.floor(lats.max() + pad)) + 1):
        for tlon in range(int(math.floor(lons.min() - pad)), int(math.floor(lons.max() + pad)) + 1):
            path = offline_dem_store.local_tile_path(storage_folder, offline_data_root, tlat + 0.5, tlon + 0.5)
            todo = np.isnan(z)
            if not todo.any():
                break
            if not os.path.isfile(path):
                in_tile = todo & (np.floor(LAT) == tlat) & (np.floor(LON) == tlon)
                if in_tile.any():
                    files_missing.append(os.path.basename(path))
                continue
            vals = offline_dem_store._get_cached_tile(path).get_elevations(LON[todo], LAT[todo])
            if np.any(~np.isnan(vals)):
                files_used.append(path)
            z[todo] = vals
    z[~np.isfinite(z) | (z < NODATA_BELOW_M)] = np.nan
    return {"z": z, "dx_m": dx, "dy_m": dy, "ci": ny, "cj": nx,
            "files_used": sorted(set(files_used)),
            "files_missing": sorted(set(files_missing))}


# =========================== PURE ANALYSIS (no I/O) ===========================

def local_relief(z: np.ndarray, dx: float, dy: float, radius_m: float) -> np.ndarray:
    """z minus the NaN-aware mean of z over a disc of radius_m (centre
    included). Cells whose own value is NaN, or whose disc is less than
    MIN_DISC_FRACTION present, are NaN. Cells within the radius of the
    grid edge see a clipped disc -- callers read a margin and crop."""
    ry = int(radius_m // dy)
    rx = int(radius_m // dx)
    offs = [(i, j) for i in range(-ry, ry + 1) for j in range(-rx, rx + 1)
            if (i * dy) ** 2 + (j * dx) ** 2 <= radius_m ** 2]
    h, w = z.shape
    valid = ~np.isnan(z)
    zf = np.where(valid, z, 0.0)
    zp = np.pad(zf, ((ry, ry), (rx, rx)))
    vp = np.pad(valid.astype(np.float64), ((ry, ry), (rx, rx)))
    s = np.zeros_like(zf)
    n = np.zeros_like(zf)
    for i, j in offs:
        s += zp[ry + i: ry + i + h, rx + j: rx + j + w]
        n += vp[ry + i: ry + i + h, rx + j: rx + j + w]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = s / n
    lr = z - mean
    lr[(~valid) | (n < MIN_DISC_FRACTION * len(offs))] = np.nan
    return lr


def _components(mask: np.ndarray) -> Tuple[np.ndarray, int]:
    """8-connected component labelling (no scipy on the phone)."""
    h, w = mask.shape
    lab = np.zeros((h, w), dtype=np.int32)
    n = 0
    for i0 in range(h):
        for j0 in range(w):
            if mask[i0, j0] and lab[i0, j0] == 0:
                n += 1
                lab[i0, j0] = n
                stack = [(i0, j0)]
                while stack:
                    i, j = stack.pop()
                    for di in (-1, 0, 1):
                        for dj in (-1, 0, 1):
                            a, b = i + di, j + dj
                            if 0 <= a < h and 0 <= b < w and mask[a, b] and lab[a, b] == 0:
                                lab[a, b] = n
                                stack.append((a, b))
    return lab, n


def _elongation(rows: np.ndarray, cols: np.ndarray, dx: float, dy: float) -> float:
    y = rows * dy
    x = cols * dx
    cxx = np.var(x) + dx * dx / 12.0
    cyy = np.var(y) + dy * dy / 12.0
    cxy = np.mean((x - x.mean()) * (y - y.mean()))
    tr = cxx + cyy
    det = cxx * cyy - cxy * cxy
    disc = math.sqrt(max(tr * tr / 4.0 - det, 0.0))
    l1 = tr / 2.0 + disc
    l2 = max(tr / 2.0 - disc, 1e-12)
    return math.sqrt(l1 / l2)


def classify_shape(lr: np.ndarray, ci: int, cj: int, dx: float, dy: float) -> Dict[str, Any]:
    """Shape label for the cell (ci, cj) of a local-relief grid lr."""
    h, w = lr.shape
    c_val = lr[ci, cj]
    if np.isnan(c_val):
        return {"shape": "No DEM", "note": "no local relief at the candidate cell"}
    raised = np.nan_to_num(lr, nan=-np.inf) >= RELIEF_THRESHOLD_M
    lowered = np.nan_to_num(lr, nan=np.inf) <= -RELIEF_THRESHOLD_M

    # Ring first: centre not raised, one connected raised group around it.
    if not raised[ci, cj]:
        ii, jj = np.mgrid[0:h, 0:w]
        ny_m = (ci - ii) * dy          # north positive
        ex_m = (jj - cj) * dx
        r = np.hypot(ny_m, ex_m)
        ann = (r >= RING_INNER_M) & (r <= RING_OUTER_M)
        sector = (np.floor((np.degrees(np.arctan2(ny_m, ex_m)) % 360.0) / 45.0)).astype(int) % 8
        lab, n = _components(raised)
        best = 0
        for k in range(1, n + 1):
            sel = (lab == k) & ann
            if sel.any():
                best = max(best, len(set(sector[sel].tolist())))
        if best >= RING_MIN_SECTORS:
            return {"shape": "Ring", "ring_sectors_of_8": best,
                    "centre_local_relief_m": round(float(c_val), 2)}

    # Seed within SEED_SEARCH_CELLS of the candidate cell.
    best_ij = None
    best_abs = 0.0
    s = SEED_SEARCH_CELLS
    for i in range(max(0, ci - s), min(h, ci + s + 1)):
        for j in range(max(0, cj - s), min(w, cj + s + 1)):
            v = lr[i, j]
            if not np.isnan(v) and abs(v) >= RELIEF_THRESHOLD_M and abs(v) > best_abs:
                best_abs, best_ij = abs(v), (i, j)
    if best_ij is None:
        return {"shape": "No shape", "centre_local_relief_m": round(float(c_val), 2)}
    positive = lr[best_ij] > 0
    lab, _ = _components(raised if positive else lowered)
    patch = lab == lab[best_ij]
    rows, cols = np.nonzero(patch)
    cells = int(rows.size)
    peak = float(np.nanmax(lr[patch]) if positive else np.nanmin(lr[patch]))
    out = {
        "patch_cells": cells,
        "patch_area_m2": int(round(cells * dx * dy)),
        "peak_local_relief_m": round(peak, 2),
        "centre_local_relief_m": round(float(c_val), 2),
        "patch_reaches_window_edge": bool(rows.min() == 0 or cols.min() == 0
                                          or rows.max() == h - 1 or cols.max() == w - 1),
    }
    if cells < MIN_SHAPE_CELLS:
        out["shape"] = "Too small to shape"
        return out
    el = _elongation(rows.astype(float), cols.astype(float), dx, dy)
    out["elongation"] = round(el, 2)
    if el >= LINEAR_ELONGATION:
        out["shape"] = "Linear"
    else:
        out["shape"] = "Mound" if positive else "Depression"
    return out


def horn_slope_deg(z: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Horn (1981) slope with separate x/y cell sizes (same 3x3 weights as
    terrain_derivatives._horn_gradients, which assumes square cells).
    NaN wherever any of the 3x3 neighbours is NaN."""
    zp = np.pad(z, 1, mode="edge")
    z1 = zp[0:-2, 0:-2]; z2 = zp[0:-2, 1:-1]; z3 = zp[0:-2, 2:]
    z4 = zp[1:-1, 0:-2];                       z6 = zp[1:-1, 2:]
    z7 = zp[2:, 0:-2];   z8 = zp[2:, 1:-1];    z9 = zp[2:, 2:]
    dzdx = ((z3 + 2 * z6 + z9) - (z1 + 2 * z4 + z7)) / (8 * dx)
    dzdy = ((z7 + 2 * z8 + z9) - (z1 + 2 * z2 + z3)) / (8 * dy)
    return np.degrees(np.arctan(np.hypot(dzdx, dzdy)))


def _disc(shape: Tuple[int, int], ci: int, cj: int, dx: float, dy: float, radius_m: float) -> np.ndarray:
    h, w = shape
    ii, jj = np.mgrid[0:h, 0:w]
    return np.hypot((ii - ci) * dy, (jj - cj) * dx) <= radius_m


def near_mountains(z: np.ndarray, slope: np.ndarray, ci: int, cj: int,
                   dx: float, dy: float) -> Dict[str, Any]:
    """The f3-v1 Mountain flag, unchanged, renamed Near mountains in f3-v2.
    Context only -- never a rule."""
    disc = _disc(z.shape, ci, cj, dx, dy, NEAR_MOUNTAINS_RADIUS_M)
    zd = z[disc]
    valid = ~np.isnan(zd)
    frac = float(valid.mean()) if zd.size else 0.0
    if not valid.any():
        return {"near_mountains": "Unknown", "dem_coverage_2km": 0.0}
    rng = float(np.nanmax(zd) - np.nanmin(zd))
    sl = slope[disc]
    sl = sl[~np.isnan(sl)]
    med = float(np.median(sl)) if sl.size else float("nan")
    yes = rng > NEAR_MOUNTAINS_RELIEF_M or (not math.isnan(med) and med > NEAR_MOUNTAINS_MEDIAN_SLOPE_DEG)
    flag = "Yes" if yes else ("No" if frac >= MIN_VALID_FRACTION else "Unknown")
    return {"near_mountains": flag,
            "relief_within_2km_m": round(rng, 1),
            "median_slope_within_2km_deg": None if math.isnan(med) else round(med, 1),
            "dem_coverage_2km": round(frac, 3)}


def hillside(z: np.ndarray, slope: np.ndarray, ci: int, cj: int,
             dx: float, dy: float) -> Dict[str, Any]:
    """f3-v2 Hillside label: median Horn slope within HILLSIDE_RADIUS_M.
    Unknown when less than HILLSIDE_MIN_VALID_FRACTION of the disc has DEM
    data (nothing is filled in). The median is taken over the cells whose
    slope could be computed (a cell next to NoData has no Horn slope)."""
    disc = _disc(z.shape, ci, cj, dx, dy, HILLSIDE_RADIUS_M)
    zd = z[disc]
    frac = float((~np.isnan(zd)).mean()) if zd.size else 0.0
    sl = slope[disc]
    sl = sl[~np.isnan(sl)]
    med = float(np.median(sl)) if sl.size else float("nan")
    if frac < HILLSIDE_MIN_VALID_FRACTION or math.isnan(med):
        flag = "Unknown"
    else:
        flag = "Yes" if med > HILLSIDE_MEDIAN_SLOPE_DEG else "No"
    return {"hillside": flag,
            "median_slope_within_250m_deg": None if math.isnan(med) else round(med, 2),
            "dem_coverage_250m": round(frac, 3)}


def analyse_point(storage_folder: str, offline_data_root: str, lat: float, lon: float) -> Dict[str, Any]:
    """Full F3 description of one point. Reads ONE window (the 2 km near-mountains disc)
    and cuts the shape window out of it (same lattice)."""
    half = max(NEAR_MOUNTAINS_RADIUS_M, HILLSIDE_RADIUS_M,
               SHAPE_HALF_WINDOW_M + LOCAL_RELIEF_RADIUS_M) + 50.0
    win = read_window(storage_folder, offline_data_root, lat, lon, half)
    if "error" in win:
        return {"shape": "No DEM", "hillside": "Unknown", "near_mountains": "Unknown",
                "error": win["error"]}
    z, dx, dy, ci, cj = win["z"], win["dx_m"], win["dy_m"], win["ci"], win["cj"]
    # Local relief on shape window + disc margin, then crop to the shape window.
    my = int(math.ceil((SHAPE_HALF_WINDOW_M + LOCAL_RELIEF_RADIUS_M) / dy))
    mx = int(math.ceil((SHAPE_HALF_WINDOW_M + LOCAL_RELIEF_RADIUS_M) / dx))
    sub = z[ci - my: ci + my + 1, cj - mx: cj + mx + 1]
    lr = local_relief(sub, dx, dy, LOCAL_RELIEF_RADIUS_M)
    sy = int(math.ceil(SHAPE_HALF_WINDOW_M / dy))
    sx = int(math.ceil(SHAPE_HALF_WINDOW_M / dx))
    lr = lr[my - sy: my + sy + 1, mx - sx: mx + sx + 1]
    out = classify_shape(lr, sy, sx, dx, dy)
    slope = horn_slope_deg(z, dx, dy)      # once, shared by both context labels
    out.update(hillside(z, slope, ci, cj, dx, dy))
    out.update(near_mountains(z, slope, ci, cj, dx, dy))
    out["cell_size_m"] = "%.1f x %.1f" % (dx, dy)
    out["shape_window_cells"] = "%d x %d" % (lr.shape[1], lr.shape[0])
    out["dem_files"] = [os.path.basename(p) for p in win["files_used"]]
    out["_dem_paths"] = win["files_used"]
    if win["files_missing"]:
        out["dem_files_missing"] = win["files_missing"]
    return out


# =========================== JOB-LEVEL RUN ===========================

def _xy(lat0, lon0, lat, lon):
    return ((lon - lon0) * _M_PER_DEG_LAT * math.cos(math.radians(lat0)),
            (lat - lat0) * _M_PER_DEG_LAT)


def label_job(db_root: str, job_ref: str) -> Dict[str, Any]:
    conn = review._connect(db_root)
    try:
        try:
            job_id = review._resolve_id(conn, "wide_area_search_job", job_ref)
        except review.ReviewError as e:
            raise TerrainLabelError(str(e))
        job = dict(conn.execute("SELECT * FROM wide_area_search_job WHERE id = ?", (job_id,)).fetchone())
        trust = review._current_job_trust(conn).get(job_id)
        if trust and trust["trust"] == "CORRUPTED":
            raise TerrainLabelError("Job %s is marked CORRUPTED (%s); terrain labels refuse it."
                                    % (job_id[:6], trust["reason"]))
        tiles = [dict(r) for r in conn.execute(
            "SELECT tile_index, center_lat, center_lon, status, investigation_id "
            "FROM wide_area_search_tile WHERE job_id = ? ORDER BY tile_index", (job_id,)).fetchall()]
        done = [t for t in tiles if t["status"] == "DONE"]
        if not done:
            raise TerrainLabelError("Job %s has no DONE tiles; nothing was scanned yet." % job_id[:6])
        inv_ids = [t["investigation_id"] for t in done if t["investigation_id"]]
        cands: List[Dict[str, Any]] = []
        for i in range(0, len(inv_ids), 500):
            chunk = inv_ids[i:i + 500]
            cands += [dict(r) for r in conn.execute(
                "SELECT id, lat, lon, status FROM candidate WHERE investigation_id IN (%s)"
                % ",".join("?" * len(chunk)), chunk).fetchall()]
        existing: Dict[str, Dict[str, Any]] = {}
        ids = [c["id"] for c in cands]
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for r in conn.execute(
                    "SELECT candidate_id, detail_json FROM evidence_link WHERE evidence_type = ? "
                    "AND candidate_id IN (%s) ORDER BY id" % ",".join("?" * len(chunk)),
                    [EVIDENCE_TYPE] + chunk).fetchall():
                try:
                    d = json.loads(r["detail_json"] or "{}")
                except ValueError:
                    continue
                if d.get("method_version") == METHOD_VERSION:
                    existing[r["candidate_id"]] = d
    finally:
        conn.close()

    new_rows: List[Tuple[str, Dict[str, Any]]] = []
    failures: Dict[str, int] = {}
    labels: Dict[str, Dict[str, Any]] = dict(existing)
    dem_hashes: Dict[str, str] = {}
    params = parameters()
    for c in cands:
        if c["id"] in existing:
            continue
        country = countries.get_country_for_point(c["lat"], c["lon"])
        if country is None:
            failures["no offline country package covers this point"] = \
                failures.get("no offline country package covers this point", 0) + 1
            continue
        res = analyse_point(country.storage_folder, db_root, c["lat"], c["lon"])
        if res.get("error"):
            failures[res["error"]] = failures.get(res["error"], 0) + 1
            continue
        paths = res.pop("_dem_paths", [])
        for p in paths:
            if p not in dem_hashes:
                dem_hashes[p] = _file_sha256(p)
        detail = {
            "method_version": METHOD_VERSION,
            "what": "terrain context derived from the offline DEM; describes shape, not evidence of a site",
            "shape": res["shape"],
            "hillside": res["hillside"],
            "near_mountains": res["near_mountains"],
        }
        for k in ("peak_local_relief_m", "centre_local_relief_m", "patch_cells", "patch_area_m2",
                  "elongation", "patch_reaches_window_edge", "ring_sectors_of_8",
                  "median_slope_within_250m_deg", "dem_coverage_250m",
                  "relief_within_2km_m", "median_slope_within_2km_deg", "dem_coverage_2km",
                  "cell_size_m", "shape_window_cells", "dem_files_missing"):
            if k in res:
                detail[k] = res[k]
        detail["dem_files"] = ["%s sha256:%s" % (os.path.basename(p), dem_hashes[p][:16]) for p in paths]
        detail["parameters"] = params
        new_rows.append((c["id"], detail))
        labels[c["id"]] = detail

    if new_rows:
        conn = db.get_connection(db_root)
        try:
            db.initialize_schema(conn)
            now = db._now_iso()
            with conn:
                conn.executemany(
                    "INSERT INTO evidence_link (candidate_id, evidence_type, relation, detail_json, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [(cid, EVIDENCE_TYPE, "neutral", json.dumps(d), now) for cid, d in new_rows])
        finally:
            conn.close()

    # Recorded sites inside the scanned coverage: label AT the gazetteer point,
    # plus the nearest candidate and its label. Same coverage rule as F2.
    half = float(job["tile_size_m"]) / 2.0
    lat0 = sum(t["center_lat"] for t in done) / len(done)
    lon0 = sum(t["center_lon"] for t in done) / len(done)
    tile_xy = [_xy(lat0, lon0, t["center_lat"], t["center_lon"]) for t in done]
    pad = half / _M_PER_DEG_LAT + 0.01
    lon_pad = pad / max(0.2, math.cos(math.radians(lat0)))
    lats = [t["center_lat"] for t in done]
    lons = [t["center_lon"] for t in done]
    site_rows = []
    cand_xy = [(c, _xy(lat0, lon0, c["lat"], c["lon"])) for c in cands]
    for s in known_sites.sites_in_bbox(min(lats) - pad, min(lons) - lon_pad,
                                       max(lats) + pad, max(lons) + lon_pad):
        x, y = _xy(lat0, lon0, s["lat"], s["lon"])
        if not any(abs(x - tx) <= half and abs(y - ty) <= half for tx, ty in tile_xy):
            continue
        country = countries.get_country_for_point(s["lat"], s["lon"])
        at = (analyse_point(country.storage_folder, db_root, s["lat"], s["lon"]) if country
              else {"shape": "No DEM", "hillside": "Unknown", "near_mountains": "Unknown",
                    "error": "no country package"})
        at.pop("_dem_paths", None)
        near = None
        best = None
        for c, (cx, cy) in cand_xy:
            d = math.hypot(cx - x, cy - y)
            if best is None or d < best:
                best, near = d, c
        site_rows.append({
            "name": s.get("display_name") or s.get("name"),
            "lat": s["lat"], "lon": s["lon"],
            "at_site": {k: at.get(k) for k in ("shape", "hillside", "near_mountains",
                                              "peak_local_relief_m", "patch_cells", "elongation",
                                              "median_slope_within_250m_deg", "dem_coverage_250m",
                                              "relief_within_2km_m", "median_slope_within_2km_deg",
                                              "error")},
            "nearest_candidate_id": near["id"] if near else None,
            "nearest_candidate_m": round(best, 1) if best is not None else None,
            "nearest_candidate_label": ({"shape": labels[near["id"]]["shape"],
                                         "hillside": labels[near["id"]]["hillside"],
                                         "near_mountains": labels[near["id"]]["near_mountains"]}
                                        if near and near["id"] in labels else None),
        })
    site_rows.sort(key=lambda r: (r["nearest_candidate_m"] is None, r["nearest_candidate_m"] or 0))

    shape_counts = {k: 0 for k in SHAPES}
    hillside_counts = {"Yes": 0, "No": 0, "Unknown": 0}
    near_counts = {"Yes": 0, "No": 0, "Unknown": 0}
    for d in labels.values():
        shape_counts[d["shape"]] = shape_counts.get(d["shape"], 0) + 1
        hillside_counts[d["hillside"]] = hillside_counts.get(d["hillside"], 0) + 1
        near_counts[d["near_mountains"]] = near_counts.get(d["near_mountains"], 0) + 1
    prereg = _prereg_check(site_rows, hillside_counts, near_counts)

    result = {
        "job_id": job_id,
        "job_name": job.get("title"),
        "method_version": METHOD_VERSION,
        "candidates_on_done_tiles": len(cands),
        "newly_labelled": len(new_rows),
        "already_labelled": len(existing),
        "not_labelled": failures,
        "shape_counts": shape_counts,
        "hillside_counts": hillside_counts,
        "near_mountains_counts": near_counts,
        "prereg_check": prereg,
        "sites": site_rows,
        "dem_files": {os.path.basename(p): h for p, h in dem_hashes.items()},
        "parameters": params,
        "done_tiles": len(done),
        "total_tiles": len(tiles),
    }
    try:
        db.log_timeline_event(
            db_root, job["grand_project_id"], "TERRAIN_CONTEXT_LABELS_RUN",
            related_entity_type="wide_area_search_job", related_entity_id=job_id,
            description=("F3 terrain labels %s: %d candidates on %d/%d DONE tiles, %d newly labelled, "
                         "%d already labelled, %d not labelled. Shapes: %s. Hillside: %s. "
                         "Near mountains: %s. Pre-registered check 1: Hillside=Yes at %d of %d "
                         "recorded site points (pass if <= %d) -> %s."
                         % (METHOD_VERSION, len(cands), len(done), len(tiles), len(new_rows),
                            len(existing), sum(failures.values()),
                            ", ".join("%s %d" % (k, v) for k, v in shape_counts.items() if v),
                            ", ".join("%s %d" % (k, v) for k, v in hillside_counts.items() if v),
                            ", ".join("%s %d" % (k, v) for k, v in near_counts.items() if v),
                            prereg["sites_hillside_yes"], prereg["sites_total"],
                            PREREG_MAX_HILLSIDE_SITES, prereg["check1"])))
    except Exception as e:
        result["timeline_warning"] = "labels saved, but the timeline event failed: %s" % e
    result["report_text"] = _report_text(result)
    return result


def _prereg_check(site_rows: List[Dict[str, Any]], hillside_counts: Dict[str, int],
                  near_counts: Dict[str, int]) -> Dict[str, Any]:
    """Counts for the pre-registered f3-v2 checks. Reports only -- applies
    nothing. check1 is PASS / FAIL / NOT EVALUABLE (no site points)."""
    n_sites = len(site_rows)
    s_yes = sum(1 for s in site_rows if s["at_site"].get("hillside") == "Yes")
    s_unk = sum(1 for s in site_rows if s["at_site"].get("hillside") not in ("Yes", "No"))
    s_near = sum(1 for s in site_rows if s["at_site"].get("near_mountains") == "Yes")
    if n_sites == 0:
        check1 = "NOT EVALUABLE"
    else:
        check1 = "PASS" if s_yes <= PREREG_MAX_HILLSIDE_SITES else "FAIL"
    n_cand = sum(hillside_counts.values())
    known = hillside_counts.get("Yes", 0) + hillside_counts.get("No", 0)
    share = (hillside_counts.get("Yes", 0) / n_cand) if n_cand else None
    near_share = (near_counts.get("Yes", 0) / n_cand) if n_cand else None
    return {"sites_total": n_sites, "sites_hillside_yes": s_yes, "sites_hillside_unknown": s_unk,
            "sites_near_mountains_yes": s_near, "check1": check1,
            "candidates_labelled": n_cand, "candidates_hillside_known": known,
            "hillside_yes_share": share, "near_mountains_yes_share": near_share,
            "worth_automating": (None if share is None else share >= PREREG_MIN_USEFUL_SHARE)}


def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else "%.1f%%" % (100.0 * x)


def _fmt_at(a: Dict[str, Any]) -> str:
    if a.get("error"):
        return "no DEM (%s)" % a["error"]
    s = a["shape"]
    bits = []
    if a.get("peak_local_relief_m") is not None:
        bits.append("%+.1f m" % a["peak_local_relief_m"])
    if a.get("patch_cells") is not None:
        bits.append("%d cells" % a["patch_cells"])
    if a.get("elongation") is not None:
        bits.append("elong %.1f" % a["elongation"])
    if bits:
        s += " (" + ", ".join(bits) + ")"
    s += "; hillside %s" % a.get("hillside")
    if a.get("median_slope_within_250m_deg") is not None:
        s += " (median slope %.2f deg" % a["median_slope_within_250m_deg"]
        if a.get("dem_coverage_250m") is not None and a["dem_coverage_250m"] < 1.0:
            s += ", DEM %.0f%%" % (100.0 * a["dem_coverage_250m"])
        s += ")"
    s += "; near mountains %s" % a.get("near_mountains")
    if a.get("relief_within_2km_m") is not None:
        s += " (range %.0f m, median slope %s deg)" % (
            a["relief_within_2km_m"],
            "n/a" if a.get("median_slope_within_2km_deg") is None else "%.1f" % a["median_slope_within_2km_deg"])
    return s


def _report_text(r: Dict[str, Any]) -> str:
    L = []
    L.append("Job %s  %s" % (r["job_id"][:6], r.get("job_name") or ""))
    L.append("Method %s: shape, hillside and near-mountains context read from the OFFLINE DEM only. "
             "Derived from the same DEM the detector used -- it describes the ground, "
             "it is NOT evidence of a site, and it changes no status or confidence."
             % r["method_version"])
    L.append("")
    L.append("Candidates on %d/%d DONE tiles: %d" % (r["done_tiles"], r["total_tiles"],
                                                    r["candidates_on_done_tiles"]))
    L.append("  newly labelled: %d, already labelled (same method): %d"
             % (r["newly_labelled"], r["already_labelled"]))
    if r["not_labelled"]:
        L.append("  NOT labelled:")
        for reason, n in r["not_labelled"].items():
            L.append("    %d  %s" % (n, reason))
    L.append("")
    L.append("Shape (all labelled candidates):")
    for k, v in r["shape_counts"].items():
        L.append("  %-20s %d" % (k, v))
    pc = r["prereg_check"]
    L.append("Hillside (median slope within 250 m; label only, rejects nothing):")
    for k, v in r["hillside_counts"].items():
        L.append("  %-20s %d" % (k, v))
    L.append("  share Yes: %s of labelled candidates" % _pct(pc["hillside_yes_share"]))
    L.append("Near mountains (old f3-v1 Mountain flag; context only, never a rule):")
    for k, v in r["near_mountains_counts"].items():
        L.append("  %-20s %d" % (k, v))
    L.append("  share Yes: %s of labelled candidates" % _pct(pc["near_mountains_yes_share"]))
    L.append("")
    if r["sites"]:
        L.append("Recorded sites in the scanned area (gazetteer points):")
        for s in r["sites"]:
            L.append("  %s" % s["name"])
            L.append("    at the point: %s" % _fmt_at(s["at_site"]))
            if s["nearest_candidate_m"] is not None:
                lab = s["nearest_candidate_label"]
                L.append("    nearest candidate %.0f m: %s" % (
                    s["nearest_candidate_m"],
                    "not labelled" if lab is None else "%s; hillside %s; near mountains %s"
                    % (lab["shape"], lab["hillside"], lab["near_mountains"])))
        L.append("  (gazetteer points were placed by eye; the label AT the point can")
        L.append("   miss a feature a few cells away, so both lines are shown)")
    else:
        L.append("No recorded gazetteer sites inside the scanned area.")
    L.append("")
    L.append("f3-v2 pre-registered checks (the decision applies to the Kangavar test job;")
    L.append("on any other job these lines are information only; nothing is applied):")
    L.append("  1. Hillside = Yes at %d of %d recorded site points (pass if <= %d): %s"
             % (pc["sites_hillside_yes"], pc["sites_total"], PREREG_MAX_HILLSIDE_SITES, pc["check1"]))
    if pc["sites_hillside_unknown"]:
        L.append("     (%d site point(s) Hillside Unknown -- not enough DEM around them)"
                 % pc["sites_hillside_unknown"])
    L.append("  2. Hillside = Yes on %s of candidates (< %.0f%% = not worth automating)%s"
             % (_pct(pc["hillside_yes_share"]), 100.0 * PREREG_MIN_USEFUL_SHARE,
                "" if pc["worth_automating"] is None else
                (": at or above the 5% floor (a rule could matter)" if pc["worth_automating"]
                 else ": below the 5% floor -- not worth automating")))
    L.append("  3. Near mountains = Yes at %d of %d site points, on %s of candidates"
             % (pc["sites_near_mountains_yes"], pc["sites_total"], _pct(pc["near_mountains_yes_share"])))
    L.append("  Even a PASS here does not make Hillside a rule: a second fresh job")
    L.append("  (Susiana plain) must pass too, and it would apply to mound/tell searches only.")
    L.append("")
    p = r["parameters"]
    L.append("Parameters (fixed 2026-09-30): local relief = elevation minus mean within %.0f m; "
             "shape needs |relief| >= %.1f m; window +/- %.0f m; < %d cells = too small; "
             "elongation >= %.0f = linear; ring = %d of 8 sectors at %.0f-%.0f m; "
             "hillside = median slope > %.0f deg within %.0f m (Unknown below %.0f%% DEM); "
             "near mountains = range > %.0f m or median slope > %.0f deg within %.0f m."
             % (p["local_relief_radius_m"], p["relief_threshold_m"], p["shape_half_window_m"],
                p["min_shape_cells"], p["linear_elongation"], p["ring_min_sectors_of_8"],
                p["ring_annulus_m"][0], p["ring_annulus_m"][1],
                p["hillside_median_slope_deg"], p["hillside_radius_m"],
                100.0 * p["hillside_min_valid_fraction"],
                p["near_mountains_relief_m"], p["near_mountains_median_slope_deg"],
                p["near_mountains_radius_m"]))
    L.append("Resolution: Copernicus GLO-30 cells are ~30 m, so features narrower than "
             "~90 m cannot be shaped and are reported as such, not guessed.")
    if r["dem_files"]:
        L.append("DEM files hashed this run:")
        for name, h in sorted(r["dem_files"].items()):
            L.append("  %s  sha256 %s" % (name, h))
    if r.get("timeline_warning"):
        L.append("WARNING: " + r["timeline_warning"])
    return "\n".join(L)


def label_job_json(db_root: str, job_ref: str) -> str:
    try:
        return json.dumps(label_job(db_root, job_ref))
    except (TerrainLabelError, review.ReviewError) as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": "terrain labels failed: %s" % e})
