"""
steward_evidence_states.py

Scientific Steward -- Stage 1 (Steward Foundation)

Defines the core vocabulary the rest of the Steward module is built on:

  * EvidenceLevel      -- the A-E evidence hierarchy (direct evidence
                          through conclusion). Nothing in the Steward
                          is allowed to silently jump from A to E.
  * PipelineStage      -- the escalating-certainty pipeline an anomaly
                          moves through: ANOMALY -> CANDIDATE ->
                          HYPOTHESIS -> TARGET -> VERIFIED_TARGET.
  * StatementTier       -- OBSERVED / INFERRED / HYPOTHESIZED / CONFIRMED,
                          used to keep generated wording honest about
                          how strong a claim actually is.
  * EvidenceStatement   -- a single piece of Steward-authored text, tagged
                          with its StatementTier so nothing downstream can
                          accidentally treat a hypothesis as a fact.

This module has no network or file-system dependency -- it is pure
Python data/logic, so it can be (and has been) fully unit-tested in a
sandbox with no real device or connectivity required.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EvidenceLevel(Enum):
    """The A-E evidence hierarchy from the Scientific Steward spec."""

    A_DIRECT = "A_DIRECT_EVIDENCE"
    B_DERIVED = "B_DERIVED_EVIDENCE"
    C_INTERPRETATION = "C_INTERPRETATION"
    D_HYPOTHESIS = "D_HYPOTHESIS"
    E_CONCLUSION = "E_CONCLUSION"

    @property
    def rank(self) -> int:
        """Ordinal position in the hierarchy, A=0 ... E=4."""
        order = {
            EvidenceLevel.A_DIRECT: 0,
            EvidenceLevel.B_DERIVED: 1,
            EvidenceLevel.C_INTERPRETATION: 2,
            EvidenceLevel.D_HYPOTHESIS: 3,
            EvidenceLevel.E_CONCLUSION: 4,
        }
        return order[self]

    def is_before(self, other: "EvidenceLevel") -> bool:
        return self.rank < other.rank


class PipelineStage(Enum):
    """The escalating-certainty pipeline the Steward controls transitions through."""

    ANOMALY = "ANOMALY"
    CANDIDATE = "CANDIDATE"
    HYPOTHESIS = "HYPOTHESIS"
    TARGET = "TARGET"
    VERIFIED_TARGET = "VERIFIED_TARGET"

    @property
    def rank(self) -> int:
        order = {
            PipelineStage.ANOMALY: 0,
            PipelineStage.CANDIDATE: 1,
            PipelineStage.HYPOTHESIS: 2,
            PipelineStage.TARGET: 3,
            PipelineStage.VERIFIED_TARGET: 4,
        }
        return order[self]


class StatementTier(Enum):
    """How strong a piece of Steward-authored wording is allowed to sound."""

    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    HYPOTHESIZED = "HYPOTHESIZED"
    CONFIRMED = "CONFIRMED"


@dataclass(frozen=True)
class EvidenceStatement:
    """
    A single piece of Steward-authored text, tagged with the strength of
    claim it is actually entitled to make.

    `text` should always be phrased consistently with `tier` -- e.g. an
    OBSERVED statement should never claim a confirmed conclusion, and a
    HYPOTHESIZED statement should never be phrased as fact. Callers that
    build these are responsible for phrasing; this class exists so every
    downstream consumer (UI, reasoning trace, reports) can tell at a
    glance how much epistemic weight a given sentence is allowed to carry.
    """

    tier: StatementTier
    text: str
    evidence_level: EvidenceLevel

    def as_dict(self) -> dict:
        return {
            "tier": self.tier.value,
            "text": self.text,
            "evidence_level": self.evidence_level.value,
        }


def validate_no_stage_skip(
    from_stage: PipelineStage, to_stage: PipelineStage
) -> tuple[bool, str]:
    """
    Returns (ok, reason). The Steward's core job is to prevent ARIYAN
    from silently promoting a raw anomaly straight to a verified target
    (or any stage skip) without the intervening reasoning steps existing.

    A jump of more than one stage at once is flagged as invalid -- this
    does not block the caller, it is meant to be checked by
    steward_engine.py and surfaced as a warning/failure if violated.
    """
    if to_stage.rank <= from_stage.rank:
        return False, (
            f"Stage did not advance ({from_stage.value} -> {to_stage.value}); "
            "not a promotion."
        )
    if to_stage.rank - from_stage.rank > 1:
        return False, (
            f"Illegal stage skip: {from_stage.value} -> {to_stage.value} "
            "skips at least one required intermediate stage."
        )
    return True, "ok"


def validate_no_evidence_level_skip(
    from_level: EvidenceLevel, to_level: EvidenceLevel
) -> tuple[bool, str]:
    """Same idea as validate_no_stage_skip, but for the A-E evidence hierarchy."""
    if to_level.rank <= from_level.rank:
        return False, (
            f"Evidence level did not advance ({from_level.value} -> {to_level.value})."
        )
    if to_level.rank - from_level.rank > 1:
        return False, (
            f"Illegal evidence-level skip: {from_level.value} -> {to_level.value} "
            "(e.g. going straight from Direct Evidence to Conclusion)."
        )
    return True, "ok"