"""
debate_engine.py
================
AI Debate Engine for ARIYAN GEO AI -- rule-based, offline, no LLM / no network.

WHY RULE-BASED:
This project's own testing rigor requires every claim to be reproducible and
provenance-tracked. An LLM-driven "debate" would introduce a non-deterministic,
unauditable reasoning step directly into a scientific evidence chain. Instead,
this module encodes a fixed set of transparent, hand-written heuristics --
one per "department" (perspective) -- that any reviewer can read, test, and
trace claim-by-claim back to the evidence fields that produced them.

This module is intentionally 100% Python standard library. No numpy, no
scipy, no network calls. It runs identically on desktop and on the Android
build (Chaquopy) with no additional dependencies or permissions.

INPUT CONTRACT (see _get() below for the actual field-name fallbacks used):
A "candidate" is a dict describing one detected anomaly, as already produced
by this project's anomaly_detection[_mobile].py / correlation.py pipeline.
This module does not assume one exact key-naming scheme -- it tries several
plausible aliases for each field (documented per perspective below) and
degrades gracefully (treats missing evidence as "insufficient data" rather
than guessing) when a field truly isn't present.

If your actual evidence-record schema uses different key names than the
aliases tried here, see the "SCHEMA MISMATCH" note in the README delivered
alongside this file -- update the alias tuples in _get() calls below; the
rule logic itself does not need to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Small schema-tolerant helpers
# ---------------------------------------------------------------------------

def _get(d: dict, *keys: str, default: Any = None) -> Any:
    """Return the first present, non-None value among several possible key
    names. Evidence records across this project's history have used slightly
    different naming (e.g. 'z_score' vs 'z', 'elevation_delta_m' vs
    'height_m'), so every lookup here tries a short list of aliases rather
    than assuming one fixed schema."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _abs_z(candidate: dict) -> Optional[float]:
    z = _get(candidate, "z_score", "z", "zscore", "anomaly_score")
    try:
        return abs(float(z)) if z is not None else None
    except (TypeError, ValueError):
        return None


def _correlation_status(candidate: dict, context: dict) -> str:
    status = _get(candidate, "correlation_status", "status", default=None)
    if status:
        return str(status).upper()
    # Fall back to context-level status if the candidate itself doesn't carry one
    status = _get(context, "correlation_status", default="SINGLE_SOURCE")
    return str(status).upper()


def _sources_present(candidate: dict, context: dict) -> list[str]:
    srcs = _get(candidate, "sources", "source_types", "evidence_sources")
    if srcs:
        return [str(s).upper() for s in srcs]
    srcs = _get(context, "sources", "source_types", "evidence_sources", default=[])
    return [str(s).upper() for s in srcs]


def _ndvi_is_synthetic(candidate: dict, context: dict) -> Optional[bool]:
    val = _get(candidate, "ndvi_synthetic", "synthetic_ndvi")
    if val is None:
        val = _get(context, "ndvi_synthetic", "synthetic_ndvi")
    return bool(val) if val is not None else None


def _elevation_relief_m(candidate: dict) -> Optional[float]:
    val = _get(
        candidate,
        "elevation_delta_m", "height_m", "relief_m",
        "elevation_range_m", "delta_elevation_m",
    )
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Confidence scoring (shared, deterministic)
# ---------------------------------------------------------------------------

def _confidence_label(score: float) -> str:
    """Maps a 0-1 heuristic score to this project's existing LOW/MODERATE/HIGH
    confidence vocabulary (matching anomaly_detection's existing framing)."""
    if score >= 0.70:
        return "HIGH"
    if score >= 0.40:
        return "MODERATE"
    return "LOW"


def _z_component(abs_z: Optional[float]) -> float:
    """Monotonic, saturating mapping from |z| to a 0-1 component. |z| of ~2 is
    the project's existing 'notable' threshold; |z| of ~4+ saturates."""
    if abs_z is None:
        return 0.0
    if abs_z <= 2.0:
        return max(0.0, (abs_z / 2.0) * 0.4)
    if abs_z >= 4.0:
        return 1.0
    return 0.4 + ((abs_z - 2.0) / 2.0) * 0.6


