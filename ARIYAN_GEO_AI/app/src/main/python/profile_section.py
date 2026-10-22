"""
profile_section.py -- fa-v1 (2026-10-21): Profile & Section, scientific core.

First piece of the Final Assessment page. A straight line A-A' is drawn on
the Final Image window and the real cells under it are read out.

RULES (user decisions 2026-10-21, project rules):
  * Exact cells, no smoothing. The line is walked cell by cell on the DEM's
    own lattice; every cell it crosses becomes one flat step whose length is
    exactly the part of the line inside that cell. No interpolation, no
    resampling, no fill. Cells with no measurement stay gaps (None).
  * Relief trace = the SAME local-relief measure as the colour map
    (elevation minus neighbourhood mean, same radius), computed on the
    whole window, then read cell by cell.
  * Satellite trace (optional) is read on the satellite image's OWN cells,
    only from a layer already open (already saved) -- this module never
    downloads anything.
  * Distances and positions are UTM metres (zone of the window centre, the
    same zone as the on-screen UTM grid).
  * Candidates within 50 m of the line are marked; their status and
    confidence are read, never changed.
  * Vertical exaggeration is always computed and printed with the plot.
  * Every export carries provenance (source tile SHA-256, line, method,
    parameters, SHA-256 of every output file).

numpy only.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

import final_image as fi

FA_VERSION = "fa-v1"
NEAR_LINE_M = 50.0
MIN_LINE_M = 1.0
STATEMENT = ("Profile of real DEM cells: one flat step per cell crossed, no smoothing "
             "or interpolation. Visual aid only; not archaeological proof.")


# --------------------------------------------------------------------------
# Walking a straight line through a lattice, cell by cell
# --------------------------------------------------------------------------

def _clip_to_box(x0, y0, x1, y1, w, h) -> Optional[Tuple[float, float]]:
    """Liang-Barsky: parameter range [ta, tb] of the segment inside [0,w]x[0,h]."""
    ta, tb = 0.0, 1.0
    dx, dy = x1 - x0, y1 - y0
    for p, q in ((-dx, x0), (dx, w - x0), (-dy, y0), (dy, h - y0)):
        if p == 0.0:
            if q < 0.0:
                return None
            continue
        r = q / p
        if p < 0.0:
            ta = max(ta, r)
        else:
            tb = min(tb, r)
        if ta > tb:
            return None
    return ta, tb


def cells_crossed(x0: float, y0: float, x1: float, y1: float, w: int, h: int,
                  eps: float = 1e-9) -> List[Tuple[int, int, float, float]]:
    """Every lattice cell the segment (x0,y0)->(x1,y1) passes through, in
    order, as (col, row, t_enter, t_exit) with t in [0, 1] along the segment.
    Cell (c, r) is the square [c, c+1] x [r, r+1] in continuous grid-pixel
    coordinates. Parts of the segment outside the lattice are dropped. A
    line through a cell corner does not produce a zero-length step."""
    clip = _clip_to_box(x0, y0, x1, y1, w, h)
    if clip is None:
        return []
    ta, tb = clip
    if tb - ta <= eps:
        return []
    dx, dy = x1 - x0, y1 - y0
    ts = {ta, tb}
    for start, d, n in ((x0, dx, w), (y0, dy, h)):
        if d == 0.0:
            continue
        for k in range(0, n + 1):
            t = (k - start) / d
            if ta < t < tb:
                ts.add(t)
    ts = sorted(ts)
    out: List[Tuple[int, int, float, float]] = []
    for a, b in zip(ts[:-1], ts[1:]):
        if b - a <= eps:
            continue
        m = 0.5 * (a + b)
        c = min(w - 1, max(0, int(math.floor(x0 + m * dx))))
        r = min(h - 1, max(0, int(math.floor(y0 + m * dy))))
        if out and out[-1][0] == c and out[-1][1] == r:
            out[-1] = (c, r, out[-1][2], b)
        else:
            out.append((c, r, a, b))
    return out


# --------------------------------------------------------------------------
# Geometry in UTM metres
# --------------------------------------------------------------------------

class _Utm:
    """Grid-pixel (DEM lattice) -> UTM metres, zone of the window centre."""

    def __init__(self, grid: fi.Grid):
        import utm_projection as up
        self.up = up
        self.grid = grid
        h, w = grid.shape
        lon_c, lat_c = grid.pixel_to_lonlat(w / 2.0, h / 2.0)
        self.zone = up.utm_zone_for(lon_c)
        self.northern = lat_c >= 0

    def en(self, x: float, y: float) -> Tuple[float, float]:
        lon, lat = self.grid.pixel_to_lonlat(x, y)
        p = self.up.utm_forward(lat, lon, self.zone)
        return p.easting, p.northing


def _r(v, nd=3):
    if v is None:
        return None
    v = float(v)
    return round(v, nd) if math.isfinite(v) else None


def _steps_on_lattice(values: np.ndarray, ax: float, ay: float, bx: float, by: float,
                      to_dem, utm: _Utm, ea: float, na: float) -> Dict[str, list]:
    """Walks the segment A->B given in THIS lattice's pixel coordinates.
    to_dem(u, v) maps lattice pixel coords to DEM pixel coords (identity for
    the DEM itself, affine placement for a satellite image). Distances are
    UTM metres from A."""
    h, w = values.shape
    out = {"col": [], "row": [], "t0": [], "t1": [], "d0": [], "d1": [], "v": []}
    cache: Dict[float, float] = {}

    def dist(t: float) -> float:
        if t not in cache:
            x, y = to_dem(ax + t * (bx - ax), ay + t * (by - ay))
            e, n = utm.en(x, y)
            cache[t] = math.hypot(e - ea, n - na)
        return cache[t]

    for c, r, t0, t1 in cells_crossed(ax, ay, bx, by, w, h):
        out["col"].append(c)
        out["row"].append(r)
        out["t0"].append(round(t0, 9))
        out["t1"].append(round(t1, 9))
        out["d0"].append(round(dist(t0), 3))
        out["d1"].append(round(dist(t1), 3))
        out["v"].append(_r(values[r, c]))
    return out


def axis_range(vals: Sequence[Optional[float]], min_span: float = 2.0) -> Tuple[float, float]:
    """Plot axis for a trace: data min..max padded 5 % each side, at least
    min_span wide (so a flat line is not blown up into fake relief)."""
    v = [x for x in vals if x is not None]
    if not v:
        return 0.0, min_span
    lo, hi = min(v), max(v)
    span = max(hi - lo, min_span)
    mid = 0.5 * (lo + hi)
    lo, hi = mid - span / 2.0, mid + span / 2.0
    pad = 0.05 * span
    nd = max(3, 3 - int(math.floor(math.log10(span))))   # keep the span visible
    return round(lo - pad, nd), round(hi + pad, nd)


def vertical_exaggeration(length_m: float, axis: Tuple[float, float],
                          plot_w_px: float, plot_h_px: float) -> float:
    """Metres per pixel horizontally / metres per pixel vertically."""
    span = axis[1] - axis[0]
    if length_m <= 0 or span <= 0 or plot_w_px <= 0 or plot_h_px <= 0:
        return 1.0
    return (length_m / plot_w_px) / (span / plot_h_px)


# --------------------------------------------------------------------------
# The profile
# --------------------------------------------------------------------------

def relief_layer(result: Dict) -> np.ndarray:
    """Local relief with the radius used by the colour map (cached)."""
    if "_relief" not in result:
        grid = result["grid"]
        dx, dy = grid.cell_size_m()
        radius = float(result["provenance"]["parameters"].get("relief_radius_m") or 300.0)
        result["_relief"] = fi.local_relief(grid.values, dx, dy, radius)
        result["_relief_radius_m"] = radius
    return result["_relief"]


def preset_line(grid: fi.Grid, fx: float, fy: float, which: str) -> Tuple[float, float, float, float]:
    """N-S or E-W line through (fx, fy) across the whole window. A is the
    north / west end."""
    h, w = grid.shape
    which = which.upper().replace("-", "").replace("_", "")
    if which == "NS":
        return fx, 0.0, fx, float(h)
    if which == "EW":
        return 0.0, fy, float(w), fy
    raise ValueError("preset must be 'NS' or 'EW'")


def candidates_near(markers: Sequence[Dict], utm: _Utm, a: Tuple[float, float],
                    b: Tuple[float, float], length_m: float,
                    within_m: float = NEAR_LINE_M) -> List[Dict]:
    """Candidates within `within_m` of segment A-B (UTM metres). Status and
    confidence are copied from the markers, never changed."""
    ea, na = a
    eb, nb = b
    ux, uy = (eb - ea) / length_m, (nb - na) / length_m
    out = []
    for m in markers:
        e, n = utm.en(float(m["x"]), float(m["y"]))
        s = (e - ea) * ux + (n - na) * uy
        s_c = min(max(s, 0.0), length_m)
        off = (e - ea) * uy - (n - na) * ux           # + = right of A->B
        dist = math.hypot(e - (ea + s_c * ux), n - (na + s_c * uy))
        if dist <= within_m:
            out.append({"id": m["id"], "label": str(m["id"])[:8],
                        "d_m": round(s_c, 2), "offset_m": round(dist, 2),
                        "side": "on" if dist < 0.5 else ("right" if off > 0 else "left"),
                        "status": m.get("status"), "confidence_label": m.get("confidence_label"),
                        "style": m.get("style"), "focus": bool(m.get("focus"))})
    out.sort(key=lambda c: c["d_m"])
    return out


def build_profile(result: Dict, ax: float, ay: float, bx: float, by: float, *,
                  markers: Sequence[Dict] = (), sat: Optional[Dict] = None) -> Dict:
    """result: an fi-v1 build_final_image result. (ax, ay)->(bx, by) in DEM
    grid-pixel coordinates. sat (optional): {"product", "label", "units",
    "values" (H,W), "placement" {x0,y0,sx,sy}, "scene_date", "provenance"}.
    Returns the profile (plain JSON-able dict)."""
    grid: fi.Grid = result["grid"]
    h, w = grid.shape
    if cells_crossed(ax, ay, bx, by, w, h) == []:
        raise ValueError("the line does not cross the image window")
    clip = _clip_to_box(ax, ay, bx, by, w, h)
    ta, tb = clip
    # A and B are the ends of the part of the line on the image
    ax, ay, bx, by = (ax + ta * (bx - ax), ay + ta * (by - ay),
                      ax + tb * (bx - ax), ay + tb * (by - ay))
    utm = _Utm(grid)
    ea, na = utm.en(ax, ay)
    eb, nb = utm.en(bx, by)
    length = math.hypot(eb - ea, nb - na)
    if length < MIN_LINE_M:
        raise ValueError("line too short")
    ident = lambda u, v: (u, v)
    dem = _steps_on_lattice(grid.values, ax, ay, bx, by, ident, utm, ea, na)
    rel = relief_layer(result)
    dem["relief"] = [_r(rel[r, c]) for c, r in zip(dem["col"], dem["row"])]
    dem["elevation"] = dem.pop("v")
    lon_a, lat_a = grid.pixel_to_lonlat(ax, ay)
    lon_b, lat_b = grid.pixel_to_lonlat(bx, by)
    bearing = (math.degrees(math.atan2(eb - ea, nb - na)) + 360.0) % 360.0
    n_cells = len(dem["col"])
    n_gap = sum(1 for v in dem["elevation"] if v is None)
    out = {
        "version": FA_VERSION,
        "a": {"x": round(ax, 4), "y": round(ay, 4), "lat": lat_a, "lon": lon_a,
              "easting": round(ea, 2), "northing": round(na, 2)},
        "b": {"x": round(bx, 4), "y": round(by, 4), "lat": lat_b, "lon": lon_b,
              "easting": round(eb, 2), "northing": round(nb, 2)},
        "utm_zone": utm.zone, "hemisphere": "N" if utm.northern else "S",
        "length_m": round(length, 2), "bearing_deg": round(bearing, 2),
        "native_resolution_m": grid.native_resolution_m(),
        "relief_radius_m": result.get("_relief_radius_m"),
        "dem": dem, "cells": n_cells, "cells_no_data": n_gap,
        "elevation_axis": list(axis_range(dem["elevation"])),
        "relief_axis": list(axis_range(dem["relief"])),
        "candidates": candidates_near(markers, utm, (ea, na), (eb, nb), length),
        "near_line_m": NEAR_LINE_M,
        "source": grid.source, "source_sha256": grid.source_sha256,
        "statement": STATEMENT,
    }
    if sat is not None:
        p = sat["placement"]
        # A, B in satellite-lattice pixel coordinates
        to_sat = lambda x, y: ((x - p["x0"]) / p["sx"], (y - p["y0"]) / p["sy"])
        to_dem = lambda u, v: (p["x0"] + u * p["sx"], p["y0"] + v * p["sy"])
        sa, sb = to_sat(ax, ay), to_sat(bx, by)
        st = _steps_on_lattice(sat["values"], sa[0], sa[1], sb[0], sb[1], to_dem, utm, ea, na)
        st["value"] = st.pop("v")
        out["sat"] = {"product": sat["product"], "label": sat.get("label"),
                      "units": sat.get("units"), "scene_date": sat.get("scene_date"),
                      "cell_m": sat.get("cell_m"), "steps": st,
                      "cells": len(st["col"]),
                      "cells_no_data": sum(1 for v in st["value"] if v is None),
                      "axis": list(axis_range(st["value"], min_span=sat.get("min_span", 1e-6))),
                      "provenance": sat.get("provenance")}
    return out


def value_at(profile: Dict, d_m: float) -> Dict:
    """Readout at distance d along the line: the DEM cell under that point,
    its elevation and relief, the point's position (UTM, interpolated along
    the straight line A-B) and the satellite cell value if a trace exists."""
    dem = profile["dem"]
    L = profile["length_m"]
    d = min(max(float(d_m), 0.0), L)
    i = _step_index(dem["d0"], dem["d1"], d)
    f = d / L if L else 0.0
    a, b = profile["a"], profile["b"]
    out = {"d_m": round(d, 2),
           "easting": round(a["easting"] + f * (b["easting"] - a["easting"]), 1),
           "northing": round(a["northing"] + f * (b["northing"] - a["northing"]), 1),
           "x": a["x"] + f * (b["x"] - a["x"]), "y": a["y"] + f * (b["y"] - a["y"]),
           "col": dem["col"][i], "row": dem["row"][i],
           "elevation": dem["elevation"][i], "relief": dem["relief"][i]}
    if "sat" in profile:
        st = profile["sat"]["steps"]
        if st["d0"]:
            j = _step_index(st["d0"], st["d1"], d)
            inside = st["d0"][j] - 1e-6 <= d <= st["d1"][j] + 1e-6
            out["sat"] = st["value"][j] if inside else None
    return out


def _step_index(d0: Sequence[float], d1: Sequence[float], d: float) -> int:
    lo, hi = 0, len(d0) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if d1[mid] < d:
            lo = mid + 1
        else:
            hi = mid
    return lo


# --------------------------------------------------------------------------
# Export: CSV of every cell crossed + PNG of the profile + provenance
# --------------------------------------------------------------------------

def profile_csv(profile: Dict, grid: fi.Grid) -> bytes:
    dem = profile["dem"]
    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    wr.writerow(["step", "distance_from_m", "distance_to_m", "col", "row",
                 "cell_centre_lat", "cell_centre_lon", "elevation_m", "relief_m"])
    for i, (c, r) in enumerate(zip(dem["col"], dem["row"])):
        lon, lat = grid.pixel_to_lonlat(c + 0.5, r + 0.5)
        wr.writerow([i + 1, dem["d0"][i], dem["d1"][i], c, r, f"{lat:.7f}", f"{lon:.7f}",
                     "" if dem["elevation"][i] is None else dem["elevation"][i],
                     "" if dem["relief"][i] is None else dem["relief"][i]])
    return buf.getvalue().encode("utf-8")


def sat_csv(profile: Dict) -> bytes:
    s = profile["sat"]
    st = s["steps"]
    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    wr.writerow(["step", "distance_from_m", "distance_to_m", "image_col", "image_row",
                 f"{s['product'].lower()}_value"])
    for i, (c, r) in enumerate(zip(st["col"], st["row"])):
        wr.writerow([i + 1, st["d0"][i], st["d1"][i], c, r,
                     "" if st["value"][i] is None else st["value"][i]])
    return buf.getvalue().encode("utf-8")


# 5x7 bitmap font (no font library on the phone's Python)
_FONT_ROWS = {
    "A": "01110 10001 10001 11111 10001 10001 10001", "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110", "D": "11110 10001 10001 10001 10001 10001 11110",
    "E": "11111 10000 10000 11110 10000 10000 11111", "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111", "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "01110 00100 00100 00100 00100 00100 01110", "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001", "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001", "N": "10001 10001 11001 10101 10011 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110", "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101", "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110", "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110", "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 10101 01010", "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 10001 01010 00100 00100 00100", "Z": "11111 00001 00010 00100 01000 10000 11111",
    "0": "01110 10001 10011 10101 11001 10001 01110", "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111", "3": "11111 00010 00100 00010 00001 10001 01110",
    "4": "00010 00110 01010 10010 11111 00010 00010", "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110", "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110", "9": "01110 10001 10001 01111 00001 00010 01100",
    " ": "00000 00000 00000 00000 00000 00000 00000", ".": "00000 00000 00000 00000 00000 01100 01100",
    ",": "00000 00000 00000 00000 01100 00100 01000", ":": "00000 01100 01100 00000 01100 01100 00000",
    "-": "00000 00000 00000 11111 00000 00000 00000", "+": "00000 00100 00100 11111 00100 00100 00000",
    "/": "00000 00001 00010 00100 01000 10000 00000", "(": "00010 00100 01000 01000 01000 00100 00010",
    ")": "01000 00100 00010 00010 00010 00100 01000", "%": "11000 11001 00010 00100 01000 10011 00011",
    "=": "00000 00000 11111 00000 11111 00000 00000", "_": "00000 00000 00000 00000 00000 00000 11111",
    "'": "01100 00100 01000 00000 00000 00000 00000", "<": "00010 00100 01000 10000 01000 00100 00010",
    ">": "01000 00100 00010 00001 00010 00100 01000", "#": "01010 01010 11111 01010 11111 01010 01010",
    "[": "01110 01000 01000 01000 01000 01000 01110", "]": "01110 00010 00010 00010 00010 00010 01110",
    "*": "00000 00100 10101 01110 10101 00100 00000", "?": "01110 10001 00001 00010 00100 00000 00100",
}
_FONT = {k: np.array([[ch == "1" for ch in row] for row in v.split()], dtype=bool)
         for k, v in _FONT_ROWS.items()}


class _Canvas:
    def __init__(self, w: int, h: int, bg=(255, 255, 255)):
        self.w, self.h = w, h
        self.px = np.zeros((h, w, 4), np.uint8)
        self.px[..., :3] = bg
        self.px[..., 3] = 255

    def rect(self, x0, y0, x1, y1, col):
        x0, x1 = sorted((int(round(x0)), int(round(x1))))
        y0, y1 = sorted((int(round(y0)), int(round(y1))))
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(self.w - 1, x1), min(self.h - 1, y1)
        if x1 >= x0 and y1 >= y0:
            self.px[y0:y1 + 1, x0:x1 + 1, :3] = col

    def line(self, x0, y0, x1, y1, col, width=1, dash=0):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        xs = np.rint(np.linspace(x0, x1, n)).astype(int)
        ys = np.rint(np.linspace(y0, y1, n)).astype(int)
        keep = np.ones(n, bool) if not dash else ((np.arange(n) // dash) % 2 == 0)
        half = width // 2
        for ox in range(-half, width - half):
            for oy in range(-half, width - half):
                x, y = xs[keep] + ox, ys[keep] + oy
                ok = (x >= 0) & (x < self.w) & (y >= 0) & (y < self.h)
                self.px[y[ok], x[ok], :3] = col

    def text(self, x, y, s, col=(0, 0, 0), scale=2):
        cx = int(x)
        for ch in str(s).upper():
            g = _FONT.get(ch, _FONT["?"])
            ys, xs = np.nonzero(np.kron(g, np.ones((scale, scale), bool)))
            ys, xs = ys + int(y), xs + cx
            ok = (xs >= 0) & (xs < self.w) & (ys >= 0) & (ys < self.h)
            self.px[ys[ok], xs[ok], :3] = col
            cx += 6 * scale

    @staticmethod
    def text_w(s, scale=2) -> int:
        return len(str(s)) * 6 * scale


def _nice_ticks(lo: float, hi: float, n: int = 5) -> List[float]:
    step = fi.nice_interval(hi - lo, n)
    t = math.ceil(lo / step) * step
    out = []
    while t <= hi + 1e-9:
        out.append(round(t, 6))
        t += step
    return out


def _fmt(v: float) -> str:
    if abs(v) < 1e-9:
        v = 0.0
    return f"{v:.0f}" if abs(v) >= 100 or float(v).is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


def layout_labels(xs: Sequence[float], texts: Sequence[str], width_of, left: float, right: float,
                  max_rows: int = 3, gap: float = 4.0, focus: Sequence[bool] = ()) -> List[Dict]:
    """Place candidate labels along a profile without overlap.

    Each label sits just right of its line (or just left near the right edge)
    in the first of `max_rows` rows where it fits. A label that fits nowhere
    is folded into the nearest placed label as "+N" -- it is never drawn on
    top of another. Focus candidates are placed first. The dashed lines are
    not affected; every candidate keeps its own line.
    Returns [{"text", "x", "row", "members": [indices]}] in placement order."""
    n = len(xs)
    order = sorted(range(n), key=lambda i: (not (focus[i] if i < len(focus) else False), xs[i]))
    rows: List[List[List[float]]] = [[] for _ in range(max_rows)]
    out: List[Dict] = []

    def span(x, t):
        w = width_of(t)
        x0 = x + gap
        if x0 + w > right:
            x0 = x - gap - w
        x0 = max(left, x0)
        return x0, x0 + w

    for i in order:
        x0, x1 = span(xs[i], texts[i])
        for r in range(max_rows):
            if all(x1 + gap <= a or x0 >= b + gap for a, b in rows[r]):
                rows[r].append([x0, x1])
                out.append({"text": texts[i], "x": x0, "row": r, "members": [i],
                            "_x": xs[i], "_span": rows[r][-1], "_base": texts[i]})
                break
        else:
            if not out:
                continue
            host = min(out, key=lambda o: abs(o["_x"] - xs[i]))
            host["members"].append(i)
            host["text"] = f"{host['_base']} +{len(host['members']) - 1}"
            nx0, nx1 = span(host["_x"], host["text"])
            host["x"] = nx0
            host["_span"][0], host["_span"][1] = nx0, nx1
    for o in out:
        for k in ("_x", "_span", "_base"):
            del o[k]
    return out


def _panel(cv: _Canvas, top: int, height: int, left: int, right: int, title: str,
           d0, d1, vals, axis, length_m, colour, cands, metres: bool = True) -> Optional[float]:
    """One step trace. Returns the vertical exaggeration of this panel
    (None when the values are not metres -- VE is meaningless there)."""
    ph = height - 40
    py0 = top + 28
    pw = right - left
    lo, hi = axis
    if hi <= lo:
        hi = lo + 1e-9
    cv.text(left, top + 4, title, scale=2)
    cv.rect(left, py0, right, py0 + ph, (247, 247, 247))
    X = lambda d: left + d / length_m * pw
    Y = lambda v: py0 + ph - (v - lo) / (hi - lo) * ph
    for t in _nice_ticks(lo, hi, 4):
        y = Y(t)
        cv.line(left, y, right, y, (215, 215, 215))
        lab = _fmt(t)
        cv.text(left - _Canvas.text_w(lab, 1) - 4, y - 3, lab, scale=1)
    for c in cands:
        x = X(c["d_m"])
        cv.line(x, py0, x, py0 + ph, (200, 0, 160), dash=4)
    for lab in layout_labels([X(c["d_m"]) for c in cands], [c["label"] for c in cands],
                             lambda t: _Canvas.text_w(t, 1), left, right, gap=3,
                             focus=[bool(c.get("focus")) for c in cands]):
        cv.text(lab["x"], py0 + 2 + 10 * lab["row"], lab["text"], (200, 0, 160), scale=1)
    prev = None
    for a, b, v in zip(d0, d1, vals):
        if v is None:
            prev = None
            continue
        y = Y(v)
        if prev is not None:
            cv.line(X(a), prev, X(a), y, colour, width=2)
        cv.line(X(a), y, X(b), y, colour, width=2)
        prev = y
    cv.line(left, py0, left, py0 + ph, (0, 0, 0))
    cv.line(left, py0 + ph, right, py0 + ph, (0, 0, 0))
    if not metres:
        return None
    ve = vertical_exaggeration(length_m, axis, pw, ph)
    tag = f"VE X{ve:.1f}"
    cv.text(right - _Canvas.text_w(tag, 2), top + 4, tag, (160, 0, 0), scale=2)
    return ve


def render_png(profile: Dict, created_utc: str = "", width: int = 1400) -> Tuple[np.ndarray, Dict]:
    """The profile drawn as an RGBA image with its provenance block. Returns
    (rgba, {"vertical_exaggeration": {...}})."""
    has_sat = "sat" in profile
    panel_h = 300
    left, right = 110, width - 30
    head = 70
    prov_lines = _prov_lines(profile, created_utc)
    foot = 40 + 20 * len(prov_lines)
    height = head + panel_h * (3 if has_sat else 2) + 50 + foot
    cv = _Canvas(width, height)
    a, b = profile["a"], profile["b"]
    cv.text(left, 14, f"PROFILE A-A'  {profile['length_m']:.0f} M  BEARING "
                      f"{profile['bearing_deg']:.0f}  ({profile['cells']} DEM CELLS, EXACT STEPS)", scale=2)
    cv.text(left, 42, f"A E{a['easting']:.0f} N{a['northing']:.0f}   A' E{b['easting']:.0f} "
                      f"N{b['northing']:.0f}   UTM {profile['utm_zone']}{profile['hemisphere']} WGS84",
            scale=2)
    dem = profile["dem"]
    L = profile["length_m"]
    ves = {}
    y = head
    ves["elevation"] = _panel(cv, y, panel_h, left, right, "ELEVATION (M)", dem["d0"], dem["d1"],
                              dem["elevation"], profile["elevation_axis"], L, (20, 60, 180),
                              profile["candidates"])
    y += panel_h
    ves["relief"] = _panel(cv, y, panel_h, left, right,
                           f"RELIEF (M ABOVE/BELOW SURROUNDINGS, R={profile['relief_radius_m']:.0f} M)",
                           dem["d0"], dem["d1"], dem["relief"], profile["relief_axis"], L,
                           (200, 90, 0), profile["candidates"])
    y += panel_h
    if has_sat:
        s = profile["sat"]
        st = s["steps"]
        unit = f" ({s['units']})" if s.get("units") else ""
        _panel(cv, y, panel_h, left, right,
               f"{s['product']}{unit}  SCENE {s.get('scene_date') or '-'}  (OWN CELLS)",
               st["d0"], st["d1"], st["value"], s["axis"], L, (0, 130, 60),
               profile["candidates"], metres=False)
        y += panel_h
    for t in _nice_ticks(0, L, 8):
        x = left + t / L * (right - left)
        cv.line(x, y - 12, x, y - 6, (0, 0, 0))
        lab = _fmt(t)
        cv.text(x - _Canvas.text_w(lab, 1) / 2, y - 2, lab, scale=1)
    cv.text(right - _Canvas.text_w("DISTANCE FROM A (M)", 1), y + 12, "DISTANCE FROM A (M)", scale=1)
    y += 40
    cv.line(left, y, right, y, (120, 120, 120))
    for i, ln in enumerate(prov_lines):
        cv.text(left, y + 12 + 20 * i, ln, (60, 60, 60), scale=2)
    return cv.px, {"vertical_exaggeration": {k: round(v, 2) for k, v in ves.items()}}


def _prov_lines(profile: Dict, created_utc: str) -> List[str]:
    lines = [f"{FA_VERSION}  CREATED {created_utc or '-'}  NATIVE {profile['native_resolution_m']} M",
             f"SOURCE {os.path.basename(profile['source'] or '-')}",
             f"SHA256 {profile['source_sha256'] or '-'}",
             "EXACT CELLS: ONE FLAT STEP PER CELL CROSSED. NO SMOOTHING, NO INTERPOLATION.",
             f"GAPS = NO DATA ({profile['cells_no_data']} OF {profile['cells']} CELLS).",
             f"CANDIDATES MARKED WITHIN {profile['near_line_m']:.0f} M OF THE LINE.",
             "VISUAL AID ONLY. NOT ARCHAEOLOGICAL PROOF."]
    if "sat" in profile:
        s = profile["sat"]
        lines.insert(3, f"SAT {s['product']} SCENE {s.get('scene_date') or '-'} ON ITS OWN CELLS "
                        f"({s['cells_no_data']} OF {s['cells']} EMPTY)")
    return lines


def export_profile(profile: Dict, grid: fi.Grid, out_dir: str, stem: str,
                   created_utc: str = "") -> Dict[str, str]:
    """Writes <stem>.csv (every DEM cell crossed), <stem>_<product>.csv (if a
    satellite trace), <stem>.png and <stem>.provenance.json."""
    os.makedirs(out_dir, exist_ok=True)
    files: Dict[str, bytes] = {"csv": profile_csv(profile, grid)}
    if "sat" in profile:
        files["sat_csv"] = sat_csv(profile)
    rgba, meta = render_png(profile, created_utc)
    files["png"] = fi.encode_png(rgba)
    names = {"csv": stem + ".csv", "png": stem + ".png"}
    if "sat" in profile:
        names["sat_csv"] = f"{stem}_{profile['sat']['product'].lower()}.csv"
    paths = {}
    for k, data in files.items():
        p = os.path.join(out_dir, names[k])
        with open(p, "wb") as f:
            f.write(data)
        paths[k] = p
    prov = {
        "version": FA_VERSION, "created_utc": created_utc, "synthetic_data": False,
        "source": profile["source"], "source_sha256": profile["source_sha256"],
        "line": {"a": profile["a"], "b": profile["b"], "utm_zone": profile["utm_zone"],
                 "hemisphere": profile["hemisphere"], "datum": "WGS84",
                 "length_m": profile["length_m"], "bearing_deg": profile["bearing_deg"]},
        "cells": profile["cells"], "cells_no_data": profile["cells_no_data"],
        "native_resolution_m": profile["native_resolution_m"],
        "method": "line walked cell by cell on the DEM lattice (exact cell boundaries); "
                  "one flat step per cell, value = that cell's stored measurement; "
                  "relief = elevation minus neighbourhood box mean (same as colour map)",
        "parameters": {"relief_radius_m": profile["relief_radius_m"],
                       "near_line_m": profile["near_line_m"],
                       "vertical_exaggeration": meta["vertical_exaggeration"]},
        "candidates_marked": profile["candidates"],
        "statement": profile["statement"],
        "outputs": {k + "_sha256": hashlib.sha256(v).hexdigest() for k, v in files.items()},
    }
    if "sat" in profile:
        s = profile["sat"]
        prov["satellite"] = {"product": s["product"], "scene_date": s.get("scene_date"),
                             "cells": s["cells"], "cells_no_data": s["cells_no_data"],
                             "layer_provenance": s.get("provenance"),
                             "note": "read from the image already saved on the phone; "
                                     "nothing downloaded for this profile"}
    paths["provenance"] = os.path.join(out_dir, stem + ".provenance.json")
    with open(paths["provenance"], "w", encoding="utf-8") as f:
        json.dump(prov, f, indent=2, sort_keys=True)
    return paths
