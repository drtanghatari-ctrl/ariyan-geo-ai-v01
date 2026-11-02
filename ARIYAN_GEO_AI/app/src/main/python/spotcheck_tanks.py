"""
spotcheck_tanks.py -- d4-v1 (2026-11-02), user-approved. READ-ONLY spot-check list.

Open question since ind-label-v1: tank farms and silo complexes that are NOT
mapped in OpenStreetMap can still produce candidates (mapped ones are already
labelled and moved to the back of Pass 2). No rule can be justified without
real checks, so this module only builds a ranked list for the user to look at
on True colour, and stores the user's verdicts. Decisions come afterwards,
from the verdict counts, exactly as d3 did for ind-label-v1.

WHO IS LISTED: candidates that are not Rejected, have a stored lc-v2 land-cover
row (ESA WorldCover), have NO mapped industry within 300 m (those are already
handled), and whose RING (the window around the ~15 m centre) is at least
MIN_RING_BUILT built-up. Ranked by ring built-up share, then centre built-up.

CONTEXT SHOWN, never used to rank: nearest mapped industry within 2 km (kind,
distance) and the nearest recorded archaeological site. A village on a tell is
also built-up, so a high built-up ring is NOT a sign of industry by itself --
that is exactly what the spot-check is for.

VERDICTS: one per candidate (the newest wins; every one is kept), stored in
spotcheck_verdict. A verdict NEVER changes a status, review, confidence,
evidence row or job. Values: TANK_OR_SILO, OTHER_INDUSTRY, VILLAGE_OR_TOWN,
OPEN_GROUND_OR_SITE, CANT_TELL.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

import grand_project_db as db

VERSION = "d4-v1"
MIN_RING_BUILT = 0.15
INDUSTRY_LABEL_M = 300.0
CONTEXT_RADIUS_M = 2000.0
VERDICTS = {
    "TANK_OR_SILO": "Tank farm / silos",
    "OTHER_INDUSTRY": "Other industry",
    "VILLAGE_OR_TOWN": "Village / town",
    "OPEN_GROUND_OR_SITE": "Open ground / site",
    "CANT_TELL": "Can't tell",
}
STATUS_LABELS = {"GENERATED": "Open", "SUPPORTED": "Supported", "INCONCLUSIVE": "Inconclusive"}
STATEMENT = ("Read-only list for checking on True colour. A verdict is your note only: it never changes a "
             "status, review, confidence or evidence row. Built-up land also means villages on tells, so "
             "a place on this list is not a sign of industry by itself.")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS spotcheck_verdict (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id  TEXT NOT NULL,
    verdict       TEXT NOT NULL,
    note          TEXT,
    recorded_at   TEXT NOT NULL,
    version       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spotcheck_verdict_cand ON spotcheck_verdict(candidate_id);
"""


