"""
grand_project_query_mobile.py

Part of ARIYAN GEO AI's GRAND PROJECT FRAMEWORK -- Phase 2 (Confidence
History + Evidence Graph + explicit Hypothesis objects), added
2026-09-16. This module is the Kotlin-facing read boundary for Phase
2's FIRST, flat version of the Grand Project browse screen (user's own
decision: three separate flat lists -- Investigations / Candidates /
Timeline -- no drill-down yet, that is a deliberately separate later
step).

THIS MODULE ADDS NO NEW LOGIC. Exactly like investigation_mobile.py's
run_investigation_json() and debate_mobile.py's run_debate_json(), it
is a thin JSON-string wrapper: each function here calls one existing,
already-tested grand_project_db.py read function and json.dumps() the
real result, unchanged. This mirrors the SAME real convention this
project has used at every other Kotlin<->Python boundary -- Chaquopy
can pass Python lists/dicts across directly, but every other call site
in this app deliberately returns a JSON string instead and lets Kotlin
parse it with org.json.JSONObject/JSONArray (see MainActivity.kt's own
renderResult()) for a consistent, single parsing convention across the
whole app, rather than mixing raw Chaquopy object access in some places
and JSON parsing in others.

NOT YET WIRED TO ANY UI. No Kotlin call site exists yet -- this module
is delivered ahead of GrandProjectActivity.kt (which needs
AndroidManifest.xml and activity_main.xml content to build correctly,
not yet supplied) so the Python side can be sandbox-verified
independently first, matching this project's "prove one piece before
wiring" discipline used throughout (Wikipedia module before the
combiner, geocoding before claim extraction, etc.).
"""

from __future__ import annotations

import json

import grand_project_db as db
import grand_project_review as review


def list_investigations_json(db_root: str, grand_project_id: str) -> str:
    """Returns every investigation row for a project as a JSON array
    string, oldest first -- the real dicts
    grand_project_db.list_investigations_for_project() already returns,
    unchanged. Real fields per row: id, grand_project_id, objective,
    workflow_reference, parameters_json, execution_status,
    interpretation_summary, created_at."""
    rows = db.list_investigations_for_project(db_root, grand_project_id)
    return json.dumps(rows)


def list_candidates_json(db_root: str, grand_project_id: str) -> str:
    """Returns every candidate row for a project as a JSON array string,
    oldest first -- the real dicts
    grand_project_db.list_candidates_for_project() already returns,
    unchanged. Real fields per row: id, grand_project_id,
    investigation_id, hypothesis_id, lat, lon, status, score,
    confidence_band, confidence_numeric, created_at, last_updated_at."""
    rows = db.list_candidates_for_project(db_root, grand_project_id)
    # ADDED 2026-09-24 (Phase 3): each row also carries the user's
    # review label and its Wide-Area Search job's trust mark, from
    # grand_project_review.review_summary_for_project(). Extra keys only;
    # the original fields are unchanged. Keys: status_label, job_id,
    # job_trust, job_trust_reason, last_review_reason.
    summary = review.review_summary_for_project(db_root, grand_project_id)
    for row in rows:
        row.update(summary.get(row["id"], {}))
    return json.dumps(rows)


def list_timeline_json(db_root: str, grand_project_id: str) -> str:
    """Returns every timeline_event row for a project as a JSON array
    string, oldest first -- the real dicts grand_project_db.get_timeline()
    already returns, unchanged. Real fields per row: id,
    grand_project_id, occurred_at, event_type, related_entity_type,
    related_entity_id, description."""
    rows = db.get_timeline(db_root, grand_project_id)
    return json.dumps(rows)


def list_hypotheses_json(db_root: str, grand_project_id: str) -> str:
    """ADDED for Phase 2's Hypothesis UI. Returns every hypothesis row
    for a project as a JSON array string, oldest first -- the real
    dicts grand_project_db.list_hypotheses_for_project() already
    returns, unchanged. Real fields per row: id, grand_project_id,
    statement, created_at, current_status, current_confidence."""
    rows = db.list_hypotheses_for_project(db_root, grand_project_id)
    return json.dumps(rows)


def create_hypothesis_json(db_root: str, grand_project_id: str, statement: str) -> str:
    """ADDED for Phase 2's Hypothesis UI (user's own explicit request
    this session, including candidate-linking in the same pass).
    Creates a new, EXPLICIT, user-stated Hypothesis -- `statement` must
    be the user's own words; ARIYAN never generates this text itself
    (Phase 0's own design decision, unchanged here, just finally given
    a real UI path to reach it). Thin wrapper over
    grand_project_db.create_hypothesis(); returns
    {"hypothesis_id": "..."} as JSON so the caller can confirm creation
    succeeded and knows the new id, e.g. to immediately link a
    candidate to it afterward if it chooses to."""
    hypothesis_id = db.create_hypothesis(db_root, grand_project_id, statement)
    return json.dumps({"hypothesis_id": hypothesis_id})


