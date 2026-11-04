"""
The Scientific Steward as a mentor (sm-v1, 2026-11-04).

The Steward reads what the project actually records and leads you, one step at
a time, until a job is scientifically finished, with nothing left unresolved:

  1 target      what we are looking for (Mound or tell switches on the Hillside rule)
  2 search      every tile of the area searched; failed tiles retried
  3 automatic   the Automatic run: library, sweep, land cover, terrain labels,
                review, Pass 2, review, satellite layers, provenance, trust, report
  4 pass2       every calib-v1 strong candidate refined (Pass 2 has a daily cap)
  5 layers      satellite layers saved for the leading candidates
  6 trust       the whole job judged: Trusted, Unverified or Corrupted, with a reason
  7 review      every leading candidate decided by you: Supported, Inconclusive or
                Rejected, with your reason
  8 report      a job report exported after the last change
  +  field      advice only: SUBSTANTIAL needs field data (GPR/ERT) at the leading
                candidate; shown, never counted against completion

Every suggestion is derived from stored rows and says why. The Steward only
suggests and points to the place; it never changes a status, review, trust,
confidence or evidence row by itself.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

VERSION = "sm-v1"
LEADING_BANDS = ("SUBSTANTIAL", "HIGH", "MODERATE")
STEP_NAMES = {"target": "Target", "search": "Search the area", "automatic": "Automatic run",
              "pass2": "Pass 2 refinement", "layers": "Satellite layers", "trust": "Job trust",
              "review": "Your review", "report": "Job report", "field": "Field data (advice)"}

# where each action takes you: (top tab, sub tab or None)
WHERE = {"run_job": ("INVESTIGATION", "Wide-area jobs"), "auto": ("INVESTIGATION", "Wide-area jobs"),
         "retry": ("INVESTIGATION", "Wide-area jobs"), "target": ("GRAND PROJECT", "Dashboard & jobs"),
         "trust": ("GRAND PROJECT", "Dashboard & jobs"), "review": ("REPORT & ARCHIVE", None),
         "report": ("REPORT & ARCHIVE", None), "layers": ("MISSION CONTROL", None),
         "field": ("DATA & EVIDENCE", None), "new_job": ("INVESTIGATION", "Wide-area jobs"),
         "single": ("GRAND PROJECT", "Single points"), "receive": (None, None)}


def _conn(root: str):
    import grand_project_db as db
    c = db.get_connection(root)
    db.initialize_schema(c)
    try:
        import grand_project_review as rv
        rv._connect(root).close()                 # makes sure the review tables exist
    except Exception:
        pass
    return c


def _has(conn, t: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone() is not None


def _step(key: str, state: str, text: str, action: Optional[str] = None, label: str = "",
          optional: bool = False) -> Dict[str, Any]:
    return {"key": key, "name": STEP_NAMES[key], "state": state, "text": text, "action": action,
            "action_label": label, "optional": optional}


def _latest_auto(root: str, job_id: str) -> Optional[Dict[str, Any]]:
    import auto_pipeline as ap
    try:
        runs = ap.list_auto_runs(root, job_id)
    except Exception:
        return None
    if not runs:
        return None
    try:
        return ap.auto_run_status(root, runs[0]["run_id"])
    except Exception:
        return None


def job_guide(root: str, job_id: str) -> Dict[str, Any]:
    """The Steward's path for one wide-area job: every step with its state (done / todo /
    working / advice), what to do next, and whether the job is complete."""
    conn = _conn(root)
    try:
        j = conn.execute("SELECT * FROM wide_area_search_job WHERE id = ?", (job_id,)).fetchone()
        if j is None:
            return {"error": "job %s not found" % job_id}
        j = dict(j)
        tiles = {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM wide_area_search_tile WHERE job_id = ? "
                                                  "GROUP BY status", (job_id,))}
        cands = [dict(r) for r in conn.execute(
            "SELECT c.id, c.status, c.score, UPPER(COALESCE(c.confidence_band, '')) AS band, c.confidence_numeric "
            "FROM candidate c JOIN wide_area_search_tile t ON t.investigation_id = c.investigation_id "
            "WHERE t.job_id = ?", (job_id,))]
        target = conn.execute("SELECT target, reason FROM job_target WHERE job_id = ? ORDER BY id DESC LIMIT 1",
                              (job_id,)).fetchone() if _has(conn, "job_target") else None
        trust = conn.execute("SELECT trust, reason, recorded_at FROM job_trust WHERE job_id = ? ORDER BY id DESC "
                             "LIMIT 1", (job_id,)).fetchone() if _has(conn, "job_trust") else None
        user_reviewed = set()
        last_review = None
        if _has(conn, "candidate_review") and cands:
            ids = [c["id"] for c in cands]
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                q = ",".join("?" * len(chunk))
                for r in conn.execute("SELECT candidate_id, MAX(reviewed_at) FROM candidate_review WHERE reviewed_by = "
                                      "'user' AND candidate_id IN (%s) GROUP BY candidate_id" % q, chunk):
                    user_reviewed.add(r[0])
                    last_review = max(last_review or "", r[1] or "")
        report = conn.execute("SELECT MAX(occurred_at) FROM timeline_event WHERE event_type = 'REPORT_EXPORTED' AND "
                              "related_entity_id = ?", (job_id,)).fetchone()[0]
        field = 0
        if _has(conn, "field_dataset") and cands:
            lead_ids = [c["id"] for c in cands if c["band"] in LEADING_BANDS][:500]
            if lead_ids:
                field = conn.execute("SELECT COUNT(*) FROM field_dataset WHERE candidate_id IN (%s)" % ",".join(
                    "?" * len(lead_ids)), lead_ids).fetchone()[0]
    finally:
        conn.close()

    auto = _latest_auto(root, job_id)
    steps: List[Dict[str, Any]] = []
    n_tiles = sum(tiles.values())
    pending = tiles.get("PENDING", 0) + tiles.get("RUNNING", 0)
    failed = tiles.get("FAILED", 0)
    lead = [c for c in cands if c["band"] in LEADING_BANDS and c["status"] != "REJECTED"]
    lead.sort(key=lambda c: (-(c["confidence_numeric"] or 0), -abs(c["score"] or 0)))
    auto_state = (auto or {}).get("state")
    step_of = {s["step"]: s for s in (auto or {}).get("steps", [])}

    # 1 target
    if target and target[0] != "NOT_SET":
        try:
            import grand_project_review as rv
            tl = rv.TARGET_LABELS.get(target[0], target[0])
        except Exception:
            tl = str(target[0]).replace("_", " ").lower()
        steps.append(_step("target", "done", "We are looking for: %s." % tl))
    else:
        steps.append(_step("target", "todo", "Before the review runs, tell me what we are looking for. \u201cMound or "
                           "tell\u201d switches on the Hillside rule, so natural slopes are not mistaken for mounds.",
                           "target", "Set the target"))
    # 2 search
    if n_tiles and pending == 0 and failed == 0:
        steps.append(_step("search", "done", "All %d tile%s searched." % (n_tiles, "" if n_tiles == 1 else "s")))
    elif failed and pending == 0:
        steps.append(_step("search", "todo", "%d tile%s failed. May I suggest retrying them? A job with failed tiles "
                           "cannot be marked Trusted." % (failed, "" if failed == 1 else "s"), "retry",
                           "Retry failed tiles"))
    elif auto_state == "RUNNING":
        steps.append(_step("search", "working", "%d of %d tiles still to search; the Automatic run is doing it." % (
            pending, n_tiles)))
    else:
        steps.append(_step("search", "todo", "%d of %d tiles still to search. The Automatic run below does this "
                           "for you, offline first." % (pending, n_tiles), "auto", "Start the Automatic run"))
    # 3 automatic
    if auto_state == "DONE":
        steps.append(_step("automatic", "done", "The Automatic run finished (%s)." % (
            (auto.get("created_at") or "")[:10])))
    elif auto_state == "RUNNING":
        paused = auto.get("paused_for_s") or 0
        steps.append(_step("automatic", "working", "The Automatic run is at \u201c%s\u201d%s. Let it carry on; open "
                           "the job and press Automatic run again if this computer was closed." % (
                               (auto.get("next_step") or "").replace("_", " "),
                               " (waiting %d min for the quota)" % (paused // 60) if paused else ""),
                           "auto", "Continue the Automatic run"))
    elif auto_state in ("FAILED", "CANCELLED"):
        steps.append(_step("automatic", "todo", "The last Automatic run %s. May I suggest starting it again? Every "
                           "step resumes where the data stopped." % auto_state.lower(), "auto",
                           "Start the Automatic run"))
    else:
        steps.append(_step("automatic", "todo", "At this stage, may I suggest the Automatic run? It fills the DEM "
                           "library, sweeps, adds land cover and terrain labels, reviews, refines with Pass 2, saves "
                           "satellite layers, checks provenance, judges trust and writes the report.", "auto",
                           "Start the Automatic run"))
    # 4 pass2
    p2 = (step_of.get("pass2") or {}).get("detail") or {}
    if auto_state != "DONE":
        steps.append(_step("pass2", "waiting", "Comes with the Automatic run."))
    elif p2.get("remaining_strong"):
        why = "the daily cap of live calls was reached" if p2.get("stopped_at_cap") else (
            p2.get("skipped") or "the per-run cap was reached")
        steps.append(_step("pass2", "todo", "%d strong candidate%s still not refined (%s). May I suggest another "
                           "Automatic run (tomorrow, if the cap was reached)?" % (
                               p2["remaining_strong"], "" if p2["remaining_strong"] == 1 else "s", why), "auto",
                           "Run again"))
    else:
        steps.append(_step("pass2", "done", "Every strong candidate refined (%s)." % (
            "%d refined" % p2.get("refined_total") if p2.get("refined_total") is not None else "none needed")))
    # 5 layers
    im = (step_of.get("images") or {}).get("detail") or {}
    if auto_state != "DONE":
        steps.append(_step("layers", "waiting", "Comes with the Automatic run."))
    elif im.get("remaining"):
        steps.append(_step("layers", "todo", "%d leading candidate%s still without satellite layers (%s). May I "
                           "suggest another Automatic run, or fetching them from the Final Image?" % (
                               im["remaining"], "" if im["remaining"] == 1 else "s",
                               im.get("note") or "cap per run"), "auto", "Run again"))
    else:
        steps.append(_step("layers", "done", "Satellite layers saved for the leading candidates."))
    # 6 trust
    tdet = (step_of.get("trust") or {}).get("detail") or {}
    if trust and trust[0] == "TRUSTED":
        steps.append(_step("trust", "done", "Job marked Trusted: %s" % (trust[1] or "")[:160]))
    elif trust and trust[0] == "CORRUPTED":
        steps.append(_step("trust", "done", "You marked this job Corrupted; its candidates count as rejected. "
                           "Reason: %s" % (trust[1] or "")[:160]))
    elif trust and trust[0] == "UNVERIFIED":
        steps.append(_step("trust", "done", "You marked this job Unverified: %s" % (trust[1] or "")[:160]))
    elif auto_state != "DONE":
        steps.append(_step("trust", "waiting", "Judged automatically at the end of the Automatic run."))
    else:
        reasons = tdet.get("reasons") or []
        steps.append(_step("trust", "todo", "The Automatic run could not mark this job Trusted%s. Please look at "
                           "these reasons and set the trust yourself, with your reason." % (
                               (": " + "; ".join(str(x) for x in reasons[:3])) if reasons else ""),
                           "trust", "Set the trust"))
    # 7 review
    open_lead = [c for c in lead if c["id"] not in user_reviewed and c["status"] in ("GENERATED", "INCONCLUSIVE")]
    if not cands and n_tiles and pending == 0:
        steps.append(_step("review", "done", "The search found no candidates: nothing to review."))
    elif not lead:
        steps.append(_step("review", "waiting" if auto_state != "DONE" else "done",
                           "No leading (Moderate or higher) candidate to decide yet." if auto_state != "DONE" else
                           "No candidate reached Moderate or higher; nothing left for you to decide."))
    elif open_lead:
        top = ", ".join(c["id"][:8] for c in open_lead[:3])
        steps.append(_step("review", "todo", "%d leading candidate%s still wait%s for your decision (first: %s). "
                           "Open each one, read the Steward and the debate, then mark it Supported, Inconclusive or "
                           "Rejected with your reason." % (len(open_lead), "" if len(open_lead) == 1 else "s",
                                                          "s" if len(open_lead) == 1 else "", top),
                           "review", "Review the candidates"))
    else:
        steps.append(_step("review", "done", "You have decided every leading candidate (%d)." % len(lead)))
    # 8 report
    marks = [last_review or "", (trust[2] if trust else "") or ""]
    marks += [(s.get("at") or "") for s in (auto or {}).get("steps", []) if s.get("step") != "report"]
    last_change = max(marks) if marks else ""
    if report and (not last_change or report >= last_change):
        steps.append(_step("report", "done", "Report exported %s, after the last change." % report[:16].replace(
            "T", " ")))
    elif report:
        steps.append(_step("report", "todo", "Things changed after the last report (%s). May I suggest exporting "
                           "it again so it matches the project?" % report[:16].replace("T", " "), "report",
                           "Generate the job report"))
    else:
        steps.append(_step("report", "todo" if auto_state == "DONE" or not n_tiles or pending == 0 else "waiting",
                           "Finally, export the job report so the result is kept and can be shared.", "report",
                           "Generate the job report"))
    # + field (advice)
    if lead and not field and lead[0]["band"] != "SUBSTANTIAL":
        steps.append(_step("field", "advice", "To go beyond %s, the leading candidate %s needs real field data: a "
                           "GPR or ERT survey there, imported in Data & Evidence." % (
                               lead[0]["band"].title(), lead[0]["id"][:8]), "field", "Open Data & Evidence",
                           optional=True))
    required = [s for s in steps if not s["optional"]]
    done = sum(1 for s in required if s["state"] == "done")
    nxt = next((s for s in required if s["state"] in ("todo", "working")), None)
    complete = done == len(required)
    if complete:
        say = ("This job is scientifically complete: every step is resolved. Well done." +
               (" One piece of advice remains: field data would let the evidence go further." if
                any(s["optional"] for s in steps) else ""))
    elif nxt and nxt["state"] == "working":
        say = nxt["text"]
    elif nxt:
        say = nxt["text"]
    else:
        say = "Waiting for the steps above."
    return {"version": VERSION, "job_id": job_id, "title": j.get("title"), "steps": steps, "done": done,
            "total": len(required), "complete": complete, "next": nxt, "say": say,
            "leading": [c["id"] for c in lead[:5]]}


def _greeting(now: Optional[datetime] = None) -> str:
    h = (now or datetime.now()).hour
    return "Good morning" if 5 <= h < 12 else "Good afternoon" if 12 <= h < 18 else "Good evening"


def project_guide(root: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The welcome at Mission Control: where the project stands, the job that needs you most,
    and the Steward's first suggestion."""
    conn = _conn(root)
    try:
        gp = conn.execute("SELECT id, name FROM grand_project ORDER BY created_at LIMIT 1").fetchone()
        jobs = [dict(r) for r in conn.execute("SELECT id, title, last_updated_at FROM wide_area_search_job "
                                              "ORDER BY last_updated_at DESC")]
        singles = conn.execute(
            "SELECT COUNT(*) FROM investigation i WHERE NOT EXISTS (SELECT 1 FROM wide_area_search_tile t WHERE "
            "t.investigation_id = i.id) AND EXISTS (SELECT 1 FROM candidate c WHERE c.investigation_id = i.id)"
        ).fetchone()[0]
    finally:
        conn.close()
    hello = _greeting(now) + ". I am the Scientific Steward."
    if gp is None:
        return {"version": VERSION, "hello": hello, "say": "There is no project on this computer yet. May I suggest "
                "receiving it from the phone first?", "action": "receive", "action_label": "Receive from phone",
                "jobs": [], "complete": 0, "open": 0}
    guides = []
    for j in jobs:
        try:
            g = job_guide(root, j["id"])
        except Exception as e:                       # shown, never hidden
            g = {"job_id": j["id"], "title": j["title"], "error": "%s: %s" % (type(e).__name__, e)}
        guides.append(g)
    ok = [g for g in guides if "error" not in g]
    complete = [g for g in ok if g["complete"]]
    open_ = [g for g in ok if not g["complete"]]
    # the job that needs you most: furthest along but not finished (closest to completion), then newest
    open_.sort(key=lambda g: (-(g["done"] / float(g["total"] or 1))))
    focus = open_[0] if open_ else None
    if focus:
        say = "Of %d job%s, %d %s complete. The one closest to the finish is \u201c%s\u201d (%d of %d steps). %s" % (
            len(ok), "" if len(ok) == 1 else "s", len(complete), "is" if len(complete) == 1 else "are",
            focus["title"], focus["done"], focus["total"], focus["say"])
        action = (focus.get("next") or {}).get("action")
        label = (focus.get("next") or {}).get("action_label")
    elif ok:
        say = "All %d job%s are scientifically complete. May I suggest a new wide-area job, or a single point " \
              "where history points?" % (len(ok), "" if len(ok) == 1 else "s")
        action, label = "new_job", "Start a new job"
    else:
        say = "No wide-area job yet. May I suggest starting one over the area you want to study?"
        action, label = "new_job", "Start a new job"
    if singles:
        say += " Also, %d single-point investigation%s with candidates %s not yet a job; turning %s into one-tile " \
               "jobs lets me guide %s to the end too." % (singles, "" if singles == 1 else "s",
                                                          "is" if singles == 1 else "are",
                                                          "it" if singles == 1 else "them",
                                                          "it" if singles == 1 else "them")
    return {"version": VERSION, "hello": hello, "say": say, "action": action, "action_label": label,
            "focus_job": focus["job_id"] if focus else None, "jobs": guides, "complete": len(complete),
            "open": len(open_), "singles": singles}


