"""
investigation_multi_mobile.py — Two-evidence-source investigation entry
point called from Kotlin (via Chaquopy): DEM + NDVI correlation.

Two NDVI modes are supported now:

  - SYNTHETIC (default, use_real_ndvi=False): an independent synthetic
    NDVI raster is generated, anomaly-detected, and spatially correlated
    against the DEM anomalies via correlation.correlate_anomalies(). This
    mirrors investigation_mobile.py's DEM-only pattern (JSON string
    return, no scipy, no file I/O) and remains unchanged from before.

  - REAL (use_real_ndvi=True): a TARGETED per-DEM-candidate check via
    ndvi_source_mobile.fetch_ndvi_core_halo_check() -- a small "core"
    bbox and a larger "halo" bbox around each already-detected DEM
    anomaly's own coordinates, fetched from the Copernicus Data Space
    Ecosystem's Sentinel Hub Statistical API (real Sentinel-2 NDVI,
    server-side aggregate stats only -- no raster ever reaches the
    device, which is what keeps this GDAL-free on Android). This is NOT
    an independent full-area NDVI scan the way the synthetic path is; it
    is a real, honest, but narrower check: "is there a real vegetation-
    stress signature at this specific candidate's location?" A
    CORROBORATED status from the real path means real DEM + real,
    independently-measured vegetation stress at that exact point --
    genuine two-real-source corroboration, by this targeted method.

IMPORTANT HONEST LIMITATION (synthetic path only): real Sentinel-2 NDVI
via a full independent raster (PlanetaryComputerNDVISource) requires
rasterio to read GeoTIFF bands, and Chaquopy cannot build rasterio/GDAL
for Android (same blocker that ruled out rasterio for the DEM path --
see dem_source_mobile.py). No pure-Python GeoTIFF-band reader has been
built for a full NDVI raster, so when use_real_ndvi=False the NDVI side
of this investigation is ALWAYS SyntheticNDVISource, regardless of
use_real_dem. This limitation is appended to the returned record's
limitations list, not hidden. When use_real_ndvi=True, this limitation
does not apply -- see the real-path limitation appended instead.
"""
from __future__ import annotations

from dataclasses import dataclass

from coordinate import GeoPoint, build_aoi
from dem_source import SyntheticDEMSource
from imagery_source import SyntheticNDVISource
from anomaly_detection_mobile import detect_anomalies, detect_raster_anomalies
from correlation import correlate_anomalies, CorrelatedCandidate
from evidence_record import build_investigation_record


