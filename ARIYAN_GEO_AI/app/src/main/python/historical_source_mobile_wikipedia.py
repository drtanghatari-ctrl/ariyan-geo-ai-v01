"""
historical_source_mobile_archive.py

ARIYAN GEO AI - Phase 2.5 (Historical Research & Probable-Area Engine)

Second of two independent, self-contained keyless historical-evidence
source modules (Option C). Mirrors the existing *_source_mobile.py
convention: own error class, own hard-deadline HTTP wrapper, returns
structured real evidence items with genuine provenance.

Data source: Internet Archive's advancedsearch.php (the "General Metadata
Search" -- item title/creator/description/subject/year), scoped by
default to mediatype:texts. No API key, no account, no signup required.

IMPORTANT SCOPE CORRECTION (found by live-testing during development,
2026-09-15): archive.org's advancedsearch.php only searches item
METADATA. It does NOT search the actual OCR'd text inside scanned books
-- that is a separate "Full-Text Search" feature backed by an internal,
undocumented endpoint (fulltext/inside.php) that (a) requires already
knowing a specific item to search inside, i.e. it is not corpus-wide, and
(b) was observed failing in a live public bug report. Building a real
evidence source on that endpoint would mean depending on something
neither stable nor genuinely corpus-searchable, so this module
deliberately does NOT attempt full-text-inside search.

Honest scope of what this module actually does: DISCOVERS real, citable
books/publications/media relevant to a query (e.g. surfaces an actual
book like "Gold Warriors: America's Secret Recovery of Yamashita's Gold"
by Seagrave & Seagrave) -- it does not search inside their pages. This
complements historical_source_mobile_wikisource.py, which DOES return
real historical-text CONTENT (primary-source chronicles/encyclopedia
entries), and historical_source_mobile_wikipedia.py, which covers
grounded/established facts. None of the three fakes coverage the others
provide -- same "no single source fakes independence" philosophy as the
app's satellite evidence-independence weighting.

Defaults to mediatype:texts (real books/publications) rather than every
media type IA hosts, to stay aligned with the "old chronicles /
out-of-copyright histories" intent that motivated this module. Callers
that want audio/video/other media discovered too can pass
media_types=None or a custom list.
"""

import json
import time
import urllib.request
import urllib.parse
import urllib.error


ARCHIVE_ORG_SEARCH_BASE = "https://archive.org/advancedsearch.php"
USER_AGENT = "ARIYAN-GEO-AI/1.0 (historical-evidence-source; contact: repo owner)"

# Hard deadline for the whole HTTP round-trip -- same discipline as the
# Wikipedia source module. Fail loudly with a real error rather than hang
# the calling investigation run.
_HTTP_TIMEOUT_SECONDS = 15

_FIELDS = ["identifier", "title", "mediatype", "year", "creator", "description"]


class ArchiveOrgSourceError(Exception):
    """Raised on any real failure to fetch or parse Internet Archive
    metadata search results.

    Never swallow this silently -- let it surface to the calling
    investigation code so the real error reaches the on-screen UI text,
    per the project's no-ADB debugging discipline.
    """
    pass


def _normalize_text_field(value):
    """archive.org's advancedsearch.php returns some fields (notably
    creator and description) as EITHER a single string OR a list of
    strings, depending on the item -- confirmed by live testing, not
    assumed. Normalize both shapes to a single clean string so downstream
    code never has to special-case it.
    """
    if value is None:
        return None
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if v is not None and str(v).strip()]
        return " | ".join(parts) if parts else None
    text = str(value).strip()
    return text if text else None


def _identifier_to_url(identifier):
    """Build the canonical Internet Archive item page URL from its
    identifier. This is IA's own stable, documented URL convention.
    """
    return "https://archive.org/details/" + urllib.parse.quote(identifier, safe="")


