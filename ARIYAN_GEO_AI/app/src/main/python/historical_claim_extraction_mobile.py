"""
historical_claim_extraction_mobile.py

ARIYAN GEO AI - Phase 2.5 (Historical Research & Probable-Area Engine)

Scans the combined output of historical_source_mobile_combined.py for
candidate anchor-place-name + search-radius pairings, e.g. spotting
"...buried within 100km of Persepolis..." inside a real evidence
snippet and suggesting Persepolis + 100km as a possible search area.

THIS MODULE NEVER PRODUCES A FINAL SEARCH AREA. It only produces
SUGGESTIONS for a human to review, edit, or reject -- matching the
project's existing decisions that Hypothesis objects are user-stated,
not auto-generated, and the user's own mockup panel explicitly labeled
"Research Hypothesis -- Not a Claim". Nothing here should ever be wired
directly into an AOI/tiling step without a human confirming it first.

Two real, separate problems, solved with two different levels of rigor:

1. Place name -> real coordinates: solved properly, via
   geocoding_source_mobile_nominatim.py (a real, keyless, rate-limited
   geocoding API). A candidate is only ever surfaced as a "grounded"
   anchor if Nominatim genuinely resolves it to a real place -- an
   unresolvable candidate is reported separately as
   "ungrounded_place_candidates", never silently dropped, never
   silently promoted.

2. Free text -> which words are a place name, and what the stated
   radius is: NOT solved properly -- this is genuinely hard without
   heavy NLP libraries (deliberately avoided, same reason the app
   avoids GDAL/rasterio: keeps everything Chaquopy-buildable). Solved
   here with plain regex heuristics only:
     - candidate place names = Title-Case word sequences (a common,
       imperfect proxy for proper nouns)
     - candidate radii = a number immediately followed by km/kilometers/
       miles/mi
   This WILL miss real place names that aren't capitalized-as-expected
   and WILL flag some non-place capitalized phrases as candidates. Real
   place-name grounding (step 1) filters out most fabricated noise
   automatically, since a non-place phrase very rarely resolves to a
   real Nominatim result -- but this is honestly a heuristic, not
   reliable extraction, and is documented as such rather than
   overclaiming precision it doesn't have. IMPORTANT CAVEAT found by
   live testing: a real, grounded (geocodable) place is not necessarily
   a RELEVANT one -- an incidental Title-Case citation/institution name
   in unrelated source metadata can and does get geocoded successfully.
   Nominatim grounding proves realness, not relevance. Human review of
   every suggestion is load-bearing, not a formality.
"""

import re
import time

import geocoding_source_mobile_nominatim as _geocoding


# A short list of very common English function words that would
# otherwise show up as capitalized-word "candidates" purely because
# they start a sentence. Kept intentionally short -- real filtering
# happens via geocoding grounding, not this list. This just avoids
# wasting Nominatim calls (and its 1.1s/request rate limit) on the most
# obviously non-place words.
_COMMON_NON_PLACE_WORDS = frozenset({
    "the", "this", "that", "these", "those", "it", "he", "she", "they",
    "a", "an", "and", "but", "or", "so", "if", "when", "where", "what",
    "who", "how", "why", "there", "here", "his", "her", "their", "its",
    "chapter", "page", "book", "part",
})

_TITLE_CASE_PHRASE_RE = re.compile(r"\b[A-Z][a-zA-Z'\u2019-]*(?:\s+[A-Z][a-zA-Z'\u2019-]*){0,3}\b")
_DISTANCE_RE = re.compile(
    r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(kilometers?|kilometres?|km|miles?|mi)\b",
    re.IGNORECASE,
)
_PROXIMITY_KEYWORDS = ("within", "near", "buried", "hidden", "vicinity", "around")

_CONTEXT_WINDOW_CHARS = 80


def _item_text_blob(item):
    """Concatenate the real text fields an evidence item actually has
    (different source modules populate different fields -- title/
    snippet for Wikipedia+Wikisource, title/description for Internet
    Archive). Never fabricates text for a missing field.
    """
    parts = [item.get("title") or ""]
    if item.get("snippet"):
        parts.append(item["snippet"])
    if item.get("description"):
        parts.append(item["description"])
    return " ".join(p for p in parts if p)


def _extract_place_candidates(text):
    """Return a deduplicated, order-preserving list of Title-Case phrase
    candidates from real text, minus the short common-word exclude list.
    A heuristic, not reliable NLP -- see module docstring.
    """
    seen = []
    for match in _TITLE_CASE_PHRASE_RE.finditer(text):
        phrase = match.group(0).strip()
        if phrase.lower() in _COMMON_NON_PLACE_WORDS:
            continue
        if phrase not in seen:
            seen.append(phrase)
    return seen


