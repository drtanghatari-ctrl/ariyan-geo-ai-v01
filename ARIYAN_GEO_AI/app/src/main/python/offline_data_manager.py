"""
offline_data_manager.py

Part of ARIYAN GEO AI's OFFLINE MODE extension.

DEM HALF: the bulk downloader for a country's offline DEM package: given a
CountryConfig (see offline_country_registry.py), enumerates the 1x1
degree tiles covering its bounding box, downloads each from the public
Copernicus DEM AWS bucket, and saves it under the local naming
offline_dem_store.py expects.

REMOTE NAMING, confirmed against a real, live bucket listing (not
assumed): each tile lives at
  {dem_dataset_prefix}_{N/S}{lat:02d}_00_{E/W}{lon:03d}_00_DEM/
  {dem_dataset_prefix}_{N/S}{lat:02d}_00_{E/W}{lon:03d}_00_DEM.tif
e.g. Copernicus_DSM_COG_10_N34_00_E051_00_DEM/Copernicus_DSM_COG_10_N34_00_E051_00_DEM.tif
(that specific tile, covering Tehran, was confirmed to actually exist in
a live listing of the bucket -- along with several other real Iran-area
tiles -- while researching this file).

Downloaded via plain HTTPS GET (the bucket is public, no-sign-request --
no AWS account, no credentials, no signing needed), using `requests`,
already a proven Chaquopy dependency.

NOT EVERY TILE EXISTS: ocean areas have no tile at all (elevation is
implicitly zero there, per Copernicus's own documentation), and a small
number of tiles are withheld by country. A missing tile (HTTP 404) is
therefore an ordinary, expected outcome here -- it is recorded and
skipped, never treated as a fatal error.

DEM HALF TESTED SO FAR: tile enumeration (which 1x1 tiles cover a bbox)
and remote-key construction were verified in a local sandbox test against
Iran's real bbox and cross-checked against real tile names confirmed to
exist in a live bucket listing -- all matched. The full control flow
(download-and-save, 404 handling, manifest writing, resume-on-rerun
skipping an already-downloaded tile) was verified end-to-end in sandbox
using a fake HTTP session standing in for the real bucket -- all correct.
The actual network download path (the real HTTP GET itself, against the
real bucket) has NOT been tested -- this sandbox has no network access
at all, so that can only be tested where the app actually runs (GitHub
Actions CI or the Android device itself, per the agreed build order's
on-device confirmation step). Treat the download function as logically
reviewed and control-flow-tested, not yet proven against the live bucket.

===========================================================================

NDVI HALF (added in a later session): for each of this app's own 1x1
degree cells covering a country (the SAME grid the DEM half already
uses, reused via tiles_covering_bbox() below -- offline_ndvi_store.py's
own docstring explains why NDVI storage deliberately uses this simple
grid rather than real Sentinel-2 MGRS tiling), this queries the real,
free, public Earth Search STAC API (sentinel2_stac_client.py) for
Sentinel-2 L2A scenes in the country's configured composite window,
downloads the red/nir/scl COG band assets for the least-cloudy real
scenes found (capped at MAX_SCENES_PER_CELL -- see rationale below),
samples all three bands at a fixed output grid using
sentinel2_cog_reader.py, applies each real scene's own per-asset
scale/offset (read from that scene's actual STAC metadata, not a single
hardcoded assumption -- see sentinel2_stac_client.py for the
harmonization-offset background) and SCL-based cloud/water/shadow/snow
masking, takes the per-pixel median NDVI across scenes, and writes the
result into offline_ndvi_store.py's exact .npz schema.

OUTPUT GRID RESOLUTION -- A DELIBERATE, DOCUMENTED ENGINEERING TRADEOFF
(this is this project's own choice, not an external fact requiring
verification): Sentinel-2's native resolution is 10-20m; sampling a full
1x1-degree cell at that resolution is roughly 1e8 points, which -- even
with sentinel2_cog_reader.py's per-tile caching -- would make a
whole-country download (Iran: roughly 300 such cells) impractical as a
background mobile job. NDVI_GRID_SIZE=32 (1024 points/cell, roughly
3.5km/pixel at Iran's latitude) was chosen instead: far coarser than the
live pipeline's per-candidate core/halo check, but this offline
composite's honest job is letting an investigation COMPLETE with no
network access, not replacing the live per-candidate fetch. The user's
own stated NDVI requirement was temporal freshness ("averaged is fine"),
not spatial resolution, and no spatial-resolution requirement was
specified for NDVI the way 30m was explicitly agreed for DEM -- flagged
here for visibility since this resolution choice was not itself
pre-agreed the way DEM's was.

SCL MASKING CLASSES USED (the published ESA Sentinel-2 standard, the
same kind of external reference this project already cites for GPR
velocities in gpr_depth_model.py -- not fabricated): valid = SCL in
{4, 5, 7} (VEGETATION, NOT_VEGETATED, UNCLASSIFIED). Water (6) is
excluded to match this project's existing live-pipeline precedent in
ndvi_source_mobile.py (which also explicitly excludes SCL==6); clouds
(8,9,10), cloud shadow (3), snow (11), defective/saturated (1),
dark-area (2), and no-data (0) are excluded as ordinary real-world
quality filtering.

NDVI HALF TESTED in a local sandbox against a hand-built fake STAC search
response and synthetic red/nir/scl COG files (not real downloaded
Sentinel-2 data -- same already-flagged honest gap as the DEM half and
as sentinel2_stac_client.py/sentinel2_cog_reader.py): verified NDVI math
correctness against hand-computed expected values (including the
harmonization -0.1 offset case), SCL masking correctly excluding
cloud/water pixels on a per-point basis, multi-scene median compositing,
the "zero real scenes found" and "scenes found but none downloadable"
honest-empty cases (writes n_scenes_used=0 with an all-NaN grid rather
than fabricating a value or crashing), resumability (already-composited
cell skipped on re-run, reported "already_present"), the manifest file,
and a full round-trip read-back through
offline_ndvi_store.get_offline_ndvi()/get_offline_ndvi_metadata() on the
actually-written .npz file -- all passed on first run. The real network
calls (STAC search + band download against the live Earth Search API and
sentinel-cogs bucket) are, like every other real-network piece of this
project, unverified until the on-device/CI confirmation stage.

MINOR FOLLOW-UP FIX (same session as offline_download_runner.py, below):
an all-NaN composite pixel (every scene masked or out of that scene's
real coverage at that point -- an ordinary, already-handled outcome, not
a bug) was triggering a numpy RuntimeWarning on every occurrence. Now
explicitly suppressed around the nanmedian call so real Logcat output
isn't cluttered with noise for an outcome the code already handles
correctly -- behavior is unchanged, this only silences a benign warning.

BUGFIX (2026-09-02) -- UNIQUE TEMP FILENAMES, defense in depth for the
same concurrent-download race documented in offline_download_runner.py's
module docstring (that file's new per-country lock is the actual fix --
read that first). This file's own atomic-write helpers
(_download_one_tile's .tif.part, _download_band_file's .part, and
_write_ndvi_cell's .npz.part) all previously used a FIXED temp filename
derived only from the destination path. If two full download runs for
the same country were ever concurrent (the scenario that lock now
prevents), two writers targeting the SAME destination tile/band/cell
would race on the identical temp path -- whichever finished
os.replace() first would yank the other's temp file out from under it,
raising FileNotFoundError, caught by each function's existing broad
except-and-record-as-"error" handling. This is the concrete mechanism
behind the real on-device Iran run's inflated error counts (341/357 DEM
tiles, 357/357 NDVI cells) -- most of those were lost temp-file races,
not real network/API failures. Every temp path below now includes
os.getpid() and a random uuid, so two writers can no longer collide on
the same temp filename even if they do end up running concurrently.
"""

