"""
field_data.py -- ef-v4a (2026-10-31): REAL field data in the evidence volume.
First method: GPR depth slices. (ERT sections follow in ef-v4b.)

Import: the user copies a survey export into
    <offline_data>/field_data/inbox/
as plain text, one point per line:  x, y, depth, value
  x, y   : UTM easting/northing in metres (the map's own UTM zone) or
           longitude/latitude in degrees -- the user says which at import
  depth  : metres BELOW the ground, positive downward
  value  : the survey software's value (e.g. GPR amplitude); units as typed
Separators: comma, semicolon, tab or spaces. Lines that are not four numbers
(headers, comments) are skipped and counted.

What the app does with it -- and does NOT do:
  * the original file is copied unchanged into field_data/store/ under its
    SHA-256, so the provenance can always point at the exact bytes;
  * points are BINNED on the dataset's own spacing (detected from the data):
    a bin holds the mean of the points that fall in it; a bin with no point
    stays empty (hatched). Nothing is interpolated or smoothed;
  * depth slices are the file's own depths when there are at most
    MAX_OWN_DEPTHS of them, otherwise 0.5 m bins (said so on screen);
  * for display on the north-up map, each output pixel takes the bin it falls
    in (nearest bin, values unchanged) through a local UTM <-> lat/lon affine
    fitted over the dataset's extent; the fit error is reported;
  * one grey ramp per dataset (2-98 percentile of ALL its values) so slices
    are comparable as depth increases.
MEASURED means: these are the user's survey numbers. Interpreting them stays
with the user; nothing here changes a candidate, review, status or confidence.

ef-v4b (2026-10-31): ERT sections. A text export of an inverted section,
one model cell per line:  distance, depth, value
  distance : metres along the line from its START
  depth    : metres below the ground, positive downward
  value    : resistivity (ohm m) -- coloured on a log10 scale when every value
             is positive, otherwise on a linear scale (said so on screen)
The line's start and end are given at import (the open profile line A-A' or
typed coordinates). The section is binned on its own distance spacing and its
own depth layers (layer edges halfway between the file's depths); the image
used for drawing has uniform rows of the thinnest layer, each pixel taking
the layer it lies in (values unchanged, nothing interpolated). It is drawn on
the 3D cut face when the cut follows the same line.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import grand_project_db as db
import utm_projection as up

VERSION = "fd-v2"
MAX_POINTS = 3_000_000
MAX_BINS_PER_SIDE = 1500
MAX_OWN_DEPTHS = 60
DEPTH_BIN_M = 0.5
STATEMENT = ("MEASURED field data (your survey file, unchanged). Shown binned on its own spacing; empty bins "
             "are hatched; nothing is interpolated. Interpretation is yours; nothing here changes status "
             "or confidence.")

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS field_dataset (
        id               TEXT PRIMARY KEY,
        candidate_id     TEXT NOT NULL,
        grand_project_id TEXT NOT NULL,
        created_at       TEXT NOT NULL,
        method           TEXT NOT NULL,
        label            TEXT NOT NULL,
        value_units      TEXT NOT NULL DEFAULT '',
        source_filename  TEXT NOT NULL,
        file_sha256      TEXT NOT NULL,
        stored_path      TEXT NOT NULL,
        coords           TEXT NOT NULL,
        meta_json        TEXT NOT NULL,
        version          TEXT NOT NULL,
        FOREIGN KEY (candidate_id) REFERENCES candidate(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS field_dataset_event (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        dataset_id  TEXT NOT NULL,
        event       TEXT NOT NULL,
        reason      TEXT NOT NULL DEFAULT '',
        occurred_at TEXT NOT NULL,
        FOREIGN KEY (dataset_id) REFERENCES field_dataset(id)
    )
    """,
]

_CACHE: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# folders and storage
# ---------------------------------------------------------------------------

def inbox_dir(db_root: str) -> str:
    return os.path.join(db_root, "field_data", "inbox")


def store_dir(db_root: str) -> str:
    return os.path.join(db_root, "field_data", "store")


def _conn(db_root: str):
    conn = db.get_connection(db_root)
    db.initialize_schema(conn)
    for stmt in _SCHEMA:
        conn.execute(stmt)
    return conn


# ---------------------------------------------------------------------------
# pure parts (tested directly)
# ---------------------------------------------------------------------------

_SPLIT = re.compile(r"[,;\t ]+")


