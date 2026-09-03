"""
offline_evidence_fallback.py

Part of ARIYAN GEO AI's OFFLINE MODE extension.

THIS FILE IS THE BRIDGE between the two halves of the project that
previously didn't talk to each other: the LIVE pipeline (dem_source_
mobile.py, ndvi_source_mobile.py) and the OFFLINE pre-downloaded
library (offline_dem_store.py, offline_ndvi_store.py). Before this
session, a live-fetch failure had exactly one fallback: SyntheticDEM
Source / SyntheticNDVISource (dem_source.py / imagery_source.py) --
fabricated terrain, clearly labeled as such, but fabricated data
nonetheless. That violated this project's own hard requirement (nothing
synthetic/fake -- data must actually be gathered) the moment a user
ever saw it as the DEFAULT behavior rather than an explicit opt-in
dev/test mode, which is exactly what happened: switchRealDem defaulted
OFF, so the main investigation screen ran on synthetic terrain unless
the user remembered to flip a switch and paste in an API key every
session.

THE FIX, this session: real data is now ALWAYS attempted first (no
toggle -- see investigation_mobile.py / investigation_multi_mobile.py,
rewritten to call this module). If the real, live fetch fails for ANY
reason (no network, API key rejected, rate-limited, HTTP error,
response parse failure -- OpenTopographyFetchError / NDVIFetchError
cover all of these already), this module is asked whether the SAME
coordinate is covered by a country the user has already pre-downloaded
via OfflineDataActivity (offline_data_manager.py). If yes, that real
(if less fresh, less fine-resolution) previously-downloaded data is
used instead. If NEITHER real-live NOR real-offline data is available,
the caller raises a clear, honest error -- there is no third,
fabricated option anymore.

DEM: samples offline_dem_store.get_offline_elevation() at every AOI
grid point and assembles a DEM raster (dem_source.DEM) with the exact
same shape/orientation convention the live AAIGrid path already uses
(row 0 = north edge, col 0 = west edge, center-of-cell sampling -- see
_sample_grid_points() below, deliberately the same centered-sample
convention offline_data_manager.py's own _output_grid() already uses
for NDVI composite cells, for consistency across this project's two
offline grid samplers).

If ANY grid point falls in a DEM tile that was never downloaded (e.g.
the AOI straddles the edge of the pre-downloaded country, or the user
simply never ran a download at all), the WHOLE offline DEM fetch fails
honestly with OfflineDataUnavailableError rather than silently
returning a partial/interpolated/fabricated raster -- an investigation
result must be either fully real or an honest failure, never a mix
quietly presented as complete.

NDVI: same per-point sampling approach via offline_ndvi_store.
get_offline_ndvi(), producing a full-AOI raster (imagery_source.
NDVIRaster) that investigation_multi_mobile.py can run through the SAME
detect_raster_anomalies() + correlate_anomalies() pipeline already used
for an independent full-grid NDVI scan. HONEST LIMITATION, stated here
rather than hidden: the offline NDVI composite's native resolution is
NDVI_GRID_SIZE=32 cells per 1x1 degree (~3.5km/pixel at these
latitudes -- see offline_data_manager.py's own docstring for why that
coarse resolution was chosen), while a typical investigation AOI
(default 500m radius, 96x96 grid) is roughly 10m/cell. Many adjacent
AOI grid points will therefore land on the exact same underlying
offline NDVI pixel (nearest-neighbor sampling, not invented
interpolation between real measurements) -- real data, honestly
labeled and honestly coarse, not a claim of fine spatial resolution it
doesn't have. This is a genuinely weaker signal than the live
per-candidate Copernicus core/halo check it replaces, but it is real
Sentinel-2-derived data, not synthetic terrain -- consistent with this
module's whole purpose.

TESTED: sampling-grid math (centered points, row/col orientation) and
the all-or-nothing missing-tile behavior were verified in a local
sandbox against hand-placed fixture files at the exact paths
offline_dem_store.py/offline_ndvi_store.py compute, mirroring the test
approach already proven for those two modules themselves. The
end-to-end real-fetch-fails-then-offline-succeeds control flow (via
investigation_mobile.py/investigation_multi_mobile.py) has NOT yet been
run on an actual device with a real expired network connection and a
real previously-downloaded country -- that on-device confirmation is
the honest next step once this build compiles clean, same practice as
every other real-network piece of this project.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from coordinate import AreaOfInterest
from dem_source import DEM
from imagery_source import NDVIRaster
import offline_dem_store
import offline_ndvi_store
from offline_country_registry import get_country_for_point, CountryConfig


class OfflineDataUnavailableError(RuntimeError):
    """Raised when the offline library cannot honestly serve a real DEM
    or NDVI raster for a given AOI -- either because no registered
    country's bounding box covers this coordinate at all, or because at
    least one AOI grid point falls inside a tile/cell that has not
    actually been downloaded. Always carries a human-readable message;
    callers (investigation_mobile.py / investigation_multi_mobile.py)
    combine this with the live-fetch error into one final honest
    message shown to the user, rather than ever silently substituting
    fabricated data."""


def _sample_grid_points(aoi: AreaOfInterest) -> Tuple[List[float], List[float]]:
    """Centered sample (lat, lon) for every cell in the AOI's grid_size x
    grid_size grid, row 0 = north edge (aoi.max_lat), col 0 = west edge
    (aoi.min_lon) -- the same orientation convention
    dem_source_mobile.py's AAIGrid decoding and offline_data_manager.py's
    NDVI _output_grid() already use, so a DEM/NDVI raster built from
    this module lines up with what anomaly_detection_mobile.py and
    correlation.py already assume about grid layout."""
    n = aoi.grid_size
    lat_min, lat_max = aoi.min_lat, aoi.max_lat
    lon_min, lon_max = aoi.min_lon, aoi.max_lon
    lats = [lat_max - (i + 0.5) / n * (lat_max - lat_min) for i in range(n)]
    lons = [lon_min + (j + 0.5) / n * (lon_max - lon_min) for j in range(n)]
    return lats, lons


def _resolve_country(aoi: AreaOfInterest) -> CountryConfig:
    """Looks up which registered country's offline package covers this
    AOI's center point. Uses only the center, not every corner -- a
    small, realistic-radius AOI (hundreds of meters to a few km) that
    straddles a country's padded bounding-box edge is already an
    unusual edge case; the per-point missing-tile check in
    fetch_offline_dem/fetch_offline_ndvi below is what actually catches
    a genuinely under-covered AOI, honestly, regardless of country
    lookup granularity."""
    country = get_country_for_point(aoi.center.lat, aoi.center.lon)
    if country is None:
        raise OfflineDataUnavailableError(
            f"No offline country package is registered for this location "
            f"({aoi.center.lat:.4f}, {aoi.center.lon:.4f}). Offline fallback "
            f"data only exists for countries you've pre-downloaded via "
            f"'Offline Country Data'."
        )
    return country


def fetch_offline_dem(aoi: AreaOfInterest, offline_data_root: str) -> DEM:
    """Real fallback DEM source: samples offline_dem_store.py's
    already-downloaded Copernicus DEM tiles at every AOI grid point.
    Raises OfflineDataUnavailableError -- never returns a partial or
    fabricated raster -- if this coordinate isn't covered by any
    registered country, or if any grid point falls in a tile that
    hasn't actually been downloaded yet."""
    country = _resolve_country(aoi)
    lats, lons = _sample_grid_points(aoi)
    n = aoi.grid_size

    elevation = np.empty((n, n), dtype=np.float64)
    missing_count = 0
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            value = offline_dem_store.get_offline_elevation(
                country.storage_folder, offline_data_root, lat, lon
            )
            if value is None:
                missing_count += 1
                continue
            elevation[i, j] = value

    if missing_count > 0:
        raise OfflineDataUnavailableError(
            f"{missing_count} of {n * n} DEM grid points in this AOI have no "
            f"downloaded tile in the offline '{country.name}' package "
            f"(likely this AOI extends past the downloaded area, or the "
            f"download didn't fully complete). Re-run 'Download offline "
            f"data' for {country.name}, or move to a location well inside "
            f"the downloaded area."
        )

    return DEM(
        aoi=aoi,
        elevation_m=elevation,
        source=f"Offline library: Copernicus DEM GLO-30 ({country.name}, pre-downloaded)",
        synthetic=False,
        resolution_m=float(country.dem_resolution_m),
        acquisition_date=None,
        notes=(
            f"Real Copernicus DEM data, but read from this device's own "
            f"offline copy of {country.name} (downloaded earlier via "
            f"'Offline Country Data'), not fetched live for this run -- "
            f"used because a live OpenTopography fetch failed or no network "
            f"was available. Same real 30m dataset the live path uses."
        ),
    )


