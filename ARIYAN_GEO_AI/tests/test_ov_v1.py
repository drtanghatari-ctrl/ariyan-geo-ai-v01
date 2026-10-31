"""ov-v1 (2026-10-31): Overview dashboard data. Recorded results only; never a
tick for something absent; nothing written."""
import json

import numpy as np

import evidence_volume as ev
import final_image_mobile as fim
import grand_project_db as db
import offline_dem_store as ods
import overview_mobile as ov
from test_fi_v1 import _bridge_env, _db_snapshot


def _open(tmp_path):
    root, cid, near, far = _bridge_env(tmp_path)
    d = json.loads(fim.open_final_image_json(root, cid, 1000.0, "relief"))
    assert "error" not in d, d
    return root, cid, d


def test_overview_reports_only_what_exists(tmp_path):
    root, cid, d = _open(tmp_path)
    before = _db_snapshot(root)
    o = json.loads(ov.overview_json(root, d["session_id"]))
    assert "error" not in o, o
    assert o["candidate_id"] == cid and o["version"] == "ov-v1"
    names = {l["name"]: l for l in o["layers"]}
    assert names["DEM (terrain)"]["state"] == "USED"
    assert names["GPR (field)"]["state"] == "NONE" and names["ERT (field)"]["state"] == "NONE"
    assert names["Magnetometry"]["detail"] == "not supported yet"
    # no satellite layer saved or linked in the fixture: none may claim more than NONE
    sat = [l for l in o["layers"] if "Sentinel" in l["name"] or "Landsat" in l["name"]]
    assert sat and all(l["state"] == "NONE" for l in sat)
    assert o["debate"] == {"stored": 0} and o["hypotheses"] == {"section": 0, "footprint": 0}
    assert o["map"]["utm_zone"] in (38, 39, 40) and o["map"]["cells"] == [d["width"], d["height"]]
    assert "Nothing here is recomputed" in o["statement"]
    assert _db_snapshot(root) == before
    ods.clear_tile_cache()


def test_overview_counts_user_hypotheses_and_neighbours(tmp_path):
    root, cid, d = _open(tmp_path)
    sid = d["session_id"]
    cx, cy = float(d["width"] // 2), float(d["height"] // 2)
    sq = json.dumps([[cx - 2, cy - 2], [cx + 2, cy - 2], [cx + 2, cy + 2], [cx - 2, cy + 2]])
    assert json.loads(ev.add_footprint_json(root, sid, sq, "x?", 0, 1))["ok"]
    o = json.loads(ov.overview_json(root, sid))
    assert o["hypotheses"]["footprint"] == 1
    # neighbours: every other marker of the session, nearest first, never the candidate itself
    others = o["others"]
    assert all(x["id"] != cid for x in others)
    assert others == sorted(others, key=lambda x: x["distance_m"])
    ods.clear_tile_cache()


def test_expired_session():
    assert "expired" in json.loads(ov.overview_json("/nowhere", "gone"))["error"]
