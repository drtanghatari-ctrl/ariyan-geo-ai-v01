"""win-w1: workstation data comes from the core, read-only, and a missing terrain tile
is reported (with the tile to fetch) instead of a broken view."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ariyan_win import core_path  # noqa: E402

core_path.install()

import grand_project_db as db  # noqa: E402

from ariyan_win import workstation  # noqa: E402


def _project(root):
    gid = db.create_grand_project(root, "Default Grand Project", project_id="default")
    inv = db.create_investigation(root, gid, objective="t")
    cid = db.create_candidate(root, gid, inv, 36.95323, 45.52454, score=12.5)
    db.update_candidate_confidence(root, cid, "MODERATE", 0.55)
    db.add_evidence_link(root, cid, "SAR", "supports", {"n": 1})
    return cid


def test_detail_and_timeline_are_real_and_read_only(tmp_path):
    root = str(tmp_path)
    cid = _project(root)
    import project_bundle
    path = os.path.join(root, db.DB_FILENAME)
    before = project_bundle.content_fingerprint(path)      # content, not bytes (empty tables appear on first read)
    d = workstation.candidate_detail(root, cid)
    assert d["band"] == "MODERATE" and d["numeric"] == 0.55 and d["evidence"] == {"SAR": {"supports": 1}}
    assert d["debate"] is None
    tl = workstation.timeline(root, 5)
    assert tl and tl[0]["event_type"]
    assert project_bundle.content_fingerprint(path) == before


def test_missing_terrain_tile_is_reported_with_the_tile_to_fetch(tmp_path):
    root = str(tmp_path)
    cid = _project(root)
    t = workstation.terrain(root, cid)
    assert "error" in t
    nt = t["needs_tile"]
    assert nt["covered"] and not nt["present"] and nt["tile"]


def test_workstation_window_builds_on_a_project(tmp_path):
    from PySide6 import QtWidgets
    from ariyan_win import app, qtwork
    root = str(tmp_path)
    _project(root)
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    w = app.build_window(root)
    qtwork.wait_all(30000)
    qa.processEvents()
    qtwork.wait_all(30000)
    qa.processEvents()
    assert w.mission.table.rowCount() == 1
    w.close()


def test_debate_studio_lists_each_debate_once(tmp_path):
    import debate_store
    from PySide6 import QtWidgets
    from ariyan_win import app, qtwork
    root = str(tmp_path)
    cid = _project(root)
    debate_store.record(root, cid, {"positions": [], "synthesis": {"agreement_level": "WEAK_SIGNAL"}}, None, "run")
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    w = app.build_window(root)
    for _ in range(4):
        qtwork.wait_all(30000)
        qa.processEvents()
    assert w.debates.list.count() == 1
    w.close()


def test_final_image_window_reports_a_missing_tile(tmp_path):
    from PySide6 import QtWidgets
    from ariyan_win import qtwork
    from ariyan_win.finalimage import FinalImageWindow
    root = str(tmp_path)
    cid = _project(root)
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    w = FinalImageWindow(root, cid)
    for _ in range(3):
        qtwork.wait_all(30000)
        qa.processEvents()
    assert "terrain tile" in w.layer_note.text()
    w.close()
