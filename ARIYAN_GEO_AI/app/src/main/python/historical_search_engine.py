"""
historical_search_engine.py

ARIYAN GEO AI - Historical Search REBUILD, engine version "hs-v1",
ADDED 2026-10-01 (Python engine first; Kotlin display + persistence of
located findings is the next step).

WHY THIS EXISTS (diagnosis 2026-10-01): the Phase 2.5 pipeline searched
only en.wikipedia + Wikisource + Internet Archive, so a Persian query
returned 0 results, and its only route to a map position was
regex-extracting Title-Case words from snippets and geocoding them
worldwide with Nominatim (e.g. "Persian Gate" -> England/France). That
route answers "which capitalised words geocode somewhere", not "where
is the thing I asked about". This engine answers the second question
directly, from the coordinate the SOURCE ITSELF records for the subject
of the article / gazetteer entry -- no word guessing, no worldwide
geocoding.

SOURCES (all keyless, all real HTTP calls, nothing synthetic):
    1. Wikipedia search, English AND Persian (en/fa) -- finds the
       subject; each hit is mapped to its Wikidata item (pageprops).
    2. Wikidata -- structured record of that item: coordinate (P625),
       country (P17), instance-of (P31), point in time (P585/P580),
       Pleiades id (P1584), en/fa labels and sitelinks. One item that
       appears in both language searches is merged into ONE finding.
    3. Pleiades (pleiades.stoa.org) -- the specialist ancient-world
       gazetteer: free-text search plus a direct lookup for every
       Wikidata item that carries a Pleiades id.
    4. OpenAlex -- scholarly literature DISCOVERY only (titles, year,
       DOI). Never a coordinate; the papers' content is not read.

TIERS (fixed definitions, shown with every coordinate; no confidence
percentages anywhere -- none can be honestly computed here):
    A = coordinate from a specialist scholarly gazetteer record that
        the gazetteer itself marks as LOCATED with PRECISE location
        precision (Pleiades; rough-only points are not used). OpenAlex works
        are also tier A, but as literature-exists pointers only.
    B = coordinate from a community-edited encyclopedic source
        (Wikidata P625 or the Wikipedia article's own coordinate).
        `referenced` says whether the Wikidata statement cites a source.
    C = anything inferred from free text (e.g. the legacy
        name-in-snippet + Nominatim route) or a general web search.
        This engine produces NO tier-C coordinates.
A coordinate of any tier is the recorded position of the article /
gazetteer SUBJECT. It is not a verified archaeological position, and
for events (battles etc.) the true site may be debated in scholarship.

NO FILTERING, ONLY FLAGS (same spirit as the 2026-09-16 "persist every
suggestion" decision): results outside Iran are kept and flagged
(`in_iran` False), never dropped. `in_iran` is read from Wikidata P17
only (True / False / None = not recorded); no bounding-box guessing.

PLEIADES "UNLOCATED" TRAP (found while building this, 2026-10-01): an
unlocated Pleiades place (placeTypes contains "unlocated", e.g. Maitona)
still carries a `reprPoint`. That point is NOT a location and is never
used as one here -- such places go to unlocated_findings.

ORDERING: findings keep the order the sources' own search ranking gave
them (Wikipedia rank, en and fa interleaved; Pleiades-only hits after).
It is search rank, not likelihood.

Self-contained: stdlib only (Chaquopy-safe), own error class, own
hard-deadline HTTP helper, plus a whole-search time budget so one slow
source can never hang the screen.
"""

import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request


ENGINE_VERSION = "hs-v1"
USER_AGENT = "ARIYAN-GEO-AI/1.0 (historical-search-engine; contact: repo owner)"

_HTTP_TIMEOUT_SECONDS = 12
_TOTAL_BUDGET_SECONDS = 75

