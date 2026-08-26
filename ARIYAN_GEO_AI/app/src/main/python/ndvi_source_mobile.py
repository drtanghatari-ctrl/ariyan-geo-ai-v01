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

Pure Python standard library only (urllib, json, math, datetime). No numpy,
no rasterio, no requests library dependency.

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
"""

from __future__ import annotations

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


def _http_post(url: str, data: bytes, headers: dict, timeout: int) -> str:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise NDVIFetchError(f"HTTP {exc.code} from {url}: {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise NDVIFetchError(f"Network error contacting {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise NDVIFetchError(f"Timed out contacting {url}") from exc


def get_access_token(client_id: str, client_secret: str, timeout: int = 30) -> str:
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
    client_id: str,
    client_secret: str,
    time_from: str | None = None,
    time_to: str | None = None,
    timeout: int = 30,
) -> dict:
    """Calls the Sentinel Hub Statistical API for one bbox and returns the
    pooled real NDVI statistics across whatever cloud-free/water-masked
    pixel observations exist in the time range.

    Returns a dict: {"mean": float, "stddev": float, "sample_count": int,
    "n_intervals_with_data": int}.

    Raises NDVIFetchError if authentication fails, the request fails, the
    response is malformed, or there is no valid (non-water, non-nodata)
    pixel data anywhere in the time range -- this is a real "no usable
    signal" condition, not something to paper over with a default value.
    """
    token = get_access_token(client_id, client_secret, timeout=timeout)

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
            "Authorization": f"Bearer {token}",
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
        weighted_var_sum += (stdev or 0.0) ** 2 * valid_count

    if total_n <= 0:
        raise NDVIFetchError(
            "No usable (non-water, non-cloud, non-nodata) NDVI pixels found "
            "in this AOI over the queried time range. This can be a real "
            "condition (persistent cloud cover, water body, or a very small "
            "AOI), not necessarily a bug."
        )

    pooled_mean = weighted_mean_sum / total_n
    pooled_stddev = math.sqrt(weighted_var_sum / total_n)

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
    timeout: int = 30,
) -> dict:
    """Single-AOI real NDVI mean/stddev/min-style summary for a circular
    area around a point, expressed as an equivalent bbox. Used for the
    simple single-AOI path (not the per-candidate core/halo check below)."""
    bbox = _bbox_from_point(lat, lon, radius_m)
    return _stats_for_bbox(bbox, client_id, client_secret, timeout=timeout)


def fetch_ndvi_core_halo_check(
    lat: float,
    lon: float,
    client_id: str,
    client_secret: str,
    core_radius_m: float = 15.0,
    halo_radius_m: float = 60.0,
    stress_zscore_threshold: float = 1.5,
    timeout: int = 30,
) -> dict:
    """Per-DEM-candidate real vegetation-stress check.

    Fetches real NDVI mean/stddev for a small "core" bbox at the candidate
    point and a larger "halo" bbox around it (the halo bbox geometrically
    includes the core -- this is a documented approximation, not a true
    annulus subtraction, since the Statistics API operates on bboxes).

    Flags vegetation_stress_detected=True when the core mean NDVI is
    significantly below the halo mean NDVI (z-score computed against the
    halo's own stddev) -- a real, documented remote-sensing signature of
    vegetation stress that can occur over a buried feature (e.g. reduced
    root-zone moisture/soil depth altering canopy vigor).

    Returns a dict:
      {
        "core_mean": float, "halo_mean": float, "halo_stddev": float,
        "z_score": float, "vegetation_stress_detected": bool,
        "core_sample_count": int, "halo_sample_count": int,
      }

    Raises NDVIFetchError (propagated from either the core or halo fetch)
    on any auth/network/no-data failure. Callers should catch this per
    candidate and record it as an honest SINGLE_SOURCE result with the
    real error message, rather than failing the whole investigation.
    """
    core_bbox = _bbox_from_point(lat, lon, core_radius_m)
    halo_bbox = _bbox_from_point(lat, lon, halo_radius_m)

    core_stats = _stats_for_bbox(core_bbox, client_id, client_secret, timeout=timeout)
    halo_stats = _stats_for_bbox(halo_bbox, client_id, client_secret, timeout=timeout)

    halo_stddev = halo_stats["stddev"]
    if halo_stddev <= 1e-9:
        z_score = 0.0
    else:
        z_score = (core_stats["mean"] - halo_stats["mean"]) / halo_stddev

    vegetation_stress_detected = z_score <= -stress_zscore_threshold

    return {
        "core_mean": core_stats["mean"],
        "halo_mean": halo_stats["mean"],
        "halo_stddev": halo_stddev,
        "z_score": z_score,
        "vegetation_stress_detected": vegetation_stress_detected,
        "core_sample_count": core_stats["sample_count"],
        "halo_sample_count": halo_stats["sample_count"],
    }
