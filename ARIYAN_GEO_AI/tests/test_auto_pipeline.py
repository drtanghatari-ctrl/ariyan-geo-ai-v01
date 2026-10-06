"""ap-v1: auto_pipeline step machine with every network step mocked."""
import json
import random

import pytest

import auto_pipeline as ap
import calib_profile
import dem_library_mobile as dlm
import grand_project_db as db
import grand_project_refinement as gpr
import grand_project_report as rep
import grand_project_review as review
import land_cover_flags as lc
import provenance_check as pc
import terrain_context_labels as tcl
import wide_area_search_mobile as was


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = str(tmp_path)
    gp = db.create_grand_project(root, "t")
    centers = [{"tile_index": i, "center_lat": 32.1 + i * 0.01, "center_lon": 48.3} for i in range(3)]
    jid = db.create_wide_area_search_job(root, gp, "auto", "MANUAL_BBOX", 32.1, 32.13, 48.3, 48.31, 1000, centers)
    random.seed(1)
    for t in db.list_tiles_for_job(root, jid):
        inv = db.create_investigation(root, gp, "", "", {})
        db.mark_tile_done(root, t["id"], inv)
        for k in range(6):
            db.create_candidate(root, gp, inv, t["center_lat"] + k * 0.002, t["center_lon"] + k * 0.002,
                                score=random.choice([3, 6, 9, 12, 15]))
    mode = {"sweep_pause": 0, "lc_problem": 0, "p2_fail": 0, "prov_ok": True, "batches": []}
    monkeypatch.setattr(dlm, "dem_library_plan_json", lambda r, j, *a: json.dumps({"missing_total": 0, "demtypes": {}}))

    def sweep(r, j, **k):
        assert k["dem_only"] and k["dem_offline_first"] and k["demtype"] == "COP30"
        if mode["sweep_pause"]:
            mode["sweep_pause"] -= 1
            return json.dumps({"paused": True, "pause_reason": "guard"})
        return json.dumps({"total": 3, "done": 3, "failed": 0, "pending": 0})
    monkeypatch.setattr(was, "run_wide_area_search_job", sweep)

    def land(r, j):
        if mode["lc_problem"]:
            mode["lc_problem"] -= 1
            return {"problem": "offline"}
        return {"newly": 18}
    monkeypatch.setattr(lc, "ensure_job_land_cover", land)
    monkeypatch.setattr(lc, "job_flags", lambda r, j: {"flagged": {}})
    monkeypatch.setattr(tcl, "label_job", lambda r, j: {"labelled": 18})
    monkeypatch.setattr(calib_profile, "active_profile", lambda r: {"threshold_abs_z": 8.0})

    def refine(r, j, refs, **k):
        assert k["require_live_dem"]
        mode["batches"].append(len(refs))
        f = 1 if mode["p2_fail"] else 0     # p2_fail = how many times refs[0] fails
        if f:
            mode["p2_fail"] -= 1
        for c in refs[f:]:
            db.add_evidence_link(r, c, "DEM", gpr.REFINEMENT_RELATION, {"x": 1})
        return {"attempted": len(refs), "refined": len(refs) - f, "failed": f,
                "failures": [{"candidate_id": refs[0], "error": "RuntimeError: token"}] if f else [],
                "dem_library": {"library_cuts": 3, "library_misses": {}}, "copernicus_throttle": {"trips": 0}}
    monkeypatch.setattr(gpr, "run_selected_refinement", refine)
    monkeypatch.setattr(pc, "check_job", lambda r, j: {"candidates": 18,
                        "candidates_verified": 18 if mode["prov_ok"] else 17})
    monkeypatch.setattr(rep, "export_job_report", lambda *a: {"rows_shown": 18})
    return root, jid, mode


def _drive(root, rid, key="K", budget=540):
    for _ in range(40):
        r = json.loads(ap.run_slice_json(root, rid, key, "", "", budget))
        if r["state"] in ("DONE", "FAILED", "CANCELLED"):
            return r["state"]
        if r["state"] == "PAUSED":
            c = ap._conn(root)
            with c:
                c.execute("UPDATE auto_run_event SET detail_json=json_set(detail_json,'$.retry_at',0) WHERE run_id=?", (rid,))
            c.close()
    return "STUCK"