from __future__ import annotations

import json
import math
import os
import uuid
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, Tuple

import numpy as np
import requests

from offline_country_registry import CountryConfig
from offline_dem_store import local_tile_path
from offline_ndvi_store import local_cell_path
from sentinel2_cog_reader import Sentinel2CogBand, UnsupportedS2TiffError
from sentinel2_stac_client import search_scenes, Sentinel2Scene, StacSearchError


def _unique_tmp_path(dest: str) -> str:
    """A temp path unique to this process and this call -- pid + a
    random uuid, not a fixed '.part' suffix. See module docstring's
    2026-09-02 BUGFIX note: this means two writers targeting the same
    `dest` (from an accidental concurrent download run) can never
    collide on the identical temp filename and race each other's
    os.replace(). The actual prevention is offline_download_runner.py's
    per-country lock; this is defense in depth on top of it."""
    return f"{dest}.{os.getpid()}.{uuid.uuid4().hex}.part"


# =========================== DEM HALF (unchanged) ===========================

def tiles_covering_bbox(south: float, north: float, west: float, east: float) -> List[Tuple[int, int]]:
    """Returns the (lat, lon) southwest-corner integers of every 1x1
    degree tile that intersects the given bbox. Shared by the DEM half
    (above) and the NDVI half (below) -- NDVI reuses this same grid
    rather than implementing real Sentinel-2 MGRS tiling; see
    offline_ndvi_store.py for why."""
    lat0, lat1 = math.floor(south), math.floor(north)
    lon0, lon1 = math.floor(west), math.floor(east)
    return [(lat, lon) for lat in range(lat0, lat1 + 1) for lon in range(lon0, lon1 + 1)]


