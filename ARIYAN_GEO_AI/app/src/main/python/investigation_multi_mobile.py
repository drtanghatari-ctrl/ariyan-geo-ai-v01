"""
investigation_multi_mobile.py — Two-evidence-source investigation entry
point called from Kotlin (via Chaquopy): DEM + NDVI correlation.

Mirrors investigation_mobile.py's pattern (JSON string return, no
scipy, no file I/O) but runs BOTH an elevation (DEM) and a vegetation
(NDVI) raster through anomaly detection and cross-references them via
correlation.py to produce CORROBORATED / SINGLE_SOURCE status per
candidate -- the actual "independent evidence corroboration" step the
project's roadmap has been building toward.

NDVI HAS TWO MODES NOW:

1. use_real_ndvi=False (default): NDVI is ALWAYS SyntheticNDVISource,
   because real Sentinel-2 raster NDVI (PlanetaryComputerNDVISource)
   requires rasterio to read GeoTIFF bands, and Chaquopy cannot build
   rasterio/GDAL for Android (same blocker that ruled out rasterio for
   the DEM path -- see dem_source_mobile.py). This mode's correlation
   LOGIC is real and tested, but a CORROBORATED result means "real DEM
   anomaly co-located with a synthetic NDVI anomaly", not two real
   sources.

2. use_real_ndvi=True: for EACH real DEM candidate, calls
   ndvi_source_mobile.fetch_ndvi_core_halo_check() -- a real,
   network-fetched, per-candidate vegetation-stress check via the
   Copernicus Sentinel Hub Statistical API (server-side NDVI
   computation, no raster ever reaches the device, so the GDAL
   blocker does not apply here). This is NOT an independent full-grid
   NDVI scan; it is a targeted real check anchored at each DEM
   candidate's location. A candidate is CORROBORATED when real
   vegetation stress is detected there, SINGLE_SOURCE otherwise (or on
   a per-candidate fetch failure, which is caught and recorded with
   the real error message rather than failing the whole investigation).
   Requires a real Copernicus Data Space Ecosystem OAuth client
   (client_id + client_secret).

GPR (roadmap item 4, ADDED THIS SESSION, additive/optional):
   When use_gpr=True, a single real GPR manual pick (a human-read
   two-way travel time + chosen soil preset, see gpr_source_mobile.py)
   anchored at this investigation's (lat, lon) is converted into a
   depth estimate and attached as a THIRD, independent evidence entry
   (evidence_record.py's third_evidence slot) -- reported honestly with
   its own uncertainty range, never merged into the DEM/NDVI anomalies
   list (different schema, same reasoning as the real-NDVI core/halo
   path). This is field-verification evidence for the single site
   under investigation, not an independent full-area scan like DEM or
   NDVI. NOT YET fed into the AI Debate Engine (debate_mobile.py) --
   that integration is deferred until this Python-side wiring itself
   has been confirmed working on a real compiled build with a real
   manual pick, per this project's own "verify one real step before
   building the next" practice.
"""
from __future__ import annotations

from dataclasses import dataclass

from coordinate import GeoPoint, build_aoi
from dem_source import SyntheticDEMSource
from imagery_source import SyntheticNDVISource
from anomaly_detection_mobile import detect_anomalies, detect_raster_anomalies
from correlation import correlate_anomalies, CorrelatedCandidate
from evidence_record import build_investigation_record
import ndvi_source_mobile
from ndvi_source_mobile import NDVIFetchError
from gpr_source_mobile import GPRSurvey, GPRPick, estimate_depths, GPREvidence
from gpr_depth_model import GPRDepthModelError


@dataclass
class NdviCoreHaloResult:
    """One real per-candidate NDVI core/halo check result (or a recorded
    failure), used as a `second_anomalies` entry when use_real_ndvi=True.
    Kept as a plain dataclass so evidence_record.py's asdict() call works
    on it exactly like it does on AnomalyCandidate. NOTE: this has a
    DIFFERENT schema than AnomalyCandidate (core_mean/halo_mean/z_score,
    not area_cells/peak_zscore/polarity) -- evidence_record.py routes it
    into second_evidence_detail rather than the anomalies[] list because
    of that, see build_investigation_record's second_anomalies_are_candidates
    parameter."""
    lat: float
    lon: float
    core_mean: float | None
    halo_mean: float | None
    halo_stddev: float | None
    z_score: float | None
    vegetation_stress_detected: bool
    error: str | None = None


