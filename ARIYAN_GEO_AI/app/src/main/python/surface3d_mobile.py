"""
surface3d_mobile.py -- s3d-v1 (2026-10-31): data for the 3D Visualization tab
of the Final Image screen (Surface3DView.kt draws it with OpenGL ES 2.0).

Reads the DEM window of an open Final Image session (final_image_mobile) and
hands Android:
  * the stored DEM cell values as float32 (NaN = no measurement; holes stay
    holes, nothing is filled or smoothed),
  * an AUTOMATIC height exaggeration with its rule written out, so the screen
    can always say what it did,
  * a snapshot export: PNG (rendered on the phone) + provenance JSON.

cut-v1 (2026-10-31): the snapshot provenance also records the cutaway state
("cut"); the cut face shows NO subsurface measurement.

cut-v2 (2026-10-31): the cut face gets a DERIVED band. surface_base() gives
the local base level of every cell: the mean ground level in the same window
as the relief colours (default 300 m), so  ground - base = local relief.
On the face, ground ABOVE its base is drawn orange (raised material, DEM-
derived, make-up unknown); ground BELOW its base gets a translucent blue band
up to the base (missing material, a hollow). Everything below the lower of
the two stays grey hatched: UNKNOWN, no measurement.

cut-v2 part 2 (2026-10-31): the user's own HYPOTHESIZED shapes on the face
(section_hypothesis.py). hypotheses_json() lists them for the candidate and
says which lie on the open line; add/withdraw go through the append-only
store. They are drawn purple, labelled HYPOTHESIZED, and are never evidence.

The 3D view is a different way of LOOKING at stored cells. It adds no
measurement and no evidence, and it never writes a candidate, review, status
or confidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Dict, Tuple

import numpy as np

import final_image as fi
import final_image_mobile as fim

S3D_VERSION = "s3d-v1"
# allowed exaggerations (the automatic one is always one of these)
NICE_VE = (1.0, 1.5, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0, 50.0)
# automatic rule: the window's height span (2-98 percentile) is drawn as about
# this fraction of the window's shorter side
TARGET_FRACTION = 0.10
STATEMENT = ("3D view of the stored DEM cells, display only. Height is exaggerated as "
             "stated; it adds no new measurement and is not archaeological proof.")
CUT_FACE_RULE = ("cut-v2 face: orange = DERIVED raised material between the ground line and the local "
                 "base level (mean ground level within %g m, from the DEM; make-up unknown); translucent "
                 "blue = DERIVED hollow between the ground line and the local base; grey hatched below = "
                 "UNKNOWN, no subsurface measurement (no GPR, no ERT). The drawn depth of the grey part "
                 "is a drawing aid, not a depth.")
_STATE_KEYS = ("ve", "ve_mode", "azimuth_deg", "tilt_deg", "distance_m",
               "drape", "drape_detail", "pins", "profile_line", "cut", "hypotheses", "width_px", "height_px")


def _session(session_id: str) -> Dict:
    with fim._LOCK:
        s = fim._SESSIONS.get(session_id)
    if s is None:
        raise KeyError("final image session expired; reopen the image")
    return s


def auto_exaggeration(z: np.ndarray, dx: float, dy: float) -> Tuple[float, Dict]:
    """Largest allowed exaggeration that keeps the height span (2-98
    percentile) at or below TARGET_FRACTION of the shorter side. Never below
    1x, never above 50x."""
    v = z[np.isfinite(z)]
    h, w = z.shape
    across = min(w * dx, h * dy)
    info = {"target_fraction": TARGET_FRACTION, "across_m": round(across, 1)}
    if v.size < 4 or across <= 0:
        info.update(span_m=None, raw=None)
        return 1.0, info
    lo, hi = np.percentile(v, [2.0, 98.0])
    span = float(hi - lo)
    info.update(span_m=round(span, 2), p2_m=round(float(lo), 2), p98_m=round(float(hi), 2))
    if span <= 0:
        info["raw"] = None
        return 1.0, info
    raw = TARGET_FRACTION * across / span
    info["raw"] = round(raw, 2)
    ve = 1.0
    for n in NICE_VE:
        if n <= raw:
            ve = n
    return ve, info


def open_surface_json(session_id: str) -> str:
    try:
        s = _session(session_id)
        grid = s["result"]["grid"]
        z = np.asarray(grid.values, dtype=np.float64)
        dx, dy = grid.cell_size_m()
        h, w = z.shape
        finite = np.isfinite(z)
        if finite.sum() < 4:
            return json.dumps({"error": "too few DEM cells with a value to draw a surface"})
        ve, info = auto_exaggeration(z, dx, dy)
        z_ref = float(np.median(z[finite]))
        rule = ("automatic: the height span of the window (2-98 percentile, %.1f m) is drawn as "
                "about %d%% of the shorter side (%.0f m); rounded down to an allowed step"
                % (info["span_m"] or 0.0, round(TARGET_FRACTION * 100), info["across_m"])
                if info.get("raw") else "automatic: terrain flat, drawn at true scale (1x)")
        return json.dumps({
            "version": S3D_VERSION, "width": int(w), "height": int(h),
            "cell_dx_m": dx, "cell_dy_m": dy,
            "ve_auto": ve, "ve_rule": rule, "ve_info": info, "ve_choices": list(NICE_VE),
            "z_ref_m": round(z_ref, 3),
            "z_min_m": round(float(np.min(z[finite])), 2), "z_max_m": round(float(np.max(z[finite])), 2),
            "cells": int(h * w), "cells_no_data": int((~finite).sum()),
            "source": grid.source, "source_sha256": grid.source_sha256,
            "relief_radius_m": _relief_radius(s),
            "statement": STATEMENT,
        })
    except Exception as e:                      # shown to the user, never hidden
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def surface_heights(session_id: str) -> bytes:
    """Stored cell values minus the window median, float32 little-endian,
    row-major (H*W). NaN stays NaN."""
    s = _session(session_id)
    z = np.asarray(s["result"]["grid"].values, dtype=np.float64)
    finite = np.isfinite(z)
    ref = float(np.median(z[finite])) if finite.any() else 0.0
    out = np.where(finite, z - ref, np.nan).astype("<f4")
    return out.tobytes()


def _relief_radius(s: Dict) -> float:
    params = s["result"].get("provenance", {}).get("parameters", {}) or {}
    return float(params.get("relief_radius_m") or 300.0)


def surface_base(session_id: str) -> bytes:
    """cut-v2: local base level per cell (mean ground within the relief
    radius) minus the same window median as surface_heights(), float32
    little-endian, row-major. NaN where the stored cell has no value."""
    s = _session(session_id)
    grid = s["result"]["grid"]
    z = np.asarray(grid.values, dtype=np.float64)
    dx, dy = grid.cell_size_m()
    finite = np.isfinite(z)
    ref = float(np.median(z[finite])) if finite.any() else 0.0
    relief = fi.local_relief(z, dx, dy, _relief_radius(s))
    base = z - relief
    out = np.where(np.isfinite(base), base - ref, np.nan).astype("<f4")
    return out.tobytes()


def cut_face_rule(session_id: str) -> str:
    return CUT_FACE_RULE % _relief_radius(_session(session_id))


def _clean_state(state_json: str) -> Dict:
    if not state_json:
        return {}
    try:
        d = json.loads(state_json)
    except ValueError:
        return {"error": "view state not readable"}
    if not isinstance(d, dict):
        return {}
    return {k: d[k] for k in _STATE_KEYS if k in d}


def export_snapshot_json(db_root: str, session_id: str, png_bytes, state_json: str = "") -> str:
    """Writes the phone-rendered PNG and its provenance JSON."""
    try:
        s = _session(session_id)
        data = bytes(png_bytes)
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return json.dumps({"error": "snapshot is not a PNG"})
        grid = s["result"]["grid"]
        stem = "s3d_%s_%s" % (s["candidate_id"][:8], time.strftime("%Y%m%d_%H%M%S", time.gmtime()))
        out_dir = os.path.join(db_root, "exports", "final_image")
        os.makedirs(out_dir, exist_ok=True)
        png_path = os.path.join(out_dir, stem + ".png")
        prov_path = os.path.join(out_dir, stem + ".provenance.json")
        with open(png_path, "wb") as f:
            f.write(data)
        z = np.asarray(grid.values, dtype=np.float64)
        dx, dy = grid.cell_size_m()
        ve_auto, info = auto_exaggeration(z, dx, dy)
        prov = {
            "version": S3D_VERSION, "kind": "3D snapshot (display only)",
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "candidate_id": s["candidate_id"], "synthetic_data": False,
            "dem": {"source": grid.source, "source_sha256": grid.source_sha256,
                    "cells": list(z.shape), "cell_dx_m": round(dx, 2), "cell_dy_m": round(dy, 2),
                    "bounds": s["result"]["provenance"]["bounds"]},
            "geometry": "one vertex per stored DEM cell centre; flat triangles between four cells "
                        "that all have a value; cells without a value leave a hole",
            "ve_auto": ve_auto, "ve_auto_info": info,
            "view": _clean_state(state_json),
            "cut_face": None,
            "processing_parameters": s.get("processing_parameters"),
            "outputs": {"png_sha256": hashlib.sha256(data).hexdigest()},
            "statement": STATEMENT,
        }
        cut = str(prov["view"].get("cut") or "off")
        if cut != "off":
            prov["cut_face"] = CUT_FACE_RULE % _relief_radius(s)
        with open(prov_path, "w", encoding="utf-8") as f:
            json.dump(prov, f, indent=2, sort_keys=True)
        return json.dumps({"ok": True, "paths": {"png": png_path, "provenance": prov_path}})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# --------------------------------------------------------------------------
# cut-v2 part 2: user-drawn HYPOTHESIZED shapes on the cut face
# --------------------------------------------------------------------------

LINE_MATCH_CELLS = 1.5      # a stored line is "this line" if both ends are within this many cells


def _line_geo(s: Dict, ax: float, ay: float, bx: float, by: float) -> Dict:
    grid = s["result"]["grid"]
    cdx, cdy = grid.cell_size_m()
    a_lon, a_lat = grid.pixel_to_lonlat(ax, ay)
    b_lon, b_lat = grid.pixel_to_lonlat(bx, by)
    length = float(np.hypot((bx - ax) * cdx, (by - ay) * cdy))
    return {"a_lat": a_lat, "a_lon": a_lon, "b_lat": b_lat, "b_lon": b_lon, "length_m": length}


def hypotheses_json(db_root: str, session_id: str, ax: float, ay: float, bx: float, by: float,
                    include_withdrawn: bool = True) -> str:
    try:
        import section_hypothesis as sh
        s = _session(session_id)
        grid = s["result"]["grid"]
        h, w = grid.shape
        out = []
        for r in sh.list_for_candidate(db_root, s["candidate_id"], include_withdrawn=include_withdrawn):
            pax, pay = grid.lonlat_to_pixel(r["a_lon"], r["a_lat"])
            pbx, pby = grid.lonlat_to_pixel(r["b_lon"], r["b_lat"])
            same = (np.hypot(pax - ax, pay - ay) <= LINE_MATCH_CELLS and
                    np.hypot(pbx - bx, pby - by) <= LINE_MATCH_CELLS)
            inside = all(0 <= v <= lim for v, lim in ((pax, w), (pbx, w), (pay, h), (pby, h)))
            out.append({"id": r["id"], "label": r["label"], "note": r["note"], "status": r["status"],
                        "status_reason": r["status_reason"], "created_at": r["created_at"],
                        "along_from_m": r["along_from_m"], "along_to_m": r["along_to_m"],
                        "depth_top_m": r["depth_top_m"], "depth_bottom_m": r["depth_bottom_m"],
                        "line_length_m": r["line_length_m"], "kind": r["kind"],
                        "on_this_line": bool(same), "line_in_window": bool(inside),
                        "line_grid": [round(pax, 3), round(pay, 3), round(pbx, 3), round(pby, 3)]})
        return json.dumps({"ok": True, "line": _line_geo(s, ax, ay, bx, by), "hypotheses": out,
                           "statement": "HYPOTHESIZED = the user's own idea of what might lie below; "
                                        "not measured, not evidence, never changes status or confidence."})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def add_hypothesis_json(db_root: str, session_id: str, ax: float, ay: float, bx: float, by: float,
                        label: str, along_from_m: float, along_to_m: float,
                        depth_top_m: float, depth_bottom_m: float, note: str = "") -> str:
    try:
        import section_hypothesis as sh
        s = _session(session_id)
        g = _line_geo(s, ax, ay, bx, by)
        hid = sh.add(db_root, s["candidate_id"], g["a_lat"], g["a_lon"], g["b_lat"], g["b_lon"], g["length_m"],
                     label, float(along_from_m), float(along_to_m), float(depth_top_m), float(depth_bottom_m), note)
        return json.dumps({"ok": True, "id": hid})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def withdraw_hypothesis_json(db_root: str, hypothesis_id: str, reason: str) -> str:
    try:
        import section_hypothesis as sh
        sh.withdraw(db_root, hypothesis_id, reason)
        return json.dumps({"ok": True})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
