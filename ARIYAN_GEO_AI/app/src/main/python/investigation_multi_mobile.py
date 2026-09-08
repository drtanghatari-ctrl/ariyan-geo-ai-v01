# --- Additions to investigation_multi_mobile.py ---
#
# New import line (add alongside the existing coordinate import):
#   from coordinate import GeoPoint, build_aoi, offset_point, haversine_distance_m
#
# (offset_point and haversine_distance_m are new to this file's import
# list -- both already exist in coordinate.py; offset_point is new
# there too, see coordinate.py's own diff.)

# DEM WINDOW-SENSITIVITY / DETECTION STABILITY (added this session):
#
# Real on-device testing (18+ live investigations across two real sites,
# see project notes) found that detect_anomalies() -- which z-scores
# each cell against a regional trend computed from whatever terrain
# falls inside THIS investigation's own fetched AOI window -- can
# genuinely disagree with itself: the same physical terrain, fetched
# via a differently-centered (and therefore differently-bounded) live
# OpenTopography request, can score meaningfully differently or drop
# below threshold entirely. This is a real, architectural property of
# local-detrending anomaly detection (not unique to this codebase), and
# it was found to correlate closely with how close a candidate's own
# |z| sits to dem_zscore_threshold: candidates well above threshold
# (|z| >~3.2 in real testing) were rock-solid across every re-fetch
# tested; candidates close to threshold (|z| <~3.0) frequently failed
# to reproduce.
#
# This check makes that instability VISIBLE instead of leaving it
# silently baked into a single number, for exactly the candidates where
# it matters -- it does NOT, and cannot, fix the underlying window
# sensitivity itself. detect_anomalies() is unchanged; this is a
# diagnostic layer on top of it, not a correction to it.
#
# Runs AUTOMATICALLY (no user toggle) for any DEM candidate whose |z|
# falls within STABILITY_MARGIN_DEFAULT of dem_zscore_threshold -- i.e.
# exactly the borderline population real testing showed was actually
# fragile. Capped to MAX_AUTO_STABILITY_CANDIDATES_DEFAULT per
# investigation so a multi-candidate run can't silently multiply live
# DEM fetches without bound, given this project's real network
# constraints (see project notes on the user's network environment).
#
# Each offset re-fetch reuses the exact same real live-first/offline-
# fallback pattern as the PRIMARY DEM fetch (OpenTopographyAAIGridSource
# -> fetch_offline_dem on failure) -- a stability sub-fetch failing
# (network, HTTP, parse) is recorded honestly as "not tested" for that
# window, never silently treated as "not detected." This never fails
# the investigation itself; a stability check that can't complete for
# any reason simply leaves stability_score=None for that candidate,
# same as a candidate that was never eligible for the check at all.

DEFAULT_AUTO_STABILITY_OFFSETS_M: list[tuple[float, float]] = [
    (15.0, 0.0), (-15.0, 0.0), (0.0, 15.0), (0.0, -15.0),
]  # (north_m, east_m) pairs. 4 offsets + the candidate's own primary
   # detection = 5 total data points per tested candidate -- enough to
   # distinguish the real "rock-solid vs. fragile" pattern found in
   # manual testing (11-offset grids) without multiplying live fetches
   # by more than 5x for the (at most MAX_AUTO_STABILITY_CANDIDATES)
   # candidates that actually qualify.

STABILITY_MARGIN_DEFAULT = 1.0  # |z| within threshold+this margin triggers
                                 # the automatic check. Chosen from real
                                 # testing: the fragile band observed was
                                 # roughly |z| 2.6-3.0 against a 2.5
                                 # threshold -- a margin of 1.0
                                 # (triggering up to |z|~3.5) deliberately
                                 # keeps some buffer above that observed
                                 # fragile band rather than cutting it
                                 # exactly at its edge.

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
                                            # elsewhere in this module.


@dataclass
class StabilityResult:
    """Result of re-fetching+re-detecting around ONE DEM candidate at
    several genuinely independent offset centers, to measure whether
    that candidate's detection is robust to exact AOI window placement
    or an artifact of one specific fetch. `stability_score` and
    `z_scores_where_detected` are the real, caller-facing numbers --
    everything else here is provenance/debugging detail. A candidate
    this was never run for (not near dem_zscore_threshold, or the
    per-investigation cap was already reached) has no StabilityResult
    at all -- this dataclass is only ever constructed for a candidate
    the check actually ran on."""
    target_lat: float
    target_lon: float
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
    z_scores_where_detected: list[float]
    z_min: float | None
    z_max: float | None
    offset_errors: list[str]     # honest per-offset failure reasons, if any

    def as_dict(self) -> dict:
        return {
            "target_lat": self.target_lat,
            "target_lon": self.target_lon,
            "target_zscore": self.target_zscore,
            "n_windows_attempted": self.n_windows_attempted,
            "n_windows_fetched": self.n_windows_fetched,
            "n_windows_detected": self.n_windows_detected,
            "stability_score": self.stability_score,
            "z_scores_where_detected": self.z_scores_where_detected,
            "z_min": self.z_min,
            "z_max": self.z_max,
            "offset_errors": self.offset_errors,
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
    own primary DEM fetch (see that function). Factored out so the
    primary fetch and every stability offset fetch share one real
    implementation rather than two copies that could silently drift
    apart. Raises OpenTopographyFetchError (naming BOTH the live and
    offline failure reasons, same as the primary path) only when
    neither live nor offline succeeds -- callers (here, the stability
    loop) catch that and record it as an honest per-offset failure
    rather than letting it escape."""
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
    # Derived per-offset below once we have a real aoi.cell_size_m, same
    # colocation-style default pattern used elsewhere in this module
    # (see _gpr_colocation_distance_m/_ert_colocation_distance_m).

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
        target_lat=dem_candidate.lat,
        target_lon=dem_candidate.lon,
        target_zscore=dem_candidate.peak_zscore,
        n_windows_attempted=n_attempted,
        n_windows_fetched=n_fetched,
        n_windows_detected=n_detected,
        stability_score=stability_score,
        z_scores_where_detected=z_scores,
        z_min=min(z_scores) if z_scores else None,
        z_max=max(z_scores) if z_scores else None,
        offset_errors=errors,
    )
