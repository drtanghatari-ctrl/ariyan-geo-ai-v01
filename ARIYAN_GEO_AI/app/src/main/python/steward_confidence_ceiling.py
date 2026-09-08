"""
steward_confidence_ceiling.py

Scientific Steward -- Stage 1 (Steward Foundation)

The confidence governor: computes the MAXIMUM confidence ARIYAN is
scientifically permitted to report for a candidate, given what evidence
actually exists. This ceiling can only ever clamp confidence DOWN --
it never boosts a model's confidence, and it never lets a raw AI/debate
confidence value pass through unexamined.

"The AI's enthusiasm must never override scientific evidence."

DETECTION STABILITY EXTENSION (added this session): real on-device
testing (18+ live investigations, see project notes) found that
detect_anomalies() -- run once per investigation, against whatever DEM
raster this run's specific AOI window happened to fetch -- can
genuinely disagree with itself when re-run at a slightly different
window center. Candidates well above the detection threshold were
rock-solid across every re-fetch tested; candidates close to threshold
frequently failed to reproduce. A `stability_score` (fraction of
independently re-fetched offset windows that reproduced this candidate
-- see investigation_multi_mobile.py's _run_stability_check()) is now
an optional input here.

This is placed at the SAME priority tier as has_contradiction --
BEFORE has_field_validation, source count, or quality are ever
consulted -- and deliberately so: field-validating (GPR/ERT) a
candidate whose underlying elevation anomaly itself may not reliably
exist doesn't rescue it, it just validates a possible artifact. A low
stability_score therefore caps the ceiling unconditionally, the same
way a contradiction does, rather than being averaged in with other
positive factors.

stability_score=None (the default, and the actual value for any
candidate the automatic check did not run against -- see
investigation_multi_mobile.py for exactly which candidates qualify)
means "not tested," not "unstable" -- it applies NO cap and changes
NOTHING about this function's existing behavior. Only a candidate that
WAS tested and came back fragile is affected.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from steward_evidence_matrix import EvidenceMatrix, EvidenceQuality

# Thresholds derived from real testing (see project notes): the
# observed fragile band was roughly |z| 2.6-3.0 against a 2.5 DEM
# threshold, with reproduction rates ranging from 0.0 (total failure)
# up through roughly 0.5 (mixed) up to 1.0 (rock-solid, |z| >~3.2).
# These two cutoffs are a first real calibration from that data, not a
# settled scientific constant -- expect them to be revisited as more
# real investigations accumulate.
STABILITY_LOW_CAP_THRESHOLD = 0.4   # below this: cap at LOW, unconditionally
STABILITY_MODERATE_CAP_THRESHOLD = 0.7  # below this (and >= LOW threshold): cap at MODERATE


class ConfidenceBand(Enum):
    NO_DATA = "NO_DATA"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SUBSTANTIAL = "SUBSTANTIAL"

    @property
    def numeric_ceiling(self) -> float:
        """Upper bound (0-1 scale) a raw confidence value may be clamped to."""
        return {
            ConfidenceBand.NO_DATA: 0.0,
            ConfidenceBand.LOW: 0.35,
            ConfidenceBand.MODERATE: 0.55,
            ConfidenceBand.HIGH: 0.75,
            ConfidenceBand.SUBSTANTIAL: 0.90,
        }[self]


@dataclass
class ConfidenceCeilingResult:
    band: ConfidenceBand
    numeric_ceiling: float
    raw_confidence: float
    clamped_confidence: float
    was_clamped: bool
    reasoning: list[str]

    def as_dict(self) -> dict:
        return {
            "band": self.band.value,
            "numeric_ceiling": self.numeric_ceiling,
            "raw_confidence": self.raw_confidence,
            "clamped_confidence": self.clamped_confidence,
            "was_clamped": self.was_clamped,
            "reasoning": self.reasoning,
        }


def _quality_score(quality: EvidenceQuality) -> float:
    return {
        EvidenceQuality.HIGH: 1.0,
        EvidenceQuality.MEDIUM: 0.6,
        EvidenceQuality.LOW: 0.3,
        EvidenceQuality.UNKNOWN: 0.4,
    }[quality]


def compute_confidence_band(
    matrix: EvidenceMatrix,
    has_field_validation: bool,  # GPR/ERT pick that colocates with this candidate
    environmental_confounders_controlled: bool,
    has_contradiction: bool,
    stability_score: float | None = None,
    stability_z_range: tuple[float, float] | None = None,
) -> tuple[ConfidenceBand, list[str]]:
    """
    Derives a ConfidenceBand from real, caller-supplied facts about a
    candidate's evidence. This is intentionally a small set of clear,
    explainable rules (not a black-box score) so every ceiling decision
    can be explained in plain language in the reasoning trace.

    stability_score (0-1, or None if the detection-stability check was
    never run for this candidate -- see module docstring) is checked
    immediately after has_contradiction, BEFORE has_field_validation or
    source count/quality are consulted -- a low score caps the ceiling
    unconditionally, the same way a contradiction does.
    """
    reasoning: list[str] = []

    independent_sources = matrix.independent_used_sources
    avg_quality = 0.0
    # Restricted to content evidence (excludes GPS, which is positional
    # metadata, not corroborating evidence -- see steward_evidence_matrix.py).
    used_entries = matrix.content_used_entries
    if used_entries:
        avg_quality = sum(_quality_score(e.quality) for e in used_entries) / len(used_entries)

    if independent_sources == 0:
        reasoning.append("No evidence categories were actually used for this candidate.")
        return ConfidenceBand.NO_DATA, reasoning

    if has_contradiction:
        reasoning.append(
            "Independent evidence contradicts the leading hypothesis; "
            "confidence is capped at LOW regardless of other factors."
        )
        return ConfidenceBand.LOW, reasoning

    if stability_score is not None and stability_score < STABILITY_LOW_CAP_THRESHOLD:
        range_note = ""
        if stability_z_range is not None:
            range_note = f" (z-score ranged {stability_z_range[0]:.2f} to {stability_z_range[1]:.2f} across the windows where it did reproduce)"
        reasoning.append(
            f"Detection stability check found this candidate reproduced in "
            f"only {stability_score:.0%} of independently re-fetched "
            f"sampling windows{range_note} -- the underlying elevation "
            f"anomaly itself is not reliably reproducible at this z-score "
            f"margin, independent of how many other sources corroborate "
            f"it. Confidence is capped at LOW regardless of other factors "
            f"(including field validation)."
        )
        return ConfidenceBand.LOW, reasoning

    if stability_score is not None and stability_score < STABILITY_MODERATE_CAP_THRESHOLD:
        reasoning.append(
            f"Detection stability check found this candidate reproduced in "
            f"only {stability_score:.0%} of independently re-fetched "
            f"sampling windows -- moderate sensitivity to exact AOI "
            f"placement. Confidence is capped at MODERATE regardless of "
            f"other factors (including field validation)."
        )
        return ConfidenceBand.MODERATE, reasoning

    if independent_sources == 1:
        reasoning.append(
            "Only a single independent evidence source was used; "
            "confidence cannot exceed MODERATE regardless of visual conviction."
        )
        band = ConfidenceBand.MODERATE if avg_quality >= 0.6 else ConfidenceBand.LOW
        reasoning.append(f"Average quality of that source ({avg_quality:.2f}) yields {band.value}.")
        return band, reasoning

    # independent_sources >= 2
    reasoning.append(f"{independent_sources} independent evidence sources were used.")

    if not environmental_confounders_controlled:
        reasoning.append(
            "Environmental confounders (vegetation/moisture/season/etc.) were not "
            "controlled for; ceiling held at MODERATE despite multiple sources."
        )
        return ConfidenceBand.MODERATE, reasoning

    reasoning.append("Environmental confounders were considered/controlled.")

    if has_field_validation:
        reasoning.append(
            "Field validation (GPR/ERT pick colocated with this candidate) is present; "
            "ceiling raised substantially."
        )
        return ConfidenceBand.SUBSTANTIAL, reasoning

    if avg_quality >= 0.8:
        reasoning.append(f"High average evidence quality ({avg_quality:.2f}).")
        return ConfidenceBand.HIGH, reasoning

    reasoning.append(f"Moderate/mixed average evidence quality ({avg_quality:.2f}).")
    return ConfidenceBand.MODERATE, reasoning


def govern_confidence(
    raw_confidence: float,
    matrix: EvidenceMatrix,
    has_field_validation: bool = False,
    environmental_confounders_controlled: bool = False,
    has_contradiction: bool = False,
    stability_score: float | None = None,
    stability_z_range: tuple[float, float] | None = None,
) -> ConfidenceCeilingResult:
    """
    Main entry point. Takes a raw confidence value (e.g. from the
    existing 4-perspective debate synthesis) and returns the
    Steward-governed result: the band, the numeric ceiling, and the
    actually-permitted (clamped) confidence value.

    This NEVER increases raw_confidence -- clamped_confidence is always
    min(raw_confidence, ceiling).

    stability_score/stability_z_range are optional (default None =
    "not tested for this candidate" -- see module docstring); passed
    straight through to compute_confidence_band().
    """
    raw_confidence = max(0.0, min(1.0, raw_confidence))

    band, reasoning = compute_confidence_band(
        matrix,
        has_field_validation,
        environmental_confounders_controlled,
        has_contradiction,
        stability_score=stability_score,
        stability_z_range=stability_z_range,
    )
    ceiling = band.numeric_ceiling
    clamped = min(raw_confidence, ceiling)
    was_clamped = clamped < raw_confidence

    if was_clamped:
        reasoning.append(
            f"Raw confidence {raw_confidence:.2f} exceeded the {band.value} ceiling "
            f"({ceiling:.2f}); clamped down to {clamped:.2f}."
        )
    else:
        reasoning.append(
            f"Raw confidence {raw_confidence:.2f} was already within the {band.value} "
            f"ceiling ({ceiling:.2f}); no clamping needed."
        )

    return ConfidenceCeilingResult(
        band=band,
        numeric_ceiling=ceiling,
        raw_confidence=raw_confidence,
        clamped_confidence=clamped,
        was_clamped=was_clamped,
        reasoning=reasoning,
    )
