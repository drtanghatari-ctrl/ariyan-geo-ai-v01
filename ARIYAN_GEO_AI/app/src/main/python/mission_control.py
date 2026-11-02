"""
mission_control.py -- mc-v1 + dbe-v1 (2026-11-02). Read-only.

mc-v1, Mission Control (the app's new start page). mission_json() returns:
  * study area: the default Grand Project, jobs, candidates, last activity;
  * confidence picture: candidates per Steward band (Rejected left out and
    counted separately), the highest band reached, its numeric ceiling and
    the reason it holds -- the Steward's own recorded words where they exist.
    No invented percentage;
  * candidate targets: the best non-Rejected candidates by stored band,
    stored confidence, Supported first, then |z|; with calib-v1 strong flag
    and nearest recorded site;
  * data sources: what really exists on the phone (bulk DEM tiles, DEM
    library tiles, WorldCover tiles, saved satellite answers, field datasets,
    calibration, latest database backup). Keys are checked by the Kotlin
    screen and never pass through here.

mc-v1.3: thumbs_json() lists, for an open Final Image session (the 3D card's
window), which satellite layers are already SAVED on the phone for that window,
and opens only those (never fetches, never uses Copernicus quota; a layer
whose one-time self-check has not passed stays hidden with its reason).

mc-v1.3: models_json() lists the analysis rules and models the app really
uses, each read from its own module (version names, the adopted calib-v1
profile from the database, the debate engine's SHA-256), with what each may and
may not do. settings_json() reports the storage, database, backups, guard and
crash reports for the Settings screen. Both are read-only.

mc-v1.4 (user decision 2026-11-02): Settings marks which automatic daily
backups are safe to delete and delete_backup_json() deletes ONE of them. Rule:
the 3 newest automatic backups and the largest one(s) are protected; only files
named grand_project_auto_YYYYMMDD.db inside db_backups can ever be deleted, so
grand_project.db and the user's own copies are never touched. The rule is
checked again at the moment of deleting, and every deletion is written to the
project timeline (BACKUP_DELETED_BY_USER).

dbe-v1, AI Debate Engine. debates_json() lists the debates stored by dbr-v1
(newest first, filterable by agreement) with a project-wide summary;
debate_detail_json() returns one stored debate in full. Nothing is re-run or
re-created; nothing changes a status, a review or a confidence.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import grand_project_db as db

VERSION = "mc-v1.4"
DEBATE_VERSION = "dbe-v1"
DEFAULT_PROJECT_ID = "default"          # grand_project_sync.DEFAULT_GRAND_PROJECT_ID

BAND_ORDER = ["SUBSTANTIAL", "HIGH", "MODERATE", "LOW", "NO_DATA"]
BAND_RANK = {b: i for i, b in enumerate(reversed(BAND_ORDER))}       # NO_DATA 0 ... SUBSTANTIAL 4
BAND_CEILING = {"NO_DATA": 0.0, "LOW": 0.35, "MODERATE": 0.55, "HIGH": 0.75, "SUBSTANTIAL": 0.90}
NOT_RATED = "NOT_RATED"
STATUS_LABELS = {"GENERATED": "Open", "SUPPORTED": "Supported", "REJECTED": "Rejected",
                 "INCONCLUSIVE": "Inconclusive"}
STATUS_RANK = {"SUPPORTED": 2, "GENERATED": 1, "INCONCLUSIVE": 1}
AGREEMENTS = ["LEADING_INTERPRETATION", "CONTESTED", "WEAK_SIGNAL", "NO_DATA"]
SUMMARY_SCAN_CAP = 20000                # Python fallback only (no SQLite JSON functions)

CEILING_RULES = {
    "MODERATE": ("HIGH needs environmental confounders to be controlled, which the app cannot do yet; "
                 "SUBSTANTIAL needs real field data (GPR/ERT) confirming the candidate."),
    "HIGH": "SUBSTANTIAL needs real field data (GPR/ERT) confirming the candidate.",
    "LOW": "Most candidates have one remote source only; corroboration from independent sources raises the band.",
}
PRINCIPLES = ["Real Data Only", "Scientific Integrity", "No Synthetic Data", "Uncertainty Quantified",
              "Human Oversight"]
STATEMENT = ("Mission Control shows recorded results only. Nothing here is recomputed, and nothing here "
             "changes a status, a review or a confidence.")
DEBATE_STATEMENT = ("Stored debates only (dbr-v1, from 2026-10-31). The debate is a ranked rule-based "
                    "opinion, not proof; the Steward's band is what counts. Nothing is re-run here.")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _has_table(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _band(b: Any) -> str:
    b = (str(b).upper() if b not in (None, "") else NOT_RATED)
    return b if b in BAND_CEILING else NOT_RATED


def _count_files(folder: str, suffixes=(".tif", ".tiff")) -> Dict[str, int]:
    n, size = 0, 0
    try:
        for name in os.listdir(folder):
            p = os.path.join(folder, name)
            if os.path.isfile(p) and name.lower().endswith(suffixes):
                n += 1
                size += os.path.getsize(p)
    except OSError:
        pass
    return {"files": n, "bytes": size}


def _ceiling_lines(conn, candidate_id: Optional[str]) -> List[str]:
    """The Steward's own recorded reasoning lines about the cap, for one candidate."""
    if not candidate_id:
        return []
    r = conn.execute("SELECT reasoning_snapshot_json FROM confidence_history WHERE candidate_id = ? "
                     "ORDER BY id DESC LIMIT 1", (candidate_id,)).fetchone()
    if r is None or not r[0]:
        return []
    try:
        lines = json.loads(r[0])
    except ValueError:
        lines = [str(r[0])]
    if not isinstance(lines, list):
        lines = [str(lines)]
    keys = ("ceiling", "capped", "cap ", "confounder", "field valid")
    return [str(x) for x in lines if any(k in str(x).lower() for k in keys)][:2]


