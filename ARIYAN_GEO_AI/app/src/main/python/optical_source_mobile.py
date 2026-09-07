"""
optical_source_mobile.py
=========================
REAL Sentinel-2 optical (visible-band) brightness for Android, via the same
Copernicus Data Space Ecosystem Sentinel Hub Statistical API used by
ndvi_source_mobile.py and thermal_source_mobile.py -- same account, same
"push the computation server-side, parse plain JSON on-device" pattern, no
raster ever reaches the device.

WHAT THIS CHECKS AND WHY IT IS A GENUINELY DIFFERENT SIGNAL FROM NDVI:
NDVI measures vegetation VIGOR (a live-plant signal). This module measures
broadband VISIBLE REFLECTANCE -- how bright or dark the ground looks in
ordinary red/green/blue light, averaged across bands B04 (red), B03
(green), B02 (blue). This is the real remote-sensing signature aerial
archaeologists call a "soilmark": backfilled ditches, robbed-out wall
foundations, and other disturbed ground often show as an anomalously
bright or dark patch in bare-earth imagery for reasons that have nothing
to do with plant health -- disturbed/looser subsoil retains moisture
differently than undisturbed ground (darker when damp), or contains
different material entirely (chalk/limestone rubble reads brighter;
organic-rich pit/ditch fill reads darker). This is the same "core vs
halo" per-DEM-candidate architecture as NDVI and Thermal, but a
physically distinct phenomenon -- not a repackaging of the vegetation
signal, and not double-counting a single canopy measurement as two
independent sources (see debate_mobile.py's HONEST MAPPING NOTES on
why has_optical was deliberately kept False until this file existed).

MASKING DESIGN DECISION (documented here so it's not silently assumed):
this evalscript masks out water (SCL==6) via the exact same approach as
ndvi_source_mobile.py's NDVI_EVALSCRIPT, and relies on the same
maxCloudCoverage=40 scene-level filter -- it does NOT additionally
restrict to bare-soil-classified pixels (SCL==5). A stricter bare-soil
mask would be a MORE physically pure soil-tone signal, but it is a new,
untested heuristic that could leave zero valid pixels over any
vegetated ground (making the check frequently inconclusive) and departs
from this project's two other core/halo checks' exact masking pattern.
Kept consistent with the proven NDVI/Thermal masking instead. HONEST
LIMITATION (also stated in this file's public docstrings and propagated
into investigation_multi_mobile.py's limitations text): on vegetated
ground, this measures CANOPY brightness, not soil tone -- interpret
accordingly. A bare-soil-only mask (SCL==5) is a real, deferred future
refinement, not something silently built in.

DIRECTION CONVENTION: unlike NDVI (which is inherently one-directional --
lower core NDVI than halo means vegetation stress), a soilmark can be
EITHER brighter or darker than its surroundings depending on the fill
material, exactly like Thermal's convention (see thermal_source_mobile.py).
This flags on |z| clearing the threshold in EITHER direction, and reports
the direction (brighter/darker) as a separate honest fact rather than
assuming one.

RESOLUTION / CORE-HALO RADII: B02/B03/B04 are native 10m Sentinel-2 bands
-- the SAME resolution as NDVI's B04/B08 bands. This module therefore
reuses NDVI's exact default core/halo radii (15m/60m), unlike Thermal
(which used larger radii to compensate for Landsat's coarser ~30m/100m
thermal-band resolution) -- there is no physical justification for
enlarging them here.

STATISTICAL METHOD: identical two-sample z-test for a difference in
means as NDVI (post-fix) and Thermal, applying both fixes' lessons from
the start (this file was written after both, not before):
  SE = sqrt(core_stddev^2 / core_n + halo_stddev^2 / halo_n)
  z  = (core_mean - halo_mean) / SE
A missing/null stDev for an interval is treated as UNKNOWN variance, not
verified-zero (see _stats_for_bbox below, following the same pooling
logic as ndvi_source_mobile.py's now-fixed version). A near-zero standard
error with a real, non-null, confirmed-small variance AND a real nonzero
mean difference is the most statistically confident possible result
(sentinel z=+/-50.0, matching Thermal's convention) -- only genuine 0/0
(near-zero SE AND near-zero mean difference) raises an honest "no
detectable signal" error. Too few valid pixels, or an unknown (null)
stddev on either side, also raises honestly rather than fabricating a
result.

SELF-CONTAINED PER THIS PROJECT'S CONVENTION (matching thermal_source_mobile.py
exactly): this module imports ONLY `get_access_token` and `NDVIFetchError`
from ndvi_source_mobile.py -- `get_access_token` because it's the shared
public OAuth entry point (same Copernicus account as NDVI/Thermal), and
`NDVIFetchError` ONLY so this module can catch the specific exception
`get_access_token` raises and translate it into this module's own
`OpticalFetchError` at that one call site. Nothing else is imported or
reused -- the hard-wall-clock-deadline HTTP wrapper below
(`_urlopen_with_hard_deadline`) is this module's OWN self-contained copy
of the same pattern used in ndvi_source_mobile.py and dem_source_mobile.py,
not a shared/imported helper, exactly matching thermal_source_mobile.py's
own convention of each evidence-source module owning its complete
network-handling code rather than reaching into another module's private
helpers.
"""

