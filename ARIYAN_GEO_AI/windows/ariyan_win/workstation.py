"""
Data for the Mission Control workstation (win-w1). Read-only: everything comes
from the phone's own core modules (mission_control, final_image_mobile,
surface3d_mobile, sat_image_mobile, debate_store tables) on this computer's copy
of the project. Nothing here changes a status, review, confidence or evidence row.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import numpy as np


def _conn(root: str):
    import grand_project_db as db
    c = db.get_connection(root)
    db.initialize_schema(c)
    return c


def _has(conn, t: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone() is not None


def timeline(root: str, n: int = 12) -> List[Dict[str, Any]]:
    conn = _conn(root)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT occurred_at, event_type, description FROM timeline_event ORDER BY id DESC LIMIT ?", (int(n),))]
    finally:
        conn.close()


def candidate_detail(root: str, cid: str) -> Dict[str, Any]:
    import mission_control as mc
    conn = _conn(root)
    try:
        c = conn.execute("SELECT c.*, j.title AS job_title FROM candidate c "
                         "LEFT JOIN wide_area_search_tile t ON t.investigation_id = c.investigation_id "
                         "LEFT JOIN wide_area_search_job j ON j.id = t.job_id WHERE c.id = ?", (cid,)).fetchone()
        if c is None:
            raise KeyError("candidate %s not found" % cid)
        c = dict(c)
        ev: Dict[str, Dict[str, int]] = {}
        for r in conn.execute("SELECT evidence_type, relation, COUNT(*) AS n FROM evidence_link "
                              "WHERE candidate_id = ? GROUP BY evidence_type, relation", (cid,)):
            ev.setdefault(r["evidence_type"], {})[r["relation"]] = r["n"]
        debate_id = None
        if _has(conn, "debate_record"):
            r = conn.execute("SELECT id FROM debate_record WHERE candidate_id = ? ORDER BY id DESC LIMIT 1",
                             (cid,)).fetchone()
            debate_id = r[0] if r else None
        hist = conn.execute("SELECT reasoning_snapshot_json FROM confidence_history WHERE candidate_id = ? "
                            "ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    finally:
        conn.close()
    steward_lines: List[str] = []
    if hist and hist[0]:
        try:
            v = json.loads(hist[0])
            steward_lines = [str(x) for x in (v if isinstance(v, list) else [v])]
        except ValueError:
            steward_lines = [str(hist[0])]
    debate = json.loads(mc.debate_detail_json(root, debate_id)) if debate_id else None
    ks = None
    try:
        import known_sites
        ks = known_sites.annotate(c["lat"], c["lon"]).get("text")
    except Exception:
        ks = None
    strong = False
    try:
        import calib_profile
        strong = calib_profile.is_strong(c.get("score"), calib_profile.active_profile(root))
    except Exception:
        strong = False
    return {"id": cid, "lat": c["lat"], "lon": c["lon"], "status": c.get("status"), "band": c.get("confidence_band"),
            "numeric": c.get("confidence_numeric"), "z": c.get("score"), "job_title": c.get("job_title"),
            "evidence": ev, "debate": debate if debate and "error" not in debate else None,
            "steward_lines": steward_lines, "known_site": ks, "calib_strong": strong}


def terrain(root: str, cid: str) -> Dict[str, Any]:
    """The candidate's +/-1 km DEM window: relief drape, heights, pins and every saved layer."""
    import final_image_mobile as fim
    import mission_control as mc
    import sat_image_mobile as sim
    import surface3d_mobile as s3d
    j = json.loads(fim.open_final_image_json(root, cid, 1000.0, "relief"))
    if "error" in j:
        out: Dict[str, Any] = {"error": j["error"]}
        if "no saved DEM tile" in j["error"] or "no DEM" in j["error"]:
            import terrain_tile
            c = candidate_detail_light(root, cid)
            out["needs_tile"] = json.loads(terrain_tile.tile_status_json(root, c["lat"], c["lon"]))
        return out
    sid = j["session_id"]
    try:
        w, h = j["width"], j["height"]
        drape = bytes(fim.image_rgba(sid))
        m = json.loads(s3d.open_surface_json(sid))
        if "error" in m:
            return {"error": m["error"]}
        hb = bytes(s3d.surface_heights(sid))
        heights = np.frombuffer(hb, dtype="<f4").reshape(m["height"], m["width"]).copy()   # minus the window median
        finite = np.isfinite(heights)
        median_m = (float(m["z_min_m"]) - float(np.nanmin(heights))) if finite.any() and m.get("z_min_m") is not None else 0.0
        layers = []
        th = json.loads(mc.thumbs_json(root, sid))
        for l in th.get("layers", []):
            item = dict(l)
            if l.get("state") == "SAVED":
                try:
                    item["rgba"] = bytes(sim.layer_rgba(sid, l["product"]))
                except Exception as e:
                    item["state"], item["reason"] = "ERROR", str(e)
            layers.append(item)
        try:
            sim.close_layers(sid)
        except Exception:
            pass
        return {"meta": j, "surface": m, "drape": drape, "width": w, "height": h, "heights": heights,
                "heights_abs": heights + median_m,
                "pins": j.get("candidates", []), "layers": layers}
    finally:
        try:
            fim.close_session(sid)
        except Exception:
            pass


def candidate_detail_light(root: str, cid: str) -> Dict[str, Any]:
    conn = _conn(root)
    try:
        r = conn.execute("SELECT lat, lon FROM candidate WHERE id = ?", (cid,)).fetchone()
        return {"lat": r[0], "lon": r[1]}
    finally:
        conn.close()
