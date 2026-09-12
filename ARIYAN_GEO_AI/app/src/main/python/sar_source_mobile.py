"""
sar_source_mobile.py
======================
REAL Sentinel-1 SAR (Synthetic Aperture Radar) backscatter evidence for
Android, via the Copernicus Data Space Ecosystem's Sentinel Hub Statistical
API -- same account/OAuth already used by ndvi_source_mobile.py,
thermal_source_mobile.py, and optical_source_mobile.py.

WHY THIS WORKS THE SAME WAY NDVI DOES: exactly like NDVI, the heavy lifting
(SAR calibration, terrain correction, statistics) happens server-side; the
device only ever receives a small plain-JSON statistics object, never a
raster. Confirmed working via a real, live test from this project's own
history: a real HTTP POST to the Statistics API with
`"type":"sentinel-1-grd"` (run via Termux/curl directly on the user's
phone, since there is no laptop and the original desktop test script
wasn't recoverable) returned real VV/VH backscatter statistics across
real 30-day intervals -- genuine live data, not synthetic. That test also
found the API requires an explicit `dataMask` input/output band in the
evalscript (added below, matching the fix applied during that test).

WHY THIS IS ARCHITECTED TWO-DIRECTIONAL, NOT ONE-DIRECTIONAL LIKE NDVI
(a deliberate design decision, grounded in real published literature, not
guessed -- verified via web search before writing any code, per this
project's zero-fabrication rule):

NDVI has a clean, single, physically-justified direction: reduced
root-zone moisture/soil depth over a buried feature suppresses vegetation
vigor, so only core-BELOW-halo counts as "stress" evidence. SAR backscatter
has NO equivalent single direction. Real published research on Sentinel-1
over palaeo-landscape/archaeological features (Mediterranean study, 2020)
found BOTH signatures occur -- "some black ditches and white complex areas
were identified with archaeological potential for buried archaeological
remains" -- because backscatter intensity is jointly driven by soil
dielectric constant (moisture) and surface roughness, which can push a
buried feature's signature either brighter or darker than its surroundings
depending on season and ground conditions. The same source notes VV and VH
polarizations "helped in discriminating and estimating the different
contributions due to (i) the moisture content and (ii) roughness" -- i.e.
the two channels carry genuinely separable information, which is why this
module tracks and tests them SEPARATELY rather than merging into one
number (see fetch_sar_core_halo_check's returned dict shape below).

This module therefore mirrors thermal_source_mobile.py's/
optical_source_mobile.py's two-directional "core different from halo,
sign not assumed in advance" pattern -- never NDVI's one-directional rule.

HONEST SCOPE LIMITATION (stated here and worth surfacing in the UI, not
just this docstring): genuinely robust SAR-based archaeological detection
in the literature typically combines backscatter intensity WITH coherence
and interferometric phase (a 2017 COSMO-SkyMed study over Rome-area sites
demonstrated "SAR backscatter intensity, coherence and interferometry" all
contributing to detecting buried-structure residues). The Statistics API
used here returns only single-date backscatter statistics -- real data,
but a narrower slice of what the literature considers strong SAR evidence.
This module's evidence should be read as informative, not as strong on its
own the way a corroborated multi-source detection is.

CREDENTIALS: reuses the SAME Copernicus Data Space Ecosystem OAuth2
client_id/client_secret already used for NDVI/Thermal/Optical -- no new
account or credential needed.

Pure Python standard library only (urllib, json, math, datetime) plus
concurrent.futures (stdlib) for the hard-deadline wrapper, mirroring
ndvi_source_mobile.py's own HARD-DEADLINE FIX exactly (urllib's timeout=
does not reliably bound DNS resolution, which is a separate unbounded
OS-level call).

NOT YET WIRED INTO THE APP: this module is built and will be sandbox-
tested against realistic synthetic Sentinel Hub response shapes, but is
NOT YET called from investigation_multi_mobile.py, has no evidence_record.py
slot yet (planned: ninth_evidence), and MainActivity.kt/activity_main.xml
have no rendering for it yet. All deliberately deferred to the immediate
next wiring step, per this project's established pattern for every prior
evidence source (build the source module standalone and sandbox-verified
first, then wire it through the remaining files one at a time).
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

# Computes VV and VH backscatter server-side. dataMask is REQUIRED by the
# API for sentinel-1-grd requests -- confirmed via the real Termux/curl
# test in this project's history, where the first attempt (missing
# dataMask) was rejected and adding it to both input.bands and output
# fixed it on the first retry. Two separate output bands (vv, vh) rather
# than a single combined band, so the Statistics API reports each
# polarization's own mean/stddev/sampleCount independently -- this is
# what lets fetch_sar_core_halo_check below test VV and VH separately
# rather than conflating two genuinely different physical signals into
# one number (see module docstring).
SAR_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["VV", "VH", "dataMask"] }],
    output: [
      { id: "vv", bands: 1 },
      { id: "vh", bands: 1 },
      { id: "dataMask", bands: 1 }
    ]
  }
}
function evaluatePixel(samples) {
  return {
    vv: [samples.VV],
    vh: [samples.VH],
    dataMask: [samples.dataMask]
  }
}
"""


