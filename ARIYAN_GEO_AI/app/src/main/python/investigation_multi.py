"""
investigation_multi.py — Two-evidence-source investigation:

    GPS coordinate -> AOI -> [DEM evidence, NDVI evidence] (independent)
        -> anomaly detection on each -> cross-evidence correlation
        -> evidence record with corroboration status

This is the real increment the desktop vertical slice's own README
named as priority #2: "an actual evidence-fusion step that checks
whether a DEM anomaly and an imagery anomaly co-locate — this is where
'independent corroboration' becomes real rather than conceptual."

investigation.py (single-source, DEM-only) is untouched and still
works exactly as before — this is additive, not a replacement, per the
project's own cumulative-build rule.
"""
from __future__ import annotations

import json
import os

from coordinate import GeoPoint, build_aoi
from dem_source import SyntheticDEMSource
from imagery_source import SyntheticNDVISource
from anomaly_detection_mobile import detect_anomalies, detect_raster_anomalies
from correlation import correlate_anomalies
from evidence_record import build_investigation_record


def run_multi_source_investigation(
    lat: float,
    lon: float,
    radius_m: float = 500.0,
    grid_size: int = 128,
    dem_kernel_sigma_cells: float = 15.0,
    dem_zscore_threshold: float = 2.5,
    ndvi_kernel_sigma_cells: float = 15.0,
    ndvi_zscore_threshold: float = 2.0,
    colocation_distance_m: float | None = None,
    synthetic_dem_seed: int = 42,
    synthetic_ndvi_seed: int = 43,
    synthetic_dem_anomaly: dict | None = None,
    synthetic_ndvi_anomaly: dict | None = None,
    out_dir: str = "output",
):
    os.makedirs(out_dir, exist_ok=True)

    center = GeoPoint(lat, lon)
    aoi = build_aoi(center, radius_m=radius_m, grid_size=grid_size)

    dem = SyntheticDEMSource(seed=synthetic_dem_seed).fetch(
        aoi,
        relief_amplitude_m=0.5,
        relief_wavelength_cells=90,
        anomalies=[synthetic_dem_anomaly] if synthetic_dem_anomaly else None,
    )
    ndvi = SyntheticNDVISource(seed=synthetic_ndvi_seed).fetch(
        aoi,
        variability=0.06,
        variability_wavelength_cells=30,
        anomalies=[synthetic_ndvi_anomaly] if synthetic_ndvi_anomaly else None,
    )

    dem_candidates = detect_anomalies(
        dem, kernel_sigma_cells=dem_kernel_sigma_cells,
        zscore_threshold=dem_zscore_threshold, min_area_cells=3,
    )
    ndvi_candidates = detect_raster_anomalies(
        aoi, ndvi.ndvi, kernel_sigma_cells=ndvi_kernel_sigma_cells,
        zscore_threshold=ndvi_zscore_threshold, min_area_cells=3,
    )

    if colocation_distance_m is None:
        # Default tolerance: a few cells' worth of distance at this AOI's
        # resolution, generous enough for two different rasters' anomaly
        # peaks to land within it, tight enough to be a meaningful check.
        colocation_distance_m = max(30.0, aoi.cell_size_m * 4)

    correlation_results = correlate_anomalies(
        {"DEM": dem_candidates, "NDVI": ndvi_candidates},
        aoi_center=center,
        colocation_distance_m=colocation_distance_m,
    )

    record = build_investigation_record(
        aoi, dem, dem_candidates, dem_zscore_threshold, dem_kernel_sigma_cells,
        second_evidence=ndvi,
        second_anomalies=ndvi_candidates,
        second_evidence_type="NDVI",
        correlation_results=correlation_results,
    )

    json_path = os.path.join(out_dir, "investigation_record_multi.json")
    with open(json_path, "w") as f:
        f.write(record.to_json())

    return record, json_path


def _cli():
    import argparse
    p = argparse.ArgumentParser(description="Run a two-source (DEM+NDVI) ARIYAN investigation.")
    p.add_argument("lat", type=float)
    p.add_argument("lon", type=float)
    p.add_argument("--radius-m", type=float, default=500.0)
    p.add_argument("--grid-size", type=int, default=128)
    p.add_argument("--out-dir", type=str, default="output")
    args = p.parse_args()

    record, json_path = run_multi_source_investigation(
        args.lat, args.lon, radius_m=args.radius_m, grid_size=args.grid_size,
        out_dir=args.out_dir,
    )
    print(f"Wrote {json_path}")
    print()
    print(record.confidence_statement)


if __name__ == "__main__":
    _cli()