_WIKIPEDIA_API = {
    "en": "https://en.wikipedia.org/w/api.php",
    "fa": "https://fa.wikipedia.org/w/api.php",
}
_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_PLEIADES_SEARCH = "https://pleiades.stoa.org/search_rss"
_PLEIADES_PLACE_JSON = "https://pleiades.stoa.org/places/%s/json"
_OPENALEX_WORKS = "https://api.openalex.org/works"

_IRAN_QID = "Q794"
# Wikidata instance-of items that are EVENTS -- their coordinate gets the
# "site may be debated" caveat. Small explicit list, extend only with
# checked QIDs.
_EVENT_CLASS_QIDS = frozenset({
    "Q178561",   # battle
    "Q188055",   # siege
    "Q1190554",  # occurrence
    "Q1656682",  # event
    "Q645883",   # military operation
    "Q180684",   # conflict
})

_PERSIAN_CHAR_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
_TAG_RE = re.compile(r"<[^>]+>")

# Question / function words removed to build the keyword query. MediaWiki
# search ANDs every term, so a full natural-language question in Persian
# lost the right article (tested live 2026-10-01: "محل نبرد دربند پارس
# کجاست؟" missed it, "نبرد دربند پارس" found it first).
_EN_STOP = frozenset({
    "where", "was", "were", "is", "are", "the", "a", "an", "of", "did",
    "does", "do", "what", "which", "who", "when", "how", "located",
    "location", "fought", "happen", "happened", "take", "took", "exactly",
    "in", "at", "on", "to", "please", "find", "tell", "me", "about",
})
_FA_STOP = frozenset({
    "کجاست", "کجا", "کجای", "محل", "مکان", "موقعیت", "چیست", "چه",
    "کدام", "در", "به", "از", "را", "که", "و", "آیا", "این", "آن",
    "بود", "است", "شد", "دقیقا", "دقیقاً", "کجاس",
})
_PUNCT_RE = re.compile(r"[?؟!.,،;:()\"'«»\[\]]+")


class HistoricalSearchError(Exception):
    """A real failure to fetch/parse ONE source. Caught per source and
    reported in source_errors -- never hidden, never fatal for the
    other sources."""
    pass


class _Budget(object):
    """Whole-search wall-clock budget. Sources that would start after it
    is spent are recorded as skipped, not silently omitted."""

    def __init__(self, seconds):
        self.deadline = time.monotonic() + seconds

    def left(self):
        return self.deadline - time.monotonic()

    def check(self, what):
        if self.left() <= 1.0:
            raise HistoricalSearchError("skipped: search time budget spent before %s" % what)


