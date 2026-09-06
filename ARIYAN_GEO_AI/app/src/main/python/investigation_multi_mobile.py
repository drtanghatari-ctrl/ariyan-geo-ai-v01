"""
investigation_multi_mobile.py — Multi-evidence-source investigation entry
point called from Kotlin (via Chaquopy): DEM + NDVI + Thermal correlation.

Mirrors investigation_mobile.py's pattern (JSON string return, no
scipy, no file I/O) but runs DEM through anomaly detection, then
independently checks each DEM candidate against real Copernicus
Sentinel-2 NDVI AND real Landsat 8/9 thermal data, cross-referencing
all three via a per-candidate combiner to produce CORROBORATED /
SINGLE_SOURCE status -- and now which of NDVI and/or THERMAL actually
corroborated each candidate.

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

NEW THIS SESSION -- REAL THERMAL (Landsat 8/9 surface temperature) AS A
GENUINE THIRD PER-CANDIDATE CORROBORATING SOURCE, not a passive
site-anchored note like GPR: a real, live, per-DEM-candidate Landsat
core/halo thermal-anomaly check (thermal_source_mobile.
fetch_thermal_core_halo_check(), see that module's own docstring for
the full physical/statistical reasoning) is ALWAYS attempted for every
DEM candidate, using the SAME Copernicus OAuth credentials already
entered for NDVI (same account, different Sentinel Hub collection --
see thermal_source_mobile.py). Runs INDEPENDENTLY of whichever NDVI
path succeeds or fails this run.

In the common case (live per-candidate NDVI succeeds for at least one
candidate), NDVI and Thermal results are combined per-candidate via
_build_correlated_candidates() below -- a single CorrelatedCandidate per
DEM candidate whose supporting_sources reflects whichever of NDVI/
THERMAL actually corroborated it (["DEM"], ["DEM","NDVI"],
["DEM","THERMAL"], or ["DEM","NDVI","THERMAL"]).

In the rare case where live NDVI fails for EVERY candidate (triggering
the offline raster/geometric correlate_anomalies() fallback -- see
below), Thermal's per-candidate results are still fully recorded (in
fourth_evidence_detail, visible in the final record) but are NOT woven
into that fallback path's supporting_sources/notes: correlate_anomalies()
is geometric-colocation based and this module does not have
confirmed visibility into whether its output preserves a stable
1:1 index correspondence with dem_candidates, so blindly enriching it
by index risked silently attaching a Thermal result to the wrong
candidate. An honest limitations note explains this gap explicitly
rather than papering over it. Thermal currently has no offline-raster
fallback of its own (unlike NDVI) -- a real, known, honestly-noted gap,
not an oversight; can be added later the same way NDVI's was, if useful.

GPR (roadmap item 4, unchanged): when use_gpr=True, a single real GPR
manual pick (a human-read two-way travel time + chosen soil preset, see
gpr_source_mobile.py) anchored at this investigation's (lat, lon) is
converted into a depth estimate and attached as a fixed, site-anchored
(not per-candidate) evidence entry (evidence_record.py's third_evidence
slot), reported honestly with its own uncertainty range. Not yet fed
into the AI Debate Engine from this file directly -- that happens in
debate_mobile.py, called separately by MainActivity.kt.

TOKEN-CACHING + PROGRESS-REPORTING FIX (a prior session, EXTENDED this
session to cover Thermal too): a real on-device airplane-mode test
showed this module could appear to hang for several minutes with a
multi-candidate grid, because the old NDVI loop fetched a brand-new
OAuth token independently for every candidate (see ndvi_source_mobile.py's
own docstring for the full explanation) with zero visible progress in
the meantime. Fixed two ways: (1) ONE access token is now fetched for
the whole run and reused for EVERY candidate across BOTH the NDVI and
Thermal checks (they use the same Copernicus account); (2) this module
writes a small investigation_status.json into offline_data_root as it
works (phase = "dem" / "ndvi" / "thermal" / "done", plus done/total
counts for each per-candidate loop), mirroring the exact JSON shape
offline_data_manager.py already writes for offline downloads.
MainActivity.kt polls this file on a separate coroutine so "Running..."
can show real progress instead of a silent spinner. Status writes are
best-effort -- a failure to write progress must never fail the actual
investigation.

LIVE-DEM-FAILURE VISIBILITY FIX (a prior session): a real on-device
test, run WHILE genuinely online with a valid OpenTopography API key
entered, still resulted in offline DEM data being used -- meaning the
live fetch was failing for some real reason even under conditions
where it should have succeeded. Previously, if live_dem_error was set
but the offline fallback succeeded, the specific reason live failed was
discarded entirely. Fixed by appending a new limitations entry naming
the real live_dem_error whenever offline DEM was used, so a
genuinely-online failure is now diagnosable from the results screen
itself.

DIAGNOSTIC PLUMBING (a prior session): OpenTopographyAAIGridSource now
accepts offline_data_root, so that IF its live fetch times out, the
abandoned background thread's eventual real outcome (success or the
exact exception, once it finally completes) can be written to
dem_fetch_diagnostic.json for later inspection -- see
dem_source_mobile.py's own docstring for the full explanation.

CREDENTIAL NAMING NOTE (this session): the ndvi_client_id/
ndvi_client_secret parameters below are now used for BOTH the NDVI and
Thermal checks (same Copernicus Data Space Ecosystem account, verified
this session against Copernicus's own Landsat 8-9 documentation) --
they were deliberately NOT renamed to something more source-neutral
(e.g. copernicus_client_id) to avoid a breaking change to existing
Kotlin call sites that already pass these by keyword. New parameters
were added instead; only NEW arguments need to be added at the Kotlin
call site, not renamed ones.

WHETHER A LANDSAT-SCOPED TOKEN ACTUALLY WORKS FOR NDVI'S SENTINEL-2
COLLECTION TOO (AND VICE VERSA) IS NOT YET CONFIRMED ON THIS ACCOUNT --
both use the same OAuth2 client-credentials flow and the same
Copernicus Data Space Ecosystem account, which plausibly authorizes
both collections under one token, but this has not been verified
on-device yet. If it turns out a single token does NOT cover both
collections, the SYMPTOM would be one of NDVI/Thermal succeeding and
the other failing with an auth-related error for every single
candidate despite a valid token existing -- which would show up
clearly as a real, diagnosable failure (not a crash), consistent with
this project's existing graceful-degradation pattern, and could be
fixed by fetching two separate tokens instead of one if it comes to
that.
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
import thermal_source_mobile
from thermal_source_mobile import ThermalFetchError
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
    failure -- including "credentials not configured", treated the same
    honest way as a network failure). Kept as a plain dataclass so
    evidence_record.py's asdict() call works on it exactly like it does
    on AnomalyCandidate. NOTE: this has a DIFFERENT schema than
    AnomalyCandidate (core_mean/halo_mean/z_score, not
    area_cells/peak_zscore/polarity) -- evidence_record.py routes it
    into second_evidence_detail rather than the anomalies[] list
    because of that."""
    lat: float
    lon: float
    core_mean: float | None
    halo_mean: float | None
    halo_stddev: float | None
    z_score: float | None
    vegetation_stress_detected: bool
    error: str | None = None


