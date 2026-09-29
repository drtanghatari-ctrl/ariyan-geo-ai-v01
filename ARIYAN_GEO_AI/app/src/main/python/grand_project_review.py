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

CHANGELOG
- 2026-09-29 (roadmap R1, AUTO-REVIEW, user's request of 2026-09-24:
  the manual review process was too much to keep up with by hand).
  auto_review_project() now sets candidate status ITSELF from measured
  rules that are already stored in the database, in this order (the
  first rule that applies wins):
    1. the candidate's Wide-Area Search job is currently marked
       CORRUPTED (job_trust)                              -> Rejected
    2. the candidate is land-cover flagged (water, or trees/buildings
       >= 20 % within ~60 m; land_cover_flags.flag_reason() -- the SAME
       rule Pass 2 uses, not a copy)                       -> Rejected
    3. Pass 2 refinement markers exist and at least one was a LIVE DEM
       fetch that reproduced the anomaly                  -> Supported
    4. Pass 2 markers exist but none is a live reproduction (offline
       reproduction only, live not reproduced, or DEM source not
       recorded)                                          -> Inconclusive
    5. none of the above                                   -> Open
  Rule 4 is deliberately fail-closed: a marker written before
  2026-09-23 has no dem_source, so a reproduction it records cannot be
  counted as a live check (grand_project_refinement._refinement_history
  reports it as NOT_RECORDED); it stays Inconclusive until a new live
  refinement or a user review says otherwise.
  Guarantees:
  - A candidate that has EVER been reviewed by the user is never
    touched again by the automatic pass (user choices always win and
    are never overwritten). Rows written before this change are all
    user rows, so candidate_review gains a reviewed_by column
    ('user' / 'auto', default 'user') via ALTER TABLE ADD COLUMN.
  - Auto rows are ordinary append-only candidate_review rows with
    reviewed_by='auto' and a reason starting "[auto] ", so the existing
    screens show the tag without any Kotlin change. status_label gets
    " (auto)" appended when the current status came from the automatic
    pass.
  - A row is written only when the status (or, for an earlier auto row,
    its reason) actually changes -- never one per candidate per load.
    An untouched Open candidate that stays Open writes nothing.
  - One summary timeline event (AUTO_REVIEW) per run that changed
    anything, instead of one event per candidate.
  - Still never changes Steward confidence and never deletes anything.
  - Satellite visual checks stay optional human calls (no rule reads
    imagery).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

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

REVIEWED_BY_USER = "user"
REVIEWED_BY_AUTO = "auto"
AUTO_REASON_PREFIX = "[auto] "

