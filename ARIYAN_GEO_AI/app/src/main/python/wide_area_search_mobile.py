"""
wide_area_search_mobile.py

Part of ARIYAN GEO AI's GRAND PROJECT FRAMEWORK -- the next item on the
roadmap after Phase 2 (Confidence History + Evidence Graph + Hypothesis
UI, closed 2026-09-17): WIDE-AREA / WHOLE-PROVINCE SEARCH.

PER THE USER'S OWN EXPLICIT ARCHITECTURAL INSTRUCTION (given before any
of this was built): wide-area search is a NEW KIND of investigation the
user launches (province-wide, tiled, potentially long-running) -- it is
NOT part of the existing Grand Project browse screen, which is
retrospective ("review what already happened"). This module's own
Kotlin-facing surface is therefore entirely separate from
grand_project_query_mobile.py, even though both sit on top of the same
grand_project_db.py.

THIS MODULE ADDS NO NEW EVIDENCE-GATHERING OR PERSISTENCE LOGIC. Every
real per-tile investigation runs through the SAME, already-proven-
correct investigation_multi_mobile.run_investigation_multi_json() (DEM +
NDVI + Thermal + Optical + SAR + Detection Stability + Temporal
Persistence + DEM Cross-Check + optional GPR/ERT) and debate_mobile.
run_debate_json(), then persists through the SAME
grand_project_sync.record_investigation_results() path Phase 1 verified
on real hardware -- this module is purely batch orchestration (tile
geometry + checkpointed looping) on top of what already works. A tile's
resulting candidates therefore show up in the existing browse screen's
Candidates tab like any other investigation; this module's own screen
is only responsible for configuring/launching/monitoring the batch job,
never for re-displaying results.

THREE REAL AOI INPUT MECHANISMS (per the Phase 2.5 scoping recap this
was queued from):
  (a) a named place, geocoded to a real bounding box -- reuses
      geocoding_source_mobile_nominatim.geocode_place_name_safe()
      UNCHANGED; that function already returns a real "bounding_box"
      dict (min_lat/max_lat/min_lon/max_lon, straight from Nominatim's
      own real "boundingbox" field) -- no new geocoding logic needed.
  (b) a manually typed bounding box -- the caller (Kotlin) supplies
      min_lat/max_lat/min_lon/max_lon directly; no Python-side lookup
      at all.
  (c) a reviewed geographic_suggestion row (from the Historical
      Research & Probable-Area Engine, Phase 2.5) -- WIRED 2026-09-17,
      see create_wide_area_search_job_from_suggestion_json() below. A
      PAIRED_SUGGESTION row's own real anchor lat/lon + radius (per
      grand_project_db.add_geographic_suggestion()'s own docstring)
      is turned into a bbox via the SAME real offset_point() geodesy
      generate_tile_grid() itself already uses -- no new geocoding or
      geometry capability was needed, exactly as this docstring
      originally expected.

NOT YET BUILT (deliberately out of this module's own first-pass scope,
matching this project's "prove one piece before wiring" discipline):
  - Kotlin/Service/Activity/XML wiring (WideAreaSearchService.kt,
    WideAreaSearchActivity.kt, activity_wide_area_search.xml,
    MainActivity.kt's own navigation button, AndroidManifest.xml's
    service/activity registration) -- this module is delivered ahead of
    all of that, sandbox-verified independently first, exactly matching
    how grand_project_query_mobile.py was delivered ahead of
    GrandProjectActivity.kt.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional

from coordinate import GeoPoint, offset_point

import grand_project_db as db
import geocoding_source_mobile_nominatim as geocoding
import investigation_multi_mobile
import debate_mobile
import grand_project_sync

DEFAULT_TILE_SIZE_M = 1000.0  # 1 km tiles: a sensible default survey grain.
                              # How much ground each tile's DEM analysis
                              # window must span to actually COVER that
                              # tile is NOT simply "tile / 2" -- see
                              # derive_analysis_window() below.

# ---- ANALYSIS-WINDOW SIZING (COVERAGE FIX) -------------------------------
# Found on real hardware by measuring candidate positions against tile
# centres: anomaly_detection.detect_anomalies() ignores a border of
# `edge_margin_cells` (default 2 x kernel sigma) on EVERY side of its grid,
# because Gaussian detrending is unreliable near a raster's edge. On the
# 96-cell grid this project always used, that leaves only the central 48
# cells -- HALF the window's width, a QUARTER of its area -- in which a
# candidate can ever be reported. Sizing the window as "radius = tile / 2"
# therefore examined only the central quarter of every tile; the real
# fixed 500 m radius examined only a 500 m square per tile no matter how
# big the tile was. derive_analysis_window() sizes the window so that the
# detector's usable INTERIOR equals the tile.
TESTED_CELL_SIZE_M = 2 * 500.0 / 96   # 10.4167 m: the DEM cell size at the
                                      # radius/grid this project's analysis
                                      # was built and proven on (500 m, 96
                                      # cells). Kept constant wherever
                                      # possible so what the detector
                                      # "sees" stays what was tested.
DEM_KERNEL_SIGMA_CELLS = 12.0         # Passed EXPLICITLY to every tile's
                                      # investigation (never left to a
                                      # default), so the margin below can
                                      # never silently drift from what the
                                      # detector actually uses.
DETECTOR_EDGE_MARGIN_CELLS = int(round(2 * DEM_KERNEL_SIGMA_CELLS))  # 24 --
                                      # detect_anomalies()' own default rule
                                      # (2 x sigma), verified empirically
                                      # against the real detector.
MIN_TILE_INTERIOR_M = 500.0           # Tiles smaller than this are analysed
                                      # as if they were 500 m: the proven
                                      # 96-cell/500 m configuration. Its
                                      # interior is 500 m wide, so
                                      # neighbouring windows overlap and
                                      # near-duplicate candidates are
                                      # possible for tiles under 500 m --
                                      # use tiles of 1 km or more for real
                                      # surveys.
MAX_AUTO_GRID_SIZE = 384              # Upper bound on the derived grid. Past
                                      # a ~3.5 km tile the cell size grows
                                      # instead of the grid (a 10 km tile
                                      # gets ~30 m cells, which is
                                      # SRTM/COP30's own native resolution),
                                      # trading fine detail for reach. An
                                      # unmeasured-on-phone compute guard --
                                      # lower it if large tiles prove slow.

DEFAULT_MAX_TILES = 500  # A real, deliberate cap, not an arbitrary
                          # round number: at ~8-10 real HTTP calls per
                          # tile (DEM + shared-token NDVI/Thermal/
                          # Optical/SAR core+halo + DEM cross-check,
                          # per investigation_multi_mobile.py's own
                          # REAL NETWORK-COST NOTE), 500 tiles is
                          # already several thousand real calls -- a
                          # multi-hour-to-multi-day job on this
                          # project's real free-tier API accounts. An
                          # accidentally degree-scale bbox (e.g. a
                          # whole country typed into the manual-bbox
                          # fields by mistake) at a 1km tile size would
                          # otherwise silently generate tens of
                          # thousands of tiles; this raises a clear,
                          # honest error instead of quietly starting a
                          # job that could never realistically finish.


class WideAreaSearchError(Exception):
    """Raised for a genuinely bad input to this module (an invalid bbox,
    a tile grid exceeding max_tiles, or a job_id that doesn't exist) --
    never for an ordinary per-tile evidence-gathering failure, which is
    recorded honestly on that tile's own row instead (see
    run_wide_area_search_job() below)."""


def generate_tile_grid(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    tile_size_m: float = DEFAULT_TILE_SIZE_M,
    max_tiles: int = DEFAULT_MAX_TILES,
) -> List[Dict[str, float]]:
    """Computes real tile-center coordinates covering a bounding box, on
    a regular grid stepped tile_size_m apart. Uses this project's own
    existing, already-exercised coordinate.py.offset_point() (the same
    real WGS84 geodesy helper investigation_multi_mobile.py's Detection
    Stability check already uses for its own offset re-fetches) --
    deliberately NOT a fresh degree-arithmetic implementation, so this
    module inherits the same real, tested geodesy rather than a second,
    independently-written (and independently-buggy) version of it.

    Tile centers are inset tile_size_m/2 from the bbox edges on both
    axes, so the resulting tiles evenly cover the box edge-to-edge
    without a fractional partial tile hanging off either side.

    Returns a list of {"tile_index": int, "center_lat": float,
    "center_lon": float} dicts, tile_index assigned in row-major order
    (west-to-east within each row, south-to-north across rows) -- the
    exact shape grand_project_db.create_wide_area_search_job()'s own
    `tile_centers` parameter expects.

    Raises WideAreaSearchError for a malformed bbox (min >= max on
    either axis, non-positive tile_size_m), or if the real tile count
    this bbox/tile_size_m combination would produce exceeds max_tiles --
    see DEFAULT_MAX_TILES above for why this is a real, deliberate
    guard, not an arbitrary limitation. Never silently truncates the
    grid to fit under the cap; a caller hitting this should either
    shrink the bbox or increase tile_size_m, not receive a partial,
    silently-incomplete grid.
    """
    if min_lat >= max_lat:
        raise WideAreaSearchError(
            f"min_lat ({min_lat}) must be less than max_lat ({max_lat})."
        )
    if min_lon >= max_lon:
        raise WideAreaSearchError(
            f"min_lon ({min_lon}) must be less than max_lon ({max_lon})."
        )
    if tile_size_m <= 0:
        raise WideAreaSearchError(f"tile_size_m must be positive, got {tile_size_m}.")

    sw_corner = GeoPoint(min_lat, min_lon)
    first_center = offset_point(sw_corner, tile_size_m / 2.0, tile_size_m / 2.0)

    tiles: List[Dict[str, float]] = []
    row_start = first_center
    guard_rows = 0
    # guard_rows/guard_cols are a hard backstop against an infinite loop
    # if offset_point() ever returned a non-advancing point for a
    # degenerate input (never observed, but this loop has no other
    # natural termination besides the lat/lon bounds themselves) --
    # generously sized relative to max_tiles so it never fires for any
    # legitimate grid that would pass the max_tiles check below anyway.
    guard_limit = max(max_tiles * 4, 4000)

    while row_start.lat <= max_lat and guard_rows < guard_limit:
        col_point = row_start
        guard_cols = 0
        while col_point.lon <= max_lon and guard_cols < guard_limit:
            tiles.append({
                "tile_index": len(tiles),
                "center_lat": col_point.lat,
                "center_lon": col_point.lon,
            })
            if len(tiles) > max_tiles:
                raise WideAreaSearchError(
                    f"This bounding box at tile_size_m={tile_size_m:g} would "
                    f"produce more than {max_tiles} tiles -- shrink the "
                    f"bounding box or increase tile_size_m. No tiles were "
                    f"created."
                )
            col_point = offset_point(col_point, 0.0, tile_size_m)
            guard_cols += 1
        row_start = offset_point(row_start, tile_size_m, 0.0)
        guard_rows += 1

    if not tiles:
        raise WideAreaSearchError(
            "This bounding box produced zero tiles -- it may be smaller "
            "than half a tile_size_m on one axis."
        )

    return tiles


# =========================== JOB CREATION (JSON-facing) ===========================

def geocode_place_to_bbox_json(place_name: str) -> str:
    """Thin wrapper for AOI input mechanism (a): looks up `place_name`
    via the real Nominatim geocoder already used elsewhere in this
    project (geocoding_source_mobile_nominatim.py, unchanged, including
    its own real rate limiter) and returns its real bounding box, if
    found. Returns {"found": true, "resolved_name": ..., "bounding_box":
    {...}} on a real match, or {"found": false, "error": "..."} on a
    genuine "not found" or a real network/HTTP failure -- mirrors this
    project's existing {"error": "..."} convention (e.g.
    grand_project_query_mobile.get_candidate_detail_json()) rather than
    raising, since "place not found" is an ordinary, expected UI
    outcome here, not a malformed-input failure.

    Adds no new geocoding logic -- calls geocode_place_name_safe()
    unchanged and repackages its own real (result, error) tuple.
    """
    result, error = geocoding.geocode_place_name_safe(place_name)
    if error is not None:
        return json.dumps({"found": False, "error": error})
    if result is None:
        return json.dumps({
            "found": False,
            "error": f"No place matching {place_name!r} was found.",
        })
    return json.dumps({
        "found": True,
        "resolved_name": result.get("resolved_name"),
        "bounding_box": result.get("bounding_box"),
    })


def create_wide_area_search_job_json(
    db_root: str,
    grand_project_id: str,
    title: str,
    input_kind: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    tile_size_m: float = DEFAULT_TILE_SIZE_M,
    hypothesis_id: Optional[str] = None,
    place_name: Optional[str] = None,
    geographic_suggestion_id: Optional[str] = None,
    max_tiles: int = DEFAULT_MAX_TILES,
) -> str:
    """Creates one wide-area search job: computes the real tile grid for
    the given bbox (see generate_tile_grid() above), then persists the
    job + every tile row via grand_project_db.create_wide_area_search_job().

    `input_kind` MUST be one of 'PLACE_NAME' / 'MANUAL_BBOX' /
    'GEOGRAPHIC_SUGGESTION' -- the caller (Kotlin) is responsible for
    resolving the real min_lat/max_lat/min_lon/max_lon for whichever
    mechanism the user picked (mechanism (a) via
    geocode_place_to_bbox_json() above; mechanism (b) directly from the
    four manual-entry fields; mechanism (c) not yet wired, see module
    docstring) before calling this function -- this function itself
    does not distinguish between the three beyond storing the label and
    optional place_name/geographic_suggestion_id for later display.

    Returns {"job_id": "...", "n_tiles": int} as JSON on success, or
    {"error": "..."} (never raises) if the bbox/tile_size_m combination
    is invalid or would exceed max_tiles -- mirrors this project's
    existing {"error": ...} convention for an ordinary, expected
    "can't proceed with this input" case rather than a hard crash, since
    a user mistyping a bounding box is a normal occurrence this UI needs
    to handle gracefully, not a programming error.
    """
    try:
        tiles = generate_tile_grid(min_lat, max_lat, min_lon, max_lon, tile_size_m, max_tiles)
    except WideAreaSearchError as exc:
        return json.dumps({"error": str(exc)})

    job_id = db.create_wide_area_search_job(
        db_root, grand_project_id, title, input_kind,
        min_lat, max_lat, min_lon, max_lon, tile_size_m, tiles,
        hypothesis_id=hypothesis_id,
        place_name=place_name,
        geographic_suggestion_id=geographic_suggestion_id,
    )
    return json.dumps({"job_id": job_id, "n_tiles": len(tiles)})


def list_wide_area_search_jobs_json(db_root: str, grand_project_id: str) -> str:
    """Returns every wide-area search job for a project as a JSON array,
    newest first -- the real dicts
    grand_project_db.list_wide_area_search_jobs_for_project() already
    returns, unchanged. Mirrors grand_project_query_mobile.py's own
    thin-wrapper convention exactly."""
    rows = db.list_wide_area_search_jobs_for_project(db_root, grand_project_id)
    return json.dumps(rows)


def get_wide_area_search_job_status_json(db_root: str, job_id: str) -> str:
    """Returns one job's own row PLUS its real live tile-progress counts
    in a single combined object -- {"job": {...} | null, "progress":
    {"total", "pending", "done", "failed"}} -- so the wide-area search
    screen can poll this ONE function while a job is running rather than
    making two separate calls every poll tick. "job" is null (not
    omitted) if job_id doesn't resolve to a real row, matching this
    project's existing "never assume a lookup always succeeds" pattern
    (grand_project_query_mobile.get_candidate_detail_json()'s own
    investigation/hypothesis null-handling)."""
    job = db.get_wide_area_search_job(db_root, job_id)
    progress = db.get_wide_area_search_job_progress(db_root, job_id)
    return json.dumps({"job": job, "progress": progress})


def list_tiles_for_job_json(db_root: str, job_id: str) -> str:
    """Returns every tile row for a job as a JSON array, ordered by
    tile_index -- the real dicts grand_project_db.list_tiles_for_job()
    already returns, unchanged. Used for the per-tile status list (which
    tiles are DONE/FAILED/PENDING, and each DONE tile's real
    investigation_id) the wide-area search screen shows."""
    rows = db.list_tiles_for_job(db_root, job_id)
    return json.dumps(rows)


# ============== AOI MECHANISM (c): GEOGRAPHIC_SUGGESTION -> JOB (ADDED 2026-09-17) ==============

def create_wide_area_search_job_from_suggestion_json(
    db_root: str,
    grand_project_id: str,
    title: str,
    center_lat: float,
    center_lon: float,
    radius_km: float,
    tile_size_m: float = DEFAULT_TILE_SIZE_M,
    hypothesis_id: Optional[str] = None,
    geographic_suggestion_id: Optional[str] = None,
    max_tiles: int = DEFAULT_MAX_TILES,
) -> str:
    """AOI input mechanism (c): turns ONE reviewed
    grand_project_db.geographic_suggestion row (a real anchor
    lat/lon + radius, already produced by
    historical_claim_extraction_mobile.suggest_probable_areas() and
    persisted by grand_project_historical_sync.record_historical_research_results())
    directly into a wide-area search job -- the deferred piece this
    module's own docstring flagged as "expected to be a thin addition
    once the UI exists", now that it does.

    Computes a real bounding box centered on (center_lat, center_lon)
    with radius_km on every side, using the SAME real
    coordinate.py.offset_point() geodesy generate_tile_grid() itself
    uses (north/south/east/west offsets from the center point) --
    no new geometry, no approximation beyond what a "radius" claim
    already is. The resulting bbox is then handed to
    generate_tile_grid() exactly as create_wide_area_search_job_json()
    does for mechanisms (a)/(b) -- same honest max_tiles cap, same
    "raise rather than silently truncate" behavior for a suggestion
    whose real radius/tile_size_m combination would produce too many
    tiles.

    `title` is caller-supplied (Kotlin) rather than derived from the
    suggestion's own source_item title here, so the caller can let the
    user review/edit it first -- consistent with mechanisms (a)/(b),
    where the job title is always a deliberate human-entered value,
    never auto-generated silently.

    Stores `input_kind="GEOGRAPHIC_SUGGESTION"` and the real
    `geographic_suggestion_id` on the job row (both already existing
    grand_project_db.create_wide_area_search_job() parameters, unused
    by mechanisms (a)/(b) until now) so the job's real provenance --
    which suggestion it came from -- is preserved, not just its
    resulting geometry.

    Returns {"job_id": "...", "n_tiles": int} as JSON on success, or
    {"error": "..."} (never raises) on an invalid radius/tile_size_m
    combination -- same convention as create_wide_area_search_job_json().
    """
    if radius_km <= 0:
        return json.dumps({"error": f"radius_km must be positive, got {radius_km}."})

    center = GeoPoint(center_lat, center_lon)
    radius_m = radius_km * 1000.0
    north = offset_point(center, radius_m, 0.0)
    south = offset_point(center, -radius_m, 0.0)
    east = offset_point(center, 0.0, radius_m)
    west = offset_point(center, 0.0, -radius_m)
    min_lat, max_lat = south.lat, north.lat
    min_lon, max_lon = west.lon, east.lon

    try:
        tiles = generate_tile_grid(min_lat, max_lat, min_lon, max_lon, tile_size_m, max_tiles)
    except WideAreaSearchError as exc:
        return json.dumps({"error": str(exc)})

    job_id = db.create_wide_area_search_job(
        db_root, grand_project_id, title, "GEOGRAPHIC_SUGGESTION",
        min_lat, max_lat, min_lon, max_lon, tile_size_m, tiles,
        hypothesis_id=hypothesis_id,
        geographic_suggestion_id=geographic_suggestion_id,
    )
    return json.dumps({"job_id": job_id, "n_tiles": len(tiles)})


# =========================== JOB RUNNER (resumable, checkpointed) ===========================

def _write_wide_area_status(
    data_root: str, job_id: str, done: int, total: int, detail: str = ""
) -> None:
    """Best-effort progress status write, polled by
    WideAreaSearchActivity.kt while a job runs in
    WideAreaSearchService.kt -- mirrors investigation_multi_mobile.py's
    own _write_investigation_status() convention exactly (same JSON
    shape: phase/done/total/detail), one file PER JOB (named by job_id)
    rather than a single shared file, since a future job could in
    principle be queued behind a currently-running one and this keeps
    each job's own progress file unambiguous. Never raises: a failure to
    write progress must never fail the actual job, exactly like the
    single-point investigation's own status-write philosophy."""
    try:
        import os
        path = os.path.join(data_root, f"wide_area_search_status_{job_id}.json")
        with open(path, "w") as f:
            json.dump({"phase": "running", "done": done, "total": total, "detail": detail}, f)
    except Exception:
        pass


