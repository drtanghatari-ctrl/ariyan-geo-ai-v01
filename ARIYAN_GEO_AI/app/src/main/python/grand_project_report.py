"""
grand_project_report.py  --  Phase 6 (Report + Dashboard), report version "rp-v1"

Part of ARIYAN GEO AI's Grand Project framework. Added 2026-10-04.

WHAT THIS MODULE DOES (design approved by the user 2026-10-02):
  1. dashboard(): one READ-ONLY summary row per Wide-Area Search job in the
     project -- trust, target, tiles, candidates by status, calib-v1 strong
     count, DEM source (offline file / live / not recorded, from the
     provenance ledger), ledger coverage (a quick count, NOT a
     verification), plus the project's own-review outcome counter.
  2. export_job_report(): writes ONE job's report as an HTML file (English
     and Persian) plus a CSV of its candidates, into
     <phone storage>/ARIYAN_GEO_AI/reports/. It runs the full Phase 4b
     provenance check on the job first (re-hashes the offline files).

WHAT IT NEVER DOES:
  - never changes any candidate, status, review, trust, target, confidence,
    evidence or ledger row. The ONLY write is one append-only timeline
    event REPORT_EXPORTED (with the MD5 of both files) after an export.
  - never says "discovered" or "site found". Candidates are candidates.
  - never exports a job marked CORRUPTED (refused with an error).
  - the caveat block in the HTML cannot be switched off.

COORDINATES: exported files round every coordinate to 0.01 degree (about
1 km) unless the user explicitly chooses exact coordinates for that one
export. In rounded mode the known-site distances are also rounded to whole
kilometres, because "415 m from <a public gazetteer point>" would give the
exact position back. The screen itself always stays exact.

ORDER OF THE CANDIDATE TABLE: candidates that are not Rejected first, then
Steward confidence (high to low), then |DEM z-score| (high to low). "Top N"
means the first N rows in that order. The rule is printed in the report.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import grand_project_db as db
import grand_project_review as review

REPORT_VERSION = "rp-v1"
ROUND_DECIMALS = 2          # 0.01 degree, about 1.1 km north-south
DEFAULT_TOP_N = 50
REPORTS_DIR_NAME = "reports"
EVENT_TYPE = "REPORT_EXPORTED"

_STATUS_EN = dict(review.STATUS_LABELS)
_STATUS_FA = {
    review.STATUS_OPEN: "باز",
    review.STATUS_SUPPORTED: "پشتیبانی‌شده",
    review.STATUS_REJECTED: "ردشده",
    review.STATUS_INCONCLUSIVE: "بی‌نتیجه",
}
_TRUST_EN = {"TRUSTED": "Trusted", "CORRUPTED": "Corrupted", "UNVERIFIED": "Unverified", None: "not marked"}
_TRUST_FA = {"TRUSTED": "مورد اعتماد", "CORRUPTED": "خراب", "UNVERIFIED": "تأییدنشده", None: "علامت‌گذاری‌نشده"}
_TARGET_FA = {
    review.TARGET_MOUND_TELL: "تپه / تل",
    review.TARGET_OTHER: "دیگر (قلعه، آرامگاه صخره‌ای، نقش برجسته ...)",
    review.TARGET_NOT_SET: "تعیین‌نشده",
}
_STATUS_ORDER = (review.STATUS_OPEN, review.STATUS_SUPPORTED,
                 review.STATUS_INCONCLUSIVE, review.STATUS_REJECTED)


class ReportError(ValueError):
    """Refused or impossible export (unknown job, CORRUPTED job, bad N)."""


# ---------------------------------------------------------------------------
# Shared reads
# ---------------------------------------------------------------------------

def _has_table(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


def _candidates_with_job(conn, grand_project_id: str) -> List[Dict[str, Any]]:
    """Every candidate of the project with its job id (null when it did not
    come from a Wide-Area Search tile)."""
    rows = conn.execute(
        """
        SELECT c.id, c.investigation_id, c.lat, c.lon, c.status, c.score,
               c.confidence_band, c.confidence_numeric, c.created_at, t.job_id
        FROM candidate c
        LEFT JOIN wide_area_search_tile t ON t.investigation_id = c.investigation_id
        WHERE c.grand_project_id = ?
        """,
        (grand_project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _evidence_ledger_scan(conn, candidate_ids: Optional[set] = None) -> Dict[str, Dict[str, int]]:
    """candidate_id -> {"rows", "with_record", "dem_file", "dem_live",
    "dem_not_recorded"}. One scan of evidence_link joined to the ledger
    (provenance_record.evidence_link_id is UNIQUE, so the join is indexed).
    Quick count only: nothing is re-hashed here."""
    has_ledger = _has_table(conn, "provenance_record")
    if has_ledger:
        sql = ("SELECT e.candidate_id, e.evidence_type, p.id AS rec_id, p.sources_json "
               "FROM evidence_link e LEFT JOIN provenance_record p ON p.evidence_link_id = e.id")
    else:
        sql = ("SELECT e.candidate_id, e.evidence_type, NULL AS rec_id, NULL AS sources_json "
               "FROM evidence_link e")
    out: Dict[str, Dict[str, int]] = {}
    for r in conn.execute(sql):
        cid = r["candidate_id"]
        if candidate_ids is not None and cid not in candidate_ids:
            continue
        s = out.setdefault(cid, {"rows": 0, "with_record": 0, "dem_file": 0,
                                 "dem_live": 0, "dem_not_recorded": 0})
        s["rows"] += 1
        if r["rec_id"] is not None:
            s["with_record"] += 1
        if r["evidence_type"] == "DEM":
            kinds = set()
            if r["sources_json"]:
                try:
                    for src in json.loads(r["sources_json"]) or []:
                        if isinstance(src, dict) and src.get("kind") == "DEM":
                            kinds.add(src.get("type"))
                except ValueError:
                    pass
            if "FILE" in kinds:
                s["dem_file"] += 1
            elif "LIVE" in kinds:
                s["dem_live"] += 1
            else:
                s["dem_not_recorded"] += 1
    return out


def _active_profile(db_root: str):
    try:
        import calib_profile
        return calib_profile, calib_profile.active_profile(db_root)
    except Exception:
        return None, None


def _is_strong(calib_mod, profile, score) -> bool:
    if calib_mod is None or profile is None:
        return False
    try:
        return bool(calib_mod.is_strong(score, profile))
    except Exception:
        return False


def _fmt_time(iso: Optional[str]) -> str:
    return (iso or "")[:16].replace("T", " ")


# ---------------------------------------------------------------------------
# 1. Dashboard
# ---------------------------------------------------------------------------

def dashboard(db_root: str, grand_project_id: str) -> Dict[str, Any]:
    calib_mod, profile = _active_profile(db_root)
    conn = review._connect(db_root)
    try:
        jobs = [dict(r) for r in conn.execute(
            "SELECT * FROM wide_area_search_job WHERE grand_project_id = ? ORDER BY created_at DESC",
            (grand_project_id,)).fetchall()]
        tiles: Dict[str, Dict[str, int]] = {}
        for r in conn.execute(
                "SELECT t.job_id, t.status, COUNT(*) AS n FROM wide_area_search_tile t "
                "JOIN wide_area_search_job j ON j.id = t.job_id WHERE j.grand_project_id = ? "
                "GROUP BY t.job_id, t.status", (grand_project_id,)):
            d = tiles.setdefault(r["job_id"], {"DONE": 0, "FAILED": 0, "PENDING": 0, "OTHER": 0})
            key = r["status"] if r["status"] in d else "OTHER"
            d[key] += r["n"]
        trust = review._current_job_trust(conn)
        targets = review._current_job_target(conn)
        cands = _candidates_with_job(conn, grand_project_id)
        ledger = _evidence_ledger_scan(conn, {c["id"] for c in cands})
        user_owned = review._user_owned_ids(conn)
    finally:
        conn.close()

    per_job: Dict[Optional[str], Dict[str, Any]] = {}
    for c in cands:
        j = per_job.setdefault(c["job_id"], {
            "candidates": 0, "by_status": {s: 0 for s in _STATUS_ORDER}, "other_status": 0,
            "calib_strong": 0, "evidence_rows": 0, "ledger_rows": 0,
            "dem_file": 0, "dem_live": 0, "dem_not_recorded": 0})
        j["candidates"] += 1
        if c["status"] in j["by_status"]:
            j["by_status"][c["status"]] += 1
        else:
            j["other_status"] += 1
        if _is_strong(calib_mod, profile, c["score"]):
            j["calib_strong"] += 1
        s = ledger.get(c["id"])
        if s:
            j["evidence_rows"] += s["rows"]
            j["ledger_rows"] += s["with_record"]
            j["dem_file"] += s["dem_file"]
            j["dem_live"] += s["dem_live"]
            j["dem_not_recorded"] += s["dem_not_recorded"]

    outcome = {"SUPPORTED": 0, "REJECTED": 0}
    for c in cands:
        if c["id"] in user_owned and c["status"] in outcome:
            outcome[c["status"]] += 1

    rows = []
    for job in jobs:
        jid = job["id"]
        t = trust.get(jid)
        rows.append({
            "job_id": jid, "title": job.get("title"), "created_at": job.get("created_at"),
            "status": job.get("status"), "tile_size_m": job.get("tile_size_m"),
            "n_tiles": job.get("n_tiles"), "tiles": tiles.get(jid, {}),
            "trust": t["trust"] if t else None,
            "target": targets[jid]["target"] if jid in targets else review.TARGET_NOT_SET,
            **per_job.get(jid, {"candidates": 0, "by_status": {s: 0 for s in _STATUS_ORDER},
                                "other_status": 0, "calib_strong": 0, "evidence_rows": 0,
                                "ledger_rows": 0, "dem_file": 0, "dem_live": 0,
                                "dem_not_recorded": 0}),
        })
    # Corrupted jobs last, otherwise newest first (already sorted).
    rows.sort(key=lambda r: 1 if r["trust"] == "CORRUPTED" else 0)

    result = {
        "report_version": REPORT_VERSION,
        "grand_project_id": grand_project_id,
        "jobs": rows,
        "no_job": per_job.get(None),
        "candidates_total": len(cands),
        "calib_active": profile is not None,
        "outcome_user": outcome,
    }
    result["report_text"] = _dashboard_text(result)
    return result


def _dashboard_text(r: Dict[str, Any]) -> str:
    L = ["Project dashboard (%s, read-only; changes nothing)" % REPORT_VERSION,
         "Jobs: %d   Candidates: %d" % (len(r["jobs"]), r["candidates_total"]),
         "calib-v1: %s" % ("active (label only)" if r["calib_active"] else "not active"),
         "Your own reviews: Supported %d / Rejected %d (calib-v2 needs 20 of each)"
         % (r["outcome_user"]["SUPPORTED"], r["outcome_user"]["REJECTED"]),
         "Confidence ceiling: MODERATE 0.55 for every candidate (confounders not controlled).",
         ""]
    for j in r["jobs"]:
        b = j["by_status"]
        tl = j["tiles"]
        L.append("%s  %s" % (j["job_id"][:6], j.get("title") or ""))
        if j["trust"] == "CORRUPTED":
            L.append("  *** CORRUPTED -- ignore its candidates; no report can be exported ***")
        L.append("  created %s   %s" % (_fmt_time(j["created_at"]), j.get("status") or ""))
        L.append("  tiles %s: done %d / failed %d / pending %d  (%s m)"
                 % (j.get("n_tiles"), tl.get("DONE", 0), tl.get("FAILED", 0),
                    tl.get("PENDING", 0), _num(j.get("tile_size_m"))))
        L.append("  trust: %s   target: %s"
                 % (_TRUST_EN.get(j["trust"], j["trust"]),
                    review.TARGET_LABELS.get(j["target"], j["target"]).split(" (")[0]))
        L.append("  candidates %d: Open %d / Supported %d / Inconclusive %d / Rejected %d"
                 % (j["candidates"], b[review.STATUS_OPEN], b[review.STATUS_SUPPORTED],
                    b[review.STATUS_INCONCLUSIVE], b[review.STATUS_REJECTED])
                 + (" / other %d" % j["other_status"] if j["other_status"] else ""))
        if r["calib_active"]:
            L.append("  calib-v1 strong: %d" % j["calib_strong"])
        L.append("  DEM rows: offline file %d / live %d / not recorded %d"
                 % (j["dem_file"], j["dem_live"], j["dem_not_recorded"]))
        L.append("  ledger records: %d of %d evidence rows" % (j["ledger_rows"], j["evidence_rows"]))
        L.append("")
    nj = r.get("no_job")
    if nj:
        L.append("Not from a Wide-Area Search job (single-point runs): %d candidates" % nj["candidates"])
        L.append("")
    L.append("\"ledger records\" is a quick count, not a verification. "
             "Provenance check or Export report runs the full check.")
    return "\n".join(L)


def _num(x) -> str:
    if isinstance(x, (int, float)):
        return ("%d" % x) if float(x).is_integer() else ("%g" % x)
    return "?"


# ---------------------------------------------------------------------------
# 2. Per-job report export
# ---------------------------------------------------------------------------

def _resolve_job(conn, job_ref: str) -> str:
    try:
        return review._resolve_id(conn, "wide_area_search_job", job_ref)
    except review.ReviewError as e:
        raise ReportError(str(e))


def _terrain_latest(conn, candidate_ids: set) -> Dict[str, Dict[str, Any]]:
    """candidate_id -> newest TERRAIN_CONTEXT detail (any method version)."""
    out: Dict[str, Dict[str, Any]] = {}
    if not candidate_ids:
        return out
    for r in conn.execute("SELECT candidate_id, detail_json FROM evidence_link "
                          "WHERE evidence_type = 'TERRAIN_CONTEXT' ORDER BY id"):
        if r["candidate_id"] not in candidate_ids:
            continue
        try:
            out[r["candidate_id"]] = json.loads(r["detail_json"] or "{}")
        except ValueError:
            continue
    return out


def _round_coord(x: Optional[float], exact: bool) -> Optional[float]:
    if x is None:
        return None
    return float(x) if exact else round(float(x), ROUND_DECIMALS)


def _known_site(lat, lon, exact: bool) -> Dict[str, str]:
    """{"label", "text_en", "text_fa"}. Rounded mode hides metre distances."""
    try:
        import known_sites
        a = known_sites.annotate(lat, lon)
    except Exception as e:
        return {"label": "", "text_en": "known-site lookup failed (%s)" % type(e).__name__,
                "text_fa": "جست‌وجوی محوطهٔ ثبت‌شده ناموفق بود"}
    label = a.get("label") or ""
    name = a.get("nearest_name")
    d = a.get("nearest_distance_m")
    if exact:
        return {"label": label, "text_en": a.get("text") or "", "text_fa": _known_site_fa(a, exact)}
    if label == "NEAR_KNOWN_SITE":
        en = "within 1 km of recorded site: %s (likely rediscovery)" % name
    elif label == "GAZETTEER_SPARSE":
        en = a.get("text") or "gazetteer too sparse here to judge"
    elif name is not None and d is not None:
        en = "not in gazetteer: nearest recorded site about %d km (%s)" % (int(round(d / 1000.0)), name)
    else:
        en = "not in gazetteer: no recorded site within 50 km"
    return {"label": label, "text_en": en, "text_fa": _known_site_fa(a, exact)}


def _known_site_fa(a: Dict[str, Any], exact: bool) -> str:
    label = a.get("label")
    name = a.get("nearest_name") or ""
    d = a.get("nearest_distance_m")
    if label == "NEAR_KNOWN_SITE":
        if exact and d is not None:
            return "%.0f متر از محوطهٔ ثبت‌شده: %s (احتمالاً بازیابی یک محوطهٔ شناخته‌شده)" % (d, name)
        return "کمتر از ۱ کیلومتر از محوطهٔ ثبت‌شده: %s (احتمالاً بازیابی یک محوطهٔ شناخته‌شده)" % name
    if label == "GAZETTEER_SPARSE":
        return "فهرست محوطه‌ها در این منطقه برای داوری بسیار کم‌تراکم است"
    if d is not None:
        km = ("%.1f" % (d / 1000.0)) if exact else ("%d" % int(round(d / 1000.0)))
        return "در فهرست نیست؛ نزدیک‌ترین محوطهٔ ثبت‌شده حدود %s کیلومتر (%s)" % (km, name)
    return "در فهرست نیست؛ هیچ محوطهٔ ثبت‌شده‌ای تا ۵۰ کیلومتر نیست"


def _sort_key(row: Dict[str, Any]):
    rejected = 1 if row["status"] == review.STATUS_REJECTED else 0
    conf = row.get("confidence_numeric")
    conf_key = -float(conf) if isinstance(conf, (int, float)) else 1.0
    z = row.get("score")
    z_key = -abs(float(z)) if isinstance(z, (int, float)) else 1.0
    return (rejected, conf_key, z_key, row["id"])


def _md5_bytes(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def _reports_dir(db_root: str) -> str:
    parent = os.path.dirname(os.path.abspath(db_root.rstrip("/\\"))) or db_root
    return os.path.join(parent, REPORTS_DIR_NAME)


def _write_atomic(path: str, data: bytes) -> None:
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


def build_job_report(db_root: str, grand_project_id: str, job_ref: str,
                     top_n: int = DEFAULT_TOP_N, exact_coords: bool = False,
                     now: Optional[datetime] = None) -> Dict[str, Any]:
    """Builds the report in memory (no files, no timeline event). top_n <= 0
    means all candidates. Raises ReportError for a CORRUPTED job."""
    try:
        top_n = int(top_n)
    except (TypeError, ValueError):
        raise ReportError("Number of candidates must be a whole number (0 = all).")
    exact = bool(exact_coords)
    now = now or datetime.now(timezone.utc)

    calib_mod, profile = _active_profile(db_root)
    conn = review._connect(db_root)
    try:
        job_id = _resolve_job(conn, job_ref)
        job = dict(conn.execute("SELECT * FROM wide_area_search_job WHERE id = ?", (job_id,)).fetchone())
        if job.get("grand_project_id") != grand_project_id:
            raise ReportError("Job %s belongs to a different Grand Project." % job_id[:6])
        t = review._current_job_trust(conn).get(job_id)
        trust = t["trust"] if t else None
        trust_reason = t["reason"] if t else None
        if trust == review.TRUST_CORRUPTED:
            raise ReportError("Job %s is marked CORRUPTED (%s). Reports are refused for corrupted jobs."
                              % (job_id[:6], trust_reason or "no reason"))
        tg = review._current_job_target(conn).get(job_id)
        target = tg["target"] if tg else review.TARGET_NOT_SET
        tile_counts = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM wide_area_search_tile WHERE job_id = ? GROUP BY status",
            (job_id,))}
        all_cands = [c for c in _candidates_with_job(conn, grand_project_id) if c["job_id"] == job_id]
        ids = {c["id"] for c in all_cands}
        latest = review._latest_reviews(conn)
        terrain = _terrain_latest(conn, ids)
        ledger = _evidence_ledger_scan(conn, ids)
        bundles: Dict[str, int] = {}
        if _has_table(conn, "provenance_record") and ids:
            id_list = list(ids)
            for i in range(0, len(id_list), 500):
                chunk = id_list[i:i + 500]
                for r in conn.execute(
                        "SELECT code_bundle_md5, COUNT(*) AS n FROM provenance_record "
                        "WHERE candidate_id IN (%s) GROUP BY code_bundle_md5" % ",".join("?" * len(chunk)),
                        chunk):
                    key = r["code_bundle_md5"] or "none"
                    bundles[key] = bundles.get(key, 0) + r["n"]
    finally:
        conn.close()

    # Full Phase 4b check (re-hashes the offline files). A failure is reported,
    # never hidden, and makes the job count as not verified.
    try:
        import provenance_check
        prov = provenance_check.check_job(db_root, job_id)
        prov_error = None
    except Exception as e:
        prov, prov_error = None, "%s: %s" % (type(e).__name__, e)
    if prov is not None:
        prov_verified = prov["candidates"] > 0 and prov["candidates_verified"] == prov["candidates"]
    else:
        prov_verified = False

    # Each banner line is (English, Persian).
    banner: List[List[str]] = []
    if trust != review.TRUST_TRUSTED:
        banner.append(["job trust is %s (not Trusted)" % _TRUST_EN.get(trust, trust),
                       "اعتماد به کار «مورد اعتماد» نیست (%s)" % _TRUST_FA.get(trust, trust)])
    if not prov_verified:
        if prov_error:
            banner.append(["provenance check could not run (%s)" % prov_error,
                           "بررسی منشأ داده‌ها اجرا نشد"])
        elif prov is not None and prov["candidates"] == 0:
            banner.append(["job has no candidates to verify", "این کار نامزدی برای بررسی ندارد"])
        else:
            banner.append(["provenance NOT VERIFIED (%d of %d candidates verified)"
                           % (prov["candidates_verified"], prov["candidates"]),
                           "منشأ داده‌ها تأیید نشده است (%d از %d نامزد تأیید شده)"
                           % (prov["candidates_verified"], prov["candidates"])])

    rows = []
    status_counts = {s: 0 for s in _STATUS_ORDER}
    for c in all_cands:
        if c["status"] in status_counts:
            status_counts[c["status"]] += 1
        last = latest.get(c["id"])
        src = last["reviewed_by"] if last else None
        ter = terrain.get(c["id"], {})
        rows.append({
            "id": c["id"], "_lat": c["lat"], "_lon": c["lon"],
            "lat": _round_coord(c["lat"], exact), "lon": _round_coord(c["lon"], exact),
            "score": c["score"], "status": c["status"],
            "status_en": _STATUS_EN.get(c["status"], c["status"]),
            "status_fa": _STATUS_FA.get(c["status"], c["status"]),
            "review_source": ("auto" if src in (review.REVIEWED_BY_AUTO, review.REVIEWED_BY_HANDBACK)
                              else ("user" if src == review.REVIEWED_BY_USER else "")),
            "review_reason": (last or {}).get("reason") or "",
            "confidence_band": c["confidence_band"] or "",
            "confidence_numeric": c["confidence_numeric"],
            "calib_strong": _is_strong(calib_mod, profile, c["score"]),
            "terrain_shape": ter.get("shape") or "", "hillside": ter.get("hillside") or "",
            "terrain_method": ter.get("method_version") or "",
        })
    rows.sort(key=_sort_key)
    total = len(rows)
    shown = rows if top_n <= 0 else rows[:top_n]
    for i, r in enumerate(shown, 1):
        r["rank"] = i
        # Gazetteer context only for the rows that are exported (from the
        # exact position; the text itself is rounded in rounded mode).
        lat0, lon0 = r.pop("_lat"), r.pop("_lon")
        ks = (_known_site(lat0, lon0, exact) if lat0 is not None and lon0 is not None
              else {"label": "", "text_en": "no coordinates", "text_fa": "بدون مختصات"})
        r["known_site_label"], r["known_site_en"], r["known_site_fa"] = ks["label"], ks["text_en"], ks["text_fa"]

    led = {"rows": 0, "with_record": 0, "dem_file": 0, "dem_live": 0, "dem_not_recorded": 0}
    for s in ledger.values():
        for k in led:
            led[k] += s[k]

    box = {k: _round_coord(job.get(k), exact) for k in ("min_lat", "max_lat", "min_lon", "max_lon")}
    info = {
        "report_version": REPORT_VERSION,
        "generated_at": now.replace(microsecond=0).isoformat(),
        "job_id": job_id, "title": job.get("title") or "", "created_at": job.get("created_at"),
        "job_status": job.get("status"), "input_kind": job.get("input_kind"),
        "place_name": job.get("place_name"), "box": box,
        "tile_size_m": job.get("tile_size_m"), "n_tiles": job.get("n_tiles"),
        "tiles": tile_counts, "trust": trust, "trust_reason": trust_reason, "target": target,
        "exact_coords": exact, "top_n": top_n, "candidates_total": total, "rows_shown": len(shown),
        "status_counts": status_counts,
        "calib_active": profile is not None,
        "calib_strong": sum(1 for r in rows if r["calib_strong"]),
        "ledger": led, "code_bundles": bundles,
        "provenance_verified": prov_verified, "provenance_error": prov_error,
        "provenance_summary": ({"candidates": prov["candidates"],
                                "candidates_verified": prov["candidates_verified"],
                                "evidence_rows": prov["evidence_rows"],
                                "evidence_rows_verified": prov["evidence_rows_verified"],
                                "checker_version": prov["checker_version"],
                                "chain_problem": prov["chain_problem"],
                                "reasons": prov["reasons"]} if prov is not None else None),
        "banner": banner,
    }
    return {"info": info, "rows": shown,
            "html": _render_html(info, shown), "csv": _render_csv(info, shown)}


def export_job_report(db_root: str, grand_project_id: str, job_ref: str,
                      top_n: int = DEFAULT_TOP_N, exact_coords: bool = False) -> Dict[str, Any]:
    """Builds the report, writes the HTML and CSV files, then appends one
    REPORT_EXPORTED timeline event carrying both MD5s."""
    now = datetime.now(timezone.utc)
    built = build_job_report(db_root, grand_project_id, job_ref, top_n, exact_coords, now)
    info = built["info"]
    out_dir = _reports_dir(db_root)
    os.makedirs(out_dir, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    base = "ariyan_report_%s_%s%s" % (info["job_id"][:6], stamp, "_EXACT" if info["exact_coords"] else "")
    html_bytes = built["html"].encode("utf-8")
    csv_bytes = built["csv"].encode("utf-8-sig")  # BOM so spreadsheet apps read Persian names
    html_path = os.path.join(out_dir, base + ".html")
    csv_path = os.path.join(out_dir, base + ".csv")
    _write_atomic(html_path, html_bytes)
    _write_atomic(csv_path, csv_bytes)
    html_md5, csv_md5 = _md5_bytes(html_bytes), _md5_bytes(csv_bytes)

    desc = ("Report %s exported for job %s: %s rows of %d, %s coordinates, provenance %s. "
            "HTML %s md5 %s; CSV %s md5 %s"
            % (REPORT_VERSION, info["job_id"][:6],
               "all" if info["top_n"] <= 0 else "top %d" % info["top_n"], info["candidates_total"],
               "EXACT" if info["exact_coords"] else "rounded (0.01 deg)",
               "VERIFIED" if info["provenance_verified"] else "NOT VERIFIED",
               os.path.basename(html_path), html_md5, os.path.basename(csv_path), csv_md5))
    event_logged = True
    try:
        db.log_timeline_event(db_root, grand_project_id, EVENT_TYPE,
                              related_entity_type="wide_area_search_job",
                              related_entity_id=info["job_id"], description=desc)
    except Exception:
        event_logged = False

    return {"job_id": info["job_id"], "title": info["title"],
            "html_path": html_path, "csv_path": csv_path,
            "html_md5": html_md5, "csv_md5": csv_md5,
            "rows_shown": info["rows_shown"], "candidates_total": info["candidates_total"],
            "exact_coords": info["exact_coords"], "provenance_verified": info["provenance_verified"],
            "banner": [b[0] for b in info["banner"]], "timeline_event_logged": event_logged,
            "summary_text": _export_summary(info, html_path, csv_path, html_md5, csv_md5, event_logged)}


def _export_summary(info, html_path, csv_path, html_md5, csv_md5, event_logged) -> str:
    L = ["Job %s  %s" % (info["job_id"][:6], info["title"]),
         "Rows: %d of %d candidates (%s)" % (info["rows_shown"], info["candidates_total"],
                                            "all" if info["top_n"] <= 0 else "top %d" % info["top_n"]),
         "Coordinates: %s" % ("EXACT (your choice for this export)" if info["exact_coords"]
                              else "rounded to 0.01 deg (about 1 km)"),
         "Provenance: %s" % ("VERIFIED" if info["provenance_verified"] else "NOT VERIFIED"),
         ""]
    if info["banner"]:
        L.append("Banner in the report: " + "; ".join(b[0] for b in info["banner"]))
        L.append("")
    L += ["Files (open with a browser / a spreadsheet app):",
          "  " + html_path, "  md5 " + html_md5,
          "  " + csv_path, "  md5 " + csv_md5, "",
          ("Timeline: REPORT_EXPORTED event written." if event_logged
           else "Timeline event could NOT be written (files were still saved).")]
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _e(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _fmt_coord(x, exact: bool) -> str:
    if x is None:
        return ""
    return ("%.6f" % x) if exact else ("%.2f" % x)


def _fmt_z(z) -> str:
    return ("%+.2f" % z) if isinstance(z, (int, float)) else ""


def _fmt_conf(r) -> str:
    n = r.get("confidence_numeric")
    band = r.get("confidence_band") or ""
    return ("%s %.2f" % (band, n)).strip() if isinstance(n, (int, float)) else band


_CAVEATS_EN = [
    "Confidence ceiling: every candidate is capped at MODERATE (0.55). The ceiling stays there until "
    "environmental confounders are controlled. Provenance verification does not raise it, and the "
    "calib-v1 label does not raise it.",
    "Nothing in this report has been checked in the field. A candidate is a measured anomaly worth "
    "looking at, not a site. This report does not announce any discovery.",
    "The known-site gazetteer (Uppsala ANE Site Placemarks, CC-BY-4.0) is context, not evidence. Its "
    "coverage of Iran is thin; \"not in gazetteer\" does not mean \"unknown\".",
    "calib-v1 was benched on DEM-only, offline-first Copernicus GLO-30 runs in Khuzestan (Susiana) and "
    "Kangavar. Elsewhere the same label is applied by the same rule, untested. It is not a false-alarm rate.",
    "Statuses marked (auto) were set by ARIYAN's measured rules; your own reviews always override them.",
]
_CAVEATS_FA = [
    "سقف اطمینان: اطمینان همهٔ نامزدها حداکثر «متوسط» (۰٫۵۵) است. این سقف تا زمانی که عوامل مخدوش‌کنندهٔ "
    "محیطی کنترل نشده‌اند بالا نمی‌رود. تأیید منشأ داده‌ها (Provenance) و برچسب calib-v1 آن را بالا نمی‌برند.",
    "هیچ بخشی از این گزارش در میدان (روی زمین) بررسی نشده است. «نامزد» یک ناهنجاری اندازه‌گیری‌شده است که "
    "ارزش بررسی دارد، نه یک محوطه. این گزارش هیچ کشفی را اعلام نمی‌کند.",
    "فهرست محوطه‌های ثبت‌شده (ANE Site Placemarks دانشگاه اوپسالا، CC-BY-4.0) فقط زمینه است، نه شاهد. "
    "پوشش آن برای ایران کم است؛ «در فهرست نیست» به معنای «ناشناخته» نیست.",
    "calib-v1 فقط روی اجراهای DEM-only با COP30 (ابتدا آفلاین) در خوزستان (دشت شوش) و کنگاور سنجیده شده است. "
    "در جاهای دیگر همان قاعده اعمال می‌شود ولی آزموده نشده است. این برچسب نرخ هشدار کاذب نیست.",
    "وضعیت‌هایی که با (auto) مشخص شده‌اند را قواعد اندازه‌گیری‌شدهٔ ARIYAN تعیین کرده‌اند؛ بازبینی خود شما همیشه "
    "بر آن‌ها مقدم است.",
]


def _render_html(info: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
    exact = info["exact_coords"]
    box = info["box"]
    sc = info["status_counts"]
    tl = info["tiles"]
    ps = info["provenance_summary"]
    target_en = review.TARGET_LABELS.get(info["target"], info["target"])
    target_fa = _TARGET_FA.get(info["target"], info["target"])
    n_label_en = "all" if info["top_n"] <= 0 else "top %d" % info["top_n"]
    n_label_fa = "همه" if info["top_n"] <= 0 else "%d نامزد برتر" % info["top_n"]
    coord_en = ("EXACT coordinates (chosen explicitly by the user for this export)" if exact
                else "Coordinates rounded to 0.01 degree (about 1 km); known-site distances rounded to whole km")
    coord_fa = ("مختصات دقیق (به انتخاب صریح کاربر برای همین خروجی)" if exact
                else "مختصات به ۰٫۰۱ درجه (حدود ۱ کیلومتر) و فاصله تا محوطه‌های ثبت‌شده به کیلومتر کامل گرد شده‌اند")

    def box_txt():
        return "%s to %s N, %s to %s E" % (_fmt_coord(box["min_lat"], exact), _fmt_coord(box["max_lat"], exact),
                                           _fmt_coord(box["min_lon"], exact), _fmt_coord(box["max_lon"], exact))

    prov_en = ("VERIFIED" if info["provenance_verified"] else "NOT VERIFIED")
    prov_fa = ("تأییدشده" if info["provenance_verified"] else "تأییدنشده")
    led = info["ledger"]

    P = []
    P.append("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
             "<meta name='viewport' content='width=device-width, initial-scale=1'>")
    P.append("<title>ARIYAN GEO AI report %s</title>" % _e(info["job_id"][:6]))
    P.append("<style>body{font-family:sans-serif;margin:16px;color:#111;background:#fff;line-height:1.45}"
             "h1{font-size:1.3em}h2{font-size:1.1em;margin-top:1.4em;border-bottom:1px solid #999}"
             ".banner{border:2px solid #b00;background:#fee;padding:8px;margin:8px 0;font-weight:bold}"
             ".caveat{border:2px solid #333;background:#f4f4f4;padding:8px 12px;margin:12px 0}"
             ".fa{direction:rtl;text-align:right;font-family:Tahoma,'Vazirmatn',sans-serif}"
             "table{border-collapse:collapse;font-size:0.85em;min-width:1250px}td.ks{min-width:230px}"
             "th,td{border:1px solid #bbb;padding:3px 5px;vertical-align:top}"
             "th{background:#eee}.wrap{overflow-x:auto}.mono{font-family:monospace}"
             "dl{margin:0}dt{font-weight:bold}dd{margin:0 0 6px 12px}</style></head><body>")

    # ---------------- English ----------------
    P.append("<h1>ARIYAN GEO AI &mdash; Wide-Area Search job report</h1>")
    for b in info["banner"]:
        P.append("<div class='banner'>NOT FULLY VERIFIED: %s</div>" % _e(b[0]))
    P.append("<div class='caveat'><b>Read this first</b><ul>%s</ul></div>"
             % "".join("<li>%s</li>" % _e(c) for c in _CAVEATS_EN))
    P.append("<h2>Job</h2><dl>")
    for k, v in [("Job id", info["job_id"]), ("Title", info["title"]),
                 ("Created", _fmt_time(info["created_at"])), ("Job status", info["job_status"]),
                 ("Input", "%s%s" % (info["input_kind"] or "", (" (%s)" % info["place_name"]) if info["place_name"] else "")),
                 ("Search box", box_txt()),
                 ("Tiles", "%s total: done %d, failed %d, pending %d (%s m tiles)"
                  % (info["n_tiles"], tl.get("DONE", 0), tl.get("FAILED", 0), tl.get("PENDING", 0),
                     _num(info["tile_size_m"]))),
                 ("Job trust", "%s%s" % (_TRUST_EN.get(info["trust"], info["trust"]),
                                         (" (%s)" % info["trust_reason"]) if info["trust_reason"] else "")),
                 ("Job target", target_en),
                 ("Report", "%s, generated %s UTC" % (REPORT_VERSION, info["generated_at"][:19].replace("T", " "))),
                 ("Coordinates", coord_en)]:
        P.append("<dt>%s</dt><dd>%s</dd>" % (_e(k), _e(v)))
    P.append("</dl>")

    P.append("<h2>Provenance</h2><dl>")
    P.append("<dt>Full check</dt><dd>%s</dd>" % _e(prov_en))
    if ps:
        P.append("<dt>Candidates verified</dt><dd>%d of %d</dd>" % (ps["candidates_verified"], ps["candidates"]))
        P.append("<dt>Evidence rows verified</dt><dd>%d of %d (checker %s)</dd>"
                 % (ps["evidence_rows_verified"], ps["evidence_rows"], _e(ps["checker_version"])))
        if ps["chain_problem"]:
            P.append("<dt>Ledger chain</dt><dd>%s</dd>" % _e(ps["chain_problem"]))
        if ps["reasons"]:
            P.append("<dt>Why rows are not verified (rows affected)</dt><dd>%s</dd>"
                     % "<br>".join("%d &nbsp; %s" % (n, _e(k))
                                   for k, n in sorted(ps["reasons"].items(), key=lambda kv: -kv[1])))
    if info["provenance_error"]:
        P.append("<dt>Check error</dt><dd>%s</dd>" % _e(info["provenance_error"]))
    P.append("<dt>DEM source of the DEM evidence rows</dt><dd>offline file %d, live %d, not recorded %d</dd>"
             % (led["dem_file"], led["dem_live"], led["dem_not_recorded"]))
    if info["code_bundles"]:
        P.append("<dt>Code bundles (MD5) behind the ledger records</dt><dd class='mono'>%s</dd>"
                 % "<br>".join("%s &nbsp; (%d rows)" % (_e(k), n) for k, n in sorted(info["code_bundles"].items())))
    P.append("</dl>")

    P.append("<h2>Counts</h2><dl>")
    P.append("<dt>Candidates</dt><dd>%d: Open %d, Supported %d, Inconclusive %d, Rejected %d</dd>"
             % (info["candidates_total"], sc[review.STATUS_OPEN], sc[review.STATUS_SUPPORTED],
                sc[review.STATUS_INCONCLUSIVE], sc[review.STATUS_REJECTED]))
    if info["calib_active"]:
        P.append("<dt>calib-v1 strong (|z| &ge; 6)</dt><dd>%d</dd>" % info["calib_strong"])
    P.append("<dt>In the table below</dt><dd>%d rows (%s)</dd>" % (info["rows_shown"], _e(n_label_en)))
    P.append("<dt>Table order</dt><dd>not Rejected first, then Steward confidence (high to low), "
             "then |DEM z-score| (high to low)</dd></dl>")

    # ---------------- Persian ----------------
    P.append("<div class='fa' lang='fa' dir='rtl'>")
    P.append("<h1>ARIYAN GEO AI &mdash; گزارش کار جست‌وجوی گسترده</h1>")
    for b in info["banner"]:
        P.append("<div class='banner'>کاملاً تأییدنشده: %s</div>" % _e(b[1]))
    P.append("<div class='caveat'><b>پیش از هر چیز این را بخوانید</b><ul>%s</ul></div>"
             % "".join("<li>%s</li>" % _e(c) for c in _CAVEATS_FA))
    P.append("<h2>کار</h2><dl>")
    for k, v in [("شناسهٔ کار", info["job_id"]), ("عنوان", info["title"]),
                 ("تاریخ ایجاد", _fmt_time(info["created_at"])),
                 ("کاشی‌ها", "%s کاشی: انجام‌شده %d، ناموفق %d، در انتظار %d"
                  % (info["n_tiles"], tl.get("DONE", 0), tl.get("FAILED", 0), tl.get("PENDING", 0))),
                 ("اعتماد به کار", _TRUST_FA.get(info["trust"], info["trust"])),
                 ("هدف کار", target_fa),
                 ("منشأ داده‌ها (بررسی کامل)", prov_fa),
                 ("نامزدها", "%d: باز %d، پشتیبانی‌شده %d، بی‌نتیجه %d، ردشده %d"
                  % (info["candidates_total"], sc[review.STATUS_OPEN], sc[review.STATUS_SUPPORTED],
                     sc[review.STATUS_INCONCLUSIVE], sc[review.STATUS_REJECTED])),
                 ("جدول", "%d ردیف (%s)؛ ترتیب: ابتدا ردنشده‌ها، سپس اطمینان، سپس قدر مطلق z" % (info["rows_shown"], n_label_fa)),
                 ("مختصات", coord_fa)]:
        P.append("<dt>%s</dt><dd>%s</dd>" % (_e(k), _e(v)))
    P.append("</dl></div>")

    # ---------------- Table ----------------
    P.append("<h2>Candidates / نامزدها</h2><div class='wrap'><table><tr>"
             "<th>#</th><th>Candidate id</th><th>Lat</th><th>Lon</th><th>DEM z</th>"
             "<th>Status / وضعیت</th><th>Confidence</th><th>calib-v1</th>"
             "<th>Terrain (F3)</th><th>Known-site context</th><th class='fa'>زمینهٔ محوطهٔ ثبت‌شده</th></tr>")
    for r in rows:
        status = "%s%s / %s" % (r["status_en"], " (auto)" if r["review_source"] == "auto" else "", r["status_fa"])
        terrain = r["terrain_shape"]
        if r["hillside"]:
            terrain += ", hillside %s" % r["hillside"]
        if r["terrain_method"]:
            terrain += " [%s]" % r["terrain_method"]
        P.append("<tr><td>%d</td><td class='mono'>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                 "<td>%s</td><td>%s</td><td>%s</td><td class='ks'>%s</td><td class='fa ks'>%s</td></tr>"
                 % (r["rank"], _e(r["id"][:8]), _e(_fmt_coord(r["lat"], exact)), _e(_fmt_coord(r["lon"], exact)),
                    _e(_fmt_z(r["score"])), _e(status), _e(_fmt_conf(r)),
                    "strong" if r["calib_strong"] else "", _e(terrain), _e(r["known_site_en"]),
                    _e(r["known_site_fa"])))
    if not rows:
        P.append("<tr><td colspan='11'>No candidates / بدون نامزد</td></tr>")
    P.append("</table></div>")
    P.append("<p style='font-size:0.8em;color:#555'>Generated by ARIYAN GEO AI %s. This file was written "
             "by the app; its MD5 is recorded on the project timeline (REPORT_EXPORTED).</p>" % REPORT_VERSION)
    P.append("</body></html>")
    return "\n".join(P)


_CSV_COLUMNS = ["rank", "candidate_id", "lat", "lon", "coordinate_precision", "dem_z", "status",
                "status_source", "confidence_band", "confidence", "calib_v1", "terrain_shape",
                "hillside", "terrain_method", "known_site_label", "known_site_context", "job_id",
                "report_version"]


def _render_csv(info: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
    exact = info["exact_coords"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(_CSV_COLUMNS)
    for r in rows:
        w.writerow([
            r["rank"], r["id"], _fmt_coord(r["lat"], exact), _fmt_coord(r["lon"], exact),
            "exact" if exact else "0.01 deg", _fmt_z(r["score"]), r["status_en"], r["review_source"],
            r["confidence_band"],
            ("%.2f" % r["confidence_numeric"]) if isinstance(r["confidence_numeric"], (int, float)) else "",
            "strong" if r["calib_strong"] else "", r["terrain_shape"], r["hillside"], r["terrain_method"],
            r["known_site_label"], r["known_site_en"], info["job_id"], REPORT_VERSION,
        ])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# JSON wrappers (Kotlin boundary)
# ---------------------------------------------------------------------------

def _json(fn, *args) -> str:
    try:
        return json.dumps(fn(*args))
    except (ReportError, review.ReviewError) as e:
        return json.dumps({"error": str(e)})


def dashboard_json(db_root: str, grand_project_id: str) -> str:
    return _json(dashboard, db_root, grand_project_id)


def export_job_report_json(db_root: str, grand_project_id: str, job_ref: str,
                           top_n: int, exact_coords: bool) -> str:
    return _json(export_job_report, db_root, grand_project_id, job_ref, top_n, exact_coords)
