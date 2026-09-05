"""
offline_ndvi_store.py

Part of ARIYAN GEO AI's OFFLINE MODE extension (NDVI half).

Given a coordinate, this module answers two things:
  1. Which locally-downloaded NDVI composite cell (if any) covers it?
  2. If one exists, what's the NDVI value at that coordinate, and how
     was that composite actually built (date window, scene count)?

It does NOT download or composite anything -- that is the NDVI half of
offline_data_manager.py. This module only knows how to name/locate
composite cells that have ALREADY been produced by that downloader, and
how to read them.

CELL IDENTITY -- IMPORTANT, READ BEFORE CHANGING: unlike Copernicus DEM,
Sentinel-2 does NOT get tiled by this app's own grid here. Real Sentinel-2
scenes are tiled by MGRS (100km UTM grid squares), and correctly computing
a coordinate's MGRS grid-square LETTER (not just its UTM zone) requires
implementing the actual MGRS lettering standard -- a non-trivial algorithm
that could not be verified against a real reference in this environment
(no live network access here). Rather than risk a subtly wrong
hand-rolled MGRS implementation silently mis-tiling real data, this
module deliberately uses its OWN simple, exactly-computable storage grid:
plain 1x1 degree WGS84 lat/lon cells, identified the same way
offline_dem_store.py already identifies DEM tiles (by southwest corner,
e.g. "N32_E051"). This is NOT a Sentinel-2 MGRS tile id -- it is purely
this app's local storage/lookup key. The NDVI downloader (offline half of
offline_data_manager.py) is responsible for querying Sentinel-2 by real
bbox (which needs no MGRS math at all -- the Earth Search STAC API takes
a plain bbox) and writing its composite output into cells keyed this way.

STORAGE FORMAT: each cell is a single .npz file (numpy's own format --
deliberately not a TIFF; this is OUR OWN output, fully under this app's
control, so there is no reason to hand-roll a format as complex as the
one geotiff_cog_reader.py/sentinel2_cog_reader.py must parse for
externally-produced files). Contents (written by the downloader, not
this module):
  - ndvi: float32 array, shape (rows, cols). NaN marks a pixel with no
    cloud-free observation in the composite window -- an honest "no
    data" rather than a fabricated value.
  - lat_min, lat_max, lon_min, lon_max: the cell's real covered bounds
    (stored explicitly rather than re-derived, so this module never has
    to assume the array exactly fills the nominal 1x1 degree cell).
  - window_start, window_end: ISO date strings for the composite's real
    date range.
  - n_scenes_used: how many individual Sentinel-2 scenes contributed to
    this composite (0 is a valid, honest value -- means no cloud-free
    scene was found in the window for that cell).

PER-CELL CACHING FIX (this session, found via real on-device testing --
same root cause as offline_dem_store.py's identical fix, see that
module's own docstring for the full explanation): _load_cell() re-read
and re-parsed the same .npz file from disk on EVERY call, with no
caching, and offline_evidence_fallback.py's fetch_offline_ndvi() calls
BOTH get_offline_ndvi() and get_offline_ndvi_metadata() -- each
independently calling _load_cell() -- for every one of up to 9,216 AOI
grid points. Since a typical AOI is tiny compared to this module's 1x1
degree cell, nearly all of those points land in the same one or two
cells, meaning a single investigation could re-load the identical .npz
file from disk roughly 18,000 times (2 loads x ~9,216 points) for data
that never changes between calls. Fixed by caching each loaded cell
dict in a module-level dict, keyed by absolute file path, so each cell
is read from disk and parsed at most ONCE per app process.

HONEST TRADEOFF, same as offline_dem_store.py: this cache is never
invalidated by this module itself. clear_cell_cache() exists for the
case of re-downloading the same country's same cell within one
continuous app session, but is NOT YET wired up to be called
automatically after a download completes -- an honest follow-up item,
not done in this pass.

TESTED: end-to-end in a local sandbox test against a hand-built synthetic
.npz cell (see build_and_test_offline_ndvi_store.py), including a
coordinate with a real value, a coordinate landing on a NaN (no-data)
pixel, a coordinate outside the stored cell's actual bounds, and a
missing-file (never-downloaded) case. The caching behavior added this
session (same loaded cell dict reused across repeated calls for the
same path) has been reasoned through but not yet re-run against that
same sandbox fixture -- an honest gap to close alongside the on-device
retest this fix is going out for.
"""

from __future__ import annotations

import math
import os
from typing import Optional, Dict, Any

import numpy as np

_cell_cache: Dict[str, Optional[Dict[str, Any]]] = {}


def clear_cell_cache() -> None:
    """Drops all cached, already-loaded NDVI cell dicts. Not yet called
    automatically anywhere (see module docstring's PER-CELL CACHING FIX
    note) -- available for OfflineDataActivity.kt / offline_data_manager.py
    to call after a fresh download completes, once that wiring is added."""
    _cell_cache.clear()


