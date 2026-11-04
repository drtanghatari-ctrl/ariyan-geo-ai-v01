"""u2: search inside one job; a candidate's group is the job's candidates chained within
300 m; its interpretation carries the Steward words and the stored debate; read-only."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ariyan_win import core_path  # noqa: E402

core_path.install()

import grand_project_db as db  # noqa: E402

from ariyan_win import workstation  # noqa: E402


def _job(root, gid, title, lat, lon):
    jid = db.create_wide_area_search_job(root, gid, title, "MANUAL_BBOX", lat - .01, lat + .01, lon - .01, lon + .01, 2000.0,
                                         [{"tile_index": 0, "center_lat": lat, "center_lon": lon}])
    tile = db.list_tiles_for_job(root, jid)[0]
    inv = db.create_investigation(root, gid, objective="tile")
    db.mark_tile_done(root, tile["id"], inv)
    return jid, inv


def _project(root):
    gid = db.create_grand_project(root, "Default Grand Project", project_id="default")
    j1, inv1 = _job(root, gid, "Solduz plain", 36.95, 45.52)
    j2, inv2 = _job(root, gid, "Deh Luran", 32.70, 47.27)
    a = db.create_candidate(root, gid, inv1, 36.95000, 45.52000, score=11.0)
    b = db.create_candidate(root, gid, inv1, 36.95200, 45.52000, score=7.0)     # 223 m from a
    c = db.create_candidate(root, gid, inv1, 36.95400, 45.52000, score=6.0)     # 223 m from b (chained)
    d = db.create_candidate(root, gid, inv1, 36.96500, 45.52000, score=5.0)     # 1.2 km: another group
    e = db.create_candidate(root, gid, inv2, 32.70, 47.27, score=9.0)
    db.update_candidate_confidence(root, a, "MODERATE", 0.55)
    return j1, j2, a, b, c, d, e


def test_job_filter_and_name(tmp_path):
    root = str(tmp_path)
    j1, j2, a, b, c, d, e = _project(root)
    r = workstation.search_candidates(root, "solduz")
    assert {x["id"] for x in r["rows"]} == {a, b, c, d}
    r = workstation.search_candidates(root, e[:6], job_id=j1)
    assert r["rows"] == []
    r = workstation.search_candidates(root, e[:6], job_id=j2)
    assert [x["id"] for x in r["rows"]] == [e]


def test_group_is_chained_within_the_job_and_read_only(tmp_path):
    import project_bundle
    root = str(tmp_path)
    j1, j2, a, b, c, d, e = _project(root)
    path = os.path.join(root, db.DB_FILENAME)
    before = project_bundle.content_fingerprint(path)
    g = workstation.candidate_group(root, a)
    ids = [m["id"] for m in g["members"]]
    assert ids[0] == a and set(ids) == {a, b, c}
    assert "Solduz plain" in g["scope"]
    assert project_bundle.content_fingerprint(path) == before


def test_interpretation_has_debate_and_steward(tmp_path):
    import debate_store
    from ariyan_win import candidates
    root = str(tmp_path)
    j1, j2, a, b, c, d, e = _project(root)
    debate_store.record(root, a, {"positions": [{"perspective": "Geomorphology", "stance": "natural rise",
                                                 "confidence_score": 0.4, "confidence_label": "low",
                                                 "reasoning": ["slope matches the fan"]}],
                                  "synthesis": {"agreement_level": "WEAK_SIGNAL", "leading_position": "Geomorphology",
                                                "steward_note": "weak overall"}}, None, "run")
    d_ = workstation.interpretation(root, a)
    assert d_["debate"]["positions"][0]["stance"] == "natural rise"
    h = candidates.interpretation_html(d_)
    assert "slope matches the fan" in h and "weak overall" in h and "Moderate 0.55" in h


def test_grand_project_candidates_page_builds(tmp_path):
    from PySide6 import QtWidgets
    from ariyan_win import app, qtwork
    root = str(tmp_path)
    j1, j2, a, b, c, d, e = _project(root)
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    w = app.build_window(root)
    for _ in range(3):
        qtwork.wait_all(30000)
        qa.processEvents()
    page = w.grand.candidates
    page.view.show_candidate(a)
    for _ in range(3):
        qtwork.wait_all(30000)
        qa.processEvents()
    assert page.view.group.count() == 3
    assert "Candidate" in page.view.text.toPlainText()
    w.close()
