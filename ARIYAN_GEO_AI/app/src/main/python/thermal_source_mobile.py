"""
thermal_source_mobile.py
=========================
REAL Landsat 8/9 thermal (surface temperature) evidence for Android, via
the SAME Copernicus Data Space Ecosystem Sentinel Hub Statistical API
already used for NDVI (see ndvi_source_mobile.py) -- same OAuth account
and endpoint, verified against Copernicus's own documentation
(documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/Landsat8-9.html)
this session, different collection (`landsat-ot-l2`) and band (B10,
requested directly in real Kelvin via SURFACE_TEMPERATURE units, typical
range 250-320K per that documentation).

WHY THIS IS A DIFFERENT, GENUINE EVIDENCE TYPE (not a copy of NDVI):
A buried feature can create a real surface thermal contrast -- different
thermal mass and moisture retention above a void, wall, or disturbed soil
layer than the surrounding undisturbed ground, which shows up as the
surface radiating heat differently at the time of the satellite pass.
This is a physically different mechanism than NDVI's vegetation-vigor
signal, and Sentinel-2 carries no thermal band at all -- only Landsat
8/9's TIRS instrument does, hence this needs its own data source.

COARSER RESOLUTION, HONESTLY NOTED: Landsat 8/9's thermal band is
resampled to 30m (native ~100m) versus Sentinel-2's 10m -- this module's
default core/halo radii are therefore larger than NDVI's, to keep a
comparable number of underlying pixels per bbox. This is a real physical
tradeoff of using a coarser-resolution instrument, not an arbitrary
choice or something papered over.

NO ASSUMED SIGN: unlike NDVI's vegetation-stress check (which
specifically looks for the core being LOWER than the halo), a thermal
anomaly from a buried feature can be WARMER OR COOLER than the
surrounding ground depending on the feature's material, the time of day/
season of the satellite pass, and moisture conditions -- there is no
honest single "expected direction" to assume. This module flags
thermal_anomaly_detected based on the MAGNITUDE of the core/halo
difference (|z| clearing the threshold) in EITHER direction, and reports
which direction was actually observed (core_warmer_than_halo) as a
separate, honestly-labeled fact rather than folding a directional
assumption into the detection itself.

STATISTICAL METHOD: applies the SAME two-layer fix already proven
correct in ndvi_source_mobile.py's fetch_ndvi_core_halo_check() (see
that module's own HONEST NOTE comments for the full real-on-device
debugging history behind this):
  - a missing/null stDev from Sentinel Hub for an interval means
    UNKNOWN variance for that interval, never coerced to a fabricated
    zero;
  - the significance test is a proper two-sample z-test using standard
    error of the difference (not a single side's raw stddev);
  - when standard error is genuinely (near) zero AND the mean
    difference is real (both stddevs confirmed non-null and near-zero),
    that is the MOST confident possible result, not "insufficient
    data" -- a large-but-finite sentinel z-score is used instead of
    either a silent 0.0 or an overly conservative error;
  - only a genuinely uninformative case (near-zero SE AND near-zero
    mean difference -- true 0/0) raises an honest error.
Applying this from the start here avoids repeating the same multi-round
real-on-device bug hunt this session's NDVI fix went through.

SELF-CONTAINED MODULE, matching this project's existing convention for
_mobile.py wrapper files (debate_mobile.py, ndvi_source_mobile.py,
gpr_source_mobile.py are each self-contained): only imports
get_access_token() from ndvi_source_mobile.py (a PUBLIC function --
same OAuth client/credentials are used for both NDVI and thermal, one
token per investigation run, shared across whichever real evidence
checks are requested). The hard-deadline HTTP wrapper is duplicated
locally rather than reaching into ndvi_source_mobile.py's underscore-
prefixed (module-private) helpers.
"""

from __future__ import annotations

import concurrent.futures
import json
import math
import urllib.error
import urllib.parse
import urllib.request

from ndvi_source_mobile import get_access_token

STATISTICS_URL = "https://sh.dataspace.copernicus.eu/statistics/v1"