# ---------------------------------------------------------------- u3d: one candidate, everywhere
CANDIDATE_STEPS = {"rated": "Steward rating", "layers": "Satellite layers", "debate": "AI debate",
                   "review": "Your decision", "job": "Its job", "field": "Field data (advice)"}
NEEDED_LAYERS = ("TRUE_COLOR", "NDVI", "THERMAL")      # radar is a bonus, never required
WHERE.update({"final_image": (None, None), "review_cand": ("REPORT & ARCHIVE", None),
              "rerun_point": ("INVESTIGATION", "Single point")})


def _cstep(key, state, text, action=None, label="", optional=False):
    return {"key": key, "name": CANDIDATE_STEPS[key], "state": state, "text": text, "action": action,
            "action_label": label, "optional": optional}


def _layers_covering(root: str, lat: float, lon: float, half_m: float = 900.0) -> Dict[str, bool]:
    import math
    import sat_image as si
    dlat = half_m / 111320.0
    dlon = half_m / (111320.0 * max(0.1, math.cos(math.radians(lat))))
    b = {"west": lon - dlon, "east": lon + dlon, "south": lat - dlat, "north": lat + dlat}
    out = {}
    for p in si.LAYER_ORDER:
        try:
            out[p] = si.find_saved(root, p, b) is not None
        except Exception:
            out[p] = False
    return out


