"""
geocoding_source_mobile_nominatim.py

ARIYAN GEO AI - Phase 2.5 (Historical Research & Probable-Area Engine)

Real-place-name -> real-coordinates geocoding, via Nominatim (OpenStreetMap's
free geocoding service). No API key, no account, no signup required.
Mirrors the existing *_source_mobile.py convention: own error class, own
hard-deadline HTTP wrapper.

Response shape confirmed by a LIVE call during development (2026-09-15):
    [{"place_id": ..., "lat": "29.9351669", "lon": "52.8904041",
      "display_name": "...", "boundingbox": ["29.93..","29.93..","52.88..","52.89.."],
      "osm_type": "way", ...}]
lat/lon come back as STRINGS, not numbers -- confirmed, not assumed.
boundingbox order confirmed as [min_lat, max_lat, min_lon, max_lon].
A place name with no real match returns an empty array (confirmed live
with a nonsense query) -- this is a real "not found" result, not an
error, and is represented here as a real None return, never fabricated
coordinates.

RATE LIMIT (Nominatim's own usage policy, not a project preference):
absolute max 1 request/second, and a real identifying User-Agent is
required. This module enforces the 1-req/sec ceiling itself at the
module level (a small sleep before any request that would otherwise
exceed it), so callers doing multiple lookups in a loop can't
accidentally violate Nominatim's policy and risk this app's requests
getting blocked. This is a free, shared public service -- not something
to hammer with bulk/production-scale traffic; if this ever needs
heavier volume than one-at-a-time historical-claim lookups, a
self-hosted Nominatim instance or a paid geocoding provider would be
the honest next step, not raising this module's internal rate limit.
"""

import json
import time
import urllib.request
import urllib.parse
import urllib.error


NOMINATIM_SEARCH_BASE = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "ARIYAN-GEO-AI/1.0 (geocoding-source; contact: repo owner)"

_HTTP_TIMEOUT_SECONDS = 15

# Nominatim's usage policy hard ceiling is 1 request/second. Use 1.1s to
# leave real margin rather than race the exact limit.
_MIN_SECONDS_BETWEEN_REQUESTS = 1.1
_last_request_monotonic = [None]  # mutable single-element list so it can be updated from a module-level function


class NominatimGeocodingError(Exception):
    """Raised on any real failure to reach or parse the Nominatim
    geocoding API.

    A place name with no real match is NOT this exception -- that is a
    genuine "not found" result, represented as a None return from
    geocode_place_name(). This exception is only for actual network,
    HTTP-status, or JSON-shape failures.
    """
    pass


def _respect_rate_limit():
    """Enforce Nominatim's 1-request/second usage-policy ceiling at the
    module level, regardless of how the caller sequences its own calls.
    """
    last = _last_request_monotonic[0]
    if last is not None:
        elapsed = time.monotonic() - last
        remaining = _MIN_SECONDS_BETWEEN_REQUESTS - elapsed
        if remaining > 0:
            time.sleep(remaining)
    _last_request_monotonic[0] = time.monotonic()


def geocode_place_name(place_name, timeout_seconds=_HTTP_TIMEOUT_SECONDS):
    """Resolve a real place name to real coordinates via Nominatim.

    Returns None if Nominatim genuinely has no match for this place name
    -- a real "not found" result, never fabricated coordinates.

    On a real match, returns:
        {
            "query": str,                # the place name that was looked up
            "resolved_name": str,        # Nominatim's own display_name for the match
            "lat": float,
            "lon": float,
            "bounding_box": {
                "min_lat": float, "max_lat": float,
                "min_lon": float, "max_lon": float,
            },
            "osm_type": str or None,
            "place_id": int or None,     # Nominatim's own id, for reference/debugging
            "retrieval_date": str,       # ISO 8601 UTC, generated at call time
        }

    Raises NominatimGeocodingError on any real network, HTTP-status, or
    JSON-shape failure. Never returns fabricated coordinates.
    """
    if not place_name or not place_name.strip():
        raise NominatimGeocodingError("Empty place name passed to Nominatim geocoding source.")

    _respect_rate_limit()

    params = {
        "q": place_name.strip(),
        "format": "json",
        "limit": "1",
        "addressdetails": "0",
    }
    url = NOMINATIM_SEARCH_BASE + "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise NominatimGeocodingError(
                    "Nominatim returned HTTP %s for place name %r" % (status, place_name)
                )
            raw_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise NominatimGeocodingError(
            "Nominatim HTTP error %s for place name %r: %s" % (exc.code, place_name, exc.reason)
        )
    except urllib.error.URLError as exc:
        raise NominatimGeocodingError(
            "Nominatim network error for place name %r: %s" % (place_name, exc.reason)
        )
    except Exception as exc:
        raise NominatimGeocodingError(
            "Nominatim request failed for place name %r: %s" % (place_name, exc)
        )

    try:
        results = json.loads(raw_body)
    except (ValueError, TypeError) as exc:
        raise NominatimGeocodingError(
            "Nominatim returned non-JSON body for place name %r: %s" % (place_name, exc)
        )

    if not isinstance(results, list):
        raise NominatimGeocodingError(
            "Unexpected Nominatim response shape for place name %r: expected a list, got %s"
            % (place_name, type(results))
        )

    if not results:
        return None  # real "not found" -- not an error, not fabricated coordinates

    match = results[0]

    try:
        lat = float(match["lat"])
        lon = float(match["lon"])
        bbox_raw = match["boundingbox"]
        bounding_box = {
            "min_lat": float(bbox_raw[0]),
            "max_lat": float(bbox_raw[1]),
            "min_lon": float(bbox_raw[2]),
            "max_lon": float(bbox_raw[3]),
        }
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise NominatimGeocodingError(
            "Unexpected Nominatim match shape for place name %r: %s. Raw match: %r"
            % (place_name, exc, match)
        )

    return {
        "query": place_name.strip(),
        "resolved_name": match.get("display_name", place_name.strip()),
        "lat": lat,
        "lon": lon,
        "bounding_box": bounding_box,
        "osm_type": match.get("osm_type"),
        "place_id": match.get("place_id"),
        "retrieval_date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def geocode_place_name_safe(place_name, timeout_seconds=_HTTP_TIMEOUT_SECONDS):
    """Defensive wrapper mirroring the _safe pattern in the other source
    modules. Returns (result_or_None, error_or_None) instead of raising
    -- for call sites that must never crash over a geocoding failure.
    Note this has THREE possible outcomes in effect: a real match
    (result, None), a real not-found (None, None), and a real failure
    (None, error_string) -- callers should check both fields, not just
    truthiness of the first.
    """
    try:
        return geocode_place_name(place_name, timeout_seconds), None
    except NominatimGeocodingError as exc:
        return None, str(exc)