@dataclass
class RealNdviCoreHaloEvidence:
    """Evidence-record wrapper for the REAL, per-candidate NDVI core/halo
    check (ndvi_source_mobile.fetch_ndvi_core_halo_check), distinct from
    imagery_source.py's NDVIRaster: there is no independent full-area NDVI
    raster here, only a targeted real measurement at each DEM candidate's
    own coordinates. `checks` holds one result dict per DEM candidate --
    either a real core/halo result, or {"lat", "lon", "error": ...} if the
    fetch failed for that specific location. Failures are recorded, never
    hidden or silently substituted."""
    source: str
    synthetic: bool
    checks: list

    def as_evidence_record(self) -> dict:
        return {
            "source": self.source,
            "synthetic": self.synthetic,
            "evidence_type": "NDVI",
            "method": (
                "Per-candidate real Sentinel-2 NDVI core-vs-halo statistical "
                "check (Copernicus Data Space Ecosystem Statistical API) at "
                "each DEM candidate's own coordinates -- not an independent "
                "full-area NDVI scan."
            ),
            "checks": self.checks,
        }


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
    use_real_ndvi: bool = False,
    ndvi_client_id: str | None = None,
    ndvi_client_secret: str | None = None,
    ndvi_core_radius_m: float = 15.0,
    ndvi_halo_outer_m: float = 60.0,
    ndvi_stress_zscore_threshold: float = 1.0,
) -> str:
    """Run a two-source (DEM + NDVI) investigation and return the
    InvestigationRecord as a JSON string. This is the function
    MainActivity.kt calls when the "Include NDVI correlation" switch
    is on.

    DEM: real (OpenTopography, if use_real_dem=True + api_key given)
    or synthetic, exactly as in investigation_mobile.py.

    NDVI: real, targeted per-candidate corroboration if use_real_ndvi=True
    (requires ndvi_client_id + ndvi_client_secret -- a free Copernicus Data
    Space Ecosystem OAuth2 client-credentials client). Otherwise always
    SyntheticNDVISource -- see module docstring.

    Raises the same OpenTopographyFetchError as investigation_mobile.py
    for any real-DEM network/HTTP/parse failure. Raises ValueError if
    use_real_dem or use_real_ndvi is True without its required
    credentials. Real per-candidate NDVI check failures (e.g. total cloud
    cover at one candidate's location) do NOT raise -- they are recorded
    per-candidate as an honest SINGLE_SOURCE result with the real error
    message, so one bad location doesn't hide DEM results or other
    candidates' successful checks.
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

    dem_candidates = detect_anomalies(
        dem,
        kernel_sigma_cells=dem_kernel_sigma_cells,
        zscore_threshold=dem_zscore_threshold,
        min_area_cells=3,
    )

    if use_real_ndvi:
        if not ndvi_client_id or not ndvi_client_secret:
            raise ValueError(
                "use_real_ndvi=True requires non-empty ndvi_client_id and "
                "ndvi_client_secret"
            )
        from ndvi_source_mobile import fetch_ndvi_core_halo_check, NDVIFetchError

        checks: list = []
        correlation_results: list = []
        for cand in dem_candidates:
            try:
                result = fetch_ndvi_core_halo_check(
                    cand.lat, cand.lon, ndvi_client_id, ndvi_client_secret,
                    core_radius_m=ndvi_core_radius_m,
                    halo_outer_m=ndvi_halo_outer_m,
                    stress_zscore_threshold=ndvi_stress_zscore_threshold,
                )
                checks.append({"lat": cand.lat, "lon": cand.lon, **result})
                stress = result["vegetation_stress_detected"]
                note = (
                    f"Real Sentinel-2 NDVI targeted check at this DEM "
                    f"candidate's location: core mean={result['core_mean']:.4f}, "
                    f"halo mean={result['halo_mean']:.4f} "
                    f"(z={result['zscore']:.2f}). "
                    + (
                        "Vegetation stress detected -- possible independent "
                        "corroboration (targeted core/halo check, not an "
                        "independent full-area scan)."
                        if stress else
                        "No vegetation-stress signature detected here -- "
                        "remains single-source (DEM only)."
                    )
                )
                correlation_results.append(CorrelatedCandidate(
                    lat=cand.lat, lon=cand.lon,
                    status="CORROBORATED" if stress else "SINGLE_SOURCE",
                    supporting_sources=["DEM", "NDVI"] if stress else ["DEM"],
                    source_candidates={"DEM": cand},
                    distance_between_peaks_m=None,
                    combined_confidence_note=note,
                ))
            except NDVIFetchError as exc:
                checks.append({"lat": cand.lat, "lon": cand.lon, "error": str(exc)})
                correlation_results.append(CorrelatedCandidate(
                    lat=cand.lat, lon=cand.lon,
                    status="SINGLE_SOURCE",
                    supporting_sources=["DEM"],
                    source_candidates={"DEM": cand},
                    distance_between_peaks_m=None,
                    combined_confidence_note=(
                        f"Real NDVI check failed for this location and could "
                        f"not be used as corroboration: {exc}"
                    ),
                ))

        ndvi_evidence = RealNdviCoreHaloEvidence(
            source="Sentinel-2 L2A (Copernicus Data Space Ecosystem Statistical API)",
            synthetic=False,
            checks=checks,
        )

        record = build_investigation_record(
            aoi, dem, dem_candidates, dem_zscore_threshold, dem_kernel_sigma_cells,
            second_evidence=ndvi_evidence,
            second_anomalies=None,
            second_evidence_type="NDVI",
            correlation_results=correlation_results,
        )
        record.limitations.append(
            "Real NDVI corroboration here is a TARGETED per-candidate check "
            "(small core bbox vs. a larger halo bbox around each DEM "
            "anomaly's own coordinates, via the Copernicus Sentinel-2 "
            "Statistical API) -- not an independent full-area NDVI scan. "
            "The halo bbox geometrically includes the core bbox (not a true "
            "annulus), which slightly dilutes the contrast it can detect. "
            "A CORROBORATED status here means real DEM plus a real, "
            "independently-measured vegetation-stress signal at that exact "
            "point -- genuine two-real-source corroboration, but by this "
            "targeted method, not a second independent full-grid detection."
        )
        return record.to_json()

    # ---- Synthetic NDVI path (unchanged from before) ----
    ndvi = SyntheticNDVISource(seed=synthetic_ndvi_seed).fetch(
        aoi,
        variability=0.06,
        variability_wavelength_cells=max(15.0, grid_size * 0.23),
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