def _extract_distance_candidates(text):
    """Return real distance mentions found in the text, each with its
    raw surrounding context and whether a proximity keyword appears
    nearby (a real, checkable signal -- not a fabricated confidence
    score).
    """
    candidates = []
    for match in _DISTANCE_RE.finditer(text):
        value = float(match.group(1).replace(",", ""))
        if value <= 0:
            # A zero-or-negative "radius" is never meaningful here. In
            # practice this mostly catches OCR corruption in old scanned
            # texts (e.g. a comma-thousands number missing its leading
            # digits due to a scan artifact, observed live during
            # development) -- cheaper and more honest than trying to
            # regex-repair every possible OCR corruption pattern.
            continue
        unit_raw = match.group(2).lower()
        unit = "km" if unit_raw.startswith(("km", "kilomet")) else "miles"
        start = max(0, match.start() - _CONTEXT_WINDOW_CHARS)
        end = min(len(text), match.end() + _CONTEXT_WINDOW_CHARS)
        context = text[start:end].strip()
        has_proximity_keyword = any(kw in context.lower() for kw in _PROXIMITY_KEYWORDS)
        candidates.append({
            "value": value,
            "unit": unit,
            "raw_text": match.group(0),
            "context": context,
            "has_proximity_keyword": has_proximity_keyword,
        })
    return candidates


def suggest_probable_areas(combined_evidence_result, max_place_candidates_to_geocode=10,
                            geocode_timeout_seconds=15):
    """Scan a historical_source_mobile_combined.fetch_combined_historical_evidence()
    result for candidate anchor-place + radius pairings.

    NEVER returns a committed search area -- every entry in
    "suggested_areas" is a SUGGESTION requiring human review before it
    is used to define any real investigation scope.

    Returns:
        {
            "suggested_areas": [
                {
                    "anchor": {...geocode_place_name() result...},
                    "radius": {"value": float, "unit": "km"|"miles", "raw_text": str},
                    "source_item": {"source": str, "title": str, "url": str},
                    "context": str,   # the real text window this was extracted from
                },
                ...
            ],
            "ungrounded_place_candidates": [str, ...],  # extracted but Nominatim found no real match
            "distance_only_mentions": [ {value, unit, raw_text, context}, ... ],  # a real distance
                                                                                   # mention with no
                                                                                   # co-located resolvable
                                                                                   # place in the same item
            "geocoding_errors": [str, ...],  # real geocoding failures encountered, never hidden
        }

    Each real evidence item is scanned independently; a place candidate
    and a distance candidate are only ever paired if they occur in the
    SAME item's text (a real, checkable co-location signal, not a
    guess about which place a distant mention refers to).
    """
    suggested_areas = []
    ungrounded_place_candidates = []
    distance_only_mentions = []
    geocoding_errors = []

    already_attempted_geocode = {}  # place phrase -> (result_or_None, error_or_None), real cache to
                                     # avoid re-geocoding + re-rate-limiting the same phrase twice

    geocode_calls_made = 0

    for item in combined_evidence_result.get("items", []):
        text = _item_text_blob(item)
        if not text.strip():
            continue

        place_candidates = _extract_place_candidates(text)
        distance_candidates = _extract_distance_candidates(text)

        if not distance_candidates:
            continue  # nothing to pair in this item; place-only candidates aren't useful alone here

        item_had_grounded_place = False

        for phrase in place_candidates:
            if phrase in already_attempted_geocode:
                geocode_result, geocode_error = already_attempted_geocode[phrase]
            elif geocode_calls_made >= max_place_candidates_to_geocode:
                # Real cap reached -- stop making new geocoding calls this run rather than
                # silently ignoring the cap or hammering Nominatim beyond what was agreed.
                continue
            else:
                geocode_result, geocode_error = _geocoding.geocode_place_name_safe(
                    phrase, geocode_timeout_seconds
                )
                already_attempted_geocode[phrase] = (geocode_result, geocode_error)
                geocode_calls_made += 1

            if geocode_error:
                geocoding_errors.append(geocode_error)
                continue

            if geocode_result is None:
                if phrase not in ungrounded_place_candidates:
                    ungrounded_place_candidates.append(phrase)
                continue

            item_had_grounded_place = True
            for distance in distance_candidates:
                suggested_areas.append({
                    "anchor": geocode_result,
                    "radius": {
                        "value": distance["value"],
                        "unit": distance["unit"],
                        "raw_text": distance["raw_text"],
                    },
                    "source_item": {
                        "source": item.get("source"),
                        "title": item.get("title"),
                        "url": item.get("url"),
                    },
                    "context": distance["context"],
                })

        if not item_had_grounded_place:
            for distance in distance_candidates:
                distance_only_mentions.append(distance)

    return {
        "suggested_areas": suggested_areas,
        "ungrounded_place_candidates": ungrounded_place_candidates,
        "distance_only_mentions": distance_only_mentions,
        "geocoding_errors": geocoding_errors,
    }