# Must match grand_project_refinement.REFINEMENT_RELATION and its
# DEM_SOURCE_LIVE (copied, not imported, so this cheap query never has to
# load the heavy refinement module unless markers actually exist).
_REFINEMENT_RELATION = "refinement_dem_check"
_DEM_SOURCE_LIVE = "LIVE"


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
        reviewed_by      TEXT NOT NULL DEFAULT 'user',
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
        # 2026-09-29 (R1): tables created before auto-review lack
        # reviewed_by. Every existing row was written by the user, so the
        # default 'user' is exactly right for them.
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(candidate_review)")}
        if "reviewed_by" not in columns:
            conn.execute(
                "ALTER TABLE candidate_review "
                "ADD COLUMN reviewed_by TEXT NOT NULL DEFAULT 'user'")
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
                    (candidate_id, previous_status, new_status, reason,
                     reviewed_at, reviewed_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (candidate_id, previous, status, text, now, REVIEWED_BY_USER),
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
            SELECT id, candidate_id, previous_status, new_status, reason,
                   reviewed_at, reviewed_by
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


def _latest_reviews(conn) -> Dict[str, Dict[str, Any]]:
    """candidate_id -> newest candidate_review row as {"new_status",
    "reason", "reviewed_by"}."""
    rows = conn.execute(
        """
        SELECT r.candidate_id, r.new_status, r.reason, r.reviewed_by
        FROM candidate_review r
        JOIN (SELECT candidate_id, MAX(id) AS max_id
              FROM candidate_review GROUP BY candidate_id) m
          ON r.id = m.max_id
        """
    ).fetchall()
    return {r["candidate_id"]: dict(r) for r in rows}


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
        latest = _latest_reviews(conn)
        out: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            job_id = r["job_id"]
            t = trust.get(job_id) if job_id else None
            last = latest.get(r["id"])
            source = last["reviewed_by"] if last else None
            label = STATUS_LABELS.get(r["status"], r["status"])
            if source == REVIEWED_BY_AUTO:
                label += " (auto)"
            out[r["id"]] = {
                "status": r["status"],
                "status_label": label,
                "review_source": source,
                "job_id": job_id,
                "job_trust": t["trust"] if t else None,
                "job_trust_reason": t["reason"] if t else None,
                "last_review_reason": last["reason"] if last else None,
            }
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Automatic review (roadmap R1, 2026-09-29) -- see CHANGELOG at the top
# ---------------------------------------------------------------------------

_LAND_COVER_TEXT = {
    "water": "open water within ~60 m (ESA WorldCover 2021)",
    "tree_or_built": "trees or buildings cover at least 20 % within ~60 m (ESA WorldCover 2021)",
}


def _land_cover_reasons(conn, candidate_ids: set) -> Optional[Dict[str, str]]:
    """candidate_id -> flag reason for flagged candidates, using
    land_cover_flags.flag_reason() itself. None if the land-cover table or
    module is unavailable (then rule 2 is simply not applied)."""
    try:
        import land_cover_flags
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='candidate_land_cover'"
        ).fetchone()
        if not has_table:
            return {}
        rows = conn.execute(
            "SELECT candidate_id, center_class, frac_tree, frac_built, frac_water "
            "FROM candidate_land_cover"
        ).fetchall()
        out: Dict[str, str] = {}
        for row in rows:
            if row["candidate_id"] not in candidate_ids:
                continue
            reason = land_cover_flags.flag_reason(row)
            if reason:
                out[row["candidate_id"]] = reason
        return out
    except Exception:
        return None


def _refinement_verdicts(db_root: str, conn, candidate_ids: set
                         ) -> Tuple[Dict[str, Tuple[str, str]], set]:
    """(verdicts, unreadable). verdicts: candidate_id -> (status, reason)
    for candidates with Pass 2 markers. unreadable: candidates that HAVE
    markers but whose history could not be read -- the automatic pass
    leaves those untouched rather than guessing."""
    refined = {
        r["candidate_id"] for r in conn.execute(
            "SELECT DISTINCT candidate_id FROM evidence_link WHERE relation = ?",
            (_REFINEMENT_RELATION,),
        ).fetchall()
    } & candidate_ids
    if not refined:
        return {}, set()
    try:
        # Imported only here: heavy module, needed only when markers exist.
        # Using its own reader keeps ONE definition of "which DEM source".
        import grand_project_refinement as refinement
    except Exception:
        return {}, refined

    verdicts: Dict[str, Tuple[str, str]] = {}
    unreadable: set = set()
    for cid in sorted(refined):
        history = refinement._refinement_history(db_root, cid)
        if not history:
            unreadable.add(cid)
            continue
        live_hits = [h for h in history
                     if h.get("reproduced") and h.get("dem_source") == _DEM_SOURCE_LIVE]
        if live_hits:
            d = live_hits[-1].get("match_distance_m")
            where = f" {d:.0f} m from the original position" if isinstance(d, (int, float)) else ""
            verdicts[cid] = (STATUS_SUPPORTED,
                             f"Pass 2 with a LIVE DEM fetch reproduced the anomaly{where}.")
            continue
        last = history[-1]
        src = last.get("dem_source") or "NOT_RECORDED"
        if last.get("reproduced"):
            if src == "NOT_RECORDED":
                why = ("Pass 2 reproduced the anomaly, but the DEM source was not "
                       "recorded (marker from before 2026-09-23), so it cannot count "
                       "as a live check.")
            else:
                why = (f"Pass 2 reproduced the anomaly only from the {src} DEM "
                       "(offline self-agreement, not an independent live check).")
        else:
            if src == _DEM_SOURCE_LIVE:
                why = ("Live SRTM did not reproduce the anomaly; SRTM (~30 m, year "
                       "2000) may be too coarse -- not evidence against.")
            else:
                why = f"Pass 2 ({src} DEM) did not reproduce the anomaly -- not evidence against."
        verdicts[cid] = (STATUS_INCONCLUSIVE, why)
    return verdicts, unreadable