def fetch_offline_ndvi(aoi: AreaOfInterest, offline_data_root: str) -> NDVIRaster:
    """Real fallback NDVI source: samples offline_ndvi_store.py's
    already-downloaded Sentinel-2 composite cells at every AOI grid
    point. Same all-or-nothing honesty rule as fetch_offline_dem: any
    grid point with no downloaded cell fails the whole fetch rather than
    returning a partial raster. See module docstring for the resolution
    caveat (this composite is much coarser than a typical AOI grid, so
    many adjacent AOI cells will read the same real underlying pixel --
    real data, honestly coarse, not fabricated)."""
    country = _resolve_country(aoi)
    lats, lons = _sample_grid_points(aoi)
    n = aoi.grid_size

    ndvi = np.empty((n, n), dtype=np.float64)
    missing_count = 0
    window_starts = set()
    window_ends = set()
    n_scenes_seen: List[int] = []
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            value = offline_ndvi_store.get_offline_ndvi(
                country.storage_folder, offline_data_root, lat, lon
            )
            if value is None:
                missing_count += 1
                continue
            ndvi[i, j] = value
            meta = offline_ndvi_store.get_offline_ndvi_metadata(
                country.storage_folder, offline_data_root, lat, lon
            )
            if meta is not None:
                window_starts.add(meta["window_start"])
                window_ends.add(meta["window_end"])
                n_scenes_seen.append(meta["n_scenes_used"])

    if missing_count > 0:
        raise OfflineDataUnavailableError(
            f"{missing_count} of {n * n} NDVI grid points in this AOI have no "
            f"downloaded composite cell in the offline '{country.name}' "
            f"package. Re-run 'Download offline data' for {country.name}, or "
            f"move to a location well inside the downloaded area."
        )

    window_note = (
        f"composite window {min(window_starts)} to {max(window_ends)}"
        if window_starts and window_ends else "composite window unknown"
    )
    avg_scenes = (sum(n_scenes_seen) / len(n_scenes_seen)) if n_scenes_seen else 0.0

    return NDVIRaster(
        aoi=aoi,
        ndvi=ndvi,
        source=f"Offline library: Sentinel-2 L2A composite ({country.name}, pre-downloaded)",
        synthetic=False,
        resolution_m=float(country.dem_resolution_m) * 0 + 3500.0,  # ~NDVI_GRID_SIZE=32/1deg cell, see module docstring
        acquisition_date=None,
        cloud_cover_pct=None,
        notes=(
            f"Real Sentinel-2-derived NDVI, but read from this device's own "
            f"offline composite of {country.name} ({window_note}, average "
            f"{avg_scenes:.1f} real scenes per cell), not a live per-candidate "
            f"fetch -- used because a live Copernicus check failed or no "
            f"network was available. Resolution is COARSE (~3.5km/pixel) "
            f"compared to the live path's targeted check -- see this "
            f"module's docstring for why."
        ),
    )
