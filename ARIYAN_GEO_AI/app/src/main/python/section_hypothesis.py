"""
section_hypothesis.py -- cut-v2 part 2 (2026-10-31): HYPOTHESIZED shapes on
the 3D cut face, drawn by the USER only.

A section hypothesis is the user's own idea of what MIGHT lie below the
ground along a profile line A-A', for one candidate, e.g.
    "mud-brick wall?"  from 40 to 90 m along A->A', 1 to 3 m below the ground.
The app never creates one by itself, never infers one, and never lets one
change a candidate's status, review or confidence. It is drawn as a purple
shape labelled HYPOTHESIZED on the cut face, nothing more.

Storage (append-only, like candidate_review):
  section_hypothesis        one row per hypothesis, never edited
  section_hypothesis_event  ADDED / WITHDRAWN rows; the newest decides status
The line is stored by the latitude/longitude of A and A' so the hypothesis
belongs to the ground, not to a screen window. Every add/withdraw is also
written to the project timeline.
"""
from __future__ import annotations

import math
import uuid
from typing import Any, Dict, List, Optional

import grand_project_db as db

VERSION = "shyp-v1"
MAX_DEPTH_M = 50.0          # deeper than this is not a near-surface archaeology question
MAX_LABEL = 80
MAX_NOTE = 500
KIND = "HYPOTHESIZED"

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS section_hypothesis (
        id               TEXT PRIMARY KEY,
        candidate_id     TEXT NOT NULL,
        grand_project_id TEXT NOT NULL,
        created_at       TEXT NOT NULL,
        label            TEXT NOT NULL,
        note             TEXT NOT NULL DEFAULT '',
        a_lat REAL NOT NULL, a_lon REAL NOT NULL,
        b_lat REAL NOT NULL, b_lon REAL NOT NULL,
        line_length_m    REAL NOT NULL,
        along_from_m     REAL NOT NULL,
        along_to_m       REAL NOT NULL,
        depth_top_m      REAL NOT NULL,
        depth_bottom_m   REAL NOT NULL,
        kind             TEXT NOT NULL DEFAULT 'HYPOTHESIZED',
        version          TEXT NOT NULL,
        FOREIGN KEY (candidate_id) REFERENCES candidate(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS section_hypothesis_event (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        hypothesis_id   TEXT NOT NULL,
        event           TEXT NOT NULL,
        reason          TEXT NOT NULL DEFAULT '',
        occurred_at     TEXT NOT NULL,
        FOREIGN KEY (hypothesis_id) REFERENCES section_hypothesis(id)
    )
    """,
]


def _conn(db_root: str):
    conn = db.get_connection(db_root)
    db.initialize_schema(conn)
    for stmt in _SCHEMA:
        conn.execute(stmt)
    return conn


def validate(label: str, along_from_m: float, along_to_m: float, depth_top_m: float,
             depth_bottom_m: float, line_length_m: float, note: str = "") -> List[str]:
    """Problems with a proposed hypothesis; empty list = acceptable."""
    p = []
    vals = (along_from_m, along_to_m, depth_top_m, depth_bottom_m, line_length_m)
    if any(v is None or not math.isfinite(float(v)) for v in vals):
        return ["every number must be filled in"]
    if not (label or "").strip():
        p.append("a label is required (for example: mud-brick wall?)")
    if len((label or "").strip()) > MAX_LABEL:
        p.append("label longer than %d characters" % MAX_LABEL)
    if len(note or "") > MAX_NOTE:
        p.append("note longer than %d characters" % MAX_NOTE)
    if line_length_m <= 0:
        p.append("the profile line has no length")
    if not (0.0 <= along_from_m < along_to_m <= line_length_m + 1e-6):
        p.append("'from' and 'to' must satisfy 0 <= from < to <= %.0f m (the length of A-A')" % line_length_m)
    if not (0.0 <= depth_top_m < depth_bottom_m <= MAX_DEPTH_M):
        p.append("depths must satisfy 0 <= top < bottom <= %g m below the ground line" % MAX_DEPTH_M)
    return p


def add(db_root: str, candidate_id: str, a_lat: float, a_lon: float, b_lat: float, b_lon: float,
        line_length_m: float, label: str, along_from_m: float, along_to_m: float,
        depth_top_m: float, depth_bottom_m: float, note: str = "") -> str:
    probs = validate(label, along_from_m, along_to_m, depth_top_m, depth_bottom_m, line_length_m, note)
    if probs:
        raise ValueError("; ".join(probs))
    cand = db.get_candidate(db_root, candidate_id)
    if cand is None:
        raise LookupError("candidate not found")
    hid = uuid.uuid4().hex
    now = db._now_iso()
    conn = _conn(db_root)
    try:
        with conn:
            conn.execute(
                "INSERT INTO section_hypothesis (id, candidate_id, grand_project_id, created_at, label, note, "
                "a_lat, a_lon, b_lat, b_lon, line_length_m, along_from_m, along_to_m, depth_top_m, "
                "depth_bottom_m, kind, version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (hid, candidate_id, cand["grand_project_id"], now, label.strip(), (note or "").strip(),
                 float(a_lat), float(a_lon), float(b_lat), float(b_lon), float(line_length_m),
                 float(along_from_m), float(along_to_m), float(depth_top_m), float(depth_bottom_m),
                 KIND, VERSION))
            conn.execute("INSERT INTO section_hypothesis_event (hypothesis_id, event, reason, occurred_at) "
                         "VALUES (?, 'ADDED', '', ?)", (hid, now))
    finally:
        conn.close()
    db.log_timeline_event(
        db_root, cand["grand_project_id"], "SECTION_HYPOTHESIS_ADDED", "candidate", candidate_id,
        "HYPOTHESIZED by user (%s): '%s', %.0f-%.0f m along A-A', %.1f-%.1f m below ground. "
        "Not evidence; does not change status or confidence."
        % (hid[:8], label.strip(), along_from_m, along_to_m, depth_top_m, depth_bottom_m))
    return hid


def withdraw(db_root: str, hypothesis_id: str, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("a reason is required to withdraw a hypothesis")
    conn = _conn(db_root)
    try:
        row = conn.execute("SELECT candidate_id, grand_project_id, label FROM section_hypothesis WHERE id = ?",
                           (hypothesis_id,)).fetchone()
        if row is None:
            raise LookupError("hypothesis not found")
        with conn:
            conn.execute("INSERT INTO section_hypothesis_event (hypothesis_id, event, reason, occurred_at) "
                         "VALUES (?, 'WITHDRAWN', ?, ?)", (hypothesis_id, reason.strip(), db._now_iso()))
    finally:
        conn.close()
    db.log_timeline_event(db_root, row["grand_project_id"], "SECTION_HYPOTHESIS_WITHDRAWN", "candidate",
                          row["candidate_id"], "withdrawn by user (%s): '%s'. Reason: %s"
                          % (hypothesis_id[:8], row["label"], reason.strip()))


def list_for_candidate(db_root: str, candidate_id: str, include_withdrawn: bool = False) -> List[Dict[str, Any]]:
    conn = _conn(db_root)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM section_hypothesis WHERE candidate_id = ? ORDER BY created_at", (candidate_id,))]
        for r in rows:
            ev = conn.execute("SELECT event, reason, occurred_at FROM section_hypothesis_event "
                              "WHERE hypothesis_id = ? ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
            r["status"] = "WITHDRAWN" if ev is not None and ev["event"] == "WITHDRAWN" else "ACTIVE"
            r["status_reason"] = ev["reason"] if ev is not None else ""
    finally:
        conn.close()
    return rows if include_withdrawn else [r for r in rows if r["status"] == "ACTIVE"]
