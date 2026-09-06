"""
steward_warnings.py

Scientific Steward -- Stage 1 (Steward Foundation)

Generates the Steward's scientific alerts. These are meant to be shown
directly in the Android UI (not buried in logs), so each warning is a
short, plain-language, non-dramatic sentence plus a machine-readable
kind for the UI to badge/sort by.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from steward_confidence_ceiling import ConfidenceCeilingResult
from steward_evidence_matrix import EvidenceMatrix


class WarningKind(Enum):
    EVIDENCE = "EVIDENCE_WARNING"
    RESOLUTION = "RESOLUTION_WARNING"
    CONFOUNDER = "CONFOUNDER_WARNING"
    PROVENANCE = "PROVENANCE_WARNING"
    CONFIDENCE = "CONFIDENCE_WARNING"
    CONTRADICTION = "CONTRADICTION_WARNING"
    DATA_GAP = "DATA_GAP"


@dataclass(frozen=True)
class StewardWarning:
    kind: WarningKind
    message: str

    def as_dict(self) -> dict:
        return {"kind": self.kind.value, "message": self.message}


def generate_warnings(
    matrix: EvidenceMatrix,
    ceiling_result: ConfidenceCeilingResult,
    requested_precision_m: float | None,
    effective_resolution_m: float | None,
    provenance_verified: bool,
    confounder_notes: list[str] | None = None,
    has_contradiction: bool = False,
    raw_model_confidence: float | None = None,
) -> list[StewardWarning]:
    """
    Builds the applicable subset of the 7 Steward warning types from
    real, caller-supplied facts about a candidate. Never invents a
    warning that isn't actually supported by the inputs -- if nothing
    applies, this returns an empty list.
    """
    warnings: list[StewardWarning] = []
    confounder_notes = confounder_notes or []

    # EVIDENCE_WARNING: single-dataset support
    if matrix.independent_used_sources == 1:
        warnings.append(
            StewardWarning(
                WarningKind.EVIDENCE,
                "Candidate is supported primarily by a single dataset.",
            )
        )

    # RESOLUTION_WARNING: requested precision exceeds what the data can support
    if (
        requested_precision_m is not None
        and effective_resolution_m is not None
        and requested_precision_m < effective_resolution_m
    ):
        warnings.append(
            StewardWarning(
                WarningKind.RESOLUTION,
                f"Requested interpretation precision ({requested_precision_m:g} m) "
                f"exceeds the effective spatial resolution of available evidence "
                f"({effective_resolution_m:g} m).",
            )
        )

    # CONFOUNDER_WARNING: one per real confounder note supplied
    for note in confounder_notes:
        warnings.append(
            StewardWarning(WarningKind.CONFOUNDER, f"Anomaly correlates with {note}.")
        )

    # PROVENANCE_WARNING
    if not provenance_verified:
        warnings.append(
            StewardWarning(
                WarningKind.PROVENANCE,
                "Evidence lineage cannot currently be verified.",
            )
        )

    # CONFIDENCE_WARNING: raw model confidence exceeded the Steward's ceiling
    if (
        raw_model_confidence is not None
        and raw_model_confidence > ceiling_result.numeric_ceiling
    ):
        warnings.append(
            StewardWarning(
                WarningKind.CONFIDENCE,
                "Model confidence exceeds the scientifically supported "
                f"confidence ceiling ({ceiling_result.band.value}, "
                f"{ceiling_result.numeric_ceiling:.2f}).",
            )
        )

    # CONTRADICTION_WARNING
    if has_contradiction:
        warnings.append(
            StewardWarning(
                WarningKind.CONTRADICTION,
                "Independent evidence does not support the current hypothesis.",
            )
        )

    # DATA_GAP: any missing category at all is surfaced as at least an informational gap
    missing = matrix.missing_categories()
    if missing:
        names = ", ".join(m.value for m in missing)
        warnings.append(
            StewardWarning(
                WarningKind.DATA_GAP,
                f"Critical validation dataset(s) unavailable: {names}.",
            )
        )

    return warnings