"""
correlation.py — Multi-Source Correlation Engine

This is the module the vertical slice's own README named as the
priority-2 next increment, and the reason it matters: a single DEM
anomaly is weak evidence (the desktop pipeline's own limitations text
says so). What actually strengthens a candidate is INDEPENDENT
corroboration — a different evidence source, measuring a different
physical quantity, showing an anomaly at the same location for reasons
that aren't explained by the same underlying cause.

This module does exactly one honest thing: given anomaly lists from two
independent rasters (e.g. DEM local-relief anomalies and NDVI
vegetation-stress anomalies), it checks spatial co-location within a
distance tolerance and classifies each candidate as CORROBORATED
(supported by 2+ independent sources) or SINGLE_SOURCE (only one).
It does not claim to know *why* they co-locate — that interpretation
step belongs to a human investigator or a future debate/steward layer,
not to this statistical correlation step.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from anomaly_detection_mobile import AnomalyCandidate
from coordinate import GeoPoint, haversine_distance_m


@dataclass
class CorrelatedCandidate:
    lat: float
    lon: float
    status: str  # "CORROBORATED" or "SINGLE_SOURCE"
    supporting_sources: list[str]
    source_candidates: dict  # evidence_type -> AnomalyCandidate
    distance_between_peaks_m: float | None
    combined_confidence_note: str


def correlate_anomalies(
    candidates_by_source: dict,
    aoi_center: GeoPoint,
    colocation_distance_m: float,
) -> list[CorrelatedCandidate]:
    """Cross-reference anomaly candidates from N independent evidence
    sources. candidates_by_source: {"DEM": [AnomalyCandidate, ...],
    "NDVI": [AnomalyCandidate, ...], ...}.

    colocation_distance_m: how close two candidates from different
    sources must be (in meters) to count as the same physical location.
    This should scale with the coarsest source's resolution — cells
    from a 10m source and a 30m source will never land on the exact
    same lat/lon, so an appropriately generous tolerance is part of an
    honest correlation check, not a way to manufacture agreement.

    Returns one CorrelatedCandidate per DISTINCT location across all
    sources — a candidate present in only one source is still returned,
    correctly labeled SINGLE_SOURCE, not dropped. Silently dropping
    unconfirmed candidates would hide exactly the information a
    "no hallucinated archaeology" system must keep visible.
    """
    # Flatten to (source_name, candidate) pairs.
    flat: list[tuple] = []
    for source_name, cands in candidates_by_source.items():
        for c in cands:
            flat.append((source_name, c))

    used = [False] * len(flat)
    results: list[CorrelatedCandidate] = []

    for i, (source_i, cand_i) in enumerate(flat):
        if used[i]:
            continue
        group = {source_i: cand_i}
        used[i] = True
        point_i = GeoPoint(cand_i.lat, cand_i.lon)

        best_pair_distance = None

        for j in range(i + 1, len(flat)):
            if used[j]:
                continue
            source_j, cand_j = flat[j]
            if source_j in group:
                continue  # only one candidate per source per group
            point_j = GeoPoint(cand_j.lat, cand_j.lon)
            dist = haversine_distance_m(point_i, point_j)
            if dist <= colocation_distance_m:
                group[source_j] = cand_j
                used[j] = True
                if best_pair_distance is None or dist < best_pair_distance:
                    best_pair_distance = dist

        n_sources = len(group)
        if n_sources >= 2:
            status = "CORROBORATED"
            note = (
                f"{n_sources} independent evidence sources "
                f"({', '.join(sorted(group.keys()))}) show co-located anomalies "
                f"within {colocation_distance_m:.0f}m. This is genuine independent "
                f"corroboration — confidence should be treated as MODERATE to HIGH, "
                f"still pending field verification."
            )
        else:
            status = "SINGLE_SOURCE"
            note = (
                f"Only {source_i} shows an anomaly at this location. No "
                f"independent corroboration found within {colocation_distance_m:.0f}m. "
                f"Confidence remains LOW — this could be a real feature invisible to "
                f"other evidence types, or noise/an artifact specific to {source_i}."
            )

        # Representative location: centroid of the group's peak locations.
        lats = [c.lat for c in group.values()]
        lons = [c.lon for c in group.values()]
        results.append(CorrelatedCandidate(
            lat=sum(lats) / len(lats),
            lon=sum(lons) / len(lons),
            status=status,
            supporting_sources=sorted(group.keys()),
            source_candidates={k: v for k, v in group.items()},
            distance_between_peaks_m=best_pair_distance,
            combined_confidence_note=note,
        ))

    # Corroborated candidates first, then by source count, most sources first.
    results.sort(key=lambda r: (r.status != "CORROBORATED", -len(r.supporting_sources)))
    return results
