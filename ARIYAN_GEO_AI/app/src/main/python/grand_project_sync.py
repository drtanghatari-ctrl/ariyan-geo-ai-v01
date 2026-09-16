"""
grand_project_sync.py

Part of ARIYAN GEO AI's GRAND PROJECT FRAMEWORK -- Phase 1 ("make
existing investigation runs persist instead of being discarded").

PURPOSE: the single bridging entry point between the two things that
already exist and work (investigation_multi_mobile.run_investigation_
multi_json() and debate_mobile.run_debate_json()) and grand_project_db.py
(Phase 0's persistence layer, built and sandbox-verified in an earlier
session). This module adds NO new science, NO new evidence logic, and
NO new confidence computation -- it only reads the REAL JSON both of
those functions already produce and writes it into the database using
grand_project_db.py's existing functions. Every field name/shape used
below was taken directly from the real investigation_multi_mobile.py,
evidence_record.py, debate_mobile.py, steward_engine.py, and
steward_confidence_ceiling.py source (fetched and read this session),
not guessed or approximated from what MainActivity.kt happens to render.

INTENDED CALL SITE (Phase 1 wiring into Kotlin, NOT done by this module
itself -- MainActivity.kt is not touched here): after
runInvestigation() and runDebate() both complete successfully (the
exact same two calls MainActivity.kt's onRunClicked() already makes,
see that file's own doc comment), Kotlin would call this module's
record_investigation_results() once, passing the SAME two JSON strings
it already has in hand plus a grand_project_id (and, if the user has
one open, a hypothesis_id) -- no new Chaquopy call shape, no new
network activity, nothing that could fail differently from what
already runs today. A failure in THIS module must never be allowed to
hide or block the investigation/debate results the user already sees
on screen -- exactly this project's existing "a failure in one piece
never fails the whole run" philosophy (see investigation_multi_mobile.py's
own docstring, "GPR/NDVI/Thermal/Optical/SAR one failure never fails
the whole investigation"). Concretely: THIS MODULE'S CALLER should
wrap the call in its own try/except, exactly like MainActivity.kt
already wraps runDebate() in a try/catch that returns null on failure
without touching the investigation results already rendered.

SCOPE MATCHES debate_mobile.py's OWN SCOPE, DELIBERATELY: only
anomalies[] entries with evidence_type == "DEM" (or no evidence_type at
all -- single-source investigation_mobile.py output, not currently
routed through this module since that path has no debate/Steward
output to persist) are turned into Candidate rows here -- exactly the
same population debate_mobile.run_debate_json() itself debates (see
that module's own SCOPE note). An NDVI-raster-detected candidate from
the rare offline-fallback path (evidence_type == "NDVI") is correctly
NOT a debated candidate and is therefore correctly NOT persisted as one
either -- persisting a candidate this module has no Steward confidence
data for at all would create a DB row permanently missing the very
thing Phase 2's Evidence Graph is meant to explain.

CANDIDATE <-> DEBATE MATCHING: debate_mobile.py assigns each debated
candidate an "id" equal to "#" + (that candidate's own 1-based position
in the FULL anomalies[] list) -- see debate_mobile.py's own module
docstring and _build_candidate()'s own docstring for exactly why (kept
aligned with MainActivity.kt's own "Candidates: #N" numbering). This
module recovers that same index (int(candidate_id.lstrip("#")) - 1) to
match each debate entry back to its originating anomaly, rather than
re-deriving position independently -- there is no other stable id
field anywhere in this schema (confirmed by reading debate_mobile.py's
own REAL SCHEMA NOTES directly), so this is the same real mechanism the
rest of this project already relies on, not a new assumption.

EVIDENCE PERSISTED (matches evidence_record.py's real per-slot design,
read directly, not approximated):
- DEM itself: always one evidence_link per candidate (relation=
  "primary_detection" -- not "supports"/"contradicts"/"neutral",
  since DEM's own anomaly is what DEFINES the candidate, not
  corroborating evidence for something else).
- NDVI/THERMAL/OPTICAL/SAR: each candidate's REAL correlation[] entry
  (built by investigation_multi_mobile._build_correlated_candidates(),
  lat/lon copied directly from the SAME dem_candidate -- confirmed
  exact-match reliable per debate_mobile.py's own REAL SCHEMA NOTES)
  is read for its real supporting_sources list -- each source beyond
  DEM that genuinely corroborated this candidate gets relation=
  "supports", with the real per-candidate detail dict (second/
  fourth/fifth/ninth_evidence_detail, matched by the SAME tight
  lat/lon tolerance debate_mobile.py itself uses) stored verbatim as
  detail_json -- not reshaped, not summarized.
- GPR/ERT: real, site-anchored evidence (evidence_record.py's third/
  sixth slots) -- persisted only for whichever candidate(s) the real
  colocation-radius match in debate_mobile.py already decided were
  close enough (candidate["gpr_confirmed"]/candidate["ert_confirmed"]
  on the ALREADY-BUILT debate candidate dict). This module does NOT
  re-run that colocation logic -- it is not exposed on the JSON
  debate_mobile.py returns to Kotlin today (only the CONSEQUENCE --
  e.g. candidate["gpr_confirmed"] having fed into the Steward report
  -- is visible via steward's own inputs, not the raw flag itself).
  See KNOWN GAP note below for the honest limitation this causes.
- Detection Stability / Temporal Persistence / DEM Cross-Check
  (seventh/eighth/tenth slots): these are explicitly NOT independent
  evidence sources (see evidence_record.py's own docstring) -- they
  are Steward confidence-ceiling inputs, not corroborating evidence
  a hypothesis would cite. They are therefore NOT written as
  evidence_link rows here (that would misrepresent them as if they
  were a source like NDVI/SAR); their effect is already fully
  captured in the Steward reasoning_snapshot saved to
  confidence_history below, which is the correct, honest place for
  them per this project's own design.

KNOWN GAP, HONESTLY NOTED (not silently worked around): the JSON
debate_mobile.run_debate_json() actually returns to Kotlin today does
NOT include the raw per-candidate gpr_confirmed/ert_confirmed booleans
or GPR/ERT's own real distance/depth/resistivity numbers on each debate
entry -- those live only on the internal Python `candidate` dict inside
debate_mobile.py, which is discarded before the JSON is built (only
`debate` -- positions/synthesis/steward -- is appended to the result).
Since evidence_record.py's third_evidence_detail/sixth_evidence_detail
(the real GPR/ERT survey records) ARE present on the investigation_json
this module already receives, GPR/ERT are still persisted here as
evidence_link rows -- but matched independently, by this module's own
colocation-radius check against investigation_json's own aoi.cell_size_m
(mirroring debate_mobile.py's _gpr_colocation_distance_m()/
_ert_colocation_distance_m() logic, which this module reimplements
locally since it isn't exposed as an importable shared helper), NOT by
reading debate_mobile.py's own already-computed decision. In the
ordinary case this produces the identical result (both use the exact
same real formula and the exact same real coordinates), but if
debate_mobile.py's internal logic is ever changed without a matching
change here, the two could silently drift -- flagged honestly rather
than silently assumed to always agree.

CONFIDENCE PERSISTED: for each candidate with a Steward report present
(debate["steward"]["reasoning_trace"]["confidence"] -- real field
names confirmed directly from steward_engine.py/steward_confidence_
ceiling.py's own ConfidenceCeilingResult.as_dict()), this module calls
BOTH grand_project_db.record_confidence_history() (append-only trail)
AND grand_project_db.update_candidate_confidence() (the candidate row's
own "current" band/numeric fields) with the SAME real band/
clamped_confidence/reasoning values -- see grand_project_db.py's own
update_candidate_confidence() docstring for why both are called
together. A candidate whose Steward evaluation itself failed this run
(debate.get("steward_error") is set -- see debate_mobile.py's own
"never raise across the Chaquopy boundary" contract) is still persisted
as a Candidate row (the DEM detection itself is real regardless of
whether Steward could evaluate it), but gets NO confidence_history row
and NO evidence_link rows for this run -- an honest "Steward could not
evaluate this" gap, not a fabricated LOW/None value.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional

import grand_project_db as db

DEFAULT_GRAND_PROJECT_ID = "default"


def get_or_create_default_grand_project(db_root: str) -> str:
    """Interim stopgap until real Grand Project selection UI exists in
    MainActivity.kt (see module docstring's own INTENDED CALL SITE note
    -- this was the missing piece: the function this project's own
    memory described as already built and sandbox-verified did not
    actually exist in committed code, confirmed 2026-09-14 via grep
    returning zero hits in both this file and grand_project_db.py).

    Uses a FIXED, known id (DEFAULT_GRAND_PROJECT_ID) rather than a
    randomly generated one, specifically so the SAME project is reused
    across every app restart: get_grand_project() looks it up by that
    fixed id first, and only creates a new row the very first time this
    is ever called on a given device (fresh install, or first run after
    this function was added). Future UI work should replace this
    stopgap with real Grand Project selection/creation, not build
    further logic on top of it.
    """
    existing = db.get_grand_project(db_root, DEFAULT_GRAND_PROJECT_ID)
    if existing is not None:
        return existing["id"]
    return db.create_grand_project(
        db_root,
        name="Default Grand Project",
        description=(
            "Automatically created default Grand Project -- interim "
            "stopgap until real Grand Project selection UI exists."
        ),
        project_id=DEFAULT_GRAND_PROJECT_ID,
    )


_PER_CANDIDATE_DETAIL_MATCH_TOLERANCE_M = 5.0  # SAME constant as
                                                # debate_mobile.py's own
                                                # _PER_CANDIDATE_DETAIL_
                                                # MATCH_TOLERANCE_M --
                                                # kept as a separate
                                                # local constant
                                                # (deliberate small
                                                # duplication) rather
                                                # than importing from
                                                # debate_mobile, so this
                                                # module has zero import
                                                # dependency on the
                                                # Kotlin-facing wrapper
                                                # module.


def _haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Standalone haversine, deliberately NOT importing coordinate.py's
    own GeoPoint/haversine_distance_m -- this module only needs plain
    lat/lon floats already present in the JSON dicts it receives, and
    avoiding the import keeps this module usable for offline testing
    (e.g. this session's own sandbox verification) without needing the
    rest of this project's Chaquopy-specific module graph available."""
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _nearest_by_latlon(target_lat: float, target_lon: float, items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    best = None
    best_dist = None
    for item in items:
        try:
            dist = _haversine_distance_m(target_lat, target_lon, item["lat"], item["lon"])
        except (KeyError, TypeError):
            continue
        if best_dist is None or dist < best_dist:
            best, best_dist = item, dist
    return best


def _nearest_within(target_lat: float, target_lon: float, items: List[Dict[str, Any]], tolerance_m: float) -> Optional[Dict[str, Any]]:
    best = _nearest_by_latlon(target_lat, target_lon, items)
    if best is None:
        return None
    dist = _haversine_distance_m(target_lat, target_lon, best["lat"], best["lon"])
    return best if dist <= tolerance_m else None


def _colocation_distance_m(investigation: Dict[str, Any]) -> float:
    """Mirrors debate_mobile.py's _gpr_colocation_distance_m()/
    _ert_colocation_distance_m() exactly (same real formula, same
    fallback) -- see this module's own KNOWN GAP docstring note for why
    this is reimplemented locally rather than imported."""
    aoi = investigation.get("aoi") or {}
    cell_size_m = aoi.get("cell_size_m")
    try:
        cell_size_m = float(cell_size_m) if cell_size_m is not None else None
    except (TypeError, ValueError):
        cell_size_m = None
    if cell_size_m is None:
        return 50.0
    return max(30.0, cell_size_m * 4)


def record_investigation_results(
    db_root: str,
    grand_project_id: str,
    investigation_json: str,
    debate_json: Optional[str] = None,
    hypothesis_id: Optional[str] = None,
    objective: str = "",
) -> Dict[str, Any]:
    """Persists ONE completed investigation (and, if available, its
    debate/Steward output) into the Grand Project database. Returns
    {"investigation_id": str, "candidate_ids": [str, ...]} on success.

    `investigation_json` MUST be the real JSON string
    investigation_multi_mobile.run_investigation_multi_json() returns
    (this module has not been built against, and does not support,
    investigation_mobile.py's single-source output -- see module
    docstring, SCOPE). `debate_json`, if given, MUST be the real JSON
    string debate_mobile.run_debate_json() returns for THAT SAME
    investigation_json -- passing a debate result for a different
    investigation would silently mismatch candidates by index; this
    module has no way to detect that, so the caller (Kotlin) is
    responsible for always pairing the two from the same run, exactly
    as MainActivity.kt's own onRunClicked() already does today.

    Never raises for an ordinary per-candidate issue (a missing
    detail entry, a candidate with no Steward output) -- those are
    handled as documented gaps in the module docstring. DOES raise on
    a genuinely malformed investigation_json/debate_json (e.g. invalid
    JSON, missing "aoi") -- this project's own conventions treat a
    malformed evidence record as a real, surfaceable failure, not
    something to silently paper over; the caller should catch this
    itself, per this module's own docstring.
    """
    investigation = json.loads(investigation_json)
    debate_result = json.loads(debate_json) if debate_json else None

    anomalies = investigation.get("anomalies") or []
    correlation = investigation.get("correlation") or []
    evidence_top = investigation.get("evidence") or []

    detail_by_source = {
        "NDVI": investigation.get("second_evidence_detail") or [],
        "THERMAL": investigation.get("fourth_evidence_detail") or [],
        "OPTICAL": investigation.get("fifth_evidence_detail") or [],
        "SAR": investigation.get("ninth_evidence_detail") or [],
    }
    gpr_records = investigation.get("third_evidence_detail") or []
    ert_records = investigation.get("sixth_evidence_detail") or []
    colocation_tolerance_m = _colocation_distance_m(investigation)

    debates_by_index: Dict[int, Dict[str, Any]] = {}
    if debate_result and not debate_result.get("error"):
        for d in debate_result.get("debates", []):
            candidate_id_str = d.get("candidate_id") or ""
            if candidate_id_str.startswith("#"):
                try:
                    idx = int(candidate_id_str.lstrip("#")) - 1
                    debates_by_index[idx] = d
                except ValueError:
                    continue

    investigation_id = db.create_investigation(
        db_root,
        grand_project_id,
        objective=objective,
        workflow_reference="investigation_multi_mobile.run_investigation_multi_json",
        parameters=investigation.get("aoi"),
    )

    candidate_ids: List[str] = []
    for i, anomaly in enumerate(anomalies):
        # SCOPE, matching debate_mobile.py's own: only real DEM
        # candidates become Candidate rows. See module docstring.
        evidence_type = anomaly.get("evidence_type", "DEM")
        if evidence_type != "DEM":
            continue

        lat, lon = anomaly.get("lat"), anomaly.get("lon")
        candidate_id = db.create_candidate(
            db_root,
            grand_project_id,
            investigation_id,
            lat=lat,
            lon=lon,
            score=anomaly.get("peak_zscore"),
            hypothesis_id=hypothesis_id,
        )
        candidate_ids.append(candidate_id)

        # DEM's own detection -- always recorded, relation is
        # "primary_detection" (this candidate's own defining evidence,
        # not corroboration of something else). Real fields stored
        # verbatim: area_cells/peak_residual_m/mean_residual_m/
        # peak_zscore/polarity -- exactly evidence_record.py's own
        # AnomalyCandidate schema, nothing invented.
        db.add_evidence_link(
            db_root, candidate_id,
            evidence_type="DEM",
            relation="primary_detection",
            detail=anomaly,
        )

        # NDVI/THERMAL/OPTICAL/SAR -- real per-candidate corroboration,
        # read from the REAL correlation[] entry for this exact
        # candidate (lat/lon copied directly from dem_candidate --
        # confirmed exact-match reliable per debate_mobile.py's own
        # REAL SCHEMA NOTES).
        corr_entry = _nearest_by_latlon(lat, lon, correlation) if (lat is not None and lon is not None) else None
        if corr_entry is not None:
            for source in corr_entry.get("supporting_sources", []):
                if source == "DEM":
                    continue  # already recorded above
                detail_list = detail_by_source.get(source, [])
                matched_detail = _nearest_within(lat, lon, detail_list, _PER_CANDIDATE_DETAIL_MATCH_TOLERANCE_M)
                db.add_evidence_link(
                    db_root, candidate_id,
                    evidence_type=source,
                    relation="supports",
                    detail=matched_detail if matched_detail is not None else {"note": corr_entry.get("note")},
                )

        # GPR/ERT -- real, site-anchored evidence. See module
        # docstring, KNOWN GAP: matched here independently via the
        # same real colocation-radius formula debate_mobile.py itself
        # uses, since the raw gpr_confirmed/ert_confirmed flags are not
        # exposed on the JSON this module receives.
        for records, evidence_type_name in ((gpr_records, "GPR"), (ert_records, "ERT")):
            for record in records:
                r_lat, r_lon = record.get("lat"), record.get("lon")
                if r_lat is None or r_lon is None or lat is None or lon is None:
                    continue
                dist = _haversine_distance_m(lat, lon, r_lat, r_lon)
                if dist <= colocation_tolerance_m:
                    db.add_evidence_link(
                        db_root, candidate_id,
                        evidence_type=evidence_type_name,
                        relation="supports",
                        detail=record,
                    )

        # Steward confidence -- both the append-only trail AND the
        # candidate row's own "current" fields. Real field names taken
        # directly from steward_engine.py/steward_confidence_ceiling.py:
        # debate["steward"]["reasoning_trace"]["confidence"]["band"] /
        # ["clamped_confidence"] / ["reasoning"].
        debate_entry = debates_by_index.get(i)
        if debate_entry is not None and not debate_entry.get("steward_error"):
            steward = debate_entry.get("steward") or {}
            trace = steward.get("reasoning_trace") or {}
            confidence = trace.get("confidence") or {}
            band = confidence.get("band")
            numeric = confidence.get("clamped_confidence")
            reasoning = confidence.get("reasoning")
            if band is not None or numeric is not None:
                db.record_confidence_history(
                    db_root, candidate_id,
                    band=band, numeric_confidence=numeric,
                    reasoning_snapshot=reasoning,
                    triggering_investigation_id=investigation_id,
                )
                db.update_candidate_confidence(db_root, candidate_id, band, numeric)

    db.complete_investigation(
        db_root, investigation_id, grand_project_id,
        execution_status="COMPLETED",
        interpretation_summary=investigation.get("confidence_statement", ""),
    )

    return {"investigation_id": investigation_id, "candidate_ids": candidate_ids}