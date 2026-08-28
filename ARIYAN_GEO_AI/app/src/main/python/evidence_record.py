"""
evidence_record.py — Minimal, honest evidence/investigation record.

This intentionally does NOT replicate the hash-chained "custody
governance" pattern found elsewhere in the ARIYAN codebase (append-only
ledgers validating ledgers of ledgers). That pattern produces a large
amount of code that verifies its own bookkeeping without ever
strengthening the underlying science. What actually matters for
scientific defensibility is much simpler and is implemented here:

  - every evidence item states its source and whether it's real or synthetic
  - every derived product states what it was derived from and by what method
  - every anomaly is reported with its supporting numbers, not a verdict
  - the record is a single, inspectable JSON document — not a tool a
    human must trust without reading
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
) -> InvestigationRecord:
    """Build the InvestigationRecord JSON payload.

    second_anomalies_are_candidates controls how `second_anomalies` is
    merged into the `anomalies` list:

    - True (default): `second_anomalies` are AnomalyCandidate instances
      with the SAME schema as the DEM `anomalies` (e.g. NDVI raster
      candidates from detect_raster_anomalies in the synthetic-NDVI
      path). Safe to concatenate into a single uniform `anomalies` list.

    - False: `second_anomalies` are a structurally DIFFERENT record type
      (e.g. NdviCoreHaloResult from the real-NDVI per-candidate check --
      core_mean/halo_mean/z_score fields, no area_cells/peak_zscore/
      polarity). These are kept OUT of `anomalies` and reported in the
      separate `second_evidence_detail` field instead. Mixing them into
      `anomalies` previously caused downstream consumers (including
      MainActivity.kt's renderResult(), which reads every anomalies[]
      entry assuming AnomalyCandidate fields) to silently default
      missing fields to fake values -- area=0, |z|=NaN, polarity="" --
      which looked exactly like a degenerate/empty DEM candidate but
      was actually a real NDVI check result being read through the
      wrong schema.
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

    limitations = [
        "Anomalies reflect statistical deviation from local terrain/spectral "
        "trend only. No archaeological, geological, or causal interpretation is "
        "implied or should be inferred from this record alone.",
        "On terrain with no real anomaly present, this detector still flags "
        "roughly 1 candidate per run at the z>=2.5 threshold used here — "
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
            # second_anomalies really are AnomalyCandidate instances
            # (same schema as the DEM anomalies) -- safe to merge into
            # one uniform list.
            anomaly_dicts.extend([
                {**asdict(a), "evidence_type": second_evidence_type}
                for a in (second_anomalies or [])
            ])
            for a in anomaly_dicts[:len(anomalies)]:
                a.setdefault("evidence_type", "DEM")
        else:
            # second_anomalies have a DIFFERENT schema (e.g. the real-NDVI
            # per-candidate core/halo check). Keep them out of `anomalies`
            # so nothing downstream defaults missing AnomalyCandidate
            # fields to fake 0 / NaN / "" values -- report them in their
            # own field instead.
            for a in anomaly_dicts:
                a.setdefault("evidence_type", "DEM")
            second_evidence_detail = [
                {**asdict(a), "evidence_type": second_evidence_type}
                for a in (second_anomalies or [])
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
            confidence = (
                f"{n_corroborated} candidate(s) CORROBORATED by independent evidence "
                f"sources (co-located anomalies in {' + '.join(evidence[i]['evidence_type'] for i in range(len(evidence)))}). "
                f"This is genuine independent corroboration; confidence should be "
                f"treated as MODERATE to HIGH pending field verification. "
                f"{len(correlation_results) - n_corroborated} additional single-source "
                f"candidate(s) remain LOW confidence."
            )
        else:
            confidence = (
                f"{len(correlation_results)} candidate(s) detected across "
                f"{len(evidence)} evidence source(s), but none were corroborated "
                f"by more than one independent source. Confidence remains LOW."
            )
    elif not anomalies:
        confidence = "No anomalies met the detection threshold. Absence of a detected anomaly is not evidence of absence — it may reflect resolution, threshold, or evidence limitations above."
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

    return InvestigationRecord(**record_kwargs)