class SARFetchError(Exception):
    """Raised for any failure fetching/parsing real SAR data: auth,
    network, malformed response, or an AOI/time-range with no usable
    data on either polarization. Callers should catch this and record it
    as an honest failure -- never silently fall back to synthetic data,
    matching every other evidence source in this project."""


def _urlopen_with_hard_deadline(req: urllib.request.Request, timeout: int):
    """Identical pattern to ndvi_source_mobile.py's own
    _urlopen_with_hard_deadline() -- runs urlopen() on a background
    thread and enforces a real wall-clock deadline via
    concurrent.futures, regardless of which phase (DNS/connect/TLS/read)
    is actually blocking. Raises SARFetchError directly for every
    failure mode (never lets a raw exception escape)."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        def _do_request():
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")

        future = executor.submit(_do_request)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise SARFetchError(
                f"Timed out contacting {req.full_url} after {timeout}s "
                "(no network, or an extremely slow/blocked connection)."
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise SARFetchError(f"HTTP {exc.code} from {req.full_url}: {body[:300]}") from exc
        except urllib.error.URLError as exc:
            raise SARFetchError(f"Network error contacting {req.full_url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise SARFetchError(f"Timed out contacting {req.full_url}") from exc
    finally:
        executor.shutdown(wait=False)


def _http_post(url: str, data: bytes, headers: dict, timeout: int) -> str:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    return _urlopen_with_hard_deadline(req, timeout)


def get_access_token(client_id: str, client_secret: str, timeout: int = 8) -> str:
    """OAuth2 client-credentials token exchange -- identical to
    ndvi_source_mobile.py's own get_access_token(). Callers with an
    already-fetched token from another source's check this same
    investigation run (NDVI/Thermal/Optical all use the same Copernicus
    account) may pass it directly to the functions below instead of
    calling this again."""
    if not client_id or not client_secret:
        raise SARFetchError("Copernicus client_id and client_secret are required.")

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
        raise SARFetchError(f"Malformed token response: {exc}") from exc

    token = token_data.get("access_token")
    if not token:
        raise SARFetchError("Token response did not include an access_token.")
    return token


def _bbox_from_point(lat: float, lon: float, radius_m: float) -> list:
    """Same equirectangular-approximation bbox helper used by
    ndvi_source_mobile.py -- kept as its own copy (small, deliberate
    duplication) rather than importing across evidence-source modules,
    matching this project's existing pattern of each evidence module
    being independently self-contained."""
    dlat = radius_m / 111_320.0
    cos_lat = max(0.1, abs(math.cos(math.radians(lat))))
    dlon = radius_m / (111_320.0 * cos_lat)
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def _default_time_range(days_back: int = 90) -> tuple:
    """Defaults to the last `days_back` days ending now (UTC), mirroring
    NDVI's own 90-day snapshot-check default -- chosen for the same
    reason (enough real Sentinel-1 revisit opportunities -- roughly
    6-12 day repeat cycle depending on coverage -- without pooling too
    far across genuinely different seasonal ground-moisture states)."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days_back)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(fmt), now.strftime(fmt)