def _trust(root, rid):
    return json.loads(ap.auto_run_status_json(root, rid))["steps"][ap.STEPS.index("trust")]["detail"]


def test_happy_path_trusts_and_refines_only_strong(env):
    root, jid, mode = env
    rid = json.loads(ap.start_auto_run_json(root, jid))["run_id"]
    assert "error" in json.loads(ap.start_auto_run_json(root, jid))       # one active run per job
    assert _drive(root, rid, budget=0) == "DONE"                           # zero budget still progresses
    strong = db.get_connection(root).execute("select count(*) from candidate where abs(score)>=8").fetchone()[0]
    assert sum(mode["batches"]) == strong and max(mode["batches"]) <= 3
    assert _trust(root, rid)["decision"] == "TRUSTED"
    assert review.list_job_trust(root)[0]["reason"].startswith(ap.AUTO_PREFIX)


def test_pauses_recorded_and_trust_withheld_with_reasons(env):
    root, jid, mode = env
    mode.update(sweep_pause=1, lc_problem=1, p2_fail=10**6, prov_ok=False)
    rid = json.loads(ap.start_auto_run_json(root, jid))["run_id"]
    assert _drive(root, rid) == "DONE"
    t = _trust(root, rid)
    assert t["decision"] == "not marked" and len(t["reasons"]) == 3
    assert review.list_job_trust(root) == []


def test_user_trust_never_overwritten(env):
    root, jid, mode = env
    review.set_job_trust(root, jid, "UNVERIFIED", "user")
    rid = json.loads(ap.start_auto_run_json(root, jid))["run_id"]
    assert _drive(root, rid) == "DONE"
    assert _trust(root, rid)["decision"] == "kept"
    assert [t["trust"] for t in review.list_job_trust(root)] == ["UNVERIFIED"]


def test_budget_pause_and_repeated_failure(env, monkeypatch):
    root, jid, mode = env
    for _ in range(40):
        dlm._record_call(root, "x")
    rid = json.loads(ap.start_auto_run_json(root, jid))["run_id"]
    for _ in range(10):
        r = json.loads(ap.run_slice_json(root, rid, "K"))
        if r["state"] != "RUNNING":
            break
    assert r["state"] == "PAUSED" and r["next_step"] == "pass2" and r["retry_after_s"] > 3600
    ap.cancel_auto_run(root, rid)
    monkeypatch.setattr(tcl, "label_job", lambda r, j: 1 / 0)
    rid2 = json.loads(ap.start_auto_run_json(root, jid))["run_id"]
    assert _drive(root, rid2) == "FAILED"


def test_auto_trust_withdrawn_when_later_run_falls_short(env):
    root, jid, mode = env
    rid = json.loads(ap.start_auto_run_json(root, jid))["run_id"]
    assert _drive(root, rid) == "DONE" and _trust(root, rid)["decision"] == "TRUSTED"
    mode.update(p2_fail=10**6)
    # second run needs strong candidates left: clear refinement links
    c = db.get_connection(root)
    with c:
        c.execute("DELETE FROM evidence_link")
    rid2 = json.loads(ap.start_auto_run_json(root, jid))["run_id"]
    assert _drive(root, rid2) == "DONE"
    t = _trust(root, rid2)
    assert t["decision"] == "withdrawn" and any("still failed after retry" in r for r in t["reasons"])
    cur = review.list_job_trust(root)[0]
    assert cur["trust"] == "UNVERIFIED" and cur["reason"].startswith(ap.AUTO_PREFIX)
    p2 = json.loads(ap.auto_run_status_json(root, rid2))["steps"][ap.STEPS.index("pass2")]["detail"]
    assert "library_cuts_total" in p2 and p2["errors"]



def test_failure_retried_successfully_does_not_block_trust(env):
    root, jid, mode = env
    mode.update(p2_fail=1)
    rid = json.loads(ap.start_auto_run_json(root, jid))["run_id"]
    assert _drive(root, rid) == "DONE"
    t = _trust(root, rid)
    assert t["decision"] == "TRUSTED" and "succeeded on retry" in t["note"]
    p2 = json.loads(ap.auto_run_status_json(root, rid))["steps"][ap.STEPS.index("pass2")]["detail"]
    assert p2["failed_total"] == 1 and p2["remaining_strong"] == 0
