"""
debate_mobile.py -- Chaquopy entry point wrapping debate_engine.py for
MainActivity.kt.

Kotlin calls debate_mobile.run_debate_json(investigation_json: str) and
expects a JSON string back (see MainActivity.kt's runDebate() /
appendDebateSection()). debate_engine.py's public API works on Python
dicts, not JSON strings, and expects candidate dicts using its own alias
vocabulary (z_score, elevation_delta_m, correlation_status, sources,
ndvi_synthetic -- see debate_engine.py's module docstring and _get()
helper). This module is the translation layer between the two: it does
NOT modify debate_engine.py's core rule logic for existing fields (per
that file's own docstring recommendation -- "the rule logic itself does
not need to change"), it only maps this project's REAL InvestigationRecord
schema (confirmed by reading evidence_record.py, anomaly_detection_mobile.py,
correlation.py, and investigation_multi_mobile.py directly, not guessed)
onto the field names debate_engine.py already knows how to read.

REAL SCHEMA NOTES (why this file looks the way it does):
- anomalies[] entries are AnomalyCandidate dicts: row, col, lat, lon,
  area_cells, peak_residual_m, mean_residual_m, peak_zscore, polarity
  (+ "evidence_type": "DEM"/"NDVI" in multi-source runs; ABSENT entirely
  in single-source investigation_mobile.py output). There is no natural
  id/candidate_id field anywhere in this schema, so this module assigns
  one itself: each debated candidate gets "id" set to its own 1-based
  position in THIS RUN'S OWN anomalies[] list (e.g. the first anomaly
  entry becomes "#1", matching the numbering MainActivity.kt's
  renderResult() already shows in its "Candidates: #N ..." listing).
- correlation[] entries (when present) are CorrelatedCandidate dicts:
  lat, lon, status ("CORROBORATED"/"SINGLE_SOURCE"), supporting_sources,
  distance_between_peaks_m, note. In real-NDVI mode
  (investigation_multi_mobile.py's per-candidate path) each entry's
  lat/lon is copied directly from its one DEM candidate, so matching by
  nearest lat/lon is always exact. In synthetic-NDVI mode, correlate_
  anomalies() sorts correlation[] independently of anomalies[] order and
  uses a centroid lat/lon for CORROBORATED (2+ source) groups -- still
  exact for SINGLE_SOURCE entries (centroid of one point is that point),
  and a close match for CORROBORATED ones (centroid of co-located points
  within colocation_distance_m by construction). Nearest-match is
  therefore correct, not a guess, across both modes.
- TWO DISTINCT "sources" CONCEPTS, KEPT SEPARATE (fixed a prior session
  -- see SOURCES-SPLIT FIX note below for the full story): "which sources
  actually CORROBORATED this candidate" (precise, drives correlation-
  status reasoning text) and "which sources were CHECKED/attempted for
  this candidate regardless of outcome" (broader, drives the Vegetation/
  Agronomic perspective's "was NDVI evaluated at all" question). These
  used to be silently merged into one field; conflating them was the
  root cause of a real on-device bug, now fixed and unaffected by this
  session's Optical addition (Optical follows the SAME precise/checked
  split from the start).
- SCOPE: only anomalies[] entries with evidence_type == "DEM" (or no
  evidence_type at all -- single-source runs) are debated. In synthetic-
  NDVI mode, anomalies[] can also hold NDVI-raster-detected candidates
  (evidence_type == "NDVI") that were never individually corroborated
  against a specific DEM candidate; debating those through perspectives
  written around "elevation anomaly magnitude" would not be a faithful
  use of the tool, so they're skipped and reported as a count instead of
  silently dropped. Skipped candidates are NOT counted when assigning
  "id" to the debated ones -- id is always the anomaly's own position in
  the full anomalies[] list, so it stays aligned with the "Candidates:"
  section's own #N numbering regardless of how many others were skipped.

GPR (ground-penetrating radar) EXTENSION: a real GPR field pick
(evidence_record.py's third evidence slot, see
gpr_source_mobile.GPREvidence.as_evidence_record()) is anchored at the
investigation's own (lat, lon) -- it is a single site-anchored check,
not a per-candidate one like NDVI/Thermal/Optical core/halo. This module
therefore matches the GPR pick to whichever DEM candidate(s) are close
enough (within a distance tolerance derived from the AOI's cell size,
same reasoning as investigation_multi_mobile.py's own default
colocation_distance_m) to plausibly be about the same physical location,
and attaches gpr_confirmed/gpr_distance_m/gpr_depth_min_m/gpr_depth_max_m
to just those candidates. A candidate that's too far from the GPR pick
gets nothing added -- GPR wasn't informative for it, which is the honest
state, not a guess either way. If GPR evidence exists but no candidate
was close enough to use it, that is reported in the result's "gpr_note"
field rather than silently discarded.

REAL THERMAL EXTENSION (a prior session): unlike GPR's single
site-anchored pick, real Landsat thermal (evidence_record.py's fourth
evidence slot -- see thermal_source_mobile.py and
investigation_multi_mobile.py's _run_thermal_checks) is a per-DEM-
candidate check, run at EACH candidate's own exact (lat, lon) --
matching is therefore a TIGHT-tolerance exact match (a few meters, to
absorb only floating-point noise, not GPR's colocation-radius-style
"was this nearby" match), via _attach_thermal_detail() below. This uses
fourth_evidence_detail's own per-candidate error field directly, so it
correctly distinguishes "Thermal genuinely checked and succeeded for
this candidate" from "Thermal was attempted for this run but failed for
this specific candidate".

REAL OPTICAL EXTENSION (ADDED THIS SESSION): like Thermal, real
Sentinel-2 visible-brightness (evidence_record.py's fifth evidence slot
-- see optical_source_mobile.py and
investigation_multi_mobile.py's _run_optical_checks) is a per-DEM-
candidate check, run at EACH candidate's own exact (lat, lon).
_attach_optical_detail() below mirrors _attach_thermal_detail() exactly
-- same tight-tolerance exact-match approach against fifth_evidence_detail
by lat/lon, checking that specific entry's own error field, for the same
reasons documented on _attach_thermal_detail() itself.

SOURCES-SPLIT FIX (a prior session -- REAL on-device bug, unaffected by
this session's Optical addition): candidate["sources"] is the PRECISE
list of sources that actually corroborated this candidate (drives
debate_engine.py's Anthropogenic/Geomorphology reasoning text via
_sources_present()). candidate["checked_sources"] is the BROADER union
of every source genuinely checked for this candidate regardless of
outcome (drives debate_engine.py's Vegetation/Agronomic perspective via
_sources_checked_present(), and this module's own
_build_steward_report() below for has_dem/has_ndvi). Optical follows
this exact same split from the start: it is exact-match-precise (via
_attach_optical_detail(), just like Thermal) rather than routed through
the whole-run union checked_sources currently used for NDVI (see the
KNOWN, FLAGGED, NOT-YET-FIXED IMPRECISION note below, unchanged and
unaffected by Optical's addition).

KNOWN, FLAGGED, NOT-YET-FIXED IMPRECISION (identified a prior session,
NOT changed without explicit confirmation -- this is a real,
already-on-device-confirmed-working code path, and remains exactly as
it was before this session): candidate["checked_sources"] (the
whole-run union used for has_ndvi and Vegetation/Agronomic's "was NDVI
checked" question) cannot distinguish "NDVI genuinely succeeded for
THIS candidate" from "NDVI evidence exists somewhere in this run but
genuinely failed for EVERY candidate". The SAME exact-match technique
now used for both Thermal (_attach_thermal_detail()) and Optical
(_attach_optical_detail()) could fix this too, if wanted -- deliberately
not applied to NDVI here without asking first, since it would change
already-proven on-device behavior.

SCIENTIFIC STEWARD STAGE 1 EXTENSION: after debate_engine.run_debate()
returns its positions + synthesis for a candidate, this module also
calls steward_engine.evaluate_candidate() (see steward_engine.py) and
attaches the result under a new "steward" key on that same debate dict.
This is purely additive -- MainActivity.kt's existing
appendDebateSection() rendering is completely unaffected by the extra
key until it's explicitly updated to read it.

HONEST MAPPING NOTES (read before changing _build_steward_report below):
this module has REAL data for some Steward inputs and does NOT for
others -- the mapping below is deliberately conservative rather than
guessing, per this project's zero-fabrication rule:
  - has_dem / has_ndvi: real, taken from candidate["checked_sources"]
    (the broader union -- see SOURCES-SPLIT FIX above).
  - has_gpr / has_field_validation: real, taken directly from
    candidate["gpr_confirmed"] (see _attach_gpr() above -- set only
    when a real GPR pick colocated with this specific candidate).
  - has_thermal: real, taken directly from candidate["thermal_checked"]
    (see _attach_thermal_detail() below -- set only when a real per-
    candidate Thermal check genuinely succeeded, i.e. its own error
    field was None, for THIS EXACT candidate).
  - has_optical (REAL AS OF THIS SESSION, previously always False):
    taken directly from candidate["optical_checked"] (see
    _attach_optical_detail() below -- set only when a real per-
    candidate Optical check genuinely succeeded, i.e. its own error
    field was None, for THIS EXACT candidate -- not merely "Optical was
    attempted somewhere in this run"). If a candidate's Optical check
    genuinely failed (network/auth/no-data), has_optical is honestly
    False for that candidate, not True. This REMOVES Optical from every
    future Steward DATA_GAP warning for candidates where it genuinely
    succeeded -- real progress toward filling the DATA_GAP list this
    whole evidence-source-expansion effort was undertaken to close.
  - has_lidar / has_ert: always False. Neither has been built (LiDAR has
    no real data source available for this project's operating region;
    ERT is designed but not yet built -- see the project's own history
    notes). Deliberate, not an oversight.
  - raw_debate_confidence: real, taken directly from
    synthesis["leading_confidence"] (0.0 when NO_DATA / absent, which
    correctly yields the Steward's NO_DATA band).
  - has_contradiction: an APPROXIMATION, not a true independent-evidence
    contradiction detector -- mapped from agreement_level == "CONTESTED"
    (two perspectives closely competing). This is honestly a proxy, not
    the real Team-A/Team-B/Judge contradiction detection the Scientific
    Steward spec describes for Stage 3.
  - environmental_confounders_controlled: always False for Stage 1.
  - provenance_verified: always False for Stage 1 (Stage 2, SHA-256
    evidence validation, not yet built).
  - quality_hints / requested_precision_m / effective_resolution_m: left
    unset (UNKNOWN / None). Not currently tracked as explicit
    per-candidate fields anywhere in this schema.
  - hypothesis / alternative_hypotheses / debate_summary: real, built
    directly from the SAME positions[]/synthesis{} debate_engine.py
    already produced.

A Steward evaluation failure for one candidate is caught and reported as
a "steward_error" string on that candidate's debate dict instead of
raising -- consistent with this file's existing "never raise across the
Chaquopy boundary" contract for run_debate_json as a whole.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from coordinate import GeoPoint, haversine_distance_m
from debate_engine import run_debate
from steward_engine import evaluate_candidate as steward_evaluate_candidate

# Tolerance for matching a DEM candidate to its OWN per-candidate Thermal
# or Optical detail entry. Deliberately tight (a few meters) -- unlike
# GPR's colocation-radius-style tolerance for "was this nearby", both
# Thermal and Optical detail entries are built directly from the SAME
# dem_candidate.lat/lon (see investigation_multi_mobile.py's
# _run_thermal_checks/_run_optical_checks), so any real distance here
# should only ever reflect floating-point noise, not a genuine
# "different but nearby location" case. Shared by both
# _attach_thermal_detail() and _attach_optical_detail() below.
_PER_CANDIDATE_DETAIL_MATCH_TOLERANCE_M = 5.0


def _nearest_correlation_entry(anomaly: dict, correlation: list[dict]) -> Optional[dict]:
    if not correlation:
        return None
    try:
        a_point = GeoPoint(anomaly["lat"], anomaly["lon"])
    except (KeyError, TypeError):
        return None
    best = None
    best_dist = None
    for entry in correlation:
        try:
            e_point = GeoPoint(entry["lat"], entry["lon"])
            dist = haversine_distance_m(a_point, e_point)
        except (KeyError, TypeError):
            continue
        if best_dist is None or dist < best_dist:
            best = entry
            best_dist = dist
    return best


def _ndvi_synthetic_flag(evidence: list[dict]) -> Optional[bool]:
    for item in evidence or []:
        if item.get("evidence_type") == "NDVI":
            val = item.get("synthetic")
            return bool(val) if val is not None else None
    return None


def _gpr_evidence_item(evidence: list[dict]) -> Optional[dict]:
    for item in evidence or []:
        if item.get("evidence_type") == "GPR":
            return item
    return None


def _gpr_colocation_distance_m(investigation: dict) -> float:
    aoi = investigation.get("aoi") or {}
    cell_size_m = aoi.get("cell_size_m")
    try:
        cell_size_m = float(cell_size_m) if cell_size_m is not None else None
    except (TypeError, ValueError):
        cell_size_m = None
    if cell_size_m is None:
        return 50.0
    return max(30.0, cell_size_m * 4)


def _attach_gpr(candidate: dict, anomaly: dict, gpr_item: Optional[dict], max_distance_m: float) -> bool:
    if gpr_item is None:
        return False
    try:
        anomaly_point = GeoPoint(anomaly["lat"], anomaly["lon"])
        gpr_point = GeoPoint(gpr_item["lat"], gpr_item["lon"])
        distance = haversine_distance_m(anomaly_point, gpr_point)
    except (KeyError, TypeError):
        return False
    if distance > max_distance_m:
        return False

    depth_estimates = gpr_item.get("depth_estimates_m") or []
    depth_mins = [d["depth_min_m"] for d in depth_estimates if d.get("depth_min_m") is not None]
    depth_maxs = [d["depth_max_m"] for d in depth_estimates if d.get("depth_max_m") is not None]

    candidate["gpr_confirmed"] = True
    candidate["gpr_distance_m"] = round(distance, 1)
    if depth_mins:
        candidate["gpr_depth_min_m"] = round(min(depth_mins), 3)
    if depth_maxs:
        candidate["gpr_depth_max_m"] = round(max(depth_maxs), 3)
    return True


def _attach_per_candidate_detail(
    candidate: dict,
    anomaly: dict,
    detail_list: list[dict],
    flag_key: str,
    tolerance_m: float = _PER_CANDIDATE_DETAIL_MATCH_TOLERANCE_M,
) -> None:
    """Shared exact-match logic for both _attach_thermal_detail() and
    _attach_optical_detail() below -- sets candidate[flag_key] = True
    only when a real per-candidate result exists for THIS exact
    candidate (tight tolerance) AND that result's own error field is
    None (i.e. the check genuinely succeeded for this candidate,
    regardless of whether it detected an anomaly). False for: no detail
    present at all (this source never attempted this run), a detail
    entry existing only for a different/distant candidate, or a
    genuinely matched entry whose error field is set (this candidate's
    own check failed).

    Factored out this session so Thermal's and Optical's identical
    matching logic isn't duplicated verbatim -- both public functions
    below are now thin wrappers naming their own detail list and flag
    key, preserving each one's own exact previously-proven behavior
    (Thermal's) or newly-built behavior (Optical's) unchanged.
    """
    best = None
    best_dist = None
    for entry in detail_list:
        try:
            e_point = GeoPoint(entry["lat"], entry["lon"])
            a_point = GeoPoint(anomaly["lat"], anomaly["lon"])
            dist = haversine_distance_m(a_point, e_point)
        except (KeyError, TypeError):
            continue
        if best_dist is None or dist < best_dist:
            best = entry
            best_dist = dist

    if best is None or best_dist is None or best_dist > tolerance_m:
        candidate[flag_key] = False
        return
    candidate[flag_key] = best.get("error") is None


def _attach_thermal_detail(
    candidate: dict,
    anomaly: dict,
    fourth_evidence_detail: list[dict],
    tolerance_m: float = _PER_CANDIDATE_DETAIL_MATCH_TOLERANCE_M,
) -> None:
    """Sets candidate["thermal_checked"] -- see
    _attach_per_candidate_detail()'s own docstring for the exact
    matching semantics (unchanged from before this session's
    refactor -- this is the same logic, just factored into the shared
    helper above rather than duplicated)."""
    _attach_per_candidate_detail(candidate, anomaly, fourth_evidence_detail, "thermal_checked", tolerance_m)


def _attach_optical_detail(
    candidate: dict,
    anomaly: dict,
    fifth_evidence_detail: list[dict],
    tolerance_m: float = _PER_CANDIDATE_DETAIL_MATCH_TOLERANCE_M,
) -> None:
    """Sets candidate["optical_checked"] -- ADDED THIS SESSION, mirrors
    _attach_thermal_detail() exactly via the shared
    _attach_per_candidate_detail() helper above. Already precise from
    the start (built the more-precise way immediately, like Thermal,
    rather than routed through the whole-run checked_sources union like
    NDVI currently is -- see this module's own KNOWN, FLAGGED
    IMPRECISION note)."""
    _attach_per_candidate_detail(candidate, anomaly, fifth_evidence_detail, "optical_checked", tolerance_m)


def _build_candidate(
    anomaly: dict,
    correlation_entry: Optional[dict],
    checked_sources: Optional[list[str]] = None,
    original_index: Optional[int] = None,
) -> dict:
    """Builds the candidate dict debate_engine.py consumes.

    candidate["sources"] is set to ONLY this candidate's own
    supporting_sources -- precise, exactly what corroborated THIS
    candidate (now correctly includes OPTICAL whenever
    investigation_multi_mobile.py's _build_correlated_candidates()
    determined it genuinely corroborated this candidate, with no
    changes needed here -- this function already treats
    correlation_entry["supporting_sources"] generically, however many
    real source types it lists).

    candidate["checked_sources"] carries the whole-run union
    (supporting_sources + checked_sources param, deduplicated) -- read
    by debate_engine.py's _sources_checked_present() (Vegetation/
    Agronomic perspective) and this module's own _build_steward_report()
    below for has_dem/has_ndvi. Optical does NOT feed into this
    broader/imprecise union -- it uses the precise exact-match
    _attach_optical_detail() above instead, exactly like Thermal.
    """
    candidate: dict[str, Any] = {
        "location": {"lat": anomaly.get("lat"), "lon": anomaly.get("lon")},
    }
    if original_index is not None:
        candidate["id"] = f"#{original_index + 1}"
    if anomaly.get("peak_zscore") is not None:
        candidate["z_score"] = anomaly["peak_zscore"]
    if anomaly.get("peak_residual_m") is not None:
        candidate["elevation_delta_m"] = anomaly["peak_residual_m"]

    supporting_sources = []
    if correlation_entry is not None:
        if correlation_entry.get("status"):
            candidate["correlation_status"] = correlation_entry["status"]
        if correlation_entry.get("supporting_sources"):
            supporting_sources = list(correlation_entry["supporting_sources"])

    if supporting_sources:
        candidate["sources"] = supporting_sources

    merged_sources = list(dict.fromkeys([*supporting_sources, *(checked_sources or [])]))
    if merged_sources:
        candidate["checked_sources"] = merged_sources

    return candidate


def _build_context(investigation: dict) -> dict:
    evidence = investigation.get("evidence") or []
    context: dict[str, Any] = {
        "sources": [e.get("evidence_type") for e in evidence if e.get("evidence_type")],
    }
    ndvi_synth = _ndvi_synthetic_flag(evidence)
    if ndvi_synth is not None:
        context["ndvi_synthetic"] = ndvi_synth
    return context


def _build_steward_report(debate: dict, candidate: dict) -> dict:
    """Scientific Steward Stage 1 wiring. See HONEST MAPPING NOTES (in
    this module's own docstring) for exactly which inputs are real vs.
    deliberately conservative placeholders.

    has_optical is real as of this session -- see this module's own
    docstring, HONEST MAPPING NOTES, for exactly what "real" means here
    (precise per-candidate success, via candidate["optical_checked"]).
    """
    checked_sources = candidate.get("checked_sources") or []
    has_dem = "DEM" in checked_sources
    has_ndvi = "NDVI" in checked_sources
    has_gpr = bool(candidate.get("gpr_confirmed"))
    has_thermal = bool(candidate.get("thermal_checked"))
    has_optical = bool(candidate.get("optical_checked"))

    synthesis = debate.get("synthesis") or {}
    raw_confidence = float(synthesis.get("leading_confidence") or 0.0)
    agreement_level = synthesis.get("agreement_level", "NO_DATA")
    has_contradiction = agreement_level == "CONTESTED"

    positions = debate.get("positions") or []
    leader_name = synthesis.get("leading_position")
    leader_position = next((p for p in positions if p.get("perspective") == leader_name), None)
    hypothesis = leader_position.get("stance", "") if leader_position else ""
    alternative_hypotheses = [
        p.get("stance", "")
        for p in positions
        if p.get("perspective") != leader_name and not p.get("insufficient_data")
    ]

    z_score = candidate.get("z_score")
    if z_score is not None:
        observation = f"A candidate elevation anomaly (|z|={float(z_score):.2f}) was detected via DEM analysis."
    else:
        observation = "A candidate anomaly was detected."

    steward_note = synthesis.get("steward_note", "")
    candidate_id = debate.get("candidate_id") or "?"

    report = steward_evaluate_candidate(
        candidate_id=str(candidate_id),
        observation=observation,
        has_gps=True,
        has_dem=has_dem,
        has_optical=has_optical,
        has_ndvi=has_ndvi,
        has_gpr=has_gpr,
        has_thermal=has_thermal,
        raw_debate_confidence=raw_confidence,
        has_field_validation=has_gpr,
        environmental_confounders_controlled=False,
        has_contradiction=has_contradiction,
        interpretation=steward_note,
        hypothesis=hypothesis,
        alternative_hypotheses=alternative_hypotheses,
        debate_summary=steward_note,
        provenance_verified=False,
    )
    return report.as_dict()


def run_debate_json(investigation_json: str) -> str:
    try:
        investigation = json.loads(investigation_json)
        anomalies = investigation.get("anomalies") or []
        correlation = investigation.get("correlation") or []
        evidence = investigation.get("evidence") or []
        fourth_evidence_detail = investigation.get("fourth_evidence_detail") or []
        fifth_evidence_detail = investigation.get("fifth_evidence_detail") or []
        context = _build_context(investigation)

        gpr_item = _gpr_evidence_item(evidence)
        gpr_max_distance_m = _gpr_colocation_distance_m(investigation)

        debates = []
        n_skipped_non_dem = 0
        any_gpr_confirmed = False
        for original_index, anomaly in enumerate(anomalies):
            evidence_type = anomaly.get("evidence_type", "DEM")
            if evidence_type != "DEM":
                n_skipped_non_dem += 1
                continue
            correlation_entry = _nearest_correlation_entry(anomaly, correlation)
            candidate = _build_candidate(anomaly, correlation_entry, context.get("sources"), original_index)
            if _attach_gpr(candidate, anomaly, gpr_item, gpr_max_distance_m):
                any_gpr_confirmed = True
            _attach_thermal_detail(candidate, anomaly, fourth_evidence_detail)
            _attach_optical_detail(candidate, anomaly, fifth_evidence_detail)
            debate = run_debate(candidate, context)

            try:
                debate["steward"] = _build_steward_report(debate, candidate)
            except Exception as steward_exc:
                debate["steward_error"] = str(steward_exc)

            debates.append(debate)

        result: dict[str, Any] = {"debates": debates}
        if n_skipped_non_dem:
            result["note"] = (
                f"{n_skipped_non_dem} NDVI-raster-detected candidate(s) were "
                f"not individually debated -- see debate_mobile.py's SCOPE note."
            )
        if gpr_item is not None and not any_gpr_confirmed:
            result["gpr_note"] = (
                f"Real GPR field-pick evidence was present for this "
                f"investigation, but no DEM candidate was within "
                f"{gpr_max_distance_m:.0f}m of the GPR pick location, so it "
                f"was not applied to any candidate's debate."
            )
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})
