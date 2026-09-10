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

QUERY-WINDOW WIDENED 60 -> 90 DAYS (a prior session -- REAL on-device
confidence issue, not a guess): mirrors ndvi_source_mobile.py's and
thermal_source_mobile.py's own QUERY-WINDOW WIDENED fix, applied for the
same real reason -- a real investigation run showed this module's
core/halo check reaching n=2 valid pixels per side (the statistical
floor fetch_optical_core_halo_check requires before attempting a
significance test at all), reaching the sentinel z=+/-50.0 "maximally
confident" branch on a sample too thin to actually justify that framing
(see fetch_optical_core_halo_check's own KNOWN LIMITATION note below).
Widened to 90 days for more chances at a cloud-free/water-clear
Sentinel-2 pass, matching NDVI's own reasoning exactly (same 10m bands,
same ~5-day revisit cadence at mid-latitudes) -- without extending far
enough to risk pooling a genuinely different season's visible-brightness
baseline (e.g. different soil moisture, different vegetation cover
fraction) into the same core/halo comparison.

CORE/HALO SHARED-TIME-WINDOW FIX (a prior session): mirrors
ndvi_source_mobile.py's and thermal_source_mobile.py's own fix of the
same name -- fetch_optical_core_halo_check previously called
_stats_for_bbox() for the core and halo bboxes without passing
time_from/time_to, so each call independently derived its own window via
_default_time_range() (which reads datetime.now(timezone.utc) separately
each time it's called). Fixed by computing (time_from, time_to) ONCE in
fetch_optical_core_halo_check and passing the same values explicitly to
both _stats_for_bbox() calls, guaranteeing core and halo are queried
over the identical time range.

TEMPORAL PERSISTENCE CHECK, ADDED THIS SESSION -- MIRRORS THERMAL'S OWN
(queue item 2, continuing from ndvi_source_mobile.py's and
thermal_source_mobile.py's already-built pieces; see
ndvi_source_mobile.py's own TEMPORAL PERSISTENCE CHECK docstring
section for the full shared design reasoning -- no new API calls
needed beyond the snapshot check's existing 2-calls-per-candidate
shape, since the Statistical API already returns one entry per
aggregationInterval bucket; date-matched by exact interval "from"/"to"
boundary strings rather than list position, since core and halo are
separate API calls that can have different usable dates; "untested,
never assumed unstable" error philosophy -- a thin-but-nonzero number
of testable intervals is honest information, not a fetch failure).

FOLLOWS THERMAL'S NO-ASSUMED-SIGN PATTERN, NOT NDVI'S ONE-DIRECTIONAL
ONE: like Thermal, Optical's snapshot check (fetch_optical_core_halo_check
above) already has no assumed direction -- a soilmark can be brighter or
darker than its surroundings depending on fill material (see module
docstring, DIRECTION CONVENTION). So this persistence check applies the
SAME |z| >= threshold rule as the snapshot check per interval, and
reports core_brighter_than_halo per interval (not just an aggregate
direction), matching thermal_source_mobile.py's own reasoning for why
collapsing sign into one aggregate would discard real information --
here specifically, different real acquisitions could plausibly disagree
in sign depending on how soil moisture/illumination varied between
passes.