@dataclass
class ThermalCoreHaloResult:
    """One real per-candidate Landsat thermal core/halo check result (or
    a recorded failure), used exactly like NdviCoreHaloResult -- kept as
    a plain dataclass so evidence_record.py's asdict() call works on it,
    routed into fourth_evidence_detail (never merged into anomalies[])
    since its schema (core_mean_kelvin/halo_mean_kelvin/z_score/
    core_warmer_than_halo) has nothing in common with AnomalyCandidate,
    same reasoning as NdviCoreHaloResult's own note above."""
    lat: float
    lon: float
    core_mean_kelvin: float | None
    halo_mean_kelvin: float | None
    halo_stddev: float | None
    z_score: float | None
    thermal_anomaly_detected: bool
    core_warmer_than_halo: bool | None
    error: str | None = None


class RealNdviCoreHaloEvidence:
    """Wrapper satisfying build_investigation_record's `second_evidence`
    interface (.as_evidence_record(), .source, .synthetic), since there
    is no NDVIRaster object in this mode (no raster is ever fetched --
    only per-candidate server-side statistics)."""

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


class RealThermalCoreHaloEvidence:
    """Wrapper satisfying build_investigation_record's `fourth_evidence`
    interface (.as_evidence_record(), .source, .synthetic), mirroring
    RealNdviCoreHaloEvidence exactly for the real-Thermal-via-
    Statistical-API path."""

    source = "Landsat 8/9 Level 2 (Sentinel Hub Statistical API via Copernicus Data Space Ecosystem, real per-candidate core/halo check)"
    synthetic = False

    def __init__(self, n_candidates_checked: int, n_fetch_errors: int):
        self.n_candidates_checked = n_candidates_checked
        self.n_fetch_errors = n_fetch_errors

    def as_evidence_record(self) -> dict:
        return {
            "evidence_type": "THERMAL",
            "source": self.source,
            "synthetic": self.synthetic,
            "method": (
                "Same Copernicus Data Space Ecosystem OAuth2 client-"
                "credentials account used for NDVI (auth-scope compatibility "
                "not yet on-device confirmed -- see this module's own "
                "docstring); per-DEM-candidate real Landsat 8/9 surface "
                "temperature (Kelvin) fetched server-side for a small core "
                "bbox and a larger halo bbox around each candidate (larger "
                "than NDVI's -- Landsat's thermal band is 30m resolution, "
                "resampled from ~100m native, versus Sentinel-2's 10m). A "
                "thermal anomaly is flagged when the core/halo difference "
                "clears a z-score threshold in EITHER direction (a buried "
                "feature can be warmer or cooler than its surroundings "
                "depending on material, season, and time of day -- no "
                "direction is assumed)."
            ),
            "n_candidates_checked": self.n_candidates_checked,
            "n_fetch_errors": self.n_fetch_errors,
        }


