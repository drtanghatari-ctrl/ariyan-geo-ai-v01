"""
historical_source_mobile_wikipedia.py

ARIYAN GEO AI - Phase 2.5 (Historical Research & Probable-Area Engine)

One of two independent, self-contained keyless historical-evidence source
modules (Option C, decided 2026-09-15 after the Tavily key was retired in
favor of free/keyless sources). Mirrors the existing *_source_mobile.py
convention used by dem_source_mobile.py / ndvi_source_mobile.py / etc.:
own error class, own hard-deadline HTTP wrapper, returns structured real
evidence items with genuine provenance (title, URL, snippet, retrieval date).

Data source: Wikipedia Search API (MediaWiki Action API), action=query,
list=search. No API key, no account, no signup required.

Real response shape confirmed by a LIVE call during development
(2026-09-15) -- not copied from documentation without checking, because a
docs claim that inprop=url would add a "url" field to each search result
did NOT hold up against the real live response. The URL is therefore built
from the page title using Wikipedia's own well-established URL convention
(spaces -> underscores, percent-encoded), not fetched from a field that
does not reliably exist.

Scope note: Wikipedia is encyclopedic, not exhaustive. It reliably surfaces
established historical facts (e.g. Persepolis's location, Darius III's
death) but is honestly weak on fringe/speculative treasure-hunt claims,
which tend to live off-Wikipedia. This module is the "grounded facts" half
of the pair; historical_source_mobile_archive.py (Internet Archive
full-text search, not yet built) is meant to cover that gap.

This module proves ONE thing only: the app can really call the Wikipedia
API from the Chaquopy Python layer and get back real, citable evidence. No
Grand Project wiring, no AOI/geographic extraction, no dashboard here yet.
"""

import json
import time
import re
import urllib.request
import urllib.parse
import urllib.error


WIKIPEDIA_API_BASE = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "ARIYAN-GEO-AI/1.0 (historical-evidence-source; contact: repo owner)"

# Hard deadline for the whole HTTP round-trip. If Wikipedia doesn't answer
# in this window, we fail loudly with a real error rather than hang the
# calling investigation run. Matches the project's "widened try/catch,
# report real errors to on-screen UI text" discipline (no ADB/logcat on
# the user's device).
_HTTP_TIMEOUT_SECONDS = 15

# Strip the <span class="searchmatch">...</span> highlighting (and any
# other stray tags) that Wikipedia's snippet field embeds, so downstream
# code gets clean text, not markup.
_TAG_RE = re.compile(r"<[^>]+>")
# MediaWiki also HTML-entity-escapes snippets (e.g. &#039; for an
# apostrophe, &amp; for &). Cover the common cases actually seen live.
_ENTITY_MAP = {
    "&#039;": "'",
    "&quot;": '"',
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
}


class WikipediaSourceError(Exception):
    """Raised on any real failure to fetch or parse Wikipedia search results.

    Never swallow this silently -- let it surface to the calling
    investigation code so the real error reaches the on-screen UI text,
    per the project's no-ADB debugging discipline.
    """
    pass


def _clean_snippet(raw_snippet):
    """Strip HTML tags and un-escape the common entities Wikipedia emits
    in its search snippets. Real transformation of real text -- not a
    fabrication of new content.
    """
    if not raw_snippet:
        return ""
    text = _TAG_RE.sub("", raw_snippet)
    for entity, replacement in _ENTITY_MAP.items():
        text = text.replace(entity, replacement)
    return text.strip()


def _title_to_url(title):
    """Build the canonical Wikipedia article URL from a page title using
    Wikipedia's own established convention (spaces -> underscores, then
    percent-encoded). Confirmed necessary during development: the API's
    inprop=url parameter did NOT actually populate a url field in the
    real live response, despite third-party docs suggesting it would --
    so we do not depend on that field existing.
    """
    underscored = title.replace(" ", "_")
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(underscored, safe="_():,")


