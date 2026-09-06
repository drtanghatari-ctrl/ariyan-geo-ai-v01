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
- "sources" on a candidate (consumed by debate_engine.py's
  _sources_present()) must mean "which evidence TYPES were actually
  evaluated for this candidate" (e.g. DEM elevation + NDVI vegetation),
  not merely "which sources happened to corroborate it".
  BUG HISTORY (fixed): earlier versions of this file set
  candidate["sources"] directly from correlation_entry["supporting_sources"]
  alone. For a SINGLE_SOURCE correlation entry, supporting_sources only
  lists the source that positively detected the anomaly (e.g. ["DEM"]) --
  it does NOT include a source like NDVI that was genuinely checked at
  this candidate's exact location but simply found no corroborating
  signal. Because debate_engine.py's _sources_present() returns the
  candidate-level "sources" the moment it is non-empty (never falling
  back to the broader context-level list), this caused
  debate_engine.py's Vegetation/Agronomic perspective to wrongly report
  "no vegetation evidence present for this candidate" (insufficient_data)
  even when real Copernicus NDVI evidence had actually been fetched and
  checked for that exact candidate and simply showed no stress signal --
  an honest "checked, no signal" finding was mislabeled as "not checked
  at all", exactly the kind of mislabeling this project's zero-fake-data
  principle exists to prevent. Fixed at the root here: candidate
  ["sources"] is now the union of correlation_entry's supporting_sources
  AND the investigation-level list of evidence types that were actually
  gathered (context["sources"], built in _build_context() from the
  top-level evidence[] list) -- so a checked-but-no-signal source is
  never silently indistinguishable from an unchecked one.
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

SCIENTIFIC STEWARD STAGE 1 EXTENSION (added this session -- the ONLY
change in this file this session, everything above is unchanged from the
prior version): after debate_engine.run_debate() returns its positions +
synthesis for a candidate, this module now ALSO calls
steward_engine.evaluate_candidate() (see steward_engine.py, built and
sandbox-tested standalone in a prior session) and attaches the result
under a new "steward" key on that same debate dict. This is purely
additive -- MainActivity.kt's existing appendDebateSection() rendering
is completely unaffected by the extra key until it's explicitly updated
to read it (see this session's matching MainActivity.kt change).

HONEST MAPPING NOTES (read before changing _build_steward_report below):
this module has REAL data for some Steward inputs and does NOT for
others -- the mapping below is deliberately conservative rather than
guessing, per this project's zero-fabrication rule:
  - has_dem / has_ndvi: real, taken directly from candidate["sources"]
    (see the "sources" bug-history note above -- this is the same
    union-of-checked-and-corroborating list debate_engine.py itself
    reads, so it is exactly as reliable as the existing Vegetation/
    Agronomic perspective's own "was NDVI checked" logic).
  - has_gpr / has_field_validation: real, taken directly from
    candidate["gpr_confirmed"] (see _attach_gpr() above -- set only
    when a real GPR pick colocated with this specific candidate).
  - has_optical / has_thermal / has_lidar / has_ert: always False.
    ARIYAN does not track a separate raw-optical evidence stream
    distinct from NDVI (NDVI IS derived from the same Sentinel-2
    optical bands), and has no thermal/LiDAR/ERT sources built at all
    -- counting OPTICAL as a source independent from NDVI here would
    double-count a single satellite pass as two independent evidence
    sources and artificially inflate the confidence ceiling. This is a
    deliberate choice, not an oversight.
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
the same per-candidate defensive pattern already used for GPR/NDVI
elsewhere in this project (one candidate's Steward failure must never
hide the other three perspectives' real debate results for that same
candidate, or any other candidate's results).
"""
from __future__ import annotations

import json
from typing import Any, Optional

from coordinate import GeoPoint, haversine_distance_m
from debate_engine import run_debate
from steward_engine import evaluate_candidate as steward_evaluate_candidate


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


def _build_candidate(
    anomaly: dict,
    correlation_entry: Optional[dict],
    checked_sources: Optional[list[str]] = None,
    original_index: Optional[int] = None,
) -> dict:
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

    merged_sources = list(dict.fromkeys([*supporting_sources, *(checked_sources or [])]))
    if merged_sources:
        candidate["sources"] = merged_sources

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
    """Scientific Steward Stage 1 wiring. See HONEST MAPPING NOTES (in the
    real committed file's module docstring) for exactly which inputs are
    real vs. deliberately conservative placeholders."""
    sources = candidate.get("sources") or []
    has_dem = "DEM" in sources
    has_ndvi = "NDVI" in sources
    has_gpr = bool(candidate.get("gpr_confirmed"))

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