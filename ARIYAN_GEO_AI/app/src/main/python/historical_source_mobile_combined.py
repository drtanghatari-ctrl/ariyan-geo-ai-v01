"""
historical_source_mobile_combined.py

ARIYAN GEO AI - Phase 2.5 (Historical Research & Probable-Area Engine)

Thin combiner over the three independent, already-proven historical
evidence source modules:
    - historical_source_mobile_wikipedia.py   (grounded/established facts)
    - historical_source_mobile_archive.py     (book/publication discovery)
    - historical_source_mobile_wikisource.py  (primary-source text content)

This module does exactly ONE thing: call all three with the same
free-text query and merge the results into a single list, tagging each
item with which source produced it (all three already set a "source"
field, so nothing new needed there) and reporting per-source item counts
and per-source errors explicitly -- never silently swallowing a failure.

Deliberately NOT in scope here (per the agreed build order, 2026-09-15):
no claim-text -> geographic-area extraction, no Grand Project
persistence wiring, no AOI tiling. This is purely "prove the three
pieces can be combined" before any of that harder work starts.

Uses the defensive _safe wrapper from each source module rather than the
raising variant, because a single source's real network hiccup should
never prevent the other two from returning what they found -- matches
the project's existing "fully defensive/never blocks" pattern (same
philosophy as persistToGrandProject's wiring).
"""

import time

import historical_source_mobile_wikipedia as _wikipedia
import historical_source_mobile_archive as _archive
import historical_source_mobile_wikisource as _wikisource


# Registry of enabled sources: (name, safe-fetch-callable). Order here is
# also the order items are appended in the combined list, source-grouped.
_SOURCE_REGISTRY = {
    "wikipedia": _wikipedia.fetch_historical_evidence_wikipedia_safe,
    "internet_archive": _archive.fetch_historical_evidence_archive_safe,
    "wikisource": _wikisource.fetch_historical_evidence_wikisource_safe,
}

_ALL_SOURCE_NAMES = tuple(_SOURCE_REGISTRY.keys())


def fetch_combined_historical_evidence(query, max_results_per_source=10, enabled_sources=None):
    """Call the requested historical source modules with the same
    free-text query and merge their results.

    enabled_sources: iterable of source names to actually call, a subset
    of ("wikipedia", "internet_archive", "wikisource"). None (default)
    means all three. An unknown name raises ValueError immediately --
    that is a real caller bug, not a network failure, so it is NOT
    swallowed the way per-source network errors are.

    Returns a dict (never raises for a source's own network/parse
    failure -- those are reported, not hidden):
        {
            "query": str,
            "retrieval_date": str,             # ISO 8601 UTC, generated once for the whole call
            "items": [ ... ],                  # merged list, source-grouped in registry order;
                                                # each item is exactly as its own source module
                                                # defined it (already carries a "source" field)
            "source_counts": {name: int, ...},  # items actually returned per source
            "source_errors": {name: str or None, ...},  # None = that source succeeded
        }
    """
    if enabled_sources is None:
        names = _ALL_SOURCE_NAMES
    else:
        names = tuple(enabled_sources)
        unknown = set(names) - set(_ALL_SOURCE_NAMES)
        if unknown:
            raise ValueError(
                "Unknown historical source(s) requested: %s. Valid names: %s"
                % (sorted(unknown), _ALL_SOURCE_NAMES)
            )

    retrieval_date = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    items = []
    source_counts = {}
    source_errors = {}

    for name in names:
        safe_fetch = _SOURCE_REGISTRY[name]
        source_items, error = safe_fetch(query, max_results_per_source)
        items.extend(source_items)
        source_counts[name] = len(source_items)
        source_errors[name] = error

    return {
        "query": query,
        "retrieval_date": retrieval_date,
        "items": items,
        "source_counts": source_counts,
        "source_errors": source_errors,
    }