def _http_get(url, params, budget, what, accept_json=True, _retried=False):
    budget.check(what)
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
    timeout = max(2.0, min(_HTTP_TIMEOUT_SECONDS, budget.left()))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                raise HistoricalSearchError("%s: HTTP %s" % (what, status))
            body = resp.read().decode("utf-8", errors="replace")
    except HistoricalSearchError:
        raise
    except urllib.error.HTTPError as exc:
        # ONE polite retry for rate-limit / temporary-unavailable answers
        # (OpenAlex returned 429 on back-to-back searches in live testing,
        # 2026-10-01). A second refusal is reported, not hidden.
        # Only when the server's own Retry-After is short: OpenAlex's
        # keyless daily budget answers 429 with Retry-After of HOURS
        # (until midnight UTC) -- waiting on that would be pointless.
        retry_after = None
        try:
            retry_after = float((exc.headers or {}).get("Retry-After"))
        except (TypeError, ValueError):
            retry_after = None
        if (exc.code in (429, 503) and not _retried and retry_after is not None
                and retry_after <= 5 and budget.left() > retry_after + 4):
            time.sleep(max(1.0, retry_after))
            return _http_get(url, params, budget, what, accept_json, _retried=True)
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8", errors="replace")).get("message") or ""
        except Exception:
            detail = ""
        if retry_after is not None and retry_after > 5:
            detail = ("server says retry after %.0f min. " % (retry_after / 60.0)) + detail
        raise HistoricalSearchError("%s: HTTP error %s %s%s%s" % (
            what, exc.code, exc.reason, " (after one retry)" if _retried else "",
            (" -- " + detail[:300]) if detail else ""))
    except urllib.error.URLError as exc:
        raise HistoricalSearchError("%s: network error %s" % (what, exc.reason))
    except Exception as exc:
        raise HistoricalSearchError("%s: request failed %s" % (what, exc))
    if not accept_json:
        return body
    try:
        return json.loads(body)
    except (ValueError, TypeError) as exc:
        raise HistoricalSearchError("%s: non-JSON response (%s)" % (what, exc))


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clean(text):
    if not text:
        return ""
    text = _TAG_RE.sub("", text)
    for a, b in (("&#039;", "'"), ("&quot;", '"'), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
        text = text.replace(a, b)
    return " ".join(text.split())


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def detect_script(query):
    """'persian' if the query contains Arabic-script letters, else 'latin'."""
    return "persian" if _PERSIAN_CHAR_RE.search(query or "") else "latin"


def keyword_query(query):
    """Drop question/function words (en + fa) and punctuation. Returns the
    original stripped query if nothing would be left."""
    stripped = _PUNCT_RE.sub(" ", query or "")
    words = [w for w in stripped.split() if w.lower() not in _EN_STOP and w not in _FA_STOP]
    reduced = " ".join(words).strip()
    return reduced or (query or "").strip()


def _wiki_url(lang, title):
    return "https://%s.wikipedia.org/wiki/%s" % (
        lang, urllib.parse.quote(title.replace(" ", "_"), safe="_():,/"))


# ---------------------------------------------------------------- Wikipedia

def _wikipedia_search(lang, query, limit, budget):
    data = _http_get(_WIKIPEDIA_API[lang], {
        "action": "query", "format": "json", "list": "search", "utf8": "1",
        "srlimit": str(max(1, min(int(limit), 20))), "srsearch": query,
    }, budget, "wikipedia_%s search" % lang)
    try:
        return data["query"]["search"]
    except (KeyError, TypeError):
        raise HistoricalSearchError("wikipedia_%s search: unexpected response shape" % lang)


def _wikipedia_pages(lang, pageids, budget):
    """pageprops (Wikidata id) + article's own primary coordinate + intro."""
    if not pageids:
        return {}
    data = _http_get(_WIKIPEDIA_API[lang], {
        "action": "query", "format": "json", "utf8": "1",
        "pageids": "|".join(str(p) for p in pageids),
        "prop": "pageprops|coordinates|extracts", "ppprop": "wikibase_item",
        "coprimary": "primary", "exintro": "1", "explaintext": "1",
        "exchars": "500", "exlimit": "max",
    }, budget, "wikipedia_%s pages" % lang)
    pages = (data.get("query") or {}).get("pages") or {}
    out = {}
    for pid, page in pages.items():
        coords = page.get("coordinates") or []
        primary = None
        for c in coords:
            if c.get("globe", "earth") == "earth" and "lat" in c and "lon" in c:
                primary = (float(c["lat"]), float(c["lon"]))
                break
        out[int(pid)] = {
            "title": page.get("title"),
            "qid": (page.get("pageprops") or {}).get("wikibase_item"),
            "coordinate": primary,
            "extract": _clean(page.get("extract", ""))[:500],
        }
    return out


def _run_wikipedia(lang, kq, original, limit, budget, errors, counts):
    """Search one language; fall back to the original wording only if the
    keyword query found nothing. Returns ranked list of page dicts."""
    key = "wikipedia_" + lang
    try:
        hits = _wikipedia_search(lang, kq, limit, budget)
        used = kq
        if not hits and original.strip() and original.strip() != kq:
            hits = _wikipedia_search(lang, original.strip(), limit, budget)
            used = original.strip()
        pages = _wikipedia_pages(lang, [h.get("pageid") for h in hits if h.get("pageid")], budget)
        ranked = []
        for rank, h in enumerate(hits):
            p = pages.get(h.get("pageid"), {})
            ranked.append({
                "lang": lang, "rank": rank, "query_used": used,
                "title": h.get("title"), "pageid": h.get("pageid"),
                "snippet": _clean(h.get("snippet", "")),
                "extract": p.get("extract", ""),
                "qid": p.get("qid"), "coordinate": p.get("coordinate"),
                "url": _wiki_url(lang, h.get("title") or ""),
            })
        counts[key] = len(ranked)
        errors[key] = None
        return ranked
    except HistoricalSearchError as exc:
        counts[key] = 0
        errors[key] = str(exc)
        return []


# ---------------------------------------------------------------- Wikidata

def _claim_values(claims, prop):
    vals = []
    for st in claims.get(prop, []) or []:
        if st.get("rank") == "deprecated":
            continue
        snak = st.get("mainsnak") or {}
        if snak.get("snaktype") != "value":
            continue
        vals.append((snak.get("datavalue", {}).get("value"), len(st.get("references") or []), st.get("rank")))
    return vals


def _wikidata_entities(qids, budget, what, props="labels|descriptions|claims|sitelinks"):
    out = {}
    qids = [q for q in qids if q]
    for i in range(0, len(qids), 50):
        data = _http_get(_WIKIDATA_API, {
            "action": "wbgetentities", "format": "json", "ids": "|".join(qids[i:i + 50]),
            "props": props, "languages": "en|fa", "sitefilter": "enwiki|fawiki",
        }, budget, what)
        out.update(data.get("entities") or {})
    return out


def _label(entity, lang):
    return ((entity.get("labels") or {}).get(lang) or {}).get("value")


def _wikidata_time(v):
    """Wikidata time value -> short human string, honest about precision.
    precision 9 = year, 10 = month, 11 = day; coarser -> 'century'."""
    if not isinstance(v, dict) or "time" not in v:
        return None
    t = v["time"]
    m = re.match(r"([+-])0*(\d+)-(\d\d)-(\d\d)", t)
    if not m:
        return t
    sign, year, mon, day = m.groups()
    y = int(year)
    era = "BC" if sign == "-" else "AD"
    prec = v.get("precision", 9)
    if prec >= 11:
        return "%d-%s-%s %s" % (y, mon, day, era)
    if prec == 10:
        return "%d-%s %s" % (y, mon, era)
    if prec == 9:
        return "%d %s" % (y, era)
    return "c. %d %s (precision %s)" % (y, era, prec)


# ---------------------------------------------------------------- Pleiades

def _pleiades_search(q, budget, limit):
    body = _http_get(_PLEIADES_SEARCH, {"SearchableText": q, "portal_type": "Place"},
                     budget, "pleiades search", accept_json=False)
    items = re.findall(
        r'<item rdf:about="https://pleiades\.stoa\.org/places/(\d+)">\s*<title>([^<]*)</title>',
        body)
    return [(pid, _clean(title)) for pid, title in items[:limit]]


def _pleiades_place(pid, budget):
    d = _http_get(_PLEIADES_PLACE_JSON % pid, None, budget, "pleiades place %s" % pid)
    types = d.get("placeTypes") or []
    locations = d.get("locations") or []
    unlocated = ("unlocated" in types) or not locations
    precisions = sorted({(f.get("properties") or {}).get("location_precision")
                         for f in (d.get("features") or [])} - {None})
    rp = d.get("reprPoint")
    coord = None
    rough_point = None
    if not unlocated and isinstance(rp, list) and len(rp) == 2:
        point = (float(rp[1]), float(rp[0]))  # Pleiades reprPoint is [lon, lat]
        # ROUGH-ONLY RULE (found on-device 2026-10-01: Pleiades 926388
        # "Untitled" dam sat at exactly 30.5, 53.5 with precision
        # "rough"): a point Pleiades itself calls rough is NOT used as a
        # location -- kept as rough_point for the record, finding goes to
        # unlocated_findings. Only a "precise" location counts as tier A.
        if "precise" in precisions:
            coord = point
        else:
            rough_point = point
    return {
        "pleiades_id": str(pid),
        "title": d.get("title"),
        "description": _clean(d.get("description") or "")[:400],
        "place_types": types,
        "unlocated": unlocated,
        "location_precision": precisions,
        "coordinate": coord,
        "rough_point": rough_point,
        "url": d.get("uri") or ("https://pleiades.stoa.org/places/%s" % pid),
        "review_state": d.get("review_state"),
    }


# ---------------------------------------------------------------- OpenAlex

def _openalex(q, budget, limit, api_key=None):
    # Keyless OpenAlex use is a small free DAILY budget shared per network
    # IP (live 2026-10-01: about 100 searches/day; resets midnight UTC).
    # A free personal key has its own budget; it is passed in by the app
    # from a settings field -- never typed into chat, never logged here.
    params = {
        "search": q, "per-page": str(limit),
        "select": "id,doi,title,publication_year,type,primary_location",
    }
    if api_key:
        params["api_key"] = api_key
    data = _http_get(_OPENALEX_WORKS, params, budget, "openalex search")
    works = []
    for w in data.get("results") or []:
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        works.append({
            "tier": "A",
            "tier_note": "scholarly work exists (title match only; content not read; no coordinate)",
            "title": w.get("title"),
            "year": w.get("publication_year"),
            "type": w.get("type"),
            "doi": w.get("doi"),
            "venue": src.get("display_name"),
            "url": w.get("doi") or loc.get("landing_page_url") or w.get("id"),
            "openalex_id": w.get("id"),
        })
    return works


# ---------------------------------------------------------------- assembly

def _coord_record(lat, lon, source, tier, url, referenced=None, note=None):
    return {
        "lat": round(lat, 6), "lon": round(lon, 6), "source": source, "tier": tier,
        "url": url, "referenced": referenced, "note": note,
    }


def search_historical(query, max_results=6, max_pleiades=5, max_literature=5,
                      budget_seconds=_TOTAL_BUDGET_SECONDS, openalex_api_key=None):
    """Run ONE historical search. Never raises for a source failure (each
    is reported in source_errors); raises ValueError only for an empty
    query (a caller bug).

    Returns:
        {
          "engine_version", "query", "keyword_query", "query_script",
          "retrieval_date",
          "tier_definitions": {...},
          "located_findings":   [finding, ...],   # >=1 coordinate
          "unlocated_findings": [finding, ...],   # subject found, no coordinate
          "literature":         [work, ...],      # OpenAlex, discovery only
          "source_counts": {name: int}, "source_errors": {name: str|None},
        }
    finding = {
        "key", "title", "title_en", "title_fa", "description",
        "wikidata_id", "instance_of": [{"id","label"}], "is_event",
        "date": str|None, "countries": [{"id","label"}],
        "in_iran": True|False|None,
        "coordinates": [{"lat","lon","source","tier","url","referenced","note"}],
        "best_tier": "A"|"B"|None,
        "coordinate_spread_km": float|None,  # max distance between this finding's coordinates
        "caveat": str,
        "pleiades": {...}|None,
        "links": {"wikipedia_en","wikipedia_fa","wikidata","pleiades"},
        "evidence": [{"source","lang","rank","title","url","text","query_used"}],
        "search_rank": int,
    }
    """
    if not query or not query.strip():
        raise ValueError("Empty query passed to historical search.")
    budget = _Budget(budget_seconds)
    original = query.strip()
    kq = keyword_query(original)
    script = detect_script(original)
    retrieval_date = _now_iso()
    errors, counts = {}, {}

    # 1. Wikipedia, both languages. Query language first, the other second.
    langs = ["fa", "en"] if script == "persian" else ["en", "fa"]
    hits = {lang: _run_wikipedia(lang, kq, original, max_results, budget, errors, counts) for lang in langs}

    # Interleave by rank -> one merged order.
    merged_hits = []
    for r in range(max(len(v) for v in hits.values()) if hits else 0):
        for lang in langs:
            if r < len(hits[lang]):
                merged_hits.append(hits[lang][r])

    # 2. Wikidata for every hit that has an item id.
    entities = {}
    qids = []
    for h in merged_hits:
        if h["qid"] and h["qid"] not in qids:
            qids.append(h["qid"])
    try:
        entities = _wikidata_entities(qids, budget, "wikidata entities")
        counts["wikidata"] = len(entities)
        errors["wikidata"] = None
    except HistoricalSearchError as exc:
        counts["wikidata"] = 0
        errors["wikidata"] = str(exc)

    # Labels for instance-of / country ids (one batch).
    aux_ids = []
    for e in entities.values():
        claims = e.get("claims") or {}
        for prop in ("P31", "P17"):
            for v, _r, _k in _claim_values(claims, prop):
                if isinstance(v, dict) and v.get("id") and v["id"] not in aux_ids:
                    aux_ids.append(v["id"])
    aux = {}
    if aux_ids:
        try:
            aux = _wikidata_entities(aux_ids[:100], budget, "wikidata labels", props="labels")
        except HistoricalSearchError as exc:
            errors["wikidata"] = (errors.get("wikidata") or "") + " | labels: " + str(exc)

    def aux_label(qid):
        e = aux.get(qid) or {}
        return _label(e, "en") or _label(e, "fa") or qid

    # 3. Build findings keyed by Wikidata id (or by page when no item).
    findings = {}
    order = []
    for h in merged_hits:
        key = ("wd:" + h["qid"]) if h["qid"] else ("wp:%s:%s" % (h["lang"], h["pageid"]))
        f = findings.get(key)
        if f is None:
            f = {
                "key": key, "title": h["title"], "title_en": None, "title_fa": None,
                "description": None, "wikidata_id": h["qid"], "instance_of": [],
                "is_event": False, "date": None, "countries": [], "in_iran": None,
                "coordinates": [], "best_tier": None, "coordinate_spread_km": None,
                "caveat": "", "pleiades": None,
                "links": {"wikipedia_en": None, "wikipedia_fa": None,
                          "wikidata": ("https://www.wikidata.org/wiki/" + h["qid"]) if h["qid"] else None,
                          "pleiades": None},
                "evidence": [], "search_rank": len(order),
            }
            findings[key] = f
            order.append(key)
        f["links"]["wikipedia_" + h["lang"]] = h["url"]
        if h["lang"] == "en":
            f["title_en"] = h["title"]
        else:
            f["title_fa"] = h["title"]
        f["evidence"].append({
            "source": "wikipedia_" + h["lang"], "lang": h["lang"], "rank": h["rank"],
            "title": h["title"], "url": h["url"],
            "text": h["extract"] or h["snippet"], "query_used": h["query_used"],
        })
        if h["coordinate"] and not any(c["source"] == "wikipedia_" + h["lang"] for c in f["coordinates"]):
            f["coordinates"].append(_coord_record(
                h["coordinate"][0], h["coordinate"][1], "wikipedia_" + h["lang"], "B", h["url"],
                note="article's own primary coordinate"))

    pleiades_wanted = []  # (pleiades_id, finding_key)
    for key in order:
        f = findings[key]
        e = entities.get(f["wikidata_id"] or "")
        if not e:
            continue
        claims = e.get("claims") or {}
        f["title_en"] = f["title_en"] or _label(e, "en")
        f["title_fa"] = f["title_fa"] or _label(e, "fa")
        f["title"] = f["title_en"] or f["title_fa"] or f["title"]
        f["description"] = (((e.get("descriptions") or {}).get("en") or {}).get("value")
                            or ((e.get("descriptions") or {}).get("fa") or {}).get("value"))
        sl = e.get("sitelinks") or {}
        if sl.get("enwiki") and not f["links"]["wikipedia_en"]:
            f["links"]["wikipedia_en"] = _wiki_url("en", sl["enwiki"]["title"])
            f["title_en"] = f["title_en"] or sl["enwiki"]["title"]
        if sl.get("fawiki") and not f["links"]["wikipedia_fa"]:
            f["links"]["wikipedia_fa"] = _wiki_url("fa", sl["fawiki"]["title"])
            f["title_fa"] = f["title_fa"] or sl["fawiki"]["title"]
        for v, _r, _k in _claim_values(claims, "P31"):
            if isinstance(v, dict) and v.get("id"):
                f["instance_of"].append({"id": v["id"], "label": aux_label(v["id"])})
                if v["id"] in _EVENT_CLASS_QIDS:
                    f["is_event"] = True
        country_ids = []
        for v, _r, _k in _claim_values(claims, "P17"):
            if isinstance(v, dict) and v.get("id"):
                country_ids.append(v["id"])
                f["countries"].append({"id": v["id"], "label": aux_label(v["id"])})
        if country_ids:
            f["in_iran"] = _IRAN_QID in country_ids
        for prop in ("P585", "P580", "P571"):
            vals = _claim_values(claims, prop)
            if vals:
                f["date"] = _wikidata_time(vals[0][0])
                break
        for v, nrefs, _k in _claim_values(claims, "P625"):
            if isinstance(v, dict) and "latitude" in v and "longitude" in v:
                globe = v.get("globe") or ""
                if globe and not globe.endswith("/Q2"):
                    continue  # not Earth
                f["coordinates"].append(_coord_record(
                    float(v["latitude"]), float(v["longitude"]), "wikidata_P625", "B",
                    f["links"]["wikidata"], referenced=nrefs > 0,
                    note="Wikidata statement %s a cited reference" % ("has" if nrefs else "has no")))
        for v, _r, _k in _claim_values(claims, "P1584"):
            if isinstance(v, str) and v.isdigit():
                pleiades_wanted.append((v, key))

    # 4. Pleiades: ids linked from Wikidata first, then free-text search.
    pleiades_records = {}
    pl_count = 0
    pl_errors = []
    search_pids = []
    try:
        search_pids = _pleiades_search(kq, budget, max_pleiades)
    except HistoricalSearchError as exc:
        pl_errors.append(str(exc))
    linked_pids = [p for p, _k in pleiades_wanted]
    for pid in linked_pids + [p for p, _t in search_pids if p not in linked_pids]:
        if pid in pleiades_records:
            continue
        try:
            pleiades_records[pid] = _pleiades_place(pid, budget)
            pl_count += 1
        except HistoricalSearchError as exc:
            pl_errors.append(str(exc))
    counts["pleiades"] = pl_count
    errors["pleiades"] = " | ".join(pl_errors) if pl_errors else None

    def attach_pleiades(f, rec):
        f["pleiades"] = rec
        f["links"]["pleiades"] = rec["url"]
        if rec["coordinate"]:
            f["coordinates"].append(_coord_record(
                rec["coordinate"][0], rec["coordinate"][1], "pleiades", "A", rec["url"],
                note="Pleiades representative point; location precision: %s"
                     % (", ".join(rec["location_precision"]) or "not stated")))

    used_pids = set()
    for pid, key in pleiades_wanted:
        if pid in pleiades_records and pid not in used_pids:
            attach_pleiades(findings[key], pleiades_records[pid])
            used_pids.add(pid)
    for pid, title in search_pids:
        if pid in used_pids or pid not in pleiades_records:
            continue
        rec = pleiades_records[pid]
        key = "pl:" + pid
        f = {
            "key": key, "title": rec["title"] or title, "title_en": rec["title"] or title,
            "title_fa": None, "description": rec["description"], "wikidata_id": None,
            "instance_of": [{"id": None, "label": t} for t in rec["place_types"]],
            "is_event": False, "date": None, "countries": [], "in_iran": None,
            "coordinates": [], "best_tier": None, "coordinate_spread_km": None,
            "caveat": "", "pleiades": None,
            "links": {"wikipedia_en": None, "wikipedia_fa": None, "wikidata": None, "pleiades": None},
            "evidence": [{"source": "pleiades", "lang": "en", "rank": len(used_pids),
                          "title": rec["title"], "url": rec["url"],
                          "text": rec["description"], "query_used": kq}],
            "search_rank": len(order),
        }
        attach_pleiades(f, rec)
        findings[key] = f
        order.append(key)
        used_pids.add(pid)

    # 5. OpenAlex literature (discovery only).
    literature = []
    try:
        literature = _openalex(kq, budget, max_literature, api_key=openalex_api_key)
        counts["openalex"] = len(literature)
        errors["openalex"] = None
    except HistoricalSearchError as exc:
        counts["openalex"] = 0
        errors["openalex"] = str(exc)

    # 6. Finalise: best tier, spread between coordinates, caveat text.
    located, unlocated = [], []
    for key in order:
        f = findings[key]
        cs = f["coordinates"]
        if cs:
            f["best_tier"] = "A" if any(c["tier"] == "A" for c in cs) else "B"
            spread = 0.0
            for i in range(len(cs)):
                for j in range(i + 1, len(cs)):
                    spread = max(spread, _haversine_km(cs[i]["lat"], cs[i]["lon"], cs[j]["lat"], cs[j]["lon"]))
            f["coordinate_spread_km"] = round(spread, 3)
        parts = ["Coordinate = recorded position of this subject in the cited source, "
                 "not a verified archaeological position."]
        if f["is_event"]:
            parts.append("This is an event; its exact site may be debated in scholarship.")
        if f["coordinate_spread_km"] and f["coordinate_spread_km"] > 1.0:
            parts.append("Sources disagree by %.1f km." % f["coordinate_spread_km"])
        if f["in_iran"] is False:
            parts.append("Outside Iran per Wikidata (project scope is Iran) -- kept, flagged.")
        elif f["in_iran"] is None:
            parts.append("Country not recorded.")
        if f["pleiades"] and f["pleiades"]["unlocated"]:
            parts.append("Pleiades marks this place UNLOCATED.")
        elif f["pleiades"] and f["pleiades"].get("rough_point"):
            parts.append("Pleiades gives only a ROUGH position (%.4f, %.4f); not used as a location."
                         % f["pleiades"]["rough_point"])
        f["caveat"] = " ".join(parts)
        (located if cs else unlocated).append(f)

    return {
        "engine_version": ENGINE_VERSION,
        "query": original,
        "keyword_query": kq,
        "query_script": script,
        "retrieval_date": retrieval_date,
        "tier_definitions": {
            "A": "specialist scholarly gazetteer record marked located, precise (Pleiades); "
                 "OpenAlex works = literature exists only",
            "B": "community-edited encyclopedic coordinate (Wikidata P625 / Wikipedia article)",
            "C": "inferred from free text or general web search (not produced by this engine)",
        },
        "ordering": "source search rank, not likelihood",
        "located_findings": located,
        "unlocated_findings": unlocated,
        "literature": literature,
        "source_counts": counts,
        "source_errors": errors,
    }


def search_historical_safe(query, **kwargs):
    """Never raises; returns (result_or_None, error_or_None)."""
    try:
        return search_historical(query, **kwargs), None
    except Exception as exc:  # includes ValueError for an empty query
        return None, "%s: %s" % (type(exc).__name__, exc)
