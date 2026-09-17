"""
historical_source_mobile_wikipedia.py

ARIYAN GEO AI - Phase 2.5 (Historical Research & Probable-Area Engine)

RECREATED 2026-09-17: this module's real content was missing from the
repo -- the file at this exact path had been silently overwritten with
historical_source_mobile_archive.py's own content (confirmed via a
repo-wide grep and a real Python import test: this file previously
defined fetch_historical_evidence_archive_safe, not
fetch_historical_evidence_wikipedia_safe, which is why
historical_source_mobile_combined.py could not actually run end-to-end
despite being described elsewhere as complete). This is the same
"wrong-filename commit" failure mode this project has hit once before
(grand_project_sync.py/historical sync, Phase 2 session) -- recurring
silently rather than caught immediately, since nothing had ever
exercised this import path on a real device (no Kotlin UI called into
Phase 2.5 yet). Rebuilt here from scratch, live-tested against the real
Wikipedia API before delivery -- not restored from a backup that may not
exist, and not guessed from memory of what it "should" contain.

First of three independent, self-contained keyless historical-evidence
source modules (Option C). Mirrors the existing *_source_mobile.py
convention: own error class, own hard-deadline HTTP wrapper, returns
structured real evidence items with genuine provenance.

Data source: Wikipedia Search API -- the SAME MediaWiki Action API as
historical_source_mobile_wikisource.py, just pointed at
en.wikipedia.org instead of en.wikisource.org. No API key, no account,
no signup required.

Why this exists alongside the other two: Wikipedia covers grounded,
established, encyclopedic facts about a topic -- not primary-source
historical text content (that's Wikisource) and not book DISCOVERY
without content (that's historical_source_mobile_archive.py, metadata-
only, see its own module docstring for why). This module deliberately
duplicates historical_source_mobile_wikisource.py's structure rather
than sharing code with it, matching this project's existing convention
of fully independent, self-contained source modules (so a bug in one
never ripples into another).
"""

import json
import time
import re
import urllib.request
import urllib.parse
import urllib.error


WIKIPEDIA_API_BASE = "https://en.wikipedia.org/w/api.php"
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


class WikipediaSourceError(Exception):
    """Raised on any real failure to fetch or parse Wikipedia search
    results.

    Never swallow this silently -- let it surface to the calling
    investigation code so the real error reaches the on-screen UI text,
    per the project's no-ADB debugging discipline.
    """
    pass


def _clean_snippet(raw_snippet):
    """Strip HTML tags and un-escape the common entities Wikipedia emits
    in its search snippets (identical behavior to the Wikisource module --
    same underlying MediaWiki search engine)."""
    if not raw_snippet:
        return ""
    text = _TAG_RE.sub("", raw_snippet)
    for entity, replacement in _ENTITY_MAP.items():
        text = text.replace(entity, replacement)
    return text.strip()


def _title_to_url(title):
    """Build the canonical Wikipedia page URL from its title, using the
    same underscore + percent-encode convention as Wikisource (both run
    the same MediaWiki software)."""
    underscored = title.replace(" ", "_")
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(underscored, safe="_():,/")


def _fetch_raw(query, max_results, timeout_seconds):
    """Hard-deadline HTTP wrapper around the real Wikipedia Search API
    call. Raises WikipediaSourceError on any network, HTTP-status, or
    JSON-shape failure. Never returns fabricated data."""
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
    Wikipedia Search API, and return a list of structured real
    grounded/established-fact evidence items, each with genuine
    provenance.

    Each item:
        {
            "source": "wikipedia",
            "title": str,               # real page title
            "url": str,                 # canonical page URL, built from title
            "snippet": str,              # cleaned excerpt of real article text
            "pageid": int,               # Wikipedia's own page id
            "wordcount": int,            # real page length in words
            "last_edited": str or None,  # ISO 8601 timestamp of last edit, from the API
            "retrieval_date": str,       # ISO 8601 UTC, generated at call time
        }

    Raises WikipediaSourceError on any failure -- never returns
    fabricated or partial-but-unlabeled results.
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
    investigation run over a historical-source failure. Returns an empty
    list and lets the caller decide how/whether to surface the error
    text, instead of raising. Mirrors the equivalent _safe wrappers in
    the Wikisource and Internet Archive source modules.
    """
    try:
        return fetch_historical_evidence_wikipedia(query, max_results, timeout_seconds), None
    except WikipediaSourceError as exc:
        return [], str(exc)