def _get_shared_copernicus_token(
    client_id: str, client_secret: str, timeout: float
) -> tuple[str | None, str | None]:
    """Fetches ONE OAuth access token to be shared across BOTH the NDVI
    and Thermal per-candidate checks this run (both use the same
    Copernicus Data Space Ecosystem account) -- extends the existing
    one-token-per-run fix (previously NDVI-only) to also cover Thermal,
    so neither source independently re-fetches its own token per
    candidate or per source.

    Returns (token_or_None, error_message_or_None). Missing credentials
    is treated exactly like a fetch failure -- callers get a uniform
    honest error message either way, applied identically to every
    candidate for both sources, rather than raising."""
    if not client_id or not client_secret:
        return None, (
            "Copernicus OAuth client ID/secret not configured yet -- enter "
            "your free client credentials (dataspace.copernicus.eu) to "
            "enable live real per-candidate NDVI/Thermal checks."
        )
    try:
        token = ndvi_source_mobile.get_access_token(client_id, client_secret, timeout=timeout)
        return token, None
    except NDVIFetchError as exc:
        return None, (
            f"Could not obtain a Copernicus access token: {exc}. This "
            f"usually means no network connection is available right "
            f"now, or the credentials are invalid. Checked once for "
            f"this entire run rather than retried per candidate/source."
        )


def _run_ndvi_checks(
    dem_candidates: list,
    client_id: str,
    client_secret: str,
    token: str | None,
    shared_error_message: str | None,
    stress_zscore_threshold: float,
    timeout: float,
    progress_callback=None,
) -> list[NdviCoreHaloResult]:
    """For each DEM candidate, run a real Copernicus NDVI core/halo
    check anchored at that candidate's location, using the pre-fetched
    shared token. Returns one NdviCoreHaloResult per candidate (success
    or honestly-recorded failure) -- does NOT build CorrelatedCandidate
    itself anymore (see _build_correlated_candidates below); this keeps
    NDVI and Thermal checking fully independent of each other and of
    however their results get combined."""
    results: list[NdviCoreHaloResult] = []
    total = len(dem_candidates)
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
            results.append(NdviCoreHaloResult(
                lat=dem_candidate.lat, lon=dem_candidate.lon,
                core_mean=None, halo_mean=None, halo_stddev=None, z_score=None,
                vegetation_stress_detected=False, error=error_message,
            ))
        else:
            results.append(NdviCoreHaloResult(
                lat=dem_candidate.lat, lon=dem_candidate.lon,
                core_mean=check["core_mean"], halo_mean=check["halo_mean"],
                halo_stddev=check["halo_stddev"], z_score=check["z_score"],
                vegetation_stress_detected=check["vegetation_stress_detected"],
            ))

        if progress_callback is not None:
            progress_callback(i + 1, total)

    return results