# ---------------------------------------------------------------------------
# mc-v1
# ---------------------------------------------------------------------------

def _data_sources(db_root: str, conn) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # bulk DEM (Pass 1): <root>/<country>/dem/*.tif, dem_library skipped (cop30_bulk rule)
    bulk = {"files": 0, "bytes": 0}
    try:
        for d in sorted(os.listdir(db_root)):
            if d == "dem_library":
                continue
            c = _count_files(os.path.join(db_root, d, "dem"))
            bulk["files"] += c["files"]
            bulk["bytes"] += c["bytes"]
    except OSError:
        pass
    out.append({"name": "Terrain DEM, bulk COP30 (Pass 1)", "ok": bulk["files"] > 0,
                "detail": "{:,} tile(s), {:.1f} GB".format(bulk["files"], bulk["bytes"] / 1e9)})
    for demtype in ("SRTMGL1", "COP30"):
        c = _count_files(os.path.join(db_root, "dem_library", demtype))
        out.append({"name": "DEM library %s (Pass 2)" % demtype, "ok": c["files"] > 0,
                    "detail": "%d tile(s), %.0f MB" % (c["files"], c["bytes"] / 1e6)})
    try:
        wc = [n for n in os.listdir(os.path.join(db_root, "worldcover_library"))
              if os.path.isdir(os.path.join(db_root, "worldcover_library", n))]
    except OSError:
        wc = []
    out.append({"name": "Land cover (ESA WorldCover)", "ok": bool(wc), "detail": "%d tile(s) saved" % len(wc)})
    sat = 0
    try:
        base = os.path.join(db_root, "sat_library")
        for kind in os.listdir(base):
            try:
                with open(os.path.join(base, kind, "index.json")) as f:
                    sat += len(json.load(f))
            except (OSError, ValueError):
                pass
    except OSError:
        pass
    out.append({"name": "Satellite answers saved (NDVI/thermal/SAR/optical)", "ok": sat > 0,
                "detail": "{:,} saved answer(s); new ones are fetched online".format(sat)})
    n_field = 0
    if _has_table(conn, "field_dataset"):
        n_field = conn.execute("SELECT COUNT(*) FROM field_dataset").fetchone()[0]
        if _has_table(conn, "field_dataset_event"):
            n_field -= conn.execute("SELECT COUNT(DISTINCT dataset_id) FROM field_dataset_event "
                                    "WHERE event = 'WITHDRAWN'").fetchone()[0]
    out.append({"name": "Field data (GPR/ERT)", "ok": n_field > 0,
                "detail": ("%d active dataset(s)" % n_field) if n_field else "none imported"})
    calib = None
    try:
        import calib_profile
        calib = calib_profile.active_profile(db_root)
    except Exception:
        calib = None
    out.append({"name": "Calibration calib-v1", "ok": calib is not None,
                "detail": ("adopted (|z| >= %s)" % calib.get("threshold_abs_z")) if calib else "not adopted"})
    backups = []
    try:
        folder = os.path.join(db_root, db.BACKUP_DIRNAME)
        backups = sorted(n for n in os.listdir(folder)
                         if n.startswith(db.AUTO_BACKUP_PREFIX) and n.endswith(".db"))
    except (OSError, AttributeError):
        backups = []
    if backups:
        p = os.path.join(db_root, db.BACKUP_DIRNAME, backups[-1])
        day = backups[-1][len(db.AUTO_BACKUP_PREFIX):-3]
        out.append({"name": "Database backup (db-safe-v1)", "ok": True,
                    "detail": "latest %s-%s-%s, %.0f MB; %d kept" % (day[:4], day[4:6], day[6:8],
                                                                    os.path.getsize(p) / 1e6, len(backups))})
    else:
        out.append({"name": "Database backup (db-safe-v1)", "ok": False, "detail": "no automatic backup found"})
    return out


