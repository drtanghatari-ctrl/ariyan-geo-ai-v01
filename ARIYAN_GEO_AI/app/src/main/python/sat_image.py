"""
sat_image.py -- fi-v2 (2026-10-21): satellite image layers for the Final
Image screen, scientific core.

Real satellite layers can be laid over the fi-v1 terrain image
(fi-v3, 2026-10-29, added TRUE_COLOR):

  TRUE_COLOR  Sentinel-2 L2A red/green/blue (B04/B03/B02) surface
           reflectance, 10 m: a real colour photo of ONE scene, chosen and
           cloud-masked exactly like NDVI. Each band is stored at 8 bits
           (0 .. 0.5 reflectance in 255 steps, 0.002 per step), packed into
           one exact float32 value R*65536 + G*256 + B, so the same
           save-once / crop / Statistical-API self-check path carries it.
           Display only: the picture is contrast-stretched (shown in the
           legend); it is never profiled or used as evidence.

  NDVI     Sentinel-2 L2A, (B08-B04)/(B08+B04), 10 m. ONE clearest scene,
           exact date. Cloud, cloud-shadow, cirrus, snow, saturated and
           no-data cells (scene classification SCL 0,1,3,8,9,10,11) are left
           EMPTY, never filled.
  THERMAL  Landsat 8/9 Level-1 band B10 as TOP-OF-ATMOSPHERE BRIGHTNESS
           TEMPERATURE in kelvin. This is NOT land-surface temperature (CDSE
           only serves Level-1 for Landsat). Delivered on a 30 m grid; the
           sensor itself sees about 100 m. Clouds are NOT masked (scene
           cloud cover is reported instead).
  SAR_VV / SAR_VH
           Sentinel-1 GRD, IW, dual-polarisation, terrain-corrected gamma0,
           shown in dB, 10 m. Raw speckle, no smoothing.

RULES
  * Real data only. Every pixel is a value the server computed from one
    scene; cells it could not compute stay NaN (transparent).
  * Images are requested in EPSG:4326 on a regular grid at about the
    sensor's pixel size, with NEAREST resampling, so no value is ever a
    blend of neighbouring measurements. The grid used is stored with the
    image and drawn as-is.
  * Save-once: each answer is stored under offline_data/sat_image_library/
    with its SHA-256; the identical request is never sent twice, and a saved
    image that contains a smaller window is cropped, not re-fetched.
  * Self-check: the first image of each product is compared against the
    Statistical API for the very same scene, box and grid; the layer is
    only shown once that check has passed (recorded once per version).
  * Images are context only. Nothing here writes a candidate, a review, a
    status or a confidence.

numpy only. Network calls go through an injectable `http` callable so the
tests never touch the network.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import threading
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

FI2_VERSION = "fi-v2"  # unchanged in fi-v2.1 so existing self-check records stay valid
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
CATALOG_URL = "https://sh.dataspace.copernicus.eu/api/v1/catalog/1.0.0/search"
STATISTICS_URL = "https://sh.dataspace.copernicus.eu/statistics/v1"   # as the existing checks
# CRS84 = WGS84 with unambiguous lon/lat order (the same CRS the existing
# NDVI/thermal/SAR statistics checks already use on the phone).
CRS_4326 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
M_PER_DEG_LAT = 111_320.0
NODATA = -9999.0
SEARCH_DAYS = 365
CATALOG_PAGES_MAX = 5
CATALOG_ACCEPT = "application/geo+json"
MAX_SCENE_TRIES = 3
MIN_CLEAR_FRACTION = 0.5
MAX_IMAGE_PX = 2500                 # Process API limit per side
AUTO_HALF_SIZE_M = 1000.0           # fi-v1 default window
AUTO_MARGIN_M = 60.0                # so the DEM window always sits inside
AUTO_CAP = 10                       # candidates per Auto run (tier 0 exempt)
LIBRARY_DIR = "sat_image_library"

# Statuses / bands, as stored in grand_project_review / candidate.
STATUS_SUPPORTED = "SUPPORTED"
STATUS_REJECTED = "REJECTED"
TOP_BANDS = ("HIGH", "SUBSTANTIAL")


class SatImageError(Exception):
    """Any failure to obtain or read a real image. Surfaced, never hidden."""


class SatImageThrottled(SatImageError):
    """HTTP 429 / quota: the caller stops and leaves the rest queued."""

    def __init__(self, msg: str, retry_after_s: Optional[float] = None):
        super().__init__(msg)
        self.retry_after_s = retry_after_s


# --------------------------------------------------------------------------
# Products
# --------------------------------------------------------------------------
# One JavaScript function value(s) per product returns the real value or
# NaN. The image script and the self-check statistics script both call it,
# so the two can only differ in how the answer is delivered.

_JS_NDVI = """
function value(s) {
  if (s.dataMask == 0) return NaN;
  if ([0, 1, 3, 8, 9, 10, 11].indexOf(s.SCL) >= 0) return NaN;
  var d = s.B08 + s.B04;
  if (d == 0) return NaN;
  return (s.B08 - s.B04) / d;
}"""

_JS_THERMAL = """
function value(s) {
  if (s.dataMask == 0) return NaN;
  if (!(s.B10 > 0)) return NaN;
  return s.B10;
}"""


# fi-v3: one exact integer per cell (< 2**24, so float32 holds it exactly)
TC_FULL_SCALE = 0.5          # reflectance mapped to 255
_JS_TRUE_COLOR = """
function q(v) {
  var x = Math.min(Math.max(v, 0), %r) / %r;
  return Math.round(x * 255);
}
function value(s) {
  if (s.dataMask == 0) return NaN;
  if ([0, 1, 3, 8, 9, 10, 11].indexOf(s.SCL) >= 0) return NaN;
  return q(s.B04) * 65536 + q(s.B03) * 256 + q(s.B02);
}""" % (TC_FULL_SCALE, TC_FULL_SCALE)


def _js_sar(band: str) -> str:
    return """
