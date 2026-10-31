"""ef-v2 (2026-10-31): user FOOTPRINT hypotheses in the evidence volume.
Polygon cells by cell centre; overlapping different hypotheses = CONTESTED,
never resolved; append-only store, withdraw needs a reason; candidate and
other tables untouched."""
import json

import numpy as np
import pytest

import evidence_volume as ev
import final_image_mobile as fim
import footprint_hypothesis as fph
import grand_project_db as db
import offline_dem_store as ods
import surface3d_mobile as s3d
from test_fi_v1 import _bridge_env


def _open(tmp_path):
    root, cid, near, far = _bridge_env(tmp_path)
    d = json.loads(fim.open_final_image_json(root, cid, 1000.0, "relief"))
    assert "error" not in d, d
    return root, cid, d


def _square(x0, y0, x1, y1):
    return json.dumps([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])


def test_polygon_cells_by_centre():
    cells = ev.polygon_cells([[1.0, 1.0], [4.0, 1.0], [4.0, 3.0], [1.0, 3.0]], 10, 10)
    assert sorted(cells) == [(r, c) for r in (1, 2) for c in (1, 2, 3)]
    tri = ev.polygon_cells([[0.0, 0.0], [6.0, 0.0], [0.0, 6.0]], 10, 10)
    assert (0, 0) in tri and (5, 5) not in tri


def test_counts_and_contested_colour():
    hyps = [{"id": "a", "label": "kiln?", "top_m": 0.0, "bottom_m": 1.0, "cells": [(0, 0), (0, 1)]},
            {"id": "b", "label": "knoll?", "top_m": 0.5, "bottom_m": 2.0, "cells": [(0, 1), (0, 2)]}]
    rel = np.zeros((1, 3))
    st = ev.build_states(rel, hyps)
    cnt = ev.build_counts(rel.shape, hyps)
    assert cnt[0, 1, 1] == 2 and cnt[0, 1, 0] == 1 and cnt[0, 0, 1] == 1
    rgba = ev.slice_rgba(st, 1, cnt)
    assert tuple(rgba[0, 1]) == ev.COLOURS["CONTESTED"] and tuple(rgba[0, 0]) == ev.COLOURS["HYPOTHESIZED"]
    ov = ev.overlaps(hyps)
    assert ov["a"] == ["knoll?"] and ov["b"] == ["kiln?"]
    # same cells but depths that do not overlap: not contested
    assert ev.overlaps([dict(hyps[0], bottom_m=0.5), dict(hyps[1], top_m=0.5)])["a"] == []


def test_add_list_volume_and_contested_end_to_end(tmp_path):
    root, cid, d = _open(tmp_path)
    sid = d["session_id"]
    cx, cy = float(d["width"] // 2), float(d["height"] // 2)      # whole-cell corners
    conn = db.get_connection(root)
    cand_before = tuple(conn.execute("SELECT * FROM candidate WHERE id=?", (cid,)).fetchone()); conn.close()
    a = json.loads(ev.add_footprint_json(root, sid, _square(cx - 3, cy - 3, cx + 3, cy + 3), "kiln?", 0.5, 2.0))
    b = json.loads(ev.add_footprint_json(root, sid, _square(cx, cy - 3, cx + 6, cy + 3), "natural knoll?", 0.0, 4.0))
    assert a["ok"] and b["ok"]
    lst = json.loads(ev.footprints_json(root, sid))["footprints"]
    assert {f["label"] for f in lst} == {"kiln?", "natural knoll?"} and all(f["status"] == "ACTIVE" for f in lst)
    assert np.allclose(lst[0]["polygon_grid"], json.loads(_square(cx - 3, cy - 3, cx + 3, cy + 3)), atol=1e-3)
    v = json.loads(ev.volume_json(root, sid))
    fps = {h["label"]: h for h in v["hypotheses"] if h["kind"] == "footprint"}
    assert fps["kiln?"]["cells"] == 36 and fps["kiln?"]["overlaps"] == ["natural knoll?"]
    assert any(s["contested_cells"] > 0 for s in v["slices"])
    assert v["slices"][0]["contested_cells"] == 0           # 0-0.5 m: only the knoll claims it
    raw = np.frombuffer(ev.volume_slice_rgba(sid, 2), np.uint8).reshape(d["height"], d["width"], 4)
    assert (raw.reshape(-1, 4) == np.array(ev.COLOURS["CONTESTED"], np.uint8)).all(axis=1).sum() > 0
    conn = db.get_connection(root)
    assert tuple(conn.execute("SELECT * FROM candidate WHERE id=?", (cid,)).fetchone()) == cand_before
    conn.close()
    ods.clear_tile_cache()


def test_withdraw_and_validation(tmp_path):
    root, cid, d = _open(tmp_path)
    sid = d["session_id"]
    bad = [(_square(2, 2, 2, 2), "x", 0, 1), (_square(2, 2, 6, 6), "", 0, 1),
           (_square(2, 2, 6, 6), "x", 2, 1), (json.dumps([[1, 1], [5, 5]]), "x", 0, 1),
           (_square(2, 2, 6, 6), "x", 0, fph.MAX_DEPTH_M + 1)]
    for pts, label, t, b in bad:
        assert "error" in json.loads(ev.add_footprint_json(root, sid, pts, label, t, b)), (label, t, b)
    hid = json.loads(ev.add_footprint_json(root, sid, _square(2, 2, 6, 6), "pit?", 0, 1))["id"]
    assert "error" in json.loads(ev.withdraw_footprint_json(root, hid, " "))
    assert json.loads(ev.withdraw_footprint_json(root, hid, "modern ditch on the photo"))["ok"]
    lst = json.loads(ev.footprints_json(root, sid))["footprints"]
    assert lst[0]["status"] == "WITHDRAWN" and "ditch" in lst[0]["status_reason"]
    v = json.loads(ev.volume_json(root, sid))
    assert [h for h in v["hypotheses"] if h["kind"] == "footprint"] == []
    gp = db.get_candidate(root, cid)["grand_project_id"]
    kinds = [e["event_type"] for e in db.get_timeline(root, gp)]
    assert "FOOTPRINT_HYPOTHESIS_ADDED" in kinds and "FOOTPRINT_HYPOTHESIS_WITHDRAWN" in kinds
    ods.clear_tile_cache()


def test_area_is_metres():
    # ~100 m x ~100 m square near 33 N
    lat0, lon0 = 33.0, 51.0
    dlat = 100.0 / 110540.0
    dlon = 100.0 / (111320.0 * np.cos(np.radians(lat0)))
    sq = [[lat0, lon0], [lat0, lon0 + dlon], [lat0 + dlat, lon0 + dlon], [lat0 + dlat, lon0]]
    assert abs(fph.polygon_area_m2(sq) - 10000.0) < 50.0