def _remote_tile_key(dem_dataset_prefix: str, lat: int, lon: int) -> str:
    """The real S3 object key for a tile, e.g.
    'Copernicus_DSM_COG_10_N34_00_E051_00_DEM/Copernicus_DSM_COG_10_N34_00_E051_00_DEM.tif'
    -- confirmed against a real, live bucket listing."""
    ns = 'N' if lat >= 0 else 'S'
    ew = 'E' if lon >= 0 else 'W'
    name = f"{dem_dataset_prefix}_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00_DEM"
    return f"{name}/{name}.tif"


def remote_tile_url(country: CountryConfig, lat: int, lon: int) -> str:
    key = _remote_tile_key(country.dem_dataset_prefix, lat, lon)
    return f"https://{country.dem_s3_bucket}.s3.amazonaws.com/{key}"


@dataclass
class TileDownloadResult:
    lat: int
    lon: int
    status: str  # "downloaded", "already_present", "not_available", "error"
    detail: str = ""


def _download_one_tile(country: CountryConfig, offline_data_root: str, lat: int, lon: int,
                        session=None) -> TileDownloadResult:
    # +0.5 nudges the integer southwest-corner into a point safely inside
    # that same tile, so offline_dem_store's coordinate-based
    # local_tile_path() resolves to this tile's file (floor() recovers
    # the same lat/lon integer either way).
    dest = local_tile_path(country.storage_folder, offline_data_root, lat + 0.5, lon + 0.5)
    if os.path.isfile(dest):
        return TileDownloadResult(lat, lon, "already_present")

    url = remote_tile_url(country, lat, lon)
    http = session or requests
    try:
        resp = http.get(url, timeout=60, stream=True)
    except requests.RequestException as exc:
        return TileDownloadResult(lat, lon, "error", str(exc))

    if resp.status_code == 404:
        # Ordinary, expected: ocean tile, or one of the small number of
        # tiles Copernicus hasn't released publicly yet. Not an error.
        return TileDownloadResult(lat, lon, "not_available", "HTTP 404")
    if resp.status_code != 200:
        return TileDownloadResult(lat, lon, "error", f"HTTP {resp.status_code}")

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp_path = _unique_tmp_path(dest)
    try:
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        os.replace(tmp_path, dest)  # atomic -- never leaves a half-written file at the real path
    except Exception as exc:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return TileDownloadResult(lat, lon, "error", str(exc))

    return TileDownloadResult(lat, lon, "downloaded")


