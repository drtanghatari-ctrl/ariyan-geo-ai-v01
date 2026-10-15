"""
industrial_label.py  (ind-label-v1, 2026-10-15)

LABEL + PASS 2 ORDER ONLY. Approved by the user 2026-10-15 after the
read-only d3-v1 diagnostic:
  - 744 Iran candidates lay within 300 m of mapped industry; 626 were not
    rejected (about 550 of them from jobs where land cover was never read).
  - 5 of 6 satellite spot-checks were real industry (silos, tank farms,
    factories); 1 was a village edge.
  - 0 current candidates lay near both industry and a recorded site, BUT
    across Iran 5 gazetteer sites lie within 300 m of mapped industry and 2
    (Tepe Nush-i Jan, Ishan ed-Dowweh) sit inside an industrial box. A
    reject rule would damage real sites, so there is none.

WHAT IT DOES:
  1. label(lat, lon): one short line, "mapped industry X m (...)", for the
     candidate row, the detail view and the report.
  2. deferred(lat, lon): True when mapped industry is within 300 m. Pass 2
     puts those candidates AFTER every other eligible candidate, so live DEM
     budget goes to open ground first. They are still refined if budget is
     left, and a user can always pick them by hand.

WHAT IT NEVER DOES: reject, hide, or change any status, review, confidence
or evidence row. A lookup failure means "no label, not deferred" -- it can
never break a list or a refinement.

DATA: industrial_index.py (ind-v1, frozen; OpenStreetMap Geofabrik extract
iran-261006.osm.pbf, data as of 2026-10-06, ODbL 1.0). The distance is to
the feature's BOUNDING BOX, so it can over-reach a little (d3 found a
village edge flagged this way). Outside the Iran extract there is no data:
no label and not deferred.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

LABEL_VERSION = "ind-label-v1"
RADIUS_M = 300.0


def nearest(lat: Any, lon: Any) -> Optional[Dict[str, Any]]:
    """{"kind", "distance_m"} of the nearest mapped industrial feature
    within RADIUS_M, or None (none mapped, outside the Iran extract, no
    coordinates, or any failure). Never raises."""
    try:
        lat, lon = float(lat), float(lon)
        import industrial_index as ii
        if not ii.in_coverage(lat, lon):
            return None
        feats = ii.features_within(lat, lon, RADIUS_M)
        return dict(feats[0]) if feats else None
    except Exception:
        return None


def _data_date() -> str:
    try:
        import industrial_osm_data as d
        return str(d.SOURCE.get("data_date") or "")
    except Exception:
        return ""


def text_for(n: Optional[Dict[str, Any]]) -> Optional[str]:
    if not n:
        return None
    d = float(n.get("distance_m") or 0.0)
    where = "inside its mapped box" if d <= 0.0 else "%.0f m" % d
    date = _data_date()
    src = "OpenStreetMap %s" % date if date else "OpenStreetMap"
    return "mapped industry %s (%s, %s) -- context only, not a rejection" % (
        where, n.get("kind") or "?", src)


def label(lat: Any, lon: Any) -> Optional[str]:
    """The one-line label, or None when nothing is mapped within 300 m."""
    return text_for(nearest(lat, lon))


def deferred(lat: Any, lon: Any) -> bool:
    return nearest(lat, lon) is not None


def detail(lat: Any, lon: Any) -> Dict[str, Any]:
    """Full context for the candidate detail view (never raises)."""
    out: Dict[str, Any] = {"method": LABEL_VERSION, "radius_m": RADIUS_M,
                           "text": None, "features": [], "deferred_in_pass2": False}
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        out["text"] = "no coordinates"
        return out
    try:
        import industrial_index as ii
        c = ii.check(la, lo, RADIUS_M)
    except Exception as e:
        out["text"] = "industrial lookup failed: %s" % type(e).__name__
        return out
    out["status"] = c.get("status")
    out["source_file"] = c.get("source_file")
    if c.get("status") == ii.STATUS_NEAR:
        out["features"] = list(c.get("features") or [])[:5]
        out["text"] = text_for(out["features"][0] if out["features"] else None)
        out["deferred_in_pass2"] = True
    else:
        out["text"] = c.get("text")
    return out
