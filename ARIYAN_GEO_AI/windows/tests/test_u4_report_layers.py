"""u4 (lay-v1): the job report carries the relief and every saved layer of its leading
candidates, names the missing ones, and its logged MD5 is the file's MD5."""
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ariyan_win import core_path  # noqa: E402

core_path.install()

import numpy as np  # noqa: E402

import grand_project_db as db  # noqa: E402

from ariyan_win import reportlayers, workstation  # noqa: E402


def _job(root):
    gid = db.create_grand_project(root, "Default Grand Project", project_id="default")
    jid = db.create_wide_area_search_job(root, gid, "Solduz plain", "MANUAL_BBOX", 36.94, 36.96, 45.51, 45.53, 2000.0,
                                         [{"tile_index": 0, "center_lat": 36.95, "center_lon": 45.52}])
    tile = db.list_tiles_for_job(root, jid)[0]
    inv = db.create_investigation(root, gid, objective="tile")
    db.mark_tile_done(root, tile["id"], inv)
    a = db.create_candidate(root, gid, inv, 36.95, 45.52, score=10.0)
    db.update_candidate_confidence(root, a, "MODERATE", 0.55)
    b = db.create_candidate(root, gid, inv, 36.951, 45.52, score=4.0)
    return gid, jid, a, b


def _fake_terrain(root, cid):
    rgba = np.full((4, 4, 4), 200, np.uint8).tobytes()
    return {"meta": {"source": "offline DEM tile N36_E045.tif"}, "drape": rgba, "width": 4, "height": 4,
            "layers": [{"product": "TRUE_COLOR", "label": "True colour (Sentinel-2)", "state": "SAVED",
                        "scene_date": "2026-09-27", "clear_fraction": 1.0, "width": 4, "height": 4, "rgba": rgba,
                        "legend": {}},
                       {"product": "THERMAL", "label": "Brightness temperature (Landsat 8/9)", "state": "SAVED",
                        "scene_date": "2026-08-15", "clear_fraction": 0.9, "width": 4, "height": 4, "rgba": rgba,
                        "legend": {"data_min": 301.2, "data_max": 309.8}},
                       {"product": "NDVI", "label": "NDVI (Sentinel-2)", "state": "NOT_SAVED"}]}


def test_report_has_layers_and_true_md5(tmp_path, monkeypatch):
    root = str(tmp_path)
    gid, jid, a, b = _job(root)
    monkeypatch.setattr(workstation, "terrain", _fake_terrain)
    r = reportlayers.export_job_report_with_layers(root, gid, jid, 50, False)
    page = open(r["html_path"], "rb").read()
    assert hashlib.md5(page).hexdigest() == r["html_md5"]
    text = page.decode("utf-8")
    assert "Satellite layers of the leading candidates" in text and a[:8] in text
    assert text.count("data:image/png;base64,") == 3            # relief + true colour + thermal
    assert "NDVI (Sentinel-2) (not saved yet)" in text and "301\u2013310 K" in text
    assert r["layers_candidates"] == 1 and r["layers_pictures"] == 2
    conn = db.get_connection(root)
    d = conn.execute("SELECT description FROM timeline_event WHERE event_type='REPORT_EXPORTED'").fetchone()[0]
    conn.close()
    assert r["html_md5"] in d and "lay-v1" in d


def test_the_steward_sees_this_report(tmp_path, monkeypatch):
    from ariyan_win import mentor
    root = str(tmp_path)
    gid, jid, a, b = _job(root)
    monkeypatch.setattr(workstation, "terrain", _fake_terrain)
    reportlayers.export_job_report_with_layers(root, gid, jid, 50, False)
    g = mentor.job_guide(root, jid)
    assert {s["key"]: s["state"] for s in g["steps"]}["report"] == "done"
