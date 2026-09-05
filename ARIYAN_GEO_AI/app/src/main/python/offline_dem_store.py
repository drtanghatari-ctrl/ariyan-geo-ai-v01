"""
offline_dem_store.py

Part of ARIYAN GEO AI's OFFLINE MODE extension.

Given a coordinate, this module answers two things:
  1. Which locally-downloaded DEM tile file (if any) covers it?
  2. If one exists, what's the elevation at that coordinate?

It does NOT download anything -- that's offline_data_manager.py's job.
This module only knows how to name/locate tiles that have ALREADY been
downloaded to local storage, and how to read them via
geotiff_cog_reader.py.

TILE IDENTITY: Copernicus DEM is distributed in a real, fixed 1x1 degree
grid, keyed by the tile's southwest corner (confirmed against the AWS
bucket's own documentation). A coordinate's tile id here is simply
floor(lat)/floor(lon), formatted as e.g. "N32_E051" or "S06_W178". This
is THIS MODULE'S OWN local filename convention -- it is not yet
confirmed to exactly match the AWS bucket's remote S3 key/filename
structure (which uses the longer "Copernicus_DSM_COG_<res>_<N/S>lat_00_
<E/W>lon_00_DEM" folder+file name from offline_country_registry.py).
offline_data_manager.py is responsible for translating between the
two: downloading from the real remote name, saving locally under the
clean tile-id name this module expects.

PER-TILE CACHING FIX (this session, found via real on-device testing):
fetch_offline_dem() in offline_evidence_fallback.py samples this
module's get_offline_elevation() once PER AOI GRID CELL -- up to 9,216
times for a default 96x96 investigation grid. Since a typical AOI
(hundreds of meters radius) is tiny compared to this module's 1x1
degree tile (~111km), nearly all of those calls land in the SAME
single tile file. The original version of this function opened and
fully decoded a fresh CopernicusDemTile for EVERY call, with no
caching -- meaning a single investigation could re-open and re-parse
the identical GeoTIFF file thousands of times over. On a real device,
this was the actual cause of a several-minute wait that was originally
(wrongly) suspected to be a live-network hang -- it was pure redundant
CPU/IO work, unrelated to network conditions entirely, which is why
tightening network timeouts elsewhere had no effect on the wait time.

Fixed by caching the opened CopernicusDemTile object in a module-level
dict, keyed by absolute file path, so each tile is opened and decoded
at most ONCE per app process, not once per grid cell. HONEST
TRADEOFF, stated rather than hidden: this cache is never invalidated
by this module itself -- if a user re-downloads/replaces a tile file
via 'Download Offline Data' while the app process is still running,
a stale in-memory copy could keep being served until the app is fully
restarted. clear_tile_cache() below exists for exactly that case, but
is NOT YET wired up to be called automatically after a download
completes -- that wiring is an honest follow-up item, not done in
this pass, since it lives in a different file
(OfflineDataActivity.kt / offline_data_manager.py) this session didn't
touch. In the ordinary flow (download once, then run investigations
against that country later, likely after an app restart anyway) this
gap does not matter; it only matters for the unusual case of
re-downloading the SAME country's SAME tile within one continuous app
session.

TESTED: end-to-end in a local sandbox test -- a real, previously-verified
synthetic COG file was placed at the exact local path this module
computes, and tile_id_for(), has_offline_dem(), and get_offline_elevation()
all returned correct results, both for a coordinate inside the downloaded
tile and for a coordinate with no tile downloaded at all (correctly
returns False/None rather than erroring). The caching behavior added
this session (same tile object reused across repeated calls for the
same path) has been reasoned through but not yet re-run against that
same sandbox fixture -- an honest gap to close alongside the on-device
retest this fix is going out for.
"""

from __future__ import annotations

import math
import os
from typing import Dict, Optional

from geotiff_cog_reader import CopernicusDemTile

_tile_cache: Dict[str, CopernicusDemTile] = {}


def clear_tile_cache() -> None:
    """Drops all cached, already-opened DEM tile objects. Not yet called
    automatically anywhere (see module docstring's PER-TILE CACHING FIX
    note) -- available for OfflineDataActivity.kt / offline_data_manager.py
    to call after a fresh download completes, once that wiring is added."""
    _tile_cache.clear()


def _get_cached_tile(path: str) -> CopernicusDemTile:
    """Returns the cached CopernicusDemTile for this path, opening and
    decoding it (once) if this is the first request for it this app
    session. See module docstring's PER-TILE CACHING FIX note -- this is
    the change that avoids re-parsing the same tile file thousands of
    times within a single investigation."""
    tile = _tile_cache.get(path)
    if tile is None:
        tile = CopernicusDemTile(path)
        _tile_cache[path] = tile
    return tile


def tile_id_for(lat: float, lon: float) -> str:
    """Returns this coordinate's 1x1 degree DEM tile identifier, e.g.
    'N32_E051' or 'S06_W178' -- keyed by the tile's southwest corner,
    matching Copernicus's own tiling convention."""
    lat_deg = math.floor(lat)
    lon_deg = math.floor(lon)
    ns = 'N' if lat_deg >= 0 else 'S'
    ew = 'E' if lon_deg >= 0 else 'W'
    return f"{ns}{abs(lat_deg):02d}_{ew}{abs(lon_deg):03d}"


def _dem_dir(storage_folder: str, offline_data_root: str) -> str:
    return os.path.join(offline_data_root, storage_folder, "dem")


def local_tile_path(storage_folder: str, offline_data_root: str, lat: float, lon: float) -> str:
    """The local file path a downloaded DEM tile for this coordinate
    would live at, whether or not it's actually been downloaded yet."""
    return os.path.join(_dem_dir(storage_folder, offline_data_root), f"{tile_id_for(lat, lon)}.tif")


def has_offline_dem(storage_folder: str, offline_data_root: str, lat: float, lon: float) -> bool:
    """Cheap existence check -- used by the live-pipeline fallback logic
    to decide whether offline data is even available before trying to
    read it."""
    return os.path.isfile(local_tile_path(storage_folder, offline_data_root, lat, lon))


def get_offline_elevation(storage_folder: str, offline_data_root: str, lat: float, lon: float) -> Optional[float]:
    """Returns the elevation at (lat, lon) from a locally-downloaded DEM
    tile, or None if no tile has been downloaded for that coordinate.
    Never raises for a missing file -- a missing tile is an expected,
    ordinary case (coordinate outside the downloaded area, or simply not
    downloaded yet), not an error.

    THIS SESSION'S FIX: the underlying tile object is now cached per
    file path (see _get_cached_tile / module docstring) -- repeated
    calls for coordinates in the same tile (the overwhelmingly common
    case for one investigation's AOI grid) reuse the already-opened,
    already-decoded tile instead of re-reading and re-parsing the file
    from disk every time."""
    path = local_tile_path(storage_folder, offline_data_root, lat, lon)
    if not os.path.isfile(path):
        return None
    tile = _get_cached_tile(path)
    return tile.get_elevation(lon, lat)