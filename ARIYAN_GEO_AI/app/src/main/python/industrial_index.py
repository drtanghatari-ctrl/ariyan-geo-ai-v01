"""
industrial_index.py  (ind-v1, 2026-10-07)

OFFLINE INDUSTRIAL CHECK for the cc-v1 HIGH rule, step 6: "no industrial
site within 300 m".

WHY: rows 3 and 5 of the Ctesiphon review were an industrial tank farm that
scored a raw 0.90 from DEM and thermal agreeing. Land cover (WorldCover)
did not catch it. Storage tanks, silos and factories make round, raised,
warm, radar-bright objects -- exactly what the detectors look for.

DATA: industrial_osm_data.py, bundled with the app, generated once from the
Geofabrik OpenStreetMap extract of Iran (iran-261006.osm.pbf, data as of
2026-10-06, md5 3c7753276b34731017c5f1a6aef6ab79, verified against
Geofabrik's published md5). Tags kept, exactly as frozen in the cc-v1 plan:
  landuse=industrial, man_made=storage_tank, man_made=silo,
  man_made=works, power=plant
24,256 features. Each is stored as the bounding box of its mapped outline.
No network is ever used here (save-once rule): every check uses the same
frozen data, recorded by its SHA-256 in SOURCE.

DISTANCE: from the candidate to the feature's BOUNDING BOX (0 inside it).
A box is never smaller than the outline, so this distance is never larger
than the true distance: an error can only flag MORE, never less
(fail-closed).

RESULTS (check()):
  CLEAR            no feature within the radius, inside OSM Iran coverage
  INDUSTRIAL_NEAR  at least one feature within the radius (listed)
  OUTSIDE_COVERAGE the point is outside the Iran extract -- no data, so the
                   cc-v1 rule must treat it as NOT cleared (fail-closed)

HONEST LIMITS: OpenStreetMap is mapped by volunteers. An unmapped tank farm
is invisible here, so CLEAR means "nothing industrial is MAPPED within
300 m", not "nothing industrial exists". The data is a 2026-10-06 snapshot.
Data (c) OpenStreetMap contributors, ODbL 1.0.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import industrial_osm_data as _data

VERSION = "ind-v1"
DEFAULT_RADIUS_M = 300.0
CELL_DEG = 0.05

STATUS_CLEAR = "CLEAR"
STATUS_NEAR = "INDUSTRIAL_NEAR"
STATUS_OUTSIDE = "OUTSIDE_COVERAGE"

_grid: Optional[Dict[Tuple[int, int], List[int]]] = None


def _cell(lat: float, lon: float) -> Tuple[int, int]:
    return int(math.floor(lat / CELL_DEG)), int(math.floor(lon / CELL_DEG))


def _build_grid() -> Dict[Tuple[int, int], List[int]]:
    global _grid
    if _grid is None:
        g: Dict[Tuple[int, int], List[int]] = {}
        for i, (_k, la0, lo0, la1, lo1) in enumerate(_data.FEATURES):
            r0, c0 = _cell(la0, lo0)
            r1, c1 = _cell(la1, lo1)
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    g.setdefault((r, c), []).append(i)
        _grid = g
    return _grid


def in_coverage(lat: float, lon: float) -> bool:
    """Point-in-polygon (even-odd) against the Geofabrik iran.poly ring."""
    ring = _data.COVERAGE
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        yi, xi = ring[i]
        yj, xj = ring[j]
        if (yi > lat) != (yj > lat):
            x = xi + (lat - yi) * (xj - xi) / (yj - yi)
            if lon < x:
                inside = not inside
        j = i
    return inside


def _dist_to_box_m(lat: float, lon: float, la0: float, lo0: float, la1: float, lo1: float) -> float:
    dlat = max(la0 - lat, 0.0, lat - la1)
    dlon = max(lo0 - lon, 0.0, lon - lo1)
    dy = dlat * 110574.0
    dx = dlon * 111320.0 * math.cos(math.radians(lat))
    return math.hypot(dx, dy)


def features_within(lat: float, lon: float, radius_m: float = DEFAULT_RADIUS_M) -> List[Dict[str, Any]]:
    """Every mapped industrial feature whose box is within radius_m,
    nearest first: [{"kind", "distance_m"}]."""
    g = _build_grid()
    pad_lat = radius_m / 110574.0
    pad_lon = radius_m / (111320.0 * max(0.01, math.cos(math.radians(lat))))
    r0, c0 = _cell(lat - pad_lat, lon - pad_lon)
    r1, c1 = _cell(lat + pad_lat, lon + pad_lon)
    seen = set()
    out = []
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            for i in g.get((r, c), ()):
                if i in seen:
                    continue
                seen.add(i)
                k, la0, lo0, la1, lo1 = _data.FEATURES[i]
                d = _dist_to_box_m(lat, lon, la0, lo0, la1, lo1)
                if d <= radius_m:
                    out.append({"kind": _data.KINDS[k], "distance_m": round(d, 1)})
    out.sort(key=lambda f: f["distance_m"])
    return out


def check(lat: float, lon: float, radius_m: float = DEFAULT_RADIUS_M) -> Dict[str, Any]:
    """The cc-v1 step-6 answer for one point. Never raises for a valid
    float pair; never uses the network."""
    base = {"method": VERSION, "radius_m": radius_m,
            "source_file": _data.SOURCE["file"], "source_sha256": _data.SOURCE["sha256"]}
    if not in_coverage(lat, lon):
        return dict(base, status=STATUS_OUTSIDE, features=[],
                    text="outside the OpenStreetMap Iran extract -- industrial check not possible")
    feats = features_within(lat, lon, radius_m)
    if feats:
        f = feats[0]
        return dict(base, status=STATUS_NEAR, features=feats[:10],
                    text="%s mapped %.0f m away (OpenStreetMap)" % (f["kind"], f["distance_m"]))
    return dict(base, status=STATUS_CLEAR, features=[],
                text="no industrial site mapped within %.0f m (OpenStreetMap, %s)"
                     % (radius_m, _data.SOURCE["data_date"]))
