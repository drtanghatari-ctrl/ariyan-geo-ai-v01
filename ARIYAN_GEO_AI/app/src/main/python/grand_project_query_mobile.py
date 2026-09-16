"""
grand_project_query_mobile.py

Part of ARIYAN GEO AI's GRAND PROJECT FRAMEWORK -- Phase 2 (Confidence
History + Evidence Graph + explicit Hypothesis objects), added
2026-09-16. This module is the Kotlin-facing read boundary for Phase
2's browse screen: three flat lists (Investigations / Candidates /
Timeline), plus, as of 2026-09-17, one combined per-candidate detail
call for drill-down (confidence history trajectory + full evidence
chain + parent-investigation context, per the user's own explicit
"extra information for orientation" request).

THIS MODULE ADDS NO NEW LOGIC. Exactly like investigation_mobile.py's
run_investigation_json() and debate_mobile.py's run_debate_json(), it
is a thin JSON-string wrapper: each function here calls one or more
existing, already-tested grand_project_db.py read functions and
json.dumps() the real result, unchanged. This mirrors the SAME real
convention this project has used at every other Kotlin<->Python
boundary -- Chaquopy can pass Python lists/dicts across directly, but
every other call site in this app deliberately returns a JSON string
instead and lets Kotlin parse it with org.json.JSONObject/JSONArray
(see MainActivity.kt's own renderResult()) for a consistent, single
parsing convention across the whole app, rather than mixing raw
Chaquopy object access in some places and JSON parsing in others.
"""

from __future__ import annotations

import json

import grand_project_db as db


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
    return json.dumps(rows)


def list_timeline_json(db_root: str, grand_project_id: str) -> str:
    """Returns every timeline_event row for a project as a JSON array
    string, oldest first -- the real dicts grand_project_db.get_timeline()
    already returns, unchanged. Real fields per row: id,
    grand_project_id, occurred_at, event_type, related_entity_type,
    related_entity_id, description."""
    rows = db.get_timeline(db_root, grand_project_id)
    return json.dumps(rows)


def get_candidate_detail_json(db_root: str, candidate_id: str) -> str:
    """ADDED for Phase 2 drill-down (user's own explicit request this
    session): returns ONE candidate's full detail as a single combined
    JSON object -- {"candidate": {...}, "investigation": {...} | null,
    "confidence_history": [...], "evidence": [...]} -- in a single
    Kotlin<->Python round-trip, rather than requiring the caller to make
    four separate calls. This is the actual "Evidence Graph (backward
    traceability)" part of Phase 2's own name: from one candidate, walk
    back to its parent investigation (for on-screen orientation, per the
    user's own explicit request -- "extra information for better
    orientation"), its full confidence trajectory, and its full
    evidence chain, all at once.

    ADDS NO NEW LOGIC -- purely composes four already-tested
    grand_project_db.py functions (get_candidate, get_investigation,
    get_confidence_history, get_candidate_evidence), each returning its
    own real, unmodified rows. The only new thing here is the
    packaging, not the data.

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
    (e.g. grand_project_historical_sync.py's own LINKING CAVEAT note)."""
    candidate = db.get_candidate(db_root, candidate_id)
    if candidate is None:
        return json.dumps({"error": "candidate not found"})

    investigation = db.get_investigation(db_root, candidate["investigation_id"])
    confidence_history = db.get_confidence_history(db_root, candidate_id)
    evidence = db.get_candidate_evidence(db_root, candidate_id)

    return json.dumps({
        "candidate": candidate,
        "investigation": investigation,
        "confidence_history": confidence_history,
        "evidence": evidence,
    })