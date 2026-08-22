"""
investigation.py — Orchestrates one end-to-end investigation:

    GPS coordinate -> AOI -> DEM evidence -> terrain derivatives
        -> anomaly detection -> evidence record -> visualization

This is the real vertical slice: every step here does genuine
computation on real (or explicitly-labeled synthetic) data. There is
no module here whose job is to validate another module's validation.
"""
from __future__ import annotations

import argparse
import json
import os

from coordinate import GeoPoint, build_aoi
from dem_source import SyntheticDEMSource, OpenTopographyDEMSource
from anomaly_detection import detect_anomalies
from evidence_record import build_investigation_record
from visualize import render_investigation


def run_investigation(
    lat: float,
    lon: float,
    radius_m: float = 500.0,
    grid_size: int = 128,
    use_real_dem: bool = False,
    opentopography_api_key: str | None = None,
    kernel_sigma_cells: float = 15.0,
    zscore_threshold: float = 2.5,
    synthetic_seed: int = 42,
    synthetic_test_anomaly: dict | None = None,
    out_dir: str = "output",
):
    os.makedirs(out_dir, exist_ok=True)

    center = GeoPoint(lat, lon)
    aoi = build_aoi(center, radius_m=radius_m, grid_size=grid_size)

    if use_real_dem:
        if not opentopography_api_key:
            raise ValueError("use_real_dem=True requires opentopography_api_key")
        dem = OpenTopographyDEMSource(opentopography_api_key).fetch(aoi)
    else:
        anomalies_spec = [synthetic_test_anomaly] if synthetic_test_anomaly else None
        dem = SyntheticDEMSource(seed=synthetic_seed).fetch(
            aoi,
            relief_amplitude_m=0.5,
            relief_wavelength_cells=90,
            anomalies=anomalies_spec,
        )

    anomalies = detect_anomalies(
        dem, kernel_sigma_cells=kernel_sigma_cells,
        zscore_threshold=zscore_threshold, min_area_cells=3,
    )

    record = build_investigation_record(
        aoi, dem, anomalies, zscore_threshold, kernel_sigma_cells
    )

    json_path = os.path.join(out_dir, "investigation_record.json")
    with open(json_path, "w") as f:
        f.write(record.to_json())

    png_path = os.path.join(out_dir, "investigation_map.png")
    render_investigation(dem, anomalies, kernel_sigma_cells, png_path)

    return record, json_path, png_path


def _cli():
    p = argparse.ArgumentParser(description="Run an ARIYAN core investigation.")
    p.add_argument("lat", type=float)
    p.add_argument("lon", type=float)
    p.add_argument("--radius-m", type=float, default=500.0)
    p.add_argument("--grid-size", type=int, default=128)
    p.add_argument("--real-dem", action="store_true",
                    help="Use OpenTopography live DEM (requires --api-key and network)")
    p.add_argument("--api-key", type=str, default=None)
    p.add_argument("--out-dir", type=str, default="output")
    args = p.parse_args()

    record, json_path, png_path = run_investigation(
        args.lat, args.lon,
        radius_m=args.radius_m, grid_size=args.grid_size,
        use_real_dem=args.real_dem, opentopography_api_key=args.api_key,
        out_dir=args.out_dir,
    )
    print(f"Wrote {json_path}")
    print(f"Wrote {png_path}")
    print()
    print(record.confidence_statement)


if __name__ == "__main__":
    _cli()
