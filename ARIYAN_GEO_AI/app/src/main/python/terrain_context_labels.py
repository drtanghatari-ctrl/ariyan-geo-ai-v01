"""
terrain_context_labels.py

Part of ARIYAN GEO AI -- F3 terrain context labels (added 2026-09-30,
parameters approved by the user BEFORE any known site was looked at).

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
2. MOUNTAIN FLAG, within MOUNTAIN_RADIUS_M of the candidate:
   Yes if elevation range > MOUNTAIN_RELIEF_M or median slope (Horn 1981,
   the same formula terrain_derivatives.py uses) > MOUNTAIN_MEDIAN_SLOPE_DEG;
   No if neither and at least MIN_VALID_FRACTION of the disc has DEM data;
   Unknown otherwise. A LABEL ONLY: it never rejects anything. It may
   become an auto-Rejected rule only with the user's approval after
   calibration.

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

METHOD_VERSION = "f3-v1"
EVIDENCE_TYPE = "TERRAIN_CONTEXT"

# ---- Parameters approved 2026-09-30, fixed before any known site was run ----
SHAPE_HALF_WINDOW_M = 300.0        # ~600 x 600 m shape window
LOCAL_RELIEF_RADIUS_M = 150.0      # mean-elevation disc radius
RELIEF_THRESHOLD_M = 1.5           # |local relief| needed to count as shape
MIN_SHAPE_CELLS = 3                # smaller patches -> "Too small to shape"
LINEAR_ELONGATION = 3.0            # length/width at or above -> "Linear"
RING_INNER_M = 45.0                # ring search annulus
RING_OUTER_M = 250.0
RING_MIN_SECTORS = 6               # of 8 compass sectors
SEED_SEARCH_CELLS = 1              # candidate cell + its 8 neighbours
MOUNTAIN_RADIUS_M = 2000.0
MOUNTAIN_RELIEF_M = 150.0
MOUNTAIN_MEDIAN_SLOPE_DEG = 15.0
MIN_VALID_FRACTION = 0.9           # DEM coverage needed to say "No"
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
        "mountain_radius_m": MOUNTAIN_RADIUS_M,
        "mountain_relief_m": MOUNTAIN_RELIEF_M,
        "mountain_median_slope_deg": MOUNTAIN_MEDIAN_SLOPE_DEG,
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


def mountain_flag(z: np.ndarray, ci: int, cj: int, dx: float, dy: float) -> Dict[str, Any]:
    h, w = z.shape
    ii, jj = np.mgrid[0:h, 0:w]
    disc = np.hypot((ii - ci) * dy, (jj - cj) * dx) <= MOUNTAIN_RADIUS_M
    zd = z[disc]
    valid = ~np.isnan(zd)
    frac = float(valid.mean()) if zd.size else 0.0
    if not valid.any():
        return {"mountain_flag": "Unknown", "dem_coverage_2km": 0.0}
    rng = float(np.nanmax(zd) - np.nanmin(zd))
    sl = horn_slope_deg(z, dx, dy)[disc]
    sl = sl[~np.isnan(sl)]
    med = float(np.median(sl)) if sl.size else float("nan")
    yes = rng > MOUNTAIN_RELIEF_M or (not math.isnan(med) and med > MOUNTAIN_MEDIAN_SLOPE_DEG)
    flag = "Yes" if yes else ("No" if frac >= MIN_VALID_FRACTION else "Unknown")
    return {"mountain_flag": flag,
            "relief_within_2km_m": round(rng, 1),
            "median_slope_within_2km_deg": None if math.isnan(med) else round(med, 1),
            "dem_coverage_2km": round(frac, 3)}


def analyse_point(storage_folder: str, offline_data_root: str, lat: float, lon: float) -> Dict[str, Any]:
    """Full F3 description of one point. Reads ONE window (the mountain disc)
    and cuts the shape window out of it (same lattice)."""
    half = max(MOUNTAIN_RADIUS_M, SHAPE_HALF_WINDOW_M + LOCAL_RELIEF_RADIUS_M) + 50.0
    win = read_window(storage_folder, offline_data_root, lat, lon, half)
    if "error" in win:
        return {"shape": "No DEM", "mountain_flag": "Unknown", "error": win["error"]}
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
    out.update(mountain_flag(z, ci, cj, dx, dy))
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
            "mountain_flag": res["mountain_flag"],
        }
        for k in ("peak_local_relief_m", "centre_local_relief_m", "patch_cells", "patch_area_m2",
                  "elongation", "patch_reaches_window_edge", "ring_sectors_of_8",
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
              else {"shape": "No DEM", "mountain_flag": "Unknown", "error": "no country package"})
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
            "at_site": {k: at.get(k) for k in ("shape", "mountain_flag", "peak_local_relief_m",
                                              "patch_cells", "elongation", "relief_within_2km_m",
                                              "median_slope_within_2km_deg", "error")},
            "nearest_candidate_id": near["id"] if near else None,
            "nearest_candidate_m": round(best, 1) if best is not None else None,
            "nearest_candidate_label": ({"shape": labels[near["id"]]["shape"],
                                         "mountain_flag": labels[near["id"]]["mountain_flag"]}
                                        if near and near["id"] in labels else None),
        })
    site_rows.sort(key=lambda r: (r["nearest_candidate_m"] is None, r["nearest_candidate_m"] or 0))

    shape_counts = {k: 0 for k in SHAPES}
    mountain_counts = {"Yes": 0, "No": 0, "Unknown": 0}
    for d in labels.values():
        shape_counts[d["shape"]] = shape_counts.get(d["shape"], 0) + 1
        mountain_counts[d["mountain_flag"]] = mountain_counts.get(d["mountain_flag"], 0) + 1

    result = {
        "job_id": job_id,
        "job_name": job.get("title"),
        "method_version": METHOD_VERSION,
        "candidates_on_done_tiles": len(cands),
        "newly_labelled": len(new_rows),
        "already_labelled": len(existing),
        "not_labelled": failures,
        "shape_counts": shape_counts,
        "mountain_counts": mountain_counts,
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
                         "%d already labelled, %d not labelled. Shapes: %s. Mountain flag: %s."
                         % (METHOD_VERSION, len(cands), len(done), len(tiles), len(new_rows),
                            len(existing), sum(failures.values()),
                            ", ".join("%s %d" % (k, v) for k, v in shape_counts.items() if v),
                            ", ".join("%s %d" % (k, v) for k, v in mountain_counts.items() if v))))
    except Exception as e:
        result["timeline_warning"] = "labels saved, but the timeline event failed: %s" % e
    result["report_text"] = _report_text(result)
    return result


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
    s += "; mountain %s" % a["mountain_flag"]
    if a.get("relief_within_2km_m") is not None:
        s += " (range %.0f m, median slope %s deg)" % (
            a["relief_within_2km_m"],
            "n/a" if a.get("median_slope_within_2km_deg") is None else "%.1f" % a["median_slope_within_2km_deg"])
    return s


def _report_text(r: Dict[str, Any]) -> str:
    L = []
    L.append("Job %s  %s" % (r["job_id"][:6], r.get("job_name") or ""))
    L.append("Method %s: shape and mountain context read from the OFFLINE DEM only. "
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
    L.append("Mountain flag (label only, rejects nothing):")
    for k, v in r["mountain_counts"].items():
        L.append("  %-20s %d" % (k, v))
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
                    "not labelled" if lab is None else "%s; mountain %s" % (lab["shape"], lab["mountain_flag"])))
        L.append("  (gazetteer points were placed by eye; the label AT the point can")
        L.append("   miss a feature a few cells away, so both lines are shown)")
    else:
        L.append("No recorded gazetteer sites inside the scanned area.")
    L.append("")
    p = r["parameters"]
    L.append("Parameters (fixed 2026-09-30): local relief = elevation minus mean within %.0f m; "
             "shape needs |relief| >= %.1f m; window +/- %.0f m; < %d cells = too small; "
             "elongation >= %.0f = linear; ring = %d of 8 sectors at %.0f-%.0f m; "
             "mountain = range > %.0f m or median slope > %.0f deg within %.0f m."
             % (p["local_relief_radius_m"], p["relief_threshold_m"], p["shape_half_window_m"],
                p["min_shape_cells"], p["linear_elongation"], p["ring_min_sectors_of_8"],
                p["ring_annulus_m"][0], p["ring_annulus_m"][1], p["mountain_relief_m"],
                p["mountain_median_slope_deg"], p["mountain_radius_m"]))
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