def parse_points(text: str, ncols: int = 4) -> Tuple[np.ndarray, int]:
    """(N, ncols) float array (GPR: x, y, depth, value; ERT: distance, depth,
    value) and the number of skipped lines."""
    rows: List[List[float]] = []
    skipped = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p for p in _SPLIT.split(line) if p]
        if len(parts) < ncols:
            skipped += 1
            continue
        try:
            vals = [float(p) for p in parts[:ncols]]
        except ValueError:
            skipped += 1
            continue
        if not all(math.isfinite(v) for v in vals):
            skipped += 1
            continue
        rows.append(vals)
        if len(rows) > MAX_POINTS:
            raise ValueError("more than %d points; split the file" % MAX_POINTS)
    if not rows:
        return np.zeros((0, ncols)), skipped
    return np.asarray(rows, dtype=np.float64), skipped


def spacing(values: np.ndarray) -> float:
    """The dataset's own grid step along one axis: median of the gaps between
    distinct coordinates (rounded to 1 mm)."""
    u = np.unique(np.round(values, 3))
    if u.size < 2:
        return 0.0
    d = np.diff(u)
    d = d[d > 1e-6]
    return float(np.median(d)) if d.size else 0.0


def depth_slices(depths: np.ndarray) -> Tuple[np.ndarray, str]:
    """Slice edges. The file's own depths when few enough (each its own slice,
    edges halfway between), otherwise DEPTH_BIN_M bins."""
    u = np.unique(np.round(depths, 2))
    if u.size <= MAX_OWN_DEPTHS:
        if u.size == 1:
            return np.array([u[0] - 0.005, u[0] + 0.005]), "own"
        mids = (u[:-1] + u[1:]) / 2.0
        first = u[0] - (mids[0] - u[0])
        last = u[-1] + (u[-1] - mids[-1])
        return np.concatenate([[max(0.0, first)], mids, [last]]), "own"
    top = math.floor(float(depths.min()) / DEPTH_BIN_M) * DEPTH_BIN_M
    bot = math.ceil(float(depths.max()) / DEPTH_BIN_M + 1e-9) * DEPTH_BIN_M
    return np.arange(top, bot + DEPTH_BIN_M / 2, DEPTH_BIN_M), "binned"


