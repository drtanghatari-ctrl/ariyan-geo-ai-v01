"""
dem_filters.py -- fa-v2 (2026-10-22): Filters for the Final Image screen.

Five filters, every one of them DERIVED from the same real DEM window that
fi-v1 already shows. Approved design (2026-10-22):

  smooth     Gaussian (sigma 1/2/3 cells) or median (3x3 / 5x5) of elevation.
  residual   elevation minus its neighbourhood mean, radius 60 / 150 / 300 m.
  curvature  -100 x Laplacian of a lightly smoothed surface (1/100 m, the
             ArcGIS convention): convex tops warm, concave hollows cool.
  slope      steepness in degrees, Horn (1981) 3x3.
  direction  aspect (downslope bearing, circular colours) OR the directional
             derivative along a chosen bearing (0/45/90/135 deg).

HONESTY RULES (fixed, tested):
  * The raw DEM is never changed: every filter works on a copy.
  * Nothing here touches a candidate, score, review, status or the Steward;
    this module does not import the database at all.
  * STRICT SUPPORT: a cell gets a value only if EVERY input cell its operator
    needs is a real measurement inside the window. Window edges and cells
    next to gaps therefore become no-data (hatched on screen), never a
    guessed value. The width of that border is reported.
  * Every result carries a "DERIVED: <name> + <settings>" label that goes on
    the map title, the legend and the export provenance.
  * Results stay on the DEM's own cells (exact-cell rendering unchanged).

numpy only (the phone has no scipy).
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import numpy as np

import final_image as fi

FA2_VERSION = "fa-v2"
FILTERS = ("smooth", "residual", "curvature", "slope", "direction")

SMOOTH_METHODS = ("gaussian", "median")
GAUSS_SIGMAS = (1, 2, 3)              # cells
MEDIAN_SIZES = (3, 5)                 # cells
RESIDUAL_RADII_M = (60.0, 150.0, 300.0)
CURV_SMOOTH = (0, 1, 2)               # gaussian sigma in cells before curvature
DIRECTION_MODES = ("aspect", "derivative")
DERIV_BEARINGS = (0.0, 45.0, 90.0, 135.0)
FLAT_SLOPE_DEG = 1.0                  # aspect undefined below this: drawn grey "flat"

DEFAULTS = {
    "smooth": {"method": "gaussian", "sigma": 1, "size": 3},
    "residual": {"radius_m": 150.0},
    "curvature": {"smooth_sigma": 1},
    "slope": {},
    "direction": {"mode": "aspect", "bearing": 0.0},
}

# ramps: [t, r, g, b]
RAMP_DIVERGING = np.array([                    # cool (concave/low) -> white -> warm
    [0.00, 40, 70, 170], [0.25, 110, 160, 220], [0.50, 245, 245, 240],
    [0.75, 240, 150, 90], [1.00, 180, 30, 30]], dtype=np.float64)
RAMP_SLOPE = np.array([                        # flat pale -> steep dark red
    [0.00, 250, 250, 235], [0.35, 245, 205, 120], [0.70, 215, 100, 50],
    [1.00, 110, 20, 30]], dtype=np.float64)
RAMP_ASPECT = np.array([                       # circular: N red, E yellow, S cyan, W blue, N red
    [0.000, 220, 50, 50], [0.125, 235, 140, 40], [0.250, 225, 210, 50],
    [0.375, 110, 190, 70], [0.500, 50, 180, 190], [0.625, 60, 120, 210],
    [0.750, 90, 70, 200], [0.875, 180, 60, 160], [1.000, 220, 50, 50]], dtype=np.float64)
FLAT_RGB = (165, 165, 165)


# --------------------------------------------------------------------------
# strict-support helpers
# --------------------------------------------------------------------------

def support_mask(z: np.ndarray, rr: int, rc: int) -> np.ndarray:
    """True where the whole (2rr+1)x(2rc+1) window around the cell lies inside
    the grid AND every cell in it is a real (finite) measurement."""
    h, w = z.shape
    bad = (~np.isfinite(z)).astype(np.int64)
    p = np.pad(bad, ((rr + 1, rr), (rc + 1, rc)), mode="constant", constant_values=1)
    s = p.cumsum(0).cumsum(1)
    n = (s[2 * rr + 1:2 * rr + 1 + h, 2 * rc + 1:2 * rc + 1 + w]
         - s[:h, 2 * rc + 1:2 * rc + 1 + w]
         - s[2 * rr + 1:2 * rr + 1 + h, :w]
         + s[:h, :w])
    return n == 0


def _gauss_kernel(sigma: float) -> np.ndarray:
    r = int(math.ceil(3.0 * sigma))
    x = np.arange(-r, r + 1, dtype=np.float64)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    return k / k.sum()


def _conv1d(a: np.ndarray, k: np.ndarray, axis: int) -> np.ndarray:
    r = len(k) // 2
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r, r)
    p = np.pad(a, pad, mode="edge")                 # edge cells are masked afterwards
    out = np.zeros(a.shape, dtype=np.float64)
    n = a.shape[axis]
    for i, kv in enumerate(k):
        sl = [slice(None), slice(None)]
        sl[axis] = slice(i, i + n)
        out += kv * p[tuple(sl)]
    return out


def gaussian(z: np.ndarray, sigma: float) -> Tuple[np.ndarray, int]:
    """Separable Gaussian, truncated at 3 sigma. Returns (values, radius in
    cells). Cells without full support are NaN."""
    k = _gauss_kernel(sigma)
    r = len(k) // 2
    filled = np.where(np.isfinite(z), z, 0.0)
    out = _conv1d(_conv1d(filled, k, 0), k, 1)
    return np.where(support_mask(z, r, r), out, np.nan), r


def median(z: np.ndarray, size: int) -> Tuple[np.ndarray, int]:
    if size % 2 != 1 or size < 3:
        raise ValueError("median size must be odd and >= 3")
    r = size // 2
    h, w = z.shape
    p = np.pad(z, r, mode="edge")
    stack = np.empty((size * size, h, w), dtype=np.float64)
    i = 0
    for dr in range(size):
        for dc in range(size):
            stack[i] = p[dr:dr + h, dc:dc + w]
            i += 1
    out = np.median(stack, axis=0)
    return np.where(support_mask(z, r, r), out, np.nan), r


def _horn(z: np.ndarray, dx: float, dy: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    gx, gy = fi.horn_gradients(z, dx, dy)          # gy is SOUTH-positive
    ok = support_mask(z, 1, 1)
    return np.where(ok, gx, np.nan), np.where(ok, gy, np.nan), ok


def residual(z: np.ndarray, dx: float, dy: float, radius_m: float) -> Tuple[np.ndarray, int, int]:
    rc = max(1, int(round(radius_m / dx)))
    rr = max(1, int(round(radius_m / dy)))
    mean = fi._box_mean(z, rr, rc)
    out = np.where(support_mask(z, rr, rc), z - mean, np.nan)
    return out, rr, rc


def curvature(z: np.ndarray, dx: float, dy: float, smooth_sigma: int) -> Tuple[np.ndarray, int]:
    """-100 x Laplacian (1/100 m). Positive = convex (mound tops, rims),
    negative = concave (ditches, hollows)."""
    base, r = (gaussian(z, smooth_sigma) if smooth_sigma > 0 else (z.copy(), 0))
    f = np.where(np.isfinite(base), base, 0.0)
    p = np.pad(f, 1, mode="edge")
    d2x = (p[1:-1, 2:] - 2 * f + p[1:-1, :-2]) / (dx * dx)
    d2y = (p[2:, 1:-1] - 2 * f + p[:-2, 1:-1]) / (dy * dy)
    out = -100.0 * (d2x + d2y)
    ok = support_mask(base, 1, 1)
    return np.where(ok, out, np.nan), r + 1


def slope(z: np.ndarray, dx: float, dy: float) -> np.ndarray:
    gx, gy, _ = _horn(z, dx, dy)
    return np.degrees(np.arctan(np.hypot(gx, gy)))


def aspect(z: np.ndarray, dx: float, dy: float) -> Tuple[np.ndarray, np.ndarray]:
    """Downslope bearing, degrees clockwise from grid north (0..360), and a
    flat mask (slope < FLAT_SLOPE_DEG: aspect undefined, NOT no-data)."""
    gx, gy, _ = _horn(z, dx, dy)
    g_e, g_n = gx, -gy                              # gradient in (east, north)
    asp = (np.degrees(np.arctan2(-g_e, -g_n)) + 360.0) % 360.0
    flat = np.isfinite(gx) & (np.degrees(np.arctan(np.hypot(gx, gy))) < FLAT_SLOPE_DEG)
    return asp, flat


def directional(z: np.ndarray, dx: float, dy: float, bearing_deg: float) -> np.ndarray:
    """Rise per 100 m walking toward bearing (grid north = 0, clockwise):
    positive = ground climbs in that direction."""
    gx, gy, _ = _horn(z, dx, dy)
    b = math.radians(bearing_deg)
    return 100.0 * (gx * math.sin(b) + (-gy) * math.cos(b))


# --------------------------------------------------------------------------
# parameters, labels, one call
# --------------------------------------------------------------------------

def normalise(name: str, params: Optional[Dict]) -> Dict:
    """Validated, complete settings for a filter (unknown values refused,
    never silently replaced)."""
    if name not in FILTERS:
        raise ValueError(f"unknown filter {name!r}; choose one of {', '.join(FILTERS)}")
    p = dict(DEFAULTS[name])
    p.update({k: v for k, v in (params or {}).items() if v is not None})
    if name == "smooth":
        if p["method"] not in SMOOTH_METHODS:
            raise ValueError("smoothing method must be gaussian or median")
        p["sigma"] = int(p["sigma"]); p["size"] = int(p["size"])
        if p["method"] == "gaussian" and p["sigma"] not in GAUSS_SIGMAS:
            raise ValueError("gaussian sigma must be 1, 2 or 3 cells")
        if p["method"] == "median" and p["size"] not in MEDIAN_SIZES:
            raise ValueError("median window must be 3 or 5 cells")
        p = {"method": p["method"], **({"sigma": p["sigma"]} if p["method"] == "gaussian"
                                       else {"size": p["size"]})}
    elif name == "residual":
        p["radius_m"] = float(p["radius_m"])
        if p["radius_m"] not in RESIDUAL_RADII_M:
            raise ValueError("residual radius must be 60, 150 or 300 m")
    elif name == "curvature":
        p["smooth_sigma"] = int(p["smooth_sigma"])
        if p["smooth_sigma"] not in CURV_SMOOTH:
            raise ValueError("curvature pre-smoothing must be 0, 1 or 2 cells")
    elif name == "direction":
        if p["mode"] not in DIRECTION_MODES:
            raise ValueError("direction mode must be aspect or derivative")
        p["bearing"] = float(p["bearing"]) % 360.0
        if p["mode"] == "derivative" and p["bearing"] not in DERIV_BEARINGS:
            raise ValueError("bearing must be 0, 45, 90 or 135 degrees")
        if p["mode"] == "aspect":
            p = {"mode": "aspect"}
    return p


def label(name: str, p: Dict) -> str:
    if name == "smooth":
        s = (f"Gaussian \u03c3={p['sigma']} cell{'s' if p['sigma'] > 1 else ''}"
             if p["method"] == "gaussian" else f"median {p['size']}\u00d7{p['size']}")
        return f"DERIVED: Smoothed elevation ({s})"
    if name == "residual":
        return f"DERIVED: Residual relief (radius {p['radius_m']:.0f} m)"
    if name == "curvature":
        return (f"DERIVED: Curvature (\u2212100\u00b7Laplacian, pre-smooth "
                f"\u03c3={p['smooth_sigma']})")
    if name == "slope":
        return "DERIVED: Slope (Horn 3\u00d73, degrees)"
    if p["mode"] == "aspect":
        return "DERIVED: Aspect (downslope direction, Horn 3\u00d73)"
    return f"DERIVED: Directional derivative (bearing {p['bearing']:.0f}\u00b0)"


def _rgba(values: np.ndarray, rgb: np.ndarray) -> np.ndarray:
    out = np.zeros(values.shape + (4,), dtype=np.uint8)
    ok = np.isfinite(values)
    out[..., :3] = np.where(ok[..., None], rgb, 0)
    out[..., 3] = np.where(ok, 255, 0)
    return out


def _symmetric(values: np.ndarray) -> Tuple[float, float]:
    lo, hi = fi.robust_range(values)
    m = max(abs(lo), abs(hi)) or 1.0
    return -m, m


def apply_filter(grid: fi.Grid, name: str, params: Optional[Dict] = None) -> Dict:
    """Runs one filter on the window. Returns {"values" (H,W float, NaN =
    no data), "image" (H,W,4 uint8), "legend", "label", "params", ...}.
    grid.values is read, never written."""
    p = normalise(name, params)
    z = np.array(grid.values, dtype=np.float64, copy=True)   # raw DEM untouched
    dx, dy = grid.cell_size_m()
    border = 0
    notes = []
    flat = None
    if name == "smooth":
        vals, border = gaussian(z, p["sigma"]) if p["method"] == "gaussian" else median(z, p["size"])
        lo, hi = fi.robust_range(vals)
        shade = fi.hillshade_multi(np.where(np.isfinite(vals), vals, np.nanmean(vals) if
                                            np.isfinite(vals).any() else 0.0), dx, dy)
        shade = np.where(support_mask(vals, 1, 1), shade, np.nan)
        vals = np.where(np.isfinite(shade), vals, np.nan)
        border += 1
        rgb = fi.colorize(vals, lo, hi).astype(np.float64)
        rgb *= (0.35 + 0.65 * np.nan_to_num(shade, nan=1.0))[..., None]
        rgb = np.rint(np.clip(rgb, 0, 255)).astype(np.uint8)
        ramp, units, kind = fi.RAMP_TERRAIN, "m elevation", "sequential"
        notes.append("Colour = smoothed elevation; shading from the smoothed surface.")
    elif name == "residual":
        vals, rr, rc = residual(z, dx, dy, p["radius_m"])
        border = max(rr, rc)
        lo, hi = _symmetric(vals)
        rgb = fi.colorize(vals, lo, hi, RAMP_DIVERGING)
        ramp, units, kind = RAMP_DIVERGING, "m above (+) / below (\u2212) surroundings", "diverging"
        notes.append(f"Window {2 * rc + 1}\u00d7{2 * rr + 1} cells around each cell.")
    elif name == "curvature":
        vals, border = curvature(z, dx, dy, p["smooth_sigma"])
        lo, hi = _symmetric(vals)
        rgb = fi.colorize(vals, lo, hi, RAMP_DIVERGING)
        ramp, units, kind = RAMP_DIVERGING, "1/100 m (+ convex, \u2212 concave)", "diverging"
    elif name == "slope":
        vals = slope(z, dx, dy)
        border = 1
        lo = 0.0
        hi = max(fi.robust_range(vals)[1], 1.0)
        rgb = fi.colorize(vals, lo, hi, RAMP_SLOPE)
        ramp, units, kind = RAMP_SLOPE, "degrees", "sequential"
    else:
        border = 1
        if p["mode"] == "aspect":
            vals, flat = aspect(z, dx, dy)
            lo, hi = 0.0, 360.0
            rgb = fi.colorize(vals, lo, hi, RAMP_ASPECT)
            rgb[flat] = FLAT_RGB
            ramp, units, kind = RAMP_ASPECT, "degrees from grid north (downslope)", "circular"
            notes.append(f"Grey = flat (slope < {FLAT_SLOPE_DEG:g}\u00b0): direction undefined, "
                         "but the ground is measured there (not no-data).")
        else:
            vals = directional(z, dx, dy, p["bearing"])
            lo, hi = _symmetric(vals)
            rgb = fi.colorize(vals, lo, hi, RAMP_DIVERGING)
            ramp, units, kind = (RAMP_DIVERGING,
                                 f"m rise per 100 m toward {p['bearing']:.0f}\u00b0", "diverging")
    img = _rgba(vals, rgb)
    n = vals.size
    n_nd = int((~np.isfinite(vals)).sum())
    lab = label(name, p)
    notes.append(f"Cells need every neighbour their operator uses: a {border}-cell border and "
                 "cells beside gaps are no-data (hatched), never guessed.")
    legend = {"label": lab, "filter": name, "params": p, "ramp": ramp.tolist(), "kind": kind,
              "vmin": round(float(lo), 4), "vmax": round(float(hi), 4), "units": units}
    return {"version": FA2_VERSION, "filter": name, "params": p, "label": lab,
            "values": vals, "image": img, "legend": legend, "units": units,
            "border_cells": int(border), "cells": n, "cells_no_data": n_nd,
            "flat_cells": int(flat.sum()) if flat is not None else 0,
            "notes": notes,
            "statement": "DERIVED view of the same DEM. Display only: the raw DEM, "
                         "candidates, scores, reviews and the Steward are unchanged. "
                         "Not archaeological proof."}


def provenance(grid: fi.Grid, f: Dict, created_utc: str = "") -> Dict:
    return {"version": FA2_VERSION, "created_utc": created_utc, "derived": True,
            "synthetic_data": False, "label": f["label"], "filter": f["filter"],
            "parameters": f["params"], "source": grid.source,
            "source_sha256": grid.source_sha256, "cells": list(grid.shape),
            "cells_no_data": f["cells_no_data"], "border_cells": f["border_cells"],
            "native_resolution_m": grid.native_resolution_m(),
            "bounds": {"west": grid.west, "north": grid.north,
                       "east": grid.west + grid.shape[1] * grid.dlon,
                       "south": grid.north - grid.shape[0] * grid.dlat},
            "method_rules": ["raw DEM not modified", "strict support: no value without "
                             "all input cells", "exact cells, no resampling",
                             "no feedback to detection, scoring or review"],
            "legend": f["legend"], "statement": f["statement"]}
