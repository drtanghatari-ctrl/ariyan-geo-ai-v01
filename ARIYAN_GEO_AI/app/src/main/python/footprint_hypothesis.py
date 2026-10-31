"""
footprint_hypothesis.py -- ef-v2 (2026-10-31): the user's own HYPOTHESIZED
bodies in 3D: a footprint drawn on the map (a polygon, its corners stored by
latitude/longitude so it belongs to the ground) plus a depth range below the
ground surface, e.g. "kiln?" 0.5-2 m, "wall?" 1-3 m, "natural knoll?" 0-4 m.

Several may sit side by side or overlap; the app never chooses between them
(no artificial closure) and never creates one by itself. They are drawn on
the map and in the evidence volume (evidence_volume.py); where two or more
overlap at the same depth the block is shown as CONTESTED. They are not
evidence and never change a candidate's status, review or confidence.

Storage is append-only, like section_hypothesis.py: one row per footprint,
ADDED / WITHDRAWN events (the newest decides the status), timeline entries.
"""
from __future__ import annotations

import json
import math
import uuid
from typing import Any, Dict, List

import grand_project_db as db

VERSION = "fph-v1"
KIND = "HYPOTHESIZED"
MAX_DEPTH_M = 50.0
MAX_VERTICES = 40
MAX_LABEL = 80
MAX_NOTE = 500

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS footprint_hypothesis (
        id               TEXT PRIMARY KEY,
        candidate_id     TEXT NOT NULL,
        grand_project_id TEXT NOT NULL,
        created_at       TEXT NOT NULL,
        label            TEXT NOT NULL,
        note             TEXT NOT NULL DEFAULT '',
        polygon_json     TEXT NOT NULL,
        area_m2          REAL NOT NULL,
        depth_top_m      REAL NOT NULL,
        depth_bottom_m   REAL NOT NULL,
        kind             TEXT NOT NULL DEFAULT 'HYPOTHESIZED',
        version          TEXT NOT NULL,
        FOREIGN KEY (candidate_id) REFERENCES candidate(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS footprint_hypothesis_event (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        hypothesis_id  TEXT NOT NULL,
        event          TEXT NOT NULL,
        reason         TEXT NOT NULL DEFAULT '',
        occurred_at    TEXT NOT NULL,
        FOREIGN KEY (hypothesis_id) REFERENCES footprint_hypothesis(id)
    )
    """,
]


def _conn(db_root: str):
    conn = db.get_connection(db_root)
    db.initialize_schema(conn)
    for stmt in _SCHEMA:
        conn.execute(stmt)
    return conn


def polygon_area_m2(points_latlon: List[List[float]]) -> float:
    """Shoelace area on a local flat projection around the polygon (adequate
    for footprints of a few hundred metres)."""
    if len(points_latlon) < 3:
        return 0.0
    lat0 = sum(p[0] for p in points_latlon) / len(points_latlon)
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    xy = [(p[1] * kx, p[0] * ky) for p in points_latlon]
    s = 0.0
    for i in range(len(xy)):
        x1, y1 = xy[i]
        x2, y2 = xy[(i + 1) % len(xy)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def validate(label: str, points_latlon: List[List[float]], depth_top_m: float, depth_bottom_m: float,
             note: str = "") -> List[str]:
    p = []
    if not (label or "").strip():
        p.append("a label is required (for example: kiln?)")
    if len((label or "").strip()) > MAX_LABEL:
        p.append("label longer than %d characters" % MAX_LABEL)
    if len(note or "") > MAX_NOTE:
        p.append("note longer than %d characters" % MAX_NOTE)
    if not (3 <= len(points_latlon) <= MAX_VERTICES):
        p.append("a footprint needs 3 to %d corners" % MAX_VERTICES)
    elif polygon_area_m2(points_latlon) < 1.0:
        p.append("the footprint has no area (corners in a line or on top of each other)")
    for v in (depth_top_m, depth_bottom_m):
        if v is None or not math.isfinite(float(v)):
            p.append("both depths must be filled in")
            return p
    if not (0.0 <= depth_top_m < depth_bottom_m <= MAX_DEPTH_M):
        p.append("depths must satisfy 0 <= top < bottom <= %g m below the ground" % MAX_DEPTH_M)
    return p


def add(db_root: str, candidate_id: str, points_latlon: List[List[float]], label: str,
        depth_top_m: float, depth_bottom_m: float, note: str = "") -> str:
    probs = validate(label, points_latlon, depth_top_m, depth_bottom_m, note)
    if probs:
        raise ValueError("; ".join(probs))
    cand = db.get_candidate(db_root, candidate_id)
    if cand is None:
        raise LookupError("candidate not found")
    hid = uuid.uuid4().hex
    now = db._now_iso()
    area = polygon_area_m2(points_latlon)
    conn = _conn(db_root)
    try:
        with conn:
            conn.execute(
                "INSERT INTO footprint_hypothesis (id, candidate_id, grand_project_id, created_at, label, note, "
                "polygon_json, area_m2, depth_top_m, depth_bottom_m, kind, version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (hid, candidate_id, cand["grand_project_id"], now, label.strip(), (note or "").strip(),
                 json.dumps([[float(a), float(b)] for a, b in points_latlon]), area,
                 float(depth_top_m), float(depth_bottom_m), KIND, VERSION))
            conn.execute("INSERT INTO footprint_hypothesis_event (hypothesis_id, event, reason, occurred_at) "
                         "VALUES (?, 'ADDED', '', ?)", (hid, now))
    finally:
        conn.close()
    db.log_timeline_event(
        db_root, cand["grand_project_id"], "FOOTPRINT_HYPOTHESIS_ADDED", "candidate", candidate_id,
        "HYPOTHESIZED by user (%s): '%s', footprint %.0f m2, %.1f-%.1f m below ground. "
        "Not evidence; does not change status or confidence." % (hid[:8], label.strip(), area,
                                                                 depth_top_m, depth_bottom_m))
    return hid


def withdraw(db_root: str, hypothesis_id: str, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("a reason is required to withdraw a hypothesis")
    conn = _conn(db_root)
    try:
        row = conn.execute("SELECT candidate_id, grand_project_id, label FROM footprint_hypothesis WHERE id = ?",
                           (hypothesis_id,)).fetchone()
        if row is None:
            raise LookupError("hypothesis not found")
        with conn:
            conn.execute("INSERT INTO footprint_hypothesis_event (hypothesis_id, event, reason, occurred_at) "
                         "VALUES (?, 'WITHDRAWN', ?, ?)", (hypothesis_id, reason.strip(), db._now_iso()))
    finally:
        conn.close()
    db.log_timeline_event(db_root, row["grand_project_id"], "FOOTPRINT_HYPOTHESIS_WITHDRAWN", "candidate",
                          row["candidate_id"], "withdrawn by user (%s): '%s'. Reason: %s"
                          % (hypothesis_id[:8], row["label"], reason.strip()))


def list_for_candidate(db_root: str, candidate_id: str, include_withdrawn: bool = False) -> List[Dict[str, Any]]:
    conn = _conn(db_root)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM footprint_hypothesis WHERE candidate_id = ? ORDER BY created_at", (candidate_id,))]
        for r in rows:
            r["polygon"] = json.loads(r.pop("polygon_json"))
            ev = conn.execute("SELECT event, reason FROM footprint_hypothesis_event WHERE hypothesis_id = ? "
                              "ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
            r["status"] = "WITHDRAWN" if ev is not None and ev["event"] == "WITHDRAWN" else "ACTIVE"
            r["status_reason"] = ev["reason"] if ev is not None else ""
    finally:
        conn.close()
    return rows if include_withdrawn else [r for r in rows if r["status"] == "ACTIVE"]
