"""
investigation_mobile.py — Entry point called from Kotlin (via Chaquopy).

Same pipeline as investigation.py (GPS coordinate -> AOI -> DEM ->
anomaly detection -> evidence record), but:
  - uses anomaly_detection_mobile (no scipy) instead of anomaly_detection
  - returns a JSON string directly instead of writing files, since the
    Android app renders results natively rather than embedding a
    matplotlib PNG
  - now supports two DEM sources: SyntheticDEMSource (default, offline,
    no network) and, when use_real_dem=True, a live OpenTopography fetch
    via dem_source_mobile.OpenTopographyAAIGridSource (AAIGrid decoded
    with pure NumPy -- no GDAL/rasterio, which Chaquopy cannot build for
    Android). Every returned record's evidence entry states synthetic
    true/false explicitly either way; nothing here upgrades a synthetic
    result to look real.
"""
from __future__ import annotations

from coordinate import GeoPoint, build_aoi
from dem_source import SyntheticDEMSource
from anomaly_detection_mobile import detect_anomalies
from evidence_record import build_investigation_record


def run_investigation_json(
    lat: float,
    lon: float,
    radius_m: float = 500.0,
    grid_size: int = 96,
    kernel_sigma_cells: float = 12.0,
    zscore_threshold: float = 2.5,
    synthetic_seed: int = 42,
    use_real_dem: bool = False,
    api_key: str | None = None,
    demtype: str = "SRTMGL1",
) -> str:
    """Run one investigation and return the InvestigationRecord as a
    JSON string. This is the function MainActivity.kt calls.

    use_real_dem=False (default): SyntheticDEMSource, exactly as before
    -- offline, no network, every result labeled synthetic=True.

    use_real_dem=True: fetches a real DEM from OpenTopography. Requires
    a non-empty api_key. Raises
    dem_source_mobile.OpenTopographyFetchError (a RuntimeError
    subclass) with a human-readable message on any network, HTTP, or
    parsing failure -- MainActivity.kt catches this and shows the
    message directly rather than a generic failure.
    """
    center = GeoPoint(lat, lon)
    aoi = build_aoi(center, radius_m=radius_m, grid_size=grid_size)

    if use_real_dem:
        if not api_key:
            raise ValueError("use_real_dem=True requires a non-empty api_key")
        from dem_source_mobile import OpenTopographyAAIGridSource
        dem = OpenTopographyAAIGridSource(api_key, demtype=demtype).fetch(aoi)
    else:
        dem = SyntheticDEMSource(seed=synthetic_seed).fetch(
            aoi,
            relief_amplitude_m=0.5,
            relief_wavelength_cells=max(20.0, grid_size * 0.7),
        )

    anomalies = detect_anomalies(
        dem,
        kernel_sigma_cells=kernel_sigma_cells,
        zscore_threshold=zscore_threshold,
        min_area_cells=3,
    )

    record = build_investigation_record(
        aoi, dem, anomalies, zscore_threshold, kernel_sigma_cells
    )
    return record.to_json()
