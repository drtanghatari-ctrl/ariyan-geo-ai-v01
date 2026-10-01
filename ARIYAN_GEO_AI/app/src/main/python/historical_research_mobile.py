"""
historical_research_mobile.py

ARIYAN GEO AI - Phase 2.5 (Historical Research & Probable-Area Engine),
Kotlin-facing boundary module, ADDED 2026-09-17.

Until today, none of Phase 2.5's real Python (`historical_source_mobile_
combined.py`, `historical_claim_extraction_mobile.py`,
`grand_project_historical_sync.py`) had any Kotlin call path -- see
`ariyan-geo-ai.md`'s own CRITICAL CORRECTION note on why that mattered:
the missing UI meant a real broken-import bug in that pipeline went
undetected for an entire prior session. This module is the thin
JSON-wrapper boundary `HistoricalResearchActivity.kt` actually calls,
matching this project's existing convention exactly (`grand_project_
query_mobile.py`'s own `*_json()` pattern) -- adds no new science, no
new persistence logic, no new geometry; it only converts between real
Python dicts and the JSON strings Chaquopy hands across the boundary.

TWO-STEP DESIGN, DELIBERATE: `run_historical_research_json()` fetches
and extracts but does NOT persist; `save_historical_research_json()`
persists a PREVIOUSLY-RUN result. This mirrors this project's existing
investigation/debate split (MainActivity.kt runs an investigation, shows
it, THEN separately calls persistence) -- the user should see real
suggestions on screen before committing anything to the database, not
have every search silently write rows. The two JSON blobs
`save_historical_research_json()` takes are exactly what
`run_historical_research_json()` just returned (round-tripped through
Kotlin unmodified) -- this module trusts the caller to pass back the
SAME pair from the SAME search, exactly the same caller responsibility
`grand_project_sync.record_investigation_results()` already documents
for its own investigation_json/debate_json pairing.
"""

from __future__ import annotations

import json
from typing import Optional

import historical_source_mobile_combined as combined
import historical_claim_extraction_mobile as extraction
import grand_project_historical_sync as sync
import grand_project_db as db
import historical_search_engine as search_engine


def run_historical_research_json(query: str, max_results_per_source: int = 10) -> str:
    """Runs ONE real historical-research query: fetches from all three
    real sources (Wikipedia/Internet Archive/Wikisource, via
    `historical_source_mobile_combined.fetch_combined_historical_evidence()`,
    unchanged) then extracts real place+radius suggestions from that
    SAME result (via `historical_claim_extraction_mobile.
    suggest_probable_areas()`, unchanged, including its own real
    Nominatim grounding calls -- this function can take several real
    seconds, matching that module's own per-place-candidate geocoding
    cost).

    Returns everything the caller needs to both DISPLAY results and
    later PERSIST them, without re-running anything:
        {
            "combined_evidence": {...},   # the exact real dict
                                           # fetch_combined_historical_evidence()
                                           # returned -- pass this straight
                                           # back into
                                           # save_historical_research_json()
            "suggestions": {...},         # the exact real dict
                                           # suggest_probable_areas()
                                           # returned -- same, pass straight
                                           # back
        }

    Never raises for an ordinary "this source is down" or "no
    suggestions found" outcome -- both are real, honest results already
    represented inside the two dicts above (source_errors / empty
    suggested_areas), not exceptions. Can raise only for a genuinely
    malformed/empty `query` string, matching
    `fetch_combined_historical_evidence()`'s own per-source raising
    behavior for that case (each source's own _safe wrapper already
    catches it per-source, so in practice this only surfaces if ALL
    three sources reject the same malformed query).
    """
    combined_evidence_result = combined.fetch_combined_historical_evidence(
        query, max_results_per_source=max_results_per_source
    )
    suggestion_result = extraction.suggest_probable_areas(combined_evidence_result)
    # ADDED 2026-10-01 (Historical Search rebuild, engine hs-v1): the new
    # en+fa Wikipedia / Wikidata / Pleiades / OpenAlex engine runs
    # ALONGSIDE the legacy pipeline above, under its own key. The two
    # legacy keys are unchanged, so the installed APK keeps working and
    # its Save path is untouched; the new key is simply ignored until the
    # Kotlin screen is updated to show it. Its own failure can never
    # break the legacy result -- reported as {"error": "..."} instead.
    hs_result, hs_error = search_engine.search_historical_safe(query)
    return json.dumps({
        "combined_evidence": combined_evidence_result,
        "suggestions": suggestion_result,
        "historical_search": hs_result if hs_result is not None else {"error": hs_error},
    }, ensure_ascii=False)


