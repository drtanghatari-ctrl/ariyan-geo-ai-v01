"""
dem_source_mobile.py — Real, network-based DEM evidence acquisition for
the Android build.

dem_source.py's OpenTopographyDEMSource is real, working code, but it
decodes GeoTIFF via rasterio, which needs GDAL's native C++ code --
and Chaquopy cannot compile native code for Android (confirmed: this
is a real, documented failure other developers have hit trying to
install GDAL under Chaquopy, not a hypothetical concern). Rather than
ship a DEM source that would crash on first use on-device, this module
requests the same OpenTopography data as AAIGrid (plain text) and
decodes it with ascii_grid.py -- pure NumPy, no native dependency,
consistent with why np_ops.py exists in place of scipy.ndimage.

A second real issue this module handles rather than hides: the raster
OpenTopography returns for a given AOI is generally NOT square
(ncols != nrows), because SRTM-family datasets are gridded in
arc-seconds, and arc-seconds are not square in degrees away from the
equator, even though the AOI itself is square in meters. This module
resamples the real, irregular raster onto the AOI's own square
grid_size x grid_size grid (np_ops.resample_bilinear) before returning
it as a DEM, so the rest of the pipeline's square-grid assumption
holds. That resampling step is stated in the returned DEM's notes
field, not hidden in a JSON corner.

HARD-DEADLINE FIX (this session, found via real on-device airplane-mode
testing): the original version of this file passed timeout=30.0 to
requests.get() and assumed that bounded the whole call. On a real
device in real airplane mode, the fetch instead sat for 5+ minutes
with zero progress. Root cause: Python's requests/urllib3 `timeout`
parameter bounds the socket connect and read phases, but does NOT
reliably bound DNS resolution (socket.getaddrinfo()), which is a
separate, unbounded blocking OS-level call made before that timeout
starts counting -- a real, documented gotcha, not specific to this
app. Depending on how the Android network stack behaves when there is
genuinely no interface available, that resolution step can hang far
longer than the requests timeout would suggest. Fixed by wrapping the
actual network call in a real, thread-based hard deadline
(concurrent.futures): the call runs on a background thread, and the
calling thread gives up after `timeout_s` seconds regardless of what
that background thread is still doing underneath -- this bounds
wall-clock time no matter which phase (DNS, connect, TLS, read) is the
one actually stuck. The background thread may still be running after
we give up on it; it is simply abandoned and its eventual result (if
any) discarded, which is the standard accepted trade-off for making an
otherwise-unkillable blocking call time-bounded from the caller's side.
Default timeout_s also reduced from 30.0 to 10.0, since a real fallback
path (this device's offline DEM library) exists and a failed live fetch
should hand off to it quickly rather than making the user wait.

HONEST LIMITATION, updated: this module's HTTP/parsing/resampling logic
was originally verified only against a hand-built AAIGrid text fixture
and a known-shape resampling test (see tests/test_dem_source_mobile.py),
not a live OpenTopography call, because the sandbox this was built in
had no outbound network access. It has now been exercised on a real
physical device in real airplane mode (confirming the hang described
above) -- but a real SUCCESSFUL live fetch, with actual network and a
real API key, still has not yet been confirmed. That remains the
honest next on-device test once this fix is installed.
"""
from __future__ import annotations

import concurrent.futures

import numpy as np

from coordinate import AreaOfInterest
from dem_source import DEM
from ascii_grid import parse_ascii_grid, AsciiGridParseError
from np_ops import resample_bilinear


class OpenTopographyFetchError(RuntimeError):
    """Raised for any network, HTTP, or parsing failure fetching a real
    DEM. Always carries a human-readable message suitable for showing
    directly in the Android UI -- MainActivity.kt displays this
    message as-is rather than a generic "something went wrong"."""


RESOLUTION_BY_DEMTYPE_M = {
    "SRTMGL1": 30.0, "SRTMGL3": 90.0, "COP30": 30.0, "COP90": 90.0,
    "NASADEM": 30.0, "AW3D30": 30.0, "SRTM15Plus": 450.0,
}


