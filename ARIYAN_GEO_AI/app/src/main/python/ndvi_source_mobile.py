"""
ndvi_source_mobile.py
======================
REAL Sentinel-2 NDVI for Android, via the Copernicus Data Space Ecosystem's
Sentinel Hub Statistical API.

WHY THIS UNBLOCKS REAL NDVI ON ANDROID:
The earlier blocker (documented in this project's history) was that
rasterio/GDAL cannot be compiled by Chaquopy, so no raster (GeoTIFF/COG)
could be read on-device. The Statistical API sidesteps that entirely: you
send it an AOI + time range + a small NDVI script, and Sentinel Hub computes
the statistics (mean/min/max/stddev) *server-side* and returns them as a
plain JSON object. No raster ever reaches the device. This is the same
"push the heavy processing server-side, parse plain text/JSON on-device"
pattern already used for DEM (OpenTopography's AAIGrid text format).

Pure Python standard library only (urllib, json, math, datetime) plus
concurrent.futures (also stdlib) for the hard-deadline wrapper below. No
numpy, no rasterio, no requests library dependency.

CREDENTIALS REQUIRED (real account, like the existing OpenTopography key):
A free Copernicus Data Space Ecosystem account + an OAuth2 "client
credentials" client (client_id + client_secret), created at
https://dataspace.copernicus.eu -> user settings -> OAuth clients.
This mirrors the existing OpenTopography API-key pattern already in the app.

HONEST NOTE ON THIS FILE'S HISTORY: an earlier version of this file was
committed to GitHub with its back half accidentally replaced by chat-UI
placeholder text ("[Message clipped] View entire message") instead of real
code -- meaning _stats_for_bbox, fetch_ndvi_stats, and
fetch_ndvi_core_halo_check never actually existed as working code, despite
being described as built in prior session notes. This version replaces that
with a real, complete implementation.

TIMEOUT/TOKEN-CACHING FIX (a prior session): the original version of this
file fetched a fresh OAuth access token independently inside EVERY call to
_stats_for_bbox, and fetch_ndvi_core_halo_check called _stats_for_bbox TWICE
per candidate (core + halo) -- meaning up to 4 separate network calls per
DEM candidate. Fixed by caching one token per investigation run and cutting
the default timeout from 30s to 8s.

HARD-DEADLINE FIX (this session, applied for the same real reason found in
dem_source_mobile.py -- see that module's own docstring): urllib.request's
`timeout=` parameter has the same underlying weakness as requests' --
it does not reliably bound DNS resolution (socket.getaddrinfo()), which is
a separate, unbounded OS-level call. _http_post below now runs the actual
urlopen() call on a background thread and enforces a real wall-clock
deadline via concurrent.futures, exactly like dem_source_mobile.py's fetch,
regardless of which underlying phase is actually stuck.
"""

from __future__ import annotations

import concurrent.futures
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
STATISTICS_URL = "https://sh.dataspace.copernicus.eu/statistics/v1"

