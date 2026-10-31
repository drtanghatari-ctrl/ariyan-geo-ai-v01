"""cut-v2 part 2 (shyp-v1, 2026-10-31): user-drawn HYPOTHESIZED shapes on the
cut face. Only the user creates them; they are append-only, stored on the
ground (lat/lon of A and A'), logged to the timeline, and never touch a
candidate's status, review or confidence."""
import json

import numpy as np
import pytest

import final_image_mobile as fim
import grand_project_db as db
import offline_dem_store as ods
import section_hypothesis as sh
import surface3d_mobile as s3d
from test_fi_v1 import _bridge_env


def _open(tmp_path):
    root, cid, near, far = _bridge_env(tmp_path)
    d = json.loads(fim.open_final_image_json(root, cid, 1000.0, "relief"))
    assert "error" not in d, d
    return root, cid, d


def _cand_row(root, cid):
    conn = db.get_connection(root)
    try:
        return tuple(conn.execute("SELECT * FROM candidate WHERE id = ?", (cid,)).fetchone())
    finally:
        conn.close()


def _line(d):
    h, w = d["height"], d["width"]
    return 2.0, h / 2.0, w - 2.0, h / 2.0          # an E-W line across the window


def test_add_list_and_line_matching(tmp_path):
    root, cid, d = _open(tmp_path)
    sid = d["session_id"]
    ax, ay, bx, by = _line(d)
    before = _cand_row(root, cid)
    r = json.loads(s3d.add_hypothesis_json(root, sid, ax, ay, bx, by, "mud-brick wall?", 40, 90, 1.0, 3.0, "my idea"))
    assert r["ok"], r
    lst = json.loads(s3d.hypotheses_json(root, sid, ax, ay, bx, by))
    assert lst["ok"] and len(lst["hypotheses"]) == 1
    h0 = lst["hypotheses"][0]
    assert h0["kind"] == "HYPOTHESIZED" and h0["status"] == "ACTIVE" and h0["on_this_line"]
    assert h0["along_from_m"] == 40 and h0["depth_bottom_m"] == 3.0
    # stored on the ground: its line maps back to the same grid points
    assert np.allclose(h0["line_grid"], [ax, ay, bx, by], atol=1e-3)
    # a different line (N-S) does not match
    other = json.loads(s3d.hypotheses_json(root, sid, d["width"] / 2.0, 2.0, d["width"] / 2.0, d["height"] - 2.0))
    assert not other["hypotheses"][0]["on_this_line"] and other["hypotheses"][0]["line_in_window"]
    # never touches the candidate
    assert _cand_row(root, cid) == before
    ods.clear_tile_cache()


def test_validation_rejects_bad_shapes(tmp_path):
    root, cid, d = _open(tmp_path)
    sid = d["session_id"]
    ax, ay, bx, by = _line(d)
    length = json.loads(s3d.hypotheses_json(root, sid, ax, ay, bx, by))["line"]["length_m"]
    for args in [("", 10, 20, 1, 2), ("x", 30, 20, 1, 2), ("x", 10, length + 50, 1, 2),
                 ("x", 10, 20, 3, 2), ("x", 10, 20, 1, sh.MAX_DEPTH_M + 1), ("x", -5, 20, 1, 2)]:
        r = json.loads(s3d.add_hypothesis_json(root, sid, ax, ay, bx, by, *args))
        assert "error" in r, args
    assert json.loads(s3d.hypotheses_json(root, sid, ax, ay, bx, by))["hypotheses"] == []
    ods.clear_tile_cache()


def test_withdraw_is_append_only_and_needs_reason(tmp_path):
    root, cid, d = _open(tmp_path)
    sid = d["session_id"]
    ax, ay, bx, by = _line(d)
    hid = json.loads(s3d.add_hypothesis_json(root, sid, ax, ay, bx, by, "ditch?", 100, 160, 0.5, 2.0))["id"]
    assert "error" in json.loads(s3d.withdraw_hypothesis_json(root, hid, "  "))
    assert json.loads(s3d.withdraw_hypothesis_json(root, hid, "satellite shows a modern canal"))["ok"]
    allh = json.loads(s3d.hypotheses_json(root, sid, ax, ay, bx, by))["hypotheses"]
    assert allh[0]["status"] == "WITHDRAWN" and "canal" in allh[0]["status_reason"]
    assert sh.list_for_candidate(root, cid) == []                       # active list is empty
    assert len(sh.list_for_candidate(root, cid, include_withdrawn=True)) == 1   # the row is kept
    ods.clear_tile_cache()


def test_timeline_records_add_and_withdraw(tmp_path):
    root, cid, d = _open(tmp_path)
    sid = d["session_id"]
    ax, ay, bx, by = _line(d)
    hid = json.loads(s3d.add_hypothesis_json(root, sid, ax, ay, bx, by, "kiln?", 10, 30, 0.2, 1.5))["id"]
    s3d.withdraw_hypothesis_json(root, hid, "changed my mind")
    gp = db.get_candidate(root, cid)["grand_project_id"]
    kinds = [e["event_type"] for e in db.get_timeline(root, gp)]
    assert "SECTION_HYPOTHESIS_ADDED" in kinds and "SECTION_HYPOTHESIS_WITHDRAWN" in kinds
    text = " ".join(e["description"] or "" for e in db.get_timeline(root, gp))
    assert "Not evidence" in text
    ods.clear_tile_cache()


def test_snapshot_records_drawn_hypotheses(tmp_path):
    import final_image as fi
    root, cid, d = _open(tmp_path)
    png = fi.encode_png(np.full((4, 4, 4), 90, np.uint8))
    state = json.dumps({"cut": "keep left of A->A'", "hypotheses": [{"id": "abc", "label": "wall?"}]})
    r = json.loads(s3d.export_snapshot_json(root, d["session_id"], png, state))
    prov = json.load(open(r["paths"]["provenance"], encoding="utf-8"))
    assert prov["view"]["hypotheses"][0]["label"] == "wall?"
    ods.clear_tile_cache()


def test_unknown_candidate_and_hypothesis_are_errors(tmp_path):
    root = str(tmp_path)
    with pytest.raises(LookupError):
        sh.add(root, "nope", 33, 51, 33, 51.01, 900, "x", 1, 2, 0, 1)
    with pytest.raises(LookupError):
        sh.withdraw(root, "nope", "reason")
