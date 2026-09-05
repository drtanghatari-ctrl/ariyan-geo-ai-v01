"""
investigation_multi_mobile.py — Two-evidence-source investigation entry
point called from Kotlin (via Chaquopy): DEM + NDVI correlation.

Mirrors investigation_mobile.py's pattern (JSON string return, no
scipy, no file I/O) but runs BOTH an elevation (DEM) and a vegetation
(NDVI) raster through anomaly detection and cross-references them via
correlation.py to produce CORROBORATED / SINGLE_SOURCE status per
candidate.

REWRITTEN A PRIOR SESSION -- SYNTHETIC PATH REMOVED ENTIRELY, BOTH DEM AND
NDVI. Previously, DEM had a use_real_dem switch (default False,
SyntheticDEMSource) and NDVI was ALWAYS SyntheticNDVISource unless a
SEPARATE use_real_ndvi switch was also flipped on -- meaning by default
this whole function ran on two independent kinds of fabricated terrain.
That directly violated this project's hard requirement (nothing
synthetic/fake -- data must actually be gathered) the moment synthetic
became the actual default rather than an explicit opt-in dev/test mode.

NEW DEM BEHAVIOR (identical pattern to investigation_mobile.py): a real,
live OpenTopography fetch is ALWAYS attempted first -- no toggle. On
failure (network/HTTP/parse error, or no api_key configured yet), falls
back to offline_evidence_fallback.fetch_offline_dem() (this device's
own previously-downloaded offline DEM library). If both fail, raises a
single combined, honest OpenTopographyFetchError.

NEW NDVI BEHAVIOR: a real, live, per-DEM-candidate Copernicus
core/halo vegetation-stress check (ndvi_source_mobile.
fetch_ndvi_core_halo_check(), unchanged) is ALWAYS attempted first for
every DEM candidate -- no toggle, and no separate use_real_ndvi switch
anymore. Each candidate's fetch is independently try/excepted (as
before): a per-candidate failure (or missing Copernicus credentials)
never fails the whole run, it's recorded honestly as SINGLE_SOURCE with
the real reason. If EVERY candidate's live check failed (the realistic
signature of "no network at all" or "credentials never configured", as
opposed to one flaky candidate), this module automatically retries NDVI
correlation using offline_evidence_fallback.fetch_offline_ndvi() -- a
full-AOI raster sampled from this device's own previously-downloaded
Sentinel-2 composite, run through the SAME independent full-grid
detect_raster_anomalies() + correlate_anomalies() pipeline the old
synthetic-NDVI path used structurally (this can therefore find an NDVI
anomaly DEM missed, which the live per-candidate check never could -- a
genuine, if coarser-resolution, capability gain, not just a fallback).
If that ALSO isn't available, the original honest per-candidate-failure
results are kept (DEM results are never discarded because NDVI failed)
with a clear limitations note explaining neither NDVI path worked this
time.

GPR (roadmap item 4, unchanged): when use_gpr=True, a single real GPR
manual pick (a human-read two-way travel time + chosen soil preset, see
gpr_source_mobile.py) anchored at this investigation's (lat, lon) is
converted into a depth estimate and attached as a THIRD, independent
evidence entry (evidence_record.py's third_evidence slot), reported
honestly with its own uncertainty range. Not yet fed into the AI Debate
Engine from this file directly -- that happens in debate_mobile.py,
called separately by MainActivity.kt.

TOKEN-CACHING + PROGRESS-REPORTING FIX (this session): a real on-device
airplane-mode test showed this module could appear to hang for several
minutes with a multi-candidate grid, because the old NDVI loop fetched
a brand-new OAuth token independently for every candidate (see
ndvi_source_mobile.py's own docstring for the full explanation) with
zero visible progress in the meantime. Fixed two ways: (1) the NDVI
loop below now fetches ONE access token for the whole run and reuses it
for every candidate; (2) this module now writes a small
investigation_status.json into offline_data_root as it works (phase =
"dem" / "ndvi" / "done", plus done/total counts for the NDVI loop),
mirroring the exact JSON shape offline_data_manager.py already writes
for offline downloads. MainActivity.kt polls this file on a separate
coroutine so "Running..." can show real progress instead of a silent
spinner. Status writes are best-effort -- a failure to write progress
must never fail the actual investigation.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from coordinate import GeoPoint, build_aoi
from anomaly_detection_mobile import detect_anomalies, detect_raster_anomalies
from correlation import correlate_anomalies, CorrelatedCandidate
from evidence_record import build_investigation_record
import ndvi_source_mobile
from ndvi_source_mobile import NDVIFetchError
from gpr_source_mobile import GPRSurvey, GPRPick, estimate_depths, GPREvidence
from gpr_depth_model import GPRDepthModelError
from dem_source_mobile import OpenTopographyAAIGridSource, OpenTopographyFetchError
from offline_evidence_fallback import fetch_offline_dem, fetch_offline_ndvi, OfflineDataUnavailableError


def _write_investigation_status(
    offline_data_root: str, phase: str, done: int, total: int, detail: str = ""
) -> None:
    """Best-effort progress status write, polled by MainActivity.kt while
    a run is in progress -- mirrors the existing offline_status.json
    pattern already proven for OfflineDataActivity.kt's downloads. Never
    raises: a failure to write progress (e.g. storage permission not
    granted) must never fail the actual investigation."""
    try:
        path = os.path.join(offline_data_root, "investigation_status.json")
        with open(path, "w") as f:
            json.dump({"phase": phase, "done": done, "total": total, "detail": detail}, f)
    except Exception:
        pass


@dataclass
class NdviCoreHaloResult:
    """One real per-candidate NDVI core/halo check result (or a recorded
    failure -- including "credentials not configured", now treated the
    same honest way as a network failure), used as a `second_anomalies`
    entry when the live per-candidate path is used. Kept as a plain
    dataclass so evidence_record.py's asdict() call works on it exactly
    like it does on AnomalyCandidate. NOTE: this has a DIFFERENT schema
    than AnomalyCandidate (core_mean/halo_mean/z_score, not
    area_cells/peak_zscore/polarity) -- evidence_record.py routes it
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
    timeout: float = 8.0,
    progress_callback=None,
) -> tuple[list, list]:
    """For each DEM candidate, run a real Copernicus NDVI core/halo check
    anchored at that candidate's location. Returns
    (correlated_candidates, ndvi_results) -- correlated_candidates is a
    list[CorrelatedCandidate] (one per DEM candidate, CORROBORATED or
    SINGLE_SOURCE), ndvi_results is a list[NdviCoreHaloResult] (including
    failed/unavailable fetches, recorded honestly rather than dropped).

    Missing client_id/client_secret is treated exactly like a fetch
    failure -- every candidate gets an honest "credentials not
    configured" note -- rather than raising, since real data is always
    attempted first and the caller (run_investigation_multi_json) needs
    a uniform way to detect "live NDVI totally unavailable this run"
    (every candidate failed) to decide whether to try the offline
    fallback.

    THIS SESSION'S FIX: fetches ONE OAuth access token up front for the
    entire run (rather than every candidate fetching its own -- see this
    module's and ndvi_source_mobile.py's docstrings). If that single
    token fetch fails (e.g. no network at all, which is the realistic
    on-device signature this was built to fix), every candidate is
    marked failed immediately with that same real error message instead
    of every candidate separately retrying and timing out. `progress_
    callback(done, total)`, if given, is called after each candidate so
    the caller can report live progress."""
    correlated: list[CorrelatedCandidate] = []
    ndvi_results: list[NdviCoreHaloResult] = []
    total = len(dem_candidates)

    creds_missing_message = None
    token = None
    token_error_message = None

    if not client_id or not client_secret:
        creds_missing_message = (
            "Copernicus OAuth client ID/secret not configured yet -- enter "
            "your free client credentials (dataspace.copernicus.eu) to "
            "enable live real per-candidate NDVI checks."
        )
    else:
        try:
            token = ndvi_source_mobile.get_access_token(client_id, client_secret, timeout=timeout)
        except NDVIFetchError as exc:
            token_error_message = (
                f"Could not obtain a Copernicus access token: {exc}. This "
                f"usually means no network connection is available right "
                f"now, or the credentials are invalid. Checked once for "
                f"this entire run rather than retried per candidate."
            )

    shared_error_message = creds_missing_message or token_error_message

    for i, dem_candidate in enumerate(dem_candidates):
        error_message = shared_error_message
        check = None
        if error_message is None:
            try:
                check = ndvi_source_mobile.fetch_ndvi_core_halo_check(
                    dem_candidate.lat, dem_candidate.lon,
                    client_id, client_secret,
                    stress_zscore_threshold=stress_zscore_threshold,
                    timeout=timeout,
                    access_token=token,
                )
            except NDVIFetchError as exc:
                error_message = str(exc)

        if error_message is not None:
            ndvi_results.append(NdviCoreHaloResult(
                lat=dem_candidate.lat, lon=dem_candidate.lon,
                core_mean=None, halo_mean=None, halo_stddev=None, z_score=None,
                vegetation_stress_detected=False, error=error_message,
            ))
            status = "SINGLE_SOURCE"
            note = (
                f"Real NDVI check unavailable for this candidate: "
                f"{error_message}. Recorded honestly as SINGLE_SOURCE (DEM "
                f"only) rather than failing the whole investigation. "
                f"Confidence remains LOW."
            )
            supporting_sources = ["DEM"]
        else:
            ndvi_results.append(NdviCoreHaloResult(
                lat=dem_candidate.lat, lon=dem_candidate.lon,
                core_mean=check["core_mean"], halo_mean=check["halo_mean"],
                halo_stddev=check["halo_stddev"], z_score=check["z_score"],
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

        correlated.append(CorrelatedCandidate(
            lat=dem_candidate.lat,
            lon=dem_candidate.lon,
            status=status,
            supporting_sources=supporting_sources,
            source_candidates={"DEM": dem_candidate},
            distance_between_peaks_m=0.0,
            combined_confidence_note=note,
        ))

        if progress_callback is not None:
            progress_callback(i + 1, total)

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
    use_gpr=True with a missing soil preset or travel time.
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
    api_key: str = "",
    demtype: str = "SRTMGL1",
    ndvi_client_id: str = "",
    ndvi_client_secret: str = "",
    ndvi_timeout_s: float = 8.0,
    offline_data_root: str = "",
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

    DEM: real (OpenTopography) always attempted first via api_key; on
    failure, falls back to this device's offline DEM library. If both
    fail, raises OpenTopographyFetchError naming both real reasons.

    NDVI: real (Copernicus Sentinel Hub Statistical API, per-DEM-candidate
    core/halo check) always attempted first via ndvi_client_id/secret,
    using ONE shared access token for the whole run (this session's fix
    -- see ndvi_source_mobile.py and this module's own docstrings). If
    EVERY candidate's live check failed, falls back to this device's
    offline Sentinel-2 composite (a full-AOI raster, independently
    scanned and correlated against the DEM candidates -- can find NDVI
    anomalies the per-candidate check couldn't). If that's also
    unavailable, the honest per-candidate-failure results are kept and
    DEM results are still returned -- an NDVI-side failure never blocks
    the DEM investigation itself.

    GPR (optional, use_gpr=True): a single real manual pick (two-way
    travel time + soil preset) anchored at this investigation's
    (lat, lon), attached as a third, independent evidence entry. All
    gpr_* parameters default to off/empty.

    Writes investigation_status.json into offline_data_root as it works
    (phase "dem" / "ndvi" / "done"), polled by MainActivity.kt for live
    progress display. Best-effort -- never raises on its own.

    Raises ValueError if use_gpr=True without both gpr_soil_preset_key
    and gpr_two_way_time_ns. Raises OpenTopographyFetchError if DEM is
    unavailable both live and offline (see above) -- this is the only
    hard failure; every NDVI-side and GPR-side failure degrades
    gracefully with an honest limitations[] entry instead.
    """
    _write_investigation_status(offline_data_root, "dem", 0, 1)

    center = GeoPoint(lat, lon)
    aoi = build_aoi(center, radius_m=radius_m, grid_size=grid_size)

    # --- DEM: real-first, offline-fallback (same pattern as investigation_mobile.py) ---
    live_dem_error: OpenTopographyFetchError | None = None
    dem = None
    if api_key:
        try:
            dem = OpenTopographyAAIGridSource(api_key, demtype=demtype).fetch(aoi)
        except OpenTopographyFetchError as exc:
            live_dem_error = exc
    else:
        live_dem_error = OpenTopographyFetchError(
            "No OpenTopography API key is configured yet -- enter your "
            "free key (opentopography.org) to enable live real DEM fetch."
        )
    if dem is None:
        try:
            dem = fetch_offline_dem(aoi, offline_data_root)
        except OfflineDataUnavailableError as offline_dem_error:
            raise OpenTopographyFetchError(
                f"Live DEM fetch failed ({live_dem_error}) and no offline "
                f"data is available for this location either "
                f"({offline_dem_error})."
            ) from offline_dem_error

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

    # --- NDVI: real per-candidate check first, offline full-raster fallback if that totally failed ---
    _write_investigation_status(offline_data_root, "ndvi", 0, max(1, len(dem_candidates)))

    def _report_ndvi_progress(done: int, total: int) -> None:
        _write_investigation_status(offline_data_root, "ndvi", done, total)

    correlation_results, ndvi_results = _real_ndvi_correlation_for_dem_candidates(
        dem_candidates, ndvi_client_id, ndvi_client_secret,
        timeout=ndvi_timeout_s,
        progress_callback=_report_ndvi_progress,
    )
    n_errors = sum(1 for r in ndvi_results if r.error is not None)

    second_evidence: object = RealNdviCoreHaloEvidence(
        n_candidates_checked=len(dem_candidates), n_fetch_errors=n_errors,
    )
    second_anomalies: list = ndvi_results
    second_anomalies_are_candidates = False
    used_offline_ndvi = False
    ndvi_limitations: list[str] = []

    if dem_candidates and n_errors == len(dem_candidates):
        try:
            offline_ndvi_raster = fetch_offline_ndvi(aoi, offline_data_root)
            ndvi_candidates = detect_raster_anomalies(
                aoi, offline_ndvi_raster.ndvi,
                kernel_sigma_cells=ndvi_kernel_sigma_cells,
                zscore_threshold=ndvi_zscore_threshold,
                min_area_cells=3,
            )
            resolved_colocation = (
                colocation_distance_m if colocation_distance_m is not None
                else max(30.0, aoi.cell_size_m * 4)
            )
            correlation_results = correlate_anomalies(
                {"DEM": dem_candidates, "NDVI": ndvi_candidates},
                aoi_center=center,
                colocation_distance_m=resolved_colocation,
            )
            second_evidence = offline_ndvi_raster
            second_anomalies = ndvi_candidates
            second_anomalies_are_candidates = True
            used_offline_ndvi = True
            ndvi_limitations.append(
                "Live per-candidate NDVI checks were unavailable for every "
                "candidate this run (no network, or Copernicus credentials "
                "not yet configured), so NDVI correlation used this "
                "device's offline Sentinel-2 composite instead -- real "
                "data, but coarser resolution than the live per-candidate "
                "check (see offline_evidence_fallback.py)."
            )
        except OfflineDataUnavailableError as offline_ndvi_error:
            ndvi_limitations.append(
                f"Live per-candidate NDVI checks were unavailable for "
                f"every candidate this run, and no offline NDVI data is "
                f"available for this location either "
                f"({offline_ndvi_error}). NDVI correlation could not be "
                f"performed for this run -- the DEM results above are "
                f"unaffected."
            )
    elif dem_candidates and n_errors > 0:
        ndvi_limitations.append(
            f"{n_errors} of {len(dem_candidates)} candidate(s) had a real "
            f"NDVI check unavailable (network/auth/no-data) and were "
            f"recorded as SINGLE_SOURCE with the real reason rather than "
            f"silently dropped or faked."
        )

    record = build_investigation_record(
        aoi, dem, dem_candidates, dem_zscore_threshold, dem_kernel_sigma_cells,
        second_evidence=second_evidence,
        second_anomalies=second_anomalies,
        second_evidence_type="NDVI",
        correlation_results=correlation_results,
        second_anomalies_are_candidates=second_anomalies_are_candidates,
        third_evidence=gpr_evidence,
        third_evidence_type="GPR",
    )

    if not used_offline_ndvi:
        record.limitations.append(
            "Real NDVI in this run (where a live per-candidate check "
            "succeeded) is a TARGETED PER-CANDIDATE check (core bbox vs. "
            "halo bbox around each DEM candidate), not an independent "
            "full-grid NDVI scan -- unlike the DEM anomaly detector, this "
            "method cannot discover a candidate that DEM missed. It can "
            "only confirm or fail to confirm vegetation stress at "
            "locations DEM already flagged. The halo bbox also "
            "geometrically includes the core bbox rather than being a "
            "true annulus, a documented approximation of the underlying "
            "Statistical API's bbox-only interface."
        )
    for note in ndvi_limitations:
        record.limitations.append(note)
    if gpr_limitation:
        record.limitations.append(gpr_limitation)

    _write_investigation_status(offline_data_root, "done", max(1, len(dem_candidates)), max(1, len(dem_candidates)))

    return record.to_json()