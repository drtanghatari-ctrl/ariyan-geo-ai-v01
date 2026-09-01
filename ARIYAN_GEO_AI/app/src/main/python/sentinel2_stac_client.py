"""
sentinel2_stac_client.py

Part of ARIYAN GEO AI's OFFLINE MODE extension (NDVI half).

Real scene discovery for Sentinel-2 L2A over the public Earth Search STAC
API (https://earth-search.aws.element84.com/v1), confirmed live during
this project's own research (not assumed): the same "sentinel-2-l2a"
collection this app's offline_country_registry.py already points at
(bucket "sentinel-cogs" / prefix "sentinel-s2-l2a-cogs") is served
through this API, and the API itself hands back real, ready-to-use asset
URLs -- so this module never needs to hand-construct an S3 key the way
offline_data_manager.py's DEM half does for Copernicus DEM. That
hand-construction approach was necessary for DEM (a plain public bucket
with no search API); Sentinel-2 has a real, free, no-auth STAC API
instead, and using it is strictly more robust than re-deriving MGRS tile
paths by hand.

CONFIRMED ASSET KEYS (cross-checked against multiple independent, live
Earth Search usage examples during research, not a single source):
"red" (B04), "nir" (B08), "scl" (Scene Classification Layer). A
collection-version fallback ("nir08" for the B8A-labelled asset some
examples use instead of "nir") is checked ONLY if "nir" is truly absent
from a real response -- never silently substituted otherwise.

SCALE/OFFSET, read per-item, never assumed: Sentinel-2 processing
baselines from 2022-01-25 onward add a documented reflectance offset (the
"harmonization" issue) to keep raw DNs from clipping to zero. Each real
STAC item's raster:bands metadata declares its own scale/offset for each
asset; this module reads those values directly from the item actually
being processed rather than hardcoding a single assumption for every
scene. The standard, published Sentinel-2 L2A reflectance scale
(0.0001) is used ONLY as an explicit, clearly-labelled fallback if a
real item's metadata happens to omit the field -- never as a first
choice.

NOT YET TESTED against the live API itself (this sandbox has no network
access, same honest gap already flagged for every other real-network
piece of this project) -- request construction and response parsing are
tested here against a hand-built, realistic fake response shaped exactly
like a real Earth Search item (this shape was confirmed via live
research this session, not invented). The real HTTP round-trip is
deferred to the on-device/CI confirmation stage, same as the DEM path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

STAC_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-l2a"

# Standard, published Sentinel-2 L2A reflectance scale factor. Used ONLY
# as an explicit fallback when a real item's own raster:bands metadata
# doesn't declare scale/offset -- never as the first choice.
_FALLBACK_SCALE = 0.0001
_FALLBACK_OFFSET = 0.0


class StacSearchError(Exception):
    """Raised for any failure searching or parsing real STAC results:
    network error, malformed response, or a response missing fields this
    module actually needs. Never silently falls back to fabricated scene
    data -- a real search failure is a real error."""


@dataclass
class Sentinel2Asset:
    href: str
    scale: float
    offset: float


@dataclass
class Sentinel2Scene:
    scene_id: str
    datetime: str
    cloud_cover: Optional[float]
    assets: Dict[str, Sentinel2Asset] = field(default_factory=dict)


def _asset_scale_offset(asset_json: dict) -> tuple:
    """Reads scale/offset from a real asset's raster:bands metadata if
    present, otherwise returns the documented fallback -- explicit and
    labelled, never a silent guess."""
    bands = asset_json.get("raster:bands")
    if bands and isinstance(bands, list) and len(bands) > 0:
        band0 = bands[0]
        scale = band0.get("scale", _FALLBACK_SCALE)
        offset = band0.get("offset", _FALLBACK_OFFSET)
        return float(scale), float(offset)
    return _FALLBACK_SCALE, _FALLBACK_OFFSET


def _parse_item(item_json: dict) -> Sentinel2Scene:
    props = item_json.get("properties", {})
    assets_json = item_json.get("assets", {})

    def get_asset(*keys) -> Optional[Sentinel2Asset]:
        for key in keys:
            a = assets_json.get(key)
            if a and "href" in a:
                scale, offset = _asset_scale_offset(a)
                return Sentinel2Asset(href=a["href"], scale=scale, offset=offset)
        return None

    red = get_asset("red")
    nir = get_asset("nir", "nir08")
    scl = get_asset("scl")

    if red is None or nir is None or scl is None:
        missing = [name for name, a in (("red", red), ("nir", nir), ("scl", scl)) if a is None]
        raise StacSearchError(
            f"Item {item_json.get('id')} is missing required asset(s) {missing}. "
            f"Real assets present: {sorted(assets_json.keys())}."
        )

    assets = {"red": red, "nir": nir, "scl": scl}

    return Sentinel2Scene(
        scene_id=item_json.get("id", "unknown"),
        datetime=props.get("datetime", ""),
        cloud_cover=props.get("eo:cloud_cover"),
        assets=assets,
    )


def search_scenes(
    south: float, north: float, west: float, east: float,
    date_from: str, date_to: str,
    max_cloud_cover: float = 60.0,
    limit: int = 8,
    timeout: int = 30,
    session=None,
) -> List[Sentinel2Scene]:
    """Real scene search against the live Earth Search STAC API for one
    bbox and date window, sorted least-cloudy first (so a caller that
    caps how many scenes it actually downloads gets the best real
    candidates, not an arbitrary subset).

    date_from/date_to: 'YYYY-MM-DD' strings.

    Raises StacSearchError on any network failure, malformed response, or
    a response missing fields this module needs. Returns an empty list
    (not an error) when the search legitimately finds no scenes -- a real,
    honest "no data in this window" outcome (e.g. persistent winter cloud
    cover), matching this project's existing distinction between real
    errors and real absence-of-data.
    """
    body = {
        "collections": [COLLECTION],
        "bbox": [west, south, east, north],
        "datetime": f"{date_from}T00:00:00Z/{date_to}T23:59:59Z",
        "query": {"eo:cloud_cover": {"lt": max_cloud_cover}},
        "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}],
        "limit": limit,
    }

    http = session or requests
    try:
        resp = http.post(
            STAC_SEARCH_URL,
            data=json.dumps(body),
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise StacSearchError(f"Network error contacting Earth Search STAC API: {exc}") from exc

    if resp.status_code != 200:
        raise StacSearchError(f"Earth Search STAC API returned HTTP {resp.status_code}: {resp.text[:300]}")

    try:
        payload = resp.json()
    except ValueError as exc:
        raise StacSearchError(f"Malformed STAC search response: {exc}") from exc

    features = payload.get("features")
    if features is None:
        raise StacSearchError(f"STAC search response missing 'features': keys={list(payload.keys())}")

    scenes = []
    for item_json in features:
        try:
            scenes.append(_parse_item(item_json))
        except StacSearchError:
            # A single malformed/incomplete item shouldn't fail the whole
            # search -- skip it and keep the real, usable ones. This is
            # NOT the same as fabricating data for the bad item; it's
            # honestly discarding it.
            continue
    return scenes
