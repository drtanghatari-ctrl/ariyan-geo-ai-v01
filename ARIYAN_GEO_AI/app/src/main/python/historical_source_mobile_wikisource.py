"""
historical_source_mobile_wikisource.py

ARIYAN GEO AI - Phase 2.5 (Historical Research & Probable-Area Engine)

Third historical-evidence source module. Mirrors the existing
*_source_mobile.py convention: own error class, own hard-deadline HTTP
wrapper, returns structured real evidence items with genuine provenance.

Data source: Wikisource Search API -- the SAME MediaWiki Action API as
historical_source_mobile_wikipedia.py, just pointed at
en.wikisource.org instead of en.wikipedia.org. No API key, no account,
no signup required. Response shape confirmed identical by a live call
during development (2026-09-15).

Why this exists alongside the other two: Wikisource hosts real
PRIMARY-SOURCE historical text content -- old encyclopedia entries
(e.g. 1911 Encyclopaedia Britannica), historical textbooks, translated
chronicles -- not encyclopedic summaries (that's Wikipedia) and not book
DISCOVERY without content (that's historical_source_mobile_archive.py,
which is metadata-only, see its module docstring for why). Wikisource is
the closest of the three to "old chronicles" in actual readable-content
form, confirmed live: a search for "Darius Persepolis treasure" returned
real passages from period sources describing Alexander seizing treasure
at Persepolis -- genuine primary-source-adjacent historical evidence,
with real snippet text, not a summary written about it.

This module deliberately duplicates historical_source_mobile_wikipedia.py's
structure rather than sharing code with it, matching this project's
existing convention of fully independent, self-contained source modules
(so a bug in one never ripples into another).
"""

import json
import time
import re
import urllib.request
import urllib.parse
import urllib.error


WIKISOURCE_API_BASE = "https://en.wikisource.org/w/api.php"
USER_AGENT = "ARIYAN-GEO-AI/1.0 (historical-evidence-source; contact: repo owner)"

# Hard deadline for the whole HTTP round-trip -- same discipline as the
# other two historical source modules.
_HTTP_TIMEOUT_SECONDS = 15

_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_MAP = {
    "&#039;": "'",
    "&quot;": '"',
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
}


class WikisourceSourceError(Exception):
    """Raised on any real failure to fetch or parse Wikisource search
    results.

    Never swallow this silently -- let it surface to the calling
    investigation code so the real error reaches the on-screen UI text,
    per the project's no-ADB debugging discipline.
    """
    pass


def _clean_snippet(raw_snippet):
    """Strip HTML tags and un-escape the common entities Wikisource emits
    in its search snippets (identical behavior to the Wikipedia module --
    same underlying MediaWiki search engine).
    """
    if not raw_snippet:
        return ""
    text = _TAG_RE.sub("", raw_snippet)
    for entity, replacement in _ENTITY_MAP.items():
        text = text.replace(entity, replacement)
    return text.strip()


def _title_to_url(title):
    """Build the canonical Wikisource page URL from its title, using the
    same underscore + percent-encode convention as Wikipedia (both run
    the same MediaWiki software).
    """
    underscored = title.replace(" ", "_")
    return "https://en.wikisource.org/wiki/" + urllib.parse.quote(underscored, safe="_():,/")


def _fetch_raw(query, max_results, timeout_seconds):
    """Hard-deadline HTTP wrapper around the real Wikisource Search API
    call. Raises WikisourceSourceError on any network, HTTP-status, or
    JSON-shape failure. Never returns fabricated data.
    """
    if not query or not query.strip():
        raise WikisourceSourceError("Empty query passed to Wikisource historical source.")

    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "utf8": "1",
        "srlimit": str(max(1, min(int(max_results), 50))),
        "srsearch": query.strip(),
    }
    url = WIKISOURCE_API_BASE + "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise WikisourceSourceError(
                    "Wikisource API returned HTTP %s for query %r" % (status, query)
                )
            raw_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise WikisourceSourceError(
            "Wikisource API HTTP error %s for query %r: %s" % (exc.code, query, exc.reason)
        )
    except urllib.error.URLError as exc:
        raise WikisourceSourceError(
            "Wikisource API network error for query %r: %s" % (query, exc.reason)
        )
    except Exception as exc:
        # Includes socket.timeout on the hard deadline above.
        raise WikisourceSourceError(
            "Wikisource API request failed for query %r: %s" % (query, exc)
        )

    try:
        data = json.loads(raw_body)
    except (ValueError, TypeError) as exc:
        raise WikisourceSourceError(
            "Wikisource API returned non-JSON body for query %r: %s" % (query, exc)
        )

    return data


def fetch_historical_evidence_wikisource(query, max_results=10, timeout_seconds=_HTTP_TIMEOUT_SECONDS):
    """Take a free-text scientific/historical question, call the real
    Wikisource Search API, and return a list of structured real
    primary-source-adjacent evidence items, each with genuine provenance.

    Each item:
        {
            "source": "wikisource",
            "title": str,               # real page title (often "Work/Chapter" form)
            "url": str,                 # canonical page URL, built from title
            "snippet": str,              # cleaned excerpt of real historical text
            "pageid": int,               # Wikisource's own page id
            "wordcount": int,            # real page length in words
            "last_edited": str or None,  # ISO 8601 timestamp of last edit, from the API
            "retrieval_date": str,       # ISO 8601 UTC, generated at call time
        }

    Raises WikisourceSourceError on any failure -- never returns
    fabricated or partial-but-unlabeled results.
    """
    data = _fetch_raw(query, max_results, timeout_seconds)

    try:
        search_results = data["query"]["search"]
    except (KeyError, TypeError) as exc:
        raise WikisourceSourceError(
            "Unexpected Wikisource API response shape for query %r "
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
            "source": "wikisource",
            "title": title,
            "url": _title_to_url(title),
            "snippet": _clean_snippet(result.get("snippet", "")),
            "pageid": result.get("pageid"),
            "wordcount": result.get("wordcount"),
            "last_edited": result.get("timestamp"),
            "retrieval_date": retrieval_date,
        })

    return items


def fetch_historical_evidence_wikisource_safe(query, max_results=10, timeout_seconds=_HTTP_TIMEOUT_SECONDS):
    """Defensive wrapper for call sites that must never crash the visible
    investigation run over a historical-source failure. Returns an empty
    list and lets the caller decide how/whether to surface the error
    text, instead of raising. Mirrors the equivalent _safe wrappers in
    the Wikipedia and Internet Archive source modules.
    """
    try:
        return fetch_historical_evidence_wikisource(query, max_results, timeout_seconds), None
    except WikisourceSourceError as exc:
        return [], str(exc)