def _fetch_raw(query, max_results, media_types, timeout_seconds):
    """Hard-deadline HTTP wrapper around the real Internet Archive
    advancedsearch.php call. Raises ArchiveOrgSourceError on any network,
    HTTP-status, or JSON-shape failure. Never returns fabricated data.
    """
    if not query or not query.strip():
        raise ArchiveOrgSourceError("Empty query passed to Internet Archive historical source.")

    solr_query = query.strip()
    if media_types:
        media_clause = " OR ".join("mediatype:%s" % mt for mt in media_types)
        solr_query = "(%s) AND (%s)" % (solr_query, media_clause)

    params = {
        "q": solr_query,
        "fl[]": _FIELDS,
        "rows": str(max(1, min(int(max_results), 50))),
        "output": "json",
    }
    # doseq=True is required here -- confirmed by live testing during
    # development that omitting it silently produces malformed fl[]
    # params and every result field comes back empty.
    url = ARCHIVE_ORG_SEARCH_BASE + "?" + urllib.parse.urlencode(params, doseq=True)

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise ArchiveOrgSourceError(
                    "Internet Archive returned HTTP %s for query %r" % (status, query)
                )
            raw_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise ArchiveOrgSourceError(
            "Internet Archive HTTP error %s for query %r: %s" % (exc.code, query, exc.reason)
        )
    except urllib.error.URLError as exc:
        raise ArchiveOrgSourceError(
            "Internet Archive network error for query %r: %s" % (query, exc.reason)
        )
    except Exception as exc:
        # Includes socket.timeout on the hard deadline above.
        raise ArchiveOrgSourceError(
            "Internet Archive request failed for query %r: %s" % (query, exc)
        )

    try:
        data = json.loads(raw_body)
    except (ValueError, TypeError) as exc:
        raise ArchiveOrgSourceError(
            "Internet Archive returned non-JSON body for query %r: %s" % (query, exc)
        )

    return data


def fetch_historical_evidence_archive(query, max_results=10, media_types=("texts",),
                                       timeout_seconds=_HTTP_TIMEOUT_SECONDS):
    """Take a free-text scientific/historical question, call the real
    Internet Archive metadata search, and return a list of structured
    real DISCOVERY items -- real books/publications relevant to the
    query, NOT full-text content matches (see module docstring for why).

    media_types defaults to ("texts",) to stay aligned with the "old
    chronicles / out-of-copyright histories" intent. Pass None to search
    across every media type IA hosts (movies, audio, etc.), or a custom
    tuple/list to scope differently.

    Each item:
        {
            "source": "internet_archive",
            "identifier": str,           # IA's own stable item identifier
            "title": str,
            "url": str,                  # canonical archive.org/details/ URL
            "mediatype": str or None,
            "year": int/str or None,     # as IA returns it, not normalized further
            "creator": str or None,      # normalized from string-or-list
            "description": str or None,  # normalized from string-or-list
            "retrieval_date": str,       # ISO 8601 UTC, generated at call time
        }

    Raises ArchiveOrgSourceError on any failure -- never returns
    fabricated or partial-but-unlabeled results.
    """
    data = _fetch_raw(query, max_results, media_types, timeout_seconds)

    try:
        docs = data["response"]["docs"]
    except (KeyError, TypeError) as exc:
        raise ArchiveOrgSourceError(
            "Unexpected Internet Archive response shape for query %r "
            "(missing response.docs): %s. Raw keys: %s"
            % (query, exc, list(data.keys()) if isinstance(data, dict) else type(data))
        )

    retrieval_date = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    items = []
    for doc in docs:
        identifier = doc.get("identifier")
        if not identifier:
            # Real API returned a malformed entry -- skip it, don't fabricate
            # an identifier, but don't crash the whole batch over one bad entry.
            continue
        items.append({
            "source": "internet_archive",
            "identifier": identifier,
            "title": doc.get("title") or identifier,
            "url": _identifier_to_url(identifier),
            "mediatype": doc.get("mediatype"),
            "year": doc.get("year"),
            "creator": _normalize_text_field(doc.get("creator")),
            "description": _normalize_text_field(doc.get("description")),
            "retrieval_date": retrieval_date,
        })

    return items


def fetch_historical_evidence_archive_safe(query, max_results=10, media_types=("texts",),
                                            timeout_seconds=_HTTP_TIMEOUT_SECONDS):
    """Defensive wrapper for call sites that must never crash the visible
    investigation run over a historical-source failure. Returns an empty
    list and lets the caller decide how/whether to surface the error
    text, instead of raising. See fetch_historical_evidence_archive() for
    the raising version, and historical_source_mobile_wikipedia.py's
    equivalent _safe wrapper for the pattern this mirrors.
    """
    try:
        return fetch_historical_evidence_archive(query, max_results, media_types, timeout_seconds), None
    except ArchiveOrgSourceError as exc:
        return [], str(exc)