def _fetch_raw(query, max_results, timeout_seconds):
    """Hard-deadline HTTP wrapper around the real Wikipedia Search API
    call. Raises WikipediaSourceError on any network, HTTP-status, or
    JSON-shape failure. Never returns fabricated data.
    """
    if not query or not query.strip():
        raise WikipediaSourceError("Empty query passed to Wikipedia historical source.")

    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "utf8": "1",
        "srlimit": str(max(1, min(int(max_results), 50))),
        "srsearch": query.strip(),
    }
    url = WIKIPEDIA_API_BASE + "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise WikipediaSourceError(
                    "Wikipedia API returned HTTP %s for query %r" % (status, query)
                )
            raw_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise WikipediaSourceError(
            "Wikipedia API HTTP error %s for query %r: %s" % (exc.code, query, exc.reason)
        )
    except urllib.error.URLError as exc:
        raise WikipediaSourceError(
            "Wikipedia API network error for query %r: %s" % (query, exc.reason)
        )
    except Exception as exc:
        # Includes socket.timeout on the hard deadline above.
        raise WikipediaSourceError(
            "Wikipedia API request failed for query %r: %s" % (query, exc)
        )

    try:
        data = json.loads(raw_body)
    except (ValueError, TypeError) as exc:
        raise WikipediaSourceError(
            "Wikipedia API returned non-JSON body for query %r: %s" % (query, exc)
        )

    return data


def fetch_historical_evidence_wikipedia(query, max_results=10, timeout_seconds=_HTTP_TIMEOUT_SECONDS):
    """Take a free-text scientific/historical question, call the real
    Wikipedia Search API, and return a list of structured real evidence
    items, each with genuine provenance.

    Each item:
        {
            "source": "wikipedia",
            "title": str,               # real page title
            "url": str,                 # canonical article URL, built from title
            "snippet": str,              # cleaned excerpt (HTML/entities stripped)
            "pageid": int,               # Wikipedia's own page id
            "wordcount": int,            # real article length in words
            "last_edited": str or None,  # ISO 8601 timestamp of last edit, from the API
            "retrieval_date": str,       # ISO 8601 UTC, generated at call time
        }

    Raises WikipediaSourceError on any failure -- never returns fabricated
    or partial-but-unlabeled results.
    """
    data = _fetch_raw(query, max_results, timeout_seconds)

    try:
        search_results = data["query"]["search"]
    except (KeyError, TypeError) as exc:
        raise WikipediaSourceError(
            "Unexpected Wikipedia API response shape for query %r "
            "(missing query.search): %s. Raw keys: %s"
            % (query, exc, list(data.keys()) if isinstance(data, dict) else type(data))
        )

    retrieval_date = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    items = []
    for result in search_results:
        title = result.get("title")
        if not title:
            # Real API returned a malformed entry -- skip it, don't fabricate
            # a title, but don't crash the whole batch over one bad entry.
            continue
        items.append({
            "source": "wikipedia",
            "title": title,
            "url": _title_to_url(title),
            "snippet": _clean_snippet(result.get("snippet", "")),
            "pageid": result.get("pageid"),
            "wordcount": result.get("wordcount"),
            "last_edited": result.get("timestamp"),
            "retrieval_date": retrieval_date,
        })

    return items


def fetch_historical_evidence_wikipedia_safe(query, max_results=10, timeout_seconds=_HTTP_TIMEOUT_SECONDS):
    """Defensive wrapper for call sites that must never crash the visible
    investigation run over a historical-source failure (mirrors the
    'fully defensive/never blocks' pattern used by
    grand_project_sync.persistToGrandProject wiring). Returns an empty
    list and lets the caller decide how/whether to surface the error
    text, instead of raising.

    Prefer fetch_historical_evidence_wikipedia() directly wherever the
    caller DOES want the real error to propagate (e.g. a dedicated
    "test this source" screen) -- this _safe variant is for the main
    investigation flow only.
    """
    try:
        return fetch_historical_evidence_wikipedia(query, max_results, timeout_seconds), None
    except WikipediaSourceError as exc:
        return [], str(exc)