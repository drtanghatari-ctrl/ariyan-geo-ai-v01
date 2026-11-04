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


# ---------------------------------------------------------------- u1: candidate search
import re as _re

_COORD = _re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*(?:[,;\s]\s*(?:r\s*=?\s*)?(\d+(?:\.\d+)?)\s*(km|m)?)?\s*$",
                     _re.I)
_HEX = _re.compile(r"^[0-9a-f\-]{3,}$", _re.I)
SEARCH_RADIUS_M = 1000.0


def parse_query(q: str) -> Dict[str, Any]:
    """'36.953, 45.524' (optionally ', 500 m' or ', 2 km') -> coordinate; hex text -> ID; anything else -> name."""
    q = (q or "").strip()
    m = _COORD.match(q)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            r = SEARCH_RADIUS_M
            if m.group(3):
                r = float(m.group(3)) * (1000.0 if (m.group(4) or "").lower() == "km" else 1.0)
            return {"kind": "coordinate", "lat": lat, "lon": lon, "radius_m": min(max(r, 10.0), 50000.0)}
    if _HEX.match(q) and any(ch.isdigit() for ch in q):
        return {"kind": "id", "text": q.lower()}
    return {"kind": "name", "text": q}


def _fold(t: str) -> str:
    """Lower case without accents, so 'kultepe' finds 'Kültepe' and 'saqqez' finds 'Saqqēz'."""
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(t or "")) if not unicodedata.combining(ch)).lower()


def _dist_m(lat1, lon1, lat2, lon2) -> float:
    import math
    return math.hypot((lat2 - lat1) * 111320.0, (lon2 - lon1) * 111320.0 * math.cos(math.radians(lat1)))


def _near(conn, lat: float, lon: float, radius_m: float, limit: int) -> List[Dict[str, Any]]:
    import math
    dlat = radius_m / 111320.0
    dlon = radius_m / (111320.0 * max(0.1, math.cos(math.radians(lat))))
    out = []
    for r in conn.execute(_SEARCH_SELECT + "WHERE c.lat BETWEEN ? AND ? AND c.lon BETWEEN ? AND ?",
                          (lat - dlat, lat + dlat, lon - dlon, lon + dlon)):
        d = _dist_m(lat, lon, r["lat"], r["lon"])
        if d <= radius_m:
            x = dict(r)
            x["distance_m"] = round(d, 1)
            out.append(x)
    out.sort(key=lambda x: x["distance_m"])
    return out[:limit]


_SEARCH_SELECT = ("SELECT c.id, c.lat, c.lon, c.status, c.confidence_band, c.confidence_numeric, c.score, "
                  "j.title AS job_title FROM candidate c "
                  "LEFT JOIN wide_area_search_tile t ON t.investigation_id = c.investigation_id "
                  "LEFT JOIN wide_area_search_job j ON j.id = t.job_id ")


def search_candidates(root: str, query: str, limit: int = 60, job_id: Optional[str] = None) -> Dict[str, Any]:
    """Find candidates by ID (prefix), by name (job title, or a known site from the gazetteer:
    candidates within 1 km of it) or by coordinate (within a radius, default 1 km).
    Read-only; every row says why it matched."""
    p = parse_query(query)
    want = limit
    if job_id:
        limit = max(limit * 20, 1000)
    if not (query or "").strip():
        return {"query": p, "rows": [], "note": "Type an ID, a name or a coordinate."}
    conn = _conn(root)
    rows: List[Dict[str, Any]] = []
    try:
        if p["kind"] == "coordinate":
            for x in _near(conn, p["lat"], p["lon"], p["radius_m"], limit):
                x["match"] = "%.0f m from %.5f, %.5f" % (x["distance_m"], p["lat"], p["lon"])
                rows.append(x)
            note = "Candidates within %s of the point, nearest first." % (
                "%.0f m" % p["radius_m"] if p["radius_m"] < 1000 else "%g km" % (p["radius_m"] / 1000.0))
        elif p["kind"] == "id":
            for r in conn.execute(_SEARCH_SELECT + "WHERE c.id LIKE ? ORDER BY c.created_at DESC LIMIT ?",
                                  (p["text"] + "%", int(limit))):
                x = dict(r)
                x["match"] = "ID"
                rows.append(x)
            note = "Candidates whose ID starts with %s." % p["text"]
        else:
            text = p["text"]
            seen = set()
            for r in conn.execute(_SEARCH_SELECT + "WHERE j.title LIKE ? ORDER BY c.confidence_numeric IS NULL, "
                                  "c.confidence_numeric DESC, ABS(COALESCE(c.score, 0)) DESC LIMIT ?",
                                  ("%" + text + "%", int(limit))):
                x = dict(r)
                x["match"] = "job: %s" % (x.get("job_title") or "")
                rows.append(x)
                seen.add(x["id"])
            sites = []
            try:
                import known_sites
                known_sites._load()
                low = _fold(text)
                sites = [s for s in known_sites._points if s.get("kind") != "N" and low in _fold(s["name"])][:25]
            except Exception:
                sites = []
            for s in sites:
                if len(rows) >= limit:
                    break
                for x in _near(conn, s["lat"], s["lon"], SEARCH_RADIUS_M, limit):
                    if x["id"] in seen:
                        continue
                    x["match"] = "%.0f m from known site %s" % (x["distance_m"], s["name"])
                    rows.append(x)
                    seen.add(x["id"])
            note = ("Jobs named like \u201c%s\u201d, and candidates within 1 km of %d known site(s) with that name." % (
                text, len(sites))) if sites else "Jobs named like \u201c%s\u201d (no known site has that name)." % text
    finally:
        conn.close()
    if job_id:
        conn = _conn(root)
        try:
            keep = {r[0] for r in conn.execute(
                "SELECT c.id FROM candidate c JOIN wide_area_search_tile t ON t.investigation_id = c.investigation_id "
                "WHERE t.job_id = ?", (job_id,))}
        finally:
            conn.close()
        rows = [x for x in rows if x["id"] in keep]
        note += " Only this job."
    limit = want
    for x in rows:
        x["band"] = (x.get("confidence_band") or "NOT_RATED").upper()
    return {"query": p, "rows": rows[:limit], "note": note}