def ndvi_cell_id_for(lat: float, lon: float) -> str:
    """Returns this coordinate's 1x1 degree NDVI storage-cell identifier,
    e.g. 'N32_E051' or 'S06_W178' -- keyed by the cell's southwest
    corner. This is THIS APP'S OWN storage grid, not a Sentinel-2 MGRS
    tile id (see module docstring)."""
    lat_deg = math.floor(lat)
    lon_deg = math.floor(lon)
    ns = 'N' if lat_deg >= 0 else 'S'
    ew = 'E' if lon_deg >= 0 else 'W'
    return f"{ns}{abs(lat_deg):02d}_{ew}{abs(lon_deg):03d}"


def _ndvi_dir(storage_folder: str, offline_data_root: str) -> str:
    return os.path.join(offline_data_root, storage_folder, "ndvi")


def local_cell_path(storage_folder: str, offline_data_root: str, lat: float, lon: float) -> str:
    """The local file path a downloaded NDVI composite cell for this
    coordinate would live at, whether or not it's actually been
    downloaded yet."""
    return os.path.join(_ndvi_dir(storage_folder, offline_data_root), f"{ndvi_cell_id_for(lat, lon)}.npz")


def has_offline_ndvi(storage_folder: str, offline_data_root: str, lat: float, lon: float) -> bool:
    """Cheap existence check -- used by the live-pipeline fallback logic
    to decide whether offline NDVI data is even available before trying
    to read it."""
    return os.path.isfile(local_cell_path(storage_folder, offline_data_root, lat, lon))


def _load_cell(path: str) -> Optional[Dict[str, Any]]:
    """Loads and parses one .npz cell, or returns None if it doesn't
    exist. THIS SESSION'S FIX: the result (including a genuine "doesn't
    exist" None) is now cached per path in _cell_cache, so repeated
    calls for the same cell -- the overwhelmingly common case within
    one investigation's AOI grid -- reuse the already-parsed result
    instead of re-reading the file from disk every time. Caching the
    None case too (not just successful loads) matters here: a
    genuinely-missing cell is looked up just as repeatedly as an
    existing one, and os.path.isfile() + a failed open is itself real,
    non-free disk I/O worth avoiding on every one of ~9,216 grid
    points."""
    if path in _cell_cache:
        return _cell_cache[path]

    if not os.path.isfile(path):
        _cell_cache[path] = None
        return None

    with np.load(path, allow_pickle=False) as npz:
        cell = {
            "ndvi": npz["ndvi"],
            "lat_min": float(npz["lat_min"]),
            "lat_max": float(npz["lat_max"]),
            "lon_min": float(npz["lon_min"]),
            "lon_max": float(npz["lon_max"]),
            "window_start": str(npz["window_start"]),
            "window_end": str(npz["window_end"]),
            "n_scenes_used": int(npz["n_scenes_used"]),
        }
    _cell_cache[path] = cell
    return cell


def get_offline_ndvi(storage_folder: str, offline_data_root: str, lat: float, lon: float) -> Optional[float]:
    """Returns the NDVI value at (lat, lon) from a locally-downloaded
    composite cell, or None if no cell has been downloaded for that
    coordinate, the coordinate falls outside the cell's actually-covered
    bounds, or the composite has no cloud-free observation at that exact
    pixel (NaN). Never raises for any of these ordinary cases."""
    path = local_cell_path(storage_folder, offline_data_root, lat, lon)
    cell = _load_cell(path)
    if cell is None:
        return None

    ndvi = cell["ndvi"]
    rows, cols = ndvi.shape
    lat_min, lat_max = cell["lat_min"], cell["lat_max"]
    lon_min, lon_max = cell["lon_min"], cell["lon_max"]
    if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
        return None

    # row 0 = north edge (lat_max), matching standard raster row order
    row = int((lat_max - lat) / (lat_max - lat_min) * rows)
    col = int((lon - lon_min) / (lon_max - lon_min) * cols)
    row = min(max(row, 0), rows - 1)
    col = min(max(col, 0), cols - 1)

    value = float(ndvi[row, col])
    if math.isnan(value):
        return None
    return value


def get_offline_ndvi_metadata(storage_folder: str, offline_data_root: str, lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """Returns the composite's provenance (date window, how many real
    scenes contributed) for the cell covering (lat, lon), or None if no
    cell has been downloaded there. Intended for surfacing honest
    data-quality context to the user alongside the NDVI value itself --
    matches this project's existing practice (e.g. GPR depth ranges,
    debate engine's insufficient_data labeling) of never presenting a
    derived number without also disclosing how solid it is.

    THIS SESSION'S FIX: shares the same per-path cache as
    get_offline_ndvi() via _load_cell() -- calling both functions for
    the same (lat, lon), as offline_evidence_fallback.py's
    fetch_offline_ndvi() does for every AOI grid point, now costs one
    disk read total for that cell, not two."""
    path = local_cell_path(storage_folder, offline_data_root, lat, lon)
    cell = _load_cell(path)
    if cell is None:
        return None
    return {
        "window_start": cell["window_start"],
        "window_end": cell["window_end"],
        "n_scenes_used": cell["n_scenes_used"],
    }