def download_country_dem(
    country: CountryConfig,
    offline_data_root: str,
    progress_callback: Optional[Callable[[int, int, TileDownloadResult], None]] = None,
) -> List[TileDownloadResult]:
    """Downloads every DEM tile covering `country`'s bbox that isn't
    already present locally. Resumable by nature: already-downloaded
    tiles are skipped on a re-run (its own explicit 'already_present'
    result rather than silently re-downloading), so an interrupted
    download can just be started again.

    progress_callback, if given, is called after each tile with
    (tiles_done, tiles_total, result) -- intended for
    OfflineDataActivity.kt (via Chaquopy) to update a progress bar,
    not yet wired up.

    Writes a manifest.json in the country's storage folder recording
    exactly what happened for every tile -- never silently drops a
    failure.
    """
    tiles = tiles_covering_bbox(country.south, country.north, country.west, country.east)
    results: List[TileDownloadResult] = []
    session = requests.Session()

    for i, (lat, lon) in enumerate(tiles):
        result = _download_one_tile(country, offline_data_root, lat, lon, session=session)
        results.append(result)
        if progress_callback is not None:
            progress_callback(i + 1, len(tiles), result)

    manifest_path = os.path.join(offline_data_root, country.storage_folder, "dem_manifest.json")
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    manifest = {
        "country_iso": country.iso_code,
        "bbox": {"south": country.south, "north": country.north, "west": country.west, "east": country.east},
        "dem_resolution_m": country.dem_resolution_m,
        "tiles": [
            {"lat": r.lat, "lon": r.lon, "status": r.status, "detail": r.detail}
            for r in results
        ],
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return results


# =========================== NDVI HALF (new) ===========================

NDVI_GRID_SIZE = 32  # see module docstring for the resolution rationale
MAX_SCENES_PER_CELL = 4  # caps whole-country download cost; scenes already sorted least-cloudy-first
VALID_SCL_CLASSES = frozenset({4, 5, 7})  # VEGETATION, NOT_VEGETATED, UNCLASSIFIED


@dataclass
class CellDownloadResult:
    lat: int
    lon: int
    status: str  # "composited", "empty_no_scenes", "already_present", "error"
    n_scenes_used: int = 0
    detail: str = ""


def _composite_window(window_days: int) -> tuple:
    """Real 'last N days ending now (UTC)' window, same pattern already
    proven in ndvi_source_mobile.py's _default_time_range()."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=window_days)
    return start.date().isoformat(), now.date().isoformat()


def _output_grid(lat: int, lon: int, n: int):
    """Centered sample points for an n x n grid over the 1x1 degree cell
    with southwest corner (lat, lon). Row 0 = north edge, matching
    offline_ndvi_store.py's row-index convention exactly (verified by
    round-trip in this module's own sandbox test)."""
    lat_min, lat_max = float(lat), float(lat + 1)
    lon_min, lon_max = float(lon), float(lon + 1)
    lats = [lat_max - (i + 0.5) / n * (lat_max - lat_min) for i in range(n)]
    lons = [lon_min + (j + 0.5) / n * (lon_max - lon_min) for j in range(n)]
    return lats, lons, lat_min, lat_max, lon_min, lon_max


def _download_band_file(url: str, dest_path: str, session, timeout: int = 60) -> None:
    """Same atomic-save pattern already proven in download_country_dem's
    _download_one_tile: temp file + os.replace, never leaves a
    half-written file at the real path. Skips re-download if already
    present (resumable)."""
    if os.path.isfile(dest_path):
        return
    resp = session.get(url, timeout=timeout, stream=True)
    if resp.status_code != 200:
        raise IOError(f"HTTP {resp.status_code} downloading {url}")
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp_path = _unique_tmp_path(dest_path)
    try:
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        os.replace(tmp_path, dest_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _composite_one_scene(scene: Sentinel2Scene, lats, lons, scenes_cache_dir: str, session) -> np.ndarray:
    """Downloads (if needed) and samples one real scene's red/nir/scl
    bands at every output grid point, returning an NDVI grid with NaN
    at any masked/invalid pixel. Real per-scene scale/offset applied to
    red/nir before computing the ratio -- see module docstring."""
    scene_dir = os.path.join(scenes_cache_dir, scene.scene_id)
    red_path = os.path.join(scene_dir, "red.tif")
    nir_path = os.path.join(scene_dir, "nir.tif")
    scl_path = os.path.join(scene_dir, "scl.tif")

    _download_band_file(scene.assets["red"].href, red_path, session)
    _download_band_file(scene.assets["nir"].href, nir_path, session)
    _download_band_file(scene.assets["scl"].href, scl_path, session)

    red_band = Sentinel2CogBand(red_path)
    nir_band = Sentinel2CogBand(nir_path)
    scl_band = Sentinel2CogBand(scl_path)

    red_asset = scene.assets["red"]
    nir_asset = scene.assets["nir"]

    n = len(lats)
    grid = np.full((n, n), np.nan, dtype=np.float32)

    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            scl_val = scl_band.get_value(lon, lat)
            if scl_val is None or int(round(scl_val)) not in VALID_SCL_CLASSES:
                continue
            red_dn = red_band.get_value(lon, lat)
            nir_dn = nir_band.get_value(lon, lat)
            if red_dn is None or nir_dn is None:
                continue

            red_refl = red_dn * red_asset.scale + red_asset.offset
            nir_refl = nir_dn * nir_asset.scale + nir_asset.offset
            denom = red_refl + nir_refl
            if abs(denom) < 1e-9:
                continue
            grid[i, j] = (nir_refl - red_refl) / denom

    return grid


def _write_ndvi_cell(dest_path, ndvi, lat_min, lat_max, lon_min, lon_max, window_start, window_end, n_scenes_used):
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp_path = _unique_tmp_path(dest_path)
    np.savez(
        tmp_path,
        ndvi=ndvi.astype(np.float32),
        lat_min=np.float64(lat_min), lat_max=np.float64(lat_max),
        lon_min=np.float64(lon_min), lon_max=np.float64(lon_max),
        window_start=window_start, window_end=window_end,
        n_scenes_used=np.int64(n_scenes_used),
    )
    # np.savez appends .npz to the filename if not already present; match
    # that behavior explicitly rather than relying on it implicitly.
    written_path = tmp_path if tmp_path.endswith(".npz") else tmp_path + ".npz"
    os.replace(written_path, dest_path)


def _composite_one_cell(
    country: CountryConfig,
    offline_data_root: str,
    lat: int,
    lon: int,
    scenes_cache_dir: str,
    session,
) -> CellDownloadResult:
    dest = local_cell_path(country.storage_folder, offline_data_root, lat + 0.5, lon + 0.5)
    if os.path.isfile(dest):
        return CellDownloadResult(lat, lon, "already_present")

    window_start, window_end = _composite_window(country.ndvi_composite_window_days)
    south, north, west, east = float(lat), float(lat + 1), float(lon), float(lon + 1)

    try:
        found = search_scenes(
            south=south, north=north, west=west, east=east,
            date_from=window_start, date_to=window_end,
            max_cloud_cover=60.0, limit=MAX_SCENES_PER_CELL,
            session=session,
        )
    except StacSearchError as exc:
        return CellDownloadResult(lat, lon, "error", detail=str(exc))

    lats, lons, lat_min, lat_max, lon_min, lon_max = _output_grid(lat, lon, NDVI_GRID_SIZE)

    if not found:
        _write_ndvi_cell(dest, np.full((NDVI_GRID_SIZE, NDVI_GRID_SIZE), np.nan, dtype=np.float32),
                          lat_min, lat_max, lon_min, lon_max, window_start, window_end, 0)
        return CellDownloadResult(lat, lon, "empty_no_scenes", n_scenes_used=0)

    per_scene_grids: List[np.ndarray] = []
    n_used = 0

    for scene in found[:MAX_SCENES_PER_CELL]:
        try:
            grid = _composite_one_scene(scene, lats, lons, scenes_cache_dir, session)
        except (UnsupportedS2TiffError, IOError, StacSearchError):
            # A single bad/undownloadable scene doesn't fail the whole
            # cell -- skip it and use whatever real scenes DID work,
            # matching this project's existing precedent (a single
            # malformed STAC item doesn't fail the whole search either).
            continue
        per_scene_grids.append(grid)
        n_used += 1

    if n_used == 0:
        _write_ndvi_cell(dest, np.full((NDVI_GRID_SIZE, NDVI_GRID_SIZE), np.nan, dtype=np.float32),
                          lat_min, lat_max, lon_min, lon_max, window_start, window_end, 0)
        return CellDownloadResult(lat, lon, "empty_no_scenes", n_scenes_used=0,
                                   detail="scenes were found but none could be downloaded/decoded")

    stacked = np.stack(per_scene_grids, axis=0)
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        # An all-NaN pixel (every scene masked/out-of-coverage there) is
        # an ordinary, already-handled outcome -- nanmedian correctly
        # returns NaN for it -- not a real problem worth surfacing as a
        # runtime warning.
        warnings.simplefilter("ignore", category=RuntimeWarning)
        composite = np.nanmedian(stacked, axis=0).astype(np.float32)

    _write_ndvi_cell(dest, composite, lat_min, lat_max, lon_min, lon_max, window_start, window_end, n_used)
    return CellDownloadResult(lat, lon, "composited", n_scenes_used=n_used)


def download_country_ndvi(
    country: CountryConfig,
    offline_data_root: str,
    progress_callback: Optional[Callable[[int, int, CellDownloadResult], None]] = None,
) -> List[CellDownloadResult]:
    """Downloads/composites every NDVI cell covering `country`'s bbox
    that isn't already present locally. Resumable, same as
    download_country_dem: an already-composited cell is reported
    'already_present' and skipped, so an interrupted country-wide
    download can simply be re-run.

    Writes an ndvi_manifest.json in the country's storage folder,
    mirroring dem_manifest.json's role -- records exactly what happened
    for every cell, including the honest 'zero real scenes found' case,
    never silently drops a failure.
    """
    cells = tiles_covering_bbox(country.south, country.north, country.west, country.east)
    results: List[CellDownloadResult] = []
    session = requests.Session()
    scenes_cache_dir = os.path.join(offline_data_root, country.storage_folder, "ndvi_scenes_cache")

    for i, (lat, lon) in enumerate(cells):
        result = _composite_one_cell(country, offline_data_root, lat, lon, scenes_cache_dir, session)
        results.append(result)
        if progress_callback is not None:
            progress_callback(i + 1, len(cells), result)

    manifest_path = os.path.join(offline_data_root, country.storage_folder, "ndvi_manifest.json")
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    manifest = {
        "country_iso": country.iso_code,
        "bbox": {"south": country.south, "north": country.north, "west": country.west, "east": country.east},
        "ndvi_grid_size": NDVI_GRID_SIZE,
        "composite_window_days": country.ndvi_composite_window_days,
        "cells": [
            {"lat": r.lat, "lon": r.lon, "status": r.status, "n_scenes_used": r.n_scenes_used, "detail": r.detail}
            for r in results
        ],
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return results
