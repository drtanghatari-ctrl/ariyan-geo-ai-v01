"""
final_image_mobile.py -- fi-v1 (2026-10-16): Kotlin bridge for the Final
Image screen (FinalImageActivity.kt).

open_final_image_json()  builds the image around one candidate from the
                         saved offline DEM tile and returns every vector
                         layer (contours, UTM grid, candidate markers,
                         legend, provenance) as JSON. The composite image
                         is kept here, in memory, under a session id.
image_rgba(session_id)   the composite as raw RGBA bytes (H*W*4), straight
                         from real DEM cells, for an Android Bitmap. Android
                         then draws it with filtering OFF ("Exact cells") or
                         ON ("Smooth") -- it never receives a pre-stretched
                         picture.
export_final_image_json() writes PNG + GeoTIFF + provenance JSON.

Read-only on the database: this module never writes a candidate, a review,
a status or a confidence.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Dict, List

import numpy as np

import final_image as fi

_SESSIONS: Dict[str, Dict] = {}
_LOCK = threading.Lock()
_MAX_SESSIONS = 3                      # phone memory: keep only the latest few
WINDOW_CHOICES_M = (500.0, 1000.0, 2500.0, 5000.0)


def _storage_folder(lat: float, lon: float) -> str:
    import offline_country_registry
    country = offline_country_registry.get_country_for_point(lat, lon)
    if country is None:
        raise LookupError("no offline country package covers this point")
    return country.storage_folder


def _candidates_in_bounds(db_root: str, grand_project_id: str, b: Dict) -> List[Dict]:
    """Candidates of the same project inside the window, with their STORED
    status and confidence (read only)."""
    import grand_project_db as db
    conn = db.get_connection(db_root)
    try:
        db.initialize_schema(conn)
        rows = conn.execute(
            "SELECT id, lat, lon, status, score, confidence_band, confidence_numeric "
            "FROM candidate WHERE grand_project_id = ? AND lat BETWEEN ? AND ? "
            "AND lon BETWEEN ? AND ?",
            (grand_project_id, b["south"], b["north"], b["west"], b["east"])).fetchall()
        rows = [dict(r) for r in rows]
    finally:
        conn.close()
    labels: Dict = {}
    try:
        import grand_project_review as review
        labels = review.review_summary_for_project(db_root, grand_project_id)
    except Exception:
        labels = {}
    out = []
    for r in rows:
        s = labels.get(r["id"], {})
        out.append({"id": r["id"], "lat": r["lat"], "lon": r["lon"],
                    "status": s.get("status_label") or r["status"],
                    "confidence_label": r.get("confidence_band"),
                    "confidence": r.get("confidence_numeric"),
                    "score": r.get("score"), "job_id": s.get("job_id")})
    return out


def _clean_rgba(img: np.ndarray) -> np.ndarray:
    """Android bitmaps are premultiplied: a transparent pixel must be 0,0,0,0."""
    out = img.copy()
    out[out[..., 3] == 0] = 0
    return out


def open_final_image_json(db_root: str, candidate_id: str, half_size_m: float = 1000.0,
                          colour_by: str = "relief") -> str:
    try:
        import grand_project_db as db
        cand = db.get_candidate(db_root, candidate_id)
        if cand is None:
            return json.dumps({"error": "candidate not found"})
        lat, lon = float(cand["lat"]), float(cand["lon"])
        folder = _storage_folder(lat, lon)
        res = fi.build_final_image(folder, db_root, lat, lon, float(half_size_m),
                                   colour_by=colour_by,
                                   created_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        if not res["ok"]:
            return json.dumps({"error": "; ".join(res["problems"]) or "no image"})
        grid = res["grid"]
        b = res["provenance"]["bounds"]
        cands = _candidates_in_bounds(db_root, cand["grand_project_id"], b)
        markers = fi.candidate_overlay(grid, cands)
        by_id = {c["id"]: c for c in cands}
        for m in markers:
            m["focus"] = m["id"] == candidate_id
            m["job_id"] = by_id[m["id"]].get("job_id")
        fx, fy = grid.lonlat_to_pixel(lon, lat)
        dx, dy = grid.cell_size_m()
        sid = uuid.uuid4().hex[:12]
        with _LOCK:
            _SESSIONS[sid] = {"result": res, "candidate_id": candidate_id, "t": time.time(),
                             "markers": markers, "focus": (fx, fy)}   # fa-v1 profile
            while len(_SESSIONS) > _MAX_SESSIONS:
                oldest = min(_SESSIONS, key=lambda k: _SESSIONS[k]["t"])
                _SESSIONS.pop(oldest)
        h, w = grid.shape
        return json.dumps({
            "session_id": sid, "version": fi.FI_VERSION,
            "candidate_id": candidate_id, "lat": lat, "lon": lon,
            "width": w, "height": h, "cell_dx_m": dx, "cell_dy_m": dy,
            "native_resolution_m": res["native_resolution_m"],
            "focus": {"x": fx, "y": fy},
            "half_size_m": float(half_size_m), "colour_by": colour_by,
            "legend": res["legend"],
            "ramp": fi.RAMP_TERRAIN.tolist(),
            "contours": {"interval_m": res["contours"]["interval_m"],
                         "levels": [{"level_m": lv["level_m"], "index": lv["index"],
                                     "flat": [v for seg in lv["segments"] for v in seg]}
                                    for lv in res["contours"]["levels"]]},
            "utm_grid": res["utm_grid"],
            "candidates": markers,
            "problems": res["problems"], "notes": res["notes"],
            "bounds": b, "source": grid.source,
            "statement": res["provenance"]["statement"],
            "window_choices_m": list(WINDOW_CHOICES_M),
        })
    except Exception as e:                      # surfaced to the user, never hidden
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def image_rgba(session_id: str) -> bytes:
    with _LOCK:
        s = _SESSIONS.get(session_id)
    if s is None:
        raise KeyError("final image session expired; reopen the image")
    return _clean_rgba(s["result"]["image"]).tobytes()


def render_view_rgba(session_id: str, x0: float, y0: float, x1: float, y1: float,
                     out_w: int, out_h: int, mode: str = fi.DEFAULT_MODE) -> bytes:
    """Python reference renderer for one view (used for exports of the
    current view and as the cross-check for the on-screen drawing)."""
    with _LOCK:
        s = _SESSIONS.get(session_id)
    if s is None:
        raise KeyError("final image session expired; reopen the image")
    out = fi.render_view(s["result"]["image"], x0, y0, x1, y1, int(out_w), int(out_h), mode)
    return _clean_rgba(out).tobytes()


def export_final_image_json(db_root: str, session_id: str) -> str:
    try:
        with _LOCK:
            s = _SESSIONS.get(session_id)
        if s is None:
            return json.dumps({"error": "final image session expired; reopen the image"})
        stem = "fi_%s_%s" % (s["candidate_id"][:8], time.strftime("%Y%m%d_%H%M%S", time.gmtime()))
        out_dir = os.path.join(db_root, "exports", "final_image")
        paths = fi.export_files(s["result"], out_dir, stem)
        return json.dumps({"ok": True, "paths": paths})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def close_session(session_id: str) -> None:
    with _LOCK:
        _SESSIONS.pop(session_id, None)