class RealNdviCoreHaloEvidence:
    """Wrapper satisfying build_investigation_record's `second_evidence`
    interface (.as_evidence_record(), .source, .synthetic) for the
    real-NDVI-via-Statistical-API path, since there is no NDVIRaster
    object in this mode (no raster is ever fetched -- only per-candidate
    server-side statistics)."""

    source = "Copernicus Sentinel-2 L2A (Sentinel Hub Statistical API, real per-candidate core/halo check)"
    synthetic = False

    def __init__(self, n_candidates_checked: int, n_fetch_errors: int):
        self.n_candidates_checked = n_candidates_checked
        self.n_fetch_errors = n_fetch_errors

    def as_evidence_record(self) -> dict:
        return {
            "evidence_type": "NDVI",
            "source": self.source,
            "synthetic": self.synthetic,
            "method": (
                "OAuth2 client-credentials auth to Copernicus Data Space "
                "Ecosystem; per-DEM-candidate real NDVI mean/stddev fetched "
                "server-side for a small core bbox and a larger halo bbox "
                "around each candidate; vegetation stress flagged when core "
                "mean NDVI is significantly below halo mean (z-score vs "
                "halo stddev). Halo bbox geometrically includes the core "
                "(not a true annulus) -- a documented approximation."
            ),
            "n_candidates_checked": self.n_candidates_checked,
            "n_fetch_errors": self.n_fetch_errors,
        }


def _real_ndvi_correlation_for_dem_candidates(
    dem_candidates: list,
    client_id: str,
    client_secret: str,
    stress_zscore_threshold: float = 1.5,
) -> tuple[list, list]:
    """For each DEM candidate, run a real Copernicus NDVI core/halo check
    anchored at that candidate's location. Returns
    (correlated_candidates, ndvi_results) -- correlated_candidates is a
    list[CorrelatedCandidate] (one per DEM candidate, CORROBORATED or
    SINGLE_SOURCE), ndvi_results is a list[NdviCoreHaloResult] (including
    failed fetches, recorded honestly rather than dropped)."""
    correlated: list[CorrelatedCandidate] = []
    ndvi_results: list[NdviCoreHaloResult] = []

    for dem_candidate in dem_candidates:
        try:
            check = ndvi_source_mobile.fetch_ndvi_core_halo_check(
                dem_candidate.lat, dem_candidate.lon,
                client_id, client_secret,
                stress_zscore_threshold=stress_zscore_threshold,
            )
            ndvi_results.append(NdviCoreHaloResult(
                lat=dem_candidate.lat,
                lon=dem_candidate.lon,
                core_mean=check["core_mean"],
                halo_mean=check["halo_mean"],
                halo_stddev=check["halo_stddev"],
                z_score=check["z_score"],
                vegetation_stress_detected=check["vegetation_stress_detected"],
            ))
            if check["vegetation_stress_detected"]:
                status = "CORROBORATED"
                note = (
                    f"Real Copernicus Sentinel-2 NDVI shows significant "
                    f"vegetation stress at this DEM candidate "
                    f"(core mean={check['core_mean']:.4f} vs halo mean="
                    f"{check['halo_mean']:.4f}, z={check['z_score']:.2f}). "
                    f"This is genuine independent corroboration from a real "
                    f"second evidence source -- confidence should be treated "
                    f"as MODERATE to HIGH, still pending field verification."
                )
                supporting_sources = ["DEM", "NDVI"]
            else:
                status = "SINGLE_SOURCE"
                note = (
                    f"Real Copernicus Sentinel-2 NDVI at this DEM candidate "
                    f"shows no significant vegetation stress "
                    f"(core mean={check['core_mean']:.4f} vs halo mean="
                    f"{check['halo_mean']:.4f}, z={check['z_score']:.2f}). "
                    f"No independent corroboration found. Confidence remains LOW."
                )
                supporting_sources = ["DEM"]
        except NDVIFetchError as exc:
            ndvi_results.append(NdviCoreHaloResult(
                lat=dem_candidate.lat,
                lon=dem_candidate.lon,
                core_mean=None,
                halo_mean=None,
                halo_stddev=None,
                z_score=None,
                vegetation_stress_detected=False,
                error=str(exc),
            ))
            status = "SINGLE_SOURCE"
            note = (
                f"Real NDVI check failed for this candidate: {exc}. "
                f"Recorded honestly as SINGLE_SOURCE (DEM only) rather than "
                f"failing the whole investigation. Confidence remains LOW."
            )
            supporting_sources = ["DEM"]

        correlated.append(CorrelatedCandidate(
            lat=dem_candidate.lat,
            lon=dem_candidate.lon,
            status=status,
            supporting_sources=supporting_sources,
            source_candidates={"DEM": dem_candidate},
            distance_between_peaks_m=0.0,
            combined_confidence_note=note,
        ))

    correlated.sort(key=lambda r: (r.status != "CORROBORATED", -len(r.supporting_sources)))
    return correlated, ndvi_results


