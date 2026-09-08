"""
investigation_multi_mobile.py -- Multi-evidence-source investigation entry
point called from Kotlin (via Chaquopy): DEM + NDVI + Thermal + Optical
correlation, plus optional single-reading GPR + ERT field verification,
plus AUTOMATIC detection-stability checking for borderline DEM candidates
(added this session -- see DETECTION STABILITY section below).

Mirrors investigation_mobile.py's pattern (JSON string return, no
scipy, no file I/O) but runs DEM through anomaly detection, then
independently checks each DEM candidate against real Copernicus
Sentinel-2 NDVI, real Landsat 8/9 thermal data, AND real Sentinel-2
visible-band optical brightness, cross-referencing all four via a
per-candidate combiner to produce CORROBORATED / SINGLE_SOURCE status --
plus which of NDVI, THERMAL, and/or OPTICAL actually corroborated each
candidate. GPR and ERT (both optional, single-reading, site-anchored)
are handled separately (see their own sections below) since neither is
a per-candidate corroborating check.

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

REAL THERMAL (a prior session) -- A GENUINE THIRD PER-CANDIDATE
CORROBORATING SOURCE, not a passive site-anchored note like GPR: a
real, live, per-DEM-candidate Landsat core/halo thermal-anomaly check
(thermal_source_mobile.fetch_thermal_core_halo_check(), see that
module's own docstring for the full physical/statistical reasoning) is
ALWAYS attempted for every DEM candidate, using the SAME Copernicus
OAuth credentials already entered for NDVI (same account, different
Sentinel Hub collection -- see thermal_source_mobile.py). Runs
INDEPENDENTLY of whichever NDVI path succeeds or fails this run.

REAL OPTICAL (a prior session) -- A GENUINE FOURTH PER-CANDIDATE
CORROBORATING SOURCE (real Sentinel-2 visible-band brightness /
"soilmark" check, see optical_source_mobile.py for the full
physical/statistical reasoning and the honest masking-design-decision
note). Uses the SAME Copernicus OAuth account and the SAME shared
per-run access token as NDVI and Thermal (Optical is on the same
sentinel-2-l2a collection NDVI already uses -- no new credential type
needed). Runs INDEPENDENTLY of whichever NDVI/Thermal path succeeds or
fails this run, following the exact same _run_X_checks() /
RealXCoreHaloEvidence() pattern Thermal established.

In the common case (live per-candidate NDVI succeeds for at least one
candidate), NDVI, Thermal, and Optical results are combined per-candidate
via _build_correlated_candidates() below -- a single CorrelatedCandidate
per DEM candidate whose supporting_sources reflects whichever of NDVI/
THERMAL/OPTICAL actually corroborated it (any subset of
["DEM","NDVI","THERMAL","OPTICAL"], DEM always present).

In the rare case where live NDVI fails for EVERY candidate (triggering
the offline raster/geometric correlate_anomalies() fallback -- see
below), Thermal's AND Optical's per-candidate results are still fully
recorded (in fourth_evidence_detail / fifth_evidence_detail respectively,
visible in the final record) but are NOT woven into that fallback path's
supporting_sources/notes: correlate_anomalies() is geometric-colocation
based and this module does not have confirmed visibility into whether
its output preserves a stable 1:1 index correspondence with
dem_candidates, so blindly enriching it by index risked silently
attaching a Thermal or Optical result to the wrong candidate. An honest
limitations note explains this gap explicitly rather than papering over
it. Neither Thermal nor Optical currently has an offline-raster fallback
of its own (unlike NDVI) -- a real, known, honestly-noted gap, not an
oversight; can be added later the same way NDVI's was, if useful.

GPR (roadmap item 4, unchanged): when use_gpr=True, a single real GPR
manual pick (a human-read two-way travel time + chosen soil preset, see
gpr_source_mobile.py) anchored at this investigation's (lat, lon) is
converted into a depth estimate and attached as a fixed, site-anchored
(not per-candidate) evidence entry (evidence_record.py's third_evidence
slot), reported honestly with its own uncertainty range. Not yet fed
into the AI Debate Engine from this file directly -- that happens in
debate_mobile.py, called separately by MainActivity.kt.

ERT (a prior session): when use_ert=True, a single real ERT manual
reading (a human-read resistivity value + depth, already read off an
already-inverted profile -- see ert_source_mobile.py) anchored at this
investigation's (lat, lon) is classified against documented reference
resistivity ranges and attached as a fixed, site-anchored (not
per-candidate) evidence entry (evidence_record.py's sixth_evidence
slot), mirroring GPR's own wiring exactly via _build_ert_evidence()
below. Like GPR, not fed into the AI Debate Engine from this file
directly -- that happens in debate_mobile.py.

DETECTION STABILITY, ADDED THIS SESSION: real on-device testing (18+
live investigations across two real sites, see project notes) found
that detect_anomalies() -- which z-scores each cell against a regional
trend computed from whatever terrain falls inside THIS investigation's
own fetched AOI window -- can genuinely disagree with itself: the same
physical terrain, fetched via a differently-centered (and therefore
differently-bounded) live OpenTopography request, can score meaningfully
differently or drop below threshold entirely. This was found to
correlate closely with how close a candidate's own |z| sits to
dem_zscore_threshold: candidates well above threshold (|z| >~3.2 in
real testing) were rock-solid across every re-fetch tested; candidates
close to threshold (|z| <~3.0) frequently failed to reproduce.

This module now AUTOMATICALLY (no user toggle) re-fetches and
re-detects around any DEM candidate whose |z| falls within
STABILITY_MARGIN_DEFAULT of dem_zscore_threshold -- exactly the
borderline population real testing showed was actually fragile --
capped at MAX_AUTO_STABILITY_CANDIDATES_DEFAULT candidates per
investigation (nearest-to-threshold prioritized if more candidates
qualify than the cap allows), so a multi-candidate run can't silently
multiply live DEM fetches without bound, given this project's real
network constraints. Each offset re-fetch reuses the exact same real
live-first/offline-fallback pattern as the PRIMARY DEM fetch (see
_fetch_dem_for_stability()) -- a stability sub-fetch failing is
recorded honestly as "not tested" for that window, never silently
treated as "not detected," and never fails the investigation itself.

This makes real window-instability VISIBLE for exactly the candidates
where it matters -- it does NOT, and cannot, fix the underlying window
sensitivity itself. detect_anomalies() is unchanged; this is a
diagnostic layer on top of it, feeding into Scientific Steward's
confidence ceiling (see steward_confidence_ceiling.py) as an
UNCONDITIONAL cap for fragile candidates, same priority tier as
has_contradiction -- no amount of field validation or source count can
rescue a candidate whose own detection is not reproducible.

Results are recorded via evidence_record.py's SEVENTH evidence slot
(seventh_evidence/seventh_anomalies/seventh_evidence_type), following
the fourth/fifth (Thermal/Optical) aggregate-plus-detail-list pattern,
with one difference: this is NOT run for every DEM candidate, only the
borderline subset that qualified -- see evidence_record.py's own
docstring for exactly how that's reflected.

TOKEN-CACHING + PROGRESS-REPORTING FIX (a prior session, EXTENDED across
Thermal, Optical, and now Detection Stability): a real on-device
airplane-mode test showed this module could appear to hang for several
minutes with a multi-candidate grid, because the old NDVI loop fetched
a brand-new OAuth token independently for every candidate (see
ndvi_source_mobile.py's own docstring for the full explanation) with
zero visible progress in the meantime. Fixed two ways: (1) ONE access
token is now fetched for the whole run and reused for EVERY candidate
across NDVI, Thermal, AND Optical (GPR, ERT, and Detection Stability
need no token at all -- Stability is manual-key-only DEM fetches, not
Copernicus); (2) this module writes a small investigation_status.json
into offline_data_root as it works (phase = "dem" / "ndvi" / "thermal"
/ "optical" / "stability" / "done", plus done/total counts for each
per-candidate loop), mirroring the exact JSON shape
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

CREDENTIAL NAMING NOTE: the ndvi_client_id/ndvi_client_secret parameters
below are now used for NDVI, Thermal, AND Optical (same Copernicus Data
Space Ecosystem account, verified against Copernicus's own Sentinel-2/
Landsat 8-9 documentation) -- they were deliberately NOT renamed to
something more source-neutral (e.g. copernicus_client_id) to avoid a
breaking change to existing Kotlin call sites that already pass these
by keyword. New parameters were added instead; only NEW arguments need
to be added at the Kotlin call site, not renamed ones. GPR, ERT, and
Detection Stability need no Copernicus credentials at all (GPR/ERT are
manual-entry-only; Stability re-uses the OpenTopography api_key/demtype
already passed for the primary DEM fetch), so this naming note does not
apply to any of the three.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from coordinate import GeoPoint, build_aoi, offset_point, haversine_distance_m
from anomaly_detection_mobile import detect_anomalies, detect_raster_anomalies
from correlation import correlate_anomalies, CorrelatedCandidate
from evidence_record import build_investigation_record
import ndvi_source_mobile
from ndvi_source_mobile import NDVIFetchError
import thermal_source_mobile
from thermal_source_mobile import ThermalFetchError
import optical_source_mobile
from optical_source_mobile import OpticalFetchError
from gpr_source_mobile import GPRSurvey, GPRPick, estimate_depths, GPREvidence
from gpr_depth_model import GPRDepthModelError
from ert_source_mobile import ERTSurvey, ERTReading, classify_survey, ERTEvidence
from ert_resistivity_model import ERTResistivityModelError
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


@dataclass
class OpticalCoreHaloResult:
    """One real per-candidate Sentinel-2 visible-brightness core/halo
    check result (or a recorded failure) -- used exactly like
    NdviCoreHaloResult/ThermalCoreHaloResult -- kept as a plain
    dataclass so evidence_record.py's asdict() call works on it, routed
    into fifth_evidence_detail (never merged into anomalies[]) since its
    schema (core_mean/halo_mean/z_score/core_brighter_than_halo) has
    nothing in common with AnomalyCandidate, same reasoning as the other
    two per-candidate check results above."""
    lat: float
    lon: float
    core_mean: float | None
    halo_mean: float | None
    halo_stddev: float | None
    z_score: float | None
    optical_anomaly_detected: bool
    core_brighter_than_halo: bool | None
    error: str | None = None


# --- DETECTION STABILITY (added this session) ---

DEFAULT_AUTO_STABILITY_OFFSETS_M: list[tuple[float, float]] = [
    (15.0, 0.0), (-15.0, 0.0), (0.0, 15.0), (0.0, -15.0),
]  # (north_m, east_m) pairs. 4 offsets + the candidate's own primary
   # detection = 5 total data points per tested candidate -- enough to
   # distinguish the real "rock-solid vs. fragile" pattern found in
   # manual testing (11-offset grids) without multiplying live fetches
   # by more than 5x for the (at most MAX_AUTO_STABILITY_CANDIDATES)
   # candidates that actually qualify.

STABILITY_MARGIN_DEFAULT = 1.0  # |z| within threshold+this margin triggers
                                 # the automatic check. From real testing:
                                 # the fragile band observed was roughly
                                 # |z| 2.6-3.0 against a 2.5 threshold --
                                 # a margin of 1.0 (triggering up to
                                 # |z|~3.5) deliberately keeps buffer above
                                 # that observed fragile band. A first
                                 # real calibration, not a settled
                                 # scientific constant -- expect this to
                                 # be revisited as more real investigations
                                 # accumulate.

MAX_AUTO_STABILITY_CANDIDATES_DEFAULT = 2  # hard cap on how many
                                            # candidates in one
                                            # investigation can trigger
                                            # the automatic check, so a
                                            # run with many borderline
                                            # candidates can't multiply
                                            # live DEM fetches without
                                            # bound.

STABILITY_MATCH_TOLERANCE_M_DEFAULT: float | None = None  # None = derive
                                            # from aoi.cell_size_m * 4,
                                            # the same colocation-style
                                            # default already used
                                            # elsewhere in this module
                                            # (see _gpr_colocation_
                                            # distance_m/_ert_colocation_
                                            # distance_m in
                                            # debate_mobile.py).


@dataclass
class StabilityResult:
    """Result of re-fetching+re-detecting around ONE DEM candidate at
    several genuinely independent offset centers, to measure whether
    that candidate's detection is robust to exact AOI window placement
    or an artifact of one specific fetch. lat/lon match the naming
    convention every other per-candidate evidence dataclass in this
    file uses (NdviCoreHaloResult etc.), so evidence_record.py's
    generic fourth/fifth-style asdict() handling and debate_mobile.py's
    generic per-candidate lat/lon matching both work unchanged. A
    candidate this was never run for (not near dem_zscore_threshold, or
    the per-investigation cap was already reached) has no StabilityResult
    at all -- this dataclass is only ever constructed for a candidate
    the check actually ran on."""
    lat: float
    lon: float
    target_zscore: float
    n_windows_attempted: int
    n_windows_fetched: int       # offset fetches that succeeded (live or offline)
    n_windows_detected: int      # of the fetched windows, how many
                                  # re-detected a matching candidate
                                  # within match_tolerance_m
    stability_score: float | None  # n_windows_detected / n_windows_fetched,
                                    # or None if n_windows_fetched == 0
                                    # (every re-fetch failed -- honestly
                                    # "could not be tested", not "unstable")
    z_min: float | None
    z_max: float | None
    offset_errors: list[str]     # honest per-offset failure reasons, if any


class StabilityCheckEvidence:
    """Wrapper satisfying build_investigation_record's `seventh_evidence`
    interface (.as_evidence_record(), .source, .synthetic), describing
    the METHOD used this run (margin, offsets, candidate count) rather
    than any one candidate's result -- mirrors RealThermalCoreHaloEvidence/
    RealOpticalCoreHaloEvidence in shape."""

    source = "Automatic re-fetch/re-detect at offset AOI windows around this investigation's own DEM candidates"
    synthetic = False

    def __init__(self, n_candidates_tested: int, margin: float, offsets_m: list[tuple[float, float]]):
        self.n_candidates_tested = n_candidates_tested
        self.margin = margin
        self.offsets_m = offsets_m

    def as_evidence_record(self) -> dict:
        return {
            "evidence_type": "DETECTION_STABILITY",
            "source": self.source,
            "synthetic": self.synthetic,
            "method": (
                "For each DEM candidate whose |peak z-score| falls within "
                f"{self.margin:g} of dem_zscore_threshold, this investigation's "
                "AOI is re-fetched (live OpenTopography, same offline "
                "fallback as the primary DEM fetch) and re-detected at "
                f"{len(self.offsets_m)} independent offset centers "
                "around that candidate's own coordinates, holding every "
                "other detection parameter (grid_size, kernel sigma, "
                "z-score threshold) fixed. stability_score is the "
                "fraction of successfully re-fetched offset windows that "
                "reproduced a matching candidate within a colocation-"
                "style distance tolerance. This measures sensitivity to "
                "exact AOI window placement specifically -- it does not "
                "and cannot correct the underlying detection, only "
                "report how reproducible it was found to be."
            ),
            "n_candidates_tested": self.n_candidates_tested,
        }


def _fetch_dem_for_stability(
    center: GeoPoint,
    radius_m: float,
    grid_size: int,
    api_key: str,
    demtype: str,
    offline_data_root: str,
):
    """Fetch a single DEM raster at `center`, live-first with offline
    fallback -- the SAME real pattern as run_investigation_multi_json()'s
    own primary DEM fetch (see that function below). Factored out so the
    primary fetch and every stability offset fetch share one real
    implementation rather than two copies that could silently drift
    apart. Raises OpenTopographyFetchError (naming BOTH the live and
    offline failure reasons, same as the primary path) only when
    neither live nor offline succeeds -- callers (the stability loop)
    catch that and record it as an honest per-offset failure rather
    than letting it escape."""
    aoi = build_aoi(center, radius_m=radius_m, grid_size=grid_size)
    live_error: OpenTopographyFetchError | None = None
    dem = None
    if api_key:
        try:
            dem = OpenTopographyAAIGridSource(
                api_key, demtype=demtype, offline_data_root=offline_data_root,
            ).fetch(aoi)
        except OpenTopographyFetchError as exc:
            live_error = exc
    else:
        live_error = OpenTopographyFetchError(
            "No OpenTopography API key is configured yet -- enter your "
            "free key (opentopography.org) to enable live real DEM fetch."
        )

    if dem is None:
        try:
            dem = fetch_offline_dem(aoi, offline_data_root)
        except OfflineDataUnavailableError as offline_error:
            raise OpenTopographyFetchError(
                f"Live DEM fetch failed ({live_error}) and no offline "
                f"data is available for this location either "
                f"({offline_error})."
            ) from offline_error

    return dem


def _run_stability_check(
    dem_candidate,
    radius_m: float,
    api_key: str,
    demtype: str,
    offline_data_root: str,
    grid_size: int,
    dem_kernel_sigma_cells: float,
    dem_zscore_threshold: float,
    offset_pattern_m: list[tuple[float, float]] = DEFAULT_AUTO_STABILITY_OFFSETS_M,
    match_tolerance_m: float | None = STABILITY_MATCH_TOLERANCE_M_DEFAULT,
) -> StabilityResult:
    """Re-fetch and re-detect around ONE DEM candidate at several real,
    independent offset centers (see offset_pattern_m), and report how
    many genuinely reproduce a matching candidate.

    `radius_m` MUST be the same radius_m the primary investigation used
    to fetch dem_candidate in the first place -- it is not stored on
    AnomalyCandidate itself, so callers pass it through explicitly
    (see run_investigation_multi_json()'s call site) rather than this
    function silently guessing or re-deriving it.

    Each offset uses the SAME live-first/offline-fallback pattern as the
    primary DEM fetch (via _fetch_dem_for_stability() above). A fetch
    failure for one offset is recorded in offset_errors and simply
    excluded from n_windows_fetched/n_windows_detected; it never raises
    out of this function (mirrors this module's existing "one failure
    never fails the whole investigation" philosophy for
    NDVI/Thermal/Optical/GPR/ERT).

    grid_size, dem_kernel_sigma_cells, and dem_zscore_threshold are
    intentionally the SAME as the primary investigation's own -- this
    tests sensitivity to WINDOW PLACEMENT specifically, holding every
    other detection parameter fixed, exactly matching how this was
    tested manually before being automated.
    """
    target = GeoPoint(dem_candidate.lat, dem_candidate.lon)
    n_attempted = len(offset_pattern_m)
    n_fetched = 0
    n_detected = 0
    z_scores: list[float] = []
    errors: list[str] = []

    resolved_tolerance_m = match_tolerance_m

    for north_m, east_m in offset_pattern_m:
        offset_center = offset_point(target, north_m, east_m)
        try:
            offset_dem = _fetch_dem_for_stability(
                offset_center, radius_m, grid_size, api_key, demtype, offline_data_root,
            )
        except OpenTopographyFetchError as exc:
            errors.append(
                f"Offset (north={north_m:+.0f}m, east={east_m:+.0f}m): {exc}"
            )
            continue

        n_fetched += 1
        if resolved_tolerance_m is None:
            resolved_tolerance_m = max(30.0, offset_dem.aoi.cell_size_m * 4)

        offset_candidates = detect_anomalies(
            offset_dem,
            kernel_sigma_cells=dem_kernel_sigma_cells,
            zscore_threshold=dem_zscore_threshold,
            min_area_cells=3,
        )

        best = None
        best_dist = None
        for c in offset_candidates:
            d = haversine_distance_m(target, GeoPoint(c.lat, c.lon))
            if best_dist is None or d < best_dist:
                best, best_dist = c, d

        if best is not None and best_dist is not None and best_dist <= resolved_tolerance_m:
            n_detected += 1
            z_scores.append(best.peak_zscore)

    stability_score = (n_detected / n_fetched) if n_fetched > 0 else None

    return StabilityResult(
        lat=dem_candidate.lat,
        lon=dem_candidate.lon,
        target_zscore=dem_candidate.peak_zscore,
        n_windows_attempted=n_attempted,
        n_windows_fetched=n_fetched,
        n_windows_detected=n_detected,
        stability_score=stability_score,
        z_min=min(z_scores) if z_scores else None,
        z_max=max(z_scores) if z_scores else None,
        offset_errors=errors,
    )


def _select_stability_candidates(
    dem_candidates: list,
    dem_zscore_threshold: float,
    margin: float = STABILITY_MARGIN_DEFAULT,
    max_candidates: int = MAX_AUTO_STABILITY_CANDIDATES_DEFAULT,
) -> list:
    """Selects which DEM candidates automatically qualify for the
    stability check this run: |peak_zscore| within
    [threshold, threshold+margin). If more candidates qualify than
    max_candidates, the ones CLOSEST to the threshold are prioritized
    (they are, per real testing, the most likely to actually be
    fragile) rather than an arbitrary or z-score-descending order."""
    eligible = [
        c for c in dem_candidates
        if dem_zscore_threshold <= abs(c.peak_zscore) < (dem_zscore_threshold + margin)
    ]
    eligible.sort(key=lambda c: abs(c.peak_zscore))  # nearest-to-threshold first
    return eligible[:max_candidates]


def _get_shared_copernicus_token(
    client_id: str, client_secret: str, timeout: float
) -> tuple[str | None, str | None]:
    """Fetches ONE OAuth access token to be shared across the NDVI,
    Thermal, AND Optical per-candidate checks this run (all three use
    the same Copernicus Data Space Ecosystem account) -- GPR, ERT, and
    Detection Stability need no token at all (manual-entry-only, and
    OpenTopography-key-only respectively), so none of the three is
    involved here.

    Returns (token_or_None, error_message_or_None). Missing credentials
    is treated exactly like a fetch failure -- callers get a uniform
    honest error message either way, applied identically to every
    candidate for all three sources, rather than raising."""
    if not client_id or not client_secret:
        return None, (
            "Copernicus OAuth client ID/secret not configured yet -- enter "
            "your free client credentials (dataspace.copernicus.eu) to "
            "enable live real per-candidate NDVI/Thermal/Optical checks."
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
    NDVI, Thermal, and Optical checking fully independent of each other
    and of however their results get combined."""
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
    pre-fetched shared token as NDVI/Optical. Mirrors _run_ndvi_checks
    exactly. Runs regardless of whether NDVI's own checks succeeded or
    failed for any given candidate -- all three sources are fully
    independent."""
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


def _run_optical_checks(
    dem_candidates: list,
    client_id: str,
    client_secret: str,
    token: str | None,
    shared_error_message: str | None,
    anomaly_zscore_threshold: float,
    timeout: float,
    progress_callback=None,
) -> list[OpticalCoreHaloResult]:
    """For each DEM candidate, run a real Sentinel-2 visible-brightness
    core/halo check anchored at that candidate's location, using the
    SAME pre-fetched shared token as NDVI/Thermal. Mirrors
    _run_thermal_checks exactly. Runs regardless of whether NDVI's or
    Thermal's own checks succeeded or failed for any given candidate --
    all three sources are fully independent."""
    results: list[OpticalCoreHaloResult] = []
    total = len(dem_candidates)
    for i, dem_candidate in enumerate(dem_candidates):
        error_message = shared_error_message
        check = None
        if error_message is None:
            try:
                check = optical_source_mobile.fetch_optical_core_halo_check(
                    dem_candidate.lat, dem_candidate.lon,
                    client_id, client_secret,
                    anomaly_zscore_threshold=anomaly_zscore_threshold,
                    timeout=timeout,
                    access_token=token,
                )
            except OpticalFetchError as exc:
                error_message = str(exc)

        if error_message is not None:
            results.append(OpticalCoreHaloResult(
                lat=dem_candidate.lat, lon=dem_candidate.lon,
                core_mean=None, halo_mean=None, halo_stddev=None,
                z_score=None, optical_anomaly_detected=False,
                core_brighter_than_halo=None, error=error_message,
            ))
        else:
            results.append(OpticalCoreHaloResult(
                lat=dem_candidate.lat, lon=dem_candidate.lon,
                core_mean=check["core_mean"],
                halo_mean=check["halo_mean"],
                halo_stddev=check["halo_stddev"], z_score=check["z_score"],
                optical_anomaly_detected=check["optical_anomaly_detected"],
                core_brighter_than_halo=check["core_brighter_than_halo"],
            ))

        if progress_callback is not None:
            progress_callback(i + 1, total)

    return results


def _build_correlated_candidates(
    dem_candidates: list,
    ndvi_results: list[NdviCoreHaloResult],
    thermal_results: list[ThermalCoreHaloResult],
    optical_results: list[OpticalCoreHaloResult],
) -> list[CorrelatedCandidate]:
    """Combines per-candidate NDVI, Thermal, and Optical results into ONE
    CorrelatedCandidate per DEM candidate, reflecting whichever real
    source(s) actually corroborated it. supporting_sources is always DEM
    plus zero, one, two, or all three of NDVI/THERMAL/OPTICAL, in that
    order -- NEVER a candidate that "loses" a real corroborating result
    just because another source also happened to succeed or fail. GPR,
    ERT, and Detection Stability are deliberately NOT part of this
    combiner -- GPR/ERT are single site-anchored readings and Stability
    is a diagnostic-only check, all handled separately, never full
    per-candidate correlation sources.

    A per-candidate failure on any source is recorded honestly in the
    combined_confidence_note (not silently dropped), and does not
    prevent the OTHER sources from still corroborating that candidate --
    e.g. if NDVI and Thermal both failed but Optical detected a real
    anomaly, the candidate is still CORROBORATED via DEM+OPTICAL, with
    NDVI's and Thermal's unavailability noted honestly alongside it.

    Sorted the same way the NDVI-only and NDVI+Thermal versions were:
    CORROBORATED first, then by number of supporting sources descending.
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
                f"Real Landsat 8/9 brightness temperature shows this DEM "
                f"candidate is significantly {direction} its surroundings "
                f"(core mean={tr.core_mean_kelvin:.1f}K vs halo mean="
                f"{tr.halo_mean_kelvin:.1f}K, z={tr.z_score:.2f})."
            )
        else:
            notes.append(
                f"Real Landsat 8/9 brightness temperature at this DEM "
                f"candidate shows no significant thermal anomaly "
                f"(core mean={tr.core_mean_kelvin:.1f}K vs halo mean="
                f"{tr.halo_mean_kelvin:.1f}K, z={tr.z_score:.2f})."
            )

        opr = optical_results[i]
        if opr.error is not None:
            notes.append(f"Real optical brightness check unavailable for this candidate: {opr.error}.")
        elif opr.optical_anomaly_detected:
            sources.append("OPTICAL")
            direction = "brighter than" if opr.core_brighter_than_halo else "darker than"
            notes.append(
                f"Real Sentinel-2 visible-band brightness shows this DEM "
                f"candidate is significantly {direction} its surroundings "
                f"(core mean={opr.core_mean:.4f} vs halo mean="
                f"{opr.halo_mean:.4f}, z={opr.z_score:.2f})."
            )
        else:
            notes.append(
                f"Real Sentinel-2 visible-band brightness at this DEM "
                f"candidate shows no significant optical anomaly "
                f"(core mean={opr.core_mean:.4f} vs halo mean="
                f"{opr.halo_mean:.4f}, z={opr.z_score:.2f})."
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
    whole DEM/NDVI/Thermal/Optical/ERT/Stability investigation it's
    attached to.

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


def _build_ert_evidence(
    lat: float,
    lon: float,
    use_ert: bool,
    ert_resistivity_ohm_m: float | None,
    ert_depth_m: float | None,
    ert_entry_method: str,
    ert_device_note: str,
) -> tuple[object | None, str | None]:
    """Build an ERTEvidence from a single real manually-entered
    resistivity reading anchored at (lat, lon), if use_ert=True. Mirrors
    _build_gpr_evidence() exactly in shape and error-handling
    philosophy -- a bad input (non-positive resistivity) is recorded as
    an honest limitation string rather than raised, so one bad ERT
    input never fails the whole investigation it's attached to.

    Raises ValueError only for the caller-programming-error case of
    use_ert=True with a missing resistivity value or depth.
    """
    if not use_ert:
        return None, None
    if ert_resistivity_ohm_m is None or ert_depth_m is None:
        raise ValueError(
            "use_ert=True requires both ert_resistivity_ohm_m and ert_depth_m"
        )
    survey = ERTSurvey(
        lat=lat,
        lon=lon,
        readings=[ERTReading(resistivity_ohm_m=ert_resistivity_ohm_m, depth_m=ert_depth_m)],
        entry_method=ert_entry_method,
        device_note=ert_device_note,
    )
    try:
        classified = classify_survey(survey)
        return ERTEvidence(survey, classified), None
    except ERTResistivityModelError as exc:
        return None, (
            f"Real ERT reading entry failed: {exc}. Recorded honestly; "
            f"this investigation continues without ERT evidence for this run."
        )


class RealNdviCoreHaloEvidence:
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
    source = "Landsat 8/9 Level 1 (Sentinel Hub Statistical API via Copernicus Data Space Ecosystem, real per-candidate core/halo check)"
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
                "credentials account used for NDVI/Optical; per-DEM-candidate "
                "real Landsat 8/9 TOP-OF-ATMOSPHERE BRIGHTNESS TEMPERATURE "
                "(Kelvin) -- Copernicus Data Space Ecosystem offers Landsat "
                "8/9 at Level 1 only, not the atmospherically-corrected "
                "Level 2 surface-temperature product -- fetched server-side "
                "for a small core bbox and a larger halo bbox around each "
                "candidate (larger than NDVI's/Optical's -- Landsat's "
                "thermal band is 30m resolution, resampled from ~100m "
                "native, versus Sentinel-2's 10m). A thermal anomaly is "
                "flagged when the core/halo difference clears a z-score "
                "threshold in EITHER direction (a buried feature can be "
                "warmer or cooler than its surroundings depending on "
                "material, season, and time of day -- no direction is "
                "assumed)."
            ),
            "n_candidates_checked": self.n_candidates_checked,
            "n_fetch_errors": self.n_fetch_errors,
        }

