"""
auto_pipeline.py -- ap-v1 (2026-10-05). Total automation of one Wide-Area
Search job, as a resumable step machine.

STEPS (in order; each is idempotent, so re-running a step after a crash
or a pause continues where the real data says it stopped):
  1 library     fill the offline DEM library (srtm_library) for the job
                bbox: SRTMGL1 + COP30 1-degree tiles, + spot-check
  2 sweep       Pass 1, DEM-only, offline-first, COP30 (resumes by tile)
  3 land_cover  WorldCover flags (needs internet; retried, then skipped)
  4 terrain     F3 terrain labels
  5 review1     R1 auto-review (Hillside rule included)
  6 pass2       Pass 2 on every calib-v1 STRONG, non-REJECTED, unflagged,
                not-yet-refined candidate, strongest first, in batches;
                library-first, so 0 live DEM calls per candidate when the
                tiles are present. Rolling 24 h cap: 40 live calls.
  7 review2     auto-review again (Pass 2 results feed Supported etc.)
  8 provenance  provenance check of the whole job (read-only)
  9 trust       AUTOMATIC trust decision (rules below)
 10 report      HTML + CSV report, top 50, rounded coordinates

AUTOMATIC TRUST: TRUSTED only if ALL hold --
  provenance VERIFIED (every candidate) AND 0 failed tiles AND the sweep's
  offline guard never paused in this run AND no Pass 2 candidate failed
  AND every library spot-check that ran was IDENTICAL.
  Otherwise nothing is marked and every reason is recorded.
  A trust mark the USER set is never overwritten; automation never marks
  CORRUPTED. Automatic marks carry the reason prefix AUTO_PREFIX.

STORAGE (append-only, same database):
  auto_run(id, job_id, grand_project_id, options_json, created_at)
  auto_run_event(id, run_id, step, status, detail_json, recorded_at)
  status: STARTED | PROGRESS | DONE | SKIPPED | PAUSED | FAILED |
          CANCELLED | FINISHED
The run's state is DERIVED from its events; nothing is ever updated.

ENTRY POINTS (JSON in/out, never raise):
  start_auto_run_json(root, job_ref, options_json)
  run_slice_json(root, run_ref, api_key, ndvi_id, ndvi_secret, budget_s)
      -> {"state": RUNNING|PAUSED|DONE|FAILED|CANCELLED,
          "retry_after_s", "next_step", "message"}
  auto_run_status_json(root, run_ref)
  list_auto_runs_json(root, job_ref)
  cancel_auto_run_json(root, run_ref, reason)
"""
import json
import time
import traceback
import uuid

import grand_project_db as db
import grand_project_review as review

VERSION = "ap-v1"
AUTO_PREFIX = "[auto ap-v1]"
STEPS = ["library", "sweep", "land_cover", "terrain", "review1",
         "pass2", "review2", "provenance", "trust", "report"]
DEFAULT_OPTIONS = {
    "sweep_demtype": "COP30",
    "pass2_demtype": "SRTMGL1",
    "pass2_batch": 3,          # candidates per Pass 2 call
    "pass2_max": 50,           # cap on Pass 2 candidates per run
    "pass2_min_budget": 10,    # live calls that must be left to start a batch
    "library_max_calls": 10,
    "report_top_n": 50,
}
MAX_STEP_FAILURES = 3          # consecutive FAILED on one step -> run FAILED
FAIL_RETRY_S = 15 * 60
LAND_COVER_RETRY_S = 30 * 60
COPERNICUS_PAUSE_S = 30 * 60
NO_LIVE_DEM_PAUSE_S = 60 * 60


class PauseStep(Exception):
    def __init__(self, reason, retry_after_s, detail=None):
        super().__init__(reason)
        self.reason, self.retry_after_s, self.detail = reason, int(retry_after_s), detail or {}


class StepContinue(Exception):
    """The step made progress but has more to do (out of slice time)."""
    def __init__(self, detail):
        super().__init__("continue")
        self.detail = detail