def derive_analysis_window(tile_size_m: float) -> Dict[str, Any]:
    """Sizes one tile's DEM analysis window so the detector's usable
    interior EXACTLY covers the tile (see the COVERAGE FIX note above the
    constants).

    Returns {"radius_m", "grid_size", "cell_size_m", "interior_m"}, where
    radius_m is the half-width of the fetched window, grid_size its cell
    count per side, cell_size_m the ground size of one cell, and
    interior_m the width of the square in which candidates can be
    reported (== max(tile_size_m, MIN_TILE_INTERIOR_M)).

    Keeps the tested 10.4 m cell size (so detector kernel scales, in
    metres, match what was proven on-device) until the grid would exceed
    MAX_AUTO_GRID_SIZE; beyond that the cell grows. Worked values:
    tile 500 m or less -> radius 500 m, 96 cells (exactly the original
    configuration); 1 km -> 750 m, 144 cells; 2 km -> 1250 m, 240 cells;
    10 km -> ~5714 m, 384 cells (~30 m cells).

    Scientific note: the detector z-scores each cell against the whole
    interior's own relief statistics, so a bigger tile means that
    reference population covers more, and more varied, terrain. Detail
    and sensitivity to subtle features on flat sub-areas therefore fall
    as tile size rises; 1-2 km tiles are the recommended survey grain.
    """
    if tile_size_m is None or tile_size_m <= 0:
        raise WideAreaSearchError(f"tile_size_m must be positive, got {tile_size_m}.")

    margin = DETECTOR_EDGE_MARGIN_CELLS
    interior_m = max(float(tile_size_m), MIN_TILE_INTERIOR_M)
    wanted_cells = int(math.ceil(interior_m / TESTED_CELL_SIZE_M - 1e-9))
    interior_cells = max(1, min(wanted_cells, MAX_AUTO_GRID_SIZE - 2 * margin))
    grid_size = interior_cells + 2 * margin
    cell_size_m = interior_m / interior_cells
    radius_m = grid_size * cell_size_m / 2.0
    return {
        "radius_m": radius_m,
        "grid_size": grid_size,
        "cell_size_m": cell_size_m,
        "interior_m": interior_m,
    }


