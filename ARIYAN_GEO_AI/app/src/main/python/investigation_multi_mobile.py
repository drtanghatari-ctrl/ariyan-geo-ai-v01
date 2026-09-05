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

TOKEN-CACHING + PROGRESS-REPORTING FIX (a prior session): a real
on-device airplane-mode test showed this module could appear to hang
for several minutes with a multi-candidate grid, because the old NDVI
loop fetched a brand-new OAuth token independently for every candidate
(see ndvi_source_mobile.py's own docstring for the full explanation)
with zero visible progress in the meantime. Fixed two ways: (1) the
NDVI loop below fetches ONE access token for the whole run and reuses
it for every candidate; (2) this module writes a small
investigation_status.json into offline_data_root as it works (phase =
"dem" / "ndvi" / "done", plus done/total counts for the NDVI loop),
mirroring the exact JSON shape offline_data_manager.py already writes
for offline downloads. MainActivity.kt polls this file on a separate
coroutine so "Running..." can show real progress instead of a silent
spinner. Status writes are best-effort -- a failure to write progress
must never fail the actual investigation.

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

DIAGNOSTIC PLUMBING (this session): OpenTopographyAAIGridSource now
accepts offline_data_root, so that IF its live fetch times out, the
abandoned background thread's eventual real outcome (success or the
exact exception, once it finally completes) can be written to
dem_fetch_diagnostic.json for later inspection -- see
dem_source_mobile.py's own docstring for the full explanation. This is
the only change in this file this session: passing offline_data_root
through to that constructor. Everything else is unchanged.
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

    Fetches ONE OAuth access token up front for the entire run (rather
    than every candidate fetching its own -- see this module's and
    ndvi_source_mobile.py's docstrings). If that single token fetch
    fails (e.g. no network at all, which is the realistic on-device
    signature this was built to fix), every candidate is marked failed
    immediately with that same real error message instead of every
    candidate separately retrying and timing out. `progress_
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