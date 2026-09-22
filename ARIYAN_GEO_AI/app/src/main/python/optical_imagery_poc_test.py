"""
optical_imagery_poc_test.py
============================
THROWAWAY VERIFICATION SCRIPT -- NOT part of the app, not wired into
investigation_multi_mobile.py or anything else. Sole purpose: answer one
open question before committing engineering effort to a real in-app
"final review" screen -- is Sentinel-2's native 10m/pixel true-color
imagery actually sharp enough to eyeball-accept/reject a candidate, for
the specific kinds of features that tripped up ARIYAN GEO AI this
session (a tank farm, an aquaculture pond complex, a real MODERATE
candidate)?

UNTESTED AGAINST THE LIVE API -- built from documented Sentinel Hub
Process API examples (same Copernicus Data Space Ecosystem account this
project already uses), following this project's OWN established
conventions from optical_source_mobile.py / ndvi_source_mobile.py:
  - same OAuth token function (imported, not duplicated)
  - same bbox-from-point equirectangular approximation (duplicated here,
    matching this project's own stated convention for tiny pure-math
    helpers with no network dependency)
  - same "reads binary, raises honestly on any failure, never fabricates
    a result" philosophy
The exact JSON request shape for the PROCESS API (distinct from the
STATISTICS API every other module in this project uses) has not been
smoke-tested against the live endpoint by me -- if the API rejects it,
compare the error message against Sentinel Hub's own Process API docs
(documentation.dataspace.copernicus.eu/APIs/SentinelHub/Process) and
adjust; the request body shape is a plausible, documentation-grounded
first draft, not a proven-working call.

RUN IT (Termux, same directory as ndvi_source_mobile.py, or with that
directory on PYTHONPATH):
    python3 optical_imagery_poc_test.py \
        --client-id YOUR_ID --client-secret YOUR_SECRET \
        --name al_wihda_tank_farm

Run it against 2-3 different known coordinates from this session (see
the presets below) and just LOOK at the resulting PNGs. That's the
entire point of this script -- it produces nothing the app reads, only
an image file for you to eyeball.

WORTH TRYING TWO WAYS PER SITE: once near native resolution (radius_m=200,
pixel_size=~40, i.e. ~10m/pixel -- the honest ground truth of what the
sensor actually resolves) and once upsampled for viewing (the defaults
below, pixel_size=512 -- interpolated, easier on the eye, but does NOT
add real detail beyond the native-resolution version). Comparing both
tells you whether apparent sharpness in the upsampled version is real
information or just smooth interpolation.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# Reused as-is -- same shared Copernicus OAuth entry point every other
# evidence source in this project already uses.
from ndvi_source_mobile import get_access_token, NDVIFetchError

PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

# Standard Sentinel-2 true-color evalscript (B04/B03/B02 -> RGB). The 2.5x
# brightening factor is the widely-used convention for Sentinel-2 L2A
# reflectance, which otherwise renders very dark at raw 0-1 scale. Tune
# this multiplier if a returned image looks over- or under-exposed.
TRUE_COLOR_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: ["B02", "B03", "B04"],
    output: { bands: 3 }
  };
}
function evaluatePixel(sample) {
  return [2.5 * sample.B04, 2.5 * sample.B03, 2.5 * sample.B02];
}
"""

# Known coordinates from this session, for quick --name shortcuts.
KNOWN_SITES = {
    "al_wihda_tank_farm": (33.150178, 44.649865),  # 8 circular storage tanks -- known NOISE
    "aquaculture_ponds": (33.057946, 44.627758),   # irrigation/aquaculture pond complex -- known NOISE
    "candidate_b": (33.10115, 44.52671),           # surviving MODERATE candidate, eroded ruin plateau
}


class ImageryFetchError(Exception):
    """Mirrors OpticalFetchError's role -- raised for any auth, network,
    or malformed-response failure. Never falls back to a placeholder
    image."""


