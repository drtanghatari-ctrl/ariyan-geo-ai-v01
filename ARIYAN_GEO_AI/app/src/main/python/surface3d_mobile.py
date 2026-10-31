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

import final_image_mobile as fim

S3D_VERSION = "s3d-v1"
# allowed exaggerations (the automatic one is always one of these)
NICE_VE = (1.0, 1.5, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0, 50.0)
# automatic rule: the window's height span (2-98 percentile) is drawn as about
# this fraction of the window's shorter side
TARGET_FRACTION = 0.10
STATEMENT = ("3D view of the stored DEM cells, display only. Height is exaggerated as "
             "stated; it adds no new measurement and is not archaeological proof.")
_STATE_KEYS = ("ve", "ve_mode", "azimuth_deg", "tilt_deg", "distance_m",
               "drape", "drape_detail", "pins", "profile_line", "width_px", "height_px")


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
            "processing_parameters": s.get("processing_parameters"),
            "outputs": {"png_sha256": hashlib.sha256(data).hexdigest()},
            "statement": STATEMENT,
        }
        with open(prov_path, "w", encoding="utf-8") as f:
            json.dump(prov, f, indent=2, sort_keys=True)
        return json.dumps({"ok": True, "paths": {"png": png_path, "provenance": prov_path}})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
