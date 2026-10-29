"""
single_point_jobs.py -- sp-v1 (2026-10-29), sp-v1.1 (2026-10-29)

sp-v1.1: reads the AOI shape the app really stores (evidence_record.py:
center_lat / center_lon / radius_m, no corners); sp-v1 expected a
different shape and silently listed nothing. Left-out runs are now
reported with their reason ("not_eligible"), never hidden.

A single-point investigation (Main screen "Run") becomes a ONE-TILE
wide-area search job, so every job feature works on it without special
cases: Refine top N / Refine selected (live-DEM Pass 2), Auto run, Job
target, Terrain labels, Land cover, Provenance check, Job trust, the job
report and Final Image.

HOW (no new science, no copied data): candidates are tied to a job only
through wide_area_search_tile.investigation_id. This module writes
  * one wide_area_search_job row, input_kind 'SINGLE_POINT', status
    COMPLETE, its box = the investigation's own analysis window (the
    stored AOI), tile_size_m = 2 x the AOI radius;
  * one wide_area_search_tile row, status DONE, pointing at the EXISTING
    investigation.
The investigation, its candidates and every piece of evidence stay
exactly as they are; refinement results attach to the original
candidates.

Which investigations qualify: an investigation from
investigation_multi_mobile.run_investigation_multi_json with at least one
candidate, not already pointed at by any tile, and whose objective does
not name a wide-area tile (guards a tile run that is between "persisted"
and "tile marked DONE"; such a run is linked by its own job moments
later and must never be claimed here).

New runs register themselves (grand_project_sync.record_investigation_
results(..., register_single_point_job=True), passed by MainActivity).
Older runs are converted only when the user chooses ("Single points ->
jobs..." in the Grand Project Candidates tab).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import grand_project_db as db
from coordinate import meters_per_degree

VERSION = "sp-v1.1"
INPUT_KIND = "SINGLE_POINT"
WORKFLOW = "investigation_multi_mobile.run_investigation_multi_json"
TILE_OBJECTIVE_PREFIX = "Wide-area search "


class SinglePointJobError(Exception):
    """A single investigation that cannot be turned into a job; the message says why."""


def _aoi(params_json: Optional[str]) -> Dict[str, Any]:
    """The investigation's stored analysis window. sp-v1.1: the real shape
    is evidence_record.py's {"center_lat", "center_lon", "radius_m",
    "grid_size", "cell_size_m"} (no box corners), so the box is rebuilt
    with coordinate.meters_per_degree(), the same WGS84 formula
    build_aoi() used for the run. A full AreaOfInterest dict ("center" +
    corners) is also accepted."""
    try:
        p = json.loads(params_json or "")
    except (TypeError, ValueError):
        raise SinglePointJobError("its analysis window (AOI) is not stored")
    if not isinstance(p, dict):
        raise SinglePointJobError("its analysis window (AOI) is not stored")
    try:
        if "center_lat" in p:
            lat, lon = float(p["center_lat"]), float(p["center_lon"])
        else:
            lat, lon = float(p["center"]["lat"]), float(p["center"]["lon"])
        r = float(p["radius_m"])
    except (KeyError, TypeError, ValueError):
        raise SinglePointJobError("its stored analysis window (AOI) is incomplete")
    if r <= 0 or not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise SinglePointJobError("its stored analysis window (AOI) is not a valid box")
    if all(k in p for k in ("min_lat", "max_lat", "min_lon", "max_lon")):
        box = {k: float(p[k]) for k in ("min_lat", "max_lat", "min_lon", "max_lon")}
    else:
        m_lat, m_lon = meters_per_degree(lat)
        box = {"min_lat": lat - r / m_lat, "max_lat": lat + r / m_lat,
               "min_lon": lon - r / m_lon, "max_lon": lon + r / m_lon}
    if box["min_lat"] >= box["max_lat"] or box["min_lon"] >= box["max_lon"]:
        raise SinglePointJobError("its stored analysis window (AOI) is not a valid box")
    return dict(lat=lat, lon=lon, radius_m=r, **box)


_UNLINKED_SQL = """
    SELECT i.id, i.grand_project_id, i.objective, i.workflow_reference,
           i.parameters_json, i.created_at,
           (SELECT COUNT(*) FROM candidate c WHERE c.investigation_id = i.id) AS n_candidates
    FROM investigation i
    WHERE NOT EXISTS (SELECT 1 FROM wide_area_search_tile t WHERE t.investigation_id = i.id)
      AND EXISTS (SELECT 1 FROM candidate c WHERE c.investigation_id = i.id)
