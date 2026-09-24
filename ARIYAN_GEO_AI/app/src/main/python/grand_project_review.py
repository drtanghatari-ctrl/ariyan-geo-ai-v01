"""
grand_project_review.py

Part of ARIYAN GEO AI's GRAND PROJECT FRAMEWORK -- Phase 3 (candidate
lifecycle + permanent retention), started 2026-09-24.

PURPOSE: lets the USER record their own judgement about a candidate
(Open / Supported / Rejected / Inconclusive, always with a written
reason) and about a whole Wide-Area Search job (Trusted / Corrupted /
Unverified), so that what has been learned by hand -- satellite checks
showing a tank farm or a fish pond, jobs built with the old broken COG
reader -- lives in the database instead of only in notes.

WHAT THIS MODULE DOES NOT DO:
- It never changes Steward confidence (confidence_band/numeric,
  confidence_history). A review is the user's judgement, a Steward
  confidence is a computed inference; the two stay separate (Fact vs
  Inference vs Hypothesis separation from the Grand Project roadmap).
- It never deletes anything. Rejected candidates keep their row, their
  evidence and their confidence history forever.
- It never decides a status by itself. Every status change requires an
  explicit call with a non-empty, user-written reason.

STORAGE: two NEW append-only tables, created here with CREATE TABLE IF
NOT EXISTS (so grand_project_db.py itself is untouched):
- candidate_review: one row per status change (previous_status,
  new_status, reason, reviewed_at). Never updated or deleted.
- job_trust: one row per trust change for a wide_area_search_job.
  The CURRENT trust of a job is its newest row. Never updated/deleted.
The candidate row's own `status` column (already present, default
'GENERATED', previously never changed) is kept in step as the
"current" value, the same two-tier pattern as confidence_history +
candidate.confidence_band.

'GENERATED' (the existing default) is shown to the user as Open.

Kotlin-facing *_json functions at the bottom return JSON strings and
report expected problems as {"error": "..."} instead of raising, the
same convention as grand_project_query_mobile.py.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import grand_project_db as db

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

STATUS_OPEN = "GENERATED"  # existing default value in candidate.status
STATUS_SUPPORTED = "SUPPORTED"
STATUS_REJECTED = "REJECTED"
STATUS_INCONCLUSIVE = "INCONCLUSIVE"

# What the user may set. "OPEN" is accepted as input and stored as the
# existing default value, so re-opening returns a candidate to exactly
# the state every untouched candidate is in.
_STATUS_INPUT = {
    "OPEN": STATUS_OPEN,
    "GENERATED": STATUS_OPEN,
    "SUPPORTED": STATUS_SUPPORTED,
    "REJECTED": STATUS_REJECTED,
    "INCONCLUSIVE": STATUS_INCONCLUSIVE,
}

STATUS_LABELS = {
    STATUS_OPEN: "Open",
    STATUS_SUPPORTED: "Supported",
    STATUS_REJECTED: "Rejected",
    STATUS_INCONCLUSIVE: "Inconclusive",
}

TRUST_TRUSTED = "TRUSTED"
TRUST_CORRUPTED = "CORRUPTED"
TRUST_UNVERIFIED = "UNVERIFIED"
_TRUST_VALUES = (TRUST_TRUSTED, TRUST_CORRUPTED, TRUST_UNVERIFIED)

MIN_REASON_CHARS = 3
MIN_ID_PREFIX_CHARS = 6


class ReviewError(ValueError):
    """Bad input (unknown status, empty reason, unknown/ambiguous id)."""


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_REVIEW_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS candidate_review (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id     TEXT NOT NULL,
        previous_status  TEXT,
        new_status       TEXT NOT NULL,
        reason           TEXT NOT NULL,
        reviewed_at      TEXT NOT NULL,
        FOREIGN KEY (candidate_id) REFERENCES candidate(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS job_trust (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id       TEXT NOT NULL,
        trust        TEXT NOT NULL,
        reason       TEXT NOT NULL,
        recorded_at  TEXT NOT NULL,
        FOREIGN KEY (job_id) REFERENCES wide_area_search_job(id)
    )
    """,
]


def _connect(db_root: str):
    conn = db.get_connection(db_root)
    db.initialize_schema(conn)
    with conn:
        for statement in _REVIEW_SCHEMA:
            conn.execute(statement)
    return conn