# ---------------------------------------------------------------------------
# Position: one perspective's argument about one candidate
# ---------------------------------------------------------------------------

@dataclass
class Position:
    perspective: str
    stance: str
    confidence_score: float
    confidence_label: str
    reasoning: list[str] = field(default_factory=list)
    insufficient_data: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# The four departments (perspectives)
# ---------------------------------------------------------------------------

def _geomorphology_position(candidate: dict, context: dict) -> Position:
    """Argues for a natural-landform explanation. Favors isolated,
    single-source elevation anomalies with moderate (not extreme) relief and
    no vegetation corroboration -- the signature of ordinary terrain
    variation rather than a discrete constructed feature."""
    abs_z = _abs_z(candidate)
    status = _correlation_status(candidate, context)
    sources = _sources_present(candidate, context)
    relief = _elevation_relief_m(candidate)

    if abs_z is None:
        return Position(
            "Geomorphology", "insufficient data to argue a natural-terrain case",
            0.0, "LOW", ["No elevation anomaly magnitude (z-score) available."],
            insufficient_data=True,
        )

    reasoning = [f"Elevation anomaly magnitude |z|={abs_z:.2f}."]
    score = 0.5 * _z_component(abs_z)  # elevation magnitude alone is weak evidence either way

    if status == "SINGLE_SOURCE" and "DEM" in sources:
        score += 0.25
        reasoning.append(
            "Anomaly detected only in elevation data, with no independent "
            "corroborating signal (e.g. vegetation) -- consistent with "
            "ordinary terrain variation (erosion, natural mounding, fluvial deposit)."
        )
    elif status == "CORROBORATED":
        score -= 0.20
        reasoning.append(
            "Anomaly is corroborated by an independent (non-elevation) source, "
            "which weakens a purely natural-terrain explanation."
        )

    if relief is not None:
        if relief <= 1.5:
            score += 0.10
            reasoning.append(
                f"Relief of {relief:.2f} m is within the range commonly produced "
                "by natural micro-topography."
            )
        elif relief >= 4.0:
            score -= 0.10
            reasoning.append(
                f"Relief of {relief:.2f} m is larger than typical natural "
                "micro-relief, which weakens a natural-only explanation."
            )

    score = max(0.0, min(1.0, score))
    return Position(
        "Geomorphology",
        "natural landform / terrain variation",
        round(score, 3),
        _confidence_label(score),
        reasoning,
    )


def _anthropogenic_position(candidate: dict, context: dict) -> Position:
    """Argues for a human-made (archaeological / constructed) feature.
    Favors corroboration across independent evidence sources (elevation +
    vegetation stress patterns) with clearly real (non-synthetic) evidence,
    which is this project's own definition of stronger evidence."""
    abs_z = _abs_z(candidate)
    status = _correlation_status(candidate, context)
    sources = _sources_present(candidate, context)
    ndvi_synth = _ndvi_is_synthetic(candidate, context)

    if abs_z is None and status == "SINGLE_SOURCE":
        return Position(
            "Anthropogenic / Archaeological", "insufficient data to argue a constructed-feature case",
            0.0, "LOW", ["No anomaly magnitude or corroboration data available."],
            insufficient_data=True,
        )

    reasoning = []
    score = 0.15  # constructed-feature is not the default assumption; must be earned

    if status == "CORROBORATED":
        score += 0.35
        reasoning.append(
            "Anomaly is CORROBORATED across independent evidence sources "
            f"({', '.join(sources) if sources else 'multiple sources'}), which this "
            "project treats as materially stronger evidence than any single source alone."
        )
        if ndvi_synth is False:
            score += 0.15
            reasoning.append(
                "The vegetation (NDVI) corroboration is real satellite data, not synthetic, "
                "so this corroboration reflects an actual real-world signal."
            )
        elif ndvi_synth is True:
            reasoning.append(
                "Note: the vegetation corroboration on this platform is currently "
                "SYNTHETIC (placeholder) data, not a real satellite signal -- this "
                "corroboration should not yet be treated as real-world confirmation."
            )
    else:
        reasoning.append(
            "Anomaly is SINGLE_SOURCE only (no independent corroboration yet), "
            "which is weak standalone evidence for a constructed feature."
        )

    if abs_z is not None:
        score += 0.25 * _z_component(abs_z)
        reasoning.append(f"Elevation anomaly magnitude |z|={abs_z:.2f}.")

    score = max(0.0, min(1.0, score))

    if ndvi_synth is True:
        # A HIGH-confidence claim of a constructed feature must not rest on
        # fake corroboration. Capping here (not just noting it in reasoning)
        # is what actually enforces the honesty requirement -- text alone is
        # not enough if the number still reads as strong evidence.
        score = min(score, 0.55)

    return Position(
        "Anthropogenic / Archaeological",
        "possible constructed / human-modified feature",
        round(score, 3),
        _confidence_label(score),
        reasoning,
    )


