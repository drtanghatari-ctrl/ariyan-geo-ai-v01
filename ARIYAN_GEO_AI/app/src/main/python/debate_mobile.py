"""
debate_mobile.py — Chaquopy entry point wrapping debate_engine.py for
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
  BUG HISTORY (fixed): earlier versions of this file left candidate_id
  entirely unset, relying on debate_engine.py returning
  candidate_id=None and assuming MainActivity.kt would fall back to a
  generated "#<index>" label. That assumption was wrong in practice --
  org.json's JSONObject.optString(name, fallback) only uses the
  fallback when the KEY IS ABSENT, not when the key is present with a
  JSON null value (which is exactly what a Python None serializes to).
  So the JSON always had a literal "candidate_id": null, and Kotlin's
  optString() returned the literal string "null", rendering "Candidate
  null:" in the UI instead of a real label. This is fixed at the root
  here (a real, non-null id is now always assigned), with a matching
  defensive fix in MainActivity.kt's appendDebateSection() in case any
  future caller of debate_engine.py still doesn't supply one.
- correlation[] entries (when present) are CorrelatedCandidate dicts:
  lat, lon, status ("CORROBORATED"/"SINGLE_SOURCE"), supporting_sources,
  distance_between_peaks_m, note. In real-NDVI mode
  (investigation_multi_mobile.py's use_real_ndvi=True path) each entry's
  lat/lon is copied directly from its one DEM candidate, so matching by
  nearest lat/lon is always exact. In synthetic-NDVI mode, correlate_
  anomalies() sorts correlation[] independently of anomalies[] order and
  uses a centroid lat/lon for CORROBORATED (2+ source) groups -- still
  exact for SINGLE_SOURCE entries (centroid of one point is that point),
  and a close match for CORROBORATED ones (centroid of co-located points
  within colocation_distance_m by construction). Nearest-match is
  therefore correct, not a guess, across both modes.
- TWO DISTINCT "sources" CONCEPTS, NOW KEPT SEPARATE (fixed this session
  -- see SOURCES-SPLIT FIX below for the full story): "which sources
  actually CORROBORATED this candidate" (precise, drives correlation-
  status reasoning text) and "which sources were CHECKED/attempted for
  this candidate regardless of outcome" (broader, drives the Vegetation/
  Agronomic perspective's "was NDVI evaluated at all" question). These
  used to be silently merged into one field; conflating them was itself
  the root cause of the bug fixed this session.
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

GPR (ground-penetrating radar) EXTENSION (added when GPR was wired into
the debate engine): a real GPR field pick (evidence_record.py's third
evidence slot, see gpr_source_mobile.GPREvidence.as_evidence_record()) is
anchored at the investigation's own (lat, lon) -- it is a single
site-anchored check, not a per-candidate one like NDVI core/halo. This
module therefore matches the GPR pick to whichever DEM candidate(s) are
close enough (within a distance tolerance derived from the AOI's cell
size, same reasoning as investigation_multi_mobile.py's own default
colocation_distance_m) to plausibly be about the same physical location,
and attaches gpr_confirmed/gpr_distance_m/gpr_depth_min_m/gpr_depth_max_m
to just those candidates. A candidate that's too far from the GPR pick
gets nothing added -- GPR wasn't informative for it, which is the honest
state, not a guess either way. If GPR evidence exists but no candidate
was close enough to use it, that is reported in the result's "gpr_note"
field rather than silently discarded.

REAL THERMAL EXTENSION (added a prior session): unlike GPR's single
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
this specific candidate" -- unaffected by this session's SOURCES-SPLIT
FIX below (it was already precise from the start).

SOURCES-SPLIT FIX (this session -- REAL on-device bug): a real
investigation showed a candidate's Anthropogenic/Archaeological
reasoning text claiming "CORROBORATED across independent evidence
sources (DEM, NDVI, GPR, THERMAL)" even though GPR's pick was nowhere
near that candidate (gpr_confirmed was False for it) and Thermal had
genuinely failed for that same candidate. The correlation_status
("CORROBORATED") and confidence numbers were CORRECT throughout --
only the reasoning sentence's list of *which* sources corroborated was
wrong.

ROOT CAUSE: candidate["sources"] was being set to the UNION of two
things that answer genuinely different questions:
  (a) supporting_sources from this candidate's own correlation_entry --
      precise, exactly what corroborated THIS candidate (e.g. ["DEM",
      "NDVI"]).
  (b) context["sources"] -- every evidence_type present ANYWHERE in
      the run's evidence[] list, regardless of whether it applied to
      this specific candidate (this is why GPR/THERMAL leaked in: a GPR
      evidence item and a Thermal evidence item both existed in this
      run's evidence[], even though neither corroborated -- or in
      Thermal's case, even successfully checked -- this particular
      candidate).
The union with (b) was NOT a mistake in isolation -- it was deliberately
added (see the older "sources" BUG HISTORY note above) to fix a REAL,
separate problem: debate_engine.py's Vegetation/Agronomic perspective
needs to know "was NDVI evaluated at all for this candidate" even when
NDVI showed no stress (a SINGLE_SOURCE correlation_entry's
supporting_sources only lists the source that positively detected an
anomaly, e.g. ["DEM"], NOT a source that was checked and found nothing).
Without (b), a genuinely-checked-but-no-signal NDVI result would look
identical to "NDVI was never attempted at all" to that perspective --
exactly the mislabeling this project's zero-fake-data principle exists
to prevent.

The actual bug was collapsing BOTH answers into the SAME field
(candidate["sources"]), which debate_engine.py's Anthropogenic
perspective then quoted verbatim as "what corroborated" -- silently
picking up (b)'s whole-run union in a place that needed (a)'s
per-candidate precision.

THE FIX: stop merging. candidate["sources"] is now set to
supporting_sources ONLY (precise, exactly what corroborated this
candidate) -- this is what debate_engine.py's Anthropogenic/
Geomorphology perspectives read via _sources_present(), so their
reasoning text is now always accurate for this candidate specifically.
A NEW, separate field, candidate["checked_sources"], now carries
EXACTLY the same union value "sources" used to carry before this fix
(supporting_sources + context["sources"], deduplicated) -- this is a
new alias debate_engine.py's Vegetation/Agronomic perspective now reads
via a new _sources_checked_present() helper (see debate_engine.py's own
docstring for that change), so its existing, already-on-device-proven
"was NDVI checked at all" behavior is UNCHANGED, byte-for-byte, just
reading from a differently-named field.

_build_steward_report() below is updated to match: has_dem/has_ndvi now
read candidate["checked_sources"] (the broader, historically-used union)
rather than candidate["sources"] (now precise-only) -- this preserves
the Scientific Steward's exact existing on-device-confirmed Stage 1
behavior unchanged; only debate_engine.py's Anthropogenic reasoning text
changes as a result of this fix.

SCIENTIFIC STEWARD STAGE 1 EXTENSION (added a prior session): after
debate_engine.run_debate() returns its positions + synthesis for a
candidate, this module also calls steward_engine.evaluate_candidate()
(see steward_engine.py, built and sandbox-tested standalone in a prior
session) and attaches the result under a new "steward" key on that same
debate dict. This is purely additive -- MainActivity.kt's existing
appendDebateSection() rendering is completely unaffected by the extra
key until it's explicitly updated to read it.

HONEST MAPPING NOTES (read before changing _build_steward_report below):
this module has REAL data for some Steward inputs and does NOT for
others -- the mapping below is deliberately conservative rather than
guessing, per this project's zero-fabrication rule:
  - has_dem / has_ndvi: real, taken from candidate["checked_sources"]
    (the broader union -- see SOURCES-SPLIT FIX above for why this is
    the correct field for Steward to read, unchanged in effect from
    before this session's fix).
  - has_gpr / has_field_validation: real, taken directly from
    candidate["gpr_confirmed"] (see _attach_gpr() above -- set only
    when a real GPR pick colocated with this specific candidate).
  - has_thermal: real, taken directly from candidate["thermal_checked"]
    (see _attach_thermal_detail() below -- set only when a real per-
    candidate Thermal check genuinely succeeded, i.e. its own error
    field was None, for THIS EXACT candidate -- not merely "Thermal was
    attempted somewhere in this run"). If a candidate's Thermal check
    genuinely failed (network/auth/no-data), has_thermal is honestly
    False for that candidate, not True.
  - has_optical / has_lidar / has_ert: always False. ARIYAN does not
    track a separate raw-optical evidence stream distinct from NDVI
    (NDVI IS derived from the same Sentinel-2 optical bands -- counting
    OPTICAL as independent here would double-count a single satellite
    pass as two independent evidence sources and artificially inflate
    the confidence ceiling), and has no LiDAR/ERT sources built at all.
    Deliberate, not an oversight.
  - raw_debate_confidence: real, taken directly from
    synthesis["leading_confidence"] (0.0 when NO_DATA / absent, which
    correctly yields the Steward's NO_DATA band).
  - has_contradiction: an APPROXIMATION, not a true independent-evidence
    contradiction detector -- mapped from agreement_level == "CONTESTED"
    (two perspectives closely competing). This is honestly a proxy, not
    the real Team-A/Team-B/Judge contradiction detection the Scientific
    Steward spec describes for Stage 3 -- documented here so it isn't
    mistaken for that later.
  - environmental_confounders_controlled: always False for Stage 1. The
    existing 4-perspective debate engine ARGUES a vegetation/moisture
    alternative when applicable (Vegetation/Agronomic perspective), but
    does not yet systematically verify/control for it the way the
    Scientific Steward spec's Stage 3 Team A/B/Judge debate is meant to
    -- claiming otherwise here would overstate what Stage 1 actually
    checks, so this stays False until Stage 3 exists.
  - provenance_verified: always False for Stage 1. SHA-256 evidence
    validation / provenance ledger / custody reconciliation is
    Scientific Steward Stage 2, not yet built -- so a PROVENANCE_WARNING
    on every candidate is the CORRECT, honest state right now, not a bug.
  - quality_hints / requested_precision_m / effective_resolution_m: left
    unset (UNKNOWN / None). Per-candidate evidence QUALITY and DEM
    resolution are not currently tracked as explicit per-candidate
    fields anywhere in this schema -- guessing a number here would
    violate this project's zero-fabrication rule. These can be wired in
    later if/when real per-candidate quality or resolution metadata is
    added to the investigation schema.
  - hypothesis / alternative_hypotheses / debate_summary: real, built
    directly from the SAME positions[]/synthesis{} debate_engine.py
    already produced -- the leading position's own stance text becomes
    the hypothesis, every other active (non-insufficient-data)
    position's stance becomes an alternative hypothesis, and the
    existing steward_note becomes both the interpretation and the
    debate_summary. Nothing here is newly authored text -- it is a
    direct re-presentation of debate_engine.py's own output through the
    Steward's structured reasoning trace.

A Steward evaluation failure for one candidate is caught and reported as
a "steward_error" string on that candidate's debate dict instead of
raising -- consistent with this file's existing "never raise across the
Chaquopy boundary" contract for run_debate_json as a whole, and matching
the same per-candidate defensive pattern already used for GPR/NDVI/
Thermal elsewhere in this project (one candidate's Steward failure must
never hide the other three perspectives' real debate results for that
same candidate, or any other candidate's results).
"""
from __future__ import annotations

