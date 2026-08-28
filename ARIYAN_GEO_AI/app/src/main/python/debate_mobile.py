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
NOT modify debate_engine.py's rule logic (per that file's own docstring
recommendation -- "the rule logic itself does not need to change"), it
only maps this project's REAL InvestigationRecord schema (confirmed by
reading evidence_record.py, anomaly_detection_mobile.py, correlation.py,
and investigation_multi_mobile.py directly, not guessed) onto the field
names debate_engine.py already knows how to read.

REAL SCHEMA NOTES (why this file looks the way it does):
- anomalies[] entries are AnomalyCandidate dicts: row, col, lat, lon,
  area_cells, peak_residual_m, mean_residual_m, peak_zscore, polarity
  (+ "evidence_type": "DEM"/"NDVI" in multi-source runs; ABSENT entirely
  in single-source investigation_mobile.py output). There is no id /
  candidate_id field anywhere in this schema -- debate_engine.py handles
  that gracefully (candidate_id comes back None; MainActivity.kt already
  falls back to "#<index>" when rendering).
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
- SCOPE: only anomalies[] entries with evidence_type == "DEM" (or no
  evidence_type at all -- single-source runs) are debated. In synthetic-
  NDVI mode, anomalies[] can also hold NDVI-raster-detected candidates
  (evidence_type == "NDVI") that were never individually corroborated
  against a specific DEM candidate; debating those through perspectives
  written around "elevation anomaly magnitude" would not be a faithful
  use of the tool, so they're skipped and reported as a count instead of
  silently dropped.
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


def _build_candidate(anomaly: dict, correlation_entry: Optional[dict]) -> dict:
    """Translate one real anomalies[] entry into the field-name vocabulary
    debate_engine.py's _get() aliases already understand. Only sets keys
    that are actually known; missing information is left absent so
    debate_engine.py's own graceful degradation (insufficient_data) does
    the right thing rather than this module guessing."""
    candidate: dict[str, Any] = {
        "location": {"lat": anomaly.get("lat"), "lon": anomaly.get("lon")},
    }
    if anomaly.get("peak_zscore") is not None:
        candidate["z_score"] = anomaly["peak_zscore"]
    if anomaly.get("peak_residual_m") is not None:
        candidate["elevation_delta_m"] = anomaly["peak_residual_m"]
    if correlation_entry is not None:
        if correlation_entry.get("status"):
            candidate["correlation_status"] = correlation_entry["status"]
        if correlation_entry.get("supporting_sources"):
            candidate["sources"] = correlation_entry["supporting_sources"]
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
        context = _build_context(investigation)

        debates = []
        n_skipped_non_dem = 0
        for anomaly in anomalies:
            evidence_type = anomaly.get("evidence_type", "DEM")
            if evidence_type != "DEM":
                n_skipped_non_dem += 1
                continue
            correlation_entry = _nearest_correlation_entry(anomaly, correlation)
            candidate = _build_candidate(anomaly, correlation_entry)
            debates.append(run_debate(candidate, context))

        result: dict[str, Any] = {"debates": debates}
        if n_skipped_non_dem:
            result["note"] = (
                f"{n_skipped_non_dem} NDVI-raster-detected candidate(s) were "
                f"not individually debated -- see debate_mobile.py's SCOPE note."
            )
        return json.dumps(result)
    except Exception as exc:  # must never raise across the Chaquopy boundary
        return json.dumps({"error": str(exc)})
