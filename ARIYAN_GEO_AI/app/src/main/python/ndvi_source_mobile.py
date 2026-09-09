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

QUERY-WINDOW WIDENED 60 -> 90 DAYS (a prior session -- REAL on-device
confidence issue, not a guess): a real investigation run showed both the
core and halo bbox for a candidate returning exactly 2 valid pixels each
after cloud/water masking over the default 60-day window -- the statistical
floor this module's own core/halo check requires before it will even
attempt a significance test (see fetch_ndvi_core_halo_check's own
core_n < 2 / halo_n < 2 check below). At n=2, "near-zero variance" is not a
meaningful statistical statement -- two quantized Sentinel-2 reflectance
values can trivially agree by chance -- yet the code correctly (per its own
documented logic) treats a confirmed near-zero variance plus a real mean
difference as the MOST confident possible case, producing a sentinel
z=+/-50.0 that reads identically to one backed by a genuinely large,
well-sampled pixel count (see this module's own SAMPLE-COUNT VISIBILITY FIX
note, referenced from investigation_multi_mobile.py, which is what made
this n=2 case visible in the first place). Widened the default window to
90 days to give more chances at a cloud-free/water-clear Sentinel-2 pass
(roughly 5-day revisit at mid-latitudes) without crossing far enough in
time to risk pooling a genuinely different seasonal vegetation state into
one "core"/"halo" mean -- a real, deliberate tradeoff, not a free win: NDVI
is seasonally variable, so an arbitrarily wide window would average across
genuinely different ground states rather than just gathering more real
spatial samples of the same one. 90 days was chosen as a moderate step
(1.5x, not a jump to 180 or 365) for this reason. This is a single,
self-contained default-value change -- no caller anywhere in this project
passes time_from/time_to explicitly to fetch_ndvi_core_halo_check or
fetch_ndvi_stats, so every call site inherits this new default uniformly.

CORE/HALO SHARED-TIME-WINDOW FIX (a prior session): fetch_ndvi_core_halo_check
previously called _stats_for_bbox() for the core and halo bboxes without
passing time_from/time_to, meaning each call independently invoked
_default_time_range() -- which reads datetime.now(timezone.utc)
separately each time. In practice this meant the core and halo windows
could differ by however many milliseconds elapsed between the two calls
(not a real-world problem at that scale), but it was never actually
guaranteed the two bboxes were queried over the IDENTICAL time range, which
is what a valid two-sample comparison requires. Fixed by computing
(time_from, time_to) ONCE in fetch_ndvi_core_halo_check and passing the
same values explicitly to both _stats_for_bbox() calls.

TEMPORAL PERSISTENCE CHECK, ADDED THIS SESSION -- ESTABLISHES THE PATTERN
FOR QUEUE ITEM 2 (Thermal/Optical mirrors, evidence_record.py's 8th slot,
and investigation_multi_mobile.py wiring are NOT part of this change --
see this project's own notes for the rest of the plan; this is
deliberately scoped to NDVI only, to prove the approach before repeating
it three more times):

WHAT THIS CHECKS AND WHY IT'S CHEAPER THAN IT SOUNDS: the existing
snapshot check (fetch_ndvi_core_halo_check above) answers "is there a
vegetation-stress signal right now" from ONE pooled measurement across
however many 30-day intervals the query window happens to span. A single
snapshot can't distinguish a persistent signal (present across many
independent real satellite passes -- stronger evidence) from a one-off
spike (a transient cloud-shadow/irrigation/recent-tillage artifact caught
in a single pass -- weaker evidence). Verified via web search against
Sentinel Hub's own official documentation and a real published usage
example (NOT guessed, matching this project's established discipline
after the Thermal Level-1/Level-2 HTTP-500 lesson): the Statistical API's
response already contains one entry per aggregationInterval (P30D) bucket
under response["data"], each with a top-level "interval": {"from", "to"}
key (a sibling of "outputs", which the existing pooled functions above
already read) -- meaning persistence needs NO new API calls beyond what
the snapshot check already makes (same 2 HTTP calls per candidate: core +
halo). The only change is widening the window (so more than one interval
genuinely exists to compare) and NOT collapsing those intervals into one
pooled mean before computing statistics.

