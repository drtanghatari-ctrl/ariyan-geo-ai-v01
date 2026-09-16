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