"""u1: Mission Control finds any candidate by ID, by name (job title or a known site)
and by coordinate, read-only; the overview shows the Study Area and the layers strip."""
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
    a = db.create_candidate(root, gid, inv, 36.95323, 45.52454, score=12.5)
    b = db.create_candidate(root, gid, inv, 36.95600, 45.52454, score=6.0)     # ~308 m north
    c = db.create_candidate(root, gid, inv, 37.50000, 45.00000, score=5.0)     # far away
    return a, b, c


def test_parse_query_kinds():
    assert workstation.parse_query("36.95, 45.52")["kind"] == "coordinate"
    q = workstation.parse_query("36.95 45.52 2 km")
    assert q["kind"] == "coordinate" and q["radius_m"] == 2000.0
    assert workstation.parse_query("090689e5")["kind"] == "id"
    assert workstation.parse_query("Hasanlu")["kind"] == "name"


def test_search_by_id_coordinate_and_is_read_only(tmp_path):
    import project_bundle
    root = str(tmp_path)
    a, b, c = _project(root)
    path = os.path.join(root, db.DB_FILENAME)
    before = project_bundle.content_fingerprint(path)
    r = workstation.search_candidates(root, a[:6])
    assert a in [x["id"] for x in r["rows"]]
    r = workstation.search_candidates(root, "36.95323, 45.52454, 500 m")
    ids = [x["id"] for x in r["rows"]]
    assert ids[0] == a and b in ids and c not in ids
    assert r["rows"][1]["distance_m"] > 250
    r = workstation.search_candidates(root, "36.95323, 45.52454, 100 m")
    assert [x["id"] for x in r["rows"]] == [a]
    assert project_bundle.content_fingerprint(path) == before


def test_search_by_known_site_name_folds_accents(tmp_path):
    import known_sites
    known_sites._load()
    site = next(p for p in known_sites._points if p["kind"] != "N" and "Hasanlu" in p["name"])
    root = str(tmp_path)
    gid = db.create_grand_project(root, "Default Grand Project", project_id="default")
    inv = db.create_investigation(root, gid, objective="t")
    cid = db.create_candidate(root, gid, inv, site["lat"] + 0.002, site["lon"], score=9.0)
    r = workstation.search_candidates(root, "hasanlu")
    assert [x["id"] for x in r["rows"]] == [cid] and "known site" in r["rows"][0]["match"]
    assert workstation._fold("Kültepe") == "kultepe"


def test_overview_cards_build(tmp_path):
    from PySide6 import QtWidgets
    from ariyan_win import app, qtwork
    root = str(tmp_path)
    _project(root)
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    w = app.build_window(root)
    for _ in range(4):
        qtwork.wait_all(30000)
        qa.processEvents()
    texts = [x.text() for x in w.mission.study_box.findChildren(QtWidgets.QLabel)]
    assert "Default Grand Project" in texts and "Candidates" in texts
    w.mission.search_edit.setText("36.95323, 45.52454, 500 m")
    w.mission.run_search()
    for _ in range(3):
        qtwork.wait_all(30000)
        qa.processEvents()
    assert w.mission.search_list.count() == 2
    w.close()
