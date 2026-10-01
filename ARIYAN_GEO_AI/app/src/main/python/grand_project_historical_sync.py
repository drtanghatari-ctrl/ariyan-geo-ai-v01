"""
grand_project_historical_sync.py

Part of ARIYAN GEO AI's GRAND PROJECT FRAMEWORK -- Phase 2.5 Item 3
("Historical Research & Probable-Area Engine" persistence wiring),
added 2026-09-16. Mirrors grand_project_sync.py's own role exactly, but
for the genuinely separate output of the historical-research pipeline
(historical_source_mobile_combined.fetch_combined_historical_evidence()
+ historical_claim_extraction_mobile.suggest_probable_areas()) rather
than investigation_multi_mobile.py/debate_mobile.py's DEM-anchored
output. See grand_project_db.py's own historical_finding/
geographic_suggestion schema comment for why this is a separate table
pair (and therefore a separate sync module) rather than being folded
into record_investigation_results()/evidence_link: this pipeline runs
BEFORE any DEM candidate exists, often before any investigation has run
at all, so there is no candidate_id to attach evidence_link rows to.

This module adds NO new science, NO new extraction/geocoding logic, and
NO relevance filtering -- it only reads the REAL dicts both of the above
functions already produce and writes them into the database using
grand_project_db.py's existing functions, exactly the same "thin
bridge, not a new decision-maker" role grand_project_sync.py itself
documents for the DEM-anchored path.

RELEVANCE FILTERING -- DELIBERATELY NONE (2026-09-16 decision): every
suggestion the extractor returns is persisted as-is, including
ungrounded/noisy ones (e.g. a real, geocodable-but-irrelevant citation
name), pending Phase 5 (self-calibration) once real outcome data exists
to validate any filtering rule against. Four prefilter options
(Nominatim place-type filtering, keyword-proximity scoring, cross-source
corroboration count, hardcoded institutional blocklist) were evaluated
and explicitly set aside for now -- see this project's own record of
that decision. This module's job is visibility (real provenance --
context text + source item -- carried through to the DB), not judgment.

WHAT COUNTS AS "PROVENANCE" HERE, HONESTLY (not overclaimed): the real
suggest_probable_areas() output does NOT preserve which specific field
(title vs snippet vs description) a place/distance match came from --
_item_text_blob() concatenates all of them into one blob before the
extraction regexes ever run. What IS genuinely available and is what
this module actually persists: the raw `context` text window around
each match (PAIRED_SUGGESTION/DISTANCE_ONLY only -- UNGROUNDED_PLACE
carries no context in the real output) and the `source_item`
(source/title/url) a PAIRED_SUGGESTION traces back to. Do not describe
this as "field-level provenance" anywhere downstream (UI, reports) --
it is real, but coarser than that.

SCOPE, matching the 2026-09-16 design decision exactly: only items that
back at least one PAIRED_SUGGESTION entry (i.e. survived claim
extraction with both a grounded place AND a co-located distance) get a
historical_finding row. Raw combined-evidence items that never produced
a match are NOT separately persisted here -- consistent with what
suggest_probable_areas() itself already does (it silently skips any
item with zero distance candidates before ever reaching place
extraction); this module does not reach back into
combined_evidence_result to persist what the extractor itself already
passed over. DISTANCE_ONLY and UNGROUNDED_PLACE suggestions are
persisted as geographic_suggestion rows regardless (per the "persist
every suggestion" decision above) but with historical_finding_id left
NULL, since neither carries a source_item in the real
suggest_probable_areas() output -- there is genuinely nothing to link
to.

LINKING CAVEAT, HONESTLY NOTED (same spirit as grand_project_sync.py's
own KNOWN GAP note on GPR/ERT colocation): a PAIRED_SUGGESTION's
`source_item` is only {source, title, url} -- no stable id. This module
links it to a historical_finding row by an EXACT match on that
(source, title, url) tuple against combined_evidence_result["items"],
built once per call as a lookup (first occurrence wins). In the
ordinary case this is a fully reliable exact match, not an approximate
one like GPR/ERT's colocation-radius matching -- but if two distinct
items from the SAME combiner call ever share an identical
(source, title, url) triple (e.g. a genuine duplicate returned by a
source module), they would collapse into a single historical_finding
row, with the suggestion linked to whichever occurrence was seen first.
Flagged here rather than silently assumed impossible.

INTENDED CALL SITE (Kotlin wiring, NOT done by this module itself):
whenever the app's own historical-research UI (not yet built) completes
a real research query -- i.e. after
historical_source_mobile_combined.fetch_combined_historical_evidence()
and historical_claim_extraction_mobile.suggest_probable_areas() have
both run for the SAME query -- Kotlin would call this module's
record_historical_research_results() once with both real result dicts.
Exactly like grand_project_sync.py's own INTENDED CALL SITE note: a
failure in THIS module must never be allowed to hide or block the
research results the user already sees on screen; the caller should
wrap this call in its own try/except, same pattern as MainActivity.kt
already uses around runDebate().
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import grand_project_db as db


def _item_key(item: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """The exact (source, title, url) tuple used both to build the
    lookup from combined_evidence_result["items"] and to match a
    suggestion's own source_item back to it. See module docstring,
    LINKING CAVEAT, for the honest limitation of this exact-match
    approach."""
    return (item.get("source"), item.get("title"), item.get("url"))


def record_historical_research_results(
    db_root: str,
    grand_project_id: str,
    combined_evidence_result: Dict[str, Any],
    suggestion_result: Dict[str, Any],
    hypothesis_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persists ONE completed historical-research query's real output
    into the Grand Project database. Returns
    {"historical_finding_ids": [str, ...], "geographic_suggestion_ids": [str, ...]}
    on success.

    `combined_evidence_result` MUST be the real dict
    historical_source_mobile_combined.fetch_combined_historical_evidence()
    returns. `suggestion_result` MUST be the real dict
    historical_claim_extraction_mobile.suggest_probable_areas() returns
    for THAT SAME combined_evidence_result -- passing a suggestion
    result derived from a different query would silently mismatch
    source_item lookups; this module has no way to detect that, exactly
    the same caller responsibility grand_project_sync.py's own
    record_investigation_results() documents for its investigation_json/
    debate_json pairing.

    `hypothesis_id`, if given, is attached to every historical_finding
    and geographic_suggestion row created by this call -- mirrors
    record_investigation_results()'s own hypothesis_id parameter and
    create_candidate()'s hypothesis_id column, so a research run can be
    explicitly tied to a user-stated Hypothesis when one exists, even
    though Phase 2's own Hypothesis-selection UI is not built yet
    (same "accept it now, wire the UI later" stance already taken for
    candidate.hypothesis_id).

    Never raises for an ordinary per-suggestion issue -- every
    suggestion the extractor produced is persisted as-is (see module
    docstring, RELEVANCE FILTERING). DOES raise on a genuinely malformed
    input (e.g. combined_evidence_result missing "items"), matching this
    project's existing convention of treating a malformed evidence
    record as a real, surfaceable failure rather than silently papering
    over it."""
    items = combined_evidence_result["items"]
    retrieval_date = combined_evidence_result.get("retrieval_date") or ""

    # Lookup for linking a PAIRED_SUGGESTION's source_item back to the
    # real full item dict -- first occurrence wins per (source, title,
    # url). See module docstring, LINKING CAVEAT.
    item_by_key: Dict[Tuple[Optional[str], Optional[str], Optional[str]], Dict[str, Any]] = {}
    for item in items:
        key = _item_key(item)
        if key not in item_by_key:
            item_by_key[key] = item

    # historical_finding rows are created LAZILY, only for items that
    # actually back a PAIRED_SUGGESTION -- see module docstring, SCOPE.
    finding_id_by_key: Dict[Tuple[Optional[str], Optional[str], Optional[str]], str] = {}
    historical_finding_ids: List[str] = []
    geographic_suggestion_ids: List[str] = []

    def _get_or_create_finding(source_item: Dict[str, Any]) -> Optional[str]:
        key = _item_key(source_item)
        if key in finding_id_by_key:
            return finding_id_by_key[key]
        # Prefer the full item dict from combined_evidence_result (has
        # every real field the source module produced); fall back to
        # the partial source_item if, for some reason, it isn't found
        # there (should not normally happen if both results come from
        # the same real query, but never fabricate a KeyError over it).
        full_item = item_by_key.get(key, source_item)
        finding_id = db.create_historical_finding(
            db_root, grand_project_id,
            source_type=full_item.get("source"),
            item_detail=full_item,
            retrieved_at=retrieval_date,
            title=full_item.get("title"),
            url=full_item.get("url"),
            hypothesis_id=hypothesis_id,
        )
        finding_id_by_key[key] = finding_id
        historical_finding_ids.append(finding_id)
        return finding_id

    for area in suggestion_result.get("suggested_areas", []):
        anchor = area.get("anchor") or {}
        radius = area.get("radius") or {}
        source_item = area.get("source_item") or {}
        finding_id = _get_or_create_finding(source_item)
        suggestion_id = db.add_geographic_suggestion(
            db_root, grand_project_id,
            kind="PAIRED_SUGGESTION",
            hypothesis_id=hypothesis_id,
            historical_finding_id=finding_id,
            place_name=anchor.get("query"),
            resolved_name=anchor.get("resolved_name"),
            lat=anchor.get("lat"),
            lon=anchor.get("lon"),
            bounding_box=anchor.get("bounding_box"),
            radius_value=radius.get("value"),
            radius_unit=radius.get("unit"),
            radius_raw_text=radius.get("raw_text"),
            has_proximity_keyword=None,  # correctly absent for PAIRED_SUGGESTION -- see
                                          # add_geographic_suggestion()'s own docstring
            context=area.get("context"),
        )
        geographic_suggestion_ids.append(suggestion_id)

    for distance in suggestion_result.get("distance_only_mentions", []):
        suggestion_id = db.add_geographic_suggestion(
            db_root, grand_project_id,
            kind="DISTANCE_ONLY",
            hypothesis_id=hypothesis_id,
            historical_finding_id=None,  # no source_item in the real output -- nothing to link
            place_name=None,
            resolved_name=None,
            lat=None,
            lon=None,
            bounding_box=None,
            radius_value=distance.get("value"),
            radius_unit=distance.get("unit"),
            radius_raw_text=distance.get("raw_text"),
            has_proximity_keyword=distance.get("has_proximity_keyword"),
            context=distance.get("context"),
        )
        geographic_suggestion_ids.append(suggestion_id)

    for place in suggestion_result.get("ungrounded_place_candidates", []):
        suggestion_id = db.add_geographic_suggestion(
            db_root, grand_project_id,
            kind="UNGROUNDED_PLACE",
            hypothesis_id=hypothesis_id,
            historical_finding_id=None,  # no source_item in the real output -- nothing to link
            place_name=place,
            resolved_name=None,
            lat=None,
            lon=None,
            bounding_box=None,
            radius_value=None,
            radius_unit=None,
            radius_raw_text=None,
            has_proximity_keyword=None,
            context=None,  # ungrounded_place_candidates is a flat list of strings in the
                            # real output -- no context field exists to carry through
        )
        geographic_suggestion_ids.append(suggestion_id)

    return {
        "historical_finding_ids": historical_finding_ids,
        "geographic_suggestion_ids": geographic_suggestion_ids,
    }


