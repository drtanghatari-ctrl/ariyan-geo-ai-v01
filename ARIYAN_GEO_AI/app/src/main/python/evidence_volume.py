"""
evidence_volume.py -- ef-v1 (2026-10-31): 3D Evidence Fusion, first build.

The ground under a candidate's Final Image window is cut into blocks: one
stored DEM cell wide, SLICE_M thick, from the ground surface down to
DEPTH_MAX_M. Every block says what is known about it and HOW:

  DERIVED       the block lies inside the raised body: ground above its local
                base level (mean ground within the relief radius), so the
                block is real material standing above the surrounding plain;
                what it is made of is unknown. From stored DEM cells only.
  HYPOTHESIZED  the user's own section hypothesis (section_hypothesis.py)
                crosses this block (one cell wide along its line, within its
                depth range). Never created by the app.
  MEASURED      reserved for real field data (GPR/ERT). ef-v1 does NOT place
                field readings in the volume: their depth fields are not yet
                mapped, so they are only counted and reported.
  UNKNOWN       everything else -- most of the volume. Nothing is drawn there.

INFERRED (rules from general archaeological knowledge) is deliberately not in
ef-v1: no sourced rule set exists in the app, and none is written from memory.

Real numbers for the candidate (DERIVED, from the DEM):
  the connected raised area containing the candidate cell (relief > 0),
  its area, the volume of material above the local base (sum of relief x cell
  area), its greatest height above base, and its E-W / N-S extent; flagged
  when the body reaches the window edge (true extent then larger).

Display only: nothing here changes a candidate, a review, a status or a
confidence. The Steward stays above this layer.

ef-v2 (2026-10-31): the user's FOOTPRINT hypotheses (footprint_hypothesis.py:
a polygon drawn on the map + a depth range) fill every block whose cell centre
lies inside the polygon, within the depth range. Section hypotheses still
count. Where two or more different hypotheses claim the same block it is
CONTESTED (magenta): the app never picks one (no artificial closure). The
summary lists, for each hypothesis, which others it overlaps.

ef-v4a (2026-10-31): real field data (field_data.py). Every DEM block that
contains at least one filled bin of an active GPR dataset at that depth gets
the MEASURED bit and is counted ("measured_in_volume"). The survey itself is
shown at its OWN resolution as a separate overlay (field_data.slice_image);
pushing centimetre data into 25-30 m blocks would average a target away.
Footprints now report how many DEM cell centres they cover.
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

import numpy as np

import final_image as fi
import final_image_mobile as fim

VERSION = "ef-v4a"
DEPTH_MAX_M = 10.0
SLICE_M = 0.5
DERIVED, HYPOTHESIZED, MEASURED = 1, 2, 4

COLOURS = {  # RGBA for a depth slice; UNKNOWN stays transparent (the map hatches it)
    "DERIVED": (237, 140, 46, 215),
    "HYPOTHESIZED": (158, 82, 242, 235),
    "CONTESTED": (230, 60, 170, 245),
}
STATEMENT = ("Evidence volume, display only. Orange = DERIVED raised material (from the DEM; make-up "
             "unknown). Purple = HYPOTHESIZED by you; magenta = CONTESTED (two or more of your hypotheses "
             "claim the same block; none is chosen). Hatched = UNKNOWN: no measurement. No field "
             "data (GPR/ERT) is placed in the volume in ef-v1. Nothing here is evidence of a buried "
             "feature and nothing changes status or confidence.")

_CACHE: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()
_MAX = 3


# ---------------------------------------------------------------------------
# pure core (tested directly)
# ---------------------------------------------------------------------------

def n_slices(depth_max_m: float = DEPTH_MAX_M, slice_m: float = SLICE_M) -> int:
    return int(round(depth_max_m / slice_m))


def build_states(relief: np.ndarray, hyp_cells: List[Dict[str, Any]],
                 depth_max_m: float = DEPTH_MAX_M, slice_m: float = SLICE_M) -> np.ndarray:
    """(H, W, K) uint8 bitmask. Slice k spans depth k*slice_m .. (k+1)*slice_m
    below the ground surface. DERIVED where the slice starts inside the raised
    body (depth top < relief). hyp_cells: [{"cells": [(r, c), ...],
    "top_m": t, "bottom_m": b}] -> HYPOTHESIZED where the slice overlaps [t, b)."""
    h, w = relief.shape
    k = n_slices(depth_max_m, slice_m)
    tops = np.arange(k) * slice_m
    rel = np.where(np.isfinite(relief), relief, -np.inf)
    states = np.zeros((h, w, k), dtype=np.uint8)
    states |= np.where(tops[None, None, :] < rel[:, :, None], DERIVED, 0).astype(np.uint8)
    for hp in hyp_cells:
        t, b = float(hp["top_m"]), float(hp["bottom_m"])
        ks = [i for i in range(k) if tops[i] < b and tops[i] + slice_m > t]
        for (r, c) in hp["cells"]:
            if 0 <= r < h and 0 <= c < w:
                for i in ks:
                    states[r, c, i] |= HYPOTHESIZED
    return states


def build_counts(shape: tuple, hyp_cells: List[Dict[str, Any]],
                 depth_max_m: float = DEPTH_MAX_M, slice_m: float = SLICE_M) -> np.ndarray:
    """(H, W, K) number of DIFFERENT hypotheses claiming each block."""
    h, w = shape
    k = n_slices(depth_max_m, slice_m)
    tops = np.arange(k) * slice_m
    counts = np.zeros((h, w, k), dtype=np.uint8)
    for hp in hyp_cells:
        t, b = float(hp["top_m"]), float(hp["bottom_m"])
        ks = [i for i in range(k) if tops[i] < b and tops[i] + slice_m > t]
        for (r, c) in set(map(tuple, hp["cells"])):
            if 0 <= r < h and 0 <= c < w:
                for i in ks:
                    counts[r, c, i] = min(255, counts[r, c, i] + 1)
    return counts


def slice_rgba(states: np.ndarray, k: int, counts: np.ndarray = None) -> np.ndarray:
    s = states[:, :, k]
    out = np.zeros(s.shape + (4,), dtype=np.uint8)
    out[(s & DERIVED) > 0] = COLOURS["DERIVED"]
    out[(s & HYPOTHESIZED) > 0] = COLOURS["HYPOTHESIZED"]       # drawn over DERIVED
    if counts is not None:
        out[counts[:, :, k] >= 2] = COLOURS["CONTESTED"]
    return out


def polygon_cells(poly_xy: List[List[float]], h: int, w: int) -> List[tuple]:
    """Cells (r, c) whose CENTRE lies inside the polygon (grid units, even-odd rule)."""
    if len(poly_xy) < 3:
        return []
    xs = [p[0] for p in poly_xy]
    ys = [p[1] for p in poly_xy]
    c0, c1 = max(0, int(math.floor(min(xs)))), min(w - 1, int(math.ceil(max(xs))))
    r0, r1 = max(0, int(math.floor(min(ys)))), min(h - 1, int(math.ceil(max(ys))))
    out = []
    n = len(poly_xy)
    for r in range(r0, r1 + 1):
        py = r + 0.5
        for c in range(c0, c1 + 1):
            px = c + 0.5
            inside = False
            j = n - 1
            for i in range(n):
                xi, yi = poly_xy[i]
                xj, yj = poly_xy[j]
                if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
                    inside = not inside
                j = i
            if inside:
                out.append((r, c))
    return out


def overlaps(hyps: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """For each hypothesis id: labels of the others sharing at least one block."""
    res: Dict[str, List[str]] = {h["id"]: [] for h in hyps}
    for i, a in enumerate(hyps):
        ca = set(map(tuple, a["cells"]))
        for b in hyps[i + 1:]:
            if a["top_m"] < b["bottom_m"] and b["top_m"] < a["bottom_m"] and ca & set(map(tuple, b["cells"])):
                res[a["id"]].append(b["label"])
                res[b["id"]].append(a["label"])
    return res


def raised_body(relief: np.ndarray, r0: int, c0: int, dx: float, dy: float) -> Dict[str, Any]:
    """Connected (4-neighbour) area of relief > 0 that contains cell (r0, c0)."""
    h, w = relief.shape
    if not (0 <= r0 < h and 0 <= c0 < w) or not np.isfinite(relief[r0, c0]) or relief[r0, c0] <= 0:
        v = None if not (0 <= r0 < h and 0 <= c0 < w) else relief[r0, c0]
        return {"present": False,
                "relief_at_candidate_m": None if v is None or not np.isfinite(v) else round(float(v), 2),
                "note": "The candidate cell is not above its local base level (no raised body here)."}
    seen = np.zeros((h, w), dtype=bool)
    q = deque([(r0, c0)])
    seen[r0, c0] = True
    cells = []
    while q:
        r, c = q.popleft()
        cells.append((r, c))
        for rr, cc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= rr < h and 0 <= cc < w and not seen[rr, cc]:
                v = relief[rr, cc]
                if np.isfinite(v) and v > 0:
                    seen[rr, cc] = True
                    q.append((rr, cc))
    rows = [r for r, _ in cells]
    cols = [c for _, c in cells]
    vals = np.array([relief[r, c] for r, c in cells])
    touches = min(rows) == 0 or min(cols) == 0 or max(rows) == h - 1 or max(cols) == w - 1
    return {
        "present": True, "cells": len(cells),
        "area_m2": round(len(cells) * dx * dy, 1),
        "volume_m3": round(float(vals.sum()) * dx * dy, 1),
        "max_height_m": round(float(vals.max()), 2),
        "relief_at_candidate_m": round(float(relief[r0, c0]), 2),
        "extent_ew_m": round((max(cols) - min(cols) + 1) * dx, 1),
        "extent_ns_m": round((max(rows) - min(rows) + 1) * dy, 1),
        "touches_window_edge": bool(touches),
        "mask_cells": cells,
    }


def line_cells(ax: float, ay: float, bx: float, by: float, f0: float, f1: float) -> List[tuple]:
    """Grid cells crossed by the part f0..f1 of the segment A->B (grid units)."""
    n = max(2, int(math.hypot(bx - ax, by - ay) * (f1 - f0) * 4))
    out = []
    for i in range(n + 1):
        f = f0 + (f1 - f0) * i / n
        cell = (int(math.floor(ay + f * (by - ay))), int(math.floor(ax + f * (bx - ax))))
        if not out or out[-1] != cell:
            out.append(cell)
    return out


# ---------------------------------------------------------------------------
# session bridge (Final Image screen)
# ---------------------------------------------------------------------------

def _field_reading_count(db_root: str, candidate_id: str) -> int:
    import grand_project_db as db
    conn = db.get_connection(db_root)
    try:
        db.initialize_schema(conn)
        return int(conn.execute("SELECT COUNT(*) FROM evidence_link WHERE candidate_id = ? "
                                "AND evidence_type IN ('GPR', 'ERT')", (candidate_id,)).fetchone()[0])
    finally:
        conn.close()


def _hyp_cells(db_root: str, s: Dict[str, Any]) -> List[Dict[str, Any]]:
    import section_hypothesis as sh
    grid = s["result"]["grid"]
    out = []
    for r in sh.list_for_candidate(db_root, s["candidate_id"]):
        ax, ay = grid.lonlat_to_pixel(r["a_lon"], r["a_lat"])
        bx, by = grid.lonlat_to_pixel(r["b_lon"], r["b_lat"])
        L = float(r["line_length_m"]) or 1.0
        f0 = max(0.0, min(1.0, r["along_from_m"] / L))
        f1 = max(0.0, min(1.0, r["along_to_m"] / L))
        if f1 <= f0:
            continue
        out.append({"id": r["id"], "label": r["label"], "top_m": r["depth_top_m"], "kind": "section",
                    "bottom_m": r["depth_bottom_m"], "cells": line_cells(ax, ay, bx, by, f0, f1)})
    # ef-v2: footprint hypotheses drawn on the map
    import footprint_hypothesis as fph
    h, w = grid.shape
    for r in fph.list_for_candidate(db_root, s["candidate_id"]):
        poly = [list(grid.lonlat_to_pixel(lon, lat)) for lat, lon in r["polygon"]]
        out.append({"id": r["id"], "label": r["label"], "top_m": r["depth_top_m"], "kind": "footprint",
                    "bottom_m": r["depth_bottom_m"], "area_m2": r["area_m2"],
                    "cells": polygon_cells(poly, h, w)})
    return out


def _mark_measured(db_root: str, s: Dict[str, Any], states: np.ndarray):
    """ef-v4a: set MEASURED on DEM blocks holding filled bins of active GPR datasets."""
    import field_data as fd
    import utm_projection as up
    grid = s["result"]["grid"]
    h, w, k = states.shape
    total = 0
    listed = []
    for r in fd.list_for_candidate(db_root, s["candidate_id"]):
        m = r["meta"]
        if r["method"] == "ERT":
            before = int(((states & MEASURED) > 0).sum())
            c = fd._dataset(db_root, r["id"])
            cnt = c["count"]                                   # (layers, distance bins)
            edges = c["edges"]
            ln = m["line"]
            ax, ay = grid.lonlat_to_pixel(ln["a_lon"], ln["a_lat"])
            bx, by = grid.lonlat_to_pixel(ln["b_lon"], ln["b_lat"])
            L = float(ln["length_m"]) or 1.0
            lays, cols = np.nonzero(cnt > 0)
            if lays.size:
                f = (m["dist_from_m"] + cols * m["dx_m"]) / L
                gx = ax + f * (bx - ax); gy = ay + f * (by - ay)
                col = np.floor(gx).astype(int); row = np.floor(gy).astype(int)
                ks = np.floor(((edges[lays] + edges[lays + 1]) / 2.0) / SLICE_M).astype(int)
                ok = (col >= 0) & (col < w) & (row >= 0) & (row < h) & (ks >= 0) & (ks < k)
                states[row[ok], col[ok], ks[ok]] |= MEASURED
            after = int(((states & MEASURED) > 0).sum())
            listed.append({"id": r["id"], "label": r["label"], "method": "ERT", "blocks": after - before})
            total = after
            continue
        c = fd._dataset(db_root, r["id"])
        cnt = c["count"]
        edges = c["edges"]
        kk, rr, cc = np.nonzero(cnt > 0)
        before = int(((states & MEASURED) > 0).sum())
        if kk.size:
            e = m["e0"] + cc * m["dx_m"]
            n = m["n1"] - rr * m["dy_m"]
            # affine UTM -> lon/lat from the dataset's own corners (exact inverse projections)
            ce = np.array([[m["e0"], m["n1"]], [m["e0"] + m["w"] * m["dx_m"], m["n1"]],
                           [m["e0"], m["n1"] - m["h"] * m["dy_m"]],
                           [m["e0"] + m["w"] * m["dx_m"], m["n1"] - m["h"] * m["dy_m"]]])
            ll = np.array([up.utm_inverse(x, y, m["utm_zone"], m["northern"]) for x, y in ce])  # lat, lon
            import field_data as _fd
            a = _fd.fit_affine(ce, ll[:, ::-1])                      # -> lon, lat
            lon = a[0, 0] * e + a[1, 0] * n + a[2, 0]
            lat = a[0, 1] * e + a[1, 1] * n + a[2, 1]
            px = (lon - grid.west) / grid.dlon
            py = (grid.north - lat) / grid.dlat
            col = np.floor(px).astype(int); row = np.floor(py).astype(int)
            mid = (edges[kk] + edges[kk + 1]) / 2.0
            ks = np.floor(mid / SLICE_M).astype(int)
            ok = (col >= 0) & (col < w) & (row >= 0) & (row < h) & (ks >= 0) & (ks < k)
            states[row[ok], col[ok], ks[ok]] |= MEASURED
        after = int(((states & MEASURED) > 0).sum())
        listed.append({"id": r["id"], "label": r["label"], "method": r["method"], "blocks": after - before})
        total = after
    return total, listed


def _build(db_root: str, session_id: str) -> Dict[str, Any]:
    with fim._LOCK:
        s = fim._SESSIONS.get(session_id)
    if s is None:
        raise KeyError("final image session expired; reopen the image")
    grid = s["result"]["grid"]
    z = np.asarray(grid.values, dtype=np.float64)
    dx, dy = grid.cell_size_m()
    params = s["result"].get("provenance", {}).get("parameters", {}) or {}
    radius = float(params.get("relief_radius_m") or 300.0)
    relief = fi.local_relief(z, dx, dy, radius)
    hyps = _hyp_cells(db_root, s)
    states = build_states(relief, hyps)
    measured_blocks, datasets = _mark_measured(db_root, s, states)
    counts = build_counts(relief.shape, hyps)
    ov = overlaps(hyps)
    fx, fy = s.get("focus") or (z.shape[1] / 2.0, z.shape[0] / 2.0)
    body = raised_body(relief, int(math.floor(fy)), int(math.floor(fx)), dx, dy)
    k = states.shape[2]
    slice_counts = [{"top_m": round(i * SLICE_M, 2), "bottom_m": round((i + 1) * SLICE_M, 2),
               "derived_cells": int(((states[:, :, i] & DERIVED) > 0).sum()),
               "hypothesized_cells": int(((states[:, :, i] & HYPOTHESIZED) > 0).sum()),
               "contested_cells": int((counts[:, :, i] >= 2).sum())} for i in range(k)]
    body_public = {kk: v for kk, v in body.items() if kk != "mask_cells"}
    summary = {
        "version": VERSION, "candidate_id": s["candidate_id"],
        "grid": {"width": int(z.shape[1]), "height": int(z.shape[0]),
                 "cell_dx_m": round(dx, 2), "cell_dy_m": round(dy, 2)},
        "depth_max_m": DEPTH_MAX_M, "slice_m": SLICE_M, "relief_radius_m": radius,
        "slices": slice_counts, "body": body_public,
        "hypotheses": [{"id": h["id"], "label": h["label"], "kind": h["kind"], "top_m": h["top_m"],
                        "bottom_m": h["bottom_m"], "cells": len(set(map(tuple, h["cells"]))),
                        "area_m2": h.get("area_m2"), "overlaps": ov.get(h["id"], [])} for h in hyps],
        "field_readings_recorded": _field_reading_count(db_root, s["candidate_id"]),
        "measured_in_volume": measured_blocks,
        "field_datasets": datasets,
        "source": grid.source, "source_sha256": grid.source_sha256,
        "statement": STATEMENT,
    }
    return {"states": states, "counts": counts, "summary": summary, "t": time.time()}


def volume_json(db_root: str, session_id: str) -> str:
    """Builds (or rebuilds) the volume for this session and returns its summary."""
    try:
        v = _build(db_root, session_id)
        with _LOCK:
            _CACHE[session_id] = v
            while len(_CACHE) > _MAX:
                _CACHE.pop(min(_CACHE, key=lambda kk: _CACHE[kk]["t"]))
        return json.dumps(v["summary"])
    except Exception as e:                      # shown, never hidden
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def volume_slice_rgba(session_id: str, k: int) -> bytes:
    with _LOCK:
        v = _CACHE.get(session_id)
    if v is None:
        raise KeyError("volume not built for this view; open Volume again")
    states = v["states"]
    k = int(k)
    if not 0 <= k < states.shape[2]:
        raise ValueError("no such depth slice")
    return slice_rgba(states, k, v.get("counts")).tobytes()


# ---------------------------------------------------------------------------
# ef-v2: footprint hypotheses from the Final Image screen
# ---------------------------------------------------------------------------

def _session(session_id: str) -> Dict[str, Any]:
    with fim._LOCK:
        s = fim._SESSIONS.get(session_id)
    if s is None:
        raise KeyError("final image session expired; reopen the image")
    return s


def footprints_json(db_root: str, session_id: str) -> str:
    """All footprints for the candidate (active and withdrawn), corners in this window's grid units."""
    try:
        import footprint_hypothesis as fph
        s = _session(session_id)
        grid = s["result"]["grid"]
        out = []
        for r in fph.list_for_candidate(db_root, s["candidate_id"], include_withdrawn=True):
            out.append({"id": r["id"], "label": r["label"], "note": r["note"], "status": r["status"],
                        "status_reason": r["status_reason"], "created_at": r["created_at"],
                        "area_m2": r["area_m2"], "depth_top_m": r["depth_top_m"],
                        "depth_bottom_m": r["depth_bottom_m"], "kind": r["kind"],
                        "polygon_grid": [list(grid.lonlat_to_pixel(lon, lat)) for lat, lon in r["polygon"]]})
        return json.dumps({"ok": True, "footprints": out})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def add_footprint_json(db_root: str, session_id: str, points_grid_json: str, label: str,
                       depth_top_m: float, depth_bottom_m: float, note: str = "") -> str:
    try:
        import footprint_hypothesis as fph
        s = _session(session_id)
        grid = s["result"]["grid"]
        pts = json.loads(points_grid_json)
        latlon = []
        for x, y in pts:
            lon, lat = grid.pixel_to_lonlat(float(x), float(y))
            latlon.append([lat, lon])
        hid = fph.add(db_root, s["candidate_id"], latlon, label, float(depth_top_m), float(depth_bottom_m), note)
        # ef-v4a: say how many DEM cell centres it covers; 0 means it cannot show in the volume
        h, w = grid.shape
        n_cells = len(polygon_cells([[float(x), float(y)] for x, y in pts], h, w))
        dx, dy = grid.cell_size_m()
        return json.dumps({"ok": True, "id": hid, "cells": n_cells,
                           "cell_dx_m": round(dx, 1), "cell_dy_m": round(dy, 1)})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def withdraw_footprint_json(db_root: str, hypothesis_id: str, reason: str) -> str:
    try:
        import footprint_hypothesis as fph
        fph.withdraw(db_root, hypothesis_id, reason)
        return json.dumps({"ok": True})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