def run_wide_area_search_job(
    data_root: str,
    job_id: str,
    radius_m: float = 0.0,
    grid_size: int = 0,
    api_key: str = "",
    demtype: str = "SRTMGL1",
    ndvi_client_id: str = "",
    ndvi_client_secret: str = "",
) -> str:
    """Runs (or RESUMES) one wide-area search job.

    ANALYSIS-WINDOW / COVERAGE FIX: `radius_m` <= 0 and `grid_size` <= 0
    (the defaults) now mean "size this tile's analysis window from the
    job's own tile size" via derive_analysis_window(), so that the DEM
    detector's usable interior -- the central half of its window's width,
    because detect_anomalies() ignores a 2 x sigma border on every side --
    exactly covers the tile. Before this, every tile was analysed at a
    fixed 500 m radius / 96 cells regardless of its size (WideAreaSearch
    Service.kt never passed either), and an intermediate version that set
    radius = tile / 2 still covered only a quarter of each tile. Measured
    on real hardware: candidates were never found farther than ~250 m
    from a tile centre on any 500 m-radius job, and never farther than
    ~480 m on a 1000 m-radius job. Consequently every wide-area job run
    before this fix (including the 10 km-tile Tehran, Golestan and
    Marvdasht jobs) examined only a small square at each tile's centre
    (~0.25% of a 10 km tile), i.e. behaved as a sparse point sample, not a
    search of the whole area. Tiles under 500 m keep the original proven
    500 m / 96-cell window (neighbouring windows then overlap).

    A caller may still pass an explicit positive `radius_m` and/or
    `grid_size` to override. An explicit radius with an automatic grid
    keeps the tested 10.4 m cell size; an explicit grid with an automatic
    radius uses the derived radius as-is. Any override voids the coverage
    guarantee. The window actually used is recorded in each tile's
    investigation objective.

    NOTE ON `data_root`: this is the SAME directory grand_project_db.py
    calls `db_root` and investigation_multi_mobile.py/MainActivity.kt
    call `offline_data_root`/`offlineDataRoot` -- see
    grand_project_db.py's own module docstring confirming these are, in
    real practice, always the same on-device path
    (ExternalStorageAccess.offlineDataRoot().absolutePath). This
    function uses ONE parameter name and passes it to both call sites
    below, rather than requiring the caller to pass the same real path
    twice under two different names.

    For every tile still 'PENDING' (see
    grand_project_db.list_pending_tiles_for_job() -- THIS is the actual
    resumability mechanism, not anything in this function itself), runs
    the SAME real full evidence-stack investigation
    (investigation_multi_mobile.run_investigation_multi_json(), with
    every credential/threshold parameter this function accepts forwarded
    through unchanged) at that tile's real center coordinates, then the
    SAME real rule-based debate (debate_mobile.run_debate_json()), then
    persists both via the SAME real
    grand_project_sync.record_investigation_results() path Phase 1
    already proved correct on real hardware -- no new evidence-gathering
    or persistence logic exists in this function; it is purely batch
    orchestration on top of what already works. The real `objective`
    string passed to record_investigation_results() names the job and
    this tile's position (e.g. "Wide-area search 'Fars Province survey'
    -- tile 12/84") -- a genuine, incidental fix to the previously-known
    cosmetic gap where investigation.objective was always blank for a
    single-point run (MainActivity.kt's own onRunClicked() never passed
    one); wide-area search tiles get a real, useful objective from the
    start.

    RESUMABLE BY DESIGN (see module docstring's CHECKPOINTING note): if
    the app/process is killed mid-run, calling this again with the SAME
    job_id continues from wherever it left off. Safe to call repeatedly;
    a job with zero PENDING tiles left simply finishes immediately with
    its already-current progress counts.

    Never raises for an ordinary per-tile failure (a genuinely failed
    real DEM fetch at that tile's location, any Chaquopy-level exception
    during that one tile's evidence run) -- that tile's row is marked
    FAILED with the real error message (via
    grand_project_db.mark_tile_failed()), and the loop continues to the
    next tile, exactly mirroring investigation_multi_mobile.py's own
    "one source's failure never fails the whole investigation"
    philosophy, one level up (one TILE's failure never fails the whole
    JOB). Does raise WideAreaSearchError if job_id doesn't resolve to a
    real job row -- a genuine caller error, not an ordinary per-tile
    outcome.

    Writes wide_area_search_status_<job_id>.json into data_root after
    every tile (see _write_wide_area_status() above), polled by
    WideAreaSearchService.kt/WideAreaSearchActivity.kt for live progress
    -- best-effort, never raises on its own.

    Returns the job's final real progress counts as a JSON string:
    {"total", "pending", "done", "failed"}.
    """
    job = db.get_wide_area_search_job(data_root, job_id)
    if job is None:
        raise WideAreaSearchError(f"No wide-area search job with id {job_id!r} was found.")

    grand_project_id = job["grand_project_id"]

    window = derive_analysis_window(job["tile_size_m"])
    radius_auto = radius_m is None or radius_m <= 0
    grid_auto = grid_size is None or grid_size <= 0
    if radius_auto:
        radius_m = window["radius_m"]
    if grid_auto:
        if radius_auto:
            grid_size = int(window["grid_size"])
        else:
            # Explicit radius, automatic grid: keep the tested cell size.
            grid_size = int(min(
                MAX_AUTO_GRID_SIZE,
                max(
                    2 * DETECTOR_EDGE_MARGIN_CELLS + 8,
                    math.ceil(2.0 * radius_m / TESTED_CELL_SIZE_M - 1e-9),
                ),
            ))
    cell_size_m = 2.0 * radius_m / grid_size

    db.update_wide_area_search_job_status(data_root, grand_project_id, job_id, "RUNNING")

    all_tiles = db.list_tiles_for_job(data_root, job_id)
    pending_tiles = db.list_pending_tiles_for_job(data_root, job_id)
    total = len(all_tiles)
    already_done = total - len(pending_tiles)

    _write_wide_area_status(data_root, job_id, already_done, total, "starting")

    for i, tile in enumerate(pending_tiles):
        tile_id = tile["id"]
        tile_index = tile["tile_index"]
        lat = tile["center_lat"]
        lon = tile["center_lon"]

        db.mark_tile_started(data_root, tile_id)

        try:
            investigation_json = investigation_multi_mobile.run_investigation_multi_json(
                lat, lon, radius_m, grid_size,
                dem_kernel_sigma_cells=DEM_KERNEL_SIGMA_CELLS,
                api_key=api_key,
                demtype=demtype,
                ndvi_client_id=ndvi_client_id,
                ndvi_client_secret=ndvi_client_secret,
                offline_data_root=data_root,
            )

            try:
                debate_json: Optional[str] = debate_mobile.run_debate_json(investigation_json)
            except Exception:
                # Mirrors MainActivity.kt's own onRunClicked() philosophy
                # exactly: a debate-engine failure must never hide the
                # real investigation evidence this tile already
                # gathered.
                debate_json = None

            result = grand_project_sync.record_investigation_results(
                data_root, grand_project_id, investigation_json,
                debate_json=debate_json,
                hypothesis_id=job.get("hypothesis_id"),
                objective=(
                    f"Wide-area search '{job['title']}' -- "
                    f"tile {tile_index + 1}/{total} "
                    f"(analysis radius {radius_m:.0f} m, "
                    f"{grid_size}x{grid_size} grid, {cell_size_m:.1f} m cells)"
                ),
            )
            db.mark_tile_done(data_root, tile_id, result["investigation_id"])

        except Exception as exc:
            db.mark_tile_failed(data_root, tile_id, f"{type(exc).__name__}: {exc}")

        _write_wide_area_status(
            data_root, job_id, already_done + i + 1, total,
            f"tile {tile_index + 1}/{total}",
        )

    progress = db.get_wide_area_search_job_progress(data_root, job_id)
    final_status = "COMPLETE" if progress["failed"] == 0 else "COMPLETE_WITH_ERRORS"
    db.update_wide_area_search_job_status(data_root, grand_project_id, job_id, final_status)
    _write_wide_area_status(data_root, job_id, progress["total"], progress["total"], "done")

    return json.dumps(progress)