function value(s) {
  if (s.dataMask == 0) return NaN;
  if (!(s.%s > 0)) return NaN;
  return 10 * Math.log(s.%s) / Math.LN10;
}""" % (band, band)


PRODUCTS: Dict[str, Dict[str, Any]] = {
    "TRUE_COLOR": {
        "label": "True colour (Sentinel-2)",
        "collection": "sentinel-2-l2a", "catalog": "sentinel-2-l2a",
        "bands": ["B02", "B03", "B04", "SCL", "dataMask"], "units": None,
        "js": _JS_TRUE_COLOR, "pixel_m": 10.0, "sensor_detail_m": 10.0,
        "unit": "reflectance", "display": None, "ramp": "gray",
        "uses_cloud": True, "kind": "rgb",
        "caption": ("Real colour photo (red, green, blue surface reflectance) from "
                    "ONE Sentinel-2 L2A scene. Contrast stretched for viewing; "
                    "cloud, shadow, cirrus and snow cells are left empty, never "
                    "filled. Visual context only, not evidence."),
        # self-check compares the mean of the packed cell values (~1e6..1e7)
        "tolerance": 1e-5,
    },
    "NDVI": {
        "label": "NDVI (Sentinel-2)",
        "collection": "sentinel-2-l2a", "catalog": "sentinel-2-l2a",
        "bands": ["B04", "B08", "SCL", "dataMask"], "units": None,
        "js": _JS_NDVI, "pixel_m": 10.0, "sensor_detail_m": 10.0,
        "unit": "NDVI", "display": (-0.2, 0.8), "ramp": "ndvi",
        "uses_cloud": True,
        "caption": ("NDVI from ONE Sentinel-2 L2A scene. Cloud, shadow, cirrus "
                    "and snow cells are left empty, never filled."),
        "tolerance": 1e-4,
    },
    "THERMAL": {
        "label": "Brightness temperature (Landsat 8/9)",
        "collection": "landsat-ot-l1", "catalog": "landsat-ot-l1",
        "bands": ["B10", "dataMask"], "units": "BRIGHTNESS_TEMPERATURE",
        "js": _JS_THERMAL, "pixel_m": 30.0, "sensor_detail_m": 100.0,
        "unit": "K", "display": None, "ramp": "thermal",
        "uses_cloud": True,
        "caption": ("Top-of-atmosphere BRIGHTNESS temperature (Landsat band 10, "
                    "Level 1), not ground temperature. 30 m grid, about 100 m "
                    "sensor detail; haze, water vapour and clouds change it. "
                    "Clouds are not masked."),
        "tolerance": 1e-3,
    },
    "SAR_VV": {
        "label": "Radar VV (Sentinel-1)",
        "collection": "sentinel-1-grd", "catalog": "sentinel-1-grd",
        "bands": ["VV", "dataMask"], "units": None,
        "js": _js_sar("VV"), "pixel_m": 10.0, "sensor_detail_m": 20.0,
        "unit": "dB", "display": (-25.0, 0.0), "ramp": "gray",
        "uses_cloud": False,
        "caption": ("Sentinel-1 radar backscatter, VV polarisation, terrain-"
                    "corrected gamma0 in dB. Raw speckle, no smoothing."),
        "tolerance": 1e-3,
    },
    "SAR_VH": {
        "label": "Radar VH (Sentinel-1)",
        "collection": "sentinel-1-grd", "catalog": "sentinel-1-grd",
        "bands": ["VH", "dataMask"], "units": None,
        "js": _js_sar("VH"), "pixel_m": 10.0, "sensor_detail_m": 20.0,
        "unit": "dB", "display": (-30.0, -5.0), "ramp": "gray",
        "uses_cloud": False,
        "caption": ("Sentinel-1 radar backscatter, VH polarisation, terrain-"
                    "corrected gamma0 in dB. Raw speckle, no smoothing."),
        "tolerance": 1e-3,
    },
}
PRODUCT_ORDER = ("NDVI", "THERMAL", "SAR_VV", "SAR_VH")   # Auto run images step (unchanged)
LAYER_ORDER = ("TRUE_COLOR",) + PRODUCT_ORDER             # fi-v3: the Satellite menu


def is_rgb(product: str) -> bool:
    return PRODUCTS[product].get("kind") == "rgb"


def decode_true_color(values: np.ndarray) -> np.ndarray:
    """(H, W) packed cells -> (H, W, 3) reflectance R, G, B; NaN where empty."""
    v = np.asarray(values, dtype=np.float64)
    ok = np.isfinite(v)
    n = np.where(ok, v, 0.0).astype(np.int64)
    rgb = np.stack([(n >> 16) & 255, (n >> 8) & 255, n & 255], axis=-1).astype(np.float64)
    rgb *= TC_FULL_SCALE / 255.0
    rgb[~ok] = np.nan
    return rgb
SAR_PROCESSING = {"orthorectify": True, "backCoeff": "GAMMA0_TERRAIN",
                  "demInstance": "COPERNICUS_30", "upsampling": "NEAREST",
                  "downsampling": "NEAREST"}
SAR_FILTER = {"acquisitionMode": "IW", "polarization": "DV"}   # as sar_source_mobile


def _input_bands(p: Dict) -> str:
    js = json.dumps(p["bands"])
    if p["units"]:                    # same form as thermal_source_mobile
        return '{bands: %s, units: %s}' % (js, json.dumps(p["units"]))
    return '{bands: %s}' % js


def process_evalscript(product: str) -> str:
    p = PRODUCTS[product]
    return ("//VERSION=3\n"
            "function setup() {\n"
            "  return {input: [%s],\n"
            "          output: {bands: 1, sampleType: \"FLOAT32\"}};\n"
            "}%s\n"
            "function evaluatePixel(s) {\n"
            "  var v = value(s);\n"
            "  return [isNaN(v) ? %s : v];\n"
            "}\n") % (_input_bands(p), p["js"], repr(NODATA))


def stats_evalscript(product: str) -> str:
    p = PRODUCTS[product]
    return ("//VERSION=3\n"
            "function setup() {\n"
            "  return {input: [%s],\n"
            "          output: [{id: \"data\", bands: 1, sampleType: \"FLOAT32\"},\n"
            "                   {id: \"dataMask\", bands: 1}]};\n"
            "}%s\n"
            "function evaluatePixel(s) {\n"
            "  var v = value(s);\n"
            "  return {data: [isNaN(v) ? 0 : v], dataMask: [isNaN(v) ? 0 : 1]};\n"
            "}\n") % (_input_bands(p), p["js"])


# --------------------------------------------------------------------------
# Geometry: the request grid
# --------------------------------------------------------------------------

def bounds_around(lat: float, lon: float, half_m: float) -> Dict[str, float]:
    dlat = half_m / M_PER_DEG_LAT
    dlon = half_m / (M_PER_DEG_LAT * math.cos(math.radians(lat)))
    return {"west": lon - dlon, "east": lon + dlon, "south": lat - dlat, "north": lat + dlat}


def request_grid(bounds: Dict[str, float], pixel_m: float) -> Dict[str, Any]:
    """A regular EPSG:4326 grid over `bounds` whose pixels are about
    `pixel_m` on the ground. The exact degree size is derived from the
    integer pixel count so the grid tiles the box exactly."""
    w, e, s, n = bounds["west"], bounds["east"], bounds["south"], bounds["north"]
    if not (e > w and n > s):
        raise ValueError("empty bounds")
    lat_c = (s + n) / 2.0
    want_dlat = pixel_m / M_PER_DEG_LAT
    want_dlon = pixel_m / (M_PER_DEG_LAT * math.cos(math.radians(lat_c)))
    width = max(1, int(round((e - w) / want_dlon)))
    height = max(1, int(round((n - s) / want_dlat)))
    if width > MAX_IMAGE_PX or height > MAX_IMAGE_PX:
        raise ValueError(f"window too large for one image ({width}x{height} px)")
    return {"west": w, "east": e, "south": s, "north": n, "width": width, "height": height,
            "dlon": (e - w) / width, "dlat": (n - s) / height}


def _round_bounds(b: Dict[str, float]) -> Dict[str, float]:
    # Requests are keyed byte-for-byte; rounding makes the same window give
    # the same key on every device (1e-7 deg is about 1 cm).
    return {k: round(float(b[k]), 7) for k in ("west", "east", "south", "north")}


# --------------------------------------------------------------------------
# Dates and scene choice
# --------------------------------------------------------------------------

def anchor_day(now: Optional[datetime] = None) -> datetime:
    """Start of the current UTC day: every search made on the same day is
    the identical request, so it is answered once."""
    now = now or datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def catalog_body(product: str, bounds: Dict[str, float], day: datetime,
                 next_token: Optional[int] = None) -> Dict[str, Any]:
    b = _round_bounds(bounds)
    body: Dict[str, Any] = {
        "bbox": [b["west"], b["south"], b["east"], b["north"]],
        "datetime": "%s/%s" % (_iso(day - timedelta(days=SEARCH_DAYS)), _iso(day)),
        "collections": [PRODUCTS[product]["catalog"]],
        "limit": 100,
    }
    if next_token is not None:
        body["next"] = next_token
    return body


def scene_dates(product: str, features: Sequence[Dict]) -> List[Dict[str, Any]]:
    """Ranks the catalog entries into distinct acquisition DAYS.

    Optical (NDVI, thermal): the clearest scene first -- lowest scene cloud
    cover; equal cover goes to the newer day. SAR: newest day first.
    A day with several tiles keeps its lowest cloud cover."""
    days: Dict[str, Dict[str, Any]] = {}
    for f in features or []:
        props = f.get("properties") or {}
        dt = props.get("datetime")
        if not dt:
            continue
        day = dt[:10]
        cc = props.get("eo:cloud_cover")
        cc = float(cc) if isinstance(cc, (int, float)) else None
        cur = days.get(day)
        if cur is None:
            days[day] = {"date": day, "cloud_cover": cc, "scene_ids": [f.get("id")]}
        else:
            cur["scene_ids"].append(f.get("id"))
            if cc is not None and (cur["cloud_cover"] is None or cc < cur["cloud_cover"]):
                cur["cloud_cover"] = cc
    out = list(days.values())
    if PRODUCTS[product]["uses_cloud"]:
        out.sort(key=lambda d: (d["cloud_cover"] if d["cloud_cover"] is not None else 101.0,
                                _neg_date(d["date"])))
    else:
        out.sort(key=lambda d: _neg_date(d["date"]))
    return out


def _neg_date(day: str) -> int:
    return -int(day.replace("-", ""))


# --------------------------------------------------------------------------
# Request bodies
# --------------------------------------------------------------------------

def _data_block(product: str, day: str) -> Dict[str, Any]:
    p = PRODUCTS[product]
    d0 = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    tr = {"from": _iso(d0), "to": _iso(d0 + timedelta(days=1))}
    filt: Dict[str, Any] = {"timeRange": tr, "mosaickingOrder": "leastCC"
                            if p["uses_cloud"] else "mostRecent"}
    block: Dict[str, Any] = {"type": p["collection"], "dataFilter": filt}
    if product.startswith("SAR"):
        filt.update(SAR_FILTER)
        block["processing"] = dict(SAR_PROCESSING)
    else:
        block["processing"] = {"upsampling": "NEAREST", "downsampling": "NEAREST"}
    return block


def process_body(product: str, grid: Dict[str, Any], day: str) -> Dict[str, Any]:
    return {
        "input": {"bounds": {"bbox": [grid["west"], grid["south"], grid["east"], grid["north"]],
                             "properties": {"crs": CRS_4326}},
                  "data": [_data_block(product, day)]},
        "output": {"width": grid["width"], "height": grid["height"],
                   "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}]},
        "evalscript": process_evalscript(product),
    }


def stats_body(product: str, grid: Dict[str, Any], day: str) -> Dict[str, Any]:
    d0 = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return {
        "input": {"bounds": {"bbox": [grid["west"], grid["south"], grid["east"], grid["north"]],
                             "properties": {"crs": CRS_4326}},
                  "data": [_data_block(product, day)]},
        "aggregation": {"timeRange": {"from": _iso(d0), "to": _iso(d0 + timedelta(days=1))},
                        "aggregationInterval": {"of": "P1D"},
                        "resx": grid["dlon"], "resy": grid["dlat"],
                        "evalscript": stats_evalscript(product)},
        "calculations": {"default": {}},
    }


def _body_bytes(body: Dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def request_key(url: str, body: bytes) -> str:
    return hashlib.sha256(url.encode() + b"\n" + body).hexdigest()[:32]


# --------------------------------------------------------------------------
# GeoTIFF reader for single-band images (strips or tiles; none/LZW/deflate;
# predictor 1/2/3; float32/float64/int16/uint16/int32/uint8)
# --------------------------------------------------------------------------

_SAMPLE = {(3, 32): "f4", (3, 64): "f8", (2, 16): "i2", (1, 16): "u2",
           (2, 32): "i4", (1, 32): "u4", (1, 8): "u1", (2, 8): "i1"}


def read_geotiff(data: bytes) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Returns (values float64 (H, W), georef) where georef has west, north,
    dlon, dlat (cell EDGES, i.e. pixel-is-area) and epsg."""
    from srtm_library import _tags, _lzw_decode, LibraryError
    from geotiff_cog_reader import _undo_floatingpoint_predictor

    try:
        bo, t = _tags(data)
    except LibraryError as e:
        raise SatImageError(f"not a readable TIFF: {e}")
    except Exception as e:
        raise SatImageError(f"not a readable TIFF: {type(e).__name__}: {e}")
    W, H = int(t[256][0]), int(t[257][0])
    bps = int(t.get(258, (1,))[0])
    spp = int(t.get(277, (1,))[0])
    comp = int(t.get(259, (1,))[0])
    pred = int(t.get(317, (1,))[0])
    fmt = int(t.get(339, (1,))[0])
    if spp != 1:
        raise SatImageError(f"expected one band, got {spp}")
    if (fmt, bps) not in _SAMPLE:
        raise SatImageError(f"unsupported sample type format={fmt} bits={bps}")
    if comp not in (1, 5, 8, 32946):
        raise SatImageError(f"unsupported compression {comp}")
    dt = np.dtype(bo + _SAMPLE[(fmt, bps)])
    nb = bps // 8

    if 322 in t:                                  # tiled
        tw, th = int(t[322][0]), int(t[323][0])
        offs, cnts = t[324], t[325]
        blocks = [(r, c) for r in range(0, H, th) for c in range(0, W, tw)]
        bw, bh_full = tw, th
    else:                                         # stripped
        rps = int(t.get(278, (H,))[0])
        offs, cnts = t[273], t[279]
        blocks = [(r, 0) for r in range(0, H, rps)]
        bw, bh_full = W, rps
    out = np.empty((H, W), dtype=np.float64)
    for i, (r0, c0) in enumerate(blocks):
        raw = data[offs[i]:offs[i] + cnts[i]]
        if comp in (8, 32946):
            raw = zlib.decompress(raw)
        elif comp == 5:
            raw = _lzw_decode(raw)
        bh = bh_full if 322 in t else min(bh_full, H - r0)
        need = bw * bh * nb
        buf = np.frombuffer(raw[:need], dtype=np.uint8)
        if buf.size < need:
            raise SatImageError("truncated image block")
        if pred == 3:
            vals = _undo_floatingpoint_predictor(buf.reshape(bh, bw * nb)).astype(np.float64)
        else:
            native = buf.view(dt).reshape(bh, bw).astype(dt.newbyteorder("="))
            if pred == 2:                      # integer horizontal differencing
                native = np.cumsum(native, axis=1, dtype=native.dtype)
            vals = native.astype(np.float64)
        rr = min(bh, H - r0)
        cc = min(bw, W - c0)
        out[r0:r0 + rr, c0:c0 + cc] = vals[:rr, :cc]

    if 33550 not in t or 33922 not in t:
        raise SatImageError("image has no georeference")
    sx, sy = float(t[33550][0]), float(t[33550][1])
    ti, tj, tx, ty = float(t[33922][0]), float(t[33922][1]), float(t[33922][3]), float(t[33922][4])
    epsg, raster_type = None, 1
    keys = t.get(34735)
    if keys:
        for k in range(int(keys[3])):
            kid, loc, _, val = keys[4 + 4 * k:8 + 4 * k]
            if loc == 0 and kid in (2048, 3072):
                epsg = int(val)
            if loc == 0 and kid == 1025:
                raster_type = int(val)
    west, north = tx - ti * sx, ty + tj * sy
    if raster_type == 2:                          # PixelIsPoint -> edges
        west, north = west - sx / 2.0, north + sy / 2.0
    return out, {"west": west, "north": north, "dlon": sx, "dlat": sy,
                 "width": W, "height": H, "epsg": epsg}


