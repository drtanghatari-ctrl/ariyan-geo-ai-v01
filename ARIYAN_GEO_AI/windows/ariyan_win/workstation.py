"""
Data for the Mission Control workstation (win-w1). Read-only: everything comes
from the phone's own core modules (mission_control, final_image_mobile,
surface3d_mobile, sat_image_mobile, debate_store tables) on this computer's copy
of the project. Nothing here changes a status, review, confidence or evidence row.
"""
from __future__ import annotations

import json
import os
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
            "steward_lines": steward_lines, "known_site": ks, "calib_strong": strong,
            "same_place": same_place(root, cid)}


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
                    # w3: where the layer's own cells sit on the DEM window (DEM pixel units)
                    item["placement"] = sim._LAYERS[sid][l["product"]]["payload"]["placement"]
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


def drape_on_dem(rgba: bytes, w: int, h: int, placement: Optional[Dict[str, float]], dem_w: int,
                 dem_h: int) -> np.ndarray:
    """(dem_h, dem_w, 3) colours: for each DEM cell centre, the satellite cell it falls in
    (nearest; no smoothing). Cells outside the layer stay dark. placement = {x0, y0, sx, sy}:
    layer cell (u, v) covers DEM pixels x0 + u*sx ... (sat_image_mobile.placement)."""
    img = np.frombuffer(rgba, dtype=np.uint8).reshape(h, w, 4)
    if not placement:
        placement = {"x0": 0.0, "y0": 0.0, "sx": dem_w / float(w), "sy": dem_h / float(h)}
    cx = np.arange(dem_w) + 0.5
    cy = np.arange(dem_h) + 0.5
    u = np.floor((cx - placement["x0"]) / placement["sx"]).astype(int)
    v = np.floor((cy - placement["y0"]) / placement["sy"]).astype(int)
    out = np.full((dem_h, dem_w, 3), 20, dtype=np.uint8)
    okx, oky = (u >= 0) & (u < w), (v >= 0) & (v < h)
    vv, uu = np.meshgrid(np.clip(v, 0, h - 1), np.clip(u, 0, w - 1), indexing="ij")
    vals = img[vv, uu, :3]
    mask = oky[:, None] & okx[None, :] & (img[vv, uu, 3] > 0)
    out[mask] = vals[mask]
    return out


SAME_PLACE_M = 30.0                     # one 1-arc-second DEM cell


def same_place(root: str, cid: str, conn=None) -> List[Dict[str, Any]]:
    """Earlier candidates within one DEM cell (30 m) of this one: a repeat run of the
    same place, a note only -- nothing is merged or changed (win-w4c)."""
    import math
    own = conn is None
    if own:
        conn = _conn(root)
    try:
        c = conn.execute("SELECT lat, lon, created_at FROM candidate WHERE id = ?", (cid,)).fetchone()
        if c is None:
            return []
        lat, lon, created = c[0], c[1], c[2]
        dlat = SAME_PLACE_M / 111320.0
        dlon = SAME_PLACE_M / (111320.0 * max(0.1, math.cos(math.radians(lat))))
        out = []
        for r in conn.execute("SELECT id, lat, lon, status, confidence_band, created_at FROM candidate WHERE id != ? "
                              "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? AND created_at < ?",
                              (cid, lat - dlat, lat + dlat, lon - dlon, lon + dlon, created)):
            d = math.hypot((r["lat"] - lat) * 111320.0, (r["lon"] - lon) * 111320.0 * math.cos(math.radians(lat)))
            if d <= SAME_PLACE_M:
                out.append({"id": r["id"], "distance_m": round(d, 1), "status": r["status"],
                            "band": r["confidence_band"], "created_at": r["created_at"]})
        return sorted(out, key=lambda x: x["created_at"])
    finally:
        if own:
            conn.close()


def candidate_page(root: str, job_id: Optional[str], status: str, band: str, text: str, offset: int,
                   limit: int = 100) -> Dict[str, Any]:
    """One page of candidates for the review list (newest first), with the same-place note."""
    conn = _conn(root)
    try:
        where, args = ["1=1"], []
        if job_id:
            where.append("c.investigation_id IN (SELECT investigation_id FROM wide_area_search_tile WHERE job_id = ?)")
            args.append(job_id)
        if status:
            where.append("c.status = ?")
            args.append(status)
        if band:
            where.append("COALESCE(c.confidence_band, 'NOT_RATED') = ?")
            args.append(band)
        if text:
            where.append("c.id LIKE ?")
            args.append(text.strip().lower() + "%")
        sql = " AND ".join(where)
        total = conn.execute("SELECT COUNT(*) FROM candidate c WHERE " + sql, args).fetchone()[0]
        rows = [dict(r) for r in conn.execute(
            "SELECT c.id, c.lat, c.lon, c.status, c.score, c.confidence_band, c.confidence_numeric, c.created_at "
            "FROM candidate c WHERE " + sql + " ORDER BY c.confidence_numeric IS NULL, c.confidence_numeric DESC, "
            "ABS(COALESCE(c.score, 0)) DESC LIMIT ? OFFSET ?", args + [int(limit), int(offset)])]
        for r in rows:
            r["same_place"] = same_place(root, r["id"], conn)
        return {"total": total, "rows": rows, "offset": offset}
    finally:
        conn.close()


def export_results(root: str) -> Dict[str, Any]:
    """Every candidate of the project as CSV and GeoJSON in offline_data/exports (read-only)."""
    import csv
    import hashlib
    from datetime import datetime, timezone
    conn = _conn(root)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT c.id, c.lat, c.lon, c.status, c.confidence_band, c.confidence_numeric, c.score, c.created_at, "
            "j.title AS job FROM candidate c LEFT JOIN wide_area_search_tile t ON t.investigation_id = c.investigation_id "
            "LEFT JOIN wide_area_search_job j ON j.id = t.job_id ORDER BY c.created_at")]
    finally:
        conn.close()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = os.path.join(root, "exports", "results")
    os.makedirs(out, exist_ok=True)
    csv_path = os.path.join(out, "ariyan_candidates_%s.csv" % stamp)
    cols = ["id", "lat", "lon", "status", "confidence_band", "confidence_numeric", "score", "job", "created_at"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(k) for k in cols])
    gj_path = os.path.join(out, "ariyan_candidates_%s.geojson" % stamp)
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
              "properties": {k: r.get(k) for k in cols if k not in ("lat", "lon")}} for r in rows]
    with open(gj_path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "name": "ARIYAN candidates %s" % stamp, "features": feats}, f)
    md5 = {p: hashlib.md5(open(p, "rb").read()).hexdigest() for p in (csv_path, gj_path)}
    return {"rows": len(rows), "csv": csv_path, "geojson": gj_path, "md5": md5,
            "note": "Coordinates are exact. Statuses and bands are as stored; nothing was changed."}