def _artifact_skeptic_position(candidate: dict, context: dict) -> Position:
    """Always argues the null hypothesis: this could be measurement noise,
    a data-processing artifact, or an interpolation error, not a real
    feature at all. This perspective's job is to keep the other two honest --
    it is weighted higher when the underlying signal is weak or borderline."""
    abs_z = _abs_z(candidate)
    status = _correlation_status(candidate, context)

    if abs_z is None:
        return Position(
            "Data Artifact / Skeptic",
            "cannot evaluate -- no anomaly magnitude reported, which is itself "
            "a data-quality concern",
            0.5, "MODERATE",
            ["No z-score/anomaly magnitude was supplied for this candidate."],
            insufficient_data=True,
        )

    reasoning = [f"Elevation anomaly magnitude |z|={abs_z:.2f}."]
    # Skeptic's score is HIGH when evidence is weak, LOW when evidence is strong.
    score = 1.0 - _z_component(abs_z)

    if 2.0 <= abs_z < 2.5:
        score = max(score, 0.55)
        reasoning.append(
            "This magnitude sits just above the detection threshold -- exactly "
            "where resampling, interpolation, or DEM void-fill artifacts most "
            "often produce false positives."
        )

    if status == "SINGLE_SOURCE":
        score += 0.10
        reasoning.append(
            "No independent source corroborates this candidate, which is "
            "consistent with (though does not prove) an artifact of a single "
            "data source."
        )
    else:
        score -= 0.15
        reasoning.append(
            "Independent corroboration across sources makes a shared artifact "
            "(e.g. a coincidental error in two unrelated datasets) less likely."
        )

    score = max(0.0, min(1.0, score))
    return Position(
        "Data Artifact / Skeptic",
        "possible measurement noise / processing artifact, not a real feature",
        round(score, 3),
        _confidence_label(score),
        reasoning,
    )


def _vegetation_position(candidate: dict, context: dict) -> Position:
    """Argues that the anomaly is primarily a vegetation-driven signal
    (e.g. a crop mark or soil-moisture-linked NDVI effect) rather than a
    true elevation feature. Only takes a substantive position when NDVI
    evidence is actually present for this candidate."""
    sources = _sources_present(candidate, context)
    ndvi_synth = _ndvi_is_synthetic(candidate, context)

    if "NDVI" not in sources:
        return Position(
            "Vegetation / Agronomic", "no vegetation evidence present for this candidate",
            0.0, "LOW", ["No NDVI/vegetation source was part of this candidate's evidence."],
            insufficient_data=True,
        )

    status = _correlation_status(candidate, context)
    reasoning = ["NDVI (vegetation) evidence is present for this candidate."]
    score = 0.30

    if status == "SINGLE_SOURCE":
        score += 0.20
        reasoning.append(
            "Vegetation signal is not corroborated by elevation data, which is "
            "consistent with a vegetation-only cause (e.g. soil moisture, crop "
            "stress) with no underlying earthwork."
        )
    else:
        reasoning.append(
            "Vegetation signal co-occurs with an elevation anomaly, so a "
            "vegetation-only explanation is weaker here than it would be alone."
        )

    if ndvi_synth is True:
        reasoning.append(
            "IMPORTANT: on this platform the NDVI signal is currently SYNTHETIC "
            "(placeholder) data, not a real satellite measurement -- this "
            "position is illustrative only until real NDVI is wired in."
        )
        score = min(score, 0.35)  # cap confidence, cannot exceed LOW/MODERATE boundary meaningfully

    score = max(0.0, min(1.0, score))
    return Position(
        "Vegetation / Agronomic",
        "possible vegetation-driven signal (crop mark / soil moisture), not a landform feature",
        round(score, 3),
        _confidence_label(score),
        reasoning,
    )