# --------------------------------------------------------------------------
# HTTP (injectable)
# --------------------------------------------------------------------------

HttpFn = Callable[[str, bytes, Dict[str, str], int], Tuple[int, Dict[str, str], bytes]]


def http_post(url: str, body: bytes, headers: Dict[str, str], timeout: int) -> Tuple[int, Dict[str, str], bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() or b""


def _post(http: HttpFn, url: str, body: bytes, token: str, accept: str, timeout: int):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
               "Accept": accept}
    status, hdr, data = http(url, body, headers, timeout)
    if status == 429:
        ra = hdr.get("retry-after")
        try:
            ra_s = float(ra) if ra is not None else None
        except ValueError:
            ra_s = None
        raise SatImageThrottled("Copernicus rate limit or quota reached (HTTP 429)", ra_s)
    if status != 200:
        raise SatImageError(f"HTTP {status} from {url.rsplit('/', 1)[-1]}: "
                            f"{data[:300].decode('utf-8', 'replace')}")
    return hdr, data


# --------------------------------------------------------------------------
# Save-once library
# --------------------------------------------------------------------------

_lib_lock = threading.Lock()


def _lib(root: str, *parts: str) -> str:
    return os.path.join(root, LIBRARY_DIR, *parts)


def _load_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def _save_bytes(path: str, data: bytes) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return hashlib.sha256(data).hexdigest()