def mission(db_root: str, top_n: int = 10) -> Dict[str, Any]:
    conn = db.get_connection(db_root)
    try:
        db.initialize_schema(conn)
        gp = conn.execute("SELECT * FROM grand_project WHERE id = ?", (DEFAULT_PROJECT_ID,)).fetchone()
        if gp is None:
            gp = conn.execute("SELECT * FROM grand_project ORDER BY created_at LIMIT 1").fetchone()
        sources = _data_sources(db_root, conn)
        if gp is None:
            return {"version": VERSION, "project": None, "bands": [], "top": [], "sources": sources,
                    "principles": PRINCIPLES, "statement": STATEMENT,
                    "empty_note": "No Grand Project yet. Run an investigation or a wide-area search to start one."}
        gid = gp["id"]
        n_jobs = conn.execute("SELECT COUNT(*) FROM wide_area_search_job WHERE grand_project_id = ?",
                              (gid,)).fetchone()[0]
        running = conn.execute("SELECT COUNT(*) FROM wide_area_search_job WHERE grand_project_id = ? "
                               "AND status IN ('RUNNING', 'PENDING')", (gid,)).fetchone()[0]
        n_inv = conn.execute("SELECT COUNT(*) FROM investigation WHERE grand_project_id = ?", (gid,)).fetchone()[0]
        last = conn.execute(
            "SELECT MAX(t) FROM (SELECT MAX(occurred_at) AS t FROM timeline_event WHERE grand_project_id = ? "
            "UNION ALL SELECT MAX(last_updated_at) FROM wide_area_search_job WHERE grand_project_id = ? "
            "UNION ALL SELECT MAX(created_at) FROM investigation WHERE grand_project_id = ?)",
            (gid, gid, gid)).fetchone()[0]

        status_counts: Dict[str, int] = {}
        for r in conn.execute("SELECT status, COUNT(*) AS n FROM candidate WHERE grand_project_id = ? "
                              "GROUP BY status", (gid,)):
            status_counts[STATUS_LABELS.get(r["status"], r["status"])] = r["n"]
        band_counts: Dict[str, int] = {b: 0 for b in BAND_ORDER + [NOT_RATED]}
        for r in conn.execute("SELECT confidence_band, COUNT(*) AS n FROM candidate WHERE grand_project_id = ? "
                              "AND status != 'REJECTED' GROUP BY confidence_band", (gid,)):
            band_counts[_band(r["confidence_band"])] += r["n"]
        rated = [b for b in BAND_ORDER if b != "NO_DATA" and band_counts[b] > 0]
        highest = rated[0] if rated else None
        highest_numeric = None
        if highest:
            highest_numeric = conn.execute(
                "SELECT MAX(confidence_numeric) FROM candidate WHERE grand_project_id = ? AND status != 'REJECTED' "
                "AND UPPER(confidence_band) = ?", (gid, highest)).fetchone()[0]

        rows = [dict(r) for r in conn.execute(
            "SELECT c.id, c.lat, c.lon, c.status, c.score, c.confidence_band, c.confidence_numeric, "
            "t.job_id, j.title AS job_title FROM candidate c "
            "LEFT JOIN wide_area_search_tile t ON t.investigation_id = c.investigation_id "
            "LEFT JOIN wide_area_search_job j ON j.id = t.job_id "
            "WHERE c.grand_project_id = ? AND c.status != 'REJECTED'", (gid,))]

        def key(c):
            b = _band(c["confidence_band"])
            return (BAND_RANK.get(b, -1), c["confidence_numeric"] or 0.0, STATUS_RANK.get(c["status"], 0),
                    abs(c["score"] or 0.0))

        rows.sort(key=key, reverse=True)
        top = rows[:max(0, int(top_n))]
        ceiling_lines = _ceiling_lines(conn, top[0]["id"] if top else None)
        n_debates = conn.execute("SELECT COUNT(*) FROM debate_record").fetchone()[0] \
            if _has_table(conn, "debate_record") else 0
    finally:
        conn.close()

    calib_mod, profile = None, None
    try:
        import calib_profile
        calib_mod, profile = calib_profile, calib_profile.active_profile(db_root)
    except Exception:
        pass
    try:
        import known_sites
    except Exception:
        known_sites = None
    targets = []
    for c in top:
        ks = None
        if known_sites is not None:
            try:
                ks = known_sites.annotate(c["lat"], c["lon"]).get("text")
            except Exception:
                ks = None
        targets.append({
            "id": c["id"], "lat": c["lat"], "lon": c["lon"], "band": _band(c["confidence_band"]),
            "numeric": c["confidence_numeric"], "status": STATUS_LABELS.get(c["status"], c["status"]),
            "z": c["score"], "job_id": c["job_id"], "job_title": c["job_title"],
            "calib_strong": bool(calib_mod and profile and calib_mod.is_strong(c["score"], profile)),
            "known_site": ks})

    total_active = sum(band_counts.values())
    return {
        "version": VERSION,
        "project": {"id": gid, "name": gp["name"], "jobs": n_jobs, "jobs_unfinished": running,
                    "investigations": n_inv, "candidates": sum(status_counts.values()),
                    "status_counts": status_counts, "last_activity": last},
        "confidence": {
            "bands": [{"band": b, "count": band_counts[b], "ceiling": BAND_CEILING.get(b)}
                      for b in BAND_ORDER + [NOT_RATED]],
            "active_candidates": total_active, "rejected": status_counts.get("Rejected", 0),
            "highest": highest, "highest_ceiling": BAND_CEILING.get(highest) if highest else None,
            "highest_numeric": highest_numeric,
            "why": CEILING_RULES.get(highest, "") if highest else "No candidate has a Steward rating yet.",
            "steward_words": ceiling_lines},
        "top": targets, "debates_stored": n_debates, "sources": sources,
        "principles": PRINCIPLES, "statement": STATEMENT,
    }