class RealOpticalCoreHaloEvidence:
    source = "Sentinel-2 L2A visible bands B02/B03/B04 (Sentinel Hub Statistical API via Copernicus Data Space Ecosystem, real per-candidate core/halo check)"
    synthetic = False

    def __init__(self, n_candidates_checked: int, n_fetch_errors: int):
        self.n_candidates_checked = n_candidates_checked
        self.n_fetch_errors = n_fetch_errors

    def as_evidence_record(self) -> dict:
        return {
            "evidence_type": "OPTICAL",
            "source": self.source,
            "synthetic": self.synthetic,
            "method": (
                "Same Copernicus Data Space Ecosystem OAuth2 client-"
                "credentials account used for NDVI/Thermal; per-DEM-candidate "
                "real broadband visible reflectance (mean of B02/B03/B04, "
                "0-1 scale), fetched server-side for a small core bbox and "
                "a larger halo bbox around each candidate -- the real "
                "remote-sensing 'soilmark' signature (disturbed/backfilled "
                "ground reading anomalously bright or dark in bare-earth "
                "imagery for reasons unrelated to vegetation vigor). Same "
                "10m resolution and core/halo radii as NDVI (unlike "
                "Thermal's coarser, larger-radius check). Masks water only "
                "(SCL==6), same as NDVI -- on vegetated ground this "
                "measures canopy brightness, not soil tone; see "
                "optical_source_mobile.py's own docstring for the full "
                "masking-design-decision reasoning. An optical anomaly is "
                "flagged when the core/halo difference clears a z-score "
                "threshold in EITHER direction (a soilmark can be brighter "
                "or darker than its surroundings depending on fill "
                "material -- no direction is assumed)."
            ),
            "n_candidates_checked": self.n_candidates_checked,
            "n_fetch_errors": self.n_fetch_errors,
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
    api_key: str = "",
    demtype: str = "SRTMGL1",
    ndvi_client_id: str = "",
    ndvi_client_secret: str = "",
    ndvi_timeout_s: float = 8.0,
    thermal_zscore_threshold: float = 1.5,
    thermal_timeout_s: float = 8.0,
    optical_zscore_threshold: float = 1.5,
    optical_timeout_s: float = 8.0,
    offline_data_root: str = "",
    use_gpr: bool = False,
    gpr_soil_preset_key: str | None = None,
    gpr_two_way_time_ns: float | None = None,
    gpr_entry_method: str = "manual",
    gpr_device_note: str = "",
    use_ert: bool = False,
    ert_resistivity_ohm_m: float | None = None,
    ert_depth_m: float | None = None,
    ert_entry_method: str = "manual",
    ert_device_note: str = "",
    stability_margin: float = STABILITY_MARGIN_DEFAULT,
    max_auto_stability_candidates: int = MAX_AUTO_STABILITY_CANDIDATES_DEFAULT,
) -> str:
    """Run a DEM + NDVI + Thermal + Optical investigation and return the
    InvestigationRecord as a JSON string. This is the function
    MainActivity.kt calls when the "Include NDVI correlation" switch
    is on (Thermal and Optical now run automatically alongside it -- no
    separate toggle for either, same as NDVI itself has none). Detection
    Stability (added this session) also runs automatically, with no
    separate toggle, for whichever DEM candidates qualify.

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
    Thermal AND Optical too). If EVERY candidate's live check failed,
    falls back to this device's offline Sentinel-2 composite (a
    full-AOI raster, independently scanned and correlated against the
    DEM candidates -- can find NDVI anomalies the per-candidate check
    couldn't). If that's also unavailable, the honest per-candidate-
    failure results are kept and DEM results are still returned -- an
    NDVI-side failure never blocks the DEM investigation itself.

    THERMAL: real (Landsat 8/9 via the same Copernicus Sentinel Hub
    Statistical API/account as NDVI, per-DEM-candidate core/halo check,
    see thermal_source_mobile.py) always attempted for every DEM
    candidate, using the SAME shared access token as NDVI/Optical. Runs
    independently of NDVI's own success or failure.

    OPTICAL: real (Sentinel-2 L2A visible-band brightness via the SAME
    Copernicus Sentinel Hub Statistical API/account as NDVI/Thermal,
    per-DEM-candidate core/halo check, see optical_source_mobile.py)
    always attempted for every DEM candidate, using the SAME shared
    access token. Runs independently of NDVI's and Thermal's own
    success or failure.

    In the common case (live NDVI succeeds for at least one candidate),
    NDVI, Thermal, and Optical results are combined per-candidate so a
    single candidate can be corroborated by any subset of the three. In
    the rare case where live NDVI fails for every candidate (triggering
    the offline NDVI raster fallback), Thermal's AND Optical's results
    are still fully recorded (fourth_evidence_detail /
    fifth_evidence_detail) but are NOT folded into that fallback's
    per-candidate correlation notes -- see this module's own docstring
    for why (unconfirmed index/geometric alignment guarantees in that
    code path). Neither Thermal nor Optical has an offline-raster
    fallback of its own yet (a real, known, honestly-noted gap, unlike
    NDVI).

    GPR (optional, use_gpr=True): a single real manual pick (two-way
    travel time + soil preset) anchored at this investigation's
    (lat, lon), attached as a single, site-anchored (not per-candidate)
    evidence entry. All gpr_* parameters default to off/empty.

    ERT (optional, use_ert=True): a single real manual reading
    (resistivity in ohm-meters + the depth at which it was read off an
    already-inverted profile) anchored at this investigation's (lat,
    lon), classified against documented reference resistivity ranges
    and attached as a single, site-anchored (not per-candidate)
    evidence entry -- mirrors GPR's own wiring exactly. All ert_*
    parameters default to off/empty.

    DETECTION STABILITY (ADDED THIS SESSION, automatic, no toggle):
    after DEM candidates are detected, any candidate whose |z| falls
    within stability_margin of dem_zscore_threshold is automatically
    re-tested at max_auto_stability_candidates independent offset AOI
    windows (see _select_stability_candidates()/_run_stability_check()
    above), reusing the primary DEM fetch's own live-first/offline-
    fallback pattern for each offset. Results feed evidence_record.py's
    seventh evidence slot and, via debate_mobile.py, Scientific
    Steward's confidence ceiling as an unconditional cap for fragile
    candidates -- see steward_confidence_ceiling.py's own docstring.
    Never fails the investigation -- a stability sub-fetch failure is
    recorded honestly, never silently treated as instability, and a
    candidate whose |z| doesn't qualify simply has no stability data at
    all (unknown, not assumed stable).

    Writes investigation_status.json into offline_data_root as it works
    (phase "dem" / "ndvi" / "thermal" / "optical" / "stability" /
    "done"), polled by MainActivity.kt for live progress display.
    Best-effort -- never raises on its own.

    Raises ValueError if use_gpr=True without both gpr_soil_preset_key
    and gpr_two_way_time_ns, or if use_ert=True without both
    ert_resistivity_ohm_m and ert_depth_m. Raises
    OpenTopographyFetchError if DEM is unavailable both live and
    offline (see above) -- this is the only hard failure; every
    NDVI-side, Thermal-side, Optical-side, GPR-side, ERT-side, and
    Stability-side failure degrades gracefully with an honest
    limitations[] entry instead.
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

    # --- DETECTION STABILITY: automatic, borderline-only (added this session) ---
    stability_candidates = _select_stability_candidates(
        dem_candidates, dem_zscore_threshold, stability_margin, max_auto_stability_candidates,
    )
    stability_results: list[StabilityResult] = []
    if stability_candidates:
        _write_investigation_status(
            offline_data_root, "stability", 0, len(stability_candidates)
        )
        for i, sc in enumerate(stability_candidates):
            result = _run_stability_check(
                sc, radius_m, api_key, demtype, offline_data_root,
                grid_size, dem_kernel_sigma_cells, dem_zscore_threshold,
            )
            stability_results.append(result)
            _write_investigation_status(
                offline_data_root, "stability", i + 1, len(stability_candidates)
            )

    gpr_evidence, gpr_limitation = _build_gpr_evidence(
        lat, lon, use_gpr, gpr_soil_preset_key, gpr_two_way_time_ns,
        gpr_entry_method, gpr_device_note,
    )
    ert_evidence, ert_limitation = _build_ert_evidence(
        lat, lon, use_ert, ert_resistivity_ohm_m, ert_depth_m,
        ert_entry_method, ert_device_note,
    )

    # --- Shared Copernicus token, fetched ONCE for NDVI, Thermal, AND Optical ---
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

    # --- OPTICAL: real per-candidate check, independent of NDVI's/Thermal's outcome ---
    _write_investigation_status(offline_data_root, "optical", 0, max(1, n_candidates))

    def _report_optical_progress(done: int, total: int) -> None:
        _write_investigation_status(offline_data_root, "optical", done, total)

    optical_results = _run_optical_checks(
        dem_candidates, ndvi_client_id, ndvi_client_secret,
        token, token_error_message,
        anomaly_zscore_threshold=optical_zscore_threshold,
        timeout=optical_timeout_s,
        progress_callback=_report_optical_progress,
    )
    n_optical_errors = sum(1 for r in optical_results if r.error is not None)

    fourth_evidence: object = None
    fifth_evidence: object = None
    used_offline_ndvi = False
    ndvi_limitations: list[str] = []
    thermal_limitations: list[str] = []
    optical_limitations: list[str] = []

    second_evidence = RealNdviCoreHaloEvidence(
        n_candidates_checked=n_candidates, n_fetch_errors=n_ndvi_errors,
    )
    fourth_evidence = RealThermalCoreHaloEvidence(
        n_candidates_checked=n_candidates, n_fetch_errors=n_thermal_errors,
    )
    fifth_evidence = RealOpticalCoreHaloEvidence(
        n_candidates_checked=n_candidates, n_fetch_errors=n_optical_errors,
    )

    if dem_candidates and n_ndvi_errors == n_candidates:
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
            optical_limitations.append(
                "Because NDVI fell back to the offline raster/geometric "
                "correlation path this run, Optical's per-candidate "
                "results (recorded below) were NOT combined into that "
                "path's supporting_sources/notes, for the same reason as "
                "Thermal above. Optical has no offline-raster fallback of "
                "its own yet either."
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
                dem_candidates, ndvi_results, thermal_results, optical_results,
            )
    else:
        second_anomalies = ndvi_results
        second_anomalies_are_candidates = False
        correlation_results = _build_correlated_candidates(
            dem_candidates, ndvi_results, thermal_results, optical_results,
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

    if n_optical_errors > 0 and n_optical_errors < n_candidates:
        optical_limitations.append(
            f"{n_optical_errors} of {n_candidates} candidate(s) had a real "
            f"Optical check unavailable (network/auth/no-data/cloud cover) "
            f"and were recorded with the real reason rather than silently "
            f"dropped or faked."
        )
    elif n_optical_errors == n_candidates and n_candidates > 0:
        optical_limitations.append(
            f"Real Optical checks were unavailable for every candidate "
            f"this run: {optical_results[0].error}. Optical contributed "
            f"no corroboration this run; DEM/NDVI/Thermal results above "
            f"are unaffected."
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
        fifth_evidence=fifth_evidence,
        fifth_anomalies=optical_results,
        fifth_evidence_type="OPTICAL",
        sixth_evidence=ert_evidence,
        sixth_evidence_type="ERT",
        seventh_evidence=(
            StabilityCheckEvidence(
                n_candidates_tested=len(stability_results),
                margin=stability_margin,
                offsets_m=DEFAULT_AUTO_STABILITY_OFFSETS_M,
            ) if stability_results else None
        ),
        seventh_anomalies=stability_results,
        seventh_evidence_type="DETECTION_STABILITY",
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
        "NDVI/Optical. This is Landsat Level 1 Top-of-Atmosphere "
        "BRIGHTNESS TEMPERATURE, not atmospherically-corrected surface "
        "temperature (Copernicus Data Space Ecosystem does not offer "
        "Landsat Level 2) -- it can be influenced by atmospheric "
        "conditions on top of any real ground-level thermal contrast, "
        "and a thermal anomaly can arise from many causes besides a "
        "buried feature (soil moisture, shadow, recent land use, "
        "atmospheric effects) -- no causal interpretation should be "
        "inferred from this check alone."
    )
    record.limitations.append(
        "Real Optical in this run is, like NDVI's and Thermal's real "
        "per-candidate checks, a TARGETED PER-CANDIDATE check (core bbox "
        "vs. halo bbox around each DEM candidate), not an independent "
        "full-grid optical scan -- it cannot discover a candidate that "
        "DEM missed, only confirm or fail to confirm a visible-brightness "
        "anomaly at locations DEM already flagged. This measures "
        "broadband visible reflectance (mean of B02/B03/B04), the real "
        "aerial-archaeology 'soilmark' signature -- but on VEGETATED "
        "ground it measures canopy brightness, not soil tone, since only "
        "water (not vegetation) is masked out of the underlying pixels "
        "(see optical_source_mobile.py's own docstring for the full "
        "masking-design-decision reasoning). An optical anomaly can arise "
        "from many causes besides a buried feature (soil moisture, "
        "shadow, recent land use, seasonal vegetation cover) -- no "
        "causal interpretation should be inferred from this check alone."
    )
    for note in ndvi_limitations:
        record.limitations.append(note)
    for note in thermal_limitations:
        record.limitations.append(note)
    for note in optical_limitations:
        record.limitations.append(note)
    if gpr_limitation:
        record.limitations.append(gpr_limitation)
    if ert_limitation:
        record.limitations.append(ert_limitation)

    _write_investigation_status(offline_data_root, "done", max(1, n_candidates), max(1, n_candidates))

    return record.to_json()
