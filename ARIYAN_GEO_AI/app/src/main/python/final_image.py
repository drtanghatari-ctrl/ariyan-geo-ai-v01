"""
final_image.py -- fi-v1 (2026-10-16): the Final Image engine, scientific core.

First piece of the Final Assessment page ("Scientific Image Processing").
Builds a Surfer-style terrain image from the REAL offline DEM tile only.

RULES (from the user's handoff and the project rules):
  * Real data only. No synthetic fill, no invented detail. Cells the DEM
    does not cover stay transparent (NaN), never guessed.
  * Zoom never fabricates detail. Two display modes:
      - "cells"  (DEFAULT, user decision 2026-10-15): every DEM measurement
        is drawn as a crisp square at any zoom -- nearest cell, no blur.
      - "smooth": bilinear interpolation between measurements, labelled.
    The native pixel size travels with every render so the screen can show
    "native 30 m".
  * The view is re-rendered from the source grid for whatever window is on
    screen; a fixed picture is never stretched.
  * Lines and text (grid, contours, candidate outlines, labels) are returned
    as VECTOR data in grid-pixel coordinates, so Android draws them at screen
    resolution -- sharp at any zoom.
  * The picture never changes a candidate's status or confidence: candidate
    styling is read from the stored values and passed through unchanged.
  * Every export carries a provenance record (source tile SHA-256, method,
    parameters, output SHA-256).

numpy only (the phone has no scipy/matplotlib/Pillow).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

FI_VERSION = "fi-v1"
DISPLAY_MODES = ("cells", "smooth")
DEFAULT_MODE = "cells"
DEFAULT_AZIMUTHS = (225.0, 270.0, 315.0, 360.0)
DEFAULT_ALTITUDE = 45.0
M_PER_DEG_LAT = 111_320.0
MAX_WINDOW_CELLS = 2048 * 2048     # guard against runaway memory on phones
MAX_OUTPUT_PIXELS = 4096 * 4096


# --------------------------------------------------------------------------
# Grid
# --------------------------------------------------------------------------

@dataclass
class Grid:
    """A window of real DEM measurements on the tile's own lattice.

    values[r, c] is the measurement at the cell CENTRE
        lon = west + (c + 0.5) * dlon,  lat = north - (r + 0.5) * dlat
    so a cell's edges are exactly the geographic bounds of the square drawn
    in "cells" mode."""
    values: np.ndarray            # (H, W) float64, NaN = no measurement
    west: float
    north: float
    dlon: float
    dlat: float
    source: str
    source_sha256: str = ""
    notes: List[str] = field(default_factory=list)

    @property
    def shape(self) -> Tuple[int, int]:
        return self.values.shape

    @property
    def centre_lat(self) -> float:
        return self.north - self.values.shape[0] * self.dlat / 2.0

    def cell_size_m(self) -> Tuple[float, float]:
        """(east-west, north-south) cell size in metres at the window centre."""
        dy = self.dlat * M_PER_DEG_LAT
        dx = self.dlon * M_PER_DEG_LAT * math.cos(math.radians(self.centre_lat))
        return dx, dy

    def native_resolution_m(self) -> float:
        dx, dy = self.cell_size_m()
        return round(max(dx, dy), 1)

    def lonlat_to_pixel(self, lon: float, lat: float) -> Tuple[float, float]:
        """Continuous grid-pixel coordinates (x right, y down); (0,0) is the
        north-west corner of cell (0,0)."""
        return (lon - self.west) / self.dlon, (self.north - lat) / self.dlat

    def pixel_to_lonlat(self, x: float, y: float) -> Tuple[float, float]:
        return self.west + x * self.dlon, self.north - y * self.dlat


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_dem_window(storage_folder: str, offline_data_root: str,
                    lat: float, lon: float, half_size_m: float) -> Grid:
    """Reads a square window (about 2*half_size_m wide) of the saved offline
    DEM tile around (lat, lon), on the tile's own pixel lattice -- no
    resampling. Raises FileNotFoundError if the tile is not saved. A window
    that runs past the tile edge is clipped (noted), never filled."""
    import offline_dem_store as ods

    if half_size_m <= 0:
        raise ValueError("half_size_m must be positive")
    path = ods.local_tile_path(storage_folder, offline_data_root, lat, lon)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"no saved DEM tile for {lat:.5f}, {lon:.5f}")
    tile = ods._get_cached_tile(path)
    g = tile.georef()
    sx, sy = g["scale_x"], g["scale_y"]
    # Copernicus tiles are PixelIsPoint: the tiepoint is a pixel CENTRE.
    tie_lon, tie_lat = g["tie_lon"], g["tie_lat"]
    col_c = (lon - tie_lon) / sx
    row_c = (tie_lat - lat) / sy
    half_c = half_size_m / (sx * M_PER_DEG_LAT * math.cos(math.radians(lat)))
    half_r = half_size_m / (sy * M_PER_DEG_LAT)
    c0 = int(math.floor(col_c - half_c)); c1 = int(math.ceil(col_c + half_c))
    r0 = int(math.floor(row_c - half_r)); r1 = int(math.ceil(row_c + half_r))
    notes: List[str] = []
    cc0, cc1 = max(c0, 0), min(c1, g["width"] - 1)
    rr0, rr1 = max(r0, 0), min(r1, g["height"] - 1)
    if (cc0, cc1, rr0, rr1) != (c0, c1, r0, r1):
        notes.append("window clipped at the DEM tile edge (no data beyond it is shown)")
    if cc1 < cc0 or rr1 < rr0:
        raise ValueError("window lies outside the saved DEM tile")
    h, w = rr1 - rr0 + 1, cc1 - cc0 + 1
    if h * w > MAX_WINDOW_CELLS:
        raise ValueError(f"window too large ({h}x{w} cells)")
    cols = np.arange(cc0, cc1 + 1, dtype=np.float64)
    rows = np.arange(rr0, rr1 + 1, dtype=np.float64)
    lons = tie_lon + cols * sx
    lats = tie_lat - rows * sy
    LON, LAT = np.meshgrid(lons, lats)
    vals = tile.get_elevations(LON, LAT).astype(np.float64)
    vals[vals <= -1000] = np.nan          # nodata sentinels are never values
    return Grid(values=vals,
                west=float(lons[0] - sx / 2.0), north=float(lats[0] + sy / 2.0),
                dlon=float(sx), dlat=float(sy),
                source=f"offline DEM tile {os.path.basename(path)}",
                source_sha256=_sha256_file(path), notes=notes)


def validate(grid: Grid) -> List[str]:
    """Problems that make the image untrustworthy. Empty list = fine."""
    v = grid.values
    out: List[str] = []
    if v.ndim != 2 or min(v.shape) < 3:
        return ["window smaller than 3x3 cells"]
    finite = np.isfinite(v)
    frac = finite.mean()
    if frac == 0:
        return ["no DEM measurements in this window"]
    if frac < 0.9:
        out.append(f"only {frac:.0%} of cells have DEM measurements")
    vf = v[finite]
    if float(vf.max() - vf.min()) == 0.0:
        out.append("terrain is perfectly flat in this window (no relief to show)")
    if vf.min() < -450 or vf.max() > 9000:
        out.append("elevations outside the physically plausible range")
    return out


# --------------------------------------------------------------------------
# Terrain products (all derived from the DEM, never new information)
# --------------------------------------------------------------------------

def _filled(z: np.ndarray) -> np.ndarray:
    """NaN cells replaced by the window mean ONLY for computing neighbours'
    gradients; those cells are masked out of every product afterwards."""
    if np.isfinite(z).all():
        return z
    m = np.nanmean(z)
    return np.where(np.isfinite(z), z, m)


def horn_gradients(z: np.ndarray, dx: float, dy: float) -> Tuple[np.ndarray, np.ndarray]:
    """Horn (1981) gradients with separate x/y cell sizes (geographic grids
    are not square in metres). dz/dx east-positive, dz/dy SOUTH-positive."""
    zp = np.pad(_filled(z), 1, mode="edge")
    z1, z2, z3 = zp[:-2, :-2], zp[:-2, 1:-1], zp[:-2, 2:]
    z4, z6 = zp[1:-1, :-2], zp[1:-1, 2:]
    z7, z8, z9 = zp[2:, :-2], zp[2:, 1:-1], zp[2:, 2:]
    gx = ((z3 + 2 * z6 + z9) - (z1 + 2 * z4 + z7)) / (8.0 * dx)
    gy = ((z7 + 2 * z8 + z9) - (z1 + 2 * z2 + z3)) / (8.0 * dy)
    return gx, gy


def slope_deg(z: np.ndarray, dx: float, dy: float) -> np.ndarray:
    gx, gy = horn_gradients(z, dx, dy)
    s = np.degrees(np.arctan(np.hypot(gx, gy)))
    return np.where(np.isfinite(z), s, np.nan)


def hillshade(z: np.ndarray, dx: float, dy: float,
              azimuth_deg: float = 315.0, altitude_deg: float = DEFAULT_ALTITUDE) -> np.ndarray:
    """gdaldem-equivalent analytical hillshade, 0..1 (NaN where no data)."""
    gx, gy = horn_gradients(z, dx, dy)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(gy, -gx)
    az = math.radians(360.0 - azimuth_deg + 90.0)
    alt = math.radians(altitude_deg)
    s = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    return np.where(np.isfinite(z), np.clip(s, 0.0, 1.0), np.nan)


def hillshade_multi(z: np.ndarray, dx: float, dy: float,
                    azimuths: Sequence[float] = DEFAULT_AZIMUTHS,
                    altitude_deg: float = DEFAULT_ALTITUDE) -> np.ndarray:
    """Mean of hillshades from several sun directions, so features of every
    orientation show (a single sun hides features parallel to it)."""
    if not azimuths:
        raise ValueError("at least one azimuth is required")
    acc = np.zeros(z.shape)
    for a in azimuths:
        acc += np.nan_to_num(hillshade(z, dx, dy, a, altitude_deg))
    return np.where(np.isfinite(z), acc / len(azimuths), np.nan)


def _box_mean(z: np.ndarray, rr: int, rc: int) -> np.ndarray:
    """NaN-aware (2rr+1)x(2rc+1) moving mean via summed-area tables."""
    finite = np.isfinite(z)
    v = np.where(finite, z, 0.0)
    n = finite.astype(np.float64)

    def box(a):
        p = np.pad(a, ((rr + 1, rr), (rc + 1, rc)), mode="constant")
        s = p.cumsum(0).cumsum(1)
        h, w = a.shape
        return (s[2 * rr + 1:2 * rr + 1 + h, 2 * rc + 1:2 * rc + 1 + w]
                - s[:h, 2 * rc + 1:2 * rc + 1 + w]
                - s[2 * rr + 1:2 * rr + 1 + h, :w]
                + s[:h, :w])
    num, den = box(v), box(n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def local_relief(z: np.ndarray, dx: float, dy: float, radius_m: float = 300.0) -> np.ndarray:
    """Local Relief Model: elevation minus its neighbourhood mean (metres).
    Positive = higher than surroundings (mounds), negative = hollows."""
    rc = max(1, int(round(radius_m / dx)))
    rr = max(1, int(round(radius_m / dy)))
    return np.where(np.isfinite(z), z - _box_mean(z, rr, rc), np.nan)


# --------------------------------------------------------------------------
# Colour
# --------------------------------------------------------------------------

# "Terrain (Custom)" ramp: blue -> cyan -> green -> yellow -> orange -> red
RAMP_TERRAIN = np.array([
    [0.00, 30, 60, 200], [0.20, 0, 170, 230], [0.40, 40, 190, 90],
    [0.60, 230, 220, 50], [0.80, 240, 140, 30], [1.00, 210, 30, 30],
], dtype=np.float64)


def colorize(values: np.ndarray, vmin: float, vmax: float,
             ramp: np.ndarray = RAMP_TERRAIN) -> np.ndarray:
    """values -> uint8 RGB (H, W, 3). NaN -> 0 (masked by alpha later)."""
    span = (vmax - vmin) or 1.0
    t = np.clip((np.nan_to_num(values, nan=vmin) - vmin) / span, 0.0, 1.0)
    out = np.empty(values.shape + (3,), dtype=np.uint8)
    for ch in range(3):
        out[..., ch] = np.rint(np.interp(t, ramp[:, 0], ramp[:, ch + 1])).astype(np.uint8)
    return out


def robust_range(values: np.ndarray, lo_pct: float = 2.0, hi_pct: float = 98.0) -> Tuple[float, float]:
    v = values[np.isfinite(values)]
    if v.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(v, [lo_pct, hi_pct])
    if hi <= lo:
        lo, hi = float(v.min()), float(v.max())
        if hi <= lo:
            hi = lo + 1.0
    return float(lo), float(hi)


def compose(z: np.ndarray, dx: float, dy: float, *, colour_by: str = "relief",
            relief_radius_m: float = 300.0, shade_strength: float = 0.65,
            azimuths: Sequence[float] = DEFAULT_AZIMUTHS) -> Tuple[np.ndarray, Dict]:
    """Surfer-style composite: colour (local relief or elevation) modulated by
    the multidirectional hillshade. Returns (RGBA uint8 (H,W,4), legend)."""
    if colour_by not in ("relief", "elevation"):
        raise ValueError("colour_by must be 'relief' or 'elevation'")
    shade = hillshade_multi(z, dx, dy, azimuths)
    if colour_by == "relief":
        layer = local_relief(z, dx, dy, relief_radius_m)
        lo, hi = robust_range(layer)
        m = max(abs(lo), abs(hi))
        lo, hi = -m, m
        units = "m relative to surroundings"
    else:
        layer = z
        lo, hi = robust_range(z)
        units = "m elevation"
    rgb = colorize(layer, lo, hi).astype(np.float64)
    k = (1.0 - shade_strength) + shade_strength * np.nan_to_num(shade, nan=1.0)
    rgb = np.clip(rgb * k[..., None], 0, 255)
    rgba = np.zeros(z.shape + (4,), dtype=np.uint8)
    rgba[..., :3] = np.rint(rgb).astype(np.uint8)
    rgba[..., 3] = np.where(np.isfinite(z), 255, 0)
    legend = {"colour_by": colour_by, "min": round(lo, 2), "max": round(hi, 2),
              "units": units, "ramp": "Terrain (Custom)",
              "hillshade_azimuths": list(azimuths), "hillshade_altitude": DEFAULT_ALTITUDE,
              "relief_radius_m": relief_radius_m if colour_by == "relief" else None}
    return rgba, legend


# --------------------------------------------------------------------------
# Zoom: re-render a window of the grid at screen size, never stretch a picture
# --------------------------------------------------------------------------

def render_view(image: np.ndarray, x0: float, y0: float, x1: float, y1: float,
                out_w: int, out_h: int, mode: str = DEFAULT_MODE) -> np.ndarray:
    """Re-renders grid-pixel window [x0,x1) x [y0,y1) (continuous grid-pixel
    coordinates, may be fractional) into an out_w x out_h RGBA image.

    "cells": each output pixel takes the cell it falls in -> every DEM
             measurement is a crisp square at any zoom (no blur, no invented
             detail). Outside the grid = transparent.
    "smooth": bilinear between cell centres (labelled as interpolated)."""
    if mode not in DISPLAY_MODES:
        raise ValueError(f"mode must be one of {DISPLAY_MODES}")
    if out_w <= 0 or out_h <= 0 or out_w * out_h > MAX_OUTPUT_PIXELS:
        raise ValueError("bad output size")
    if not (x1 > x0 and y1 > y0):
        raise ValueError("empty view window")
    h, w = image.shape[:2]
    chans = image.shape[2] if image.ndim == 3 else 1
    img = image.reshape(h, w, chans)
    xs = x0 + (np.arange(out_w) + 0.5) * (x1 - x0) / out_w
    ys = y0 + (np.arange(out_h) + 0.5) * (y1 - y0) / out_h
    out = np.zeros((out_h, out_w, chans), dtype=image.dtype)
    if mode == "cells":
        ci = np.floor(xs).astype(np.int64)
        ri = np.floor(ys).astype(np.int64)
        okx = (ci >= 0) & (ci < w)
        oky = (ri >= 0) & (ri < h)
        sub = img[np.clip(ri, 0, h - 1)][:, np.clip(ci, 0, w - 1)]
        mask = oky[:, None] & okx[None, :]
        out[mask] = sub[mask]
    else:
        fx = np.clip(xs - 0.5, 0, w - 1)
        fy = np.clip(ys - 0.5, 0, h - 1)
        ix = np.minimum(np.floor(fx).astype(np.int64), w - 2) if w > 1 else np.zeros(out_w, np.int64)
        iy = np.minimum(np.floor(fy).astype(np.int64), h - 2) if h > 1 else np.zeros(out_h, np.int64)
        tx = (fx - ix)[None, :, None] if w > 1 else np.zeros((1, out_w, 1))
        ty = (fy - iy)[:, None, None] if h > 1 else np.zeros((out_h, 1, 1))
        ix1 = np.minimum(ix + 1, w - 1)
        iy1 = np.minimum(iy + 1, h - 1)
        f = img.astype(np.float64)
        a = f[iy][:, ix]; b = f[iy][:, ix1]
        c = f[iy1][:, ix]; d = f[iy1][:, ix1]
        val = (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty
        if chans == 4:
            # a cell next to "no data" is not smoothed into it
            alpha_min = np.minimum(np.minimum(a[..., 3], b[..., 3]), np.minimum(c[..., 3], d[..., 3]))
            val[..., 3] = alpha_min
        inside = ((xs >= 0) & (xs < w))[None, :] & ((ys >= 0) & (ys < h))[:, None]
        out[inside] = np.rint(val[inside]).astype(image.dtype)
    return out.reshape((out_h, out_w) + image.shape[2:])


def view_info(grid: Grid, x0: float, x1: float, out_w: int, mode: str) -> Dict:
    """What the screen should state about this view."""
    cells_across = max(x1 - x0, 1e-9)
    px_per_cell = out_w / cells_across
    return {"mode": mode, "native_resolution_m": grid.native_resolution_m(),
            "screen_px_per_cell": round(px_per_cell, 2),
            "label": (f"native {grid.native_resolution_m():g} m"
                      + (" - interpolated" if mode == "smooth" else " - exact cells")),
            "beyond_native": px_per_cell > 1.0}


# --------------------------------------------------------------------------
# Vector layers (drawn by Android at screen resolution)
# --------------------------------------------------------------------------

def nice_interval(span: float, target_lines: int = 12) -> float:
    if span <= 0:
        return 1.0
    raw = span / max(target_lines, 1)
    p = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * p:
            return m * p
    return 10 * p


def contour_segments(z: np.ndarray, level: float) -> List[Tuple[float, float, float, float]]:
    """Marching squares on cell centres. Returns segments (x0,y0,x1,y1) in
    grid-pixel coordinates (cell (r,c) centre = (c+0.5, r+0.5)). Squares
    touching a NaN cell are skipped -- contours never cross missing data."""
    h, w = z.shape
    if h < 2 or w < 2:
        return []
    a = z[:-1, :-1]; b = z[:-1, 1:]; c = z[1:, 1:]; d = z[1:, :-1]   # tl, tr, br, bl
    ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(c) & np.isfinite(d)
    idx = ((a >= level).astype(int) * 8 + (b >= level) * 4 + (c >= level) * 2 + (d >= level) * 1)
    segs: List[Tuple[float, float, float, float]] = []
    rr, cc = np.nonzero(ok & (idx != 0) & (idx != 15))

    def interp(v0, v1):
        return 0.5 if v1 == v0 else (level - v0) / (v1 - v0)

    for r, col in zip(rr.tolist(), cc.tolist()):
        A, B, C, D = a[r, col], b[r, col], c[r, col], d[r, col]
        x, y = col + 0.5, r + 0.5
        top = (x + interp(A, B), y)
        right = (x + 1, y + interp(B, C))
        bottom = (x + interp(D, C), y + 1)
        left = (x, y + interp(A, D))
        k = int(idx[r, col])
        pairs = {1: [(left, bottom)], 2: [(bottom, right)], 3: [(left, right)],
                 4: [(top, right)], 5: [(left, top), (bottom, right)], 6: [(top, bottom)],
                 7: [(left, top)], 8: [(left, top)], 9: [(top, bottom)],
                 10: [(top, right), (left, bottom)], 11: [(top, right)], 12: [(left, right)],
                 13: [(bottom, right)], 14: [(left, bottom)]}[k]
        for p, q in pairs:
            segs.append((p[0], p[1], q[0], q[1]))
    return segs


def contours(z: np.ndarray, interval: Optional[float] = None, max_levels: int = 60) -> Dict:
    v = z[np.isfinite(z)]
    if v.size == 0:
        return {"interval_m": None, "levels": []}
    lo, hi = float(v.min()), float(v.max())
    step = interval or nice_interval(hi - lo)
    first = math.ceil(lo / step) * step
    levels = []
    lev = first
    while lev <= hi and len(levels) < max_levels:
        segs = contour_segments(z, lev)
        if segs:
            levels.append({"level_m": round(lev, 3),
                           "index": abs(round(lev / step)) % 5 == 0,
                           "segments": [[round(s, 3) for s in seg] for seg in segs]})
        lev += step
    return {"interval_m": step, "levels": levels}


def utm_grid(grid: Grid, spacing_m: Optional[float] = None) -> Dict:
    """UTM grid lines (zone of the window centre) as polylines in grid-pixel
    coordinates, with tick labels. Lines are sampled densely enough to stay
    straight-looking on screen."""
    import utm_projection as up
    h, w = grid.shape
    lon_c, lat_c = grid.pixel_to_lonlat(w / 2.0, h / 2.0)
    zone = up.utm_zone_for(lon_c)
    corners = [grid.pixel_to_lonlat(x, y) for x, y in ((0, 0), (w, 0), (0, h), (w, h))]
    pts = [up.utm_forward(la, lo, zone) for lo, la in corners]
    e_min = min(p.easting for p in pts); e_max = max(p.easting for p in pts)
    n_min = min(p.northing for p in pts); n_max = max(p.northing for p in pts)
    step = spacing_m or nice_interval(max(e_max - e_min, n_max - n_min), 6)
    northern = lat_c >= 0
    lines = []

    def poly(fixed, along_lo, along_hi, easting_fixed):
        out = []
        for t in np.linspace(along_lo, along_hi, 24):
            e, n = (fixed, t) if easting_fixed else (t, fixed)
            la, lo = up.utm_inverse(e, n, zone, northern)
            x, y = grid.lonlat_to_pixel(lo, la)
            out.append([round(x, 3), round(y, 3)])
        return out

    e = math.ceil(e_min / step) * step
    while e <= e_max:
        lines.append({"axis": "easting", "value": int(round(e)), "points": poly(e, n_min, n_max, True)})
        e += step
    n = math.ceil(n_min / step) * step
    while n <= n_max:
        lines.append({"axis": "northing", "value": int(round(n)), "points": poly(n, e_min, e_max, False)})
        n += step
    return {"zone": zone, "hemisphere": "N" if northern else "S",
            "spacing_m": step, "datum": "WGS84", "lines": lines}


def scale_bar(grid: Grid, view_cells_across: float, screen_width_px: int) -> Dict:
    """A round-number scale bar about a quarter of the screen wide."""
    dx, _ = grid.cell_size_m()
    m_per_px = view_cells_across * dx / max(screen_width_px, 1)
    length = nice_interval(m_per_px * screen_width_px / 4.0, 1)
    return {"length_m": length, "length_px": round(length / m_per_px, 1)}


# Candidate styling is READ from stored values; the image never changes them.
_CONF_STYLE = {"HIGH": "high", "MODERATE": "moderate", "LOW": "low"}


def candidate_overlay(grid: Grid, candidates: Sequence[Dict]) -> List[Dict]:
    """candidates: dicts with id, lat, lon, status, confidence_label,
    confidence (optional). Returns markers in grid-pixel coordinates; ones
    outside the window are dropped. Style follows the stored confidence
    label; Rejected candidates get their own muted style."""
    h, w = grid.shape
    out = []
    for c in candidates:
        x, y = grid.lonlat_to_pixel(float(c["lon"]), float(c["lat"]))
        if not (0 <= x <= w and 0 <= y <= h):
            continue
        status = str(c.get("status") or "Open")
        label = str(c.get("confidence_label") or "").upper()
        style = "rejected" if status.lower().startswith("rejected") else _CONF_STYLE.get(label, "unrated")
        out.append({"id": str(c["id"]), "x": round(x, 3), "y": round(y, 3),
                    "status": status, "confidence_label": label or None,
                    "confidence": c.get("confidence"), "style": style})
    return out


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

def encode_png(rgba: np.ndarray) -> bytes:
    """Minimal PNG encoder (RGBA 8-bit), pure Python + zlib."""
    if rgba.ndim != 3 or rgba.shape[2] != 4 or rgba.dtype != np.uint8:
        raise ValueError("expected (H, W, 4) uint8")
    h, w = rgba.shape[:2]
    raw = np.hstack([np.zeros((h, 1), np.uint8), rgba.reshape(h, w * 4)]).tobytes()

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def encode_geotiff(grid: Grid, rgba: np.ndarray) -> bytes:
    """Uncompressed single-strip RGBA GeoTIFF, EPSG:4326, PixelIsArea, so the
    image opens georeferenced in QGIS/Surfer/ArcGIS."""
    h, w = rgba.shape[:2]
    if rgba.shape != (grid.shape[0], grid.shape[1], 4):
        raise ValueError("image must match the grid")
    data = rgba.astype(np.uint8).tobytes()
    tags = [
        (256, 4, [w]), (257, 4, [h]), (258, 3, [8, 8, 8, 8]), (259, 3, [1]),
        (262, 3, [2]), (273, 4, [0]), (277, 3, [4]), (278, 4, [h]),
        (279, 4, [len(data)]), (284, 3, [1]), (338, 3, [2]),
        (33550, 12, [grid.dlon, grid.dlat, 0.0]),
        (33922, 12, [0.0, 0.0, 0.0, grid.west, grid.north, 0.0]),
        (34735, 3, [1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, 4326]),
    ]
    fmt = {3: "H", 4: "I", 12: "d"}
    size = {3: 2, 4: 4, 12: 8}
    n = len(tags)
    ifd_len = 2 + n * 12 + 4
    extra_off = 8 + ifd_len
    extra = bytearray()
    blobs = []
    for tag, typ, vals in tags:
        raw = struct.pack("<" + fmt[typ] * len(vals), *vals)
        blobs.append((tag, typ, vals, raw))
        if len(raw) > 4:
            extra += raw
            if len(extra) % 2:
                extra += b"\0"
    data_off = extra_off + len(extra)
    ifd = bytearray(struct.pack("<H", n))
    cursor = extra_off
    for tag, typ, vals, raw in blobs:
        if tag == 273:
            raw = struct.pack("<I", data_off)
        if len(raw) <= 4:
            ifd += struct.pack("<HHI", tag, typ, len(vals)) + raw.ljust(4, b"\0")
        else:
            ifd += struct.pack("<HHII", tag, typ, len(vals), cursor)
            cursor += len(raw) + (len(raw) % 2)
    ifd += struct.pack("<I", 0)
    return b"II" + struct.pack("<HI", 42, 8) + bytes(ifd) + bytes(extra) + data


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# --------------------------------------------------------------------------
# One call for the app
# --------------------------------------------------------------------------

def build_final_image(storage_folder: str, offline_data_root: str, lat: float, lon: float,
                      half_size_m: float = 1000.0, *, colour_by: str = "relief",
                      relief_radius_m: float = 300.0, contour_interval: Optional[float] = None,
                      candidates: Sequence[Dict] = (), created_utc: str = "") -> Dict:
    """Reads the window, checks it, builds the composite + vector layers.
    Returns everything the screen needs; arrays stay in Python (the screen
    asks for rendered views via render_view)."""
    grid = read_dem_window(storage_folder, offline_data_root, lat, lon, half_size_m)
    problems = validate(grid)
    if any(p.startswith("no DEM") or p.startswith("window smaller") for p in problems):
        return {"version": FI_VERSION, "ok": False, "problems": problems}
    dx, dy = grid.cell_size_m()
    rgba, legend = compose(grid.values, dx, dy, colour_by=colour_by, relief_radius_m=relief_radius_m)
    params = {"half_size_m": half_size_m, "colour_by": colour_by,
              "relief_radius_m": relief_radius_m, "contour_interval": contour_interval,
              "display_mode_default": DEFAULT_MODE}
    return {
        "version": FI_VERSION, "ok": True, "problems": problems, "notes": grid.notes,
        "grid": grid, "image": rgba, "legend": legend,
        "contours": contours(grid.values, contour_interval),
        "utm_grid": utm_grid(grid),
        "candidates": candidate_overlay(grid, candidates),
        "native_resolution_m": grid.native_resolution_m(),
        "provenance": {
            "version": FI_VERSION, "created_utc": created_utc,
            "synthetic_data": False, "source": grid.source,
            "source_sha256": grid.source_sha256,
            "bounds": {"west": grid.west, "north": grid.north,
                       "east": grid.west + grid.shape[1] * grid.dlon,
                       "south": grid.north - grid.shape[0] * grid.dlat},
            "cells": list(grid.shape), "native_resolution_m": grid.native_resolution_m(),
            "method": "multidirectional Horn hillshade x local relief colour; "
                      "marching-squares contours; no interpolation in stored image",
            "parameters": params,
            "statement": "Visual enhancement only. Derived from the DEM; adds no new "
                         "information and is not archaeological proof.",
        },
    }


def export_files(result: Dict, out_dir: str, stem: str) -> Dict[str, str]:
    """Writes <stem>.png, <stem>.tif and <stem>.provenance.json (with the
    SHA-256 of both images). Returns the paths."""
    if not result.get("ok"):
        raise ValueError("nothing to export")
    os.makedirs(out_dir, exist_ok=True)
    png = encode_png(result["image"])
    tif = encode_geotiff(result["grid"], result["image"])
    paths = {"png": os.path.join(out_dir, stem + ".png"),
             "geotiff": os.path.join(out_dir, stem + ".tif"),
             "provenance": os.path.join(out_dir, stem + ".provenance.json")}
    with open(paths["png"], "wb") as f:
        f.write(png)
    with open(paths["geotiff"], "wb") as f:
        f.write(tif)
    prov = dict(result["provenance"])
    prov["outputs"] = {"png_sha256": _sha(png), "geotiff_sha256": _sha(tif)}
    prov["legend"] = result["legend"]
    with open(paths["provenance"], "w", encoding="utf-8") as f:
        json.dump(prov, f, indent=2, sort_keys=True)
    return paths