def mission_json(db_root: str, top_n: int = 10) -> str:
    try:
        return json.dumps(mission(db_root, int(top_n)), default=str)
    except Exception as e:                           # shown, never hidden
        return json.dumps({"error": "%s: %s" % (type(e).__name__, e)})


# ---------------------------------------------------------------------------
# dbe-v1
# ---------------------------------------------------------------------------

def _brief(d: Dict[str, Any]) -> Dict[str, Any]:
    syn = d.get("synthesis") or {}
    conf = (((d.get("steward") or {}).get("reasoning_trace") or {}).get("confidence") or {})
    return {"leading": syn.get("leading_position"), "leading_confidence": syn.get("leading_confidence"),
            "agreement": syn.get("agreement_level") or "NO_DATA",
            "steward_band": conf.get("band"), "steward_numeric": conf.get("clamped_confidence"),
            "steward_capped": bool(conf.get("was_clamped")) if conf else None,
            "steward_error": d.get("steward_error")}


def _json_functions(conn) -> bool:
    try:
        conn.execute("SELECT json_extract('{\"a\":1}', '$.a')").fetchone()
        return True
    except Exception:
        return False


_AGR = "COALESCE(json_extract(debate_json, '$.synthesis.agreement_level'), 'NO_DATA')"


def _summary(conn, use_json: bool) -> Dict[str, Any]:
    s = {"debates": 0, "candidates": 0, "by_agreement": {a: 0 for a in AGREEMENTS},
         "by_leading": {}, "steward_capped": 0, "steward_rated": 0, "scanned": None}
    s["debates"] = conn.execute("SELECT COUNT(*) FROM debate_record").fetchone()[0]
    s["candidates"] = conn.execute("SELECT COUNT(DISTINCT candidate_id) FROM debate_record").fetchone()[0]
    if use_json:
        for r in conn.execute("SELECT %s AS a, COUNT(*) AS n FROM debate_record GROUP BY a" % _AGR):
            s["by_agreement"][r["a"]] = s["by_agreement"].get(r["a"], 0) + r["n"]
        for r in conn.execute("SELECT json_extract(debate_json, '$.synthesis.leading_position') AS p, COUNT(*) AS n "
                              "FROM debate_record GROUP BY p"):
            s["by_leading"][r["p"] or "none"] = r["n"]
        r = conn.execute("SELECT SUM(CASE WHEN json_extract(debate_json, "
                         "'$.steward.reasoning_trace.confidence.was_clamped') THEN 1 ELSE 0 END), "
                         "SUM(CASE WHEN json_extract(debate_json, '$.steward.reasoning_trace.confidence.band') "
                         "IS NOT NULL THEN 1 ELSE 0 END) FROM debate_record").fetchone()
        s["steward_capped"], s["steward_rated"] = int(r[0] or 0), int(r[1] or 0)
        return s
    n = 0
    for r in conn.execute("SELECT debate_json FROM debate_record ORDER BY id DESC LIMIT ?", (SUMMARY_SCAN_CAP,)):
        n += 1
        try:
            b = _brief(json.loads(r[0]))
        except ValueError:
            continue
        s["by_agreement"][b["agreement"]] = s["by_agreement"].get(b["agreement"], 0) + 1
        s["by_leading"][b["leading"] or "none"] = s["by_leading"].get(b["leading"] or "none", 0) + 1
        if b["steward_band"] is not None:
            s["steward_rated"] += 1
            s["steward_capped"] += 1 if b["steward_capped"] else 0
    s["scanned"] = n if n < s["debates"] else None
    return s


