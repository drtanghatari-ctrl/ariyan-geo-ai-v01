"""
investigation_multi_mobile.py — Two-evidence-source investigation entry
point called from Kotlin (via Chaquopy): DEM + NDVI correlation.

Mirrors investigation_mobile.py's pattern (JSON string return, no
scipy, no file I/O) but runs BOTH an elevation (DEM) and a vegetation
(NDVI) raster through anomaly detection and cross-references them via
correlation.py to produce CORROBORATED / SINGLE_SOURCE status per
candidate -- the actual "independent evidence corroboration" step the
project's roadmap has been building toward.

IMPORTANT HONEST LIMITATION: real Sentinel-2 NDVI
(PlanetaryComputerNDVISource) requires rasterio to read GeoTIFF bands,
and Chaquopy cannot build rasterio/GDAL for Android (same blocker that
ruled out rasterio for the DEM path -- see dem_source_mobile.py). No
pure-Python GeoTIFF-band reader has been built yet for NDVI, so on
Android the NDVI side of this investigation is ALWAYS
SyntheticNDVISource, regardless of use_real_dem. DEM can still be
real. This means a CORROBORATED result from this function means "real
DEM anomaly co-located with a synthetic NDVI anomaly" -- correlation
LOGIC is real and tested, but full two-real-source corroboration is
not yet possible on this platform. This limitation is also appended to
the returned record's limitations list, not hidden.
"""
from __future__ import annotations

from coordinate import GeoPoint, build_aoi
from dem_source import SyntheticDEMSource
from imagery_source import SyntheticNDVISource
from anomaly_detection_mobile import detect_anomalies, detect_raster_anomalies
from correlation import correlate_anomalies
from evidence_record import build_investigation_record


def run_investigation_multi_json(
    lat: float,
    lon: float,
    radius_m: float = 500.0,
    grid_size: int = 96,
    dem_kernel_sigma_cells: float = 12.0,
    dem_zscore_threshold: float = 2.5,
    ndvi_kernel_sigma_cells: float = 12.0,
    ndvi_zscore_threshold: float = 2.0,
    colocation_distance_m: float | None = None,
    synthetic_seed: int = 42,
    synthetic_ndvi_seed: int = 43,
    use_real_dem: bool = False,
    api_key: str | None = None,
    demtype: str = "SRTMGL1",
) -> str:
    """Run a two-source (DEM + NDVI) investigation and return the
    InvestigationRecord as a JSON string. This is the function
    MainActivity.kt calls when the "Include NDVI correlation" switch
    is on.

    DEM: real (OpenTopography, if use_real_dem=True + api_key given)
    or synthetic, exactly as in investigation_mobile.py.

    NDVI: ALWAYS SyntheticNDVISource on this platform -- see module
    docstring. Raises the same OpenTopographyFetchError as
    investigation_mobile.py for any real-DEM network/HTTP/parse
    failure.
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

    ndvi = SyntheticNDVISource(seed=synthetic_ndvi_seed).fetch(
        aoi,
        variability=0.06,
        variability_wavelength_cells=max(15.0, grid_size * 0.23),
    )

    dem_candidates = detect_anomalies(
        dem,
        kernel_sigma_cells=dem_kernel_sigma_cells,
        zscore_threshold=dem_zscore_threshold,
        min_area_cells=3,
    )
    ndvi_candidates = detect_raster_anomalies(
        aoi, ndvi.ndvi,
        kernel_sigma_cells=ndvi_kernel_sigma_cells,
        zscore_threshold=ndvi_zscore_threshold,
        min_area_cells=3,
    )

    if colocation_distance_m is None:
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
    record.limitations.append(
        "NDVI evidence in this run is SYNTHETIC regardless of the DEM "
        "source, because this platform (Android/Chaquopy) cannot yet "
        "read real Sentinel-2 GeoTIFF bands (rasterio/GDAL are not "
        "buildable here). A CORROBORATED status therefore reflects "
        "real DEM co-located with synthetic NDVI, not two real "
        "sources -- the correlation LOGIC is real and tested; full "
        "two-real-source corroboration is a future increment."
    )
    return record.to_json()
