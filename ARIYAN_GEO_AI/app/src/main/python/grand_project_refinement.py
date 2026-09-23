"""
grand_project_refinement.py

WIDE-AREA SEARCH, PASS 2 ("refine the best Pass 1 candidates").

WHY THIS EXISTS: Pass 1 is a cheap DEM-only sweep (see
wide_area_search_mobile.py's DEM-ONLY SWEEP note). It finds candidates
but runs none of the satellite checks (NDVI/Thermal/Optical/SAR) and
skips Detection Stability's re-fetches. Pass 2 spends the expensive
full-evidence run only where it is most worth spending: on the top N
Pass 1 candidates, ranked by their own DEM |z-score|.

NEW FILE, NO EXISTING FILE EDITED. This module only READS and CALLS what
already works (grand_project_db.py, grand_project_sync.py's private
matching helpers, investigation_multi_mobile.run_investigation_multi_
json(), debate_mobile.run_debate_json(), wide_area_search_mobile's
window/health helpers, sh_backoff, dem_source_mobile). Nothing in
grand_project_sync.py / grand_project_db.py / wide_area_search_mobile.py
is modified, so none of the already-confirmed on-device behaviour can be
disturbed by adding this file.

LATER EDIT (2026-09-21, land-cover flags): this file was edited ONCE
after it was first written, only to let selection skip candidates that
land_cover_flags.py has flagged as trees / buildings / water (see item 1b
below). The edit is additive: skip_flagged is the LAST parameter of the
three affected functions, and a job whose candidates were never
land-cover checked behaves exactly as before. skip_flagged=False gives
the original behaviour unconditionally.

LATER EDIT (2026-09-23, "refine selected candidates" + DEM source): also
additive, with the existing top-N path unchanged apart from two new keys:
- DEM SOURCE IS RECORDED per refinement. The marker row's detail now
  carries "dem_source" (LIVE / OFFLINE_FALLBACK / OFFLINE_FIRST / UNKNOWN),
  "dem_type" (the live dataset asked for, only when LIVE) and
  "dem_live_failure_reason" (short reason, only for OFFLINE_FALLBACK). It
  is read from the investigation's own limitations with the SAME parser
  (wide_area_search_mobile.parse_tile_health) the completion summary
  already used, so the two can never disagree. Before this, live vs
  offline had to be inferred from processing-time gaps.
- SELECTED MODE (run_selected_refinement_json): the user names candidate
  ids (full ids or unique prefixes of at least 6 characters). They are
  resolved ONLY against the given job's own candidates, so an id from a
  different (for example a known-corrupted) job is refused, never
  refined. Ambiguous or unknown references are reported, never guessed.
  A candidate that was refined before MAY be refined again in this mode
  (allow_repeat): the new rows are additional, separately-tagged
  observations (their own refinement_investigation_id); nothing earlier
  is deleted or edited, and confidence_history stays append-only.
- REQUIRE LIVE DEM (require_live_dem, default True in selected mode,
  False in top-N mode): before each candidate the live-DEM quota breaker
  is checked, and if the candidate's primary DEM still came from the
  offline library, its results are DISCARDED before anything is written
  (no investigation row, no evidence, no marker) and the pass stops;
  the remaining candidates are listed as not started. Reason: the offline
  library is the same Copernicus GLO-30 the wide-area sweep was built
  from, so an offline "reproduction" is partly the data agreeing with
  itself. The discarded run still cost its Copernicus calls -- a known,
  bounded waste of at most one candidate per pass.

THE APPROVED DESIGN (2026-09-21):
1. RANK by abs(candidate.score) (the stored DEM peak_zscore, which is
   signed; the detector itself sorts by abs). Candidates too close to
   one already chosen (or already refined) are skipped, so the ~2 m
   apart duplicates seen at Persepolis are not refined twice.
1b. SKIP FLAGGED (added 2026-09-21): candidates that land_cover_flags has
   flagged (tree cover + built-up >= 20% of the ~60 m window, or open
   water) are left out of the selection, and counted in the result. They
   are NOT deleted or changed; the user can choose to include them
   (skip_flagged=False). A flagged candidate could still be a real buried
   feature under an orchard or field -- the flag only says the DEM bump
   is probably a tree stand or a building. A candidate that was never
   land-cover checked is never skipped.
2. RUN one small full-evidence investigation centred on each chosen
   candidate's own coordinates, stored as its OWN investigation row so
   provenance stays intact. The window is the proven 500 m / 96-cell
   window (wide_area_search_mobile.derive_analysis_window(500)).
3. LINK, DON'T DUPLICATE: NO new candidate rows are created. Evidence is
   written against the ORIGINAL candidate_id. Each row's detail carries
   "refinement_investigation_id" and "refines_candidate_id" (added to a
   copy of the real detail dict; nothing is reshaped or summarised).
4. DEM RE-DETECTION is recorded as its own row: evidence_type "DEM",
   relation "refinement_dem_check", saying whether the refinement window
   reproduced a DEM anomaly near the original position (within a
   tolerance derived from the cell sizes) and, if so, the real anomaly.
   NOT REPRODUCED IS NOT CONTRADICTED: a different window has a
   different local reference population, so the row is a plain record of
   what happened, never a fabricated "contradicts".
5. STEWARD: only if a DEM anomaly was reproduced is there something to
   evaluate. Then the Steward's real output for that anomaly is appended
   to confidence_history (append-only; the Pass 1 rows stay) and the
   candidate's "current" confidence fields are updated. If NOT
   reproduced, or the debate/Steward failed, NO confidence row is
   written -- an honest gap, never a fabricated value.
6. MATCHING is radius-based (haversine), the same approach GPR/ERT
   colocation already uses.

WHAT IS DELIBERATELY NOT DONE:
- Satellite evidence is only recorded when the refinement's own DEM
  anomaly matched the original AND that anomaly's correlation entry lists
  the source as supporting it (exactly Phase 1's rule: only "supports"
  rows are written, never "checked, nothing found" rows). If credentials
  are blank or a source failed, that is in the refinement's own
  limitations (copied into the DEM row) -- "not run" is never recorded as
  "checked".
- GPR/ERT are not re-run (they are manual, site-anchored inputs and are
  already attached in Pass 1 wherever they fall within colocation range).

IDEMPOTENCY / RESUME: the "refinement_dem_check" row is written LAST for a
candidate and is also the marker that the candidate is done. A candidate
without it is eligible again (this is also how a FAILED attempt is
retried). Writes are separate short SQLite transactions (like every other
writer in this project), so a process kill in the few milliseconds between
them could, in principle, leave satellite rows without the marker and
cause them to be recorded a second time on retry -- rare, visible via the
"refinement_investigation_id" in each row, and never data loss.

COST WARNING: each refinement is a FULL run: about 2 live OpenTopography
calls plus up to ~8 Detection Stability re-fetches (free-key cap is about
50 calls a day) plus Copernicus calls for the satellite checks. Start with
a small N.

VERIFICATION STATUS: written 2026-09-21 and exercised in a sandbox with
FIXTURE investigation/debate JSON (the real evidence engines need live
network access and credentials that do not exist in the sandbox). It has
NOT been run on real hardware. Treat it as unverified until it has.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any, Dict, List, Optional

import debate_mobile
import dem_source_mobile
import grand_project_db as db
import grand_project_sync as sync
import investigation_multi_mobile
import land_cover_flags
import sh_backoff
import wide_area_search_mobile as was

REFINEMENT_RELATION = "refinement_dem_check"
REFINEMENT_TILE_SIZE_M = 500.0 # -> proven 500 m radius / 96-cell window
DEFAULT_MIN_SEPARATION_M = 30.0
MIN_MATCH_TOLERANCE_M = 30.0 # same floor as the GPR/ERT colocation rule
MATCH_TOLERANCE_CELLS = 4.0 # same multiplier as the GPR/ERT rule
FALLBACK_PASS1_CELL_SIZE_M = 10.4 # the tested cell size, used only if the
                                    # original investigation's own is unreadable
_SATELLITE_DETAIL_TOLERANCE_M = 5.0 # same as grand_project_sync's own


DEM_SOURCE_LIVE = "LIVE"
DEM_SOURCE_OFFLINE_FALLBACK = "OFFLINE_FALLBACK"
DEM_SOURCE_OFFLINE_FIRST = "OFFLINE_FIRST"
DEM_SOURCE_UNKNOWN = "UNKNOWN"
MIN_ID_PREFIX_LEN = 6
MAX_SELECTED_CANDIDATES = 20


class RefinementError(Exception):
    """A genuine caller error (unknown job, unknown candidate)."""


class LiveDemUnavailableError(Exception):
    """require_live_dem was set and the live DEM could not be used for
    this candidate. Nothing was written for it."""


def _status_path(data_root: str, job_id: str) -> str:
    # A DIFFERENT file from wide_area_search_status_<job>.json on purpose,
    # so Pass 2 progress can never overwrite or be mistaken for Pass 1's.
    return os.path.join(data_root, f"wide_area_refine_status_{job_id}.json")


def _write_refine_status(
    data_root: str, job_id: str, done: int, total: int,
    detail: str = "", phase: str = "running", health: str = "",
) -> None:
    """Best-effort, never raises (a progress write must never fail the run)."""
    try:
        payload: Dict[str, Any] = {
            "phase": phase, "done": done, "total": total, "detail": detail,
        }
        if health:
            payload["health"] = health
        was._atomic_write_json(_status_path(data_root, job_id), payload)
    except Exception:
        pass


# ============================ SELECTION ============================

def _job_candidates(db_root: str, job_id: str) -> List[Dict[str, Any]]:
    conn = db.get_connection(db_root)
    try:
        db.initialize_schema(conn)
        rows = conn.execute(
            """
            SELECT c.id, c.grand_project_id, c.investigation_id, c.lat, c.lon,
                   c.score, c.confidence_band, c.confidence_numeric
            FROM candidate c
            WHERE c.investigation_id IN (
                SELECT investigation_id FROM wide_area_search_tile
                WHERE job_id = ? AND investigation_id IS NOT NULL
            )
            """,
            (job_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _refined_candidate_ids(db_root: str) -> set:
    conn = db.get_connection(db_root)
    try:
        db.initialize_schema(conn)
        rows = conn.execute(
            "SELECT DISTINCT candidate_id FROM evidence_link WHERE relation = ?",
            (REFINEMENT_RELATION,),
        ).fetchall()
        return {r["candidate_id"] for r in rows}
    finally:
        conn.close()


def _refinement_history(db_root: str, candidate_id: str) -> List[Dict[str, Any]]:
    """Earlier refinement markers of one candidate, oldest first, as
    {"reproduced", "match_distance_m", "dem_source"}. For markers written
    before 2026-09-23 (no dem_source key) the source is inferred from the
    stored limitations ONLY when they contain an offline-DEM note
    ("..._INFERRED"); otherwise it is "NOT_RECORDED". Never raises."""
    try:
        conn = db.get_connection(db_root)
        try:
            db.initialize_schema(conn)
            rows = conn.execute(
                "SELECT detail_json FROM evidence_link WHERE candidate_id = ? "
                "AND relation = ? ORDER BY id ASC",
                (candidate_id, REFINEMENT_RELATION),
            ).fetchall()
        finally:
            conn.close()
        out = []
        for r in rows:
            try:
                d = json.loads(r["detail_json"]) if r["detail_json"] else {}
            except (TypeError, ValueError):
                d = {}
            src = d.get("dem_source")
            if not src:
                # Marker from before 2026-09-23: infer ONLY a positive
                # offline finding from its stored limitations. No offline
                # note is NOT proof of a live fetch, so it stays NOT_RECORDED.
                health = was.parse_tile_health(
                    json.dumps({"limitations": d.get("refinement_limitations") or []}))
                if health and health.get("dem_offline_first"):
                    src = DEM_SOURCE_OFFLINE_FIRST + "_INFERRED"
                elif health and health.get("dem_offline"):
                    src = DEM_SOURCE_OFFLINE_FALLBACK + "_INFERRED"
                else:
                    src = "NOT_RECORDED"
            out.append({
                "reproduced": d.get("reproduced"),
                "match_distance_m": d.get("match_distance_m"),
                "dem_source": src,
            })
        return out
    except Exception:
        return []


def _dem_source_of(investigation_json: str, demtype: str) -> Dict[str, Any]:
    """Which DEM the investigation's PRIMARY fetch actually used, read from
    its own recorded limitations by the same parser the run-health summary
    uses. Never raises."""
    health = was.parse_tile_health(investigation_json)
    if health is None:
        return {"dem_source": DEM_SOURCE_UNKNOWN, "dem_type": None,
                "dem_live_failure_reason": None}
    if health.get("dem_offline_first"):
        return {"dem_source": DEM_SOURCE_OFFLINE_FIRST, "dem_type": None,
                "dem_live_failure_reason": None}
    if health.get("dem_offline"):
        return {"dem_source": DEM_SOURCE_OFFLINE_FALLBACK, "dem_type": None,
                "dem_live_failure_reason": health.get("dem_reason")}
    return {"dem_source": DEM_SOURCE_LIVE, "dem_type": demtype,
            "dem_live_failure_reason": None}


def _live_dem_blocked_reason(api_key: str) -> Optional[str]:
    """Why a live DEM fetch cannot be attempted right now, or None."""
    if not api_key:
        return "no OpenTopography API key is saved on this device"
    try:
        status = dem_source_mobile.live_dem_quota_status()
    except Exception:
        status = None
    if status and status.get("suspended_now"):
        minutes = max(1, int(round(float(status.get("retry_in_s") or 0) / 60.0)))
        return (f"live OpenTopography is suspended for about {minutes} min "
                f"({status.get('reason') or 'quota or key rejected'})")
    return None


def _abs_score(c: Dict[str, Any]) -> float:
    try:
        return abs(float(c.get("score")))
    except (TypeError, ValueError):
        return 0.0


def select_refinement_candidates(
    db_root: str, job_id: str, n: int,
    min_separation_m: float = DEFAULT_MIN_SEPARATION_M,
    skip_flagged: bool = True,
) -> Dict[str, Any]:
    """Returns {"selected": [candidate dicts], "eligible": int,
    "already_refined": int, "skipped_near_duplicates": int,
    "job_candidates": int, "skip_flagged": bool, "skipped_flagged": int,
    "skipped_flagged_by_reason": {reason: count},
    "land_cover_unchecked": int}.

    skip_flagged (default True): candidates flagged by land_cover_flags
    (trees / buildings / water) are left out and counted in
    "skipped_flagged". Any problem reading the flags means "nothing is
    flagged" -- the flag can never break a refinement. "eligible" is the
    pool AFTER this exclusion. "land_cover_unchecked" is how many of the
    job's candidates have no land-cover row (so were NOT filtered); it is
    0 when skip_flagged is False.

    Ranking is abs(score) descending; a candidate with no score ranks last
    (never dropped). A candidate is skipped as a near-duplicate when it is
    within `min_separation_m` of one already selected in this call OR of
    one already refined earlier in this job, so re-running the pass after
    a partial run does not re-spend budget on a twin of finished work.
    """
    job = db.get_wide_area_search_job(db_root, job_id)
    if job is None:
        raise RefinementError(f"No wide-area search job with id {job_id!r} was found.")
    n = max(0, int(n))

    candidates = _job_candidates(db_root, job_id)
    refined_ids = _refined_candidate_ids(db_root)
    already = [c for c in candidates if c["id"] in refined_ids]
    eligible = [c for c in candidates if c["id"] not in refined_ids]

    flagged: Dict[str, str] = {}
    land_cover_unchecked = 0
    if skip_flagged:
        try:
            lc = land_cover_flags.job_flags(db_root, job_id)
            flagged = lc["flagged"]
            land_cover_unchecked = max(0, lc["candidates"] - lc["checked"])
        except Exception:
            flagged = {}
            land_cover_unchecked = 0
    skipped_flagged = 0
    skipped_flagged_by_reason: Dict[str, int] = {}
    if flagged:
        kept = []
        for c in eligible:
            reason = flagged.get(c["id"])
            if reason:
                skipped_flagged += 1
                skipped_flagged_by_reason[reason] = skipped_flagged_by_reason.get(reason, 0) + 1
            else:
                kept.append(c)
        eligible = kept

    eligible.sort(key=_abs_score, reverse=True)

    occupied = [(c["lat"], c["lon"]) for c in already
                if c.get("lat") is not None and c.get("lon") is not None]
    selected: List[Dict[str, Any]] = []
    skipped = 0
    for c in eligible:
        if len(selected) >= n:
            break
        if c.get("lat") is None or c.get("lon") is None:
            continue
        too_close = any(
            sync._haversine_distance_m(c["lat"], c["lon"], plat, plon) < min_separation_m
            for plat, plon in occupied
        )
        if too_close:
            skipped += 1
            continue
        selected.append(c)
        occupied.append((c["lat"], c["lon"]))

    return {
        "selected": selected,
        "eligible": len(eligible),
        "already_refined": len(already),
        "skipped_near_duplicates": skipped,
        "job_candidates": len(candidates),
        "skip_flagged": bool(skip_flagged),
        "skipped_flagged": skipped_flagged,
        "skipped_flagged_by_reason": skipped_flagged_by_reason,
        "land_cover_unchecked": land_cover_unchecked,
    }


def preview_refinement_selection_json(
    db_root: str, job_id: str, n: int = 5,
    min_separation_m: float = DEFAULT_MIN_SEPARATION_M,
    skip_flagged: bool = True,
) -> str:
    """Cheap, read-only: what a Pass 2 of size n WOULD refine. For a UI
    confirmation step before spending real API budget."""
    result = select_refinement_candidates(
        db_root, job_id, n, min_separation_m, skip_flagged=bool(skip_flagged))
    result["selected"] = [
        {"candidate_id": c["id"], "lat": c["lat"], "lon": c["lon"], "score": c["score"]}
        for c in result["selected"]
    ]
    return json.dumps(result)


def parse_candidate_refs(text: Any) -> List[str]:
    """Splits user input (a string, or a list of strings) into candidate
    references: separated by whitespace, commas or semicolons, lower-cased,
    duplicates dropped, order kept."""
    if isinstance(text, (list, tuple)):
        text = " ".join(str(t) for t in text)
    raw = str(text or "").replace(",", " ").replace(";", " ").split()
    out: List[str] = []
    for r in raw:
        r = r.strip().lower()
        if r and r not in out:
            out.append(r)
    return out


def resolve_candidate_refs(
    db_root: str, job_id: str, refs: Any,
) -> Dict[str, Any]:
    """Resolves references to candidates OF THIS JOB ONLY. Returns
    {"resolved": [candidate dicts, in the order given],
     "problems": [{"ref": str, "problem": str}]}.
    A reference must be a full id or a prefix of at least
    MIN_ID_PREFIX_LEN characters matching exactly one of the job's
    candidates. A reference that matches a candidate of ANOTHER job is
    reported as such (and refused) -- never refined under this job."""
    job = db.get_wide_area_search_job(db_root, job_id)
    if job is None:
        raise RefinementError(f"No wide-area search job with id {job_id!r} was found.")
    candidates = _job_candidates(db_root, job_id)
    refs = parse_candidate_refs(refs)
    resolved: List[Dict[str, Any]] = []
    problems: List[Dict[str, str]] = []
    seen_ids: set = set()
    for ref in refs:
        if len(ref) < MIN_ID_PREFIX_LEN:
            problems.append({"ref": ref, "problem":
                             f"too short (use at least {MIN_ID_PREFIX_LEN} characters)"})
            continue
        matches = [c for c in candidates if str(c["id"]).lower().startswith(ref)]
        if len(matches) == 1:
            c = matches[0]
            if c["id"] in seen_ids:
                problems.append({"ref": ref, "problem": "same candidate listed twice"})
                continue
            seen_ids.add(c["id"])
            resolved.append(c)
        elif len(matches) > 1:
            problems.append({"ref": ref, "problem":
                             f"matches {len(matches)} candidates of this job -- type more characters"})
        else:
            elsewhere = False
            try:
                conn = db.get_connection(db_root)
                try:
                    db.initialize_schema(conn)
                    row = conn.execute(
                        "SELECT 1 FROM candidate WHERE lower(substr(id, 1, ?)) = ? LIMIT 1",
                        (len(ref), ref),
                    ).fetchone()
                    elsewhere = row is not None
                finally:
                    conn.close()
            except Exception:
                elsewhere = False
            problems.append({"ref": ref, "problem":
                             "belongs to a different job, not refined here" if elsewhere
                             else "no candidate with this id"})
    if len(resolved) > MAX_SELECTED_CANDIDATES:
        for c in resolved[MAX_SELECTED_CANDIDATES:]:
            problems.append({"ref": str(c["id"])[:8], "problem":
                             f"over the limit of {MAX_SELECTED_CANDIDATES} per run"})
        resolved = resolved[:MAX_SELECTED_CANDIDATES]
    return {"resolved": resolved, "problems": problems}


def preview_selected_refinement_json(db_root: str, job_id: str, refs: Any) -> str:
    """Cheap, read-only: what a selected-candidates Pass 2 WOULD refine,
    with each candidate's earlier refinements (and their recorded DEM
    source) so the user can see what a repeat adds."""
    res = resolve_candidate_refs(db_root, job_id, refs)
    selected = []
    for c in res["resolved"]:
        history = _refinement_history(db_root, c["id"])
        selected.append({
            "candidate_id": c["id"], "lat": c["lat"], "lon": c["lon"],
            "score": c["score"], "confidence_band": c.get("confidence_band"),
            "previous_refinements": history,
        })
    return json.dumps({"selected": selected, "problems": res["problems"]})


# ============================ ONE CANDIDATE ============================

def _pass1_cell_size_m(db_root: str, investigation_id: str) -> float:
    """The cell size of the analysis that FOUND the candidate, read from
    that investigation's stored parameters (aoi.cell_size_m). Falls back to
    the tested 10.4 m only if it cannot be read."""
    try:
        inv = db.get_investigation(db_root, investigation_id)
        params = json.loads(inv["parameters_json"]) if inv and inv.get("parameters_json") else {}
        value = float(params.get("cell_size_m"))
        if value > 0:
            return value
    except (TypeError, ValueError, KeyError):
        pass
    return FALLBACK_PASS1_CELL_SIZE_M


def _with_provenance(detail: Optional[Dict[str, Any]], refinement_investigation_id: str,
                     candidate_id: str) -> Dict[str, Any]:
    out = dict(detail) if isinstance(detail, dict) else {}
    out["refinement_investigation_id"] = refinement_investigation_id
    out["refines_candidate_id"] = candidate_id
    return out


def refine_candidate(
    db_root: str,
    candidate_id: str,
    api_key: str = "",
    demtype: str = "SRTMGL1",
    ndvi_client_id: str = "",
    ndvi_client_secret: str = "",
    allow_repeat: bool = False,
    require_live_dem: bool = False,
) -> Dict[str, Any]:
    """Runs ONE full-evidence refinement of an existing Pass 1 candidate
    and records the results against THAT candidate (see module docstring).

    allow_repeat (default False): refine even if the candidate already has
    a refinement marker (selected mode only). require_live_dem (default
    False): raise LiveDemUnavailableError, having written NOTHING, if the
    live DEM cannot be attempted or the primary DEM came from the offline
    library.

    Raises RefinementError if the candidate does not exist. Any failure
    while RUNNING the investigation propagates (nothing has been written
    yet, so the candidate simply stays eligible); the pass-level caller
    catches it per candidate.

    Returns a summary dict (see keys below).
    """
    cand = db.get_candidate(db_root, candidate_id)
    if cand is None:
        raise RefinementError(f"No candidate with id {candidate_id!r} was found.")
    previous = _refinement_history(db_root, candidate_id)
    if previous and not allow_repeat:
        return {"candidate_id": candidate_id, "status": "ALREADY_REFINED"}
    if require_live_dem:
        blocked = _live_dem_blocked_reason(api_key)
        if blocked:
            raise LiveDemUnavailableError(blocked)

    grand_project_id = cand["grand_project_id"]
    lat, lon = cand["lat"], cand["lon"]
    window = was.derive_analysis_window(REFINEMENT_TILE_SIZE_M)
    radius_m, grid_size, refine_cell_m = (
        window["radius_m"], int(window["grid_size"]), window["cell_size_m"])

    investigation_json = investigation_multi_mobile.run_investigation_multi_json(
        lat, lon, radius_m, grid_size,
        dem_kernel_sigma_cells=was.DEM_KERNEL_SIGMA_CELLS,
        api_key=api_key,
        demtype=demtype,
        ndvi_client_id=ndvi_client_id,
        ndvi_client_secret=ndvi_client_secret,
        offline_data_root=db_root,
    )
    try:
        debate_json: Optional[str] = debate_mobile.run_debate_json(investigation_json)
    except Exception:
        debate_json = None # a debate failure never hides the evidence gathered

    dem_info = _dem_source_of(investigation_json, demtype)
    if require_live_dem and dem_info["dem_source"] != DEM_SOURCE_LIVE:
        # Checked BEFORE any write: this candidate gets no rows at all and
        # stays exactly as it was.
        why = dem_info.get("dem_live_failure_reason") or dem_info["dem_source"]
        raise LiveDemUnavailableError(
            f"the primary DEM came from the offline library ({why}); "
            f"results discarded, nothing recorded")

    investigation = json.loads(investigation_json)
    debate_result = json.loads(debate_json) if debate_json else None
    anomalies = investigation.get("anomalies") or []
    correlation = investigation.get("correlation") or []
    detail_by_source = {
        "NDVI": investigation.get("second_evidence_detail") or [],
        "THERMAL": investigation.get("fourth_evidence_detail") or [],
        "OPTICAL": investigation.get("fifth_evidence_detail") or [],
        "SAR": investigation.get("ninth_evidence_detail") or [],
    }

    # -- Did the refinement window reproduce a DEM anomaly here? --------
    dem_anoms = [(i, a) for i, a in enumerate(anomalies)
                 if a.get("evidence_type", "DEM") == "DEM"
                 and a.get("lat") is not None and a.get("lon") is not None]
    pass1_cell_m = _pass1_cell_size_m(db_root, cand["investigation_id"])
    tolerance_m = max(MIN_MATCH_TOLERANCE_M,
                      MATCH_TOLERANCE_CELLS * max(pass1_cell_m, refine_cell_m))
    matched_index: Optional[int] = None
    matched_anomaly: Optional[Dict[str, Any]] = None
    match_distance_m: Optional[float] = None
    for i, a in dem_anoms:
        d = sync._haversine_distance_m(lat, lon, a["lat"], a["lon"])
        if match_distance_m is None or d < match_distance_m:
            match_distance_m, matched_index, matched_anomaly = d, i, a
    reproduced = matched_anomaly is not None and match_distance_m <= tolerance_m
    if not reproduced:
        matched_index, matched_anomaly = None, None

    # -- Persist: investigation row first (provenance anchor) -----------
    objective = (
        f"Refinement (Pass 2, full evidence) of candidate {candidate_id[:8]} at "
        f"({lat:.6f}, {lon:.6f}) -- analysis radius {radius_m:.0f} m, "
        f"{grid_size}x{grid_size} grid, {refine_cell_m:.1f} m cells"
    )
    refinement_investigation_id = db.create_investigation(
        db_root, grand_project_id,
        objective=objective,
        workflow_reference="grand_project_refinement.refine_candidate",
        # Same shape as every other investigation row (the AOI dict itself,
        # which is what grand_project_sync stores), plus the refinement's own
        # provenance keys.
        parameters={
            **(investigation.get("aoi") or {}),
            "refines_candidate_id": candidate_id,
            "analysis_radius_m": radius_m,
            "grid_size": grid_size,
            "cell_size_m": refine_cell_m,
        },
    )

    satellite_recorded: List[str] = []
    if reproduced:
        corr_entry = sync._nearest_by_latlon(
            matched_anomaly["lat"], matched_anomaly["lon"], correlation)
        if corr_entry is not None:
            for source in corr_entry.get("supporting_sources", []):
                if source == "DEM":
                    continue
                matched_detail = sync._nearest_within(
                    matched_anomaly["lat"], matched_anomaly["lon"],
                    detail_by_source.get(source, []), _SATELLITE_DETAIL_TOLERANCE_M)
                base = matched_detail if matched_detail is not None else {"note": corr_entry.get("note")}
                db.add_evidence_link(
                    db_root, candidate_id,
                    evidence_type=source, relation="supports",
                    detail=_with_provenance(base, refinement_investigation_id, candidate_id),
                )
                satellite_recorded.append(source)

    # -- Steward confidence (only when there is something to evaluate) --
    confidence_recorded = False
    band = numeric = None
    steward_note = None
    if reproduced:
        debates_by_index: Dict[int, Dict[str, Any]] = {}
        if debate_result and not debate_result.get("error"):
            for d in debate_result.get("debates", []):
                cid = d.get("candidate_id") or ""
                if cid.startswith("#"):
                    try:
                        debates_by_index[int(cid.lstrip("#")) - 1] = d
                    except ValueError:
                        continue
        entry = debates_by_index.get(matched_index)
        if entry is None:
            steward_note = "No debate/Steward output was available for the reproduced anomaly."
        elif entry.get("steward_error"):
            steward_note = "The Steward could not evaluate the reproduced anomaly this run."
        else:
            conf = ((entry.get("steward") or {}).get("reasoning_trace") or {}).get("confidence") or {}
            band = conf.get("band")
            numeric = conf.get("clamped_confidence")
            if band is not None or numeric is not None:
                db.record_confidence_history(
                    db_root, candidate_id,
                    band=band, numeric_confidence=numeric,
                    reasoning_snapshot=conf.get("reasoning"),
                    triggering_investigation_id=refinement_investigation_id,
                )
                db.update_candidate_confidence(db_root, candidate_id, band, numeric)
                confidence_recorded = True
            else:
                steward_note = "The Steward output carried no confidence band."

    # -- The marker row: written LAST (see IDEMPOTENCY note) ------------
    if reproduced:
        note = ("The refinement window reproduced a DEM anomaly near this "
                "candidate's original position.")
    else:
        note = ("The refinement window did NOT reproduce a DEM anomaly within "
                "the match tolerance of this candidate's original position. "
                "That is not evidence against the candidate (a different window "
                "has a different local reference population), and it means no "
                "satellite or Steward result could be attached to it here.")
    db.add_evidence_link(
        db_root, candidate_id,
        evidence_type="DEM", relation=REFINEMENT_RELATION,
        detail=_with_provenance({
            "reproduced": bool(reproduced),
            "match_distance_m": match_distance_m,
            "match_tolerance_m": tolerance_m,
            "pass1_cell_size_m": pass1_cell_m,
            "refinement_cell_size_m": refine_cell_m,
            "refinement_analysis_radius_m": radius_m,
            "n_refinement_dem_anomalies": len(dem_anoms),
            "refinement_anomaly": matched_anomaly,
            "satellite_sources_recorded": satellite_recorded,
            "confidence_recorded": confidence_recorded,
            "steward_note": steward_note,
            "refinement_limitations": investigation.get("limitations") or [],
            "dem_source": dem_info["dem_source"],
            "dem_type": dem_info["dem_type"],
            "dem_live_failure_reason": dem_info["dem_live_failure_reason"],
            "repeat_refinement": bool(previous),
            "previous_refinements": len(previous),
            "note": note,
        }, refinement_investigation_id, candidate_id),
    )
    try:
        db.log_timeline_event(
            db_root, grand_project_id, "CANDIDATE_REFINED",
            related_entity_type="candidate", related_entity_id=candidate_id,
            description=(
                f"Pass 2 refinement finished ({dem_info['dem_source']} DEM"
                + (", repeat" if previous else "") + f"): DEM anomaly "
                f"{'reproduced' if reproduced else 'not reproduced'}"
                + (f"; satellite evidence: {', '.join(satellite_recorded)}"
                   if satellite_recorded else "")
                + (f"; confidence {band}/{numeric}" if confidence_recorded else "")
                + "."
            ),
        )
    except Exception:
        pass
    db.complete_investigation(
        db_root, refinement_investigation_id, grand_project_id,
        execution_status="COMPLETED",
        interpretation_summary=investigation.get("confidence_statement", ""),
    )

    return {
        "candidate_id": candidate_id,
        "status": "REFINED",
        "refinement_investigation_id": refinement_investigation_id,
        "reproduced": bool(reproduced),
        "match_distance_m": match_distance_m,
        "match_tolerance_m": tolerance_m,
        "satellite_sources_recorded": satellite_recorded,
        "confidence_recorded": confidence_recorded,
        "confidence_band": band,
        "confidence_numeric": numeric,
        "dem_source": dem_info["dem_source"],
        "dem_live_failure_reason": dem_info["dem_live_failure_reason"],
        "repeat_refinement": bool(previous),
        "_investigation_json": investigation_json, # stripped by the pass runner
    }


# ============================ THE PASS ============================

def _run_refinement_loop(
    data_root: str,
    job_id: str,
    chosen: List[Dict[str, Any]],
    api_key: str,
    demtype: str,
    ndvi_client_id: str,
    ndvi_client_secret: str,
    allow_repeat: bool,
    require_live_dem: bool,
) -> Dict[str, Any]:
    """The loop shared by top-N and selected mode. Arms the same throttle
    protections a wide-area job arms and ALWAYS disarms them in a
    `finally`. One candidate's failure never fails the pass. With
    require_live_dem, the first LiveDemUnavailableError STOPS the pass:
    that candidate and every later one are listed in "not_started" (each
    untouched, still eligible), because once live DEM is unavailable every
    further attempt would be discarded too."""
    total = len(chosen)
    job = db.get_wide_area_search_job(data_root, job_id)
    grand_project_id = job["grand_project_id"]

    tally = was._RunHealth(dem_only=False)
    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    not_started: List[Dict[str, Any]] = []
    stopped_reason: Optional[str] = None
    started = time.time()

    _write_refine_status(data_root, job_id, 0, total, "starting", health=was._render_run_health(tally))
    sh_backoff.arm()
    dem_source_mobile.arm_live_dem_quota_breaker()
    copernicus = live_dem = None
    try:
        for i, cand in enumerate(chosen):
            _write_refine_status(
                data_root, job_id, i, total,
                f"refining {i + 1}/{total}: running", health=was._render_run_health(tally))
            try:
                res = refine_candidate(
                    data_root, cand["id"], api_key=api_key, demtype=demtype,
                    ndvi_client_id=ndvi_client_id, ndvi_client_secret=ndvi_client_secret,
                    allow_repeat=allow_repeat, require_live_dem=require_live_dem)
                inv_json = res.pop("_investigation_json", None)
                if inv_json:
                    tally.add(was.parse_tile_health(inv_json)) # never raises
                else:
                    tally.add(None)
                results.append(res)
            except LiveDemUnavailableError as exc:
                stopped_reason = str(exc)
                not_started = [{"candidate_id": c["id"], "score": c.get("score")}
                               for c in chosen[i:]]
                try:
                    db.log_timeline_event(
                        data_root, grand_project_id, "REFINEMENT_STOPPED_NO_LIVE_DEM",
                        related_entity_type="candidate", related_entity_id=cand["id"],
                        description=(f"Pass 2 stopped before recording this candidate: "
                                     f"live DEM required but unavailable -- {exc}")[:500],
                    )
                except Exception:
                    pass
                break
            except Exception as exc:
                tally.add_failed()
                failures.append({"candidate_id": cand["id"],
                                 "error": f"{type(exc).__name__}: {exc}"})
                try:
                    db.log_timeline_event(
                        data_root, grand_project_id, "CANDIDATE_REFINEMENT_FAILED",
                        related_entity_type="candidate", related_entity_id=cand["id"],
                        description=f"Pass 2 refinement failed: {type(exc).__name__}: {exc}"[:500],
                    )
                except Exception:
                    pass
            _write_refine_status(
                data_root, job_id, i + 1, total,
                f"refined {i + 1}/{total}", health=was._render_run_health(tally))
    finally:
        copernicus = sh_backoff.disarm()
        live_dem = dem_source_mobile.disarm_live_dem_quota_breaker()

    if stopped_reason:
        final_detail = f"stopped: live DEM unavailable, {len(not_started)} not started"
    elif failures:
        final_detail = f"done, {len(failures)} failed"
    else:
        final_detail = "done"
    done_count = total - len(not_started)
    _write_refine_status(
        data_root, job_id, done_count, total, final_detail,
        phase="complete", health=was._render_run_health(tally))

    refined = [r for r in results if r.get("status") == "REFINED"]
    dem_sources: Dict[str, int] = {}
    for r in refined:
        key = r.get("dem_source") or DEM_SOURCE_UNKNOWN
        dem_sources[key] = dem_sources.get(key, 0) + 1
    return {
        "job_id": job_id,
        "attempted": done_count,
        "refined": len(refined),
        "reproduced": sum(1 for r in refined if r.get("reproduced")),
        "not_reproduced": sum(1 for r in refined if not r.get("reproduced")),
        "with_satellite_evidence": sum(1 for r in refined if r.get("satellite_sources_recorded")),
        "confidence_recorded": sum(1 for r in refined if r.get("confidence_recorded")),
        "failed": len(failures),
        "failures": failures,
        "require_live_dem": bool(require_live_dem),
        "stopped_no_live_dem": stopped_reason,
        "not_started": not_started,
        "dem_sources": dem_sources,
        "seconds": round(time.time() - started, 1),
        "results": results,
        "copernicus_throttle": copernicus,
        "opentopography_live_dem": live_dem,
    }


def run_refinement_pass(
    data_root: str,
    job_id: str,
    n: int = 5,
    api_key: str = "",
    demtype: str = "SRTMGL1",
    ndvi_client_id: str = "",
    ndvi_client_secret: str = "",
    min_separation_m: float = DEFAULT_MIN_SEPARATION_M,
    skip_flagged: bool = True,
    require_live_dem: bool = False,
) -> Dict[str, Any]:
    """Runs Pass 2 over the top `n` unrefined Pass 1 candidates of a job
    (leaving out land-cover-flagged ones unless skip_flagged is False).
    Behaviour is unchanged from the original top-N pass unless
    require_live_dem is set (it is not, from the UI). See
    _run_refinement_loop() for throttle, failure and progress handling.
    """
    selection = select_refinement_candidates(
        data_root, job_id, n, min_separation_m, skip_flagged=bool(skip_flagged))
    out = _run_refinement_loop(
        data_root, job_id, selection["selected"], api_key, demtype,
        ndvi_client_id, ndvi_client_secret,
        allow_repeat=False, require_live_dem=bool(require_live_dem))
    out.update({
        "mode": "top_n",
        "requested": int(n),
        "eligible_before_run": selection["eligible"],
        "already_refined_before_run": selection["already_refined"],
        "skipped_near_duplicates": selection["skipped_near_duplicates"],
        "skip_flagged": selection["skip_flagged"],
        "skipped_flagged": selection["skipped_flagged"],
        "skipped_flagged_by_reason": selection["skipped_flagged_by_reason"],
        "land_cover_unchecked": selection["land_cover_unchecked"],
    })
    return out


def run_selected_refinement(
    data_root: str,
    job_id: str,
    candidate_refs: Any,
    api_key: str = "",
    demtype: str = "SRTMGL1",
    ndvi_client_id: str = "",
    ndvi_client_secret: str = "",
    require_live_dem: bool = True,
) -> Dict[str, Any]:
    """Refines exactly the named candidates of this job, in the order given,
    including ones refined before (see the 2026-09-23 note in the module
    docstring). No land-cover filter and no near-duplicate skipping: the
    user chose these candidates on purpose. Unresolvable references are
    returned in "reference_problems" and nothing is run for them.

    With require_live_dem and no API key, raises RefinementError before
    anything runs (every candidate would be discarded)."""
    res = resolve_candidate_refs(data_root, job_id, candidate_refs)
    if require_live_dem and not api_key and res["resolved"]:
        raise RefinementError(
            "Live DEM is required for this run, but no OpenTopography API key "
            "is saved on this device.")
    out = _run_refinement_loop(
        data_root, job_id, res["resolved"], api_key, demtype,
        ndvi_client_id, ndvi_client_secret,
        allow_repeat=True, require_live_dem=bool(require_live_dem))
    out.update({
        "mode": "selected",
        "requested": len(res["resolved"]) + len(res["problems"]),
        "reference_problems": res["problems"],
    })
    return out


def run_selected_refinement_json(
    data_root: str,
    job_id: str,
    candidate_refs: Any,
    api_key: str = "",
    demtype: str = "SRTMGL1",
    ndvi_client_id: str = "",
    ndvi_client_secret: str = "",
    require_live_dem: bool = True,
) -> str:
    """Chaquopy-facing wrapper for run_selected_refinement(). candidate_refs
    may be one string (ids separated by spaces, commas, semicolons or new
    lines) -- that is what the Kotlin service passes."""
    return json.dumps(run_selected_refinement(
        data_root, job_id, candidate_refs, api_key, demtype,
        ndvi_client_id, ndvi_client_secret, bool(require_live_dem)), default=str)


def run_refinement_pass_json(
    data_root: str,
    job_id: str,
    n: int = 5,
    api_key: str = "",
    demtype: str = "SRTMGL1",
    ndvi_client_id: str = "",
    ndvi_client_secret: str = "",
    min_separation_m: float = DEFAULT_MIN_SEPARATION_M,
    skip_flagged: bool = True,
) -> str:
    """Chaquopy-facing wrapper (same argument order convention as
    wide_area_search_mobile.run_wide_area_search_job). Raises
    RefinementError for a genuine caller error (unknown job); the Kotlin
    caller is expected to catch it, exactly like the wide-area service."""
    return json.dumps(run_refinement_pass(
        data_root, job_id, int(n), api_key, demtype,
        ndvi_client_id, ndvi_client_secret, float(min_separation_m),
        bool(skip_flagged)), default=str)
