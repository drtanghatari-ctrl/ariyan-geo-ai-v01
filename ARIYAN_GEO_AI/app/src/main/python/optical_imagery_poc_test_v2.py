"""optical_imagery_poc_test_v2.py -- throwaway POC, not part of the app.
get_access_token logic verified against ndvi_source_mobile.py's real
source. Process API request shape is documentation-grounded, NOT
smoke-tested by me -- if it errors, paste the message back."""

import argparse, json, math, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

EVALSCRIPT = """//VERSION=3
function setup() { return { input: ["B02","B03","B04"], output: { bands: 3 } }; }
function evaluatePixel(s) { return [2.5*s.B04, 2.5*s.B03, 2.5*s.B02]; }
"""

SITES = {
    "al_wihda_tank_farm": (33.150178, 44.649865),
    "aquaculture_ponds": (33.057946, 44.627758),
    "candidate_b": (33.10115, 44.52671),
}


def bbox(lat, lon, r):
    dlat = r / 111320.0
    dlon = r / (111320.0 * max(0.1, abs(math.cos(math.radians(lat)))))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def get_token(cid, secret, timeout=8):
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": cid, "client_secret": secret,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    tok = data.get("access_token")
    if not tok:
        raise RuntimeError(f"No access_token in response: {data}")
    return tok


def fetch_png(lat, lon, cid, secret, radius_m=200.0, px=512, days_back=90, timeout=15):
    token = get_token(cid, secret, timeout=timeout)
    now = datetime.now(timezone.utc)
    t_from = (now - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    t_to = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "input": {
            "bounds": {"bbox": bbox(lat, lon, radius_m),
                       "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"}},
            "data": [{"type": "sentinel-2-l2a",
                      "dataFilter": {"timeRange": {"from": t_from, "to": t_to},
                                     "maxCloudCoverage": 40, "mosaickingOrder": "leastCC"}}],
        },
        "output": {"width": px, "height": px,
                   "responses": [{"identifier": "default", "format": {"type": "image/png"}}]},
        "evalscript": EVALSCRIPT,
    }
    req = urllib.request.Request(PROCESS_URL, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "Accept": "image/png"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--client-id", required=True)
    p.add_argument("--client-secret", required=True)
    p.add_argument("--name", help=f"One of: {', '.join(SITES)}")
    p.add_argument("--lat", type=float)
    p.add_argument("--lon", type=float)
    p.add_argument("--radius-m", type=float, default=200.0)
    p.add_argument("--pixel-size", type=int, default=512)
    p.add_argument("--out", default=None)
    a = p.parse_args()

    if a.name:
        if a.name not in SITES:
            raise SystemExit(f"Unknown --name. Options: {', '.join(SITES)}")
        lat, lon = SITES[a.name]
        label = a.name
    elif a.lat is not None and a.lon is not None:
        lat, lon = a.lat, a.lon
        label = f"{a.lat}_{a.lon}"
    else:
        raise SystemExit("Provide --name or --lat/--lon.")

    out = a.out or f"{label}_{int(a.radius_m)}m_{a.pixel_size}px.png"
    print(f"Fetching {label} ({lat},{lon}) r={a.radius_m}m {a.pixel_size}x{a.pixel_size}px ...")
    try:
        png = fetch_png(lat, lon, a.client_id, a.client_secret, a.radius_m, a.pixel_size)
    except Exception as exc:
        raise SystemExit(f"Fetch failed: {exc}")
    with open(out, "wb") as f:
        f.write(png)
    print(f"Saved {len(png):,} bytes to {out} -- open it and look.")


if __name__ == "__main__":
    main()