"""


def _qualifies(row: Dict[str, Any]) -> Optional[str]:
    """None when the row can become a job, else the reason it cannot."""
    if (row.get("workflow_reference") or "") != WORKFLOW:
        return "not a single-point evidence run"
    if (row.get("objective") or "").startswith(TILE_OBJECTIVE_PREFIX):
        return "belongs to a wide-area job (its tile is linked when that run finishes)"
    try:
        _aoi(row.get("parameters_json"))
    except SinglePointJobError as e:
        return str(e)
    return None


def _scan(db_root: str):
    conn = db.get_connection(db_root)
    try:
        db.initialize_schema(conn)
        rows = [dict(r) for r in conn.execute(_UNLINKED_SQL + " ORDER BY i.created_at DESC").fetchall()]
    finally:
        conn.close()
    ok, not_ok = [], []
    for r in rows:
        why = _qualifies(r)
        if why is not None:
            not_ok.append({"investigation_id": r["id"], "created_at": r["created_at"],
                           "n_candidates": int(r["n_candidates"]), "reason": why})
            continue
        a = _aoi(r["parameters_json"])
        ok.append({
            "investigation_id": r["id"],
            "created_at": r["created_at"],
            "lat": a["lat"], "lon": a["lon"],
            "radius_m": a["radius_m"],
            "n_candidates": int(r["n_candidates"]),
        })
    return ok, not_ok


def list_single_points(db_root: str) -> List[Dict[str, Any]]:
    """Every single-point investigation that has candidates and no job yet,
    newest first. Read-only."""
    return _scan(db_root)[0]


def _summary(not_ok: List[Dict[str, Any]]) -> str:
    """sp-v1.1: never hide a left-out run silently; group by reason."""
    groups: Dict[str, List[int]] = {}
    for n in not_ok:
        g = groups.setdefault(n["reason"], [0, 0])
        g[0] += 1
        g[1] += n["n_candidates"]
    return "\n".join("%d investigation(s), %d candidate(s): %s" % (g[0], g[1], why)
                     for why, g in sorted(groups.items(), key=lambda kv: -kv[1][0]))


def _title(a: Dict[str, Any], created_at: str) -> str:
    return "Single point %.5f, %.5f (%s)" % (a["lat"], a["lon"], (created_at or "")[:10])


def make_single_point_job(db_root: str, investigation_id: str) -> str:
    """Turns ONE single-point investigation into a one-tile COMPLETE job.
    Returns the new job id. Raises SinglePointJobError (with the reason)
    when it does not qualify. Atomic: the job row and its tile row are
    written in one transaction, and the 'not already linked' check runs
    inside it, so a second call can never create a twin job."""
    conn = db.get_connection(db_root)
    try:
        db.initialize_schema(conn)
        r = conn.execute(
            "SELECT i.*, (SELECT COUNT(*) FROM candidate c WHERE c.investigation_id = i.id) AS n_candidates "
            "FROM investigation i WHERE i.id = ?", (investigation_id,)).fetchone()
        if r is None:
            raise SinglePointJobError("no investigation with id %r" % (investigation_id,))
        row = dict(r)
        if int(row["n_candidates"]) == 0:
            raise SinglePointJobError("it has no candidates, so there is nothing to refine")
        why = _qualifies(row)
        if why is not None:
            raise SinglePointJobError(why)
        a = _aoi(row["parameters_json"])
        job_id = db._new_id()
        now = db._now_iso()
        title = _title(a, row["created_at"])
        with conn:
            linked = conn.execute(
                "SELECT job_id FROM wide_area_search_tile WHERE investigation_id = ? LIMIT 1",
                (investigation_id,)).fetchone()
            if linked is not None:
                raise SinglePointJobError("it already belongs to job %s" % linked["job_id"][:6])
            conn.execute(
                """
                INSERT INTO wide_area_search_job
                    (id, grand_project_id, hypothesis_id, title, input_kind,
                     place_name, geographic_suggestion_id, min_lat, max_lat,
                     min_lon, max_lon, tile_size_m, n_tiles, status,
                     created_at, last_updated_at)
                VALUES (?, ?, NULL, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, 1, 'COMPLETE', ?, ?)
                """,
                (job_id, row["grand_project_id"], title, INPUT_KIND,
                 a["min_lat"], a["max_lat"], a["min_lon"], a["max_lon"],
                 2.0 * a["radius_m"], now, now))
            conn.execute(
                """
                INSERT INTO wide_area_search_tile
                    (id, job_id, tile_index, center_lat, center_lon, status,
                     investigation_id, error_message, started_at, completed_at)
                VALUES (?, ?, 0, ?, ?, 'DONE', ?, NULL, ?, ?)
                """,
                (db._new_id(), job_id, a["lat"], a["lon"], investigation_id,
                 row["created_at"], now))
    finally:
        conn.close()
    db.log_timeline_event(
        db_root, row["grand_project_id"], "SINGLE_POINT_JOB_CREATED",
        related_entity_type="wide_area_search_job", related_entity_id=job_id,
        description="%s: single-point investigation %s registered as one-tile job '%s' "
                    "(%d candidate(s); no data copied or changed)."
                    % (VERSION, investigation_id[:8], title, int(row["n_candidates"])))
    return job_id


def register_after_run(db_root: str, investigation_id: str) -> Optional[str]:
    """Called right after a new single-point run is persisted. Returns the
    new job id, or None when the run has no candidates (nothing to refine,
    so no empty job is created)."""
    try:
        return make_single_point_job(db_root, investigation_id)
    except SinglePointJobError:
        return None


# ------------------------------------------------------------------ Kotlin boundary

def list_single_points_json(db_root: str) -> str:
    try:
        ok, not_ok = _scan(db_root)
        return json.dumps({"version": VERSION, "items": ok,
                           "not_eligible": not_ok, "not_eligible_summary": _summary(not_ok)})
    except Exception as e:  # surfaced to the user, never hidden
        return json.dumps({"error": str(e)})


def make_single_point_jobs_json(db_root: str, ids_json: str) -> str:
    """ids_json: JSON array of full investigation ids (from the list above).
    Converts each one independently; one failure never stops the others."""
    try:
        ids = json.loads(ids_json)
        if not isinstance(ids, list):
            raise ValueError
    except (TypeError, ValueError):
        return json.dumps({"error": "expected a JSON list of investigation ids"})
    created, skipped = [], []
    for inv in ids:
        try:
            created.append({"investigation_id": inv, "job_id": make_single_point_job(db_root, str(inv))})
        except SinglePointJobError as e:
            skipped.append({"investigation_id": inv, "reason": str(e)})
        except Exception as e:
            skipped.append({"investigation_id": inv, "reason": "failed: %s" % e})
    return json.dumps({"version": VERSION, "created": created, "skipped": skipped})