def link_candidate_to_hypothesis_json(db_root: str, candidate_id: str, hypothesis_id: str) -> str:
    """ADDED for Phase 2's Hypothesis UI (linking pass, user's own
    explicit request this session). Thin wrapper over
    grand_project_db.link_candidate_to_hypothesis() -- a plain UPDATE,
    not append-only: re-linking a candidate to a different hypothesis
    later is a normal, supported operation here, not a correction that
    needs its own history trail. (The candidate's own confidence
    trajectory remains separately, independently tracked via
    confidence_history regardless of which hypothesis it is linked to
    at any given moment -- linking does not touch that table at all.)
    Returns {"status": "ok"} as JSON; the caller should re-fetch
    get_candidate_detail_json() if it wants to see the newly linked
    hypothesis reflected in that candidate's own detail view."""
    db.link_candidate_to_hypothesis(db_root, candidate_id, hypothesis_id)
    return json.dumps({"status": "ok"})


def get_candidate_detail_json(db_root: str, candidate_id: str) -> str:
    """ADDED for Phase 2 drill-down (user's own explicit request this
    session): returns ONE candidate's full detail as a single combined
    JSON object -- {"candidate": {...}, "investigation": {...} | null,
    "confidence_history": [...], "evidence": [...], "hypothesis":
    {...} | null} -- in a single Kotlin<->Python round-trip, rather
    than requiring the caller to make several separate calls. This is
    the actual "Evidence Graph (backward traceability)" part of Phase
    2's own name: from one candidate, walk back to its parent
    investigation (for on-screen orientation, per the user's own
    explicit request -- "extra information for better orientation"),
    its full confidence trajectory, its full evidence chain, and
    (ADDED for the Hypothesis UI pass) whichever hypothesis it is
    CURRENTLY linked to, if any -- all at once.

    ADDS NO NEW LOGIC -- purely composes five already-tested
    grand_project_db.py functions (get_candidate, get_investigation,
    get_confidence_history, get_candidate_evidence, get_hypothesis),
    each returning its own real, unmodified rows. The only new thing
    here is the packaging, not the data.

    Returns {"error": "candidate not found"} (as a JSON string, not a
    raised exception) if candidate_id doesn't exist -- this is treated
    as an ordinary, expected UI case (e.g. stale on-screen state after
    the underlying data changed), not a malformed-input failure, so it
    does not raise. The caller (Kotlin) should check for an "error" key
    before reading the other fields, the same pattern already used for
    debate_mobile.run_debate_json()'s own {"error": "..."} convention.

    "investigation" is null (not omitted, not an empty dict) when the
    candidate's own investigation_id doesn't resolve to a real row --
    should not normally happen (candidate.investigation_id is NOT NULL
    with a foreign key to investigation.id), but handled explicitly
    rather than assumed impossible, consistent with this project's own
    "never silently assume a join always succeeds" convention elsewhere
    (e.g. grand_project_historical_sync.py's own LINKING CAVEAT note).

    "hypothesis" is null in the ORDINARY case where the candidate has
    never been linked to one at all (candidate.hypothesis_id is
    nullable and starts NULL for every candidate) -- this is the
    expected, common state for most candidates, not an error. It is
    ALSO null (same "never assume a join succeeds" principle as
    investigation above) in the defensive edge case where
    hypothesis_id is set but doesn't resolve to a real row."""
    candidate = db.get_candidate(db_root, candidate_id)
    if candidate is None:
        return json.dumps({"error": "candidate not found"})

    investigation = db.get_investigation(db_root, candidate["investigation_id"])
    confidence_history = db.get_confidence_history(db_root, candidate_id)
    evidence = db.get_candidate_evidence(db_root, candidate_id)

    hypothesis = None
    if candidate.get("hypothesis_id"):
        hypothesis = db.get_hypothesis(db_root, candidate["hypothesis_id"])

    # ADDED 2026-09-24 (Phase 3): the user's review history for this
    # candidate (oldest first) and its job trust mark, so the detail
    # dialog shows why a candidate is Rejected/Supported and whether its
    # job is marked Corrupted. "review" = review_summary_for_project()'s
    # entry for this candidate (status_label, job_id, job_trust, ...).
    review_history = review.get_candidate_review_history(db_root, candidate_id)
    review_entry = review.review_summary_for_project(
        db_root, candidate["grand_project_id"]).get(candidate_id)

    return json.dumps({
        "candidate": candidate,
        "investigation": investigation,
        "confidence_history": confidence_history,
        "evidence": evidence,
        "hypothesis": hypothesis,
        "review_history": review_history,
        "review": review_entry,
    })


# ADDED 2026-09-24 (Phase 3): write paths for the review UI. Thin
# pass-throughs to grand_project_review.py's own *_json functions, kept
# here so GrandProjectActivity.kt still talks to one module only.

def set_candidate_status_json(db_root: str, candidate_id: str, new_status: str, reason: str) -> str:
    return review.set_candidate_status_json(db_root, candidate_id, new_status, reason)


def set_job_trust_json(db_root: str, job_ref: str, trust: str, reason: str) -> str:
    return review.set_job_trust_json(db_root, job_ref, trust, reason)


def list_job_trust_json(db_root: str) -> str:
    return review.list_job_trust_json(db_root)