WINDOW CHOICE, DELIBERATELY SEPARATE FROM THE SNAPSHOT CHECK'S 90-DAY
DEFAULT: this check needs multiple real intervals to be meaningful at
all, so it uses its own default (180 days, ~6 real P30D buckets) rather
than reusing _default_time_range()'s now-90-day default -- 90 days would
often yield only 2-3 buckets, too few for a persistence judgment to mean
much. This is a SEPARATE, explicit parameter on the new function below,
not a change to _default_time_range() itself -- the snapshot check's own
90-day default and its own seasonal-mixing tradeoff reasoning (see
QUERY-WINDOW WIDENED note above) are completely untouched by this
addition.

DATE-MATCHING, NOT POSITIONAL MATCHING: core and halo are two SEPARATE
API calls: cloud cover, and therefore which specific dates have usable
pixels, can differ between the two bboxes (a small cloud shadow might
clip the core bbox on a date the halo bbox is unaffected, or vice versa)
-- so core and halo could plausibly return a DIFFERENT NUMBER of
intervals-with-data, or the same number in a different order. Matching
by list position would silently misalign the wrong core interval against
the wrong halo interval. Fixed by matching on the exact "from"/"to"
interval boundary strings instead -- both the core and halo requests use
the identical time_from/time_to window and identical P30D grid (mirroring
the CORE/HALO SHARED-TIME-WINDOW FIX applied to the snapshot check above),
so the interval BOUNDARIES themselves are guaranteed identical between
the two requests even when which of those intervals actually has data
differs.

HONEST "UNTESTED, NEVER ASSUMED UNSTABLE" PHILOSOPHY -- DELIBERATELY
DIFFERENT ERROR HANDLING FROM THE SNAPSHOT CHECK: fetch_ndvi_core_halo_check
above correctly RAISES NDVIFetchError when too few pixels exist for a
meaningful test (see that function's own docstring) -- for a SINGLE
snapshot, "too little data" really is a hard failure of that one
measurement. For persistence, a real location may genuinely have only 1
or 2 real cloud-free intervals in the entire window (persistent regional
cloud cover, e.g.) -- that is not a fetch failure, it is honest
information about how much persistence evidence actually exists (mirrors
investigation_multi_mobile.py's own StabilityResult "untested, never
assumed unstable" philosophy exactly, applied here to a different kind of
robustness question). fetch_ndvi_temporal_persistence_check() below
therefore only raises NDVIFetchError for TRUE hard failures (token
error, network error, malformed response, or literally zero data on
EITHER bbox across the entire window) -- a thin-but-nonzero number of
testable intervals is returned as a normal, low-but-honest
persistence_score, never an exception.

NDVI'S OWN DIRECTION RULE, UNCHANGED, APPLIED PER-INTERVAL: exactly like
the snapshot check, only core-mean-BELOW-halo-mean counts as vegetation
stress "detected" for a given interval (z <= -stress_zscore_threshold) --
NDVI's stress signature is inherently one-directional, unlike Thermal's/
Optical's two-directional checks (see their own modules' own docstrings).
This is unchanged from the snapshot check; only WHICH data feeds the same
per-interval z-test differs (per-interval instead of pooled-across-
interval).