def auto_review_project(db_root: str, grand_project_id: str) -> Dict[str, Any]:
    """Applies the R1 rules to every candidate of the project that the
    user has never reviewed. Writes only real changes. Returns counts:
    {"checked", "user_owned", "changed", "by_status": {...},
     "skipped_unreadable", "land_cover_available"}."""
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
        candidates: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            candidates.setdefault(r["id"], {"status": r["status"], "job_id": r["job_id"]})
        ids = set(candidates)

        user_owned = {
            r["candidate_id"] for r in conn.execute(
                "SELECT DISTINCT candidate_id FROM candidate_review WHERE reviewed_by = ?",
                (REVIEWED_BY_USER,),
            ).fetchall()
        } & ids
        latest = _latest_reviews(conn)
        land = _land_cover_reasons(conn, ids)
        refine, unreadable = _refinement_verdicts(db_root, conn, ids - user_owned)

        now = db._now_iso()
        writes: List[Tuple] = []
        by_status: Dict[str, int] = {}
        for cid, info in candidates.items():
            if cid in user_owned or cid in unreadable:
                continue
            job_id = info["job_id"]
            t = trust.get(job_id) if job_id else None
            if t and t["trust"] == TRUST_CORRUPTED:
                status = STATUS_REJECTED
                why = f"Job {job_id[:6]} is marked CORRUPTED ({t['reason']})."
            elif land is not None and cid in land:
                status = STATUS_REJECTED
                why = "Land cover: " + _LAND_COVER_TEXT.get(land[cid], land[cid]) + "."
            elif cid in refine:
                status, why = refine[cid]
            else:
                status = STATUS_OPEN
                why = "No rule applies (not refined, not flagged, job not marked corrupted)."
            reason = AUTO_REASON_PREFIX + why

            previous = info["status"]
            last = latest.get(cid)
            if previous == status:
                # Same status: write only to refresh an earlier AUTO reason
                # that no longer describes the situation.
                if not (last and last["reviewed_by"] == REVIEWED_BY_AUTO
                        and last["reason"] != reason):
                    continue
            writes.append((cid, previous, status, reason, now, REVIEWED_BY_AUTO))
            by_status[status] = by_status.get(status, 0) + 1

        if writes:
            with conn:
                conn.executemany(
                    """
                    INSERT INTO candidate_review
                        (candidate_id, previous_status, new_status, reason,
                         reviewed_at, reviewed_by)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    writes,
                )
                conn.executemany(
                    "UPDATE candidate SET status = ?, last_updated_at = ? WHERE id = ?",
                    [(w[2], now, w[0]) for w in writes],
                )
    finally:
        conn.close()

    if writes:
        parts = ", ".join(f"{STATUS_LABELS[k]} {v}" for k, v in sorted(by_status.items()))
        try:
            db.log_timeline_event(
                db_root, grand_project_id, "AUTO_REVIEW",
                description=(f"Automatic review changed {len(writes)} candidate(s): {parts}. "
                             f"User-reviewed candidates left untouched: {len(user_owned)}."),
            )
        except Exception:
            pass

    return {
        "checked": len(candidates),
        "user_owned": len(user_owned),
        "changed": len(writes),
        "by_status": {STATUS_LABELS[k]: v for k, v in by_status.items()},
        "skipped_unreadable": len(unreadable),
        "land_cover_available": land is not None,
    }


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


def auto_review_project_json(db_root: str, grand_project_id: str) -> str:
    return _json_call(auto_review_project, db_root, grand_project_id)