# ==================== ADDED 2026-10-01, HISTORICAL SEARCH REBUILD (hs-v1) ====================
# Persistence for ONE located finding from historical_search_engine.py
# (engine hs-v1). The legacy record_historical_research_results() above is
# untouched (the old word-guessing route is switched off in the screen
# but its code and its already-saved rows stay).
#
# What gets written, per finding the USER chose to save (never
# automatically, never all results at once):
#   - one historical_finding row, source_type "historical_search_hs-v1",
#     item_detail = the WHOLE finding exactly as the engine returned it
#     (every coordinate with its source/tier/reference flag, evidence
#     texts, links, caveat) plus the search's query / keyword query /
#     retrieval date / tier definitions -- reused, not reshaped;
#   - one geographic_suggestion row, kind "LOCATED_FINDING" (kind is not
#     DB-enforced, see add_geographic_suggestion()), status
#     PENDING_REVIEW, radius LEFT EMPTY: no radius is taken from text;
#     the user types one when starting a Wide-Area Search from it.
#
# PRIMARY COORDINATE (the lat/lon written to the suggestion row), fixed
# order, first match wins -- every other coordinate stays in the
# historical_finding row and is summarised in `context`:
#   1. pleiades (tier A, precise)
#   2. wikidata_P625 with a cited reference
#   3. wikidata_P625 without one
#   4. wikipedia_en, 5. wikipedia_fa, 6. anything else in engine order.
#
# SAVING THE SAME FINDING TWICE does not duplicate rows: an existing
# hs-v1 historical_finding with the same finding key in this project is
# returned with already_saved=True.