# Requests Landsat 8/9's thermal band directly in real Kelvin
# (SURFACE_TEMPERATURE units -- verified against Copernicus's own
# Landsat 8-9 Level 2 documentation this session), masked to valid
# pixels only via dataMask.
THERMAL_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B10", "dataMask"], units: "SURFACE_TEMPERATURE" }],
    output: [
      { id: "data", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  }
}
function evaluatePixel(samples) {
  return {
    data: [samples.B10],
    dataMask: [samples.dataMask]
  }
}
"""


class ThermalFetchError(Exception):
    """Raised for any failure fetching/parsing real Landsat thermal data:
    auth, network, malformed response, or an AOI/time-range with no
    usable (unmasked) data. Callers should catch this and surface a
    readable message -- never silently fall back to synthetic data."""


def _urlopen_with_hard_deadline(req: urllib.request.Request, timeout: int) -> str:
    """Runs urllib.request.urlopen() on a background thread and gives up
    after `timeout` seconds of real wall-clock time, regardless of which
    internal phase (DNS resolution, connect, TLS handshake, read) is
    actually blocking -- same real reason and same pattern as
    dem_source_mobile.py / ndvi_source_mobile.py's own hard-deadline
    wrappers (urllib's own `timeout=` does not reliably bound DNS
    resolution). Duplicated locally rather than imported, per this
    module's self-containment note above."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        def _do_request():
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")

        future = executor.submit(_do_request)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise ThermalFetchError(
                f"Timed out contacting {req.full_url} after {timeout}s "
                "(no network, or an extremely slow/blocked connection)."
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ThermalFetchError(f"HTTP {exc.code} from {req.full_url}: {body[:300]}") from exc
        except urllib.error.URLError as exc:
            raise ThermalFetchError(f"Network error contacting {req.full_url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ThermalFetchError(f"Timed out contacting {req.full_url}") from exc
    finally:
        executor.shutdown(wait=False)


def _bbox_from_point(lat: float, lon: float, radius_m: float) -> list:
    """Same equirectangular-approximation bbox math already used for
    DEM/NDVI AOIs in this project. Duplicated locally per this module's
    self-containment note above."""
    dlat = radius_m / 111_320.0
    cos_lat = max(0.1, abs(math.cos(math.radians(lat))))
    dlon = radius_m / (111_320.0 * cos_lat)
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def _default_time_range(days_back: int = 60):
    """Same default window as ndvi_source_mobile.py -- the last
    `days_back` days ending now (UTC). Landsat's combined 8+16 day
    revisit means a 60-day window typically covers 4-7 real passes."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days_back)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(fmt), now.strftime(fmt)


def _stats_for_bbox_thermal(
    bbox: list,
    access_token: str,
    time_from: str | None = None,
    time_to: str | None = None,
    timeout: int = 8,
) -> dict:
    """Calls the Sentinel Hub Statistical API for one bbox against the
    real Landsat 8/9 Level 2 collection and returns pooled real surface-
    temperature statistics (Kelvin) across whatever cloud-free pixel
    observations exist in the time range.

    Mirrors ndvi_source_mobile.py's _stats_for_bbox() exactly, including
    its fix: a missing/null stDev for an interval means UNKNOWN variance
    for that interval, never coerced to a fabricated zero (see that
    function's own HONEST NOTE for the full history of why this matters).

    Returns {"mean": float (Kelvin), "stddev": float | None,
    "sample_count": int, "n_intervals_with_data": int}.

    Raises ThermalFetchError on any failure, or if no valid pixel data
    exists anywhere in the time range -- this can be a real condition
    (persistent cloud cover, or Landsat's own longer revisit genuinely
    not passing over a small AOI within the window), not necessarily a bug.
    """
    if time_from is None or time_to is None:
        time_from, time_to = _default_time_range()

    request_body = {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {
                    "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
                },
            },
            "data": [{
                "type": "landsat-ot-l2",
                "dataFilter": {
                    "timeRange": {"from": time_from, "to": time_to},
                    "maxCloudCoverage": 40,
                },
            }],
        },
        "aggregation": {
            "timeRange": {"from": time_from, "to": time_to},
            "aggregationInterval": {"of": "P30D"},
            "evalscript": THERMAL_EVALSCRIPT,
            "resx": 30,
            "resy": 30,
        },
    }

    req = urllib.request.Request(
        STATISTICS_URL,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    raw = _urlopen_with_hard_deadline(req, timeout)

    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ThermalFetchError(f"Malformed statistics response: {exc}") from exc

    intervals = response.get("data", [])
    if not intervals:
        raise ThermalFetchError(
            "Statistics API returned no time intervals for this AOI/time range."
        )

    total_n = 0
    weighted_mean_sum = 0.0
    weighted_var_sum = 0.0
    n_pixels_with_stddev = 0
    n_intervals_with_data = 0

    for interval in intervals:
        outputs = interval.get("outputs", {})
        data_output = outputs.get("data", {})
        bands = data_output.get("bands", {})
        band0 = bands.get("B0", {})
        stats = band0.get("stats", {})

        sample_count = stats.get("sampleCount", 0) or 0
        nodata_count = stats.get("noDataCount", 0) or 0
        valid_count = sample_count - nodata_count
        mean = stats.get("mean")
        stdev = stats.get("stDev")

        if valid_count <= 0 or mean is None:
            continue

        n_intervals_with_data += 1
        total_n += valid_count
        weighted_mean_sum += mean * valid_count
        if stdev is not None:
            weighted_var_sum += (stdev ** 2) * valid_count
            n_pixels_with_stddev += valid_count

    if total_n <= 0:
        raise ThermalFetchError(
            "No usable (non-cloud, non-nodata) Landsat thermal pixels "
            "found in this AOI over the queried time range. This can be "
            "a real condition (persistent cloud cover, or Landsat's own "
            "longer revisit genuinely not passing over this AOI in the "
            "window), not necessarily a bug."
        )

    pooled_mean = weighted_mean_sum / total_n
    pooled_stddev = (
        math.sqrt(weighted_var_sum / n_pixels_with_stddev)
        if n_pixels_with_stddev > 0
        else None
    )

    return {
        "mean": pooled_mean,
        "stddev": pooled_stddev,
        "sample_count": total_n,
        "n_intervals_with_data": n_intervals_with_data,
    }


def fetch_thermal_core_halo_check(
    lat: float,
    lon: float,
    client_id: str,
    client_secret: str,
    core_radius_m: float = 45.0,
    halo_radius_m: float = 180.0,
    anomaly_zscore_threshold: float = 1.5,
    timeout: int = 8,
    access_token: str | None = None,
) -> dict:
    """Per-DEM-candidate real thermal-anomaly check, using Landsat 8/9's
    real surface-temperature band.

    core_radius_m/halo_radius_m default LARGER than NDVI's (15m/60m):
    Landsat's thermal band is 30m resolution (resampled from ~100m
    native), so NDVI's tighter radii would often contain 0-1 real
    pixels here; 45m/180m keeps a comparable pixel count per bbox to
    what NDVI gets at Sentinel-2's 10m resolution -- a genuine physical
    tradeoff of using a coarser-resolution real instrument, not an
    arbitrary choice.

    Uses the SAME proper two-sample z-test as ndvi_source_mobile.py's
    fetch_ndvi_core_halo_check() (standard error of the difference, a
    large-but-finite sentinel z-score for the near-zero-variance-but-
    real-difference case, and a genuine error only for the truly
    uninformative 0/0 case) -- see that function's own docstring for
    the full reasoning behind this; this module applies the fix from
    the outset rather than repeating the bug.

    UNLIKE NDVI, this does NOT assume a direction (see module docstring
    NO ASSUMED SIGN note): thermal_anomaly_detected is True whenever
    |z| clears the threshold in EITHER direction; core_warmer_than_halo
    reports which direction was actually observed as a separate, honest
    fact.

    Returns a dict:
      {
        "core_mean_kelvin": float, "halo_mean_kelvin": float,
        "halo_stddev": float, "z_score": float,
        "thermal_anomaly_detected": bool, "core_warmer_than_halo": bool,
        "core_sample_count": int, "halo_sample_count": int,
      }

    Raises ThermalFetchError on any auth/network/no-data/insufficient-
    sample/genuinely-uninformative failure. Callers should catch this
    per candidate and record it as an honest limitation, rather than
    failing the whole investigation -- same pattern as NDVI.
    """
    core_bbox = _bbox_from_point(lat, lon, core_radius_m)
    halo_bbox = _bbox_from_point(lat, lon, halo_radius_m)

    token = access_token or get_access_token(client_id, client_secret, timeout=timeout)

    core_stats = _stats_for_bbox_thermal(core_bbox, token, timeout=timeout)
    halo_stats = _stats_for_bbox_thermal(halo_bbox, token, timeout=timeout)

    core_n = core_stats["sample_count"]
    halo_n = halo_stats["sample_count"]
    core_stddev = core_stats["stddev"]
    halo_stddev = halo_stats["stddev"]

    if core_n < 2 or halo_n < 2:
        raise ThermalFetchError(
            f"Too few valid (non-cloud) Landsat thermal pixels to compute "
            f"a meaningful anomaly statistic at this location "
            f"(core_sample_count={core_n}, halo_sample_count={halo_n}). "
            f"Reporting this honestly as a real data-quality limitation."
        )

    if core_stddev is None or halo_stddev is None:
        raise ThermalFetchError(
            "Sentinel Hub did not report a usable standard deviation for "
            "the core and/or halo area over this time window -- a "
            "significance test cannot be computed honestly without it. "
            "Reporting this as a real data-quality limitation rather "
            "than assuming zero variance."
        )

    mean_difference = core_stats["mean"] - halo_stats["mean"]
    standard_error = math.sqrt(
        (core_stddev ** 2) / core_n
        + (halo_stddev ** 2) / halo_n
    )

    if standard_error <= 1e-9:
        if abs(mean_difference) <= 1e-9:
            raise ThermalFetchError(
                "Both the core and halo area report (near) zero internal "
                "thermal variance AND (near) identical mean surface "
                "temperature at this location -- there is genuinely no "
                "detectable signal to test either way, not a computation "
                "error."
            )
        z_score = 50.0 if mean_difference > 0 else -50.0
    else:
        z_score = mean_difference / standard_error

    thermal_anomaly_detected = abs(z_score) >= anomaly_zscore_threshold
    core_warmer_than_halo = mean_difference > 0

    return {
        "core_mean_kelvin": core_stats["mean"],
        "halo_mean_kelvin": halo_stats["mean"],
        "halo_stddev": halo_stddev,
        "z_score": z_score,
        "thermal_anomaly_detected": thermal_anomaly_detected,
        "core_warmer_than_halo": core_warmer_than_halo,
        "core_sample_count": core_n,
        "halo_sample_count": halo_n,
    }