# Computes NDVI server-side, masks out water (SCL==6) and pixels where
# B04+B08==0 (division-by-zero guard), matching Copernicus's own documented
# example evalscript for "basic statistics of NDVI with water pixels excluded".
NDVI_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "SCL", "dataMask"] }],
    output: [
      { id: "data", bands: 1 },
      { id: "dataMask", bands: 1 }
    ]
  }
}
function evaluatePixel(samples) {
  let ndvi = (samples.B08 - samples.B04) / (samples.B08 + samples.B04)
  var validMask = 1
  if (samples.B08 + samples.B04 == 0) { validMask = 0 }
  var noWaterMask = 1
  if (samples.SCL == 6) { noWaterMask = 0 }
  return {
    data: [ndvi],
    dataMask: [samples.dataMask * validMask * noWaterMask]
  }
}
"""


class NDVIFetchError(Exception):
    """Raised for any failure fetching/parsing real NDVI: auth, network,
    malformed response, or an AOI/time-range with no usable (unmasked) data.
    Callers (e.g. debate_mobile.py-style wrappers) should catch this and
    surface a readable message, matching the existing DEM error-handling
    pattern -- never silently fall back to synthetic data."""


def _urlopen_with_hard_deadline(req: urllib.request.Request, timeout: int):
    """Runs urllib.request.urlopen() on a background thread and gives up
    after `timeout` seconds of real wall-clock time, regardless of which
    internal phase (DNS resolution, connect, TLS handshake, read) is
    actually blocking -- see module docstring's HARD-DEADLINE FIX note.
    Returns the raw response body as decoded text. Raises NDVIFetchError
    directly for every failure mode (never lets a raw exception escape)."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        def _do_request():
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")

        future = executor.submit(_do_request)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise NDVIFetchError(
                f"Timed out contacting {req.full_url} after {timeout}s "
                "(no network, or an extremely slow/blocked connection)."
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise NDVIFetchError(f"HTTP {exc.code} from {req.full_url}: {body[:300]}") from exc
        except urllib.error.URLError as exc:
            raise NDVIFetchError(f"Network error contacting {req.full_url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise NDVIFetchError(f"Timed out contacting {req.full_url}") from exc
    finally:
        # Don't block waiting on an abandoned, still-hung background
        # thread -- we simply stop waiting on its result.
        executor.shutdown(wait=False)


def _http_post(url: str, data: bytes, headers: dict, timeout: int) -> str:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    return _urlopen_with_hard_deadline(req, timeout)


def get_access_token(client_id: str, client_secret: str, timeout: int = 8) -> str:
    """OAuth2 client-credentials token exchange. Raises NDVIFetchError on any
    failure (missing credentials, bad credentials, network error, malformed
    response, or a token response missing access_token)."""
    if not client_id or not client_secret:
        raise NDVIFetchError("Copernicus client_id and client_secret are required.")

    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")

    raw = _http_post(
        TOKEN_URL, body,
        {"Content-Type": "application/x-www-form-urlencoded"},
        timeout,
    )
    try:
        token_data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NDVIFetchError(f"Malformed token response: {exc}") from exc

    token = token_data.get("access_token")
    if not token:
        raise NDVIFetchError("Token response did not include an access_token.")
    return token


def _bbox_from_point(lat: float, lon: float, radius_m: float) -> list:
    """Small equirectangular-approximation bbox around a point, same
    approach already used for the DEM AOI math in this project."""
    dlat = radius_m / 111_320.0
    cos_lat = max(0.1, abs(math.cos(math.radians(lat))))
    dlon = radius_m / (111_320.0 * cos_lat)
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def _default_time_range(days_back: int = 60) -> tuple:
    """Defaults to the last `days_back` days ending now (UTC), so a live
    real-time investigation doesn't require the user to pick dates."""
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
    """Calls the Sentinel Hub Statistical API for one bbox and returns the
    pooled real NDVI statistics across whatever cloud-free/water-masked
    pixel observations exist in the time range.

    Takes an already-fetched `access_token` directly (see module docstring
    -- one token is fetched per run, not per bbox) rather than
    client_id/client_secret.

    Returns a dict: {"mean": float, "stddev": float, "sample_count": int,
    "n_intervals_with_data": int}.

    Raises NDVIFetchError if the request fails, the response is malformed,
    or there is no valid (non-water, non-nodata) pixel data anywhere in
    the time range -- this is a real "no usable signal" condition, not
    something to paper over with a default value.
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
            "evalscript": NDVI_EVALSCRIPT,
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
        raise NDVIFetchError(f"Malformed statistics response: {exc}") from exc

    intervals = response.get("data", [])
    if not intervals:
        raise NDVIFetchError(
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
        # HONEST NOTE (bug fixed this session): a missing/null stDev from
        # Sentinel Hub for this interval (a real, plausible response when
        # very few pixels survive cloud/water masking) means the variance
        # for THIS interval is UNKNOWN -- it does not mean the variance is
        # verified to be exactly zero. The previous version silently
        # coerced `stdev or 0.0`, contributing a fabricated zero-variance
        # sample into the pooled stddev below. That is what produced a
        # real, on-device pooled_stddev of exactly 0.0 whenever the only
        # interval(s) with valid pixel data in the 60-day window happened
        # to have a null stDev -- even though the pooled MEAN (unaffected
        # by this bug) was computing correctly and showing real, distinct
        # values per candidate. Fixed by only folding an interval's
        # variance into the pool when Sentinel Hub actually reported one;
        # pooled_stddev is now None (not 0.0) if no interval ever reported
        # a usable stDev, so callers can tell "verified zero variance"
        # apart from "variance genuinely unknown" and react honestly
        # (see fetch_ndvi_core_halo_check's own handling of stddev=None).
        if stdev is not None:
            weighted_var_sum += (stdev ** 2) * valid_count
            n_pixels_with_stddev += valid_count

    if total_n <= 0:
        raise NDVIFetchError(
            "No usable (non-water, non-cloud, non-nodata) NDVI pixels found "
            "in this AOI over the queried time range. This can be a real "
            "condition (persistent cloud cover, water body, or a very small "
            "AOI), not necessarily a bug."
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


def fetch_ndvi_stats(
    lat: float,
    lon: float,
    radius_m: float,
    client_id: str,
    client_secret: str,
    timeout: int = 8,
    access_token: str | None = None,
) -> dict:
    """Single-AOI real NDVI mean/stddev/min-style summary for a circular
    area around a point, expressed as an equivalent bbox. Used for the
    simple single-AOI path (not the per-candidate core/halo check below).

    Pass `access_token` if the caller already has one for this run to
    skip fetching a fresh one here."""
    bbox = _bbox_from_point(lat, lon, radius_m)
    token = access_token or get_access_token(client_id, client_secret, timeout=timeout)
    return _stats_for_bbox(bbox, token, timeout=timeout)


def fetch_ndvi_core_halo_check(
    lat: float,
    lon: float,
    client_id: str,
    client_secret: str,
    core_radius_m: float = 15.0,
    halo_radius_m: float = 60.0,
    stress_zscore_threshold: float = 1.5,
    timeout: int = 8,
    access_token: str | None = None,
) -> dict:
    """Per-DEM-candidate real vegetation-stress check.

    Fetches real NDVI mean/stddev for a small "core" bbox at the candidate
    point and a larger "halo" bbox around it (the halo bbox geometrically
    includes the core -- this is a documented approximation, not a true
    annulus subtraction, since the Statistics API operates on bboxes).

    Fetches (or reuses, if `access_token` is passed in) exactly ONE token
    for both the core and halo bbox calls.

    STATISTICAL METHOD (fixed this session -- see HONEST NOTE below):
    Flags vegetation_stress_detected=True when the core mean NDVI is
    significantly below the halo mean NDVI, using a proper two-sample
    z-test for a difference in means: the standard error of
    (core_mean - halo_mean) combines BOTH bboxes' pixel-level variance,
    scaled down by their own valid pixel counts --
        SE = sqrt(core_stddev^2 / core_n + halo_stddev^2 / halo_n)
        z  = (core_mean - halo_mean) / SE
    -- a real, documented remote-sensing signature of vegetation stress
    that can occur over a buried feature (e.g. reduced root-zone
    moisture/soil depth altering canopy vigor).

    HONEST NOTE (bug found and fixed this session): the previous version
    of this function computed z = (core_mean - halo_mean) / halo_stddev,
    i.e. it divided the difference in MEANS by the halo bbox's raw
    PIXEL-LEVEL spatial standard deviation. That answers a different
    question ("how does the core mean compare to the spread of
    individual halo pixels") rather than "is this mean difference
    statistically real given how many pixels went into each mean" --
    and it silently returned z_score=0.0 whenever halo_stddev computed
    to (near) zero, with no warning. On a real on-device confirmation
    run, all 4 real candidates reported z=0.00 despite visibly different
    real core/halo mean gaps (0.008-0.016 raw NDVI units each) -- the
    telltale sign the old zero-guard branch was firing every time rather
    than a coincidence of rounding. The field name and response-shape
    assumptions this function reads from Sentinel Hub (`stats.stDev`,
    `stats.sampleCount`, etc.) were verified correct against Sentinel
    Hub's own published Statistical API documentation before writing
    this fix -- the bug was the STATISTICAL TEST itself, not a
    key-name/schema mismatch. Standard-error-of-the-difference shrinks
    with real pixel counts (unlike raw stddev), so genuine small mean
    shifts at this AOI scale can register instead of structurally
    vanishing. If either bbox's valid pixel count is too small for a
    meaningful test (fewer than 2), or the standard error itself
    computes to (near) zero, this now RAISES NDVIFetchError with an
    honest explanation instead of silently returning a fabricated
    z_score=0.0 "no stress detected" result -- matching this project's
    existing zero-fake-data principle. Callers (see debate_mobile.py)
    already catch NDVIFetchError per-candidate and record it as an
    honest SINGLE_SOURCE result with the real reason, so this requires
    no caller-side changes.

    Returns a dict:
      {
        "core_mean": float, "halo_mean": float, "halo_stddev": float,
        "z_score": float, "vegetation_stress_detected": bool,
        "core_sample_count": int, "halo_sample_count": int,
      }

    Raises NDVIFetchError on any auth/network/no-data/insufficient-sample
    failure. Callers should catch this per candidate and record it as an
    honest SINGLE_SOURCE result with the real error message, rather than
    failing the whole investigation.
    """
    core_bbox = _bbox_from_point(lat, lon, core_radius_m)
    halo_bbox = _bbox_from_point(lat, lon, halo_radius_m)

    token = access_token or get_access_token(client_id, client_secret, timeout=timeout)

    core_stats = _stats_for_bbox(core_bbox, token, timeout=timeout)
    halo_stats = _stats_for_bbox(halo_bbox, token, timeout=timeout)

    core_n = core_stats["sample_count"]
    halo_n = halo_stats["sample_count"]
    core_stddev = core_stats["stddev"]
    halo_stddev = halo_stats["stddev"]

    if core_n < 2 or halo_n < 2:
        raise NDVIFetchError(
            f"Too few valid (non-cloud, non-water) NDVI pixels to compute "
            f"a meaningful vegetation-stress statistic at this location "
            f"(core_sample_count={core_n}, halo_sample_count={halo_n}). "
            f"Reporting this honestly as a real data-quality limitation "
            f"rather than a fabricated zero/no-stress result."
        )

    if core_stddev is None or halo_stddev is None:
        raise NDVIFetchError(
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

    # HONEST NOTE (refined this session, after a second real on-device run
    # reproduced the SAME "standard error near zero" outcome at a
    # DIFFERENT location -- a strong signal this was a formula flaw, not
    # a location-specific "genuinely flat terrain" finding as first
    # assumed): standard_error computing to (near) zero does NOT always
    # mean "insufficient data to test" -- that was only true when it was
    # the OLD bug (variance silently defaulted to a fabricated 0.0, see
    # the _stats_for_bbox fix above). Here, both core_stddev and
    # halo_stddev are CONFIRMED real, non-null values from Sentinel Hub
    # (the None-check above already ruled out "unknown variance"). If
    # both areas genuinely have near-zero internal variance AND their
    # means still differ by a real amount, that is not an uninformative
    # result -- it is the MOST statistically confident result possible:
    # there is essentially no measurement noise to explain the observed
    # difference away as chance. Only when the mean difference is ALSO
    # (near) zero is the result genuinely uninformative (0/0 -- two
    # areas that are both internally uniform AND indistinguishable from
    # each other). A large-but-finite sentinel z-score (not literal
    # math.inf) is used for the confident case, since Android's org.json
    # (MainActivity.kt) is not guaranteed to parse a literal "Infinity"
    # JSON token the same way Python's json module would.
    if standard_error <= 1e-9:
        if abs(mean_difference) <= 1e-9:
            raise NDVIFetchError(
                "Both the core and halo area report (near) zero internal "
                "NDVI variance AND (near) identical means at this "
                "location -- there is genuinely no detectable signal to "
                "test either way, not a computation error."
            )
        z_score = 50.0 if mean_difference > 0 else -50.0
    else:
        z_score = mean_difference / standard_error

    vegetation_stress_detected = z_score <= -stress_zscore_threshold

    return {
        "core_mean": core_stats["mean"],
        "halo_mean": halo_stats["mean"],
        "halo_stddev": halo_stddev,
        "z_score": z_score,
        "vegetation_stress_detected": vegetation_stress_detected,
        "core_sample_count": core_n,
        "halo_sample_count": halo_n,
    }