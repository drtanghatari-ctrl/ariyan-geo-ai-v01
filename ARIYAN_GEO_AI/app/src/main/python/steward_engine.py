"""
steward_engine.py

Scientific Steward -- Stage 1 (Steward Foundation)

Top-level orchestrator. This is the single entry point the rest of the
app will eventually call (from investigation_multi_mobile.py, once
Stage 1 is confirmed and wired in) to get a full Steward evaluation for
one candidate: evidence matrix, confidence ceiling, warnings, and a
structured reasoning trace, plus honest OBSERVED/HYPOTHESIZED wording.

STAGE 1 SCOPE (per the Scientific Steward spec's 5-stage build plan):
  - evidence states (steward_evidence_states.py)
  - observation/interpretation separation (steward_evidence_states.py)
  - confidence ceiling (steward_confidence_ceiling.py)
  - data completeness awareness (steward_evidence_matrix.py)
  - scientific warnings (steward_warnings.py)
  - investigation reasoning record (steward_reasoning_trace.py)
  - human override recording (this file)

OUT OF SCOPE for Stage 1 (later stages per the spec):
  - SHA-256 evidence validation / provenance ledger / custody (Stage 2)
  - Team A/Team B/Judge debate engine (Stage 3 -- distinct from and
    layered on top of the existing 4-perspective debate engine)
  - Candidate scoring / validation-priority ranking (Stage 4)
  - Adaptive "what evidence would reduce uncertainty most" reasoning (Stage 5)

This module is intentionally self-contained (new files only, zero
changes to any existing file) so it can be sandbox-tested in full
before anything in MainActivity.kt, investigation_multi_mobile.py, or
debate_engine.py is touched -- same discipline used for every other
module in this project.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from steward_confidence_ceiling import govern_confidence
from steward_evidence_matrix import EvidenceMatrix, build_evidence_matrix
from steward_evidence_states import PipelineStage
from steward_reasoning_trace import ReasoningTrace
from steward_warnings import generate_warnings


@dataclass
class HumanOverrideRecord:
    """
    Records that a human investigator's decision differed from the
    Steward's recommendation, per the spec's Human Override requirement:
    original evidence, the Steward's reasoning, the human's decision, and
    the stated reason must ALL be preserved -- never just the final call.
    """

    steward_recommendation: str
    human_decision: str
    override_reason: str

    def as_dict(self) -> dict:
        return {
            "steward_recommendation": self.steward_recommendation,
            "human_decision": self.human_decision,
            "override_reason": self.override_reason,
            "note": "AI recommendation != human decision",
        }


@dataclass
class StewardReport:
    candidate_id: str
    pipeline_stage: PipelineStage
    reasoning_trace: ReasoningTrace
    human_override: HumanOverrideRecord | None = None

    def as_dict(self) -> dict:
        d = {
            "candidate_id": self.candidate_id,
            "pipeline_stage": self.pipeline_stage.value,
            "reasoning_trace": self.reasoning_trace.as_dict(),
        }
        if self.human_override is not None:
            d["human_override"] = self.human_override.as_dict()
        return d

    def summary_text(self) -> str:
        return self.reasoning_trace.summary_text()


def evaluate_candidate(
    candidate_id: str,
    observation: str,
    *,
    has_gps: bool,
    has_dem: bool,
    has_optical: bool,
    has_ndvi: bool,
    has_gpr: bool,
    has_thermal: bool = False,
    has_lidar: bool = False,
    has_ert: bool = False,
    quality_hints: dict | None = None,
    used_hints: dict | None = None,
    limitation_hints: dict | None = None,
    raw_debate_confidence: float = 0.0,
    has_field_validation: bool = False,
    environmental_confounders_controlled: bool = False,
    has_contradiction: bool = False,
    interpretation: str = "",
    hypothesis: str = "",
    alternative_hypotheses: list[str] | None = None,
    contradictions: list[str] | None = None,
    debate_summary: str = "",
    requested_precision_m: float | None = None,
    effective_resolution_m: float | None = None,
    provenance_verified: bool = True,
    confounder_notes: list[str] | None = None,
    recommended_next_action: str = "",
) -> StewardReport:
    """
    Runs a full Stage-1 Steward evaluation for one candidate from real,
    caller-supplied facts. Nothing here fabricates data -- every input
    describes something the investigation actually has (or explicitly
    does not have). Returns a StewardReport combining the evidence
    matrix, the governed confidence, the applicable warnings, and a
    structured reasoning trace.

    `raw_debate_confidence` is the existing 4-perspective debate
    engine's synthesis confidence (0-1) -- this function NEVER
    increases it, only ever clamps it down to what the evidence
    actually supports.
    """
    alternative_hypotheses = alternative_hypotheses or []
    contradictions = contradictions or []
    confounder_notes = confounder_notes or []

    matrix: EvidenceMatrix = build_evidence_matrix(
        has_gps=has_gps,
        has_dem=has_dem,
        has_optical=has_optical,
        has_ndvi=has_ndvi,
        has_gpr=has_gpr,
        has_thermal=has_thermal,
        has_lidar=has_lidar,
        has_ert=has_ert,
        quality_hints=quality_hints,
        used_hints=used_hints,
        limitation_hints=limitation_hints,
    )

    confidence_result = govern_confidence(
        raw_confidence=raw_debate_confidence,
        matrix=matrix,
        has_field_validation=has_field_validation,
        environmental_confounders_controlled=environmental_confounders_controlled,
        has_contradiction=has_contradiction,
    )

    warnings = generate_warnings(
        matrix=matrix,
        ceiling_result=confidence_result,
        requested_precision_m=requested_precision_m,
        effective_resolution_m=effective_resolution_m,
        provenance_verified=provenance_verified,
        confounder_notes=confounder_notes,
        has_contradiction=has_contradiction,
        raw_model_confidence=raw_debate_confidence,
    )

    trace = ReasoningTrace(
        candidate_id=candidate_id,
        observation=observation,
        interpretation=interpretation,
        hypothesis=hypothesis,
        alternative_hypotheses=alternative_hypotheses,
        contradictions=contradictions,
        debate_summary=debate_summary,
        evidence_matrix=matrix,
        confidence_result=confidence_result,
        warnings=warnings,
        recommended_next_action=recommended_next_action
        or _default_next_action(confidence_result.band, matrix),
    )

    # Determine pipeline stage honestly from what evidence/confidence actually support.
    stage = _infer_pipeline_stage(matrix, confidence_result, has_field_validation)

    return StewardReport(candidate_id=candidate_id, pipeline_stage=stage, reasoning_trace=trace)


def record_human_override(
    report: StewardReport, human_decision: str, override_reason: str
) -> StewardReport:
    """
    Attaches a HumanOverrideRecord to an existing StewardReport when the
    investigator's decision differs from what the Steward recommended.
    Returns a new StewardReport (does not mutate the original in place,
    so the pre-override report remains available for audit).
    """
    override = HumanOverrideRecord(
        steward_recommendation=report.summary_text(),
        human_decision=human_decision,
        override_reason=override_reason,
    )
    return StewardReport(
        candidate_id=report.candidate_id,
        pipeline_stage=report.pipeline_stage,
        reasoning_trace=report.reasoning_trace,
        human_override=override,
    )


def _default_next_action(band, matrix: EvidenceMatrix) -> str:
    from steward_confidence_ceiling import ConfidenceBand

    missing = matrix.missing_categories()
    if band == ConfidenceBand.NO_DATA:
        return "Insufficient evidence to recommend any action."
    if band in (ConfidenceBand.LOW, ConfidenceBand.MODERATE) and missing:
        names = ", ".join(m.value for m in missing)
        return f"Consider gathering additional evidence ({names}) before field validation."
    if band in (ConfidenceBand.HIGH, ConfidenceBand.SUBSTANTIAL):
        return "Candidate may justify field validation (e.g. GPR/ERT) if not already performed."
    return "Continue monitoring; no immediate action recommended."


def _infer_pipeline_stage(matrix: EvidenceMatrix, confidence_result, has_field_validation: bool) -> PipelineStage:
    from steward_confidence_ceiling import ConfidenceBand

    if matrix.independent_used_sources == 0:
        return PipelineStage.ANOMALY
    if confidence_result.band == ConfidenceBand.NO_DATA:
        return PipelineStage.ANOMALY
    if has_field_validation and confidence_result.band == ConfidenceBand.SUBSTANTIAL:
        return PipelineStage.VERIFIED_TARGET
    if confidence_result.band in (ConfidenceBand.HIGH, ConfidenceBand.SUBSTANTIAL):
        return PipelineStage.TARGET
    if confidence_result.band == ConfidenceBand.MODERATE:
        return PipelineStage.HYPOTHESIS
    return PipelineStage.CANDIDATE