"""
known_sites.py

Part of ARIYAN GEO AI -- F1 Known-Site Layer (added 2026-09-24,
user-approved roadmap F1-F4 after the Phase A forensic inspection of
external archaeology geo-AI projects).

WHAT THIS DOES
Given a coordinate, answers one factual question: "how far is the
nearest archaeological site recorded in the bundled gazetteer, and is
the gazetteer dense enough here for that distance to mean anything?"
The gazetteer is Pedersen's "ANE Site Placemarks" (Zenodo
10.5281/zenodo.6384045, CC-BY-4.0), stored as plain text in
known_sites_data.py. Fully offline: no network, no API allowance.

WHAT THIS IS NOT
- It is CONTEXT, never evidence. Nothing here writes to evidence_link,
  confidence_history or the Steward; confidence is never changed. A
  candidate near a recorded site is a likely REDISCOVERY (good for
  calibration), not a stronger candidate.
- "Not in this gazetteer" is NOT "new discovery". The source covers only
  a selection of sites, and its point positions were placed by eye on
  satellite images (precision unknown, plausibly a few hundred metres).
- Where the gazetteer is sparse (measured: thin across Iran), the label
  says so explicitly instead of implying the place is unrecorded.

LABELS (thresholds are plain constants below, deliberately simple):
  NEAR_KNOWN_SITE          nearest recorded site/extent <= NEAR_M
  NOT_IN_GAZETTEER         nothing within NEAR_M, but >= SPARSE_MIN points
                           within DENSITY_RADIUS_KM (coverage exists here)
  GAZETTEER_SPARSE         fewer than SPARSE_MIN points within
                           DENSITY_RADIUS_KM -- cannot judge

City EXTENTS (36 outlines of large ancient cities) count as distance 0
when the coordinate lies inside the outline. One source entry ("Wall 1")
is an open line, not an area; it is measured as distance-to-line only.

Also provides sites_in_bbox() for F2 (self-calibration), not used by
the UI yet.
"""

from __future__ import annotations

import json
import math

import known_sites_data as data

NEAR_M = 1000.0
DENSITY_RADIUS_KM = 25.0
SPARSE_MIN = 3
CELL_DEG = 0.25

LABEL_NEAR = "NEAR_KNOWN_SITE"
LABEL_NOT_IN = "NOT_IN_GAZETTEER"
LABEL_SPARSE = "GAZETTEER_SPARSE"

_EARTH_R = 6371008.8

_points = None      # list of dicts: kind, name, lat, lon
_extents = None     # list of dicts: name, verts [(lat, lon)], closed
_grid = None        # {(ci, cj): [point index, ...]}
_cache = {}         # (lat5, lon5, k) -> annotate() result


def _cell(lat: float, lon: float):
    return (int(math.floor(lat / CELL_DEG)), int(math.floor(lon / CELL_DEG)))


def _load():
    global _points, _extents, _grid
    if _points is not None:
        return
    pts = []
    for line in data.POINTS.splitlines():
        line = line.strip()
        if not line:
            continue
        kind, name, lat, lon = line.split("|")
        pts.append({"kind": kind, "name": name, "lat": float(lat), "lon": float(lon)})
    exts = []
    for line in data.EXTENTS.splitlines():
        line = line.strip()
        if not line:
            continue
        name, coords = line.split("|", 1)
        verts = []
        for pair in coords.split(";"):
            la, lo = pair.split(",")
            verts.append((float(la), float(lo)))
        closed = len(verts) >= 4 and verts[0] == verts[-1]
        exts.append({"name": name, "verts": verts, "closed": closed})
    grid = {}
    for i, p in enumerate(pts):
        grid.setdefault(_cell(p["lat"], p["lon"]), []).append(i)
    _points, _extents, _grid = pts, exts, grid


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def _to_local(lat0: float, lon0: float, lat: float, lon: float):
    """Equirectangular metres around (lat0, lon0); accurate to well under
    1% at the tens-of-km scale used here."""
    x = math.radians(lon - lon0) * _EARTH_R * math.cos(math.radians(lat0))
    y = math.radians(lat - lat0) * _EARTH_R
    return x, y


def _seg_dist(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def _extent_distance_m(lat: float, lon: float, ext: dict) -> float:
    """0 if inside a closed outline, else distance to the nearest edge."""
    pts = [_to_local(lat, lon, la, lo) for la, lo in ext["verts"]]
    if ext["closed"]:
        inside = False
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            if (y1 > 0) != (y2 > 0):
                xint = x1 + (0 - y1) * (x2 - x1) / (y2 - y1)
                if xint > 0:
                    inside = not inside
        if inside:
            return 0.0
    best = float("inf")
    for i in range(len(pts) - 1):
        best = min(best, _seg_dist(0.0, 0.0, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]))
    return best