def _run_thermal_checks(
    dem_candidates: list,
    client_id: str,
    client_secret: str,
    token: str | None,
    shared_error_message: str | None,
    anomaly_zscore_threshold: float,
    timeout: float,
    progress_callback=None,
) -> list[ThermalCoreHaloResult]:
    """For each DEM candidate, run a real Landsat thermal core/halo
    check anchored at that candidate's location, using the SAME
    pre-fetched shared token as NDVI. Mirrors _run_ndvi_checks exactly.
    Runs regardless of whether NDVI's own checks succeeded or failed
    for any given candidate -- the two sources are fully independent."""
    results: list[ThermalCoreHaloResult] = []
    total = len(dem_candidates)
    for i, dem_candidate in enumerate(dem_candidates):
        error_message = shared_error_message
        check = None
        if error_message is None:
            try:
                check = thermal_source_mobile.fetch_thermal_core_halo_check(
                    dem_candidate.lat, dem_candidate.lon,
                    client_id, client_secret,
                    anomaly_zscore_threshold=anomaly_zscore_threshold,
                    timeout=timeout,
                    access_token=token,
                )
            except ThermalFetchError as exc:
                error_message = str(exc)

        if error_message is not None:
            results.append(ThermalCoreHaloResult(
                lat=dem_candidate.lat, lon=dem_candidate.lon,
                core_mean_kelvin=None, halo_mean_kelvin=None, halo_stddev=None,
                z_score=None, thermal_anomaly_detected=False,
                core_warmer_than_halo=None, error=error_message,
            ))
        else:
            results.append(ThermalCoreHaloResult(
                lat=dem_candidate.lat, lon=dem_candidate.lon,
                core_mean_kelvin=check["core_mean_kelvin"],
                halo_mean_kelvin=check["halo_mean_kelvin"],
                halo_stddev=check["halo_stddev"], z_score=check["z_score"],
                thermal_anomaly_detected=check["thermal_anomaly_detected"],
                core_warmer_than_halo=check["core_warmer_than_halo"],
            ))

        if progress_callback is not None:
            progress_callback(i + 1, total)

    return results