def _clean_reason(reason: Any) -> str:
    text = str(reason or "").strip()
    if len(text) < MIN_REASON_CHARS:
        raise ReviewError(
            f"A reason is required (at least {MIN_REASON_CHARS} characters).")
    return text


def _resolve_id(conn, table: str, ref: Any) -> str:
    """Full id, or a unique prefix of at least MIN_ID_PREFIX_CHARS hex
    characters, resolved against `table`.id. Raises ReviewError when the
    reference is too short, unknown or ambiguous -- never guesses."""
    text = str(ref or "").strip().lower()
    if len(text) < MIN_ID_PREFIX_CHARS:
        raise ReviewError(
            f"Id {text!r} is too short (use at least {MIN_ID_PREFIX_CHARS} characters).")
    rows = conn.execute(
        f"SELECT id FROM {table} WHERE id LIKE ? LIMIT 3", (text + "%",)
    ).fetchall()
    if not rows:
        raise ReviewError(f"No {table} matches {text!r}.")
    if len(rows) > 1:
        exact = [r["id"] for r in rows if r["id"] == text]
        if exact:
            return exact[0]
        raise ReviewError(f"{text!r} matches more than one {table}; use more characters.")
    return rows[0]["id"]


# ---------------------------------------------------------------------------
# Candidate review
# ---------------------------------------------------------------------------