def _bbox_from_point(lat: float, lon: float, radius_m: float) -> list:
    """Identical to optical_source_mobile.py's own helper -- duplicated
    per this project's stated convention for tiny pure-math helpers with
    no network/auth dependency."""
    dlat = radius_m / 111_320.0
    cos_lat = max(0.1, abs(math.cos(math.radians(lat))))
    dlon = radius_m / (111_320.0 * cos_lat)
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def _urlopen_binary_with_hard_deadline(req: urllib.request.Request, timeout: int) -> bytes:
    """Binary sibling of optical_source_mobile.py's own
    _urlopen_with_hard_deadline -- same hard wall-clock deadline via a
    background thread, but returns raw bytes (an image), never decoded
    as text."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        def _do_request():
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()

        future = executor.submit(_do_request)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise ImageryFetchError(f"Timed out contacting {req.full_url} after {timeout}s.")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ImageryFetchError(f"HTTP {exc.code} from {req.full_url}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise ImageryFetchError(f"Network error contacting {req.full_url}: {exc.reason}") from exc
    finally:
        executor.shutdown(wait=False)


def fetch_true_color_png(
    lat: float,
    lon: float,
    client_id: str,
    client_secret: str,
    radius_m: float = 200.0,
    pixel_size: int = 512,
    days_back: int = 90,
    timeout: int = 15,
) -> bytes:
    """One Process API call -> raw PNG bytes for a true-color crop
    centered on (lat, lon). radius_m controls the ground footprint
    (default: a 400m x 400m box). pixel_size controls the OUTPUT image
    resolution independent of Sentinel-2's native 10m -- requesting more
    pixels than the native resolution implies just interpolates, it does
    not add real ground detail, but can make small features easier to
    see on a phone screen. Both are worth varying between test runs (see
    module docstring)."""
    bbox = _bbox_from_point(lat, lon, radius_m)

    try:
        token = get_access_token(client_id, client_secret, timeout=timeout)
    except NDVIFetchError as exc:
        raise ImageryFetchError(str(exc)) from exc

    now = datetime.now(timezone.utc)
    time_from = (now - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    time_to = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    request_body = {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {"from": time_from, "to": time_to},
                    "maxCloudCoverage": 40,
                    "mosaickingOrder": "leastCC",  # prefer the clearest available scene in the window
                },
            }],
        },
        "output": {
            "width": pixel_size,
            "height": pixel_size,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
        },
        "evalscript": TRUE_COLOR_EVALSCRIPT,
    }

    req = urllib.request.Request(
        PROCESS_URL,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "image/png",
        },
        method="POST",
    )
    return _urlopen_binary_with_hard_deadline(req, timeout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    parser.add_argument("--name", help=f"One of: {', '.join(KNOWN_SITES)}")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--radius-m", type=float, default=200.0)
    parser.add_argument("--pixel-size", type=int, default=512)
    parser.add_argument("--out", default=None, help="Output PNG path")
    args = parser.parse_args()

    if args.name:
        if args.name not in KNOWN_SITES:
            raise SystemExit(f"Unknown --name '{args.name}'. Options: {', '.join(KNOWN_SITES)}")
        lat, lon = KNOWN_SITES[args.name]
        label = args.name
    elif args.lat is not None and args.lon is not None:
        lat, lon = args.lat, args.lon
        label = f"{lat}_{lon}"
    else:
        raise SystemExit("Provide either --name or both --lat and --lon.")

    out_path = args.out or f"{label}_r{int(args.radius_m)}m_{args.pixel_size}px.png"

    print(f"Fetching true-color crop for {label} ({lat}, {lon}), "
          f"radius={args.radius_m}m, output={args.pixel_size}x{args.pixel_size}px ...")

    try:
        png_bytes = fetch_true_color_png(
            lat, lon, args.client_id, args.client_secret,
            radius_m=args.radius_m, pixel_size=args.pixel_size,
        )
    except ImageryFetchError as exc:
        raise SystemExit(f"Fetch failed honestly: {exc}")

    with open(out_path, "wb") as f:
        f.write(png_bytes)

    print(f"Saved {len(png_bytes):,} bytes to {out_path} -- open it and look.")


if __name__ == "__main__":
    main()
