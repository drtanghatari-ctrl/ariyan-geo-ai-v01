"""
offline_data_manager.py

Part of ARIYAN GEO AI's OFFLINE MODE extension.

The actual bulk downloader for a country's offline DEM package: given a
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

TESTED SO FAR: tile enumeration (which 1x1 tiles cover a bbox) and
remote-key construction were verified in a local sandbox test against
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
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import requests

from offline_country_registry import CountryConfig
from offline_dem_store import local_tile_path


def tiles_covering_bbox(south: float, north: float, west: float, east: float) -> List[Tuple[int, int]]:
    """Returns the (lat, lon) southwest-corner integers of every 1x1
    degree tile that intersects the given bbox."""
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
    tmp_path = dest + ".part"
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
