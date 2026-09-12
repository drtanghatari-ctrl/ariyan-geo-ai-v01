"""
steward_confidence_ceiling.py

Scientific Steward -- Stage 1 (Steward Foundation)

The confidence governor: computes the MAXIMUM confidence ARIYAN is
scientifically permitted to report for a candidate, given what evidence
actually exists. This ceiling can only ever clamp confidence DOWN --
it never boosts a model's confidence, and it never lets a raw AI/debate
confidence value pass through unexamined.

"The AI's enthusiasm must never override scientific evidence."

DETECTION STABILITY EXTENSION (a prior session): real on-device
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

SECOND INDEPENDENT DEM CROSS-CHECK EXTENSION (ADDED THIS SESSION): a
`dem_cross_check_confirmed` (optional, tri-state: True/False/None --
see below) input describes whether this candidate's elevation anomaly
also shows up in a SECOND, genuinely independent global elevation
dataset (Copernicus GLO-30 / COP30 -- a different mission, agency, and
acquisition period than this project's primary SRTMGL1 DEM, verified
via OpenTopography's own dataset documentation to be genuinely
independent, unlike NASADEM which is explicitly a reprocessing of the
SAME underlying SRTM data -- see investigation_multi_mobile.py's own
DEM CROSS-CHECK section for the full reasoning), fetched once over the
AOI and nearest-matched against each primary DEM candidate.

PLACED AT THE SAME PRIORITY TIER AS stability_score, immediately
alongside it -- and for the SAME underlying reason: this, like
Detection Stability, questions whether the candidate's own elevation
anomaly is a reproducible physical feature at all, just via a
different perturbation (a second, independently-acquired dataset,
rather than a different sampling-window placement of the SAME
dataset). If the foundation itself doesn't reproduce in a second,
genuinely independent measurement of the same terrain, no amount of
field validation or other corroborating evidence rescues it -- exactly
Stability's own reasoning, applied to a different (and complementary)
kind of reproducibility check.

UNLIKE stability_score (a continuous 0-1 fraction across several offset
windows, needing two graduated thresholds), this is a single boolean
test against ONE second dataset, so it uses a simple tri-state
contract instead of a threshold:
  - dem_cross_check_confirmed=None (default): the check was never run
    for this candidate, or the second dataset's fetch itself failed
    this run (see investigation_multi_mobile.DemCrossCheckResult's own
    "error" field) -- means "not tested," applies NO cap, changes
    NOTHING about this function's existing behavior.
  - dem_cross_check_confirmed=True: the candidate's elevation anomaly
    WAS found in the second dataset too -- informative, but (like a
    passing stability_score) does not itself unlock any higher band;
    it simply does not trigger this cap.
  - dem_cross_check_confirmed=False: the check genuinely ran but did
    NOT find a matching anomaly in the second, independent dataset --
    caps the ceiling at LOW unconditionally, the same tier and same
    reasoning as a failing stability_score or a genuine contradiction.

Because this is an unconditional top-tier gate (never hidden behind a
downstream branch the way the Temporal Persistence cap is -- see that
extension's own docstring below for why THAT one needed an honestly-
derived `persistence_capped` flag), steward_warnings.py can safely
re-check dem_cross_check_confirmed directly, the exact same pattern
already used for stability_score's own WINDOW_SENSITIVITY_WARNING --
no derived "capped" field is needed on ConfidenceCeilingResult for this
extension.

EVIDENCE-INDEPENDENCE WEIGHTING EXTENSION (a prior session): the
source-count gate below previously used matrix.independent_used_sources
-- a flat, equally-weighted count of distinct used evidence categories.
This could not distinguish a candidate corroborated by NDVI+Thermal+
Optical (three sources, but all derived from the SAME Sentinel-2/
Landsat overpasses -- same acquisition, same atmospheric conditions,
same platform, genuinely correlated) from one corroborated by DEM+GPR+
ERT (three sources, three genuinely independent measurement
mechanisms). Both previously cleared the exact same ">= 2 sources"
gate identically. The gate now uses
matrix.effective_independent_sources (see steward_evidence_matrix.py's
own docstring for exactly how the weighting/discounting works) in its
place. Because every measurement-lineage group's contribution is
capped BELOW 2.0 (see that module's _GROUP_WEIGHT_CAP), reaching this
tier now genuinely requires sources from at least two independent
measurement mechanisms -- not just multiple correlated readings from
one. The DOWNSTREAM logic once inside that tier (environmental-
confounders gate, field-validation check, quality-based HIGH/MODERATE
split) is completely UNCHANGED -- only the gate's threshold source
changed, from raw count to weighted count. The raw count
(matrix.independent_used_sources) is still read and still reported in
the reasoning trace alongside the weighted value, so nothing about the
original evidence-category count disappears from the explanation --
it is now presented honestly alongside its weighted counterpart rather
than being the sole number quoted. SAR's own "radar" independence group
and the DEM Cross-Check's deliberate EXCLUSION from any independence
group (it is a robustness check on DEM, not a new measurement
mechanism -- see steward_evidence_matrix.py) both flow through this
gate unchanged, with zero code changes needed here.

TEMPORAL PERSISTENCE EXTENSION (a prior session): a `persistence_score`
(optional, see below) describes whether the remote-sensing signal(s)
that actually corroborated this candidate (NDVI/Thermal/Optical) hold
up across MULTIPLE real, independent satellite acquisitions over a
wider time window, rather than reflecting a single pooled snapshot --
see investigation_multi_mobile.py's TemporalPersistenceResult and
evidence_record.py's own EIGHTH EVIDENCE SLOT docstring for the full
background (queue item 2, decision 3 specifically: persistence is NOT
a new independent evidence source, it is a robustness check on the
EXISTING corroborating signals).

DELIBERATELY A SOFTER MECHANISM THAN DETECTION STABILITY (AND THE DEM
CROSS-CHECK ABOVE), NOT A COPY OF THEM -- this was the one open design
question left from decision 3 ("unconditional cap vs. softer signal, to
be designed when building steward_confidence_ceiling.py's side of
this"), resolved here as follows. Detection Stability and the DEM
Cross-Check both question whether the DEM candidate's own elevation
anomaly EXISTS as a reproducible physical feature at all -- if the
foundation itself isn't reproducible, nothing built on top of it
matters, which is why both cap unconditionally at the very top of
compute_confidence_band(), before field validation or source count are
even consulted. Temporal Persistence is a different kind of question:
it asks whether one of SEVERAL corroborating signals for a candidate
whose underlying DEM detection is otherwise sound stays consistent
over time. Critically, per this project's own documented honesty
principle (see investigation_multi_mobile.py's/evidence_record.py's
own TEMPORAL PERSISTENCE docstrings): real seasonal vegetation/thermal
cycles mean an inconsistent signal across months is NOT automatically
evidence AGAINST a buried feature -- it can be a genuine transient or
seasonal effect rather than an unreliable detection. Treating a low
persistence_score with the same unconditional LOW/MODERATE-crashing
severity as a genuine detection instability or a real contradiction
would therefore overstate what the evidence supports. Instead,
persistence_score is consulted ONLY at the point where the function
would otherwise return the TOP band, SUBSTANTIAL (i.e. inside the
has_field_validation branch, AFTER the contradiction/stability/DEM-
cross-check/source-count/confounder gates have already all passed) --
a weak persistence signal there caps that specific return at HIGH
instead of SUBSTANTIAL, with an honest reasoning line explaining why,
rather than reaching back to override any of the earlier, unconditional
gates. This is a narrower, more targeted mechanism than Stability's/the
DEM Cross-Check's, matching the narrower and more ambiguous nature of
what persistence actually tells us.

`persistence_score` is a single, ALREADY-REDUCED scalar (see
debate_mobile.py's own _compute_persistence_score_for_steward() for
exactly how investigation_multi_mobile.py's/evidence_record.py's raw
per-candidate ndvi/thermal/optical sub-dicts are reduced down to this
one value before it ever reaches this module) -- this module has no
knowledge of, and does not need, the underlying per-source breakdown.
persistence_score=None (the default, and the value for any candidate
where persistence checking never produced a usable signal -- no
corroborating source was NDVI/THERMAL/OPTICAL, or every corroborating
source's own persistence check was itself untestable/hard-failed for
this candidate) means "not applicable," not "weak" -- it applies NO
cap and changes NOTHING about this function's existing SUBSTANTIAL
branch. Only a candidate with a genuinely computed, genuinely low
persistence_score is affected.

REAL BUG FOUND AND FIXED VIA ON-DEVICE TESTING (a prior session):
steward_warnings.py's original TEMPORAL_PERSISTENCE_WARNING fired
whenever persistence_score alone was low, evaluated completely
independently of whether this function ever actually reached the
has_field_validation branch where persistence_score is consulted.
Since environmental_confounders_controlled is hardcoded False for the
whole of Stage 1 (see EVIDENCE-INDEPENDENCE WEIGHTING EXTENSION above
-- the exact same "invisible until Stage 2" situation),
compute_confidence_band() can currently NEVER reach the
has_field_validation branch at all, for ANY candidate, regardless of
GPR/ERT colocation -- confirmed by two real on-device runs, both
landing on MODERATE via the confounders gate. Yet the independent
warning check would still have fired "confidence has been capped
below SUBSTANTIAL" on a future 4-source-corroborated candidate with a
low persistence_score, which is FALSE in Stage 1: the ceiling was
never actually touched by persistence at all -- it was held at
MODERATE by the confounders gate for entirely unrelated reasons, the
same way CONFIDENCE_WARNING or DATA_GAP already correctly report only
what actually happened, never what would hypothetically happen under
different conditions.

Fixed by adding `persistence_capped` (below) to ConfidenceCeilingResult
and computing it honestly in govern_confidence() -- see that function's
own docstring for exactly how -- so steward_warnings.py can read the
ACTUAL observed effect off the result object (the same pattern
CONFIDENCE_WARNING already uses via ceiling_result.numeric_ceiling)
rather than re-deriving a hypothetical one from persistence_score in
isolation. The DEM Cross-Check extension above needed NO equivalent
derived flag -- see that extension's own docstring for why its
unconditional top-tier placement makes a direct re-check in
steward_warnings.py always safe, unlike persistence's branch-dependent
placement.
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

# Effective (evidence-independence-weighted) source count required to
# clear the "genuinely multiple independent sources" tier below. See
# steward_evidence_matrix.py's INDEPENDENCE_GROUPS/_GROUP_WEIGHT_CAP for
# why no single measurement-lineage group can ever reach this value
# alone -- clearing it requires sources from at least two distinct
# groups (e.g. DEM + any one other group, or two non-elevation groups
# together).
EFFECTIVE_SOURCES_MULTI_GROUP_THRESHOLD = 2.0

# Minimum fraction of temporally-testable acquisitions a candidate's
# corroborating remote-sensing signal must have been independently
# detected in to reach SUBSTANTIAL confidence. Deliberately a LOW bar
# (roughly one in three) -- see module docstring, TEMPORAL PERSISTENCE
# EXTENSION: this is meant to catch a genuinely rare/weak signal, not
# to demand near-perfect reproduction across every real acquisition,
# since real seasonal variation is expected and honest. A first real
# calibration, not a settled scientific constant, matching the same
# "expect this to be revisited" framing as the stability thresholds
# above -- there is not yet enough real multi-acquisition on-device
# data to calibrate this more precisely.
PERSISTENCE_SUBSTANTIAL_CAP_THRESHOLD = 1.0 / 3.0


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
    # ADDED a prior session (bug fix -- see module docstring, REAL BUG
    # FOUND AND FIXED VIA ON-DEVICE TESTING): True only when
    # persistence_score ACTUALLY capped this specific result at HIGH
    # instead of SUBSTANTIAL -- see govern_confidence() for exactly how
    # this is derived. Defaults to False so every pre-existing caller
    # (and every band other than the persistence-capped HIGH) is
    # completely unaffected.
    persistence_capped: bool = False

    def as_dict(self) -> dict:
        return {
            "band": self.band.value,
            "numeric_ceiling": self.numeric_ceiling,
            "raw_confidence": self.raw_confidence,
            "clamped_confidence": self.clamped_confidence,
            "was_clamped": self.was_clamped,
            "reasoning": self.reasoning,
            "persistence_capped": self.persistence_capped,
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
    dem_cross_check_confirmed: bool | None = None,
    persistence_score: float | None = None,
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

    dem_cross_check_confirmed (tri-state bool/None -- see module
    docstring, SECOND INDEPENDENT DEM CROSS-CHECK EXTENSION) is checked
    at the SAME priority tier as stability_score, immediately alongside
    it -- False caps the ceiling at LOW unconditionally, for the same
    underlying reason (an elevation anomaly that isn't reproducible in
    a second, genuinely independent measurement doesn't get rescued by
    other evidence). None means not tested; True means confirmed but
    does not itself unlock anything.

    The multi-source tier below is now gated on
    matrix.effective_independent_sources (evidence-independence-weighted),
    not the raw matrix.independent_used_sources count -- see module
    docstring, EVIDENCE-INDEPENDENCE WEIGHTING EXTENSION, for why.

    persistence_score (0-1, or None if not applicable -- see module
    docstring, TEMPORAL PERSISTENCE EXTENSION) is consulted ONLY inside
    the has_field_validation/SUBSTANTIAL branch, deliberately AFTER
    every other gate above it has already passed -- a low score there
    caps that specific return at HIGH instead of SUBSTANTIAL. Unlike
    stability_score/dem_cross_check_confirmed, it never affects any
    other branch or band.
    """
    reasoning: list[str] = []

    raw_sources = matrix.independent_used_sources
    effective_sources = matrix.effective_independent_sources
    avg_quality = 0.0
    # Restricted to content evidence (excludes GPS, which is positional
    # metadata, not corroborating evidence -- see steward_evidence_matrix.py).
    used_entries = matrix.content_used_entries
    if used_entries:
        avg_quality = sum(_quality_score(e.quality) for e in used_entries) / len(used_entries)

    if effective_sources == 0.0:
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

    if dem_cross_check_confirmed is False:
        reasoning.append(
            "This candidate's elevation anomaly was checked against a "
            "second, genuinely independent global elevation dataset "
            "(Copernicus GLO-30 / COP30 -- a different mission, agency, "
            "and acquisition period than the primary DEM) and did NOT "
            "reproduce there. Like a failed detection-stability check, "
            "this questions whether the underlying elevation anomaly is "
            "a real, reproducible feature at all -- confidence is capped "
            "at LOW regardless of other factors (including field "
            "validation)."
        )
        return ConfidenceBand.LOW, reasoning

    if effective_sources < EFFECTIVE_SOURCES_MULTI_GROUP_THRESHOLD:
        reasoning.append(
            f"Evidence-independence-weighted source count is "
            f"{effective_sources:.2f} (from {raw_sources} raw evidence "
            f"categor{'y' if raw_sources == 1 else 'ies'} used) -- below "
            f"the threshold for genuinely independent multi-source "
            f"corroboration. This can happen with a single source, or "
            f"with multiple sources that all share the same measurement "
            f"lineage (e.g. NDVI/Thermal/Optical, all derived from the "
            f"same satellite overpasses) rather than genuinely distinct "
            f"measurement mechanisms. Confidence cannot exceed MODERATE "
            f"regardless of visual conviction."
        )
        band = ConfidenceBand.MODERATE if avg_quality >= 0.6 else ConfidenceBand.LOW
        reasoning.append(f"Average quality of the evidence used ({avg_quality:.2f}) yields {band.value}.")
        return band, reasoning

    # effective_sources >= EFFECTIVE_SOURCES_MULTI_GROUP_THRESHOLD -- this
    # genuinely spans at least two independent measurement mechanisms
    # (see steward_evidence_matrix.py's INDEPENDENCE_GROUPS/
    # _GROUP_WEIGHT_CAP docstrings for why a single group alone can
    # never reach this threshold).
    reasoning.append(
        f"{raw_sources} raw evidence source(s) were used, weighted for "
        f"measurement-lineage independence to an effective count of "
        f"{effective_sources:.2f} -- this genuinely spans multiple "
        f"independent measurement mechanisms, not just multiple "
        f"correlated readings from the same underlying source."
    )

    if dem_cross_check_confirmed is True:
        reasoning.append(
            "This candidate's elevation anomaly was also confirmed in the "
            "second, independent COP30 dataset -- additional, informative "
            "confirmation of the underlying DEM detection, though it does "
            "not by itself raise the confidence band beyond what the "
            "gates below determine."
        )

    if not environmental_confounders_controlled:
        reasoning.append(
            "Environmental confounders (vegetation/moisture/season/etc.) were not "
            "controlled for; ceiling held at MODERATE despite multiple sources."
        )
        return ConfidenceBand.MODERATE, reasoning

    reasoning.append("Environmental confounders were considered/controlled.")

    if has_field_validation:
        # TEMPORAL PERSISTENCE EXTENSION (a prior session -- see module
        # docstring for the full reasoning on why this is consulted
        # ONLY here, deliberately after every earlier gate has already
        # passed, and why it caps at HIGH rather than crashing to
        # LOW/MODERATE the way stability_score/dem_cross_check_confirmed
        # above do).
        if persistence_score is not None and persistence_score < PERSISTENCE_SUBSTANTIAL_CAP_THRESHOLD:
            reasoning.append(
                f"Field validation (GPR/ERT pick colocated with this "
                f"candidate) is present, which would otherwise support "
                f"SUBSTANTIAL confidence, but the corroborating remote-"
                f"sensing signal for this candidate was only "
                f"independently detected in {persistence_score:.0%} of "
                f"temporally-tested real acquisitions -- this may "
                f"reflect a genuine transient or seasonal signal rather "
                f"than an unreliable detection (real vegetation/thermal "
                f"cycles are honest, expected variation, not "
                f"automatically evidence against a buried feature), but "
                f"confidence is capped at HIGH rather than SUBSTANTIAL "
                f"until more temporal evidence accumulates."
            )
            return ConfidenceBand.HIGH, reasoning
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
    dem_cross_check_confirmed: bool | None = None,
    persistence_score: float | None = None,
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
    straight through to compute_confidence_band(). dem_cross_check_confirmed
    is likewise optional (default None = "not tested" -- see module
    docstring, SECOND INDEPENDENT DEM CROSS-CHECK EXTENSION); also
    passed straight through, and needs no derived "capped" flag on the
    result (unlike persistence_score below) since it is an unconditional
    top-tier gate, never hidden behind a downstream branch.
    persistence_score is likewise optional (default None = "not
    applicable" -- see module docstring, TEMPORAL PERSISTENCE
    EXTENSION); also passed straight through.

    ALSO computes ConfidenceCeilingResult.persistence_capped here (bug
    fix, see module docstring) -- honestly, from what actually happened,
    rather than re-testing persistence_score in isolation the way the
    original (buggy) warning check did. Reliable because: whenever
    has_field_validation is True, compute_confidence_band()'s
    has_field_validation branch is the ONLY code path that can ever
    return ConfidenceBand.HIGH -- it always returns either SUBSTANTIAL
    or (only via the persistence cap inside that same branch) HIGH,
    and always returns before ever reaching the separate quality-based
    HIGH check further down the function. So "has_field_validation is
    True AND band is HIGH" uniquely identifies "this HIGH came from the
    persistence cap" -- there is no other way to reach that combination.
    A HIGH reached via the quality>=0.8 branch instead always has
    has_field_validation False, so it can never be mistaken for this.
    """
    raw_confidence = max(0.0, min(1.0, raw_confidence))

    band, reasoning = compute_confidence_band(
        matrix,
        has_field_validation,
        environmental_confounders_controlled,
        has_contradiction,
        stability_score=stability_score,
        stability_z_range=stability_z_range,
        dem_cross_check_confirmed=dem_cross_check_confirmed,
        persistence_score=persistence_score,
    )
    persistence_capped = (
        has_field_validation
        and band == ConfidenceBand.HIGH
        and persistence_score is not None
        and persistence_score < PERSISTENCE_SUBSTANTIAL_CAP_THRESHOLD
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
        persistence_capped=persistence_capped,
    )