def _has_table(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _latest_verdicts(conn) -> Dict[str, Dict[str, Any]]:
    if not _has_table(conn, "spotcheck_verdict"):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for r in conn.execute("SELECT candidate_id, verdict, note, recorded_at FROM spotcheck_verdict ORDER BY id"):
        out[r["candidate_id"]] = {"verdict": r["verdict"], "note": r["note"], "recorded_at": r["recorded_at"]}
    return out


def spotcheck(db_root: str, limit: int = 40, include_checked: bool = True) -> Dict[str, Any]:
    import industrial_index as ii
    try:
        import known_sites
    except Exception:
        known_sites = None
    conn = db.get_connection(db_root)
    try:
        db.initialize_schema(conn)
        if not _has_table(conn, "candidate_land_cover_v2"):
            return {"version": VERSION, "rows": [], "summary": None, "statement": STATEMENT,
                    "note": "No land-cover (lc-v2) rows stored yet, so there is nothing to rank."}
        rows = [dict(r) for r in conn.execute(
            "SELECT c.id, c.lat, c.lon, c.status, c.score, c.confidence_band, lc.c_built, lc.r_built, "
            "lc.ring_valid, lc.centre_valid, j.title AS job_title FROM candidate c "
            "JOIN candidate_land_cover_v2 lc ON lc.candidate_id = c.id "
            "LEFT JOIN wide_area_search_tile t ON t.investigation_id = c.investigation_id "
            "LEFT JOIN wide_area_search_job j ON j.id = t.job_id "
            "WHERE c.status != 'REJECTED' AND lc.ring_valid > 0 AND COALESCE(lc.r_built, 0) >= ?",
            (MIN_RING_BUILT,))]
        verdicts = _latest_verdicts(conn)
    finally:
        conn.close()

    listed, near_mapped = [], 0
    for r in rows:
        try:
            lat, lon = float(r["lat"]), float(r["lon"])
        except (TypeError, ValueError):
            continue
        feats = ii.features_within(lat, lon, CONTEXT_RADIUS_M) if ii.in_coverage(lat, lon) else []
        if feats and float(feats[0].get("distance_m") or 0.0) <= INDUSTRY_LABEL_M:
            near_mapped += 1                    # already labelled by ind-label-v1: not part of this check
            continue
        r["industry_2km"] = ({"kind": feats[0].get("kind"), "distance_m": round(float(feats[0].get("distance_m") or 0), 0)}
                             if feats else None)
        listed.append(r)
    listed.sort(key=lambda r: (-(r["r_built"] or 0.0), -(r["c_built"] or 0.0), r["id"]))
    total = len(listed)
    checked = [r for r in listed if r["id"] in verdicts]
    page = listed if include_checked else [r for r in listed if r["id"] not in verdicts]
    page = page[:max(1, int(limit))]
    out_rows = []
    for r in page:
        ks = None
        if known_sites is not None:
            try:
                ks = known_sites.annotate(r["lat"], r["lon"]).get("text")
            except Exception:
                ks = None
        out_rows.append({
            "id": r["id"], "lat": r["lat"], "lon": r["lon"],
            "status": STATUS_LABELS.get(r["status"], r["status"]), "band": r["confidence_band"],
            "z": r["score"], "job_title": r["job_title"],
            "ring_built": round(r["r_built"] or 0.0, 3), "centre_built": round(r["c_built"] or 0.0, 3),
            "industry_2km": r["industry_2km"], "known_site": ks, "verdict": verdicts.get(r["id"])})
    counts = {k: 0 for k in VERDICTS}
    for r in checked:
        counts[verdicts[r["id"]]["verdict"]] = counts.get(verdicts[r["id"]]["verdict"], 0) + 1
    return {"version": VERSION, "min_ring_built": MIN_RING_BUILT, "rows": out_rows, "statement": STATEMENT,
            "verdict_names": VERDICTS,
            "summary": {"listed": total, "checked": len(checked), "excluded_near_mapped_industry": near_mapped,
                        "verdicts": counts}}


def spotcheck_json(db_root: str, limit: int = 40, include_checked: bool = True) -> str:
    try:
        return json.dumps(spotcheck(db_root, int(limit), bool(include_checked)), default=str)
    except Exception as e:                     # shown, never hidden
        return json.dumps({"error": "%s: %s" % (type(e).__name__, e)})


def record_verdict(db_root: str, candidate_id: str, verdict: str, note: str = "") -> Dict[str, Any]:
    verdict = str(verdict or "").upper()
    if verdict not in VERDICTS:
        raise ValueError("verdict must be one of " + ", ".join(VERDICTS))
    conn = db.get_connection(db_root)
    try:
        db.initialize_schema(conn)
        if conn.execute("SELECT 1 FROM candidate WHERE id = ?", (candidate_id,)).fetchone() is None:
            raise KeyError("candidate %s not found" % candidate_id)
        conn.executescript(_SCHEMA)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT INTO spotcheck_verdict (candidate_id, verdict, note, recorded_at, version) "
                     "VALUES (?, ?, ?, ?, ?)", (candidate_id, verdict, (note or "")[:500], now, VERSION))
        conn.commit()
    finally:
        conn.close()
    return {"candidate_id": candidate_id, "verdict": verdict, "recorded_at": now}


def record_verdict_json(db_root: str, candidate_id: str, verdict: str, note: str = "") -> str:
    try:
        return json.dumps(record_verdict(db_root, candidate_id, verdict, note))
    except Exception as e:
        return json.dumps({"error": "%s: %s" % (type(e).__name__, e)})