_PERSPECTIVES = (
    _geomorphology_position,
    _anthropogenic_position,
    _artifact_skeptic_position,
    _vegetation_position,
)


# ---------------------------------------------------------------------------
# Synthesis ("Scientific Steward" role): combine positions, do not "decide truth"
# ---------------------------------------------------------------------------

def _synthesize(positions: list[Position]) -> dict:
    active = [p for p in positions if not p.insufficient_data]
    if not active:
        return {
            "leading_position": None,
            "agreement_level": "NO_DATA",
            "steward_note": (
                "No perspective had sufficient evidence to argue a position on "
                "this candidate. This reflects a gap in the evidence record, "
                "not a finding."
            ),
        }

    ranked = sorted(active, key=lambda p: p.confidence_score, reverse=True)
    leader = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None

    if runner_up is not None and (leader.confidence_score - runner_up.confidence_score) < 0.15:
        agreement = "CONTESTED"
        note = (
            f"'{leader.perspective}' ({leader.confidence_score:.2f}) and "
            f"'{runner_up.perspective}' ({runner_up.confidence_score:.2f}) are "
            "close in confidence -- this candidate does not have a clear leading "
            "interpretation and should be treated as genuinely ambiguous, not resolved."
        )
    elif leader.confidence_score < 0.40:
        agreement = "WEAK_SIGNAL"
        note = (
            f"Even the leading perspective ('{leader.perspective}') only reaches "
            f"{leader.confidence_score:.2f} confidence. Overall evidence for this "
            "candidate is weak across all perspectives; treat as low-priority "
            "pending stronger or additional evidence."
        )
    else:
        agreement = "LEADING_INTERPRETATION"
        note = (
            f"'{leader.perspective}' presents the strongest-supported interpretation "
            f"({leader.confidence_score:.2f} confidence), but this is a ranked "
            "heuristic opinion, not a proof -- other perspectives above should still "
            "be reviewed."
        )

    return {
        "leading_position": leader.perspective,
        "leading_confidence": leader.confidence_score,
        "agreement_level": agreement,
        "steward_note": note,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_debate(candidate: dict, context: Optional[dict] = None) -> dict:
    """Run all four perspectives against one candidate evidence record and
    return a debate result dict: positions + a non-authoritative synthesis.

    `context` is optional shared/global information about the investigation
    (e.g. which sources were run at all, whether NDVI on this platform is
    synthetic) that individual candidates may not each repeat -- perspectives
    fall back to `context` for anything missing on the candidate itself.
    """
    context = context or {}
    positions = [p(candidate, context) for p in _PERSPECTIVES]
    return {
        "candidate_id": _get(candidate, "id", "candidate_id"),
        "location": _get(candidate, "location", "coordinates"),
        "positions": [p.to_dict() for p in positions],
        "synthesis": _synthesize(positions),
    }


def run_debate_for_investigation(investigation_result: dict) -> dict:
    """Run the debate engine over every candidate in an investigation result
    (as produced by investigation.py / investigation_multi.py /
    investigation_mobile.py / investigation_multi_mobile.py).

    Tries common candidate-list key names; falls back to treating the whole
    input as a single candidate if none match (defensive, not a guess about
    correctness -- callers should check `debates` is non-empty).
    """
    candidates = _get(
        investigation_result, "candidates", "anomaly_candidates", "results",
        default=[],
    )
    context = {
        "correlation_status": _get(investigation_result, "correlation_status"),
        "sources": _get(investigation_result, "sources", "source_types", default=[]),
        "ndvi_synthetic": _get(investigation_result, "ndvi_synthetic", "synthetic_ndvi"),
    }

    if not candidates:
        return {"debates": [], "note": "No candidates found in investigation_result."}

    debates = [run_debate(c, context) for c in candidates]
    return {"debates": debates}