HS_SOURCE_TYPE = "historical_search_hs-v1"
LOCATED_FINDING_KIND = "LOCATED_FINDING"

_PRIMARY_ORDER = (
    lambda c: c.get("source") == "pleiades" and c.get("tier") == "A",
    lambda c: c.get("source") == "wikidata_P625" and c.get("referenced") is True,
    lambda c: c.get("source") == "wikidata_P625",
    lambda c: c.get("source") == "wikipedia_en",
    lambda c: c.get("source") == "wikipedia_fa",
    lambda c: True,
)


def choose_primary_coordinate(coordinates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Fixed-order pick, see the block comment above. None if empty."""
    for rule in _PRIMARY_ORDER:
        for c in coordinates or []:
            if c.get("lat") is not None and c.get("lon") is not None and rule(c):
                return c
    return None


def _coord_line(c: Dict[str, Any]) -> str:
    ref = ""
    if c.get("referenced") is True:
        ref = ", cited"
    elif c.get("referenced") is False:
        ref = ", no citation"
    return "%s %s %.5f,%.5f%s" % (c.get("tier"), c.get("source"), c.get("lat"), c.get("lon"), ref)


def build_located_finding_context(finding: Dict[str, Any], primary: Dict[str, Any], query: str) -> str:
    """Plain-text summary stored in geographic_suggestion.context, so the
    Saved tab can show sources and tiers without parsing JSON."""
    others = [c for c in finding.get("coordinates") or [] if c is not primary]
    parts = ["used: " + _coord_line(primary)]
    if others:
        parts.append("also: " + "; ".join(_coord_line(c) for c in others))
    if finding.get("coordinate_spread_km") is not None:
        parts.append("spread %.2f km" % finding["coordinate_spread_km"])
    iran = finding.get("in_iran")
    parts.append("Iran: " + ("yes" if iran is True else "no" if iran is False else "not recorded"))
    if finding.get("date"):
        parts.append("date: " + str(finding["date"]))
    parts.append(finding.get("caveat") or "")
    parts.append("query: " + (query or ""))
    return " | ".join(p for p in parts if p)


def _finding_link(finding: Dict[str, Any]) -> Optional[str]:
    links = finding.get("links") or {}
    for k in ("wikidata", "pleiades", "wikipedia_en", "wikipedia_fa"):
        if links.get(k):
            return links[k]
    return None


def record_located_finding(
    db_root: str,
    grand_project_id: str,
    search_result: Dict[str, Any],
    finding_key: str,
    hypothesis_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Saves ONE located finding (picked by its `key`) from a
    historical_search_engine.search_historical() result. Returns
    {"historical_finding_id", "geographic_suggestion_id", "already_saved",
     "primary": {...coordinate...}}.

    Raises ValueError if the key is not among located_findings (a caller
    bug -- unlocated findings carry no coordinate and are not saved)."""
    finding = None
    for f in search_result.get("located_findings") or []:
        if f.get("key") == finding_key:
            finding = f
            break
    if finding is None:
        raise ValueError("Finding %r is not a located finding of this search result." % finding_key)
    primary = choose_primary_coordinate(finding.get("coordinates") or [])
    if primary is None:
        raise ValueError("Finding %r has no usable coordinate." % finding_key)

    # Duplicate guard: same finding key already saved in this project.
    for row in db.get_historical_findings_for_project(db_root, grand_project_id):
        if row.get("source_type") != HS_SOURCE_TYPE:
            continue
        try:
            detail = json.loads(row.get("item_detail_json") or "{}")
        except (ValueError, TypeError):
            continue
        if ((detail.get("finding") or {}).get("key")) == finding_key:
            existing_sid = None
            for s in db.get_geographic_suggestions_for_project(db_root, grand_project_id):
                if s.get("historical_finding_id") == row["id"] and s.get("kind") == LOCATED_FINDING_KIND:
                    existing_sid = s["id"]
                    break
            return {"historical_finding_id": row["id"], "geographic_suggestion_id": existing_sid,
                    "already_saved": True, "primary": primary}

    item_detail = {
        "engine_version": search_result.get("engine_version"),
        "query": search_result.get("query"),
        "keyword_query": search_result.get("keyword_query"),
        "retrieval_date": search_result.get("retrieval_date"),
        "tier_definitions": search_result.get("tier_definitions"),
        "primary_coordinate": primary,
        "finding": finding,
    }
    finding_id = db.create_historical_finding(
        db_root, grand_project_id,
        source_type=HS_SOURCE_TYPE,
        item_detail=item_detail,
        retrieved_at=search_result.get("retrieval_date") or "",
        title=finding.get("title"),
        url=_finding_link(finding),
        hypothesis_id=hypothesis_id,
    )
    names = [n for n in (finding.get("title_en") or finding.get("title"), finding.get("title_fa")) if n]
    suggestion_id = db.add_geographic_suggestion(
        db_root, grand_project_id,
        kind=LOCATED_FINDING_KIND,
        hypothesis_id=hypothesis_id,
        historical_finding_id=finding_id,
        place_name=finding.get("title"),
        resolved_name=" / ".join(names) if names else finding.get("title"),
        lat=primary["lat"],
        lon=primary["lon"],
        bounding_box=None,
        radius_value=None,
        radius_unit=None,
        radius_raw_text=None,
        has_proximity_keyword=None,
        context=build_located_finding_context(finding, primary, search_result.get("query") or ""),
    )
    return {"historical_finding_id": finding_id, "geographic_suggestion_id": suggestion_id,
            "already_saved": False, "primary": primary}