def debates(db_root: str, agreement: str = "ALL", limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    agreement = (agreement or "ALL").upper()
    if agreement != "ALL" and agreement not in AGREEMENTS:
        raise ValueError("agreement must be ALL or one of " + ", ".join(AGREEMENTS))
    limit, offset = max(1, min(int(limit), 200)), max(0, int(offset))
    conn = db.get_connection(db_root)
    try:
        db.initialize_schema(conn)
        if not _has_table(conn, "debate_record"):
            return {"version": DEBATE_VERSION, "summary": None, "rows": [], "more": False,
                    "note": "No debates stored yet.", "statement": DEBATE_STATEMENT}
        use_json = _json_functions(conn)
        summary = _summary(conn, use_json)
        base = ("SELECT d.id, d.candidate_id, d.recorded_at, d.origin, d.debate_json, c.lat, c.lon, c.status, "
                "c.confidence_band FROM debate_record d LEFT JOIN candidate c ON c.id = d.candidate_id")
        rows: List[Dict[str, Any]] = []
        more = False
        if agreement == "ALL" or use_json:
            sql, args = base, []
            if agreement != "ALL":
                sql += " WHERE %s = ?" % _AGR.replace("debate_json", "d.debate_json")
                args.append(agreement)
            sql += " ORDER BY d.id DESC LIMIT ? OFFSET ?"
            args += [limit + 1, offset]
            raw = [dict(r) for r in conn.execute(sql, args)]
        else:                                         # Python filter (no SQLite JSON functions)
            raw, skipped = [], 0
            for r in conn.execute(base + " ORDER BY d.id DESC"):
                r = dict(r)
                try:
                    a = _brief(json.loads(r["debate_json"]))["agreement"]
                except ValueError:
                    continue
                if a != agreement:
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                raw.append(r)
                if len(raw) > limit:
                    break
        more = len(raw) > limit
        for r in raw[:limit]:
            try:
                d = json.loads(r.pop("debate_json"))
            except ValueError:
                d = {}
            rows.append(dict(r, **_brief(d), status=STATUS_LABELS.get(r["status"], r["status"])))
    finally:
        conn.close()
    return {"version": DEBATE_VERSION, "agreement": agreement, "offset": offset, "summary": summary,
            "rows": rows, "more": more, "statement": DEBATE_STATEMENT,
            "note": None if summary["debates"] else
            "No debates stored yet. Every new run and every Pass 2 refinement stores its debate (dbr-v1)."}


def debates_json(db_root: str, agreement: str = "ALL", limit: int = 50, offset: int = 0) -> str:
    try:
        return json.dumps(debates(db_root, agreement, limit, offset), default=str)
    except Exception as e:
        return json.dumps({"error": "%s: %s" % (type(e).__name__, e)})


def debate_detail(db_root: str, record_id: int) -> Dict[str, Any]:
    conn = db.get_connection(db_root)
    try:
        db.initialize_schema(conn)
        if not _has_table(conn, "debate_record"):
            raise KeyError("no debates stored")
        r = conn.execute("SELECT d.*, c.lat, c.lon, c.status, c.confidence_band, c.confidence_numeric "
                         "FROM debate_record d LEFT JOIN candidate c ON c.id = d.candidate_id WHERE d.id = ?",
                         (int(record_id),)).fetchone()
        if r is None:
            raise KeyError("debate %s not found" % record_id)
        r = dict(r)
        n_for_cand = conn.execute("SELECT COUNT(*) FROM debate_record WHERE candidate_id = ?",
                                  (r["candidate_id"],)).fetchone()[0]
    finally:
        conn.close()
    d = json.loads(r.pop("debate_json"))
    conf = (((d.get("steward") or {}).get("reasoning_trace") or {}).get("confidence") or {})
    return {"version": DEBATE_VERSION, "id": r["id"], "candidate_id": r["candidate_id"],
            "investigation_id": r["investigation_id"], "origin": r["origin"], "recorded_at": r["recorded_at"],
            "engine_sha256": r["engine_sha256"], "store_version": r["store_version"],
            "debates_for_candidate": n_for_cand,
            "candidate": {"lat": r["lat"], "lon": r["lon"], "status": STATUS_LABELS.get(r["status"], r["status"]),
                          "band": r["confidence_band"], "numeric": r["confidence_numeric"]},
            "positions": d.get("positions") or [], "synthesis": d.get("synthesis") or {},
            "steward": {"band": conf.get("band"), "numeric": conf.get("clamped_confidence"),
                        "raw": conf.get("raw_confidence"), "capped": conf.get("was_clamped"),
                        "reasoning": conf.get("reasoning") or [], "error": d.get("steward_error")},
            "statement": DEBATE_STATEMENT}


def debate_detail_json(db_root: str, record_id: int) -> str:
    try:
        return json.dumps(debate_detail(db_root, int(record_id)), default=str)
    except Exception as e:
        return json.dumps({"error": "%s: %s" % (type(e).__name__, e)})


# ---------------------------------------------------------------------------
# mc-v1.3 layer thumbnails (saved images only)
# ---------------------------------------------------------------------------

def thumbs(db_root: str, session_id: str) -> Dict[str, Any]:
    import sat_image as si
    import sat_image_mobile as sim
    out: List[Dict[str, Any]] = []
    for p in si.LAYER_ORDER:
        label = si.PRODUCTS[p]["label"]
        try:
            r = json.loads(sim.open_layer_json(db_root, session_id, p, "", "", False))
        except Exception as e:                        # shown, never hidden
            r = {"error": "%s: %s" % (type(e).__name__, e)}
        if r.get("needs_fetch"):
            out.append({"product": p, "label": label, "state": "NOT_SAVED"})
        elif "error" in r:
            out.append({"product": p, "label": label, "state": "ERROR", "reason": r["error"]})
        elif not r.get("allowed"):
            out.append({"product": p, "label": label, "state": "HIDDEN",
                        "reason": r.get("hidden_reason") or r.get("check")})
        else:
            g = r.get("grid") or {}
            out.append({"product": p, "label": label, "state": "SAVED", "scene_date": r.get("scene_date"),
                        "clear_fraction": r.get("clear_fraction_window"),
                        "width": g.get("width"), "height": g.get("height")})
    return {"version": VERSION, "layers": out,
            "note": "Saved images only; nothing is fetched here. Open the Final Image to fetch a missing layer."}


def thumbs_json(db_root: str, session_id: str) -> str:
    try:
        return json.dumps(thumbs(db_root, session_id), default=str)
    except Exception as e:
        return json.dumps({"error": "%s: %s" % (type(e).__name__, e)})


# ---------------------------------------------------------------------------
# mc-v1.3 Analysis & Models (read from the modules themselves)
# ---------------------------------------------------------------------------

def _const(module: str, name: str) -> Optional[str]:
    try:
        return str(getattr(__import__(module), name))
    except Exception:
        return None


def models(db_root: str) -> Dict[str, Any]:
    calib = None
    try:
        import calib_profile
        calib = calib_profile.active_profile(db_root)
    except Exception:
        calib = None
    debate_sha = None
    n_debates = 0
    try:
        import debate_store
        debate_sha = debate_store.engine_sha256()
        conn = db.get_connection(db_root)
        try:
            db.initialize_schema(conn)
            if _has_table(conn, "debate_record"):
                n_debates = conn.execute("SELECT COUNT(*) FROM debate_record").fetchone()[0]
        finally:
            conn.close()
    except Exception:
        pass
    rows = [
        {"name": "Scientific Steward (confidence ceiling)", "version": "Stage 1",
         "role": "Rates every candidate LOW / MODERATE / HIGH / SUBSTANTIAL and only ever lowers a score.",
         "limits": "HIGH needs environmental confounders controlled; SUBSTANTIAL needs field data (GPR/ERT). "
                   "Today the ceiling is MODERATE 0.55."},
        {"name": "AI Debate Engine", "version": "dbr-v1 store; engine SHA-256 " + (debate_sha or "unknown")[:12],
         "role": "Four perspectives argue each candidate; the synthesis never declares a winner.",
         "limits": "A ranked rule-based opinion, not proof. %d debate(s) stored." % n_debates},
        {"name": "calib-v1 score threshold", "version": "calib-v1" if calib else "not adopted",
         "role": ("Labels candidates with |z| >= %s as strong (bench pass, user-approved)." % calib.get("threshold_abs_z"))
                 if calib else "Not adopted on this phone.",
         "limits": "A label and a sort order only; never changes status, confidence or reviews."},
        {"name": "Pass 2 reproduction rule", "version": _const("grand_project_refinement", "POLARITY_RULE_VERSION"),
         "role": "Live SRTM re-detects the anomaly with the same polarity within tolerance -> Supported (auto).",
         "limits": "Frozen tests T3/T4 passed (site 26%/37% vs control 8%/6%); supporting evidence, not proof."},
        {"name": "Land cover rule", "version": _const("land_cover_flags", "LC2_METHOD"),
         "role": "Rejects only when the centre (~15 m) is mostly trees, buildings or water (ESA WorldCover).",
         "limits": "The ring around the centre is a label only (test T1 passed)."},
        {"name": "Terrain labels / Hillside", "version": _const("terrain_context_labels", "METHOD_VERSION"),
         "role": "Mound, Depression, Linear, Ring labels; Hillside rejects only in Mound/tell jobs.",
         "limits": "Shape labels never reject."},
        {"name": "Mapped industry", "version": _const("industrial_label", "LABEL_VERSION"),
         "role": "Labels candidates within 300 m of mapped industry and moves them to the back of Pass 2.",
         "limits": "Never rejects."},
        {"name": "Known sites (ANE gazetteer)", "version": "F1",
         "role": "Nearest recorded site and distance: likely rediscovery or not in gazetteer.",
         "limits": "Context only, never evidence."},
        {"name": "Provenance ledger", "version": _const("provenance_ledger", "LEDGER_VERSION"),
         "role": "Hash chain over every evidence row, its sources and the code that made it.",
         "limits": "Makes rows traceable; does not raise confidence."},
        {"name": "Automatic run", "version": _const("auto_pipeline", "VERSION"),
         "role": "Library fill, sweep, land cover, labels, review, Pass 2, provenance, trust, report.",
         "limits": "Never marks a job CORRUPTED; user trust marks are never overwritten."},
        {"name": "Final Image", "version": _const("final_image", "FI_VERSION"),
         "role": "Terrain image, satellite layers, profile, 3D surface, evidence volume.",
         "limits": "No interpolation: native cells only."},
    ]
    return {"version": VERSION, "models": rows,
            "statement": "Rules and models in use on this phone, read from the app's own code and database. "
                         "Nothing here is run or changed."}


def models_json(db_root: str) -> str:
    try:
        return json.dumps(models(db_root), default=str)
    except Exception as e:
        return json.dumps({"error": "%s: %s" % (type(e).__name__, e)})


# ---------------------------------------------------------------------------
# mc-v1.3 Settings (storage, database, backups) -- read-only
# ---------------------------------------------------------------------------

def _folder_stats(path: str) -> Dict[str, Any]:
    n, size = 0, 0
    for base, _dirs, files in os.walk(path):
        for f in files:
            try:
                size += os.path.getsize(os.path.join(base, f))
                n += 1
            except OSError:
                pass
    return {"files": n, "bytes": size}


def settings(db_root: str) -> Dict[str, Any]:
    dbp = os.path.join(db_root, db.DB_FILENAME)
    out: Dict[str, Any] = {"version": VERSION, "root": db_root,
                           "database": {"path": dbp, "exists": os.path.isfile(dbp),
                                        "bytes": os.path.getsize(dbp) if os.path.isfile(dbp) else 0}}
    guard = None
    try:
        with open(os.path.join(db_root, db.GUARD_FILENAME)) as f:
            guard = json.load(f)
    except (OSError, ValueError):
        guard = None
    out["guard"] = guard
    out["allow_new_flag"] = os.path.exists(os.path.join(db_root, db.ALLOW_NEW_FILENAME))
    folder = os.path.join(db_root, db.BACKUP_DIRNAME)
    out["backups"] = {"folder": folder, "files": backup_list(db_root),
                      "keep_rule": "the newest %d daily backups plus the largest"
                      % getattr(db, "AUTO_BACKUP_KEEP", 10),
                      "delete_rule": "Protected: the %d newest automatic backups and the largest. Only automatic "
                                     "backups (grand_project_auto_YYYYMMDD.db) can be deleted here; grand_project.db "
                                     "and your own copies never." % KEEP_NEWEST_BACKUPS}
    crash = []
    try:
        cdir = os.path.join(db_root, "crash_reports")
        crash = sorted((n for n in os.listdir(cdir) if n.endswith(".txt")), reverse=True)
    except OSError:
        pass
    out["crash_reports"] = {"count": len(crash), "newest": crash[0] if crash else None}
    out["folders"] = [dict(name=n, **_folder_stats(os.path.join(db_root, n)))
                      for n in ("dem_library", "worldcover_library", "sat_library", "field_data", "exports", "reports")
                      if os.path.isdir(os.path.join(db_root, n))]
    return out


def settings_json(db_root: str) -> str:
    try:
        return json.dumps(settings(db_root), default=str)
    except Exception as e:
        return json.dumps({"error": "%s: %s" % (type(e).__name__, e)})


# ---------------------------------------------------------------------------
# mc-v1.4 backups: which are safe to delete, and deleting one
# ---------------------------------------------------------------------------

import re as _re

KEEP_NEWEST_BACKUPS = 3                       # user decision 2026-11-02
_AUTO_RE = _re.compile(r"^grand_project_auto_(\d{8})\.db$")


def backup_list(db_root: str) -> List[Dict[str, Any]]:
    """Every *.db in db_backups, newest first, each marked deletable or protected (with the reason)."""
    folder = os.path.join(db_root, db.BACKUP_DIRNAME)
    files = []
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    for n in names:
        p = os.path.join(folder, n)
        if n.endswith(".db") and os.path.isfile(p) and not os.path.islink(p):
            files.append({"name": n, "bytes": os.path.getsize(p), "auto": bool(_AUTO_RE.match(n))})
    autos = sorted((f for f in files if f["auto"]), key=lambda f: f["name"], reverse=True)   # YYYYMMDD in name
    newest = {f["name"] for f in autos[:KEEP_NEWEST_BACKUPS]}
    biggest = max((f["bytes"] for f in autos), default=None)
    for f in files:
        if not f["auto"]:
            f["deletable"], f["protected_reason"] = False, "your own copy (not an automatic backup)"
        elif f["name"] in newest:
            f["deletable"], f["protected_reason"] = False, "one of the %d newest" % KEEP_NEWEST_BACKUPS
        elif f["bytes"] == biggest:
            f["deletable"], f["protected_reason"] = False, "the largest backup"
        else:
            f["deletable"], f["protected_reason"] = True, None
    files.sort(key=lambda f: (not f["auto"], f["name"]), reverse=False)
    autos_first = [f for f in files if f["auto"]]
    autos_first.sort(key=lambda f: f["name"], reverse=True)
    return autos_first + [f for f in files if not f["auto"]]


def delete_backup(db_root: str, name: str) -> Dict[str, Any]:
    name = str(name or "")
    if os.path.basename(name) != name or not _AUTO_RE.match(name):
        raise ValueError("only automatic backups named grand_project_auto_YYYYMMDD.db can be deleted")
    entry = next((f for f in backup_list(db_root) if f["name"] == name), None)
    if entry is None:
        raise FileNotFoundError("%s is not in db_backups (already deleted?)" % name)
    if not entry["deletable"]:
        raise PermissionError("%s is protected: %s" % (name, entry["protected_reason"]))
    path = os.path.join(db_root, db.BACKUP_DIRNAME, name)
    size = entry["bytes"]
    os.remove(path)
    logged = False
    try:
        conn = db.get_connection(db_root)
        try:
            db.initialize_schema(conn)
            gp = conn.execute("SELECT id FROM grand_project WHERE id = ?", (DEFAULT_PROJECT_ID,)).fetchone() \
                or conn.execute("SELECT id FROM grand_project ORDER BY created_at LIMIT 1").fetchone()
        finally:
            conn.close()
        if gp is not None:
            db.log_timeline_event(db_root, gp[0], "BACKUP_DELETED_BY_USER", "db_backup", name,
                                  "User deleted automatic backup %s (%d bytes) from Settings; rule: %d newest "
                                  "and the largest protected (%s)." % (name, size, KEEP_NEWEST_BACKUPS, VERSION))
            logged = True
    except Exception:
        logged = False
    return {"deleted": name, "bytes": size, "logged": logged, "backups": backup_list(db_root)}


def delete_backup_json(db_root: str, name: str) -> str:
    try:
        return json.dumps(delete_backup(db_root, name), default=str)
    except Exception as e:                          # shown, never hidden
        return json.dumps({"error": "%s: %s" % (type(e).__name__, e)})