def _points_within(lat: float, lon: float, radius_m: float):
    """(distance_m, point) for all points within radius_m, via the grid."""
    _load()
    dlat = radius_m / 111000.0
    dlon = radius_m / (111000.0 * max(0.05, math.cos(math.radians(lat))))
    c0 = _cell(lat - dlat, lon - dlon)
    c1 = _cell(lat + dlat, lon + dlon)
    out = []
    for ci in range(c0[0], c1[0] + 1):
        for cj in range(c0[1], c1[1] + 1):
            for idx in _grid.get((ci, cj), ()):
                p = _points[idx]
                d = haversine_m(lat, lon, p["lat"], p["lon"])
                if d <= radius_m:
                    out.append((d, p))
    out.sort(key=lambda t: t[0])
    return out


def display_name(p: dict) -> str:
    if p.get("kind") == "N":
        return "unnamed site (source region code %s)" % p["name"]
    return p["name"]


def annotate(lat: float, lon: float, k: int = 3) -> dict:
    """Factual known-site context for one coordinate. Never raises on a
    valid float pair; returns the label, the k nearest recorded points
    (within 50 km), any city outline within NEAR_M, and the local
    gazetteer density used to decide GAZETTEER_SPARSE."""
    _load()
    lat, lon = float(lat), float(lon)
    key = (round(lat, 5), round(lon, 5), k)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    # Search the density radius first; widen to 50 km only if empty.
    # Keeps list loads fast in dense areas (Mesopotamia) without losing
    # the "nearest within 50 km" answer in sparse ones.
    nearby = _points_within(lat, lon, DENSITY_RADIUS_KM * 1000.0)
    if not nearby:
        nearby = _points_within(lat, lon, 50000.0)
    nearest = [{
        "name": display_name(p),
        "kind": p["kind"],
        "lat": p["lat"],
        "lon": p["lon"],
        "distance_m": round(d, 1),
    } for d, p in nearby[:k]]

    extent_hits = []
    for ext in _extents:
        # cheap reject: first vertex more than 30 km away
        la0, lo0 = ext["verts"][0]
        if haversine_m(lat, lon, la0, lo0) > 30000.0:
            continue
        d = _extent_distance_m(lat, lon, ext)
        if d <= NEAR_M:
            extent_hits.append({
                "name": ext["name"],
                "distance_m": round(d, 1),
                "inside": d == 0.0,
                "kind": "city outline" if ext["closed"] else "line feature",
            })
    extent_hits.sort(key=lambda e: e["distance_m"])

    density = sum(1 for d, _ in nearby if d <= DENSITY_RADIUS_KM * 1000.0)

    best_name, best_d = None, None
    if nearest:
        best_name, best_d = nearest[0]["name"], nearest[0]["distance_m"]
    if extent_hits and (best_d is None or extent_hits[0]["distance_m"] < best_d):
        best_name, best_d = extent_hits[0]["name"], extent_hits[0]["distance_m"]

    if best_d is not None and best_d <= NEAR_M:
        label = LABEL_NEAR
        if extent_hits and extent_hits[0]["name"] == best_name and extent_hits[0]["inside"]:
            text = "inside recorded city outline: %s (likely rediscovery)" % best_name
        else:
            text = "%.0f m from recorded site: %s (likely rediscovery)" % (best_d, best_name)
    elif density < SPARSE_MIN:
        label = LABEL_SPARSE
        text = ("gazetteer too sparse here to judge (%d recorded points within %d km)"
                % (density, int(DENSITY_RADIUS_KM)))
    else:
        label = LABEL_NOT_IN
        if best_d is not None:
            text = ("not in gazetteer: nearest recorded site %.1f km (%s)"
                    % (best_d / 1000.0, best_name))
        else:
            text = "not in gazetteer: no recorded site within 50 km"

    result = {
        "label": label,
        "text": text,
        "nearest_name": best_name,
        "nearest_distance_m": best_d,
        "nearest": nearest,
        "extents_within_near": extent_hits,
        "density_points": density,
        "density_radius_km": DENSITY_RADIUS_KM,
        "near_threshold_m": NEAR_M,
        "source": data.SOURCE_CITATION,
        "source_license": data.SOURCE_LICENSE,
    }
    if len(_cache) < 20000:
        _cache[key] = result
    return result


def annotate_json(lat: float, lon: float) -> str:
    try:
        return json.dumps(annotate(lat, lon))
    except Exception as e:
        return json.dumps({"error": "known-site lookup failed: %s" % e})


def sites_in_bbox(south: float, west: float, north: float, east: float, include_unnamed: bool = True) -> list:
    """All recorded points inside a lat/lon box (for F2 self-calibration)."""
    _load()
    out = []
    for p in _points:
        if south <= p["lat"] <= north and west <= p["lon"] <= east:
            if include_unnamed or p["kind"] == "S":
                out.append(dict(p, display_name=display_name(p)))
    return out