# ---------------------------------------------------------------- u2: groups and interpretation
GROUP_RADIUS_M = 300.0          # neighbours closer than this are one group (chained)
GROUP_CAP = 80


def candidate_group(root: str, cid: str, radius_m: float = GROUP_RADIUS_M, cap: int = GROUP_CAP) -> Dict[str, Any]:
    """The candidates of the same job (or the same investigation, for a single point) that lie
    together with this one: each member is within radius_m of another member (chained).
    A grouping for reading only -- nothing is merged, linked or changed."""
    import math
    conn = _conn(root)
    try:
        me = conn.execute("SELECT c.id, c.lat, c.lon, c.investigation_id, t.job_id, j.title FROM candidate c "
                          "LEFT JOIN wide_area_search_tile t ON t.investigation_id = c.investigation_id "
                          "LEFT JOIN wide_area_search_job j ON j.id = t.job_id WHERE c.id = ?", (cid,)).fetchone()
        if me is None:
            return {"error": "candidate %s not found" % cid}
        sel = ("SELECT c.id, c.lat, c.lon, c.status, c.score, c.confidence_band, c.confidence_numeric FROM candidate c ")
        if me["job_id"]:
            pool = [dict(r) for r in conn.execute(sel + "JOIN wide_area_search_tile t ON t.investigation_id = "
                                                  "c.investigation_id WHERE t.job_id = ?", (me["job_id"],))]
            scope = "job %s" % (me["title"] or me["job_id"][:8])
        else:
            pool = [dict(r) for r in conn.execute(sel + "WHERE c.investigation_id = ?", (me["investigation_id"],))]
            scope = "this investigation"
    finally:
        conn.close()
    lat0 = me["lat"]
    kx = 111320.0 * math.cos(math.radians(lat0))
    cell = {}
    for i, r in enumerate(pool):
        cell.setdefault((int(r["lat"] * 111320.0 // radius_m), int(r["lon"] * kx // radius_m)), []).append(i)
    start = next(i for i, r in enumerate(pool) if r["id"] == cid)
    seen, queue = {start}, [start]
    while queue and len(seen) < cap:
        i = queue.pop(0)
        a = pool[i]
        ci, cj = int(a["lat"] * 111320.0 // radius_m), int(a["lon"] * kx // radius_m)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for k in cell.get((ci + di, cj + dj), []):
                    if k in seen:
                        continue
                    b = pool[k]
                    if math.hypot((b["lat"] - a["lat"]) * 111320.0, (b["lon"] - a["lon"]) * kx) <= radius_m:
                        seen.add(k)
                        queue.append(k)
    members = []
    for k in seen:
        r = dict(pool[k])
        r["distance_m"] = round(_dist_m(me["lat"], me["lon"], r["lat"], r["lon"]), 1)
        r["band"] = (r.get("confidence_band") or "NOT_RATED").upper()
        r["selected"] = r["id"] == cid
        members.append(r)
    members.sort(key=lambda r: (not r["selected"], -(r.get("confidence_numeric") or 0), -abs(r.get("score") or 0)))
    return {"scope": scope, "radius_m": radius_m, "members": members, "capped": len(seen) >= cap,
            "note": "Candidates of %s lying together with this one (each within %.0f m of another). A reading "
                    "aid only: nothing is merged or changed." % (scope, radius_m)}


def interpretation(root: str, cid: str) -> Dict[str, Any]:
    """Everything the laboratory has said about one candidate: Steward band and reasoning, the
    stored debate (each perspective's stance and reasons, the synthesis note), the investigation's
    own summary, your reviews, evidence, known-site and same-place notes. Read-only."""
    d = candidate_detail(root, cid)
    conn = _conn(root)
    try:
        inv = conn.execute("SELECT i.interpretation_summary, i.objective FROM candidate c JOIN investigation i "
                           "ON i.id = c.investigation_id WHERE c.id = ?", (cid,)).fetchone()
        reviews = []
        if _has(conn, "candidate_review"):
            reviews = [dict(r) for r in conn.execute(
                "SELECT previous_status, new_status, reason, reviewed_at FROM candidate_review WHERE candidate_id = ? "
                "ORDER BY id DESC LIMIT 10", (cid,))]
        hyp = conn.execute("SELECT h.statement FROM candidate c JOIN hypothesis h ON h.id = c.hypothesis_id "
                           "WHERE c.id = ?", (cid,)).fetchone()
    finally:
        conn.close()
    d["investigation_summary"] = (inv["interpretation_summary"] if inv else None) or None
    d["reviews"] = reviews
    d["hypothesis"] = hyp[0] if hyp else None
    return d
