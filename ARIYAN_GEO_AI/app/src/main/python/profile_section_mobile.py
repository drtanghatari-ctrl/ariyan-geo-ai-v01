"""
profile_section_mobile.py -- fa-v1 (2026-10-21): Kotlin bridge for Profile &
Section on the Final Image screen (FinalImageActivity.kt).

profile_json(sid, ax, ay, bx, by, product)   the profile along A-A' (DEM grid-
                                             pixel coordinates of an open fi-v1
                                             session). product = "" or a
                                             satellite layer ALREADY OPEN in
                                             that session (never fetched here).
preset_profile_json(sid, which, product)     "NS" or "EW" through the focus
                                             candidate, across the whole window.
export_profile_json(root, sid, ax, ay, bx, by, product)
                                             CSV + PNG + provenance JSON.

Read-only on the database and on the satellite library.
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, Optional

import final_image_mobile as fim
import profile_section as ps


def _session(sid: str) -> Dict:
    with fim._LOCK:
        s = fim._SESSIONS.get(sid)
    if s is None:
        raise KeyError("final image session expired; reopen the image")
    return s


DERIVED = "DERIVED"          # fa-v2: the active filter, not a satellite layer


def _derived(sid: str, product: str) -> Optional[Dict]:
    if product != DERIVED:
        return None
    import dem_filters_mobile as dfm
    return dfm.active(sid)


def _sat(sid: str, product: str) -> Optional[Dict]:
    if not product or product == DERIVED:
        return None
    import sat_image as si
    import sat_image_mobile as sim
    with sim._LOCK:
        l = (sim._LAYERS.get(sid) or {}).get(product)
    if l is None:
        raise KeyError(f"{product} layer is not open; open it from Satellite first "
                       "(the profile never downloads)")
    p = l["payload"]
    if not p.get("allowed"):
        raise PermissionError("layer hidden until its self-check passes: " + str(p.get("check")))
    lg = p.get("legend") or {}
    span = (lg.get("vmax") or 1.0) - (lg.get("vmin") or 0.0)
    return {"product": product, "label": p.get("label"), "units": p.get("unit"),
            "scene_date": p.get("scene_date"), "values": l["values"],
            "placement": p["placement"], "cell_m": p.get("pixel_m"),
            "min_span": max(abs(span) * 0.05, 1e-6), "provenance": p.get("provenance")}


def _build(sid: str, ax: float, ay: float, bx: float, by: float, product: str) -> Dict:
    s = _session(sid)
    res = s["result"]
    return ps.build_profile(res, float(ax), float(ay), float(bx), float(by),
                            markers=s.get("markers", ()), sat=_sat(sid, product),
                            derived=_derived(sid, product))


def profile_json(sid: str, ax: float, ay: float, bx: float, by: float, product: str = "") -> str:
    try:
        return json.dumps(_build(sid, ax, ay, bx, by, product), allow_nan=False)
    except Exception as e:                      # surfaced to the user, never hidden
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def preset_profile_json(sid: str, which: str, product: str = "") -> str:
    try:
        s = _session(sid)
        grid = s["result"]["grid"]
        fx, fy = s.get("focus") or (grid.shape[1] / 2.0, grid.shape[0] / 2.0)
        ax, ay, bx, by = ps.preset_line(grid, fx, fy, which)
        out = _build(sid, ax, ay, bx, by, product)
        out["preset"] = which.upper()
        return json.dumps(out, allow_nan=False)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def export_profile_json(db_root: str, sid: str, ax: float, ay: float, bx: float, by: float,
                        product: str = "") -> str:
    try:
        s = _session(sid)
        prof = _build(sid, ax, ay, bx, by, product)
        stem = "profile_%s_%s" % (s["candidate_id"][:8], time.strftime("%Y%m%d_%H%M%S", time.gmtime()))
        out_dir = os.path.join(db_root, "exports", "profile")
        paths = ps.export_profile(prof, s["result"]["grid"], out_dir, stem,
                                  created_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        return json.dumps({"ok": True, "paths": paths})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