def _build_gpr_evidence(
    lat: float,
    lon: float,
    use_gpr: bool,
    gpr_soil_preset_key: str | None,
    gpr_two_way_time_ns: float | None,
    gpr_entry_method: str,
    gpr_device_note: str,
) -> tuple[object | None, str | None]:
    """Build a GPREvidence from a single real manual pick anchored at
    (lat, lon), if use_gpr=True. Returns (gpr_evidence_or_None,
    limitation_message_or_None) -- a failure (bad soil preset key,
    non-positive travel time) is recorded as an honest limitation
    string rather than raised, so one bad GPR input never fails the
    whole DEM/NDVI investigation it's attached to.

    Raises ValueError only for the caller-programming-error case of
    use_gpr=True with a missing soil preset or travel time -- the same
    "required-args-when-enabled" contract already used by use_real_dem/
    use_real_ndvi above.
    """
    if not use_gpr:
        return None, None
    if not gpr_soil_preset_key or gpr_two_way_time_ns is None:
        raise ValueError(
            "use_gpr=True requires both gpr_soil_preset_key and "
            "gpr_two_way_time_ns"
        )
    survey = GPRSurvey(
        lat=lat,
        lon=lon,
        soil_preset_key=gpr_soil_preset_key,
        picks=[GPRPick(position_m=0.0, two_way_time_ns=gpr_two_way_time_ns)],
        entry_method=gpr_entry_method,
        device_note=gpr_device_note,
    )
    try:
        depth_estimates = estimate_depths(survey)
        return GPREvidence(survey, depth_estimates), None
    except GPRDepthModelError as exc:
        return None, (
            f"Real GPR pick entry failed: {exc}. Recorded honestly; this "
            f"investigation continues without GPR evidence for this run."
        )


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
    use_gpr: bool = False,
    gpr_soil_preset_key: str | None = None,
    gpr_two_way_time_ns: float | None = None,
    gpr_entry_method: str = "manual",
    gpr_device_note: str = "",
) -> str:
    """Run a two-source (DEM + NDVI) investigation and return the
    InvestigationRecord as a JSON string. This is the function
    MainActivity.kt calls when the "Include NDVI correlation" switch
    is on.

    DEM: real (OpenTopography, if use_real_dem=True + api_key given)
    or synthetic, exactly as in investigation_mobile.py.

    NDVI: real (Copernicus Sentinel Hub Statistical API, per-DEM-candidate
    core/halo check) if use_real_ndvi=True + ndvi_client_id/secret given;
    otherwise ALWAYS SyntheticNDVISource -- see module docstring.

    GPR (optional, use_gpr=True): a single real manual pick (two-way
    travel time + soil preset, see gpr_source_mobile.py) anchored at
    this investigation's (lat, lon), attached as a third, independent
    evidence entry. All new gpr_* parameters default to off/empty, so
    existing callers (Kotlin code that doesn't pass them) are entirely
    unaffected -- this is purely additive. See module docstring's GPR
    section for what is and isn't wired yet.

    Raises ValueError if use_real_dem=True without api_key,
    use_real_ndvi=True without both ndvi_client_id and ndvi_client_secret,
    or use_gpr=True without both gpr_soil_preset_key and
    gpr_two_way_time_ns. Raises the underlying OpenTopographyFetchError /
    NDVIFetchError for any real-DEM or real-NDVI network/HTTP/parse
    failure that isn't per-candidate-recoverable (auth failures fail the
    whole run; a single candidate's NDVI fetch failure does not -- see
    _real_ndvi_correlation_for_dem_candidates). A GPR depth-conversion
    failure (bad soil preset key, non-positive travel time) never raises
    -- it is recorded as an honest limitations[] entry instead, see
    _build_gpr_evidence.
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

    gpr_evidence, gpr_limitation = _build_gpr_evidence(
        lat, lon, use_gpr, gpr_soil_preset_key, gpr_two_way_time_ns,
        gpr_entry_method, gpr_device_note,
    )

    if use_real_ndvi:
        if not ndvi_client_id or not ndvi_client_secret:
            raise ValueError(
                "use_real_ndvi=True requires non-empty ndvi_client_id and "
                "ndvi_client_secret"
            )

        correlation_results, ndvi_results = _real_ndvi_correlation_for_dem_candidates(
            dem_candidates, ndvi_client_id, ndvi_client_secret,
        )
        n_errors = sum(1 for r in ndvi_results if r.error is not None)
        second_evidence = RealNdviCoreHaloEvidence(
            n_candidates_checked=len(dem_candidates),
            n_fetch_errors=n_errors,
        )

        record = build_investigation_record(
            aoi, dem, dem_candidates, dem_zscore_threshold, dem_kernel_sigma_cells,
            second_evidence=second_evidence,
            second_anomalies=ndvi_results,
            second_evidence_type="NDVI",
            correlation_results=correlation_results,
            second_anomalies_are_candidates=False,
            third_evidence=gpr_evidence,
            third_evidence_type="GPR",
        )
        record.limitations.append(
            "Real NDVI in this run is a TARGETED PER-CANDIDATE check "
            "(core bbox vs. halo bbox around each DEM candidate), not an "
            "independent full-grid NDVI scan -- unlike the DEM anomaly "
            "detector, this method cannot discover a candidate that DEM "
            "missed. It can only confirm or fail to confirm vegetation "
            "stress at locations DEM already flagged. The halo bbox also "
            "geometrically includes the core bbox rather than being a true "
            "annulus, a documented approximation of the underlying "
            "Statistical API's bbox-only interface."
        )
        if n_errors > 0:
            record.limitations.append(
                f"{n_errors} of {len(dem_candidates)} candidate(s) had a "
                f"real NDVI fetch failure (network/auth/no-data) and were "
                f"recorded as SINGLE_SOURCE with the real error message "
                f"rather than silently dropped or faked."
            )
        if gpr_limitation:
            record.limitations.append(gpr_limitation)
        return record.to_json()

    # --- Synthetic-NDVI path (unchanged default behavior) ---
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
        third_evidence=gpr_evidence,
        third_evidence_type="GPR",
    )
    record.limitations.append(
        "NDVI evidence in this run is SYNTHETIC regardless of the DEM "
        "source, because this platform (Android/Chaquopy) cannot yet "
        "read real Sentinel-2 GeoTIFF bands (rasterio/GDAL are not "
        "buildable here). A CORROBORATED status therefore reflects "
        "real DEM co-located with synthetic NDVI, not two real "
        "sources -- the correlation LOGIC is real and tested; full "
        "two-real-source corroboration is available via use_real_ndvi=True "
        "(see the per-candidate Copernicus check above)."
    )
    if gpr_limitation:
        record.limitations.append(gpr_limitation)
    return record.to_json()