RADII/WINDOW, THE ONE GENUINE DIFFERENCE FROM THERMAL'S VERSION: unlike
Thermal (whose persistence check reuses Thermal's own larger 45m/180m
snapshot radii, to compensate for Landsat's coarser resolution), this
function defaults to Optical's own SMALLER 15m/60m radii, identical to
NDVI's -- since Optical shares NDVI's native 10m Sentinel-2 bands (see
module docstring, RESOLUTION / CORE-HALO RADII). days_back defaults to
180, matching both NDVI's and Thermal's own persistence-check default
(NOT this module's own 90-day snapshot default) -- see
ndvi_source_mobile.py's own WINDOW CHOICE note for why a persistence
check needs its own wider, separately-reasoned window.

NOT YET WIRED INTO THE APP: mirrors ndvi_source_mobile.py's and
thermal_source_mobile.py's own status notes -- this function exists and
follows the same design proven for NDVI/Thermal, but is NOT YET called
from investigation_multi_mobile.py, and has no evidence_record.py slot
yet. Calling this function today would work correctly in isolation but
produce a result nothing in the app yet reads or displays. With this
addition, all three sources (NDVI/Thermal/Optical) now have their
persistence-check building block built -- the remaining queue-item-2
scope is entirely in evidence_record.py and investigation_multi_mobile.py
(the wiring), plus the Steward warning-type design.
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


def _default_time_range(days_back: int = 90) -> tuple:
    """WIDENED 60 -> 90 A PRIOR SESSION -- see module docstring, QUERY-WINDOW
    WIDENED note, for the full real on-device reasoning (mirrors
    ndvi_source_mobile.py's identical fix and rationale, since this
    module shares NDVI's 10m resolution and revisit cadence).

    NOT used by the new temporal-persistence check below -- that
    function takes its own explicit, separately-reasoned days_back
    default (180) directly as a parameter, mirroring NDVI's and
    Thermal's own WINDOW CHOICE separation; see this module's own
    docstring, TEMPORAL PERSISTENCE CHECK, for why."""
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


def _stats_by_interval_for_bbox(
    bbox: list,
    access_token: str,
    time_from: str,
    time_to: str,
    timeout: int = 8,
) -> list[dict]:
    """ADDED THIS SESSION -- sibling to _stats_for_bbox() above, same
    request shape and same real Sentinel Hub Statistical API call
    against `sentinel-2-l2a`, but returns the PER-INTERVAL breakdown
    instead of pooling every interval into one merged mean/stddev.
    Mirrors ndvi_source_mobile.py's and thermal_source_mobile.py's own
    sibling functions exactly -- see either's docstring, and this
    module's own TEMPORAL PERSISTENCE CHECK docstring section, for the
    full reasoning (no new API call shape beyond what _stats_for_bbox()
    already makes; interval "from"/"to" strings copied verbatim from
    Sentinel Hub's own response so core and halo can be date-matched by
    exact string equality rather than by list position or order).

    time_from/time_to are REQUIRED here (not optional/defaulted),
    exactly like NDVI's and Thermal's sibling functions -- the caller
    (fetch_optical_temporal_persistence_check below) always computes
    and shares one window across both the core and halo calls.

    Returns a list of dicts, ONE PER INTERVAL THAT HAD USABLE DATA (an
    interval with zero valid pixels after masking is simply omitted,
    not included as a zero/null entry) -- each:
      {"from": str, "to": str, "mean": float, "stddev": float | None,
       "sample_count": int}

    Raises OpticalFetchError only for a true hard failure (network/
    auth/malformed response) or if literally zero intervals exist in
    the response at all -- a response containing intervals where NONE
    of them have usable pixel data still returns an EMPTY LIST here
    (not an error), mirroring NDVI's/Thermal's own sibling functions
    exactly: "this bbox has zero usable dates in this window" is
    honest information for the caller (which has both core AND halo
    results to reason about together) to interpret, not a failure this
    low-level function should decide on its own.
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
    convention. Also computes ONE (time_from, time_to) window and passes
    it explicitly to BOTH bbox calls (a prior session -- see module
    docstring, CORE/HALO SHARED-TIME-WINDOW FIX).

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

    KNOWN LIMITATION, NOT YET ADDRESSED (flagged this session): like
    NDVI's and Thermal's own core/halo checks, the core_n/halo_n >= 2
    floor below is the bare minimum for the standard-error formula to
    be defined at all, not itself a meaningful robustness floor -- see
    ndvi_source_mobile.py's own matching note for the full reasoning.
    """
    core_bbox = _bbox_from_point(lat, lon, core_radius_m)
    halo_bbox = _bbox_from_point(lat, lon, halo_radius_m)

    try:
        token = access_token or get_access_token(client_id, client_secret, timeout=timeout)
    except NDVIFetchError as exc:
        raise OpticalFetchError(str(exc)) from exc

    # CORE/HALO SHARED-TIME-WINDOW FIX (a prior session): compute the window
    # ONCE, pass it explicitly to both calls below.
    time_from, time_to = _default_time_range()

    core_stats = _stats_for_bbox(core_bbox, token, time_from=time_from, time_to=time_to, timeout=timeout)
    halo_stats = _stats_for_bbox(halo_bbox, token, time_from=time_from, time_to=time_to, timeout=timeout)

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


def fetch_optical_temporal_persistence_check(
    lat: float,
    lon: float,
    client_id: str,
    client_secret: str,
    core_radius_m: float = 15.0,
    halo_radius_m: float = 60.0,
    anomaly_zscore_threshold: float = 1.5,
    days_back: int = 180,
    timeout: int = 8,
    access_token: str | None = None,
) -> dict:
    """ADDED THIS SESSION -- checks whether fetch_optical_core_halo_check's
    brightness-anomaly signal reproduces across MULTIPLE real, independent
    Sentinel-2 acquisitions, not just one pooled snapshot. Mirrors
    thermal_source_mobile.py's fetch_thermal_temporal_persistence_check()
    structurally (same no-assumed-sign convention -- see module docstring,
    FOLLOWS THERMAL'S NO-ASSUMED-SIGN PATTERN), with one real, deliberate
    difference documented below (see module docstring, TEMPORAL
    PERSISTENCE CHECK, for the full shared design reasoning).

    THE ONE GENUINE DIFFERENCE FROM THERMAL'S VERSION -- RADII: default
    core_radius_m/halo_radius_m are Optical's own SMALLER 15m/60m
    (identical to NDVI's), NOT Thermal's larger 45m/180m, since Optical
    shares NDVI's native 10m Sentinel-2 bands rather than Landsat's
    coarser 30m thermal band (see module docstring, RADII/WINDOW, THE
    ONE GENUINE DIFFERENCE FROM THERMAL'S VERSION). days_back still
    defaults to 180, matching both NDVI's and Thermal's persistence
    checks (NOT this module's own 90-day snapshot default).

    Otherwise identical in structure to Thermal's persistence check:
    each interval is tested with the SAME |z| >= threshold rule as the
    snapshot check (no assumed direction), each interval_results entry
    reports core_brighter_than_halo per interval (not just an aggregate
    direction), and the SAME "untested, never assumed unstable" error
    philosophy applies -- a thin-but-nonzero number of testable
    intervals is a normal, honest persistence_score, never an
    exception; only a true hard failure (token/auth/network error, a
    malformed response, or literally zero usable intervals on EITHER
    side across the entire window) raises OpticalFetchError.

    Returns a dict:
      {
        "n_intervals_fetched": int,   # real intervals with usable data
                                       # on BOTH core and halo (i.e.
                                       # actually testable)
        "n_intervals_testable": int,  # of those, how many had
                                       # core_n>=2, halo_n>=2, AND a
                                       # non-null stddev on both sides
                                       # (the same floor
                                       # fetch_optical_core_halo_check
                                       # uses, applied per-interval
                                       # instead of to one pooled
                                       # measurement)
        "n_intervals_detected": int,  # of the testable ones, how many
                                       # independently cleared |z| >=
                                       # threshold in EITHER direction
        "persistence_score": float | None,  # n_detected / n_testable,
                                       # or None if n_testable == 0
                                       # (genuinely could not be tested
                                       # this window -- NOT "no
                                       # persistence", an honest
                                       # "untested" state)
        "interval_results": [
            {"from": str, "to": str, "z_score": float | None,
             "detected": bool | None,
             "core_brighter_than_halo": bool | None},
            ...
        ],
      }
    Each interval_results entry has z_score=None/detected=None/
    core_brighter_than_halo=None when that specific interval had data on
    both sides but didn't clear the core_n>=2/halo_n>=2/non-null-stddev
    floor (genuinely untestable, not "no anomaly") -- mirroring the same
    "untested, never assumed negative" honesty this function applies at
    the aggregate level.

    Raises OpticalFetchError only for a true hard failure: token/auth
    error, network error on either the core or halo request, a
    malformed response, or literally zero usable intervals on EITHER
    side across the entire window (meaning nothing at all could be
    compared -- a real, if unfortunate, condition e.g. under near-
    constant regional cloud cover). A thin-but-nonzero number of
    testable intervals is NEVER an error.
    """
    core_bbox = _bbox_from_point(lat, lon, core_radius_m)
    halo_bbox = _bbox_from_point(lat, lon, halo_radius_m)

    try:
        token = access_token or get_access_token(client_id, client_secret, timeout=timeout)
    except NDVIFetchError as exc:
        raise OpticalFetchError(str(exc)) from exc

    # Both requests share the identical window and P30D grid -- see
    # module docstring, TEMPORAL PERSISTENCE CHECK (which cross-references
    # ndvi_source_mobile.py's DATE-MATCHING, NOT POSITIONAL MATCHING note),
    # for why this guarantees identical interval BOUNDARIES between the
    # two calls even when which intervals actually have data differs.
    time_from, time_to = _default_time_range(days_back=days_back)

    core_intervals = _stats_by_interval_for_bbox(core_bbox, token, time_from, time_to, timeout=timeout)
    halo_intervals = _stats_by_interval_for_bbox(halo_bbox, token, time_from, time_to, timeout=timeout)

    if not core_intervals and not halo_intervals:
        raise OpticalFetchError(
            "No usable (non-water, non-cloud, non-nodata) optical pixels "
            "were found in EITHER the core or halo area across the "
            "entire queried window -- nothing at all could be compared "
            "for temporal persistence at this location."
        )

    # Date-match by exact interval boundary strings -- core and halo are
    # separate API calls that can have different usable dates.
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
            # usable halo data (or vice versa) -- genuinely not
            # comparable for this one date. Not counted as fetched/
            # testable/detected; not reported as an interval_results
            # entry either, mirroring NDVI's/Thermal's own persistence
            # checks.
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
                "core_brighter_than_halo": None,
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
                # flat and identical) -- honestly untestable, not a
                # detection either way.
                interval_results.append({
                    "from": bounds[0], "to": bounds[1],
                    "z_score": None, "detected": None,
                    "core_brighter_than_halo": None,
                })
                continue
            z_score = 50.0 if mean_difference > 0 else -50.0
        else:
            z_score = mean_difference / standard_error

        # NO ASSUMED SIGN, applied per-interval (mirrors Thermal's own
        # persistence check): |z| clearing the threshold in EITHER
        # direction counts as detected.
        detected = abs(z_score) >= anomaly_zscore_threshold
        core_brighter_than_halo = mean_difference > 0
        n_testable += 1
        if detected:
            n_detected += 1
        interval_results.append({
            "from": bounds[0], "to": bounds[1],
            "z_score": z_score, "detected": detected,
            "core_brighter_than_halo": core_brighter_than_halo,
        })

    persistence_score = (n_detected / n_testable) if n_testable > 0 else None

    return {
        "n_intervals_fetched": n_fetched,
        "n_intervals_testable": n_testable,
        "n_intervals_detected": n_detected,
        "persistence_score": persistence_score,
        "interval_results": interval_results,
    }