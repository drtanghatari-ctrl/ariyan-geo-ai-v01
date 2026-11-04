"""u3d: the Steward follows the candidate or job you look at on every page, and a candidate
picked from a job's search opens with the Steward in its window."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ariyan_win import core_path  # noqa: E402

core_path.install()

import grand_project_db as db  # noqa: E402

from ariyan_win import mentor  # noqa: E402


def _project(root):
    gid = db.create_grand_project(root, "Default Grand Project", project_id="default")
    jid = db.create_wide_area_search_job(root, gid, "Tehran test", "MANUAL_BBOX", 35.68, 35.70, 51.38, 51.40, 2000.0,
                                         [{"tile_index": 0, "center_lat": 35.69, "center_lon": 51.39}])
    tile = db.list_tiles_for_job(root, jid)[0]
    inv = db.create_investigation(root, gid, objective="tile")
    db.mark_tile_done(root, tile["id"], inv)
    a = db.create_candidate(root, gid, inv, 35.69, 51.39, score=10.0)
    db.update_candidate_confidence(root, a, "MODERATE", 0.55)
    sp = db.create_investigation(root, gid, objective="single point")
    b = db.create_candidate(root, gid, sp, 36.0, 52.0, score=5.0)
    return jid, a, b


def test_candidate_guide_job_and_single(tmp_path):
    import grand_project_review as rv
    root = str(tmp_path)
    jid, a, b = _project(root)
    g = mentor.candidate_guide(root, a)
    st = {s["key"]: s["state"] for s in g["steps"]}
    assert st["rated"] == "done" and st["layers"] == "todo" and st["review"] == "todo" and st["job"] == "todo"
    assert g["next"]["action"] == "final_image" and "Tehran test" in [s for s in g["steps"] if s["key"] == "job"][0][
        "text"]
    rv.set_candidate_status(root, a, "SUPPORTED", "clear")
    g = mentor.candidate_guide(root, a)
    assert {s["key"]: s["state"] for s in g["steps"]}["review"] == "done"
    g = mentor.candidate_guide(root, b)
    assert g["job_id"] is None and g["next"]["action"] == "rerun_point"


def test_bar_follows_focus_on_every_page(tmp_path):
    from PySide6 import QtWidgets
    from ariyan_win import app, qtwork, stewardui
    root = str(tmp_path)
    jid, a, b = _project(root)
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    w = app.build_window(root)
    for _ in range(4):
        qtwork.wait_all(30000)
        qa.processEvents()
    w.tabs.setCurrentIndex(1)                      # INVESTIGATION
    qa.processEvents()
    stewardui.focus_candidate(a)
    for _ in range(3):
        qtwork.wait_all(30000)
        qa.processEvents()
    assert "Candidate %s" % a[:8] in w.steward_bar.head.text()
    w.tabs.setCurrentIndex(2)                      # another page: its own hint
    qa.processEvents()
    assert "DATA & EVIDENCE" in w.steward_bar.head.text()
    w.tabs.setCurrentIndex(1)                      # back: the candidate again
    for _ in range(3):
        qtwork.wait_all(30000)
        qa.processEvents()
    assert a[:8] in w.steward_bar.head.text()
    from ariyan_win.candidates import CandidateDialog
    d = CandidateDialog(root, a, None, None, steward_go=w.steward_go)
    for _ in range(3):
        qtwork.wait_all(30000)
        qa.processEvents()
    assert a[:8] in d.steward.head.text()
    d.close()
    w.close()


def test_arriving_on_a_page_picks_up_its_job(tmp_path):
    from PySide6 import QtWidgets
    from ariyan_win import app, qtwork
    root = str(tmp_path)
    jid, a, b = _project(root)
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    w = app.build_window(root)
    for _ in range(4):
        qtwork.wait_all(30000)
        qa.processEvents()
    w.tabs.setCurrentIndex(1)
    w.inv_tabs.setCurrentWidget(w.jobs)
    for _ in range(3):
        qtwork.wait_all(30000)
        qa.processEvents()
    assert w.jobs._job_id() == jid
    assert "Tehran test" in w.steward_bar.head.text()
    w.close()