def library_index(root: str, product: str) -> Dict[str, Dict]:
    return _load_json(_lib(root, product, "index.json"), {})


def _read_verified(path: str, sha: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    return data if hashlib.sha256(data).hexdigest() == sha else None


def _cached_post(root: str, kind: str, ext: str, http: HttpFn, url: str, body: Dict,
                 token: Optional[str], accept: str, timeout: int,
                 meta: Optional[Dict] = None) -> Tuple[bytes, Dict, bool]:
    """(data, index entry, reused). Identical request -> served from disk
    after its SHA-256 is re-checked. No token -> offline: only disk."""
    bb = _body_bytes(body)
    key = request_key(url, bb)
    path = _lib(root, kind, key + ext)
    idx = _load_json(_lib(root, kind, "index.json"), {})
    ent = idx.get(key)
    if ent is not None:
        data = _read_verified(path, ent["sha256"])
        if data is not None:
            return data, ent, True
    if not token:
        raise SatImageError("offline and this image was never saved")
    hdr, data = _post(http, url, bb, token, accept, timeout)
    sha = _save_bytes(path, data)
    ent = {"key": key, "sha256": sha, "bytes": len(data), "file": f"{kind}/{key}{ext}",
           "url": url, "request_sha256": hashlib.sha256(bb).hexdigest(),
           "processing_units": _pu(hdr),
           "saved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "version": FI2_VERSION}
    if meta:
        ent.update(meta)
    with _lib_lock:
        idx = _load_json(_lib(root, kind, "index.json"), {})
        idx[key] = ent
        _save_json(_lib(root, kind, "index.json"), idx)
    return data, ent, False


def _pu(hdr: Dict[str, str]) -> Optional[float]:
    v = hdr.get("x-processingunits-spent")
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Finding / fetching an image for a window
# --------------------------------------------------------------------------

def find_saved(root: str, product: str, bounds: Dict[str, float]) -> Optional[Dict]:
    """The newest-saved accepted image of `product` whose box CONTAINS
    `bounds` (so a zoom-in is a crop of an image already on the phone)."""
    best = None
    for ent in library_index(root, product).values():
        if not ent.get("accepted"):
            continue
        g = ent.get("grid") or {}
        tol = 1e-7       # saved boxes are rounded to 1e-7 deg (about 1 cm)
        try:
            if (g["west"] <= bounds["west"] + tol and g["east"] >= bounds["east"] - tol and
                    g["south"] <= bounds["south"] + tol and g["north"] >= bounds["north"] - tol):
                if best is None or ent.get("saved_utc", "") > best.get("saved_utc", ""):
                    best = ent
        except KeyError:
            continue
    return best


def load_image(root: str, ent: Dict) -> Dict[str, Any]:
    data = _read_verified(_lib(root, ent["file"]), ent["sha256"])
    if data is None:
        raise SatImageError("saved image is missing or its SHA-256 no longer matches")
    vals, geo = read_geotiff(data)
    vals[vals <= NODATA + 0.5] = np.nan
    vals[~np.isfinite(vals)] = np.nan
    return {"values": vals, "geo": geo, "entry": ent}


def crop(img: Dict[str, Any], bounds: Dict[str, float]) -> Dict[str, Any]:
    """Whole cells that touch `bounds`; never resampled."""
    g = img["geo"]
    v = img["values"]
    c0 = max(0, int(math.floor((bounds["west"] - g["west"]) / g["dlon"] + 1e-9)))
    c1 = min(v.shape[1], int(math.ceil((bounds["east"] - g["west"]) / g["dlon"] - 1e-9)))
    r0 = max(0, int(math.floor((g["north"] - bounds["north"]) / g["dlat"] + 1e-9)))
    r1 = min(v.shape[0], int(math.ceil((g["north"] - bounds["south"]) / g["dlat"] - 1e-9)))
    if c1 <= c0 or r1 <= r0:
        raise SatImageError("window lies outside the saved image")
    geo = dict(g, west=g["west"] + c0 * g["dlon"], north=g["north"] - r0 * g["dlat"],
               width=c1 - c0, height=r1 - r0)
    return {"values": v[r0:r1, c0:c1].copy(), "geo": geo, "entry": img["entry"]}


def clear_fraction(values: np.ndarray) -> float:
    return float(np.isfinite(values).mean()) if values.size else 0.0


def fetch_image(root: str, product: str, bounds: Dict[str, float], token: Optional[str],
                http: HttpFn = http_post, timeout: int = 60,
                day: Optional[datetime] = None) -> Dict[str, Any]:
    """Saved image if one contains `bounds`; otherwise searches the
    catalog, downloads the best scene (up to MAX_SCENE_TRIES days when the
    box is mostly cloud/empty), saves every answer, and returns the chosen
    one. Raises SatImageError / SatImageThrottled."""
    saved = find_saved(root, product, bounds)
    if saved is not None:
        out = crop(load_image(root, saved), bounds)
        out["reused"] = True
        return out
    if not token:
        raise SatImageError("offline: no saved %s image covers this window" % product)
    day = day or anchor_day()
    b = _round_bounds(bounds)
    feats: List[Dict] = []
    nxt = None
    for _ in range(CATALOG_PAGES_MAX):
        body = catalog_body(product, b, day, nxt)
        # the STAC catalog only answers GeoJSON; "application/json" gets HTTP 406
        data, _, _ = _cached_post(root, "CATALOG", ".json", http, CATALOG_URL, body, token,
                                  CATALOG_ACCEPT, timeout)
        ans = json.loads(data.decode("utf-8"))
        feats.extend(ans.get("features") or [])
        nxt = (ans.get("context") or {}).get("next")
        if nxt is None:
            break
    dates = scene_dates(product, feats)
    if not dates:
        raise SatImageError("no %s scene over this window in the last %d days"
                            % (product, SEARCH_DAYS))
    grid = request_grid(b, PRODUCTS[product]["pixel_m"])
    tries: List[Dict] = []
    best = None
    for d in dates[:MAX_SCENE_TRIES]:
        body = process_body(product, grid, d["date"])
        meta = {"product": product, "scene_date": d["date"], "scene_ids": d["scene_ids"],
                "scene_cloud_cover": d["cloud_cover"], "grid": grid,
                "request": body, "accepted": False}
        data, ent, _ = _cached_post(root, product, ".tif", http, PROCESS_URL, body, token,
                                    "image/tiff", timeout, meta)
        img = load_image(root, ent)
        _check_grid(img["geo"], grid)
        cf = clear_fraction(img["values"])
        tries.append({"date": d["date"], "clear_fraction": round(cf, 4),
                      "cloud_cover": d["cloud_cover"], "key": ent["key"]})
        if best is None or cf > best[1]:
            best = (img, cf)
        if cf >= MIN_CLEAR_FRACTION:
            break
    img, cf = best
    if cf == 0.0:
        raise SatImageError("%s: the tried scenes have no usable cell in this window (%s)"
                            % (product, ", ".join(t["date"] for t in tries)))
    _mark(root, product, img["entry"]["key"], {"accepted": True, "clear_fraction": round(cf, 4),
                                               "tries": tries})
    img["entry"] = dict(img["entry"], accepted=True, clear_fraction=round(cf, 4), tries=tries)
    out = crop(img, bounds)
    out["reused"] = False
    return out


def _check_grid(geo: Dict, grid: Dict) -> None:
    ok = (geo["width"] == grid["width"] and geo["height"] == grid["height"] and
          abs(geo["west"] - grid["west"]) < grid["dlon"] * 1e-3 and
          abs(geo["north"] - grid["north"]) < grid["dlat"] * 1e-3 and
          abs(geo["dlon"] - grid["dlon"]) < grid["dlon"] * 1e-6 and
          abs(geo["dlat"] - grid["dlat"]) < grid["dlat"] * 1e-6)
    if geo.get("epsg") not in (None, 4326):
        ok = False
    if not ok:
        raise SatImageError("server image grid does not match the requested grid")


def _mark(root: str, product: str, key: str, fields: Dict) -> None:
    with _lib_lock:
        idx = library_index(root, product)
        if key in idx:
            idx[key].update(fields)
            _save_json(_lib(root, product, "index.json"), idx)


# --------------------------------------------------------------------------
# Self-check against the Statistical API
# --------------------------------------------------------------------------

def self_check_record(root: str, product: str) -> Optional[Dict]:
    return _load_json(_lib(root, "self_check.json"), {}).get(f"{FI2_VERSION}:{product}")


def compare_stats(values: np.ndarray, stats_json: Dict, tolerance: float) -> Dict[str, Any]:
    """Mean and valid-cell count of the decoded image versus the
    Statistical API answer for the identical scene, box and grid."""
    st = None
    for iv in stats_json.get("data") or []:
        s = (((iv.get("outputs") or {}).get("data") or {}).get("bands") or {}).get("B0", {}).get("stats")
        if s and (s.get("sampleCount", 0) or 0) - (s.get("noDataCount", 0) or 0) > 0:
            st = s
            break
    finite = values[np.isfinite(values)]
    img_n, img_mean = int(finite.size), (float(finite.mean()) if finite.size else None)
    if st is None:
        return {"pass": False, "reason": "statistics answer has no valid cells",
                "image_mean": img_mean, "image_count": img_n}
    api_n = int(st["sampleCount"]) - int(st.get("noDataCount", 0) or 0)
    api_mean = float(st["mean"])
    tol = tolerance * max(1.0, abs(api_mean))
    count_ok = abs(api_n - img_n) <= max(1, int(0.001 * api_n))
    mean_ok = img_mean is not None and abs(img_mean - api_mean) <= tol
    return {"pass": bool(count_ok and mean_ok), "image_mean": img_mean, "api_mean": api_mean,
            "image_count": img_n, "api_count": api_n, "tolerance": tol,
            "reason": None if (count_ok and mean_ok) else
            ("cell count differs" if not count_ok else "mean differs")}


def run_self_check(root: str, product: str, img: Dict[str, Any], token: str,
                   http: HttpFn = http_post, timeout: int = 60) -> Dict[str, Any]:
    """Uses the FULL saved image (not a crop), so the cell sets are identical."""
    ent = img["entry"]
    full = load_image(root, ent)
    body = stats_body(product, ent["grid"], ent["scene_date"])
    data, sent, _ = _cached_post(root, "STATS_CHECK", ".json", http, STATISTICS_URL, body,
                                 token, "application/json", timeout)
    res = compare_stats(full["values"], json.loads(data.decode("utf-8")),
                        PRODUCTS[product]["tolerance"])
    res.update({"product": product, "image_key": ent["key"], "scene_date": ent["scene_date"],
                "stats_file": sent["file"], "stats_sha256": sent["sha256"],
                "saved_utc": ent.get("saved_utc"), "checked_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "version": FI2_VERSION})
    with _lib_lock:
        rec = _load_json(_lib(root, "self_check.json"), {})
        rec[f"{FI2_VERSION}:{product}"] = res
        _save_json(_lib(root, "self_check.json"), rec)
    return res


def layer_allowed(root: str, product: str, image_key: Optional[str] = None) -> Tuple[bool, str]:
    """The self-check is a ONE-TIME check of the processing pipeline for a
    product, run on one reference image.  fi-v2.1: the returned text names
    which image was checked and when, and never implies that a different
    image was itself checked."""
    r = self_check_record(root, product)
    if r is None:
        return False, "not yet checked against the Statistical API"
    if not r.get("pass"):
        return False, "self-check failed (%s); layer hidden" % r.get("reason")
    idx = library_index(root, product)
    ref_key = r.get("image_key") or ""
    ref_saved = r.get("saved_utc") or (idx.get(ref_key) or {}).get("saved_utc")
    checked = (r.get("checked_utc") or "?")[:10]
    if image_key and image_key == ref_key:
        return True, "self-check passed on this image (checked %s)" % checked
    msg = "pipeline self-check passed %s on reference scene %s (saved %s)" % (
        checked, r.get("scene_date") or "?", (ref_saved or "?")[:10])
    if image_key:
        cur = idx.get(image_key) or {}
        msg += "; this scene %s (saved %s) uses the same pipeline, not checked on its own" % (
            cur.get("scene_date") or "?", (cur.get("saved_utc") or "?")[:10])
    return True, msg


def ensure_layer(root: str, product: str, bounds: Dict[str, float], token: Optional[str],
                 http: HttpFn = http_post, timeout: int = 60) -> Dict[str, Any]:
    """fetch_image + the one-time self-check. Returns the image dict with
    'allowed' and 'check' fields."""
    img = fetch_image(root, product, bounds, token, http, timeout)
    key = (img.get("entry") or {}).get("key")
    ok, why = layer_allowed(root, product, key)
    if self_check_record(root, product) is None and token:
        run_self_check(root, product, img, token, http, timeout)
        ok, why = layer_allowed(root, product, key)
    img["allowed"], img["check"] = ok, why
    return img


# --------------------------------------------------------------------------
# Picture
# --------------------------------------------------------------------------

RAMPS = {
    "ndvi": np.array([[0.00, 140, 81, 10], [0.25, 216, 179, 101], [0.45, 246, 232, 195],
                      [0.60, 199, 234, 229], [0.75, 90, 180, 172], [1.00, 1, 102, 94]]),
    "thermal": np.array([[0.00, 49, 54, 149], [0.25, 116, 173, 209], [0.50, 255, 255, 191],
                         [0.75, 244, 109, 67], [1.00, 165, 0, 38]]),
    "gray": np.array([[0.0, 0, 0, 0], [1.0, 255, 255, 255]]),
}


def display_range(product: str, values: np.ndarray) -> Tuple[float, float]:
    if is_rgb(product):
        # fi-v3: ONE stretch for all three bands, so colour balance is kept
        values = decode_true_color(values)
    fixed = PRODUCTS[product]["display"]
    if fixed is not None:
        return fixed
    f = values[np.isfinite(values)]
    if f.size == 0:
        return 0.0, 1.0
    lo, hi = float(np.percentile(f, 2)), float(np.percentile(f, 98))
    return (lo, hi) if hi > lo else (lo - 0.5, hi + 0.5)


def colorize(product: str, values: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    if is_rgb(product):
        rgb = decode_true_color(values)
        ok = np.isfinite(rgb[..., 0])
        t = np.clip((np.where(np.isfinite(rgb), rgb, 0.0) - vmin) / (vmax - vmin), 0.0, 1.0)
        out = np.zeros(values.shape + (4,), dtype=np.uint8)
        out[..., :3] = np.round(t * 255.0)
        out[..., 3] = np.where(ok, 255, 0)
        out[~ok] = 0
        return out
    ramp = RAMPS[PRODUCTS[product]["ramp"]]
    t = np.clip((values - vmin) / (vmax - vmin), 0.0, 1.0)
    rgba = np.zeros(values.shape + (4,), dtype=np.uint8)
    ok = np.isfinite(values)
    for ch in range(3):
        rgba[..., ch] = np.round(np.interp(np.where(ok, t, 0.0), ramp[:, 0], ramp[:, ch + 1]))
    rgba[..., 3] = np.where(ok, 255, 0)
    rgba[~ok] = 0
    return rgba


def layer_payload(product: str, img: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the screen needs besides the pixels."""
    v = img["values"]
    g = img["geo"]
    ent = img["entry"]
    p = PRODUCTS[product]
    vmin, vmax = display_range(product, v)
    f = decode_true_color(v) if is_rgb(product) else v   # fi-v3: real reflectance, not packed
    f = f[np.isfinite(f)]
    lat_c = g["north"] - g["height"] * g["dlat"] / 2.0
    return {
        "product": product, "label": p["label"], "unit": p["unit"], "caption": p["caption"],
        "kind": p.get("kind", "value"),
        "scene_date": ent.get("scene_date"), "scene_cloud_cover": ent.get("scene_cloud_cover"),
        "clear_fraction_window": round(clear_fraction(v), 4),
        "pixel_m": p["pixel_m"], "sensor_detail_m": p["sensor_detail_m"],
        "grid": {"west": g["west"], "north": g["north"], "dlon": g["dlon"], "dlat": g["dlat"],
                 "width": int(v.shape[1]), "height": int(v.shape[0]),
                 "cell_dx_m": g["dlon"] * M_PER_DEG_LAT * math.cos(math.radians(lat_c)),
                 "cell_dy_m": g["dlat"] * M_PER_DEG_LAT},
        "legend": {"ramp": RAMPS[p["ramp"]].tolist(), "vmin": vmin, "vmax": vmax,
                   "data_min": float(f.min()) if f.size else None,
                   "data_max": float(f.max()) if f.size else None},
        "provenance": {"file": ent.get("file"), "sha256": ent.get("sha256"),
                       "url": ent.get("url"), "scene_ids": ent.get("scene_ids"),
                       "request_sha256": ent.get("request_sha256"),
                       "saved_utc": ent.get("saved_utc"), "tries": ent.get("tries"),
                       "resampling": "NEAREST (EPSG:4326 grid)", "version": FI2_VERSION},
        "reused": bool(img.get("reused")),
        "allowed": bool(img.get("allowed", True)), "check": img.get("check"),
    }


# --------------------------------------------------------------------------
# Auto-run queue: strongest candidates first
# --------------------------------------------------------------------------

BAND_RANK = {"HIGH": 0, "SUBSTANTIAL": 1, "MODERATE": 2, "LOW": 3}


def queue_order(candidates: Sequence[Dict], strong_threshold: Optional[float]) -> List[Dict]:
    """Orders candidates from strongest to weakest and keeps only those
    the agreed rules queue:

      tier 0  confidence HIGH / SUBSTANTIAL        (not counted in the cap)
      tier 1  review status Supported
      tier 2  confidence MODERATE, not Supported
    Rejected candidates are never queued.

    Inside a tier: higher confidence band first (HIGH > SUBSTANTIAL >
    MODERATE > LOW), then higher stored confidence, then calib-v1 strong
    (|z| >= threshold) first, then larger |z|, then id (stable).
    Each returned dict gains 'tier', 'calib_strong' and 'rank' (1 = strongest)."""
    out = []
    seen = set()
    for c in candidates:
        cid = str(c.get("id"))
        if cid in seen:            # a candidate joined to several tiles
            continue
        seen.add(cid)
        status = (c.get("status") or "").upper()
        band = (c.get("confidence_band") or "").upper()
        if status == STATUS_REJECTED:
            continue
        if band in TOP_BANDS:
            tier = 0
        elif status == STATUS_SUPPORTED:
            tier = 1
        elif band == "MODERATE":
            tier = 2
        else:
            continue
        try:
            z = abs(float(c.get("score")))
        except (TypeError, ValueError):
            z = 0.0
        strong = strong_threshold is not None and z >= float(strong_threshold)
        d = dict(c, tier=tier, calib_strong=strong, abs_z=z)
        out.append(d)
    out.sort(key=lambda d: (d["tier"], BAND_RANK.get((d.get("confidence_band") or "").upper(), 9),
                            -(d.get("confidence_numeric") or 0.0),
                            0 if d["calib_strong"] else 1, -d["abs_z"], str(d.get("id"))))
    for i, d in enumerate(out, 1):
        d["rank"] = i
    return out


def auto_bounds(c: Dict) -> Dict[str, float]:
    return bounds_around(float(c["lat"]), float(c["lon"]), AUTO_HALF_SIZE_M + AUTO_MARGIN_M)


def candidate_done(root: str, c: Dict) -> bool:
    b = auto_bounds(c)
    return all(find_saved(root, p, b) is not None for p in PRODUCT_ORDER)


def fetch_queue(root: str, queue: Sequence[Dict], token: str, http: HttpFn = http_post,
                deadline: Optional[float] = None, cap: int = AUTO_CAP,
                timeout: int = 60, log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Works down `queue` (already strongest-first). Tier 0 never counts
    against `cap`. Stops at a 429/quota or at `deadline`; what is left
    stays queued for the next run. One candidate's failure never stops the
    others and never raises."""
    summary: Dict[str, Any] = {"fetched": [], "already": 0, "failed": [], "counted": 0,
                               "stopped": None, "remaining": 0, "order": []}
    # never trust the caller's order blindly: queue_order's rank wins
    # (stable sort, so a queue without ranks keeps its own order)
    queue = sorted(queue, key=lambda c: c.get("rank", 0))
    for c in queue:
        if deadline is not None and time.time() >= deadline:
            summary["stopped"] = "time"
            break
        if candidate_done(root, c):
            summary["already"] += 1
            continue
        if c["tier"] > 0 and summary["counted"] >= cap:
            summary["stopped"] = "cap"
            break
        summary["order"].append(c["id"])
        if c["tier"] > 0:
            summary["counted"] += 1
        b = auto_bounds(c)
        errs = []
        try:
            for p in PRODUCT_ORDER:
                try:
                    ensure_layer(root, p, b, token, http, timeout)
                except SatImageThrottled:
                    raise
                except Exception as e:
                    errs.append(f"{p}: {e}")
        except SatImageThrottled as e:
            summary["stopped"] = "throttled"
            summary["failed"].append({"id": c["id"], "error": str(e)})
            if log:
                log(f"images: stopped at {c['id'][:8]} -- {e}")
            break
        if errs:
            summary["failed"].append({"id": c["id"], "error": "; ".join(errs)})
        else:
            summary["fetched"].append(c["id"])
        if log:
            log(f"images: {c['id'][:8]} tier {c['tier']} -> "
                f"{'ok' if not errs else '; '.join(errs)}")
    summary["remaining"] = sum(1 for c in queue if not candidate_done(root, c))
    return summary
