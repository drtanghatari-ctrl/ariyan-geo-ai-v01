"""ef-v1 (2026-10-31): 3D Evidence Fusion volume. Blocks are DERIVED only
inside the DEM's raised body, HYPOTHESIZED only where the user's own section
hypothesis crosses, UNKNOWN everywhere else; no field data placed; nothing
written; candidate untouched."""
import json

import numpy as np
import pytest

import evidence_volume as ev
import final_image_mobile as fim
import grand_project_db as db
import offline_dem_store as ods
import surface3d_mobile as s3d
from test_fi_v1 import _bridge_env, _db_snapshot


def test_derived_only_inside_raised_body():
    relief = np.array([[-1.0, 0.2], [1.2, np.nan]])
    st = ev.build_states(relief, [])
    assert st.shape == (2, 2, 20)
    assert not (st[0, 0] & ev.DERIVED).any()                     # hollow: nothing derived below ground
    assert (st[0, 1, 0] & ev.DERIVED) and not (st[0, 1, 1] & ev.DERIVED)   # 0.2 m body: first slice only
    assert (st[1, 0, :3] & ev.DERIVED).all() and not (st[1, 0, 3] & ev.DERIVED)  # 1.2 m: slices 0-2
    assert not st[1, 1].any()                                    # no value: stays UNKNOWN


def test_hypothesis_marks_only_its_cells_and_depths():
    relief = np.zeros((5, 5))
    st = ev.build_states(relief, [{"cells": [(2, 1), (2, 2)], "top_m": 1.0, "bottom_m": 2.0}])
    hyp = (st & ev.HYPOTHESIZED) > 0
    assert hyp[2, 1, 2] and hyp[2, 1, 3] and not hyp[2, 1, 1] and not hyp[2, 1, 4]
    assert hyp.sum() == 4                                        # 2 cells x 2 slices, nothing else


def test_slice_colours_and_unknown_transparent():
    st = ev.build_states(np.array([[2.0, -1.0]]), [{"cells": [(0, 0)], "top_m": 0.0, "bottom_m": 0.5}])
    rgba = ev.slice_rgba(st, 0)
    assert tuple(rgba[0, 0]) == ev.COLOURS["HYPOTHESIZED"]       # hypothesis drawn over derived
    assert rgba[0, 1, 3] == 0                                    # UNKNOWN: transparent (map hatches it)
    assert tuple(ev.slice_rgba(st, 1)[0, 0]) == ev.COLOURS["DERIVED"]


def test_raised_body_numbers():
    relief = np.full((6, 6), -0.5)
    relief[2:4, 2:5] = 1.0                                       # 2 x 3 cell mound, 1 m above base
    b = ev.raised_body(relief, 2, 3, 10.0, 20.0)
    assert b["present"] and b["cells"] == 6 and b["area_m2"] == 1200.0
    assert b["volume_m3"] == 1200.0 and b["max_height_m"] == 1.0
    assert b["extent_ew_m"] == 30.0 and b["extent_ns_m"] == 40.0 and not b["touches_window_edge"]
    assert not ev.raised_body(relief, 0, 0, 10.0, 20.0)["present"]


def test_line_cells_follow_the_segment():
    cells = ev.line_cells(0.5, 2.5, 4.5, 2.5, 0.0, 1.0)
    assert cells[0] == (2, 0) and cells[-1] == (2, 4) and all(r == 2 for r, _ in cells)


def test_bridge_builds_volume_with_user_hypothesis_and_writes_nothing(tmp_path):
    root, cid, near, far = _bridge_env(tmp_path)
    d = json.loads(fim.open_final_image_json(root, cid, 1000.0, "relief"))
    sid = d["session_id"]
    h, w = d["height"], d["width"]
    assert json.loads(s3d.add_hypothesis_json(root, sid, 2.0, h / 2.0, w - 2.0, h / 2.0,
                                              "wall?", 100, 400, 1.0, 3.0))["ok"]
    before = _db_snapshot(root)
    conn = db.get_connection(root)
    cand_before = tuple(conn.execute("SELECT * FROM candidate WHERE id=?", (cid,)).fetchone()); conn.close()
    v = json.loads(ev.volume_json(root, sid))
    assert "error" not in v, v
    assert v["grid"]["width"] == w and len(v["slices"]) == 20 and v["version"] == "ef-v2"
    assert v["hypotheses"][0]["label"] == "wall?" and v["hypotheses"][0]["cells"] > 0
    assert v["measured_in_volume"] == 0 and v["field_readings_recorded"] == 0
    assert any(s["hypothesized_cells"] > 0 for s in v["slices"][2:6])
    assert all(s["hypothesized_cells"] == 0 for s in v["slices"][:2])
    raw = ev.volume_slice_rgba(sid, 2)
    assert len(raw) == w * h * 4
    assert _db_snapshot(root) == before
    conn = db.get_connection(root)
    assert tuple(conn.execute("SELECT * FROM candidate WHERE id=?", (cid,)).fetchone()) == cand_before
    conn.close()
    with pytest.raises(ValueError):
        ev.volume_slice_rgba(sid, 99)
    ods.clear_tile_cache()


def test_withdrawn_hypothesis_leaves_the_volume(tmp_path):
    root, cid, near, far = _bridge_env(tmp_path)
    d = json.loads(fim.open_final_image_json(root, cid, 1000.0, "relief"))
    sid = d["session_id"]
    h, w = d["height"], d["width"]
    hid = json.loads(s3d.add_hypothesis_json(root, sid, 2.0, h / 2.0, w - 2.0, h / 2.0, "pit?", 50, 150, 0.0, 1.0))["id"]
    s3d.withdraw_hypothesis_json(root, hid, "test")
    v = json.loads(ev.volume_json(root, sid))
    assert v["hypotheses"] == [] and all(s["hypothesized_cells"] == 0 for s in v["slices"])
    ods.clear_tile_cache()


def test_expired_session_is_an_error():
    assert "expired" in json.loads(ev.volume_json("/nowhere", "gone"))["error"]
    with pytest.raises(KeyError):
        ev.volume_slice_rgba("gone", 0)