def set_candidate_status(
    db_root: str, candidate_ref: str, new_status: str, reason: str
) -> Dict[str, Any]:
    """Records the user's judgement on one candidate: appends a
    candidate_review row, keeps candidate.status current, logs a
    timeline event. Returns {"candidate_id", "previous_status",
    "new_status", "reviewed_at"}. Setting the same status again is
    allowed (it records a new reason) -- the history is the point."""
    key = str(new_status or "").strip().upper()
    if key not in _STATUS_INPUT:
        raise ReviewError(
            f"Unknown status {new_status!r}; use Open, Supported, Rejected or Inconclusive.")
    status = _STATUS_INPUT[key]
    text = _clean_reason(reason)

    conn = _connect(db_root)
    try:
        candidate_id = _resolve_id(conn, "candidate", candidate_ref)
        row = conn.execute(
            "SELECT grand_project_id, status FROM candidate WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        previous = row["status"]
        grand_project_id = row["grand_project_id"]
        now = db._now_iso()
        with conn:
            conn.execute(
                """
                INSERT INTO candidate_review
                    (candidate_id, previous_status, new_status, reason, reviewed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (candidate_id, previous, status, text, now),
            )
            conn.execute(
                "UPDATE candidate SET status = ?, last_updated_at = ? WHERE id = ?",
                (status, now, candidate_id),
            )
    finally:
        conn.close()

    try:
        db.log_timeline_event(
            db_root, grand_project_id, "CANDIDATE_REVIEWED",
            related_entity_type="candidate", related_entity_id=candidate_id,
            description=(
                f"User review: {STATUS_LABELS.get(previous, previous)} -> "
                f"{STATUS_LABELS[status]}. Reason: {text}"
            ),
        )
    except Exception:
        pass  # the review itself is already stored; a timeline failure never undoes it

    return {
        "candidate_id": candidate_id,
        "previous_status": previous,
        "new_status": status,
        "reviewed_at": now,
    }


def get_candidate_review_history(db_root: str, candidate_ref: str) -> List[Dict[str, Any]]:
    """Every review of one candidate, oldest first."""
    conn = _connect(db_root)
    try:
        candidate_id = _resolve_id(conn, "candidate", candidate_ref)
        rows = conn.execute(
            """
            SELECT id, candidate_id, previous_status, new_status, reason, reviewed_at
            FROM candidate_review WHERE candidate_id = ? ORDER BY id
            """,
            (candidate_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Job trust
# ---------------------------------------------------------------------------

def set_job_trust(db_root: str, job_ref: str, trust: str, reason: str) -> Dict[str, Any]:
    """Records the user's trust judgement on a whole Wide-Area Search job
    (append-only). Returns {"job_id", "trust", "recorded_at"}."""
    value = str(trust or "").strip().upper()
    if value not in _TRUST_VALUES:
        raise ReviewError(f"Unknown trust {trust!r}; use Trusted, Corrupted or Unverified.")
    text = _clean_reason(reason)

    conn = _connect(db_root)
    try:
        job_id = _resolve_id(conn, "wide_area_search_job", job_ref)
        grand_project_id = conn.execute(
            "SELECT grand_project_id FROM wide_area_search_job WHERE id = ?", (job_id,)
        ).fetchone()["grand_project_id"]
        now = db._now_iso()
        with conn:
            conn.execute(
                "INSERT INTO job_trust (job_id, trust, reason, recorded_at) VALUES (?, ?, ?, ?)",
                (job_id, value, text, now),
            )
    finally:
        conn.close()

    try:
        db.log_timeline_event(
            db_root, grand_project_id, "JOB_TRUST_SET",
            related_entity_type="wide_area_search_job", related_entity_id=job_id,
            description=f"User marked job {job_id[:6]} as {value}. Reason: {text}",
        )
    except Exception:
        pass

    return {"job_id": job_id, "trust": value, "recorded_at": now}


def _current_job_trust(conn) -> Dict[str, Dict[str, Any]]:
    """job_id -> newest job_trust row (as dict)."""
    rows = conn.execute(
        """
        SELECT t.job_id, t.trust, t.reason, t.recorded_at
        FROM job_trust t
        JOIN (SELECT job_id, MAX(id) AS max_id FROM job_trust GROUP BY job_id) m
          ON t.id = m.max_id
        """
    ).fetchall()
    return {r["job_id"]: dict(r) for r in rows}


def list_job_trust(db_root: str) -> List[Dict[str, Any]]:
    """Current trust of every job that has ever been marked."""
    conn = _connect(db_root)
    try:
        return sorted(_current_job_trust(conn).values(), key=lambda r: r["recorded_at"])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Per-candidate review summary (for the Candidates tab)
# ---------------------------------------------------------------------------

def review_summary_for_project(db_root: str, grand_project_id: str) -> Dict[str, Dict[str, Any]]:
    """candidate_id -> {"status", "status_label", "job_id", "job_trust",
    "job_trust_reason", "last_review_reason"} for every candidate in the
    project. job_id is traced through wide_area_search_tile
    (candidate.investigation_id = tile.investigation_id); it is null for
    candidates that did not come from a Wide-Area Search tile. job_trust
    is null when the job has never been marked."""
    conn = _connect(db_root)
    try:
        trust = _current_job_trust(conn)
        rows = conn.execute(
            """
            SELECT c.id, c.status, t.job_id
            FROM candidate c
            LEFT JOIN wide_area_search_tile t ON t.investigation_id = c.investigation_id
            WHERE c.grand_project_id = ?
            """,
            (grand_project_id,),
        ).fetchall()
        last_reason = {
            r["candidate_id"]: r["reason"]
            for r in conn.execute(
                """
                SELECT r.candidate_id, r.reason FROM candidate_review r
                JOIN (SELECT candidate_id, MAX(id) AS max_id
                      FROM candidate_review GROUP BY candidate_id) m
                  ON r.id = m.max_id
                """
            ).fetchall()
        }
        out: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            job_id = r["job_id"]
            t = trust.get(job_id) if job_id else None
            out[r["id"]] = {
                "status": r["status"],
                "status_label": STATUS_LABELS.get(r["status"], r["status"]),
                "job_id": job_id,
                "job_trust": t["trust"] if t else None,
                "job_trust_reason": t["reason"] if t else None,
                "last_review_reason": last_reason.get(r["id"]),
            }
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Kotlin-facing JSON boundary
# ---------------------------------------------------------------------------

def _json_call(fn, *args) -> str:
    try:
        return json.dumps(fn(*args))
    except ReviewError as e:
        return json.dumps({"error": str(e)})


def set_candidate_status_json(db_root: str, candidate_ref: str, new_status: str, reason: str) -> str:
    return _json_call(set_candidate_status, db_root, candidate_ref, new_status, reason)


def get_candidate_review_history_json(db_root: str, candidate_ref: str) -> str:
    return _json_call(get_candidate_review_history, db_root, candidate_ref)


def set_job_trust_json(db_root: str, job_ref: str, trust: str, reason: str) -> str:
    return _json_call(set_job_trust, db_root, job_ref, trust, reason)


def list_job_trust_json(db_root: str) -> str:
    return _json_call(list_job_trust, db_root)


def review_summary_for_project_json(db_root: str, grand_project_id: str) -> str:
    return _json_call(review_summary_for_project, db_root, grand_project_id)
