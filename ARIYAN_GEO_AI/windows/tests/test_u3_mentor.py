"""sm-v1: the Steward leads a job step by step from the stored rows, suggests the
Automatic run at the right moment, and calls the job complete only when nothing is left."""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ariyan_win import core_path  # noqa: E402

core_path.install()

import grand_project_db as db  # noqa: E402

from ariyan_win import mentor  # noqa: E402


def _job(root):
    gid = db.create_grand_project(root, "Default Grand Project", project_id="default")
    jid = db.create_wide_area_search_job(root, gid, "Solduz plain", "MANUAL_BBOX", 36.94, 36.96, 45.51, 45.53, 2000.0,
                                         [{"tile_index": 0, "center_lat": 36.95, "center_lon": 45.52}])
    return gid, jid


def _states(g):
    return {s["key"]: s["state"] for s in g["steps"]}


def test_new_job_asks_for_target_then_suggests_the_automatic_run(tmp_path):
    root = str(tmp_path)
    gid, jid = _job(root)
    g = mentor.job_guide(root, jid)
    assert g["next"]["key"] == "target" and not g["complete"]
    import grand_project_review as rv
    rv.set_job_target(root, jid, rv.TARGET_MOUND_TELL, "looking for tells")
    g = mentor.job_guide(root, jid)
    st = _states(g)
    assert st["target"] == "done" and g["next"]["key"] == "search" and g["next"]["action"] == "auto"
    assert any("may I suggest the Automatic run" in s["text"] for s in g["steps"])


def test_full_path_to_complete(tmp_path):
    import auto_pipeline as ap
    import grand_project_review as rv
    import grand_project_report as rep
    root = str(tmp_path)
    gid, jid = _job(root)
    rv.set_job_target(root, jid, rv.TARGET_MOUND_TELL, "tells")
    tile = db.list_tiles_for_job(root, jid)[0]
    inv = db.create_investigation(root, gid, objective="tile")
    db.mark_tile_done(root, tile["id"], inv)
    cid = db.create_candidate(root, gid, inv, 36.95, 45.52, score=12.0)
    db.update_candidate_confidence(root, cid, "MODERATE", 0.55)
    run = ap.start_auto_run(root, jid)
    for s in ap.STEPS:
        detail = {"reasons": ["provenance not verified"]} if s == "trust" else {}
        ap._event(root, run["run_id"], s, "DONE", detail)
    g = mentor.job_guide(root, jid)
    st = _states(g)
    assert st["automatic"] == "done" and st["trust"] == "todo" and st["review"] == "todo"
    assert "provenance not verified" in [s for s in g["steps"] if s["key"] == "trust"][0]["text"]
    rv.set_job_trust(root, jid, "UNVERIFIED", "checked the reasons")
    rv.set_candidate_status(root, cid, "SUPPORTED", "clear mound in the profile")
    g = mentor.job_guide(root, jid)
    assert _states(g)["review"] == "done" and g["next"]["key"] == "report"
    rep.export_job_report(root, gid, jid)
    g = mentor.job_guide(root, jid)
    assert g["complete"] and "scientifically complete" in g["say"]
    assert [s for s in g["steps"] if s["key"] == "field"][0]["optional"]       # advice, never blocking


def test_project_welcome(tmp_path):
    root = str(tmp_path)
    g = mentor.project_guide(root, datetime(2026, 11, 4, 8, 0))
    assert g["hello"].startswith("Good morning") and g["action"] == "receive"
    _job(root)
    g = mentor.project_guide(root, datetime(2026, 11, 4, 20, 0))
    assert g["hello"].startswith("Good evening") and g["open"] == 1 and g["action"] == "target"


def test_banner_and_guide_build(tmp_path):
    from PySide6 import QtWidgets
    from ariyan_win import app, qtwork
    root = str(tmp_path)
    gid, jid = _job(root)
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    w = app.build_window(root)
    for _ in range(4):
        qtwork.wait_all(30000)
        qa.processEvents()
    assert "Steward" in w.steward.hello.text() and w.steward.act.isVisibleTo(w.steward)
    w.jobs.guide.load(jid)
    for _ in range(3):
        qtwork.wait_all(30000)
        qa.processEvents()
    assert "step 1 of" in w.jobs.guide.count.text()
    w.close()
