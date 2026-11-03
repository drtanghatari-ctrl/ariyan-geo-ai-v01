"""win-w4c: review with reasons through the phone's own review module, the same-place note
(within one DEM cell, never merged), job report and Export Results."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ariyan_win import core_path  # noqa: E402

core_path.install()

import grand_project_db as db  # noqa: E402

from ariyan_win import workstation  # noqa: E402


def _project(root):
    gid = db.create_grand_project(root, "Default Grand Project", project_id="default")
    inv1 = db.create_investigation(root, gid, objective="first run")
    a = db.create_candidate(root, gid, inv1, 36.95323, 45.52454, score=12.5)
    inv2 = db.create_investigation(root, gid, objective="second run, same place")
    b = db.create_candidate(root, gid, inv2, 36.95330, 45.52460, score=9.0)      # about 9 m away
    c = db.create_candidate(root, gid, inv2, 36.96000, 45.53000, score=7.0)      # far away
    return gid, a, b, c


def test_same_place_points_only_to_earlier_candidates(tmp_path):
    root = str(tmp_path)
    gid, a, b, c = _project(root)
    assert workstation.same_place(root, a) == []
    s = workstation.same_place(root, b)
    assert [x["id"] for x in s] == [a] and s[0]["distance_m"] < 30
    assert workstation.same_place(root, c) == []
    page = workstation.candidate_page(root, None, "", "", "", 0)
    assert page["total"] == 3 and {r["id"]: bool(r["same_place"]) for r in page["rows"]} == {a: False, b: True, c: False}


def test_review_is_recorded_with_reason_and_band_untouched(tmp_path):
    import grand_project_query_mobile as q
    root = str(tmp_path)
    gid, a, b, c = _project(root)
    db.update_candidate_confidence(root, a, "MODERATE", 0.55)
    r = json.loads(q.set_candidate_status_json(root, a, "REJECTED", "empty urban plot beside a stream"))
    assert "error" not in r and r["new_status"] == "REJECTED"
    d = json.loads(q.get_candidate_detail_json(root, a))
    assert d["candidate"]["status"] == "REJECTED" and d["candidate"]["confidence_band"] == "MODERATE"
    assert "error" in json.loads(q.set_candidate_status_json(root, a, "MAYBE", "x"))


def test_export_results_writes_every_candidate(tmp_path):
    root = str(tmp_path)
    _project(root)
    r = workstation.export_results(root)
    assert r["rows"] == 3 and os.path.exists(r["csv"]) and os.path.exists(r["geojson"])
    gj = json.load(open(r["geojson"]))
    assert len(gj["features"]) == 3 and gj["features"][0]["geometry"]["type"] == "Point"
    assert len(open(r["csv"]).read().strip().splitlines()) == 4


def test_tabs_build(tmp_path):
    from PySide6 import QtWidgets
    from ariyan_win import app, qtwork
    root = str(tmp_path)
    _project(root)
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    w = app.build_window(root)
    for _ in range(5):
        qtwork.wait_all(30000)
        qa.processEvents()
    assert w.report.table.rowCount() == 3
    assert "Analysis" in w.models.text.toPlainText()
    w.close()