def run_historical_search_json(query: str, openalex_api_key: Optional[str] = None) -> str:
    """ADDED 2026-10-01: runs ONLY the new hs-v1 engine
    (`historical_search_engine.search_historical()`) and returns its
    result as JSON -- for the rebuilt Kotlin screen and for quick tests.
    Never raises: a failure comes back as {"error": "..."}. Nothing is
    persisted here (same two-step design as above)."""
    hs_result, hs_error = search_engine.search_historical_safe(
        query, openalex_api_key=openalex_api_key or None
    )
    return json.dumps(hs_result if hs_result is not None else {"error": hs_error},
                      ensure_ascii=False)


def save_historical_research_json(
    db_root: str,
    grand_project_id: str,
    combined_evidence_json: str,
    suggestions_json: str,
    hypothesis_id: Optional[str] = None,
) -> str:
    """Persists ONE previously-run historical-research result (the SAME
    two JSON blobs `run_historical_research_json()`'s own response
    carries, round-tripped through Kotlin unmodified) via
    `grand_project_historical_sync.record_historical_research_results()`,
    unchanged.

    Returns {"historical_finding_ids": [...], "geographic_suggestion_ids": [...]}
    as JSON on success -- the real new row ids, so the caller can
    immediately show/select from what was just saved without a
    separate re-fetch.
    """
    combined_evidence_result = json.loads(combined_evidence_json)
    suggestion_result = json.loads(suggestions_json)
    result = sync.record_historical_research_results(
        db_root, grand_project_id, combined_evidence_result, suggestion_result,
        hypothesis_id=hypothesis_id,
    )
    return json.dumps(result)


def list_geographic_suggestions_json(db_root: str, grand_project_id: str) -> str:
    """Returns every geographic_suggestion row saved for a project, as a
    JSON array -- the real dicts
    `grand_project_db.get_geographic_suggestions_for_project()` already
    returns, unchanged. This is the real list a "start a wide-area
    search from this suggestion" picker reads from (AOI mechanism (c),
    see `wide_area_search_mobile.create_wide_area_search_job_from_
    suggestion_json()`)."""
    rows = db.get_geographic_suggestions_for_project(db_root, grand_project_id)
    return json.dumps(rows)


def save_located_finding_json(
    db_root: str,
    grand_project_id: str,
    search_json: str,
    finding_key: str,
    hypothesis_id: Optional[str] = None,
) -> str:
    """ADDED 2026-10-01 (Historical Search rebuild, step 2): saves ONE
    located finding the user chose, from the SAME result JSON
    `run_historical_search_json()` returned (round-tripped through Kotlin
    unmodified), via `grand_project_historical_sync.record_located_finding()`.
    Returns {"historical_finding_id", "geographic_suggestion_id",
    "already_saved", "primary"} or {"error": "..."} -- never raises, so a
    save failure can never wipe the results already on screen."""
    try:
        search_result = json.loads(search_json)
        result = sync.record_located_finding(
            db_root, grand_project_id, search_result, finding_key,
            hypothesis_id=hypothesis_id,
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": "%s: %s" % (type(exc).__name__, exc)}, ensure_ascii=False)