import json
from typing import Any, Optional

from coordinate import GeoPoint, haversine_distance_m
from debate_engine import run_debate
from steward_engine import evaluate_candidate as steward_evaluate_candidate

# Tolerance for matching a DEM candidate to its OWN per-candidate Thermal
# detail entry. Deliberately tight (a few meters) -- unlike GPR's
# colocation-radius-style tolerance for "was this nearby", Thermal
# detail entries are built directly from the SAME dem_candidate.lat/lon
# (see investigation_multi_mobile.py's _run_thermal_checks), so any real
# distance here should only ever reflect floating-point noise, not a
# genuine "different but nearby location" case.
_THERMAL_DETAIL_MATCH_TOLERANCE_M = 5.0


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


def _attach_thermal_detail(
    candidate: dict,
    anomaly: dict,
    fourth_evidence_detail: list[dict],
    tolerance_m: float = _THERMAL_DETAIL_MATCH_TOLERANCE_M,
) -> None:
    """Sets candidate["thermal_checked"] = True only when a real
    per-candidate Thermal result exists for THIS exact candidate (tight
    tolerance -- see module-level constant's own comment) AND that
    result's own error field is None (i.e. the check genuinely
    succeeded for this candidate, regardless of whether it detected an
    anomaly). False for: no Thermal detail present at all (Thermal
    never attempted this run), a detail entry existing only for a
    different/distant candidate, or a genuinely matched entry whose
    error field is set (this candidate's own Thermal check failed).

    Already precise from the start (unaffected by this session's
    SOURCES-SPLIT FIX) -- built this way for Thermal since it's new code
    with no existing on-device-proven behavior to risk regressing by
    choosing the more precise design immediately.
    """
    best = None
    best_dist = None
    for entry in fourth_evidence_detail:
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
        candidate["thermal_checked"] = False
        return
    candidate["thermal_checked"] = best.get("error") is None


