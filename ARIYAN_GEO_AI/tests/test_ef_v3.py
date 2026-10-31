"""ef-v3 / svp-v1 (2026-10-31): survey planner. Contested zones rank first,
then single hypotheses by claimed volume; coordinates come from the user's
own shapes; methods from a fixed qualitative table; no invented numbers; the
database and the candidate are untouched (export writes only its files)."""
import json
import os

import numpy as np

import evidence_volume as ev
import final_image_mobile as fim
import grand_project_db as db
import offline_dem_store as ods
import survey_plan as sp
from test_fi_v1 import _bridge_env, _db_snapshot


def _ll(x, y):
    return 50.0 + x * 0.001, 33.0 - y * 0.001        # fake but monotonic pixel -> (lon, lat)


def test_contested_first_then_largest_hypothesis():
    hyps = [{"id": "a", "label": "kiln?", "kind": "footprint", "top_m": 0.0, "bottom_m": 2.0,
             "cells": [(r, c) for r in range(2) for c in range(3)]},
            {"id": "b", "label": "knoll?", "kind": "footprint", "top_m": 1.0, "bottom_m": 4.0,
             "cells": [(r, c) for r in range(2) for c in range(2, 5)]},
            {"id": "c", "label": "pit?", "kind": "section", "top_m": 0.0, "bottom_m": 0.5, "cells": [(5, 5)]}]
    rel = np.zeros((8, 8))
    st = ev.build_states(rel, hyps)
    cnt = ev.build_counts(rel.shape, hyps)
    p = sp.plan(st, cnt, hyps, {"present": False}, _ll)
    kinds = [it["kind"] for it in p["items"]]
    assert kinds[0] == "CONTESTED" and kinds.count("CONTESTED") == 1
    z = p["items"][0]
    assert z["hypotheses"] == ["kiln?", "knoll?"] and z["cells"] == 2
    assert z["depth_top_m"] == 1.0 and z["depth_bottom_m"] == 2.0          # only where both claim
    singles = [it["hypotheses"][0] for it in p["items"][1:]]
    assert singles == ["knoll?", "kiln?", "pit?"]                          # largest claimed volume first
    assert [it["rank"] for it in p["items"]] == [1, 2, 3, 4]
    lat, lon = z["area_corners_latlon"][0]
    assert abs(lon - 50.002) < 1e-9 and abs(lat - 33.0) < 1e-9             # corner of cell column 2, row 0


def test_no_numbers_invented_and_methods_fixed():
    p = sp.plan(np.zeros((2, 2, 20), np.uint8), np.zeros((2, 2, 20), np.uint8), [], {}, _ll)
    assert p["items"] == [] and "nothing to separate" in p["empty_reason"]
    assert set(p["methods"]) == {"GPR", "ERT", "MAG", "CORE"}
    text = " ".join(p["methods"].values()).lower()
    assert "probability" not in text and not any(ch.isdigit() for ch in text)
    assert "not evidence" in p["statement"]


def test_bridge_plan_and_export_touch_no_table(tmp_path):
    root, cid, near, far = _bridge_env(tmp_path)
    d = json.loads(fim.open_final_image_json(root, cid, 1000.0, "relief"))
    sid = d["session_id"]
    cx, cy = float(d["width"] // 2), float(d["height"] // 2)
    sq = lambda x0, y0, x1, y1: json.dumps([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    assert json.loads(ev.add_footprint_json(root, sid, sq(cx - 3, cy - 3, cx + 3, cy + 3), "A?", 0, 2))["ok"]
    assert json.loads(ev.add_footprint_json(root, sid, sq(cx, cy - 3, cx + 6, cy + 3), "B?", 1, 3))["ok"]
    before = _db_snapshot(root)
    p = json.loads(sp.plan_json(root, sid))
    assert "error" not in p, p
    assert p["items"][0]["kind"] == "CONTESTED" and p["items"][0]["hypotheses"] == ["A?", "B?"]
    assert p["items"][0]["cells"] == 18 and p["candidate_id"] == cid
    r = json.loads(sp.export_plan_json(root, sid))
    assert r["ok"] and os.path.exists(r["paths"]["text"]) and os.path.exists(r["paths"]["json"])
    txt = open(r["paths"]["text"], encoding="utf-8").read()
    assert "CONTESTED: A?, B?" in txt and "METHODS" in txt and "not evidence" in txt
    assert _db_snapshot(root) == before
    ods.clear_tile_cache()


def test_expired_session_is_an_error():
    assert "expired" in json.loads(sp.plan_json("/nowhere", "gone"))["error"]