class OpenTopographyAAIGridSource:
    """Real OpenTopography Global DEM client for Android: same public
    contract as dem_source.OpenTopographyDEMSource.fetch(aoi) -> DEM,
    but requests AAIGrid output and decodes it without GDAL/rasterio.
    """

    BASE_URL = "https://portal.opentopography.org/API/globaldem"

    def __init__(self, api_key: str, demtype: str = "SRTMGL1", timeout_s: float = 10.0):
        if not api_key:
            raise ValueError("OpenTopography requires an API key")
        self.api_key = api_key
        self.demtype = demtype
        self.timeout_s = timeout_s

    def _get_with_hard_deadline(self, params: dict):
        """Runs requests.get() on a background thread and gives up after
        self.timeout_s seconds of real wall-clock time, regardless of
        which internal phase (DNS resolution, connect, TLS handshake,
        read) is actually blocking -- see module docstring's HARD-
        DEADLINE FIX note for why requests' own `timeout=` parameter
        alone isn't trustworthy for this. Raises OpenTopographyFetchError
        directly (never lets a raw concurrent.futures.TimeoutError or
        requests exception escape to the caller)."""
        import requests

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(
                requests.get, self.BASE_URL, params=params, timeout=self.timeout_s
            )
            try:
                return future.result(timeout=self.timeout_s)
            except concurrent.futures.TimeoutError:
                raise OpenTopographyFetchError(
                    f"OpenTopography did not respond within {self.timeout_s:.0f}s "
                    "(no network, or an extremely slow/blocked connection). "
                    "Falling back to this device's offline DEM library."
                )
            except requests.exceptions.Timeout:
                raise OpenTopographyFetchError(
                    f"OpenTopography request timed out after {self.timeout_s:.0f}s. "
                    "Check your network connection and try again."
                )
            except requests.exceptions.ConnectionError as e:
                raise OpenTopographyFetchError(
                    f"Could not reach OpenTopography -- network error: {e}"
                )
        finally:
            # Don't block app shutdown waiting on an abandoned, still-
            # hung background thread -- it will be cleaned up by the
            # process eventually; we simply stop waiting on its result.
            executor.shutdown(wait=False)

    def fetch(self, aoi: AreaOfInterest) -> DEM:
        params = {
            "demtype": self.demtype,
            "south": aoi.min_lat,
            "north": aoi.max_lat,
            "west": aoi.min_lon,
            "east": aoi.max_lon,
            "outputFormat": "AAIGrid",
            "API_Key": self.api_key,
        }
        resp = self._get_with_hard_deadline(params)

        if resp.status_code == 401:
            raise OpenTopographyFetchError(
                "OpenTopography rejected the API key (401 Unauthorized). "
                "Check that it was typed correctly."
            )
        if resp.status_code == 429:
            raise OpenTopographyFetchError(
                "OpenTopography rate limit exceeded (429). Free API keys "
                "are limited to a fixed number of requests per 24 hours."
            )
        if resp.status_code != 200:
            snippet = (resp.text or "")[:300] or "(empty response body)"
            raise OpenTopographyFetchError(
                f"OpenTopography returned HTTP {resp.status_code}: {snippet}"
            )

        try:
            grid = parse_ascii_grid(resp.text)
        except AsciiGridParseError as e:
            snippet = (resp.text or "")[:300]
            raise OpenTopographyFetchError(
                f"Could not parse OpenTopography's response as AAIGrid: {e}. "
                f"Response started with: {snippet!r}"
            )

        if np.isnan(grid.values).any():
            raise OpenTopographyFetchError(
                "The returned elevation data contains NODATA cells inside "
                "the requested area (commonly open ocean, or a location "
                "outside this dataset's coverage). This location can't be "
                "investigated with this dataset -- try a different demtype "
                "or a nearby land location."
            )

        n = aoi.grid_size
        if grid.nrows == n and grid.ncols == n:
            elevation = grid.values
            resample_note = "Native raster already matched the requested grid size; no resampling needed."
        else:
            elevation = resample_bilinear(grid.values, n, n)
            resample_note = (
                f"Native raster was {grid.nrows}x{grid.ncols}; resampled to "
                f"{n}x{n} via bilinear interpolation to fit this pipeline's "
                "square-grid convention."
            )

        return DEM(
            aoi=aoi,
            elevation_m=elevation,
            source=f"OpenTopography:{self.demtype}",
            synthetic=False,
            resolution_m=RESOLUTION_BY_DEMTYPE_M.get(self.demtype, grid.cellsize * 111_320),
            acquisition_date=None,
            notes=(
                "Live fetch from OpenTopography Global DEM API, AAIGrid "
                f"format, decoded without GDAL/rasterio. {resample_note}"
            ),
        )