"""
offline_dem_store.py

Part of ARIYAN GEO AI's OFFLINE MODE extension.

Given a coordinate, this module answers two things:
  1. Which locally-downloaded DEM tile file (if any) covers it?
  2. If one exists, what's the elevation at that coordinate?

It does NOT download anything -- that's offline_data_manager.py's job
(not yet written). This module only knows how to name/locate tiles that
have ALREADY been downloaded to local storage, and how to read them via
geotiff_cog_reader.py.

TILE IDENTITY: Copernicus DEM is distributed in a real, fixed 1x1 degree
grid, keyed by the tile's southwest corner (confirmed against the AWS
bucket's own documentation). A coordinate's tile id here is simply
floor(lat)/floor(lon), formatted as e.g. "N32_E051" or "S06_W178". This
is THIS MODULE'S OWN local filename convention -- it is not yet
confirmed to exactly match the AWS bucket's remote S3 key/filename
structure (which uses the longer "Copernicus_DSM_COG_<res>_<N/S>lat_00_
<E/W>lon_00_DEM" folder+file name from offline_country_registry.py).
offline_data_manager.py, when it's written, is responsible for
translating between the two: downloading from the real remote name,
saving locally under the clean tile-id name this module expects.

TESTED: end-to-end in a local sandbox test -- a real, previously-verified
synthetic COG file was placed at the exact local path this module
computes, and tile_id_for(), has_offline_dem(), and get_offline_elevation()
all returned correct results, both for a coordinate inside the downloaded
tile and for a coordinate with no tile downloaded at all (correctly
returns False/None rather than erroring).
"""

from __future__ import annotations

import math
import os
from typing import Optional

from geotiff_cog_reader import CopernicusDemTile


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
    downloaded yet), not an error."""
    path = local_tile_path(storage_folder, offline_data_root, lat, lon)
    if not os.path.isfile(path):
        return None
    tile = CopernicusDemTile(path)
    return tile.get_elevation(lon, lat)