from __future__ import annotations

import concurrent.futures
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from ndvi_source_mobile import get_access_token, NDVIFetchError

STATISTICS_URL = "https://sh.dataspace.copernicus.eu/statistics/v1"

# Computes broadband visible brightness server-side: the mean of the three
# visible reflectance bands (B04 red, B03 green, B02 blue), masking out
# water (SCL==6) -- the exact same masking approach as
# ndvi_source_mobile.py's NDVI_EVALSCRIPT (see this module's own docstring,
# MASKING DESIGN DECISION, for why no additional bare-soil-only mask is
# applied). Reflectance values are 0-1 floats (not the UINT8 0-255 used by
# the true-color visualization example in Sentinel Hub's own
# documentation) -- keeping the statistics on the same natural scale the
# Statistical API already reports for other float-valued bands, consistent
# with how NDVI_EVALSCRIPT is written.
OPTICAL_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B02", "B03", "B04", "SCL", "dataMask"] }],
    output: [
      { id: "data", bands: 1 },
      { id: "dataMask", bands: 1 }
    ]
  }
}
function evaluatePixel(samples) {
  let brightness = (samples.B02 + samples.B03 + samples.B04) / 3.0
  var noWaterMask = 1
  if (samples.SCL == 6) { noWaterMask = 0 }
  return {
    data: [brightness],
    dataMask: [samples.dataMask * noWaterMask]
  }
}
"""


class OpticalFetchError(Exception):
    """Raised for any failure fetching/parsing real optical brightness:
    auth, network, malformed response, or an AOI/time-range with no
    usable (unmasked) data. Mirrors NDVIFetchError/ThermalFetchError's
    role exactly -- callers (debate_mobile.py-style wrappers) should
    catch this per-candidate and record an honest failure, never
    silently fall back to synthetic data."""


def _urlopen_with_hard_deadline(req: urllib.request.Request, timeout: int) -> str:
    """This module's own self-contained hard-wall-clock-deadline wrapper
    -- see module docstring, SELF-CONTAINED PER THIS PROJECT'S CONVENTION,
    for why this is a local copy of the same pattern used elsewhere in
    this project (dem_source_mobile.py, ndvi_source_mobile.py) rather than
    a shared import. Runs urlopen() on a background thread and gives up
    after `timeout` seconds of real wall-clock time regardless of which
    internal phase (DNS resolution, connect, TLS handshake, read) is
    actually blocking. Raises OpticalFetchError directly for every
    failure mode."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        def _do_request():
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")

        future = executor.submit(_do_request)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise OpticalFetchError(
                f"Timed out contacting {req.full_url} after {timeout}s "
                "(no network, or an extremely slow/blocked connection)."
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OpticalFetchError(f"HTTP {exc.code} from {req.full_url}: {body[:300]}") from exc
        except urllib.error.URLError as exc:
            raise OpticalFetchError(f"Network error contacting {req.full_url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise OpticalFetchError(f"Timed out contacting {req.full_url}") from exc
    finally:
        # Don't block waiting on an abandoned, still-hung background
        # thread -- we simply stop waiting on its result.
        executor.shutdown(wait=False)


def _http_post(url: str, data: bytes, headers: dict, timeout: int) -> str:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    return _urlopen_with_hard_deadline(req, timeout)


def _bbox_from_point(lat: float, lon: float, radius_m: float) -> list:
    """Identical equirectangular-approximation bbox math to
    ndvi_source_mobile.py's own _bbox_from_point -- duplicated (not
    imported) since it's a tiny, self-contained pure-math helper with no
    network/auth dependency, matching this project's existing convention
    (see thermal_source_mobile.py, which does the same)."""
    dlat = radius_m / 111_320.0
    cos_lat = max(0.1, abs(math.cos(math.radians(lat))))
    dlon = radius_m / (111_320.0 * cos_lat)
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def _default_time_range(days_back: int = 60) -> tuple:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days_back)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(fmt), now.strftime(fmt)


def _stats_for_bbox(
    bbox: list,
    access_token: str,
    time_from: str | None = None,
    time_to: str | None = None,
    timeout: int = 8,
) -> dict:
    """Calls the Sentinel Hub Statistical API for one bbox and returns
    pooled real optical-brightness statistics across whatever
    cloud-free/water-masked pixel observations exist in the time range.

    Structurally identical to ndvi_source_mobile.py's own (already fixed)
    _stats_for_bbox -- same pooling logic, same honest null-stddev
    handling (a missing stDev for an interval means UNKNOWN variance for
    that interval, never coerced to a fabricated 0.0) -- written this way
    from the start since this file is new code with no prior buggy
    version to fix, applying that fix's lesson directly rather than
    repeating the mistake.

    Returns {"mean": float, "stddev": float | None, "sample_count": int,
    "n_intervals_with_data": int}.

    Raises OpticalFetchError on request failure, malformed response, or
    genuinely no valid pixel data anywhere in the time range.
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
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {"from": time_from, "to": time_to},
                    "maxCloudCoverage": 40,
                },
            }],
        },
        "aggregation": {
            "timeRange": {"from": time_from, "to": time_to},
            "aggregationInterval": {"of": "P30D"},
            "evalscript": OPTICAL_EVALSCRIPT,
            "resx": 10,
            "resy": 10,
        },
    }

    raw = _http_post(
        STATISTICS_URL,
        json.dumps(request_body).encode("utf-8"),
        {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        timeout,
    )
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OpticalFetchError(f"Malformed statistics response: {exc}") from exc

    intervals = response.get("data", [])
    if not intervals:
        raise OpticalFetchError(
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
        # Honest: a missing/null stDev for THIS interval means UNKNOWN
        # variance for that interval, never coerced to a fabricated 0.0
        # -- see this function's own docstring and
        # ndvi_source_mobile.py's HONEST NOTE for the real on-device bug
        # this exact pattern was written to avoid repeating.
        if stdev is not None:
            weighted_var_sum += (stdev ** 2) * valid_count
            n_pixels_with_stddev += valid_count

    if total_n <= 0:
        raise OpticalFetchError(
            "No usable (non-water, non-cloud, non-nodata) optical pixels "
            "found in this AOI over the queried time range. This can be a "
            "real condition (persistent cloud cover or a water body), not "
            "necessarily a bug."
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


def fetch_optical_core_halo_check(
    lat: float,
    lon: float,
    client_id: str,
    client_secret: str,
    core_radius_m: float = 15.0,
    halo_radius_m: float = 60.0,
    anomaly_zscore_threshold: float = 1.5,
    timeout: int = 8,
    access_token: str | None = None,
) -> dict:
    """Per-DEM-candidate real optical-brightness (soilmark) check.

    Fetches real broadband visible-reflectance mean/stddev for a small
    "core" bbox at the candidate point and a larger "halo" bbox around it
    (halo geometrically includes the core -- same documented
    approximation as NDVI/Thermal, not a true annulus, since the
    Statistics API operates on bboxes).

    Uses the SAME Copernicus OAuth account as NDVI and Thermal -- pass an
    already-fetched `access_token` (shared across all three checks for a
    run) to skip fetching a fresh one here, exactly like Thermal's
    convention.

    Returns:
      {
        "core_mean": float, "halo_mean": float, "halo_stddev": float,
        "z_score": float, "optical_anomaly_detected": bool,
        "core_brighter_than_halo": bool,
        "core_sample_count": int, "halo_sample_count": int,
      }

    Raises OpticalFetchError on any auth/network/no-data/insufficient-
    sample/genuinely-uninformative-result failure -- see this module's
    own docstring, STATISTICAL METHOD, for exactly which conditions
    raise vs. which produce a sentinel z-score. Callers should catch this
    per candidate and record an honest SINGLE_SOURCE-style result with
    the real error message, exactly like NDVI and Thermal, rather than
    failing the whole investigation.
    """
    core_bbox = _bbox_from_point(lat, lon, core_radius_m)
    halo_bbox = _bbox_from_point(lat, lon, halo_radius_m)

    try:
        token = access_token or get_access_token(client_id, client_secret, timeout=timeout)
    except NDVIFetchError as exc:
        raise OpticalFetchError(str(exc)) from exc

    core_stats = _stats_for_bbox(core_bbox, token, timeout=timeout)
    halo_stats = _stats_for_bbox(halo_bbox, token, timeout=timeout)

    core_n = core_stats["sample_count"]
    halo_n = halo_stats["sample_count"]
    core_stddev = core_stats["stddev"]
    halo_stddev = halo_stats["stddev"]

    if core_n < 2 or halo_n < 2:
        raise OpticalFetchError(
            f"Too few valid (non-cloud, non-water) optical pixels to "
            f"compute a meaningful brightness-anomaly statistic at this "
            f"location (core_sample_count={core_n}, "
            f"halo_sample_count={halo_n}). Reporting this honestly as a "
            f"real data-quality limitation rather than a fabricated "
            f"zero/no-anomaly result."
        )

    if core_stddev is None or halo_stddev is None:
        raise OpticalFetchError(
            "Sentinel Hub did not report a usable standard deviation for "
            "the core and/or halo area over this time window (this "
            "commonly happens when very few pixel observations survived "
            "cloud/water masking) -- a significance test cannot be "
            "computed honestly without it. Reporting this as a real "
            "data-quality limitation rather than assuming zero variance."
        )

    mean_difference = core_stats["mean"] - halo_stats["mean"]
    standard_error = math.sqrt(
        (core_stddev ** 2) / core_n
        + (halo_stddev ** 2) / halo_n
    )

    # Same reasoning as thermal_source_mobile.py and the fixed
    # ndvi_source_mobile.py: a near-zero standard error with CONFIRMED
    # real (non-null) variance and a real nonzero mean difference is the
    # most statistically confident result possible, not insufficient
    # data -- only genuine 0/0 (near-zero SE AND near-zero mean
    # difference) is truly uninformative. Sentinel z=+/-50.0 (not a
    # literal math.inf, for the same Android org.json-parsing reason
    # documented in ndvi_source_mobile.py).
    if standard_error <= 1e-9:
        if abs(mean_difference) <= 1e-9:
            raise OpticalFetchError(
                "Both the core and halo area report (near) zero internal "
                "optical-brightness variance AND (near) identical means "
                "at this location -- there is genuinely no detectable "
                "signal to test either way, not a computation error."
            )
        z_score = 50.0 if mean_difference > 0 else -50.0
    else:
        z_score = mean_difference / standard_error

    optical_anomaly_detected = abs(z_score) >= anomaly_zscore_threshold

    return {
        "core_mean": core_stats["mean"],
        "halo_mean": halo_stats["mean"],
        "halo_stddev": halo_stddev,
        "z_score": z_score,
        "optical_anomaly_detected": optical_anomaly_detected,
        "core_brighter_than_halo": mean_difference > 0,
        "core_sample_count": core_n,
        "halo_sample_count": halo_n,
    }