NOT YET WIRED INTO THE APP: this function exists and is sandbox-tested
against realistic synthetic Sentinel Hub response shapes (see this
session's verification), but is NOT YET called from
investigation_multi_mobile.py, has no evidence_record.py slot yet, and is
NOT yet mirrored to thermal_source_mobile.py/optical_source_mobile.py --
all deliberately deferred to a following session, per this project's own
plan for this queue item. Calling this function today would work
correctly in isolation but produce a result nothing in the app yet reads
or displays.
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


def _default_time_range(days_back: int = 90) -> tuple:
    """Defaults to the last `days_back` days ending now (UTC), so a live
    real-time investigation doesn't require the user to pick dates.

    WIDENED 60 -> 90 THIS SESSION -- see module docstring, QUERY-WINDOW
    WIDENED note, for the full real on-device reasoning (a confirmed n=2
    pixel sample was reaching this module's own sentinel-z=50.0
    "maximally confident" path, which is only actually warranted for a
    robust sample). 90 days is a deliberate moderate widening -- enough
    extra Sentinel-2 revisit opportunities (~5-day cadence at
    mid-latitudes) to meaningfully raise the odds of a usable
    cloud-free/water-clear pass, without extending far enough to risk
    pooling a genuinely different seasonal vegetation state into the
    same core/halo comparison.

    NOT used by the new temporal-persistence check below -- that
    function takes its own explicit, separately-reasoned days_back
    default (180) directly as a parameter, rather than sharing this
    function's 90-day default; see this module's own docstring,
    TEMPORAL PERSISTENCE CHECK, WINDOW CHOICE note, for why."""
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
        # HONEST NOTE (bug fixed a prior session): a missing/null stDev from
        # Sentinel Hub for this interval (a real, plausible response when
        # very few pixels survive cloud/water masking) means the variance
        # for THIS interval is UNKNOWN -- it does not mean the variance is
        # verified to be exactly zero. Fixed by only folding an interval's
        # variance into the pool when Sentinel Hub actually reported one;
        # pooled_stddev is now None (not 0.0) if no interval ever reported
        # a usable stDev.
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


def _stats_by_interval_for_bbox(
    bbox: list,
    access_token: str,
    time_from: str,
    time_to: str,
    timeout: int = 8,
) -> list[dict]:
    """ADDED THIS SESSION -- sibling to _stats_for_bbox() above, same
    request shape and same real Sentinel Hub Statistical API call, but
    returns the PER-INTERVAL breakdown instead of pooling every interval
    into one merged mean/stddev. This is the building block the new
    temporal-persistence check below is built on -- see module docstring,
    TEMPORAL PERSISTENCE CHECK, for why this needs no new API call beyond
    what the existing snapshot check already makes.

    time_from/time_to are REQUIRED (not optional/defaulted) here, unlike
    _stats_for_bbox -- the caller (fetch_ndvi_temporal_persistence_check
    below) always computes and shares one window across both the core and
    halo calls, mirroring the CORE/HALO SHARED-TIME-WINDOW FIX already
    applied to the snapshot check; there is no meaningful standalone use
    of this function with an implicit "now"-derived window the way the
    snapshot check's single-call convenience path has.

    Returns a list of dicts, ONE PER INTERVAL THAT HAD USABLE DATA (an
    interval with zero valid pixels after masking is simply omitted, not
    included as a zero/null entry) -- each:
      {"from": str, "to": str, "mean": float, "stddev": float | None,
       "sample_count": int}
    "from"/"to" are copied verbatim from Sentinel Hub's own
    interval["interval"]["from"/"to"] strings (confirmed via official
    Sentinel Hub documentation and a real published usage example, NOT
    guessed -- see module docstring) so callers can date-match core
    against halo by exact string equality rather than by list position
    or order, since the two are separate API calls.

    Raises NDVIFetchError only for a true hard failure (network/auth/
    malformed response) or if literally zero intervals exist in the
    response at all -- a response containing intervals where NONE of
    them have usable pixel data still returns an EMPTY LIST here (not an
    error), since "this bbox has zero usable dates in this window" is
    honest, real information for the persistence check's own caller to
    interpret (see fetch_ndvi_temporal_persistence_check's own docstring,
    HONEST "UNTESTED, NEVER ASSUMED UNSTABLE" note) -- it is NOT this
    low-level function's job to decide whether zero usable intervals is
    a failure; that judgment belongs to the caller, which has both core
    AND halo results to reason about together.
    """
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

    results: list[dict] = []
    for interval in intervals:
        interval_bounds = interval.get("interval", {})
        interval_from = interval_bounds.get("from")
        interval_to = interval_bounds.get("to")

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

        if valid_count <= 0 or mean is None or interval_from is None or interval_to is None:
            continue

        results.append({
            "from": interval_from,
            "to": interval_to,
            "mean": mean,
            "stddev": stdev,
            "sample_count": valid_count,
        })

    return results


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
    for both the core and halo bbox calls. Also computes ONE (time_from,
    time_to) window and passes it explicitly to BOTH bbox calls (see
    module docstring, CORE/HALO SHARED-TIME-WINDOW FIX -- previously each
    call independently derived its own window via _default_time_range(),
    which was never actually guaranteed to be identical between the two).

    STATISTICAL METHOD (fixed a prior session -- see HONEST NOTE below):
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

    HONEST NOTE (bug found and fixed a prior session): the previous version
    of this function divided the difference in MEANS by the halo bbox's
    raw PIXEL-LEVEL spatial standard deviation instead of a proper
    standard-error-of-the-difference. Fixed as described above.
    Standard-error-of-the-difference shrinks with real pixel counts
    (unlike raw stddev), so genuine small mean shifts at this AOI scale
    can register instead of structurally vanishing. If either bbox's
    valid pixel count is too small for a meaningful test (fewer than 2),
    or the standard error itself computes to (near) zero, this now
    RAISES NDVIFetchError with an honest explanation instead of silently
    returning a fabricated z_score=0.0 "no stress detected" result --
    matching this project's existing zero-fake-data principle.

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

    # CORE/HALO SHARED-TIME-WINDOW FIX (a prior session): compute the
    # window ONCE, pass it explicitly to both calls below, so core and
    # halo are guaranteed to be queried over the identical time range.
    time_from, time_to = _default_time_range()

    core_stats = _stats_for_bbox(core_bbox, token, time_from=time_from, time_to=time_to, timeout=timeout)
    halo_stats = _stats_for_bbox(halo_bbox, token, time_from=time_from, time_to=time_to, timeout=timeout)

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

    # HONEST NOTE: standard_error computing to (near) zero does NOT
    # always mean "insufficient data to test" -- both core_stddev and
    # halo_stddev are CONFIRMED real, non-null values from Sentinel Hub
    # here (the None-check above already ruled out "unknown variance").
    # If both areas genuinely have near-zero internal variance AND their
    # means still differ by a real amount, that is the MOST statistically
    # confident result possible. A large-but-finite sentinel z-score is
    # used for the confident case (not literal math.inf, since Android's
    # org.json is not guaranteed to parse a literal "Infinity" JSON
    # token the same way Python's json module would).
    #
    # KNOWN LIMITATION, NOT YET ADDRESSED: this sentinel path only
    # requires core_n/halo_n >= 2 above, the bare minimum for the
    # standard-error formula to be defined at all, not itself a
    # meaningful robustness floor -- see investigation_multi_mobile.py's
    # own SAMPLE-COUNT VISIBILITY FIX note.
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


def fetch_ndvi_temporal_persistence_check(
    lat: float,
    lon: float,
    client_id: str,
    client_secret: str,
    core_radius_m: float = 15.0,
    halo_radius_m: float = 60.0,
    stress_zscore_threshold: float = 1.5,
    days_back: int = 180,
    timeout: int = 8,
    access_token: str | None = None,
) -> dict:
    """ADDED THIS SESSION -- checks whether fetch_ndvi_core_halo_check's
    vegetation-stress signal reproduces across MULTIPLE real, independent
    Sentinel-2 acquisitions, not just one pooled snapshot. See module
    docstring, TEMPORAL PERSISTENCE CHECK, for the full design reasoning
    (no new API calls needed beyond the snapshot check's own 2-calls-per-
    candidate shape; date-matched, not position-matched; deliberately
    different, more forgiving error-handling philosophy than the
    snapshot check).

    days_back defaults to 180 (NOT the snapshot check's 90-day default --
    see module docstring, WINDOW CHOICE, for why these are intentionally
    separate numbers) -- wide enough to typically span ~6 real P30D
    buckets, giving a persistence judgment room to mean something.

    Uses the SAME core_radius_m/halo_radius_m defaults, and the SAME
    core-below-halo direction rule (NDVI's own one-directional stress
    signature), as fetch_ndvi_core_halo_check above -- only the pooling
    behavior differs.

    Returns a dict:
      {
        "n_intervals_fetched": int,   # real intervals with usable data
                                       # on BOTH core and halo (i.e.
                                       # actually testable)
        "n_intervals_testable": int,  # of those, how many had
                                       # core_n>=2, halo_n>=2, AND a
                                       # non-null stddev on both sides
                                       # (the same floor
                                       # fetch_ndvi_core_halo_check uses,
                                       # applied per-interval instead of
                                       # to one pooled measurement)
        "n_intervals_detected": int,  # of the testable ones, how many
                                       # independently detected stress
        "persistence_score": float | None,  # n_detected / n_testable,
                                       # or None if n_testable == 0
                                       # (genuinely could not be tested
                                       # this window -- NOT "no
                                       # persistence", an honest
                                       # "untested" state)
        "interval_results": [
            {"from": str, "to": str, "z_score": float | None,
             "detected": bool | None},
            ...
        ],
      }
    Each interval_results entry has z_score=None/detected=None when that
    specific interval had data on both sides but didn't clear the
    core_n>=2/halo_n>=2/non-null-stddev floor (genuinely untestable, not
    "no stress") -- mirroring the same "untested, never assumed
    negative" honesty this function applies at the aggregate level.

    Raises NDVIFetchError only for a true hard failure: token/auth error,
    network error on either the core or halo request, a malformed
    response, or literally zero usable intervals on EITHER side across
    the entire window (meaning nothing at all could be compared -- a
    real, if unfortunate, condition e.g. under near-constant regional
    cloud cover). A thin-but-nonzero number of testable intervals is
    NEVER an error -- see module docstring, HONEST "UNTESTED, NEVER
    ASSUMED UNSTABLE" PHILOSOPHY.
    """
    core_bbox = _bbox_from_point(lat, lon, core_radius_m)
    halo_bbox = _bbox_from_point(lat, lon, halo_radius_m)

    token = access_token or get_access_token(client_id, client_secret, timeout=timeout)

    # Both requests share the identical window and P30D grid -- see
    # module docstring, DATE-MATCHING, NOT POSITIONAL MATCHING, for why
    # this guarantees identical interval BOUNDARIES between the two
    # calls even when which intervals actually have data differs.
    time_from, time_to = _default_time_range(days_back=days_back)

    core_intervals = _stats_by_interval_for_bbox(core_bbox, token, time_from, time_to, timeout=timeout)
    halo_intervals = _stats_by_interval_for_bbox(halo_bbox, token, time_from, time_to, timeout=timeout)

    if not core_intervals and not halo_intervals:
        raise NDVIFetchError(
            "No usable (non-water, non-cloud, non-nodata) NDVI pixels "
            "were found in EITHER the core or halo area across the "
            "entire queried window -- nothing at all could be compared "
            "for temporal persistence at this location."
        )

    # Date-match by exact interval boundary strings (see module
    # docstring, DATE-MATCHING, NOT POSITIONAL MATCHING).
    halo_by_bounds = {(h["from"], h["to"]): h for h in halo_intervals}

    interval_results: list[dict] = []
    n_fetched = 0
    n_testable = 0
    n_detected = 0

    for core_entry in core_intervals:
        bounds = (core_entry["from"], core_entry["to"])
        halo_entry = halo_by_bounds.get(bounds)
        if halo_entry is None:
            # This exact interval had usable core data but no matching
            # usable halo data (or vice versa, for intervals only in
            # halo_intervals -- those are simply never iterated here) --
            # genuinely not comparable for this one date. Not counted as
            # fetched/testable/detected; not reported as an
            # interval_results entry either, since there is no
            # meaningful core-vs-halo pair to describe for this date.
            continue

        n_fetched += 1
        core_n = core_entry["sample_count"]
        halo_n = halo_entry["sample_count"]
        core_stddev = core_entry["stddev"]
        halo_stddev = halo_entry["stddev"]

        if core_n < 2 or halo_n < 2 or core_stddev is None or halo_stddev is None:
            interval_results.append({
                "from": bounds[0], "to": bounds[1],
                "z_score": None, "detected": None,
            })
            continue

        mean_difference = core_entry["mean"] - halo_entry["mean"]
        standard_error = math.sqrt(
            (core_stddev ** 2) / core_n
            + (halo_stddev ** 2) / halo_n
        )

        if standard_error <= 1e-9:
            if abs(mean_difference) <= 1e-9:
                # Genuinely uninformative for THIS interval (both areas
                # flat and identical) -- honestly untestable, same as
                # the missing-stddev case above, not a detection either way.
                interval_results.append({
                    "from": bounds[0], "to": bounds[1],
                    "z_score": None, "detected": None,
                })
                continue
            z_score = 50.0 if mean_difference > 0 else -50.0
        else:
            z_score = mean_difference / standard_error

        detected = z_score <= -stress_zscore_threshold
        n_testable += 1
        if detected:
            n_detected += 1
        interval_results.append({
            "from": bounds[0], "to": bounds[1],
            "z_score": z_score, "detected": detected,
        })

    persistence_score = (n_detected / n_testable) if n_testable > 0 else None

    return {
        "n_intervals_fetched": n_fetched,
        "n_intervals_testable": n_testable,
        "n_intervals_detected": n_detected,
        "persistence_score": persistence_score,
        "interval_results": interval_results,
    }