def bin_volume(e: np.ndarray, n: np.ndarray, d: np.ndarray, v: np.ndarray) -> Dict[str, Any]:
    """Mean value per (depth slice, row, col) on the data's own spacing; NaN where empty."""
    dx, dy = spacing(e), spacing(n)
    if dx <= 0 or dy <= 0:
        raise ValueError("cannot find a grid spacing in the file (all points on one line?)")
    e0, n1 = float(e.min()), float(n.max())
    cols = np.round((e - e0) / dx).astype(np.int64)
    rows = np.round((n1 - n) / dy).astype(np.int64)        # row 0 = north
    w, h = int(cols.max()) + 1, int(rows.max()) + 1
    if w > MAX_BINS_PER_SIDE or h > MAX_BINS_PER_SIDE:
        raise ValueError("survey grid %d x %d bins is larger than %d per side" % (w, h, MAX_BINS_PER_SIDE))
    edges, mode = depth_slices(d)
    ks = np.clip(np.searchsorted(edges, d, side="right") - 1, 0, len(edges) - 2)
    k = len(edges) - 1
    total = np.zeros((k, h, w)); count = np.zeros((k, h, w))
    np.add.at(total, (ks, rows, cols), v)
    np.add.at(count, (ks, rows, cols), 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(count > 0, total / count, np.nan)
    return {"values": mean, "count": count.astype(np.int32), "edges": edges, "depth_mode": mode,
            "dx": dx, "dy": dy, "e0": e0, "n1": n1, "w": w, "h": h}


def fit_affine(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Least-squares 2-D affine dst ~ [src, 1] @ A (A is 3 x 2)."""
    m = np.hstack([src, np.ones((src.shape[0], 1))])
    a, *_ = np.linalg.lstsq(m, dst, rcond=None)
    return a


def grey(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """RGBA greyscale; NaN -> transparent (the map hatches it)."""
    out = np.zeros(values.shape + (4,), dtype=np.uint8)
    ok = np.isfinite(values)
    t = np.where(ok, np.clip((np.nan_to_num(values) - lo) / (hi - lo if hi > lo else 1.0), 0.0, 1.0), 0.0)
    g = (25 + t * 230).astype(np.uint8)
    out[..., 0] = g; out[..., 1] = g; out[..., 2] = g
    out[..., 3] = np.where(ok, 255, 0).astype(np.uint8)
    return out


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

def list_inbox(db_root: str) -> List[Dict[str, Any]]:
    d = inbox_dir(db_root)
    os.makedirs(d, exist_ok=True)
    out = []
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            out.append({"name": name, "bytes": os.path.getsize(p)})
    return out


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def import_gpr(db_root: str, candidate_id: str, filename: str, coords: str, utm_zone: int, northern: bool,
               label: str, value_units: str = "") -> Dict[str, Any]:
    if coords not in ("UTM", "LATLON"):
        raise ValueError("coordinates must be UTM or LATLON")
    if not (label or "").strip():
        raise ValueError("a label is required (for example: GPR grid 1, 2026 survey)")
    if os.path.basename(filename) != filename:
        raise ValueError("pick a file from the inbox")
    src = os.path.join(inbox_dir(db_root), filename)
    if not os.path.isfile(src):
        raise LookupError("file not found in the inbox")
    cand = db.get_candidate(db_root, candidate_id)
    if cand is None:
        raise LookupError("candidate not found")
    with open(src, "r", encoding="utf-8", errors="replace") as f:
        pts, skipped = parse_points(f.read())
    if pts.shape[0] < 4:
        raise ValueError("fewer than 4 data lines of x, y, depth, value found (%d lines skipped)" % skipped)
    if (pts[:, 2] < 0).any():
        raise ValueError("negative depths found: depth must be metres below the ground, positive downward")
    if coords == "LATLON":
        lon, lat = pts[:, 0], pts[:, 1]
        if np.abs(lat).max() > 90 or np.abs(lon).max() > 180:
            raise ValueError("values are not longitude/latitude in degrees (x = longitude, y = latitude)")
        sample = np.linspace(0, pts.shape[0] - 1, min(400, pts.shape[0])).astype(int)
        en = np.array([[p.easting, p.northing] for p in
                       (up.utm_forward(float(lat[i]), float(lon[i]), utm_zone) for i in sample)])
        a = fit_affine(np.column_stack([lon[sample], lat[sample]]), en)
        e = np.column_stack([lon, lat, np.ones_like(lon)]) @ a
        east, north = e[:, 0], e[:, 1]
    else:
        east, north = pts[:, 0], pts[:, 1]
        if np.abs(north).max() < 1000 or np.abs(east).max() < 1000:
            raise ValueError("values do not look like UTM metres; choose Latitude/Longitude if they are degrees")
    vol = bin_volume(east, north, pts[:, 2], pts[:, 3])
    vals = pts[:, 3]
    lo, hi = (float(x) for x in np.percentile(vals, [2.0, 98.0]))
    # corners of the dataset (bin edges) in lat/lon
    corners_en = [(vol["e0"] - vol["dx"] / 2, vol["n1"] + vol["dy"] / 2),
                  (vol["e0"] + (vol["w"] - 0.5) * vol["dx"], vol["n1"] + vol["dy"] / 2),
                  (vol["e0"] + (vol["w"] - 0.5) * vol["dx"], vol["n1"] - (vol["h"] - 0.5) * vol["dy"]),
                  (vol["e0"] - vol["dx"] / 2, vol["n1"] - (vol["h"] - 0.5) * vol["dy"])]
    corners_ll = [list(up.utm_inverse(x, y, utm_zone, northern)) for x, y in corners_en]   # (lat, lon)
    did = uuid.uuid4().hex
    sd = store_dir(db_root)
    os.makedirs(sd, exist_ok=True)
    sha = _sha256(src)
    stored = os.path.join(sd, "%s_%s" % (sha[:16], filename))
    if not os.path.exists(stored):
        shutil.copyfile(src, stored)
    np.savez_compressed(os.path.join(sd, did + ".npz"), values=vol["values"], count=vol["count"],
                        edges=vol["edges"])
    meta = {"utm_zone": int(utm_zone), "northern": bool(northern), "dx_m": vol["dx"], "dy_m": vol["dy"],
            "e0": vol["e0"], "n1": vol["n1"], "w": vol["w"], "h": vol["h"],
            "depth_edges_m": [round(float(x), 3) for x in vol["edges"]], "depth_mode": vol["depth_mode"],
            "points": int(pts.shape[0]), "lines_skipped": int(skipped),
            "value_lo": lo, "value_hi": hi, "value_min": float(vals.min()), "value_max": float(vals.max()),
            "corners_latlon": corners_ll,
            "filled_bins": int((vol["count"] > 0).sum()), "bins": int(vol["count"].size)}
    now = db._now_iso()
    conn = _conn(db_root)
    try:
        with conn:
            conn.execute(
                "INSERT INTO field_dataset (id, candidate_id, grand_project_id, created_at, method, label, value_units, "
                "source_filename, file_sha256, stored_path, coords, meta_json, version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (did, candidate_id, cand["grand_project_id"], now, "GPR", label.strip(), (value_units or "").strip(),
                 filename, sha, stored, coords, json.dumps(meta), VERSION))
            conn.execute("INSERT INTO field_dataset_event (dataset_id, event, reason, occurred_at) "
                         "VALUES (?, 'IMPORTED', '', ?)", (did, now))
    finally:
        conn.close()
    db.log_timeline_event(db_root, cand["grand_project_id"], "FIELD_DATA_IMPORTED", "candidate", candidate_id,
                          "MEASURED GPR file '%s' (sha256 %s), %d points, %d depth slices, bins %.2f x %.2f m. "
                          "Interpretation is the user's; status and confidence unchanged."
                          % (filename, sha[:12], pts.shape[0], len(vol["edges"]) - 1, vol["dx"], vol["dy"]))
    return {"id": did, "meta": meta, "file_sha256": sha}


def withdraw(db_root: str, dataset_id: str, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("a reason is required to withdraw a dataset")
    conn = _conn(db_root)
    try:
        row = conn.execute("SELECT candidate_id, grand_project_id, label FROM field_dataset WHERE id = ?",
                           (dataset_id,)).fetchone()
        if row is None:
            raise LookupError("dataset not found")
        with conn:
            conn.execute("INSERT INTO field_dataset_event (dataset_id, event, reason, occurred_at) "
                         "VALUES (?, 'WITHDRAWN', ?, ?)", (dataset_id, reason.strip(), db._now_iso()))
    finally:
        conn.close()
    db.log_timeline_event(db_root, row["grand_project_id"], "FIELD_DATA_WITHDRAWN", "candidate", row["candidate_id"],
                          "withdrawn by user: '%s'. Reason: %s (the file stays stored)" % (row["label"], reason.strip()))


def list_for_candidate(db_root: str, candidate_id: str, include_withdrawn: bool = False) -> List[Dict[str, Any]]:
    conn = _conn(db_root)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM field_dataset WHERE candidate_id = ? ORDER BY created_at", (candidate_id,))]
        for r in rows:
            r["meta"] = json.loads(r.pop("meta_json"))
            ev = conn.execute("SELECT event, reason FROM field_dataset_event WHERE dataset_id = ? "
                              "ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
            r["status"] = "WITHDRAWN" if ev is not None and ev["event"] == "WITHDRAWN" else "ACTIVE"
            r["status_reason"] = ev["reason"] if ev is not None and ev["event"] == "WITHDRAWN" else ""
    finally:
        conn.close()
    return rows if include_withdrawn else [r for r in rows if r["status"] == "ACTIVE"]


# ---------------------------------------------------------------------------
# display: one depth slice as an overlay on the Final Image window
# ---------------------------------------------------------------------------

def _dataset(db_root: str, dataset_id: str) -> Dict[str, Any]:
    with _LOCK:
        c = _CACHE.get(dataset_id)
    if c is not None:
        return c
    conn = _conn(db_root)
    try:
        r = conn.execute("SELECT * FROM field_dataset WHERE id = ?", (dataset_id,)).fetchone()
    finally:
        conn.close()
    if r is None:
        raise LookupError("dataset not found")
    r = dict(r)
    meta = json.loads(r["meta_json"])
    z = np.load(os.path.join(store_dir(db_root), dataset_id + ".npz"))
    c = {"row": r, "meta": meta, "values": z["values"], "count": z["count"], "edges": z["edges"]}
    with _LOCK:
        _CACHE.clear()          # one dataset in memory at a time (phone)
        _CACHE[dataset_id] = c
    return c


def slice_image(db_root: str, dataset_id: str, k: int, grid) -> Tuple[np.ndarray, Dict[str, Any]]:
    """RGBA image of depth slice k on a north-up lat/lon raster at the data's own
    spacing, plus its placement in the Final Image grid (pixel units)."""
    c = _dataset(db_root, dataset_id)
    m = c["meta"]
    vals = c["values"]
    if not 0 <= k < vals.shape[0]:
        raise ValueError("no such depth slice")
    zone, north = m["utm_zone"], m["northern"]
    lats = [p[0] for p in m["corners_latlon"]]; lons = [p[1] for p in m["corners_latlon"]]
    lat_max, lat_min, lon_min, lon_max = max(lats), min(lats), min(lons), max(lons)
    # pixel size in degrees = the data's own spacing in metres
    lat_mid = (lat_max + lat_min) / 2.0
    dlat = m["dy_m"] / 110540.0
    dlon = m["dx_m"] / (111320.0 * math.cos(math.radians(lat_mid)))
    W = max(1, int(math.ceil((lon_max - lon_min) / dlon)))
    H = max(1, int(math.ceil((lat_max - lat_min) / dlat)))
    if W > 2 * MAX_BINS_PER_SIDE or H > 2 * MAX_BINS_PER_SIDE:
        raise ValueError("survey too large to draw")
    # local affine lat/lon -> UTM from a 5 x 5 net of exact projections; report its error
    gl = np.linspace(lon_min, lon_max, 5); gt = np.linspace(lat_min, lat_max, 5)
    net = np.array([(lo, la) for la in gt for lo in gl])
    en = np.array([[p.easting, p.northing] for p in (up.utm_forward(float(la), float(lo), zone) for lo, la in net)])
    a = fit_affine(net, en)
    fit_err = float(np.abs(np.hstack([net, np.ones((net.shape[0], 1))]) @ a - en).max())
    # each output pixel centre -> UTM -> the bin it falls in (nearest bin; values unchanged)
    jj, ii = np.mgrid[0:H, 0:W]
    plon = lon_min + (ii + 0.5) * dlon
    plat = lat_max - (jj + 0.5) * dlat
    e = a[0, 0] * plon + a[1, 0] * plat + a[2, 0]
    n = a[0, 1] * plon + a[1, 1] * plat + a[2, 1]
    col = np.round((e - m["e0"]) / m["dx_m"]).astype(np.int64)
    row = np.round((m["n1"] - n) / m["dy_m"]).astype(np.int64)
    inside = (col >= 0) & (col < m["w"]) & (row >= 0) & (row < m["h"])
    out = np.full((H, W), np.nan)
    sl = vals[k]
    out[inside] = sl[row[inside], col[inside]]
    rgba = grey(out, m["value_lo"], m["value_hi"])
    x0, y0 = grid.lonlat_to_pixel(lon_min, lat_max)
    x1, y1 = grid.lonlat_to_pixel(lon_max, lat_min)
    place = {"x0": x0, "y0": y0, "sx": (x1 - x0) / ((lon_max - lon_min) / dlon),
             "sy": (y1 - y0) / ((lat_max - lat_min) / dlat), "width": W, "height": H}
    edges = c["edges"]
    info = {"k": k, "depth_top_m": round(float(edges[k]), 3), "depth_bottom_m": round(float(edges[k + 1]), 3),
            "filled_bins": int(np.isfinite(sl).sum()), "bins": int(sl.size),
            "projection_fit_error_m": round(fit_err, 4), "placement": place}
    return rgba, info


# ---------------------------------------------------------------------------
# session bridge (Final Image screen)
# ---------------------------------------------------------------------------

def _session(session_id: str):
    import final_image_mobile as fim
    with fim._LOCK:
        s = fim._SESSIONS.get(session_id)
    if s is None:
        raise KeyError("final image session expired; reopen the image")
    return s


def _utm_of_window(s) -> Tuple[int, bool]:
    grid = s["result"]["grid"]
    h, w = grid.shape
    lon, lat = grid.pixel_to_lonlat(w / 2.0, h / 2.0)
    return up.utm_zone_for(lon), lat >= 0


def field_json(db_root: str, session_id: str) -> str:
    """Inbox files + this candidate's datasets (with their depth slices)."""
    try:
        s = _session(session_id)
        zone, north = _utm_of_window(s)
        ds = []
        grid = s["result"]["grid"]
        gh, gw = grid.shape
        for r in list_for_candidate(db_root, s["candidate_id"], include_withdrawn=True):
            m = r["meta"]
            ed = m["depth_edges_m"]
            extra = {}
            if r["method"] == "ERT":
                ln = m["line"]
                pax, pay = grid.lonlat_to_pixel(ln["a_lon"], ln["a_lat"])
                pbx, pby = grid.lonlat_to_pixel(ln["b_lon"], ln["b_lat"])
                extra = {"line_grid": [pax, pay, pbx, pby], "line_length_m": ln["length_m"],
                         "line_in_window": all(0 <= v <= lim for v, lim in ((pax, gw), (pbx, gw), (pay, gh), (pby, gh))),
                         "log_scale": m["log_scale"], "depth_bottom_m": m["depth_bottom_m"]}
            ds.append(dict(extra, **{"id": r["id"], "label": r["label"], "method": r["method"], "status": r["status"],
                       "status_reason": r["status_reason"], "created_at": r["created_at"],
                       "source_filename": r["source_filename"], "file_sha256": r["file_sha256"],
                       "value_units": r["value_units"], "points": m["points"], "dx_m": m["dx_m"], "dy_m": m["dy_m"],
                       "depth_mode": m["depth_mode"],
                       "slices": [{"k": i, "top_m": ed[i], "bottom_m": ed[i + 1]} for i in range(len(ed) - 1)],
                       "value_lo": m.get("value_lo", m.get("colour_lo")),
                       "value_hi": m.get("value_hi", m.get("colour_hi"))}))
        return json.dumps({"ok": True, "inbox": inbox_dir(db_root), "inbox_files": list_inbox(db_root),
                           "utm_zone": zone, "northern": north, "datasets": ds, "statement": STATEMENT})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def import_json(db_root: str, session_id: str, filename: str, coords: str, label: str, value_units: str = "") -> str:
    try:
        s = _session(session_id)
        zone, north = _utm_of_window(s)
        r = import_gpr(db_root, s["candidate_id"], filename, coords, zone, north, label, value_units)
        return json.dumps({"ok": True, "id": r["id"], "meta": r["meta"], "utm_zone": zone, "northern": north})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def slice_json(db_root: str, session_id: str, dataset_id: str, k: int) -> str:
    try:
        s = _session(session_id)
        rgba, info = slice_image(db_root, dataset_id, int(k), s["result"]["grid"])
        with _LOCK:
            _CACHE["__last_rgba__"] = {"rgba": rgba}
        c = _dataset(db_root, dataset_id)
        info.update({"dataset_id": dataset_id, "label": c["row"]["label"], "method": c["row"]["method"],
                     "value_units": c["row"]["value_units"], "value_lo": c["meta"]["value_lo"],
                     "value_hi": c["meta"]["value_hi"], "file_sha256": c["row"]["file_sha256"],
                     "source_filename": c["row"]["source_filename"], "statement": STATEMENT})
        # keep the image for slice_rgba(); _dataset() may have cleared the cache, so store again
        with _LOCK:
            _CACHE["__last_rgba__"] = {"rgba": rgba}
        return json.dumps(info)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def slice_rgba() -> bytes:
    with _LOCK:
        c = _CACHE.get("__last_rgba__")
    if c is None:
        raise KeyError("no field slice prepared")
    return c["rgba"].tobytes()


def withdraw_json(db_root: str, dataset_id: str, reason: str) -> str:
    try:
        withdraw(db_root, dataset_id, reason)
        return json.dumps({"ok": True})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ---------------------------------------------------------------------------
# ef-v4b: ERT sections
# ---------------------------------------------------------------------------

MAX_SECTION_PIXELS = 1024
ERT_RAMP = [(0.0, (40, 60, 200)), (0.25, (40, 170, 230)), (0.5, (60, 190, 90)),
            (0.75, (240, 210, 50)), (1.0, (220, 50, 40))]


def ramp_rgba(t: np.ndarray, ok: np.ndarray) -> np.ndarray:
    out = np.zeros(t.shape + (4,), dtype=np.uint8)
    t = np.clip(np.nan_to_num(t), 0.0, 1.0)
    xs = [p[0] for p in ERT_RAMP]
    for ch in range(3):
        out[..., ch] = np.interp(t, xs, [p[1][ch] for p in ERT_RAMP]).astype(np.uint8)
    out[..., 3] = np.where(ok, 255, 0).astype(np.uint8)
    return out


def layer_edges(depths: np.ndarray) -> np.ndarray:
    u = np.unique(np.round(depths, 3))
    if u.size == 1:
        return np.array([max(0.0, u[0] - 0.25), u[0] + 0.25])
    mids = (u[:-1] + u[1:]) / 2.0
    first = max(0.0, u[0] - (mids[0] - u[0]))
    last = u[-1] + (u[-1] - mids[-1])
    return np.concatenate([[first], mids, [last]])


def bin_section(dist: np.ndarray, depth: np.ndarray, val: np.ndarray) -> Dict[str, Any]:
    """Mean value per (layer, distance bin) on the data's own spacing; plus a
    drawing image with uniform rows (thinnest layer), each pixel = its layer."""
    dx = spacing(dist)
    if dx <= 0:
        raise ValueError("cannot find a distance spacing in the file (all points at one distance?)")
    edges = layer_edges(depth)
    nl = len(edges) - 1
    d0 = float(dist.min())
    cols = np.round((dist - d0) / dx).astype(np.int64)
    w = int(cols.max()) + 1
    if w > MAX_SECTION_PIXELS:
        raise ValueError("section has %d distance bins; at most %d" % (w, MAX_SECTION_PIXELS))
    lay = np.clip(np.searchsorted(edges, depth, side="right") - 1, 0, nl - 1)
    tot = np.zeros((nl, w)); cnt = np.zeros((nl, w))
    np.add.at(tot, (lay, cols), val); np.add.at(cnt, (lay, cols), 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        cells = np.where(cnt > 0, tot / cnt, np.nan)
    thin = float(np.min(np.diff(edges)))
    top, bottom = float(edges[0]), float(edges[-1])
    rows = int(math.ceil((bottom - top) / thin - 1e-9))
    if rows > MAX_SECTION_PIXELS:
        rows = MAX_SECTION_PIXELS
    row_depth = top + (np.arange(rows) + 0.5) * (bottom - top) / rows
    row_layer = np.clip(np.searchsorted(edges, row_depth, side="right") - 1, 0, nl - 1)
    image = cells[row_layer, :]
    return {"cells": cells, "count": cnt.astype(np.int32), "edges": edges, "dx": dx, "d0": d0,
            "d1": d0 + (w - 1) * dx, "image": image, "top": top, "bottom": bottom}


def _line_length_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    zone = up.utm_zone_for((a_lon + b_lon) / 2.0)
    pa = up.utm_forward(a_lat, a_lon, zone); pb = up.utm_forward(b_lat, b_lon, zone)
    return float(math.hypot(pb.easting - pa.easting, pb.northing - pa.northing))


def import_ert(db_root: str, candidate_id: str, filename: str, a_lat: float, a_lon: float,
               b_lat: float, b_lon: float, label: str, value_units: str = "ohm m") -> Dict[str, Any]:
    if not (label or "").strip():
        raise ValueError("a label is required (for example: ERT line 1, 2026)")
    if os.path.basename(filename) != filename:
        raise ValueError("pick a file from the inbox")
    for v, lim in ((a_lat, 90), (b_lat, 90), (a_lon, 180), (b_lon, 180)):
        if v is None or not math.isfinite(float(v)) or abs(float(v)) > lim:
            raise ValueError("the line's start and end must be valid latitude, longitude")
    src = os.path.join(inbox_dir(db_root), filename)
    if not os.path.isfile(src):
        raise LookupError("file not found in the inbox")
    cand = db.get_candidate(db_root, candidate_id)
    if cand is None:
        raise LookupError("candidate not found")
    length = _line_length_m(a_lat, a_lon, b_lat, b_lon)
    if length < 1.0:
        raise ValueError("the line's start and end are the same point")
    with open(src, "r", encoding="utf-8", errors="replace") as f:
        pts, skipped = parse_points(f.read(), ncols=3)
    if pts.shape[0] < 4:
        raise ValueError("fewer than 4 data lines of distance, depth, value found (%d lines skipped)" % skipped)
    dist, depth, val = pts[:, 0], pts[:, 1], pts[:, 2]
    if (depth < 0).any():
        raise ValueError("negative depths found: depth must be metres below the ground, positive downward")
    if (dist < 0).any() or dist.max() > length * 1.05 + 1.0:
        raise ValueError("distances run outside the line (0 to %.0f m); check the start/end or the file" % length)
    log_scale = bool((val > 0).all())
    sec = bin_section(dist, depth, val)
    cv = np.log10(val) if log_scale else val
    lo, hi = (float(x) for x in np.percentile(cv, [2.0, 98.0]))
    did = uuid.uuid4().hex
    sd = store_dir(db_root)
    os.makedirs(sd, exist_ok=True)
    sha = _sha256(src)
    stored = os.path.join(sd, "%s_%s" % (sha[:16], filename))
    if not os.path.exists(stored):
        shutil.copyfile(src, stored)
    np.savez_compressed(os.path.join(sd, did + ".npz"), values=sec["image"][None, :, :],
                        count=sec["count"][:, :], edges=sec["edges"], cells=sec["cells"])
    meta = {"line": {"a_lat": float(a_lat), "a_lon": float(a_lon), "b_lat": float(b_lat), "b_lon": float(b_lon),
                     "length_m": length},
            "dist_from_m": sec["d0"], "dist_to_m": sec["d1"], "dx_m": sec["dx"], "dy_m": sec["dx"],
            "depth_top_m": sec["top"], "depth_bottom_m": sec["bottom"],
            "depth_edges_m": [round(float(x), 3) for x in sec["edges"]], "depth_mode": "layers",
            "image_rows": int(sec["image"].shape[0]), "image_cols": int(sec["image"].shape[1]),
            "points": int(pts.shape[0]), "lines_skipped": int(skipped),
            "log_scale": log_scale, "colour_lo": lo, "colour_hi": hi,
            "value_min": float(val.min()), "value_max": float(val.max()),
            "filled_bins": int((sec["count"] > 0).sum()), "bins": int(sec["count"].size),
            "w": int(sec["image"].shape[1]), "h": int(len(sec["edges"]) - 1)}
    now = db._now_iso()
    conn = _conn(db_root)
    try:
        with conn:
            conn.execute(
                "INSERT INTO field_dataset (id, candidate_id, grand_project_id, created_at, method, label, value_units, "
                "source_filename, file_sha256, stored_path, coords, meta_json, version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (did, candidate_id, cand["grand_project_id"], now, "ERT", label.strip(), (value_units or "").strip(),
                 filename, sha, stored, "LINE", json.dumps(meta), VERSION))
            conn.execute("INSERT INTO field_dataset_event (dataset_id, event, reason, occurred_at) "
                         "VALUES (?, 'IMPORTED', '', ?)", (did, now))
    finally:
        conn.close()
    db.log_timeline_event(db_root, cand["grand_project_id"], "FIELD_DATA_IMPORTED", "candidate", candidate_id,
                          "MEASURED ERT file '%s' (sha256 %s), %d model cells, line %.0f m, %d layers to %.1f m. "
                          "Interpretation is the user's; status and confidence unchanged."
                          % (filename, sha[:12], pts.shape[0], length, len(sec["edges"]) - 1, sec["bottom"]))
    return {"id": did, "meta": meta, "file_sha256": sha}


def section_image(db_root: str, dataset_id: str) -> Tuple[np.ndarray, Dict[str, Any]]:
    c = _dataset(db_root, dataset_id)
    if c["row"]["method"] != "ERT":
        raise ValueError("not an ERT dataset")
    m = c["meta"]
    img = c["values"][0]
    ok = np.isfinite(img)
    with np.errstate(invalid="ignore", divide="ignore"):
        cv = np.log10(np.where(ok & (img > 0), img, np.nan)) if m["log_scale"] else img
    span = m["colour_hi"] - m["colour_lo"]
    t = (cv - m["colour_lo"]) / (span if span > 0 else 1.0)
    rgba = ramp_rgba(t, np.isfinite(cv))
    return rgba, m


def ert_on_line_json(db_root: str, session_id: str, ax: float, ay: float, bx: float, by: float,
                     tol_cells: float = 1.5) -> str:
    """Active ERT datasets of the candidate whose line is the open line A->A'
    (either direction, ends within tol_cells). Each comes with its drawing
    image (prepared one by one through section_rgba(i))."""
    try:
        s = _session(session_id)
        grid = s["result"]["grid"]
        out = []
        imgs = []
        for r in list_for_candidate(db_root, s["candidate_id"]):
            if r["method"] != "ERT":
                continue
            ln = r["meta"]["line"]
            pax, pay = grid.lonlat_to_pixel(ln["a_lon"], ln["a_lat"])
            pbx, pby = grid.lonlat_to_pixel(ln["b_lon"], ln["b_lat"])
            same = math.hypot(pax - ax, pay - ay) <= tol_cells and math.hypot(pbx - bx, pby - by) <= tol_cells
            rev = math.hypot(pbx - ax, pby - ay) <= tol_cells and math.hypot(pax - bx, pay - by) <= tol_cells
            if not (same or rev):
                continue
            rgba, m = section_image(db_root, r["id"])
            imgs.append(rgba)
            out.append({"id": r["id"], "label": r["label"], "reversed": bool(rev and not same),
                        "line_length_m": ln["length_m"], "dist_from_m": m["dist_from_m"], "dist_to_m": m["dist_to_m"],
                        "depth_top_m": m["depth_top_m"], "depth_bottom_m": m["depth_bottom_m"],
                        "width": int(rgba.shape[1]), "height": int(rgba.shape[0]),
                        "log_scale": m["log_scale"], "colour_lo": m["colour_lo"], "colour_hi": m["colour_hi"],
                        "value_units": r["value_units"], "file_sha256": r["file_sha256"]})
        with _LOCK:
            _CACHE["__sections__"] = {"rgba": imgs}
        return json.dumps({"ok": True, "sections": out})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def section_rgba(i: int) -> bytes:
    with _LOCK:
        c = _CACHE.get("__sections__")
    if c is None or not 0 <= int(i) < len(c["rgba"]):
        raise KeyError("no such prepared section")
    return c["rgba"][int(i)].tobytes()


def import_ert_json(db_root: str, session_id: str, filename: str, line_json: str, label: str,
                    value_units: str = "ohm m") -> str:
    """line_json: {"grid": [ax, ay, bx, by]} (the open profile line, this window's
    pixels) or {"latlon": [a_lat, a_lon, b_lat, b_lon]} (typed)."""
    try:
        s = _session(session_id)
        grid = s["result"]["grid"]
        ln = json.loads(line_json)
        if "grid" in ln:
            ax, ay, bx, by = (float(v) for v in ln["grid"])
            a_lon, a_lat = grid.pixel_to_lonlat(ax, ay)
            b_lon, b_lat = grid.pixel_to_lonlat(bx, by)
        else:
            a_lat, a_lon, b_lat, b_lon = (float(v) for v in ln["latlon"])
        r = import_ert(db_root, s["candidate_id"], filename, a_lat, a_lon, b_lat, b_lon, label, value_units)
        return json.dumps({"ok": True, "id": r["id"], "meta": r["meta"]})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
