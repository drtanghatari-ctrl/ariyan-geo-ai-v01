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
    bbox: list, client_id: str, client_secret:
...

[Message clipped]  View entire message
