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

HARD-DEADLINE FIX (a prior session): the original version of this file
passed timeout=30.0 to requests.get() and assumed that bounded the
whole call. On a real device in real airplane mode, the fetch instead
sat for 5+ minutes with zero progress -- root cause was that Python's
requests/urllib3 `timeout` parameter does not reliably bound DNS
resolution. Fixed by wrapping the actual network call in a real,
thread-based hard deadline (concurrent.futures): the call runs on a
background thread, and the calling thread gives up after `timeout_s`
seconds regardless of what that background thread is still doing
underneath.

DIAGNOSTIC-VISIBILITY FIX (this session): a real on-device test showed
the live fetch consistently timing out at exactly the hard deadline
(10s) even while GENUINELY ONLINE, with a valid API key, and with the
IDENTICAL request (same URL, same key, same bbox) succeeding instantly
when made directly from the phone's own browser. This means something
about how Python's requests library behaves on this device for this
call differs from the browser -- but the app previously had NO way to
see what the abandoned background thread was actually doing, because
giving up on future.result(timeout=...) does not stop that thread, and
its eventual outcome (success, or a real exception) was simply
discarded. Fixed by registering a done-callback on the future: whenever
that background thread DOES eventually finish -- even well after we've
already given up and fallen back to offline data -- its real outcome
(success, or the exact exception type and message) is now written to
dem_fetch_diagnostic.json in offline_data_root. This is purely
diagnostic (does not change investigation behavior at all) -- its only
purpose is to let a real failure be inspected after the fact, e.g. by
waiting a bit longer after a run before checking that file, rather than
guessing blindly at network/TLS/IPv6 theories with no evidence.

HONEST LIMITATION, updated: this module's HTTP/parsing/resampling logic
was originally verified only against a hand-built AAIGrid text fixture
and a known-shape resampling test, not a live OpenTopography call. It
has since been exercised on a real physical device in real conditions
(both airplane mode and genuinely online) -- a real SUCCESSFUL live
fetch, from THIS module specifically (as opposed to a browser hitting
the same URL), has still not yet been confirmed. That remains the
honest next on-device milestone.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import time

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


def _write_dem_fetch_diagnostic(offline_data_root: str, outcome: dict) -> None:
    """Best-effort diagnostic write, reporting what an ABANDONED background
    fetch thread actually did once it eventually finishes -- see this
    module's own DIAGNOSTIC-VISIBILITY FIX docstring note. Never raises;
    a failure to write this diagnostic must never affect anything else.
    Overwrites on each call (only the most recent abandoned fetch's
    outcome matters for debugging)."""
    if not offline_data_root:
        return
    try:
        path = os.path.join(offline_data_root, "dem_fetch_diagnostic.json")
        with open(path, "w") as f:
            json.dump(outcome, f)
    except Exception:
        pass


class OpenTopographyAAIGridSource:
    """Real OpenTopography Global DEM client for Android: same public
    contract as dem_source.OpenTopographyDEMSource.fetch(aoi) -> DEM,
    but requests AAIGrid output and decodes it without GDAL/rasterio.
    """

    BASE_URL = "https://portal.opentopography.org/API/globaldem"

    def __init__(
        self, api_key: str, demtype: str = "SRTMGL1", timeout_s: float = 10.0,
        offline_data_root: str = "",
    ):
        if not api_key:
            raise ValueError("OpenTopography requires an API key")
        self.api_key = api_key
        self.demtype = demtype
        self.timeout_s = timeout_s
        self.offline_data_root = offline_data_root

    def _get_with_hard_deadline(self, params: dict):
        """Runs requests.get() on a background thread and gives up after
        self.timeout_s seconds of real wall-clock time, regardless of
        which internal phase (DNS resolution, connect, TLS handshake,
        read) is actually blocking -- see module docstring's HARD-
        DEADLINE FIX note for why requests' own `timeout=` parameter
        alone isn't trustworthy for this. Raises OpenTopographyFetchError
        directly (never lets a raw concurrent.futures.TimeoutError or
        requests exception escape to the caller).

        THIS SESSION'S FIX: on a timeout, registers a done-callback on
        the abandoned future so that IF it eventually completes (success
        or a real exception), that outcome is written to
        dem_fetch_diagnostic.json instead of being silently discarded --
        see module docstring's DIAGNOSTIC-VISIBILITY FIX note."""
        import requests

        submit_time = time.time()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(
                requests.get, self.BASE_URL, params=params, timeout=self.timeout_s
            )
            try:
                return future.result(timeout=self.timeout_s)
            except concurrent.futures.TimeoutError:
                def _report_late_outcome(f):
                    elapsed = time.time() - submit_time
                    try:
                        resp = f.result()
                        _write_dem_fetch_diagnostic(self.offline_data_root, {
                            "outcome": "eventually_succeeded_after_deadline",
                            "elapsed_s": round(elapsed, 1),
                            "status_code": resp.status_code,
                            "response_snippet": (resp.text or "")[:200],
                        })
                    except Exception as inner_exc:
                        _write_dem_fetch_diagnostic(self.offline_data_root, {
                            "outcome": "eventually_failed_after_deadline",
                            "elapsed_s": round(elapsed, 1),
                            "exception_type": type(inner_exc).__name__,
                            "exception_message": str(inner_exc),
                        })

                future.add_done_callback(_report_late_outcome)
                raise OpenTopographyFetchError(
                    f"OpenTopography did not respond within {self.timeout_s:.0f}s "
                    "(no network, or an extremely slow/blocked connection). "
                    "Falling back to this device's offline DEM library. "
                    "(If this keeps happening, check dem_fetch_diagnostic.json "
                    "a little while after this run finishes -- it will record "
                    "what this request was actually doing, if it eventually "
                    "completes.)"
                )
            except requests.exceptions.Timeout:
                raise OpenTopographyFetchError(
                    f"OpenTopography request timed out after {self.