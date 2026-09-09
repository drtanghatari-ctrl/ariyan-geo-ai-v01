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

SEVENTH EVIDENCE SLOT ADDED THIS SESSION (Detection Stability): real
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
Optical, ERT, or Stability: none of these three ever participates in
correlation() or appears in supporting_sources, so this phrase
correctly never mentions any of them.

CONFIDENCE-STATEMENT WORDING FIX (this session -- REAL on-device
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

    seventh_evidence/seventh_anomalies (optional, ADDED THIS SESSION) are
    Detection Stability's real per-candidate re-fetch/re-detect check
    results (StabilityResult from investigation_multi_mobile.py, schema:
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
    zero-candidates entry appearing on every single run.
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
            # CONFIDENCE-STATEMENT WORDING FIX (this session -- see module
            # docstring): only append the "N additional single-source
            # candidate(s) remain LOW confidence" sentence when there is
            # actually a nonzero count to report. Previously this ran
            # unconditionally, producing "...MODERATE to HIGH... 0
            # additional single-source candidate(s) remain LOW confidence"
            # for a run where every detected candidate was already
            # CORROBORATED -- factually vacuous (0 candidates really do
            # remain LOW), but read like a self-contradiction placing "LOW
            # confidence" immediately after "MODERATE to HIGH" for what
            # looked like the same candidate.
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

    return InvestigationRecord(**record_kwargs)