def candidate_guide(root: str, cid: str) -> Dict[str, Any]:
    """The Steward's path for one candidate: rated, layers saved, debated, decided by you,
    and where its job stands. The same guidance wherever the candidate is opened."""
    conn = _conn(root)
    try:
        c = conn.execute("SELECT c.id, c.lat, c.lon, c.status, UPPER(COALESCE(c.confidence_band, '')) AS band, "
                         "c.confidence_numeric, c.investigation_id, t.job_id, j.title FROM candidate c "
                         "LEFT JOIN wide_area_search_tile t ON t.investigation_id = c.investigation_id "
                         "LEFT JOIN wide_area_search_job j ON j.id = t.job_id WHERE c.id = ?", (cid,)).fetchone()
        if c is None:
            return {"error": "candidate %s not found" % cid}
        c = dict(c)
        reviewed = conn.execute("SELECT new_status, reason FROM candidate_review WHERE candidate_id = ? AND "
                                "reviewed_by = 'user' ORDER BY id DESC LIMIT 1", (cid,)).fetchone() \
            if _has(conn, "candidate_review") else None
        field = conn.execute("SELECT COUNT(*) FROM field_dataset WHERE candidate_id = ?", (cid,)).fetchone()[0] \
            if _has(conn, "field_dataset") else 0
    finally:
        conn.close()
    try:
        from ariyan_win import workstation
        deb = (workstation.candidate_detail(root, cid) or {}).get("debate")
    except Exception:
        deb = None
    band = c["band"] or "NOT_RATED"
    steps: List[Dict[str, Any]] = []
    single = not c["job_id"]
    # rated
    if band not in ("", "NOT_RATED", "NO_DATA"):
        steps.append(_cstep("rated", "done", "The Steward rates it %s%s." % (
            band.title(), "" if c["confidence_numeric"] is None else " %.2f" % c["confidence_numeric"])))
    elif single:
        steps.append(_cstep("rated", "todo", "Not rated yet. May I suggest running its investigation again so the "
                            "Steward can rate it?", "rerun_point", "Open single-point investigation"))
    else:
        steps.append(_cstep("rated", "todo", "Not rated yet. The review step of its job\u2019s Automatic run rates "
                            "it. May I suggest the Automatic run?", "auto", "Automatic run of its job"))
    # layers
    have = _layers_covering(root, c["lat"], c["lon"])
    need_missing = [p for p in NEEDED_LAYERS if not have.get(p)]
    import sat_image as si
    names = lambda ps: ", ".join(si.PRODUCTS[p]["label"].split(" (")[0] for p in ps)     # noqa: E731
    n_have = sum(1 for v in have.values() if v)
    if not need_missing:
        steps.append(_cstep("layers", "done", "%d of %d layers saved here (true colour, NDVI and thermal "
                            "included)." % (n_have, len(have))))
    else:
        steps.append(_cstep("layers", "todo", "Missing here: %s. May I suggest opening its Final Image and fetching "
                            "them from Satellite? Each uses the Copernicus quota once, then stays saved." % names(
                                need_missing), "final_image", "Open its Final Image"))
    # debate
    if deb:
        syn = deb.get("synthesis") or {}
        steps.append(_cstep("debate", "done", "Debate stored: %s." % AGREE.get(syn.get("agreement_level"),
                                                                                 "recorded")))
    else:
        steps.append(_cstep("debate", "advice", "No debate stored (debates are kept from investigations run since "
                            "2026-10-31). Re-running its investigation would add one.",
                            "rerun_point" if single else None, "Open single-point investigation" if single else "",
                            optional=True))
    # review
    if reviewed:
        steps.append(_cstep("review", "done", "You decided: %s \u2014 %s" % (
            str(reviewed[0]).title(), (reviewed[1] or "")[:120])))
    elif band in LEADING_BANDS or single:
        steps.append(_cstep("review", "todo", "Read the Steward and the debate, then decide: Supported, "
                            "Inconclusive or Rejected, with your reason.", "review_cand", "Decide on it"))
    else:
        steps.append(_cstep("review", "advice", "Below Moderate: your decision is welcome but not needed for the "
                            "job to be complete.", "review_cand", "Decide on it", optional=True))
    # job
    if single:
        steps.append(_cstep("job", "advice", "It comes from a single-point investigation. Turning it into a one-tile "
                            "job lets the Automatic run, trust and report cover it.", "single",
                            "Grand Project \u2192 Single points", optional=True))
    else:
        jg = job_guide(root, c["job_id"])
        if "error" in jg:
            steps.append(_cstep("job", "advice", jg["error"], optional=True))
        elif jg["complete"]:
            steps.append(_cstep("job", "done", "Its job \u201c%s\u201d is complete." % jg["title"]))
        else:
            n = jg.get("next") or {}
            steps.append(_cstep("job", "todo", "Its job \u201c%s\u201d is at %d of %d. Next: %s" % (
                jg["title"], jg["done"], jg["total"], n.get("text") or "waiting"), n.get("action"),
                n.get("action_label") or ""))
    if band not in ("SUBSTANTIAL",) and not field and band in LEADING_BANDS:
        steps.append(_cstep("field", "advice", "To go beyond %s it needs field data: GPR or ERT here, imported in "
                            "Data & Evidence." % band.title(), "field", "Open Data & Evidence", optional=True))
    req = [s for s in steps if not s["optional"]]
    done = sum(1 for s in req if s["state"] == "done")
    nxt = next((s for s in req if s["state"] == "todo"), None)
    complete = done == len(req)
    say = ("Candidate %s is fully worked: rated, layered and decided%s." % (
        cid[:8], ", and its job is complete" if not single else "") if complete else nxt["text"])
    return {"version": VERSION, "kind": "candidate", "id": cid, "title": "Candidate %s" % cid[:8],
            "job_id": c["job_id"], "steps": steps, "done": done, "total": len(req), "complete": complete,
            "next": nxt, "say": say}


AGREE = {"LEADING_INTERPRETATION": "a leading interpretation", "CONTESTED": "contested", "WEAK_SIGNAL": "a weak signal",
         "NO_DATA": "no data"}

TAB_HINTS = {
    "MISSION CONTROL": "Pick a candidate anywhere on this page and I will tell you what it still needs.",
    "INVESTIGATION": "Choose a job, or run a single point. I will lead it step by step to a finished, reported result.",
    "DATA & EVIDENCE": "Field data (GPR, ERT) is what lets a candidate go beyond Moderate. Import it here for the "
                       "leading candidate of a job.",
    "AI DEBATE STUDIO": "Each stored debate shows four perspectives. Pick one; I will say what its candidate still needs.",
    "VISUALIZATION": "The Final Image is where missing satellite layers are fetched; each is saved after one fetch.",
    "GRAND PROJECT": "Search a candidate, read its group and interpretation; I will guide what is left for it.",
    "HISTORICAL RESEARCH": "History points to places; a promising place becomes a single point, then a one-tile job I "
                           "can lead to the end.",
    "ANALYSIS & MODELS": "These are the rules the laboratory applies. Nothing here changes a result by itself.",
    "REPORT & ARCHIVE": "Decide every leading candidate with your reason, then export the job report.",
}
