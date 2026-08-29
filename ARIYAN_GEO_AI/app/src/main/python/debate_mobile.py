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
"""
from __future__ import annotations

import json
from typing import Any, Optional

from coordinate import GeoPoint, haversine_distance_m
from debate_engine import run_debate


def _nearest_correlation_entry(
    anomaly: dict, correlation: list[dict]
) -> Optional[dict]:
    """Return the correlation[] entry whose (lat, lon) is closest to this
    anomaly's own (lat, lon), or None if correlation is empty/unusable.
    See the module docstring for why nearest-match (not index-match) is
    the correct strategy given the real schema."""
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
    """Look up whether this investigation's NDVI evidence (if any) is
    synthetic or real, from the top-level evidence[] list (each evidence
    item -- e.g. SyntheticNDVISource / RealNdviCoreHaloEvidence's
    as_evidence_record() -- already carries evidence_type and synthetic).
    Returns None if no NDVI evidence source is present at all (NDVI
    correlation wasn't included in this run) -- debate_engine.py's
    vegetation perspective already checks NDVI presence separately via
    `sources`, so it doesn't need this value in that case."""
    for item in evidence or []:
        if item.get("evidence_type") == "NDVI":
            val = item.get("synthetic")
            return bool(val) if val is not None else None
    return None


def _gpr_evidence_item(evidence: list[dict]) -> Optional[dict]:
    """Return this investigation's GPR evidence record (see
    gpr_source_mobile.GPREvidence.as_evidence_record()), if a real GPR
    field pick was attached to this run, else None."""
    for item in evidence or []:
        if item.get("evidence_type") == "GPR":
            return item
    return None


def _gpr_colocation_distance_m(investigation: dict) -> float:
    """How close (in meters) the GPR pick's location must be to a DEM
    candidate to count as informative about that specific candidate.
    Reuses investigation_multi_mobile.py's own default colocation_distance_m
    formula (scale with the AOI's cell size, floor of 30m) -- GPR is a
    single site-anchored pick, not a raster, but this keeps the "how close
    counts as the same physical location" reasoning consistent with the
    rest of the project rather than inventing an unrelated constant."""
    aoi = investigation.get("aoi") or {}
    cell_size_m = aoi.get("cell_size_m")
    try:
        cell_size_m = float(cell_size_m) if cell_size_m is not None else None
    except (TypeError, ValueError):
        cell_size_m = None
    if cell_size_m is None:
        return 50.0
    return max(30.0, cell_size_m * 4)


def _attach_gpr(
    candidate: dict,
    anomaly: dict,
    gpr_item: Optional[dict],
    max_distance_m: float,
) -> bool:
    """If a real GPR field pick exists for this investigation and its
    location is within max_distance_m of this specific anomaly, mark the
    candidate as gpr_confirmed with distance + depth range so
    debate_engine.py's perspectives can factor in real subsurface
    confirmation. Returns True if attached, False otherwise. Left entirely
    ABSENT (not set to False) when GPR evidence doesn't exist or isn't
    close enough -- debate_engine.py's _get() already treats an absent key
    as "no signal", which is the honest state here (GPR wasn't
    informative for this candidate, not that it was checked and found
    absent)."""
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
    depth_mins = [
        d["depth_min_m"] for d in depth_estimates
        if d.get("depth_min_m") is not None
    ]
    depth_maxs = [
        d["depth_max_m"] for d in depth_estimates
        if d.get("depth_max_m") is not None
    ]

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
    """Translate one real anomalies[] entry into the field-name vocabulary
    debate_engine.py's _get() aliases already understand. Only sets keys
    that are actually known; missing information is left absent so
    debate_engine.py's own graceful degradation (insufficient_data) does
    the right thing rather than this module guessing.

    original_index, when given, is this anomaly's own 1-based position in
    THIS RUN'S OWN anomalies[] list (not the post-filter debates[] list --
    see the module docstring's SCOPE note on why those can differ). It
    becomes the candidate's "id", which debate_engine.run_debate() copies
    into the result's top-level "candidate_id" field. This is always a
    real, non-null value when original_index is provided -- see the
    module docstring's BUG HISTORY note for why that matters.

    checked_sources is the investigation-level list of evidence TYPES
    actually gathered this run (e.g. ["DEM","NDVI"] -- see
    _build_context()). candidate["sources"] is the union of this and
    correlation_entry's supporting_sources, NOT supporting_sources alone
    -- see the module docstring's second BUG HISTORY note for why using
    supporting_sources alone previously made a genuinely-checked-but-
    no-signal source (typically NDVI) indistinguishable from a source
    that was never checked at all."""
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

    # Union, order-preserving, de-duplicated: every evidence type actually
    # gathered for this investigation (checked_sources) PLUS anything
    # supporting_sources names that checked_sources might not have caught.
    # This is what fixes the Vegetation/Agronomic "no vegetation evidence
    # present" mislabeling -- see the module docstring's second BUG
    # HISTORY note.
    merged_sources = list(dict.fromkeys([*supporting_sources, *(checked_sources or [])]))
    if merged_sources:
        candidate["sources"] = merged_sources

    return candidate


def _build_context(investigation: dict) -> dict:
    """Investigation-level fallback info for candidates that don't carry
    their own correlation_status/sources (i.e. no correlation[] at all --
    a plain single-source DEM-only run). sources here reflects which
    evidence TYPES were gathered in this run (e.g. ["DEM"] or
    ["DEM","NDVI"]), not per-candidate corroboration -- debate_engine.py
    only consults it when a candidate has no per-candidate value."""
    evidence = investigation.get("evidence") or []
    context: dict[str, Any] = {
        "sources": [
            e.get("evidence_type") for e in evidence if e.get("evidence_type")
        ],
    }
    ndvi_synth = _ndvi_synthetic_flag(evidence)
    if ndvi_synth is not None:
        context["ndvi_synthetic"] = ndvi_synth
    return context


def run_debate_json(investigation_json: str) -> str:
    """Kotlin's single entry point (see MainActivity.kt's runDebate()).
    Never raises: any failure is caught and returned as {"error": "..."}
    JSON, matching the contract MainActivity.kt's appendDebateSection()
    already expects (it silently skips rendering on an "error" key)."""
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
            candidate = _build_candidate(
                anomaly, correlation_entry, context.get("sources"), original_index
            )
            if _attach_gpr(candidate, anomaly, gpr_item, gpr_max_distance_m):
                any_gpr_confirmed = True
            debates.append(run_debate(candidate, context))

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
    except Exception as exc:  # must never raise across the Chaquopy boundary
        return json.dumps({"error": str(exc)})