def _build_candidate(
    anomaly: dict,
    correlation_entry: Optional[dict],
    checked_sources: Optional[list[str]] = None,
    original_index: Optional[int] = None,
) -> dict:
    """Builds the candidate dict debate_engine.py consumes.

    SOURCES-SPLIT FIX (this session): candidate["sources"] is now set to
    ONLY this candidate's own supporting_sources -- precise, exactly
    what corroborated THIS candidate. Previously this was merged with
    checked_sources (the whole-run union of evidence types present
    anywhere), which caused debate_engine.py's Anthropogenic perspective
    to falsely list sources (e.g. GPR, THERMAL) that never actually
    corroborated this specific candidate in its reasoning text -- see
    this module's own SOURCES-SPLIT FIX docstring note for the full
    real-on-device bug history.

    candidate["checked_sources"] now separately carries EXACTLY the same
    union value "sources" used to carry before this fix (supporting_
    sources + checked_sources param, deduplicated) -- this preserves
    debate_engine.py's Vegetation/Agronomic perspective's existing,
    already-on-device-proven "was NDVI checked at all for this
    candidate" behavior byte-for-byte (see debate_engine.py's new
    _sources_checked_present(), which now reads this field), and also
    preserves _build_steward_report()'s existing has_dem/has_ndvi
    behavior below (updated to read checked_sources instead of sources).
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
        # Precise: exactly what corroborated THIS candidate. This is
        # what debate_engine.py's Anthropogenic/Geomorphology
        # perspectives read for their reasoning text (via
        # _sources_present()) -- fixed this session, see docstring.
        candidate["sources"] = supporting_sources

    merged_sources = list(dict.fromkeys([*supporting_sources, *(checked_sources or [])]))
    if merged_sources:
        # Broader: the whole-run union, exactly as "sources" used to
        # mean before this session's fix. Only debate_engine.py's
        # Vegetation/Agronomic perspective (via the new
        # _sources_checked_present()) and this module's own
        # _build_steward_report() below read this field now.
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

    has_dem/has_ndvi read candidate["checked_sources"] (the broader,
    historically-used union), NOT candidate["sources"] (now precise-only
    as of this session's SOURCES-SPLIT FIX) -- this keeps the Scientific
    Steward's exact existing on-device-confirmed Stage 1 behavior
    unchanged; only debate_engine.py's Anthropogenic reasoning text
    changes as a result of that fix.
    """
    checked_sources = candidate.get("checked_sources") or []
    has_dem = "DEM" in checked_sources
    has_ndvi = "NDVI" in checked_sources
    has_gpr = bool(candidate.get("gpr_confirmed"))
    has_thermal = bool(candidate.get("thermal_checked"))

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
        has_optical=False,
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