# ---------------------------------------------------------------- storage

def _ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS auto_run (
        id TEXT PRIMARY KEY, job_id TEXT NOT NULL, grand_project_id TEXT NOT NULL,
        options_json TEXT NOT NULL, created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS auto_run_event (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
        step TEXT NOT NULL, status TEXT NOT NULL, detail_json TEXT,
        recorded_at TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_auto_run_event_run ON auto_run_event(run_id)")


def _conn(root):
    conn = review._connect(root)
    _ensure(conn)
    return conn


def _event(root, run_id, step, status, detail=None):
    conn = _conn(root)
    try:
        with conn:
            conn.execute(
                "INSERT INTO auto_run_event (run_id, step, status, detail_json, recorded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_id, step, status, json.dumps(detail or {}, default=str), db._now_iso()))
    finally:
        conn.close()


def _run_row(conn, run_ref):
    ref = str(run_ref or "").strip()
    rows = conn.execute("SELECT * FROM auto_run WHERE id LIKE ?", (ref + "%",)).fetchall()
    if len(rows) != 1:
        raise ValueError(f"auto run {ref!r}: {'not found' if not rows else 'ambiguous'}")
    r = dict(rows[0])
    r["options"] = json.loads(r["options_json"])
    return r


def _events(conn, run_id):
    rows = conn.execute("SELECT * FROM auto_run_event WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["detail"] = json.loads(d.pop("detail_json") or "{}")
        out.append(d)
    return out


def _state(events):
    """Derive (state, next_step, paused_until_epoch, consecutive_failures)."""
    done = {e["step"] for e in events if e["status"] in ("DONE", "SKIPPED")}
    if any(e["status"] == "CANCELLED" for e in events):
        return "CANCELLED", None, 0, 0
    if any(e["step"] == "run" and e["status"] == "FAILED" for e in events):
        return "FAILED", None, 0, 0
    nxt = next((s for s in STEPS if s not in done), None)
    if nxt is None:
        return "DONE", None, 0, 0
    fails, paused_until = 0, 0.0
    for e in reversed([e for e in events if e["step"] == nxt]):
        if e["status"] == "FAILED":
            fails += 1
        elif e["status"] in ("STARTED", "PROGRESS"):
            continue
        else:
            break
    last = [e for e in events if e["step"] == nxt and e["status"] in ("PAUSED", "FAILED")]
    if last:
        paused_until = float(last[-1]["detail"].get("retry_at", 0) or 0)
    return "RUNNING", nxt, paused_until, fails


# ---------------------------------------------------------------- steps

def _step_library(root, run, creds, deadline):
    import dem_library_mobile as dlm
    plan = json.loads(dlm.dem_library_plan_json(root, run["job_id"]))
    if plan.get("error"):
        raise RuntimeError(plan["error"])
    if plan["missing_total"] == 0:
        return {"note": "all library tiles already present", "plan": plan["demtypes"]}
    if not creds["api_key"]:
        return {"skipped": "no OpenTopography API key; Pass 2 will fetch live", "missing": plan["missing_total"]}
    r = json.loads(dlm.fill_dem_library_json(root, run["job_id"], creds["api_key"],
                                            run["options"]["library_max_calls"], True))
    if r.get("error"):
        raise RuntimeError(r["error"])
    if r.get("stopped") == "budget":
        raise PauseStep("live-call budget used up while filling the library",
                        _budget_wait(root), {"fill": _slim(r)})
    return {"fill": _slim(r)}


def _slim(r):
    return {k: r.get(k) for k in ("calls", "downloaded", "failed", "stopped", "spot_checks", "seconds")}


def _step_sweep(root, run, creds, deadline):
    import wide_area_search_mobile as was
    job = db.get_wide_area_search_job(root, run["job_id"])
    if job.get("status") in ("COMPLETE", "COMPLETE_WITH_ERRORS"):
        prog = db.get_wide_area_search_job_progress(root, run["job_id"])
        if prog.get("pending", 0) == 0:
            return {"note": "sweep already complete", "progress": prog}
    payload = json.loads(was.run_wide_area_search_job(
        root, run["job_id"], api_key=creds["api_key"], demtype=run["options"]["sweep_demtype"],
        dem_only=True, dem_offline_first=True))
    if payload.get("paused"):
        raise PauseStep("sweep: offline guard paused -- " + str(payload.get("pause_reason")),
                        NO_LIVE_DEM_PAUSE_S, {"sweep": payload, "offline_guard_paused": True})
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    return {"sweep": {k: payload.get(k) for k in ("total", "done", "failed", "pending",
                                                    "dem_only", "dem_offline_first")}}


def _step_land_cover(root, run, creds, deadline):
    import land_cover_flags as lc
    r = lc.ensure_job_land_cover(root, run["job_id"])
    if r.get("problem"):
        tries = sum(1 for e in run["_events"] if e["step"] == "land_cover" and e["status"] == "PAUSED")
        if tries < 2:
            raise PauseStep("land cover: " + str(r["problem"])[:200], LAND_COVER_RETRY_S, {"result": r})
        return {"skipped_after_retries": str(r["problem"])[:300], "result": r}
    return {"result": r}


def _step_terrain(root, run, creds, deadline):
    import terrain_context_labels as tcl
    r = tcl.label_job(root, run["job_id"])
    return {"result": {k: v for k, v in r.items() if not isinstance(v, (list, dict))}}


def _step_review(root, run, creds, deadline):
    return {"result": review.auto_review_project(root, run["grand_project_id"])}


def _budget_wait(root):
    import dem_library_mobile as dlm
    calls = dlm._recent_calls(root)
    if not calls:
        return 600
    return max(600, int(min(c["t"] for c in calls) + dlm.WINDOW_S - time.time()) + 60)


def _pass2_queue(root, run):
    import calib_profile
    import grand_project_refinement as gpr
    profile = calib_profile.active_profile(root)
    if profile is None:
        return None, "no active calibration profile (calib-v1 not adopted)"
    sel = gpr.select_refinement_candidates(root, run["job_id"], 100000, skip_flagged=True)
    conn = _conn(root)
    try:
        status = {r["id"]: r["status"] for r in conn.execute(
            "SELECT id, status FROM candidate WHERE grand_project_id = ?", (run["grand_project_id"],))}
    finally:
        conn.close()
    q = [c for c in sel["selected"]
         if calib_profile.is_strong(c.get("score"), profile)
         and str(status.get(c["id"]) or "").upper() != "REJECTED"]
    return q, None


def _step_pass2(root, run, creds, deadline):
    import dem_library_mobile as dlm
    import grand_project_refinement as gpr
    opts = run["options"]
    prior = [e for e in run["_events"] if e["step"] == "pass2" and e["status"] == "PROGRESS"]
    done_total = sum(e["detail"].get("attempted", 0) for e in prior)
    failed_total = sum(e["detail"].get("failed", 0) for e in prior)
    batches = 0
    while True:
        queue, why = _pass2_queue(root, run)
        if queue is None:
            return {"skipped": why}
        room = opts["pass2_max"] - done_total
        if not queue or room <= 0:
            return {"refined_total": done_total, "failed_total": failed_total,
                    "remaining_strong": len(queue),
                    "stopped_at_cap": bool(queue) and room <= 0}
        if not creds["api_key"]:
            return {"skipped": "no OpenTopography API key", "remaining_strong": len(queue)}
        if dlm.budget_left(root) < opts["pass2_min_budget"]:
            raise PauseStep("live DEM budget (rolling 24 h) too low for another batch",
                            _budget_wait(root), {"budget_left": dlm.budget_left(root)})
        if batches and time.time() > deadline:
            raise StepContinue({"refined_total": done_total, "remaining_strong": len(queue)})
        batch = queue[:min(opts["pass2_batch"], room)]
        r = gpr.run_selected_refinement(
            root, run["job_id"], [c["id"] for c in batch], api_key=creds["api_key"],
            demtype=opts["pass2_demtype"], ndvi_client_id=creds["ndvi_id"],
            ndvi_client_secret=creds["ndvi_secret"], require_live_dem=True)
        lib = r.get("dem_library") or {}
        live = sum((lib.get("library_misses") or {}).values())
        for _ in range(live):
            dlm._record_call(root, "pass2")
        detail = {"batch": [c["id"][:8] for c in batch], "attempted": r.get("attempted", 0),
                  "refined": r.get("refined"), "reproduced": r.get("reproduced"),
                  "failed": r.get("failed", 0), "library_cuts": lib.get("library_cuts", 0),
                  "live_dem_calls": live, "seconds": r.get("seconds")}
        _event(root, run["id"], "pass2", "PROGRESS", detail)
        done_total += detail["attempted"]
        failed_total += detail["failed"]
        batches += 1
        if r.get("stopped_no_live_dem"):
            raise PauseStep("Pass 2 stopped: live DEM unavailable -- " + str(r["stopped_no_live_dem"])[:200],
                            NO_LIVE_DEM_PAUSE_S)
        if (r.get("copernicus_throttle") or {}).get("trips", 0):
            raise PauseStep("Copernicus throttling (circuit breaker tripped)", COPERNICUS_PAUSE_S)
        if detail["attempted"] == 0:
            return {"refined_total": done_total, "failed_total": failed_total,
                    "note": "batch attempted nothing; stopping Pass 2"}


def _step_provenance(root, run, creds, deadline):
    import provenance_check as pc
    r = pc.check_job(root, run["job_id"])
    verified = r["candidates"] > 0 and r["candidates_verified"] == r["candidates"]
    return {"verdict": "VERIFIED" if verified else "NOT VERIFIED",
            "candidates": r["candidates"], "candidates_verified": r["candidates_verified"],
            "evidence_rows": r.get("evidence_rows"), "evidence_rows_verified": r.get("evidence_rows_verified")}


def _last_detail(events, step):
    d = [e for e in events if e["step"] == step and e["status"] in ("DONE", "SKIPPED")]
    return d[-1]["detail"] if d else {}


def trust_decision(events, failed_tiles):
    """Pure function: (mark TRUSTED?, reasons it fell short)."""
    reasons = []
    prov = _last_detail(events, "provenance")
    if prov.get("verdict") != "VERIFIED":
        reasons.append(f"provenance {prov.get('verdict', 'not run')} "
                       f"({prov.get('candidates_verified')}/{prov.get('candidates')})")
    if failed_tiles:
        reasons.append(f"{failed_tiles} failed tile(s)")
    if any(e["step"] == "sweep" and e["detail"].get("offline_guard_paused") for e in events):
        reasons.append("sweep offline guard paused during this run")
    p2_failed = sum(e["detail"].get("failed", 0) for e in events
                    if e["step"] == "pass2" and e["status"] == "PROGRESS")
    if p2_failed:
        reasons.append(f"{p2_failed} Pass 2 candidate(s) failed")
    for e in events:
        if e["step"] == "library":
            for c in ((e["detail"].get("fill") or {}).get("spot_checks") or []):
                if "skipped" not in c and not c.get("ok"):
                    reasons.append(f"library spot-check {c.get('demtype')} not identical")
    return (not reasons), reasons


def _step_trust(root, run, creds, deadline):
    conn = _conn(root)
    try:
        cur = review._current_job_trust(conn).get(run["job_id"])
    finally:
        conn.close()
    if cur and not str(cur.get("reason") or "").startswith(AUTO_PREFIX):
        return {"decision": "kept", "note": f"user-set trust {cur['trust']} kept (never overwritten)"}
    failed = db.get_wide_area_search_job_progress(root, run["job_id"]).get("failed", 0)
    ok, reasons = trust_decision(run["_events"], failed)
    if ok:
        if cur and cur["trust"] == "TRUSTED":
            return {"decision": "TRUSTED", "note": "already auto-trusted"}
        review.set_job_trust(root, run["job_id"], "TRUSTED",
                             f"{AUTO_PREFIX} run {run['id'][:8]}: provenance VERIFIED, 0 failed tiles, "
                             f"no offline-guard pause, no Pass 2 failures")
        return {"decision": "TRUSTED"}
    return {"decision": "not marked", "reasons": reasons}


def _step_report(root, run, creds, deadline):
    import grand_project_report as rep
    r = rep.export_job_report(root, run["grand_project_id"], run["job_id"],
                              run["options"]["report_top_n"], False)
    return {k: r.get(k) for k in ("html_path", "csv_path", "html_md5", "csv_md5",
                                  "rows_shown", "timeline_event_logged")}


_IMPL = {"library": _step_library, "sweep": _step_sweep, "land_cover": _step_land_cover,
         "terrain": _step_terrain, "review1": _step_review, "pass2": _step_pass2,
         "review2": _step_review, "provenance": _step_provenance, "trust": _step_trust,
         "report": _step_report}


# ---------------------------------------------------------------- API

def start_auto_run(root, job_ref, options=None):
    conn = _conn(root)
    try:
        job_id = review._resolve_id(conn, "wide_area_search_job", job_ref)
        gp = conn.execute("SELECT grand_project_id FROM wide_area_search_job WHERE id = ?",
                          (job_id,)).fetchone()["grand_project_id"]
        for r in conn.execute("SELECT id FROM auto_run WHERE job_id = ?", (job_id,)).fetchall():
            st = _state(_events(conn, r["id"]))[0]
            if st == "RUNNING":
                raise ValueError(f"auto run {r['id'][:8]} for this job is still active")
        opts = dict(DEFAULT_OPTIONS)
        opts.update(options or {})
        rid = uuid.uuid4().hex
        with conn:
            conn.execute("INSERT INTO auto_run VALUES (?, ?, ?, ?, ?)",
                         (rid, job_id, gp, json.dumps(opts), db._now_iso()))
    finally:
        conn.close()
    _event(root, rid, "run", "STARTED", {"version": VERSION, "options": opts})
    db.log_timeline_event(root, gp, "AUTO_RUN_STARTED", "wide_area_search_job", job_id,
                          f"{AUTO_PREFIX} automatic run {rid[:8]} started")
    return {"run_id": rid, "job_id": job_id}


def run_slice(root, run_ref, api_key="", ndvi_id="", ndvi_secret="", budget_s=540):
    deadline = time.time() + float(budget_s)
    creds = {"api_key": api_key or "", "ndvi_id": ndvi_id or "", "ndvi_secret": ndvi_secret or ""}
    conn = _conn(root)
    try:
        run = _run_row(conn, run_ref)
    finally:
        conn.close()
    ran = 0   # every slice does at least one step, however small budget_s is
    while True:
        conn = _conn(root)
        try:
            run["_events"] = _events(conn, run["id"])
        finally:
            conn.close()
        state, step, paused_until, fails = _state(run["_events"])
        if state != "RUNNING":
            return {"state": state, "run_id": run["id"], "next_step": None, "retry_after_s": 0}
        if paused_until > time.time():
            return {"state": "PAUSED", "run_id": run["id"], "next_step": step,
                    "retry_after_s": int(paused_until - time.time()) + 1}
        if ran and time.time() > deadline:
            return {"state": "RUNNING", "run_id": run["id"], "next_step": step, "retry_after_s": 0}
        ran += 1
        _event(root, run["id"], step, "STARTED")
        try:
            detail = _IMPL[step](root, run, creds, deadline)
            status = "SKIPPED" if "skipped" in detail else "DONE"
            _event(root, run["id"], step, status, detail)
            if step == STEPS[-1]:
                _event(root, run["id"], "run", "FINISHED", {})
                db.log_timeline_event(root, run["grand_project_id"], "AUTO_RUN_FINISHED",
                                      "wide_area_search_job", run["job_id"],
                                      f"{AUTO_PREFIX} automatic run {run['id'][:8]} finished")
        except StepContinue as c:
            return {"state": "RUNNING", "run_id": run["id"], "next_step": step,
                    "retry_after_s": 0, "detail": c.detail}
        except PauseStep as p:
            d = dict(p.detail)
            d.update({"reason": p.reason, "retry_at": time.time() + p.retry_after_s})
            _event(root, run["id"], step, "PAUSED", d)
            return {"state": "PAUSED", "run_id": run["id"], "next_step": step,
                    "retry_after_s": p.retry_after_s, "message": p.reason}
        except Exception as ex:
            msg = f"{type(ex).__name__}: {ex}"[:500]
            _event(root, run["id"], step, "FAILED",
                   {"error": msg, "trace": traceback.format_exc()[-1200:],
                    "retry_at": time.time() + FAIL_RETRY_S})
            if fails + 1 >= MAX_STEP_FAILURES:
                _event(root, run["id"], "run", "FAILED",
                       {"error": f"step {step} failed {MAX_STEP_FAILURES} times in a row: {msg}"})
                return {"state": "FAILED", "run_id": run["id"], "next_step": step, "message": msg}
            return {"state": "PAUSED", "run_id": run["id"], "next_step": step,
                    "retry_after_s": FAIL_RETRY_S, "message": msg}


def auto_run_status(root, run_ref):
    conn = _conn(root)
    try:
        run = _run_row(conn, run_ref)
        evs = _events(conn, run["id"])
    finally:
        conn.close()
    state, step, paused_until, fails = _state(evs)
    steps = []
    for s in STEPS:
        last = [e for e in evs if e["step"] == s and e["status"] != "STARTED"]
        steps.append({"step": s, "status": last[-1]["status"] if last else "PENDING",
                      "detail": last[-1]["detail"] if last else {},
                      "at": last[-1]["recorded_at"] if last else None})
    return {"run_id": run["id"], "job_id": run["job_id"], "created_at": run["created_at"],
            "state": state, "next_step": step,
            "paused_for_s": max(0, int(paused_until - time.time())) if paused_until else 0,
            "consecutive_failures": fails, "steps": steps, "events": len(evs),
            "options": run["options"]}


def cancel_auto_run(root, run_ref, reason=""):
    conn = _conn(root)
    try:
        run = _run_row(conn, run_ref)
    finally:
        conn.close()
    _event(root, run["id"], "run", "CANCELLED", {"reason": str(reason)[:300]})
    return {"run_id": run["id"], "state": "CANCELLED"}


def list_auto_runs(root, job_ref):
    conn = _conn(root)
    try:
        job_id = review._resolve_id(conn, "wide_area_search_job", job_ref)
        rows = conn.execute("SELECT id, created_at FROM auto_run WHERE job_id = ? ORDER BY created_at DESC",
                            (job_id,)).fetchall()
        return [{"run_id": r["id"], "created_at": r["created_at"],
                 "state": _state(_events(conn, r["id"]))[0]} for r in rows]
    finally:
        conn.close()


def _wrap(fn, *a, **k):
    try:
        return json.dumps(fn(*a, **k), default=str)
    except Exception as ex:
        return json.dumps({"error": f"{type(ex).__name__}: {ex}"})


def start_auto_run_json(root, job_ref, options_json=""):
    return _wrap(start_auto_run, root, job_ref, json.loads(options_json) if options_json else None)


def run_slice_json(root, run_ref, api_key="", ndvi_id="", ndvi_secret="", budget_s=540):
    return _wrap(run_slice, root, run_ref, api_key, ndvi_id, ndvi_secret, float(budget_s))


def auto_run_status_json(root, run_ref):
    return _wrap(auto_run_status, root, run_ref)


def list_auto_runs_json(root, job_ref):
    return _wrap(list_auto_runs, root, job_ref)


def cancel_auto_run_json(root, run_ref, reason=""):
    return _wrap(cancel_auto_run, root, run_ref, reason)
