"""
steward_reasoning_trace.py

Scientific Steward -- Stage 1 (Steward Foundation)

The structured per-candidate reasoning record:

  Evidence ID -> Observation -> Transformation -> Feature -> Interpretation
  -> Hypothesis -> Alternative hypotheses -> Contradictions -> Debate
  -> Judgment -> Confidence -> Recommended next action

This becomes part of an investigation's stored history, and is the
single object the Android UI / a future report generator should read
from to explain "why did the Steward conclude this."
"""

from __future__ import annotations

from dataclasses import dataclass, field

from steward_confidence_ceiling import ConfidenceCeilingResult
from steward_evidence_matrix import EvidenceMatrix
from steward_warnings import StewardWarning


@dataclass
class ReasoningTrace:
    candidate_id: str

    observation: str
    transformation_notes: list[str] = field(default_factory=list)
    feature_description: str = ""
    interpretation: str = ""
    hypothesis: str = ""
    alternative_hypotheses: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    debate_summary: str = ""

    evidence_matrix: EvidenceMatrix | None = None
    confidence_result: ConfidenceCeilingResult | None = None
    warnings: list[StewardWarning] = field(default_factory=list)

    recommended_next_action: str = ""

    def as_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "observation": self.observation,
            "transformation_notes": self.transformation_notes,
            "feature_description": self.feature_description,
            "interpretation": self.interpretation,
            "hypothesis": self.hypothesis,
            "alternative_hypotheses": self.alternative_hypotheses,
            "contradictions": self.contradictions,
            "debate_summary": self.debate_summary,
            "evidence_matrix": self.evidence_matrix.as_table() if self.evidence_matrix else [],
            "confidence": self.confidence_result.as_dict() if self.confidence_result else None,
            "warnings": [w.as_dict() for w in self.warnings],
            "recommended_next_action": self.recommended_next_action,
        }

    def summary_text(self) -> str:
        """
        A short, calm, non-sensational plain-language summary suitable
        for direct display -- deliberately conservative in wording per
        the Steward's personality guidance (never "we found a hidden
        chamber", always the honest evidence-supported phrasing).
        """
        lines = [f"Candidate {self.candidate_id}: {self.observation}"]
        if self.interpretation:
            lines.append(f"Interpretation: {self.interpretation}")
        if self.hypothesis:
            lines.append(f"Hypothesis (unconfirmed): {self.hypothesis}")
        if self.alternative_hypotheses:
            lines.append(
                "Alternative explanation(s): " + "; ".join(self.alternative_hypotheses)
            )
        if self.confidence_result:
            lines.append(
                f"Confidence: {self.confidence_result.band.value} "
                f"({self.confidence_result.clamped_confidence:.2f})"
            )
        if self.warnings:
            lines.append(f"{len(self.warnings)} scientific warning(s) raised.")
        if self.recommended_next_action:
            lines.append(f"Recommended next action: {self.recommended_next_action}")
        return "\n".join(lines)