def _stats_for_bbox(
    bbox: list,
    access_token: str,
    time_from: str,
    time_to: str,
    acquisition_mode: str = "IW",
    polarization: str = "DV",
    timeout: int = 8,
) -> dict:
    """Calls the Sentinel Hub Statistical API for one bbox with
    "type": "sentinel-1-grd" and returns pooled real VV/VH statistics
    across whatever real acquisitions exist in the time range.

    acquisition_mode/polarization match the real, confirmed-working
    values from this project's live Termux/curl test (IW = Interferometric
    Wide swath, the standard Sentinel-1 land-observation mode; DV =
    dual-polarization VV+VH).

    Returns a dict:
      {
        "vv": {"mean": float, "stddev": float | None, "sample_count": int} | None,
        "vh": {"mean": float, "stddev": float | None, "sample_count": int} | None,
      }
    Either sub-dict is None if that polarization's band was entirely
    masked/absent for every interval in range -- a real, honest "no
    usable signal for this polarization" outcome, not folded into the
    other polarization's result.

    Raises SARFetchError if the request fails, the response is
    malformed, or there is NO usable data for either polarization
    anywhere in the time range."""
    request_body = {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {
                    "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
                },
            },
            "data": [{
                "type": "sentinel-1-grd",
                "dataFilter": {
                    "timeRange": {"from": time_from, "to": time_to},
                    "acquisitionMode": acquisition_mode,
                    "polarization": polarization,
                },
            }],
        },
        "aggregation": {
            "timeRange": {"from": time_from, "to": time_to},
            "aggregationInterval": {"of": "P30D"},
            "evalscript": SAR_EVALSCRIPT,
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
        raise SARFetchError(f"Malformed statistics response: {exc}") from exc

    intervals = response.get("data", [])
    if not intervals:
        raise SARFetchError(
            "Statistics API returned no time intervals for this AOI/time range."
        )

    def _pool_band(band_output_id: str) -> dict | None:
        total_n = 0
        weighted_mean_sum = 0.0
        weighted_var_sum = 0.0
        n_pixels_with_stddev = 0

        for interval in intervals:
            outputs = interval.get("outputs", {})
            band_output = outputs.get(band_output_id, {})
            bands = band_output.get("bands", {})
            band0 = bands.get("B0", {})
            stats = band0.get("stats", {})

            sample_count = stats.get("sampleCount", 0) or 0
            nodata_count = stats.get("noDataCount", 0) or 0
            valid_count = sample_count - nodata_count
            mean = stats.get("mean")
            stdev = stats.get("stDev")

            if valid_count <= 0 or mean is None:
                continue

            total_n += valid_count
            weighted_mean_sum += mean * valid_count
            # Same honest null-vs-zero-variance handling as NDVI: a
            # missing stDev means UNKNOWN variance for this interval,
            # never assumed to be zero.
            if stdev is not None:
                weighted_var_sum += (stdev ** 2) * valid_count
                n_pixels_with_stddev += valid_count

        if total_n <= 0:
            return None

        pooled_mean = weighted_mean_sum / total_n
        pooled_stddev = (
            math.sqrt(weighted_var_sum / n_pixels_with_stddev)
            if n_pixels_with_stddev > 0
            else None
        )
        return {"mean": pooled_mean, "stddev": pooled_stddev, "sample_count": total_n}

    vv_stats = _pool_band("vv")
    vh_stats = _pool_band("vh")

    if vv_stats is None and vh_stats is None:
        raise SARFetchError(
            "No usable Sentinel-1 backscatter data (VV or VH) found in this "
            "AOI over the queried time range. This can be a real condition "
            "(no acquisition covering this AOI in the window, or a "
            "genuinely masked/no-data pixel set), not necessarily a bug."
        )

    return {"vv": vv_stats, "vh": vh_stats}


def _two_sample_z(
    core: dict, halo: dict, label: str
) -> tuple[float, int, int]:
    """Shared two-sample z-test for one polarization's core-vs-halo
    comparison -- same statistical method as
    ndvi_source_mobile.fetch_ndvi_core_halo_check (standard error of the
    difference in means, combining both bboxes' own pixel-level
    variance), but with NO assumed sign: the returned z_score's sign
    itself carries the direction (positive = core backscatter higher
    than halo, negative = core lower), left for the caller to interpret
    -- see module docstring for why SAR cannot assume a direction the
    way NDVI does.

    Raises SARFetchError if either side has too few valid pixels (<2)
    for a meaningful test, or neither side reports a usable stddev --
    same honest-failure floor as every other core/halo check in this
    project, labeled with which polarization failed for a clearer error
    message.
    """
    core_n = core["sample_count"]
    halo_n = halo["sample_count"]
    core_stddev = core["stddev"]
    halo_stddev = halo["stddev"]

    if core_n < 2 or halo_n < 2:
        raise SARFetchError(
            f"Too few valid {label} backscatter pixels to compute a "
            f"meaningful core/halo statistic at this location "
            f"(core_sample_count={core_n}, halo_sample_count={halo_n})."
        )
    if core_stddev is None or halo_stddev is None:
        raise SARFetchError(
            f"Sentinel Hub did not report a usable standard deviation for "
            f"the {label} core and/or halo area over this time window -- "
            f"a significance test cannot be computed honestly without it."
        )

    mean_difference = core["mean"] - halo["mean"]
    standard_error = math.sqrt(
        (core_stddev ** 2) / core_n + (halo_stddev ** 2) / halo_n
    )

    if standard_error <= 1e-9:
        if abs(mean_difference) <= 1e-9:
            raise SARFetchError(
                f"Both the {label} core and halo area report (near) zero "
                f"internal variance AND (near) identical means -- there is "
                f"genuinely no detectable signal to test either way."
            )
        z_score = 50.0 if mean_difference > 0 else -50.0
    else:
        z_score = mean_difference / standard_error

    return z_score, core_n, halo_n


def fetch_sar_core_halo_check(
    lat: float,
    lon: float,
    client_id: str,
    client_secret: str,
    core_radius_m: float = 15.0,
    halo_radius_m: float = 60.0,
    detection_zscore_threshold: float = 1.5,
    acquisition_mode: str = "IW",
    polarization: str = "DV",
    timeout: int = 8,
    access_token: str | None = None,
) -> dict:
    """Per-DEM-candidate real SAR backscatter check -- the SAR sibling
    of fetch_ndvi_core_halo_check / thermal's and optical's own
    core-vs-halo functions, but TWO-DIRECTIONAL on TWO SEPARATE
    polarizations (VV and VH) -- see module docstring for the full
    real-literature grounding on why this differs from NDVI's
    one-directional design.

    Fetches (or reuses, if `access_token` is passed in -- same
    Copernicus account already used for NDVI/Thermal/Optical) exactly
    ONE token, and computes ONE shared (time_from, time_to) window
    passed to both the core and halo requests, exactly mirroring NDVI's
    CORE/HALO SHARED-TIME-WINDOW FIX.

    Returns a dict:
      {
        "vv": {
          "core_mean": float, "halo_mean": float,
          "z_score": float, "detected": bool,
          "core_sample_count": int, "halo_sample_count": int,
        } | None,
        "vh": { ...same shape... } | None,
      }
    A polarization's sub-dict is None when that polarization genuinely
    had no usable data for either the core or halo bbox this run (an
    honest "untested" outcome for that one channel -- the OTHER
    polarization's result, if it succeeded, is still returned; a single
    polarization's absence never fails the whole check). "detected" is
    True when |z_score| >= detection_zscore_threshold, in EITHER
    direction -- unlike NDVI, a positive z (core brighter/rougher than
    halo) is just as valid a detection as a negative one, per this
    module's own two-directional design.

    Raises SARFetchError only when BOTH polarizations are entirely
    unusable (no data at all, or both fail the sample-count/variance
    floor) -- mirroring every other evidence source's "a thin result on
    one channel is honest information, not a hard failure" philosophy,
    while still surfacing a genuine total failure clearly.
    """
    core_bbox = _bbox_from_point(lat, lon, core_radius_m)
    halo_bbox = _bbox_from_point(lat, lon, halo_radius_m)

    token = access_token or get_access_token(client_id, client_secret, timeout=timeout)
    time_from, time_to = _default_time_range()

    core_stats = _stats_for_bbox(
        core_bbox, token, time_from, time_to,
        acquisition_mode=acquisition_mode, polarization=polarization, timeout=timeout,
    )
    halo_stats = _stats_for_bbox(
        halo_bbox, token, time_from, time_to,
        acquisition_mode=acquisition_mode, polarization=polarization, timeout=timeout,
    )

    result: dict = {"vv": None, "vh": None}
    any_succeeded = False
    errors: list[str] = []

    for pol_key, pol_label in (("vv", "VV"), ("vh", "VH")):
        core_pol = core_stats.get(pol_key)
        halo_pol = halo_stats.get(pol_key)
        if core_pol is None or halo_pol is None:
            errors.append(f"{pol_label}: no usable data on core and/or halo side.")
            continue
        try:
            z_score, core_n, halo_n = _two_sample_z(core_pol, halo_pol, pol_label)
        except SARFetchError as exc:
            errors.append(f"{pol_label}: {exc}")
            continue

        result[pol_key] = {
            "core_mean": core_pol["mean"],
            "halo_mean": halo_pol["mean"],
            "z_score": z_score,
            "detected": abs(z_score) >= detection_zscore_threshold,
            "core_sample_count": core_n,
            "halo_sample_count": halo_n,
        }
        any_succeeded = True

    if not any_succeeded:
        raise SARFetchError(
            "SAR core/halo check failed on both VV and VH: " + " | ".join(errors)
        )

    return result