def _build_correlated_candidates(
    dem_candidates: list,
    ndvi_results: list[NdviCoreHaloResult],
    thermal_results: list[ThermalCoreHaloResult],
) -> list[CorrelatedCandidate]:
    """Combines per-candidate NDVI and Thermal results into ONE
    CorrelatedCandidate per DEM candidate, reflecting whichever real
    source(s) actually corroborated it. supporting_sources is always
    DEM plus zero, one, or both of NDVI/THERMAL, in that order --
    NEVER a candidate that "loses" a real corroborating result just
    because the other source also happened to succeed or fail.

    A per-candidate failure on either source is recorded honestly in
    the combined_confidence_note (not silently dropped), and does not
    prevent the OTHER source from still corroborating that candidate --
    e.g. if NDVI failed but Thermal detected a real anomaly, the
    candidate is still CORROBORATED via DEM+THERMAL, with NDVI's
    unavailability noted honestly alongside it.

    Sorted the same way the previous NDVI-only version was: CORROBORATED
    first, then by number of supporting sources descending.
    """
    out: list[CorrelatedCandidate] = []
    for i, dem_candidate in enumerate(dem_candidates):
        sources = ["DEM"]
        notes = []

        nr = ndvi_results[i]
        if nr.error is not None:
            notes.append(f"Real NDVI check unavailable for this candidate: {nr.error}.")
        elif nr.vegetation_stress_detected:
            sources.append("NDVI")
            notes.append(
                f"Real Copernicus Sentinel-2 NDVI shows significant "
                f"vegetation stress at this DEM candidate "
                f"(core mean={nr.core_mean:.4f} vs halo mean="
                f"{nr.halo_mean:.4f}, z={nr.z_score:.2f})."
            )
        else:
            notes.append(
                f"Real Copernicus Sentinel-2 NDVI at this DEM candidate "
                f"shows no significant vegetation stress "
                f"(core mean={nr.core_mean:.4f} vs halo mean="
                f"{nr.halo_mean:.4f}, z={nr.z_score:.2f})."
            )

        tr = thermal_results[i]
        if tr.error is not None:
            notes.append(f"Real Landsat thermal check unavailable for this candidate: {tr.error}.")
        elif tr.thermal_anomaly_detected:
            sources.append("THERMAL")
            direction = "warmer than" if tr.core_warmer_than_halo else "cooler than"
            notes.append(
                f"Real Landsat 8/9 surface temperature shows this DEM "
                f"candidate is significantly {direction} its surroundings "
                f"(core mean={tr.core_mean_kelvin:.1f}K vs halo mean="
                f"{tr.halo_mean_kelvin:.1f}K, z={tr.z_score:.2f})."
            )
        else:
            notes.append(
                f"Real Landsat 8/9 surface temperature at this DEM "
                f"candidate shows no significant thermal anomaly "
                f"(core mean={tr.core_mean_kelvin:.1f}K vs halo mean="
                f"{tr.halo_mean_kelvin:.1f}K, z={tr.z_score:.2f})."
            )

        n_independent = len(sources) - 1  # sources beyond DEM itself
        if n_independent >= 1:
            status = "CORROBORATED"
            note = (
                " ".join(notes) +
                f" This is genuine independent corroboration from "
                f"{n_independent} real source(s) beyond DEM -- confidence "
                f"should be treated as MODERATE to HIGH, still pending "
                f"field verification."
            )
        else:
            status = "SINGLE_SOURCE"
            note = " ".join(notes) + " No independent corroboration found. Confidence remains LOW."

        out.append(CorrelatedCandidate(
            lat=dem_candidate.lat,
            lon=dem_candidate.lon,
            status=status,
            supporting_sources=sources,
            source_candidates={"DEM": dem_candidate},
            distance_between_peaks_m=0.0,
            combined_confidence_note=note,
        ))

    out.sort(key=lambda r: (r.status != "CORROBORATED", -len(r.supporting_sources)))
    return out


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
    whole DEM/NDVI/Thermal investigation it's attached to.

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
    thermal_zscore_threshold: float = 1.5,
    thermal_timeout_s: float = 8.0,
    offline_data_root: str = "",
    use_gpr: bool = False,
    gpr_soil_preset_key: str | None = None,
    gpr_two_way_time_ns: float | None = None,
    gpr_entry_method: str = "manual",
    gpr_device_note: str = "",
) -> str:
    """Run a DEM + NDVI + Thermal investigation and return the
    InvestigationRecord as a JSON string. This is the function
    MainActivity.kt calls when the "Include NDVI correlation" switch
    is on (Thermal now runs automatically alongside it -- no separate
    toggle, same as NDVI itself has none).

    DEM: real (OpenTopography) always attempted first via api_key; on
    failure, falls back to this device's offline DEM library. If both
    fail, raises OpenTopographyFetchError naming both real reasons. If
    offline DEM was used, the real live-fetch error is also appended to
    the result's limitations so a genuinely-online failure is
    diagnosable from the results screen. If the live fetch times out,
    the abandoned background thread's eventual real outcome is also
    reported separately to dem_fetch_diagnostic.json (see
    dem_source_mobile.py's own docstring) for deeper debugging.

    NDVI: real (Copernicus Sentinel Hub Statistical API, per-DEM-candidate
    core/halo check) always attempted first via ndvi_client_id/secret,
    using ONE shared access token for the whole run (now shared with
    Thermal too). If EVERY candidate's live check failed, falls back to
    this device's offline Sentinel-2 composite (a full-AOI raster,
    independently scanned and correlated against the DEM candidates --
    can find NDVI anomalies the per-candidate check couldn't). If
    that's also unavailable, the honest per-candidate-failure results
    are kept and DEM results are still returned -- an NDVI-side failure
    never blocks the DEM investigation itself.

    THERMAL (new this session): real (Landsat 8/9 via the same
    Copernicus Sentinel Hub Statistical API/account as NDVI,
    per-DEM-candidate core/halo check, see thermal_source_mobile.py)
    always attempted for every DEM candidate, using the SAME shared
    access token as NDVI. Runs independently of NDVI's own success or
    failure. In the common case (live NDVI succeeds for at least one
    candidate), NDVI and Thermal results are combined per-candidate so
    a single candidate can be corroborated by either or both. In the
    rare case where live NDVI fails for every candidate (triggering the
    offline NDVI raster fallback), Thermal's results are still fully
    recorded (fourth_evidence_detail) but are NOT folded into that
    fallback's per-candidate correlation notes -- see this module's own
    docstring for why (unconfirmed index/geometric alignment guarantees
    in that code path). Thermal has no offline-raster fallback of its
    own yet (a real, known, honestly-noted gap, unlike NDVI).

    GPR (optional, use_gpr=True): a single real manual pick (two-way
    travel time + soil preset) anchored at this investigation's
    (lat, lon), attached as a single, site-anchored (not per-candidate)
    evidence entry. All gpr_* parameters default to off/empty.

    Writes investigation_status.json into offline_data_root as it works
    (phase "dem" / "ndvi" / "thermal" / "done"), polled by
    MainActivity.kt for live progress display. Best-effort -- never
    raises on its own.

    Raises ValueError if use_gpr=True without both gpr_soil_preset_key
    and gpr_two_way_time_ns. Raises OpenTopographyFetchError if DEM is
    unavailable both live and offline (see above) -- this is the only
    hard failure; every NDVI-side, Thermal-side, and GPR-side failure
    degrades gracefully with an honest limitations[] entry instead.
    """
    _write_investigation_status(offline_data_root, "dem", 0, 1)

    center = GeoPoint(lat, lon)
    aoi = build_aoi(center, radius_m=radius_m, grid_size=grid_size)

    # --- DEM: real-first, offline-fallback (same pattern as investigation_mobile.py) ---
    live_dem_error: OpenTopographyFetchError | None = None
    dem = None
    if api_key:
        try:
            dem = OpenTopographyAAIGridSource(
                api_key, demtype=demtype, offline_data_root=offline_data_root,
            ).fetch(aoi)
        except OpenTopographyFetchError as exc:
            live_dem_error = exc
    else:
        live_dem_error = OpenTopographyFetchError(
            "No OpenTopography API key is configured yet -- enter your "
            "free key (opentopography.org) to enable live real DEM fetch."
        )

    used_offline_dem = False
    if dem is None:
        used_offline_dem = True
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

    # --- Shared Copernicus token, fetched ONCE for both NDVI and Thermal ---
    n_candidates = len(dem_candidates)
    token, token_error_message = _get_shared_copernicus_token(
        ndvi_client_id, ndvi_client_secret, timeout=ndvi_timeout_s,
    )

    # --- NDVI: real per-candidate check first ---
    _write_investigation_status(offline_data_root, "ndvi", 0, max(1, n_candidates))

    def _report_ndvi_progress(done: int, total: int) -> None:
        _write_investigation_status(offline_data_root, "ndvi", done, total)

    ndvi_results = _run_ndvi_checks(
        dem_candidates, ndvi_client_id, ndvi_client_secret,
        token, token_error_message,
        stress_zscore_threshold=1.5,
        timeout=ndvi_timeout_s,
        progress_callback=_report_ndvi_progress,
    )
    n_ndvi_errors = sum(1 for r in ndvi_results if r.error is not None)

    # --- THERMAL: real per-candidate check, independent of NDVI's outcome ---
    _write_investigation_status(offline_data_root, "thermal", 0, max(1, n_candidates))

    def _report_thermal_progress(done: int, total: int) -> None:
        _write_investigation_status(offline_data_root, "thermal", done, total)

    thermal_results = _run_thermal_checks(
        dem_candidates, ndvi_client_id, ndvi_client_secret,
        token, token_error_message,
        anomaly_zscore_threshold=thermal_zscore_threshold,
        timeout=thermal_timeout_s,
        progress_callback=_report_thermal_progress,
    )
    n_thermal_errors = sum(1 for r in thermal_results if r.error is not None)

    second_evidence: object = RealNdviCoreHaloEvidence(
        n_candidates_checked=n_candidates, n_fetch_errors=n_ndvi_errors,
    )
    fourth_evidence: object = RealThermalCoreHaloEvidence(
        n_candidates_checked=n_candidates, n_fetch_errors=n_thermal_errors,
    )
    used_offline_ndvi = False
    ndvi_limitations: list[str] = []
    thermal_limitations: list[str] = []

    if dem_candidates and n_ndvi_errors == n_candidates:
        # Every candidate's LIVE NDVI check failed this run -- fall back
        # to the offline raster/geometric path. Thermal's own results
        # are UNCHANGED by this (still fully recorded below in
        # fourth_evidence_detail) but are deliberately not woven into
        # this fallback's own supporting_sources/notes -- see this
        # module's docstring for why.
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
            thermal_limitations.append(
                "Because NDVI fell back to the offline raster/geometric "
                "correlation path this run, Thermal's per-candidate "
                "results (recorded below) were NOT combined into that "
                "path's supporting_sources/notes -- this module does not "
                "have confirmed visibility into whether that path "
                "preserves a stable per-candidate correspondence, and "
                "guessing at it risked attaching a Thermal result to the "
                "wrong candidate. Thermal has no offline-raster fallback "
                "of its own yet."
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
            second_anomalies = ndvi_results
            second_anomalies_are_candidates = False
            correlation_results = _build_correlated_candidates(
                dem_candidates, ndvi_results, thermal_results,
            )
    else:
        # The common case: live NDVI succeeded for at least one
        # candidate. Combine NDVI + Thermal per-candidate, fully.
        second_anomalies = ndvi_results
        second_anomalies_are_candidates = False
        correlation_results = _build_correlated_candidates(
            dem_candidates, ndvi_results, thermal_results,
        )
        if n_ndvi_errors > 0:
            ndvi_limitations.append(
                f"{n_ndvi_errors} of {n_candidates} candidate(s) had a real "
                f"NDVI check unavailable (network/auth/no-data) and were "
                f"recorded with the real reason rather than silently "
                f"dropped or faked."
            )

    if n_thermal_errors > 0 and n_thermal_errors < n_candidates:
        thermal_limitations.append(
            f"{n_thermal_errors} of {n_candidates} candidate(s) had a real "
            f"Thermal check unavailable (network/auth/no-data/cloud cover) "
            f"and were recorded with the real reason rather than silently "
            f"dropped or faked."
        )
    elif n_thermal_errors == n_candidates and n_candidates > 0:
        thermal_limitations.append(
            f"Real Thermal checks were unavailable for every candidate "
            f"this run: {thermal_results[0].error}. Thermal contributed "
            f"no corroboration this run; DEM/NDVI results above are "
            f"unaffected."
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
        fourth_evidence=fourth_evidence,
        fourth_anomalies=thermal_results,
        fourth_evidence_type="THERMAL",
    )

    if used_offline_dem:
        record.limitations.append(
            f"This run used the offline DEM library, not a live fetch -- "
            f"the live OpenTopography attempt failed with: {live_dem_error}. "
            f"If you expected a live fetch to succeed (e.g. you have "
            f"network and a valid API key), this real error message is the "
            f"actual reason it didn't."
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
    record.limitations.append(
        "Real Thermal in this run is, like NDVI's real per-candidate "
        "check, a TARGETED PER-CANDIDATE check (core bbox vs. halo bbox "
        "around each DEM candidate), not an independent full-grid "
        "thermal scan -- it cannot discover a candidate that DEM missed, "
        "only confirm or fail to confirm a thermal anomaly at locations "
        "DEM already flagged. Landsat's 30m (resampled from ~100m native) "
        "thermal resolution is coarser than Sentinel-2's 10m used for "
        "NDVI, and a thermal anomaly can arise from many causes besides "
        "a buried feature (soil moisture, shadow, recent land use) -- no "
        "causal interpretation should be inferred from this check alone."
    )
    for note in ndvi_limitations:
        record.limitations.append(note)
    for note in thermal_limitations:
        record.limitations.append(note)
    if gpr_limitation:
        record.limitations.append(gpr_limitation)

    _write_investigation_status(offline_data_root, "done", max(1, n_candidates), max(1, n_candidates))

    return record.to_json()