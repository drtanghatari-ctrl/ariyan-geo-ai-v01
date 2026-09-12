"""
evidence_record.py -- Minimal, honest evidence/investigation record.

This intentionally does NOT replicate the hash-chained "custody
governance" pattern found elsewhere in the ARIYAN codebase (append-only
ledgers validating ledgers of ledgers). That pattern produces a large
amount of code that verifies its own bookkeeping without ever
strengthening the underlying science. What actually matters for
scientific defensibility is much simpler and is implemented here:

  - every evidence item states its source and whether it's real or synthetic
  - every derived product states what it was derived from and by what method
  - every anomaly is reported with its supporting numbers, not a verdict
  - the record is a single, inspectable JSON document -- not a tool a
    human must trust without reading

FOURTH EVIDENCE SLOT (Thermal, a prior session): mirrors the existing
`second_evidence`/`second_anomalies` pattern exactly (a single aggregate
wrapper appended to `evidence`, plus a per-candidate detail list kept
OUT of `anomalies[]` and reported in its own `fourth_evidence_detail`
field) rather than the `third_evidence` (GPR) pattern, because Thermal
-- like NDVI -- is a per-DEM-candidate corroborating check, not a
single site-anchored field-verification note. `third_evidence` (GPR)
is unchanged.

FIFTH EVIDENCE SLOT (Optical, a prior session): follows the EXACT same
shape as `fourth_evidence`/`fourth_anomalies` (itself modeled on
`second_evidence`/`second_anomalies`) -- a single aggregate wrapper
object appended to `evidence`, plus a per-candidate detail list kept
OUT of `anomalies[]` and reported in its own `fifth_evidence_detail`
field. Optical (real Sentinel-2 visible-band brightness / soilmark
check, see optical_source_mobile.py) is, like NDVI and Thermal, a
per-DEM-candidate corroborating check -- not a single site-anchored
note like GPR -- so it gets its own aggregate-plus-detail slot rather
than being folded into GPR's third_evidence pattern.

SIXTH EVIDENCE SLOT (ERT, a prior session): unlike Thermal/Optical, ERT
(electrical resistivity tomography, see ert_source_mobile.py) is
architecturally like GPR -- a SINGLE, site-anchored field-verification
reading (a human-entered resistivity value at a known depth, classified
against fixed reference ranges), not a per-DEM-candidate corroborating
check. It therefore follows the `third_evidence`/`third_evidence_type`
pattern (single record appended to `evidence`, reported in its own
`sixth_evidence_detail` field, no per-candidate anomalies list), NOT the
fourth/fifth pattern, even though it is numbered "sixth" simply because
it is the sixth evidence slot added to this record chronologically.

SEVENTH EVIDENCE SLOT (Detection Stability, a prior session): real
on-device testing (18+ live investigations, see project notes) found
that detect_anomalies() can genuinely disagree with itself when re-run
against a differently-centered AOI window -- candidates close to the
detection threshold were found to frequently fail to reproduce, while
candidates well above it were consistently robust. investigation_
multi_mobile.py now AUTOMATICALLY re-fetches+re-detects around any DEM
candidate whose |z| falls within a margin of dem_zscore_threshold (see
that module's _run_stability_check()), for at most a small, bounded
number of candidates per run (network-cost control). This follows the
FOURTH/FIFTH pattern, NOT third/sixth (GPR/ERT) -- like Thermal/
Optical, it is fundamentally a list of per-candidate results (one
StabilityResult per auto-tested candidate, 0 to a few per run), kept
OUT of `anomalies[]` for the same reason fourth/fifth are (a
StabilityResult's schema -- stability_score/n_windows_fetched/z_min/
z_max -- has nothing in common with AnomalyCandidate), and reported in
its own `seventh_evidence_detail` field. UNLIKE Thermal/Optical, it is
NOT run for every DEM candidate -- only borderline ones qualify, so
`seventh_evidence_detail` will often be empty or short even when many
DEM candidates exist. `seventh_evidence` is only appended to `evidence`
at all when at least one candidate was actually tested this run (an
investigation where nothing qualified carries no stability evidence
item, rather than a misleading "0 candidates tested" entry every time).
CRITICALLY: Stability gets NO `derived_products` entry, unlike fourth/
fifth -- it isn't a corroborating evidence source at all (a stable
detection isn't NEW evidence for a hypothesis, it's a statement about
how much the EXISTING DEM evidence can be trusted). See
steward_confidence_ceiling.py's own docstring for why it feeds the
confidence ceiling directly instead of correlation().

EIGHTH EVIDENCE SLOT ADDED A PRIOR SESSION (Temporal Persistence): checks
whether NDVI/Thermal/Optical's core-vs-halo anomaly (see the second/
fourth/fifth evidence items above) reproduces across MULTIPLE real,
independent satellite acquisitions in a wider time window, rather than
reflecting a single pooled snapshot -- see ndvi_source_mobile.py's,
thermal_source_mobile.py's, and optical_source_mobile.py's own
fetch_X_temporal_persistence_check() functions for the real per-source
mechanics (all three now built and sandbox-verified).

THREE DESIGN DECISIONS BEHIND THIS SLOT'S SHAPE, all made and confirmed
before this code was written (see the project's own queue-item-2 design
notes for the full reasoning):

  1. Runs automatically for ALL DEM candidates -- the SAME unconditional-
     per-candidate philosophy as Thermal/Optical, NOT Stability's
     bounded borderline-only subset. `eighth_anomalies` is therefore
     expected to be non-empty whenever this run has at least one DEM
     candidate, once investigation_multi_mobile.py's wiring calls all
     three per-source checks for every candidate.

  2. ONE COMBINED slot covering all three sources together, NOT three
     separate evidence slots. Each item in `eighth_anomalies` is a
     single per-candidate result (conceptually a TemporalPersistenceResult
     -- see investigation_multi_mobile.py for its exact dataclass, not
     defined here) with `ndvi`/`thermal`/`optical` sub-dict fields (each
     None on a hard per-source failure, e.g. a source that was never
     attempted or hit a true fetch error), rather than three flat
     parallel lists the way second/fourth/fifth's per-source data would
     otherwise imply. Consequently `eighth_evidence_type` is NOT a
     caller-supplied parameter the way fourth/fifth/seventh's
     evidence_type is -- it's a single FIXED literal string,
     "TEMPORAL_PERSISTENCE", tagged onto each detail item below, since
     the actual per-source split already lives INSIDE each item's own
     ndvi/thermal/optical sub-fields rather than in a variable top-level
     type name.

  3. NOT COUNTED as a new independent evidence source -- mirrors
     Stability's own precedent from the section above EXACTLY, for the
     same underlying reason: persistence is a robustness check ON
     NDVI/Thermal/Optical's EXISTING signals, not a new measurement
     mechanism. Feeding it into correlation()/supporting_sources would
     double-count against the evidence-independence weighting already
     closed in steward_evidence_matrix.py (queue item 1). So, like
     Stability: NO `derived_products` entry is added for this slot, it
     is never folded into `correlation_results`/`supporting_sources`,
     and it feeds Scientific Steward as a confidence-ceiling input
     instead.

`eighth_evidence` (optional, like seventh_evidence) is an aggregate
wrapper object describing the method/window/thresholds used this run
(e.g. days_back, per-source thresholds) -- appended to `evidence` only
when `eighth_anomalies` is non-empty, mirroring Stability's own
"no misleading zero-candidates entry on every run" precedent, even
though decision 1 above means this will in practice almost always be
non-empty once at least one DEM candidate exists.

NINTH EVIDENCE SLOT ADDED THIS SESSION (SAR): real Sentinel-1 backscatter
core/halo check (sar_source_mobile.fetch_sar_core_halo_check(), see that
module's own docstring for the full real-literature-grounded reasoning).
UNLIKE Detection Stability and Temporal Persistence, SAR IS a genuine new
independent per-DEM-candidate corroborating evidence source -- it follows
the FOURTH/FIFTH (Thermal/Optical) pattern exactly, not the
seventh/eighth pattern: a single aggregate wrapper appended to `evidence`
(describing the method used this run), plus a per-candidate detail list
kept OUT of `anomalies[]` (a SAR result's schema -- vv/vh sub-dicts, each
with their own core_mean/halo_mean/z_score -- has nothing in common with
AnomalyCandidate) and reported in its own `ninth_evidence_detail` field.
It DOES get a `derived_products` entry (mirroring fourth/fifth, unlike
seventh/eighth), and it DOES participate in correlation()/
supporting_sources (added in investigation_multi_mobile.py's
_build_correlated_candidates()) -- SAR is architecturally a genuinely
independent physical measurement (active radar, not passive optical/
thermal), so it earns its own place in steward_evidence_matrix.py's
INDEPENDENCE_GROUPS rather than being folded into the existing
optical_family group.

Each ninth_evidence_detail item combines BOTH polarizations (vv/vh
sub-dicts, each None if that polarization had no usable data for this
candidate this run) into ONE per-candidate result, following the same
"combine sub-measurements into one item" convention eighth's ndvi/
thermal/optical sub-dicts already established -- but unlike eighth,
ninth_evidence_type IS a caller-supplied parameter here (always "SAR" in
practice), matching third/fourth/fifth/sixth/seventh's convention, since
there is only one evidence_type to name (SAR), not three combined ones.

TENTH EVIDENCE SLOT ADDED THIS SESSION (Second Independent DEM
Cross-Check): checks whether a DEM candidate detected in the PRIMARY
elevation dataset (SRTMGL1, this project's existing default) also shows
up as an anomaly in a SECOND, genuinely independent elevation dataset
(Copernicus GLO-30 / "COP30" via OpenTopography) fetched once over the
same AOI -- see investigation_multi_mobile.py's own DEM CROSS-CHECK
section for the full real mechanics.

COP30 was chosen deliberately over the more casually-obvious NASADEM
after checking OpenTopography's own real dataset documentation: NASADEM
is explicitly a reprocessing of the SAME underlying SRTM radar
acquisitions this project's primary DEM (SRTMGL1) already uses --
cross-checking against it would not be a genuinely independent
confirmation, just the same radar data run through a different
pipeline. COP30 is derived from the Copernicus TanDEM-X mission (a
different agency, a different satellite pair, a different acquisition
period), so a candidate that reproduces in BOTH is real, independent
elevation-value corroboration in a way NASADEM could not honestly
provide.

UNLIKE the ninth slot (SAR) and like the seventh/eighth slots
(Detection Stability / Temporal Persistence), this is explicitly NOT
counted as a new independent EvidenceCategory: a second DEM dataset
measures the SAME physical quantity (elevation) via a different
processing pipeline, not a genuinely different physical measurement
mechanism the way radar/thermal/optical/vegetation-index are relative
to each other. Counting it as independent evidence would let two
correlated measurements of the same underlying terrain masquerade as
two sources. So, like Stability and Temporal Persistence: NO
`derived_products` entry, NEVER folded into `correlation_results`/
`supporting_sources`, and it feeds Scientific Steward's confidence
ceiling directly instead -- as an UNCONDITIONAL cap (mirroring
Stability's own priority tier, not Temporal Persistence's softer one):
a candidate whose elevation anomaly does not reproduce in a second,
genuinely independent DEM source is not rescued by any amount of other
corroborating evidence, exactly like a candidate that fails Detection
Stability's window-placement check.

Runs UNCONDITIONALLY for every DEM candidate this run (ONE second-DEM
fetch covering the whole AOI, reused for every candidate via nearest-
match -- much cheaper than Detection Stability's per-candidate
multi-offset re-fetch, since there is only one second dataset to check,
not several offset windows), mirroring Thermal's/Optical's/SAR's own
no-toggle, every-candidate philosophy for WHEN it runs, while following
Stability's/Temporal-Persistence's philosophy for HOW it counts
(robustness check, not new evidence). `tenth_evidence` (the aggregate
wrapper describing the second dataset and method) is only appended to
`evidence` when `tenth_anomalies` is non-empty, mirroring seventh/
eighth's own "no misleading zero-candidates entry" precedent.

CONFIDENCE-STATEMENT FIX (a prior session): previously, the "co-located
anomalies in X + Y" phrase listed every evidence_type present in
`evidence[]`, regardless of whether that source actually corroborated
anything -- meaning GPR's evidence_type was already being folded into
that phrase even when GPR never participates in correlation at all.
This was harmless-but-imprecise with DEM/NDVI/GPR; adding a genuine
third per-candidate corroborating source (Thermal, and then a fourth --
Optical) would make it actively wrong (claiming a source co-located
candidates it never touched). Fixed to derive the list from the sources
that actually appear in `supporting_sources` for CORROBORATED candidates
specifically -- this logic needed no further change to accommodate
Optical, ERT, Stability, Temporal Persistence, SAR, or the DEM
Cross-Check: SAR's own evidence_type only ever appears in
supporting_sources when it genuinely corroborated a candidate (see
investigation_multi_mobile.py's _build_correlated_candidates()), so
this phrase stays correct automatically; the DEM Cross-Check never
appears in supporting_sources at all (see this module's own TENTH
EVIDENCE SLOT docstring section above), so it was never a risk here to
begin with.

CONFIDENCE-STATEMENT WORDING FIX (a prior session -- REAL on-device
readability bug, reported by the user): the CORROBORATED branch of the
confidence statement previously appended a trailing sentence --
"{N} additional single-source candidate(s) remain LOW confidence." --
UNCONDITIONALLY, even when N was 0. For a run with exactly one
candidate that was itself fully CORROBORATED (n_corroborated == 1,
len(correlation_results) == 1), N computes to 0, producing genuinely
confusing text: "...confidence should be treated as MODERATE to HIGH
pending field verification. 0 additional single-source candidate(s)
remain LOW confidence." Nothing here was factually wrong (0 candidates
really do remain LOW -- the sentence was vacuously true), but placing
the words "LOW confidence" directly after "MODERATE to HIGH" for what
reads as the same candidate is a real clarity failure, not just
verbosity -- a user skimming this text has no way to tell at a glance
that the second sentence refers to a *different*, empty population
rather than walking back the first sentence's own verdict. Fixed by
only appending that sentence when there is a nonzero count of
additional single-source candidates to actually report; a fully-
corroborated single-candidate run (or any run where every detected
candidate ends up CORROBORATED) now ends cleanly after the "MODERATE
to HIGH" sentence, with nothing following it to misread. No change to
the underlying n_corroborated/CORROBORATED-status computation itself,
and no change to the SINGLE_SOURCE-only (n_corroborated == 0) branch
below, which was never affected by this issue.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from coordinate import AreaOfInterest
from dem_source import DEM
from anomaly_detection_mobile import AnomalyCandidate


@dataclass
class InvestigationRecord:
    generated_at: str
    aoi: dict
    evidence: list[dict]
    derived_products: list[dict]
    anomalies: list[dict]
    limitations: list[str]
    confidence_statement: str
    correlation: list[dict] = field(default_factory=list)
    second_evidence_detail: list[dict] = field(default_factory=list)
    third_evidence_detail: list[dict] = field(default_factory=list)
    fourth_evidence_detail: list[dict] = field(default_factory=list)
    fifth_evidence_detail: list[dict] = field(default_factory=list)
    sixth_evidence_detail: list[dict] = field(default_factory=list)
    seventh_evidence_detail: list[dict] = field(default_factory=list)
    eighth_evidence_detail: list[dict] = field(default_factory=list)
    ninth_evidence_detail: list[dict] = field(default_factory=list)
    tenth_evidence_detail: list[dict] = field(default_factory=list)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), indent=indent, default=str)


def build_investigation_record(
    aoi: AreaOfInterest,
    dem: DEM,
    anomalies: list[AnomalyCandidate],
    zscore_threshold: float,
    kernel_sigma_cells: float,
    second_evidence: Any = None,
    second_anomalies: list | None = None,
    second_evidence_type: str | None = None,
    correlation_results: list | None = None,
    second_anomalies_are_candidates: bool = True,
    third_evidence: Any = None,
    third_evidence_type: str | None = None,
    fourth_evidence: Any = None,
    fourth_anomalies: list | None = None,
    fourth_evidence_type: str | None = None,
    fifth_evidence: Any = None,
    fifth_anomalies: list | None = None,
    fifth_evidence_type: str | None = None,
    sixth_evidence: Any = None,
    sixth_evidence_type: str | None = None,
    seventh_evidence: Any = None,
    seventh_anomalies: list | None = None,
    seventh_evidence_type: str | None = None,
    eighth_evidence: Any = None,
    eighth_anomalies: list | None = None,
    ninth_evidence: Any = None,
    ninth_anomalies: list | None = None,
    ninth_evidence_type: str | None = None,
    tenth_evidence: Any = None,
    tenth_anomalies: list | None = None,
    tenth_evidence_type: str | None = None,
) -> InvestigationRecord:
    """Build the InvestigationRecord JSON payload.

    second_anomalies_are_candidates controls how `second_anomalies` is
    merged into the `anomalies` list:

    - True (default): `second_anomalies` are AnomalyCandidate instances
      with the SAME schema as the DEM `anomalies` (e.g. NDVI raster
      candidates from detect_raster_anomalies in the offline-fallback
      path). Safe to concatenate into a single uniform `anomalies` list.

    - False: `second_anomalies` are a structurally DIFFERENT record type
      (e.g. NdviCoreHaloResult from the real-NDVI per-candidate check --
      core_mean/halo_mean/z_score fields, no area_cells/peak_zscore/
      polarity). These are kept OUT of `anomalies` and reported in the
      separate `second_evidence_detail` field instead.

    third_evidence (optional) is a further, structurally-independent,
    SINGLE (not per-candidate) evidence source appended to `evidence`
    and reported in its own `third_evidence_detail` field (never merged
    into `anomalies`). third_evidence must implement
    .as_evidence_record() the same way every other evidence source does.

    fourth_evidence/fourth_anomalies (optional) follow the EXACT same
    shape as second_evidence/second_anomalies (a single aggregate
    wrapper object appended to `evidence`, plus a per-candidate detail
    list) -- for Thermal's real per-DEM-candidate core/halo check.
    Always kept out of `anomalies[]` and reported in
    `fourth_evidence_detail` instead.

    fifth_evidence/fifth_anomalies (optional) follow the IDENTICAL shape
    as fourth_evidence/fourth_anomalies -- for Optical's real
    per-DEM-candidate visible-brightness core/halo check. Always kept
    out of `anomalies[]` for the same reason as fourth_evidence, and
    reported in `fifth_evidence_detail` instead.

    sixth_evidence (optional) is ERT's real, SINGLE, site-anchored (not
    per-candidate) evidence source, appended to `evidence` and reported
    in its own `sixth_evidence_detail` field -- follows the
    third_evidence (GPR) pattern, NOT the fourth/fifth (Thermal/Optical)
    pattern.

    seventh_evidence/seventh_anomalies (optional) are Detection
    Stability's real per-candidate re-fetch/re-detect check results
    (StabilityResult from investigation_multi_mobile.py, schema:
    lat/lon/target_zscore/stability_score/n_windows_fetched/
    n_windows_detected/z_min/z_max/offset_errors -- nothing in common
    with AnomalyCandidate). Follows the fourth/fifth pattern (aggregate
    wrapper + per-item detail list, kept out of `anomalies[]`) with one
    difference: unlike Thermal/Optical, this is NOT run for every DEM
    candidate -- only the borderline subset that qualified this run, so
    `seventh_anomalies` may be an empty list even when other evidence
    slots are fully populated. `seventh_evidence` (the aggregate
    wrapper describing the method/margin/offsets used) is only appended
    to `evidence` when `seventh_anomalies` is non-empty -- an
    investigation where no candidate qualified for the automatic check
    carries no stability evidence item at all, rather than a misleading
    zero-candidates entry appearing on every single run. Stability gets
    NO `derived_products` entry -- it isn't a corroborating evidence
    source, it's a statement about how much the EXISTING DEM evidence
    can be trusted (see steward_confidence_ceiling.py's own docstring).

    eighth_evidence/eighth_anomalies (optional) are Temporal
    Persistence's real per-candidate results -- see this module's own
    EIGHTH EVIDENCE SLOT docstring section above for the three design
    decisions behind this slot's shape. Structurally like seventh
    (aggregate wrapper + per-item detail list, no derived_products
    entry, never folded into correlation()), but with two real
    differences from seventh: (a) runs unconditionally for ALL DEM
    candidates rather than a bounded borderline subset; (b) each item
    combines all three sources (NDVI/Thermal/Optical) via ndvi/thermal/
    optical sub-dict fields rather than being source-specific, so
    `eighth_evidence_type` is not a caller-supplied parameter here --
    it's the single fixed literal "TEMPORAL_PERSISTENCE".

    ninth_evidence/ninth_anomalies (optional, ADDED THIS SESSION) are
    SAR's real per-candidate backscatter core/halo results -- see this
    module's own NINTH EVIDENCE SLOT docstring section above. UNLIKE
    seventh/eighth, this DOES get a derived_products entry and DOES
    participate in correlation()/supporting_sources -- SAR is a
    genuine new independent evidence source, architecturally following
    the fourth/fifth (Thermal/Optical) pattern: a single aggregate
    wrapper appended to `evidence`, plus a per-candidate detail list
    (each item combining vv/vh sub-dicts) kept out of `anomalies[]` and
    reported in `ninth_evidence_detail`. ninth_evidence_type IS a
    caller-supplied parameter (unlike eighth's fixed literal), since
    there's only one evidence_type here ("SAR"), not three combined
    sources sharing one slot.

    tenth_evidence/tenth_anomalies (optional, ADDED THIS SESSION) are
    the Second Independent DEM Cross-Check's real per-candidate results
    -- see this module's own TENTH EVIDENCE SLOT docstring section
    above. Structurally like seventh/eighth (aggregate wrapper +
    per-item detail list, NO derived_products entry, never folded into
    correlation()) -- a second DEM dataset is a robustness check on the
    EXISTING DEM evidence, not a new independent measurement mechanism,
    so it is deliberately NOT treated like ninth (SAR). tenth_evidence_type
    IS a caller-supplied parameter (always "DEM_CROSS_CHECK" in
    practice), matching seventh's own convention.
    """
    evidence = [dem.as_evidence_record()]
    derived_products = [{
        "product": "local relief residual + z-score anomaly map",
        "derived_from": dem.source,
        "method": "Gaussian regional-trend removal + z-score thresholding",
        "kernel_sigma_cells": kernel_sigma_cells,
        "zscore_threshold": zscore_threshold,
    }]
    anomaly_dicts = [asdict(a) for a in anomalies]
    second_evidence_detail: list[dict] = []
    third_evidence_detail: list[dict] = []
    fourth_evidence_detail: list[dict] = []
    fifth_evidence_detail: list[dict] = []
    sixth_evidence_detail: list[dict] = []
    seventh_evidence_detail: list[dict] = []
    eighth_evidence_detail: list[dict] = []
    ninth_evidence_detail: list[dict] = []
    tenth_evidence_detail: list[dict] = []

    limitations = [
        "Anomalies reflect statistical deviation from local terrain/spectral "
        "trend only. No archaeological, geological, or causal interpretation is "
        "implied or should be inferred from this record alone.",
        "On terrain with no real anomaly present, this detector still flags "
        "roughly 1 candidate per run at the z>=2.5 threshold used here -- "
        "this is expected statistical behavior, not a defect.",
    ]
    if dem.synthetic:
        limitations.insert(0, (
            "THIS RUN USED SYNTHETIC TERRAIN, NOT A REAL DEM. Every "
            "'anomaly' below is a statistical description of the synthetic "
            "surface, not a claim about any real location."
        ))

    has_second_source = second_evidence is not None
    if not has_second_source:
        limitations.insert(0 if not dem.synthetic else 1, (
            "Single evidence source (DEM only). No independent corroborating "
            "evidence (imagery, GPR, historical maps) was available in this run."
        ))
    else:
        evidence.append(second_evidence.as_evidence_record())
        if getattr(second_evidence, "synthetic", False):
            limitations.insert(0, (
                f"THIS RUN USED SYNTHETIC {second_evidence_type}, NOT REAL "
                f"IMAGERY. Every '{second_evidence_type}' anomaly below is a "
                f"statistical description of the synthetic surface, not a "
                f"claim about any real location."
            ))
        derived_products.append({
            "product": f"{second_evidence_type} residual + z-score anomaly map",
            "derived_from": second_evidence.source,
            "method": "Gaussian regional-trend removal + z-score thresholding",
            "kernel_sigma_cells": kernel_sigma_cells,
            "zscore_threshold": zscore_threshold,
        })

        if second_anomalies_are_candidates:
            anomaly_dicts.extend([
                {**asdict(a), "evidence_type": second_evidence_type}
                for a in (second_anomalies or [])
            ])
            for a in anomaly_dicts[:len(anomalies)]:
                a.setdefault("evidence_type", "DEM")
        else:
            for a in anomaly_dicts:
                a.setdefault("evidence_type", "DEM")
            second_evidence_detail = [
                {**asdict(a), "evidence_type": second_evidence_type}
                for a in (second_anomalies or [])
            ]

    if third_evidence is not None:
        third_record = third_evidence.as_evidence_record()
        evidence.append(third_record)
        limitations.append(
            f"{third_evidence_type} evidence in this run is a single, "
            f"site-anchored field-verification check (not an independent "
            f"full-area scan like DEM/NDVI) and uses a documented "
            f"approximate reference range rather than a site-calibrated "
            f"measurement -- see the evidence item's own record above for "
            f"the real numbers and uncertainty range."
        )
        third_evidence_detail = [third_record]

    if fourth_evidence is not None:
        evidence.append(fourth_evidence.as_evidence_record())
        if getattr(fourth_evidence, "synthetic", False):
            limitations.insert(0, (
                f"THIS RUN USED SYNTHETIC {fourth_evidence_type}, NOT REAL "
                f"DATA. Every '{fourth_evidence_type}' result below is a "
                f"statistical description of the synthetic surface, not a "
                f"claim about any real location."
            ))
        derived_products.append({
            "product": f"{fourth_evidence_type} residual + z-score anomaly map",
            "derived_from": fourth_evidence.source,
            "method": "Gaussian regional-trend removal + z-score thresholding",
            "kernel_sigma_cells": kernel_sigma_cells,
            "zscore_threshold": zscore_threshold,
        })
        fourth_evidence_detail = [
            {**asdict(a), "evidence_type": fourth_evidence_type}
            for a in (fourth_anomalies or [])
        ]

    if fifth_evidence is not None:
        evidence.append(fifth_evidence.as_evidence_record())
        if getattr(fifth_evidence, "synthetic", False):
            limitations.insert(0, (
                f"THIS RUN USED SYNTHETIC {fifth_evidence_type}, NOT REAL "
                f"DATA. Every '{fifth_evidence_type}' result below is a "
                f"statistical description of the synthetic surface, not a "
                f"claim about any real location."
            ))
        derived_products.append({
            "product": f"{fifth_evidence_type} residual + z-score anomaly map",
            "derived_from": fifth_evidence.source,
            "method": "Gaussian regional-trend removal + z-score thresholding",
            "kernel_sigma_cells": kernel_sigma_cells,
            "zscore_threshold": zscore_threshold,
        })
        fifth_evidence_detail = [
            {**asdict(a), "evidence_type": fifth_evidence_type}
            for a in (fifth_anomalies or [])
        ]

    if sixth_evidence is not None:
        sixth_record = sixth_evidence.as_evidence_record()
        evidence.append(sixth_record)
        limitations.append(
            f"{sixth_evidence_type} evidence in this run is a single, "
            f"site-anchored field-verification check (not an independent "
            f"full-area scan like DEM/NDVI) and classifies a single "
            f"human-entered resistivity reading against documented "
            f"reference ranges (which meaningfully overlap between "
            f"several real materials) rather than a site-calibrated "
            f"inversion -- see the evidence item's own record above for "
            f"the real value, depth, and matching reference band(s)."
        )
        sixth_evidence_detail = [sixth_record]

    # Stability (seventh) is only appended when at least one candidate
    # actually qualified/was tested this run -- an investigation where
    # nothing was borderline enough to trigger the automatic check
    # carries no stability evidence item at all (see this function's
    # own docstring).
    if seventh_anomalies:
        if seventh_evidence is not None:
            evidence.append(seventh_evidence.as_evidence_record())
        limitations.append(
            f"Detection stability evidence in this run automatically "
            f"re-fetched and re-detected around {len(seventh_anomalies)} "
            f"DEM candidate(s) whose z-score was close to the detection "
            f"threshold, to check whether their detection is robust to "
            f"exact AOI sampling-window placement or an artifact of this "
            f"run's specific DEM fetch -- see the evidence item's own "
            f"record above and each candidate's own stability_score for "
            f"the real per-candidate results. Candidates well above "
            f"threshold are not automatically tested; their stability is "
            f"simply unknown/untested, not assumed stable."
        )
        seventh_evidence_detail = [
            {**asdict(a), "evidence_type": seventh_evidence_type}
            for a in seventh_anomalies
        ]

    # Temporal Persistence (eighth) -- see this module's own EIGHTH
    # EVIDENCE SLOT docstring section for the three design decisions
    # behind this shape. Like Stability, only appended when there is at
    # least one real item to report. Per decision 3: NO derived_products
    # entry (not a new measurement source), and eighth_evidence_detail
    # is NEVER read by correlation() or folded into supporting_sources
    # -- it feeds Scientific Steward as a confidence-ceiling input only.
    if eighth_anomalies:
        if eighth_evidence is not None:
            evidence.append(eighth_evidence.as_evidence_record())
        limitations.append(
            "Temporal persistence evidence in this run checked whether "
            "each DEM candidate's NDVI/Thermal/Optical anomaly signal (see "
            "the corresponding evidence item(s) above) reproduces across "
            "multiple independent real satellite acquisitions in a wider "
            "time window, rather than reflecting a single snapshot -- see "
            "the evidence item's own record above and each candidate's own "
            "ndvi/thermal/optical persistence_score for the real "
            "per-candidate results. A candidate whose signal could not be "
            "tested this run (e.g. persistent regional cloud cover, or a "
            "source that was never attempted for that candidate) has an "
            "honest untested/None score for that source, not an "
            "assumed-unstable one. Real seasonal vegetation/thermal cycles "
            "mean an inconsistent signal across months is not automatically "
            "evidence AGAINST a buried feature -- this measures "
            "reproducibility, not causation."
        )
        eighth_evidence_detail = [
            {**asdict(a), "evidence_type": "TEMPORAL_PERSISTENCE"}
            for a in eighth_anomalies
        ]

    # SAR (ninth, ADDED THIS SESSION) -- see this module's own NINTH
    # EVIDENCE SLOT docstring section. UNLIKE seventh/eighth, this is a
    # genuine new independent evidence source: gets a derived_products
    # entry, and (via investigation_multi_mobile.py's
    # _build_correlated_candidates()) participates in correlation() and
    # can appear in supporting_sources. Runs unconditionally for every
    # DEM candidate, mirroring Thermal's/Optical's own no-toggle
    # philosophy, so ninth_evidence_detail is expected to be populated
    # whenever this run has at least one DEM candidate and SAR was
    # attempted at all.
    if ninth_evidence is not None:
        evidence.append(ninth_evidence.as_evidence_record())
        if getattr(ninth_evidence, "synthetic", False):
            limitations.insert(0, (
                f"THIS RUN USED SYNTHETIC {ninth_evidence_type}, NOT REAL "
                f"DATA. Every '{ninth_evidence_type}' result below is a "
                f"statistical description of the synthetic surface, not a "
                f"claim about any real location."
            ))
        derived_products.append({
            "product": f"{ninth_evidence_type} residual + z-score anomaly map",
            "derived_from": ninth_evidence.source,
            "method": "Gaussian regional-trend removal + z-score thresholding",
            "kernel_sigma_cells": kernel_sigma_cells,
            "zscore_threshold": zscore_threshold,
        })
        limitations.append(
            "Real SAR (Sentinel-1) evidence in this run flags a core/halo "
            "backscatter anomaly in EITHER direction (brighter OR darker "
            "than surroundings) on VV and VH polarizations separately, "
            "never assuming a single direction the way NDVI does -- "
            "published research on Sentinel-1 over buried archaeological "
            "features shows both signatures occur, driven by a mix of "
            "soil moisture and surface roughness that can push either "
            "way. This measures single-date backscatter statistics only; "
            "it does not include the coherence/interferometric analysis "
            "some published SAR archaeology methods also use, and should "
            "be read as informative, not as strong evidence on its own."
        )
        ninth_evidence_detail = [
            {**asdict(a), "evidence_type": ninth_evidence_type}
            for a in (ninth_anomalies or [])
        ]

    # Second Independent DEM Cross-Check (tenth, ADDED THIS SESSION) --
    # see this module's own TENTH EVIDENCE SLOT docstring section.
    # Mirrors Stability/Temporal Persistence: only appended when there
    # is at least one real item to report, NO derived_products entry
    # (not a new measurement mechanism -- see docstring for why COP30
    # vs. SRTMGL1 is still "the same physical quantity, a different
    # pipeline" rather than a genuinely independent evidence source the
    # way SAR is), and tenth_evidence_detail is NEVER read by
    # correlation() or folded into supporting_sources -- it feeds
    # Scientific Steward's confidence ceiling as an UNCONDITIONAL cap
    # input, mirroring Detection Stability's own priority tier.
    if tenth_anomalies:
        if tenth_evidence is not None:
            evidence.append(tenth_evidence.as_evidence_record())
        limitations.append(
            "Second independent DEM cross-check evidence in this run "
            "compared each DEM candidate against a genuinely independent "
            "second elevation dataset (Copernicus GLO-30 / COP30 -- a "
            "different mission, agency, and acquisition period than this "
            "project's primary SRTMGL1 DEM, not merely a different "
            "processing of the same underlying radar data) to check "
            "whether the same elevation anomaly reproduces there too -- "
            "see the evidence item's own record above and each "
            "candidate's own cross_dem_confirmed/cross_dem_peak_zscore "
            "for the real per-candidate results. A candidate this could "
            "not be tested for (e.g. the second dataset has no coverage "
            "at this location) has an honest untested state, not an "
            "assumed-unconfirmed one."
        )
        tenth_evidence_detail = [
            {**asdict(a), "evidence_type": tenth_evidence_type}
            for a in tenth_anomalies
        ]

    correlation_dicts = []
    if correlation_results:
        for r in correlation_results:
            correlation_dicts.append({
                "lat": r.lat,
                "lon": r.lon,
                "status": r.status,
                "supporting_sources": r.supporting_sources,
                "distance_between_peaks_m": r.distance_between_peaks_m,
                "note": r.combined_confidence_note,
            })
        n_corroborated = sum(1 for r in correlation_results if r.status == "CORROBORATED")
        if n_corroborated > 0:
            corroborating_sources: list[str] = []
            for r in correlation_results:
                if r.status != "CORROBORATED":
                    continue
                for s in r.supporting_sources:
                    if s not in corroborating_sources:
                        corroborating_sources.append(s)
            confidence = (
                f"{n_corroborated} candidate(s) CORROBORATED by independent evidence "
                f"sources (co-located anomalies in {' + '.join(corroborating_sources)}). "
                f"This is genuine independent corroboration; confidence should be "
                f"treated as MODERATE to HIGH pending field verification."
            )
            # CONFIDENCE-STATEMENT WORDING FIX (a prior session -- see module
            # docstring): only append the "N additional single-source
            # candidate(s) remain LOW confidence" sentence when there is
            # actually a nonzero count to report.
            n_single_source_remaining = len(correlation_results) - n_corroborated
            if n_single_source_remaining > 0:
                confidence += (
                    f" {n_single_source_remaining} additional single-source "
                    f"candidate(s) remain LOW confidence."
                )
        else:
            confidence = (
                f"{len(correlation_results)} candidate(s) detected across "
                f"{len(evidence)} evidence source(s), but none were corroborated "
                f"by more than one independent source. Confidence remains LOW."
            )
    elif not anomalies:
        confidence = "No anomalies met the detection threshold. Absence of a detected anomaly is not evidence of absence -- it may reflect resolution, threshold, or evidence limitations above."
    else:
        top = anomalies[0]
        confidence = (
            f"{len(anomalies)} candidate(s) detected. Strongest: "
            f"|z|={abs(top.peak_zscore):.2f}, area={top.area_cells} cells, "
            f"amplitude={top.peak_residual_m:.2f}m. This reflects DEM-only "
            f"statistical evidence; confidence should be treated as LOW to "
            f"MODERATE until corroborated by an independent evidence source."
        )

    record_kwargs = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        aoi={
            "center_lat": aoi.center.lat,
            "center_lon": aoi.center.lon,
            "radius_m": aoi.radius_m,
            "grid_size": aoi.grid_size,
            "cell_size_m": aoi.cell_size_m,
        },
        evidence=evidence,
        derived_products=derived_products,
        anomalies=anomaly_dicts,
        limitations=limitations,
        confidence_statement=confidence,
    )
    if correlation_dicts:
        record_kwargs["correlation"] = correlation_dicts
    if second_evidence_detail:
        record_kwargs["second_evidence_detail"] = second_evidence_detail
    if third_evidence_detail:
        record_kwargs["third_evidence_detail"] = third_evidence_detail
    if fourth_evidence_detail:
        record_kwargs["fourth_evidence_detail"] = fourth_evidence_detail
    if fifth_evidence_detail:
        record_kwargs["fifth_evidence_detail"] = fifth_evidence_detail
    if sixth_evidence_detail:
        record_kwargs["sixth_evidence_detail"] = sixth_evidence_detail
    if seventh_evidence_detail:
        record_kwargs["seventh_evidence_detail"] = seventh_evidence_detail
    if eighth_evidence_detail:
        record_kwargs["eighth_evidence_detail"] = eighth_evidence_detail
    if ninth_evidence_detail:
        record_kwargs["ninth_evidence_detail"] = ninth_evidence_detail
    if tenth_evidence_detail:
        record_kwargs["tenth_evidence_detail"] = tenth_evidence_detail

    return InvestigationRecord(**record_kwargs)
