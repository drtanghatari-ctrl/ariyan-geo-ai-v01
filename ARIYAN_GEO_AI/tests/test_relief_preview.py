"""relief-v1: Pass 2 previews carry each candidate's Pass 1 relief in metres."""
import json

import grand_project_db as db
import grand_project_refinement as gpr


def _setup(tmp_path):
    root = str(tmp_path)
    gp = db.create_grand_project(root, "t")
    centers = [{"tile_index": 0, "center_lat": 32.1, "center_lon": 48.3}]
    jid = db.create_wide_area_search_job(root, gp, "j", "MANUAL_BBOX", 32.1, 32.11, 48.3, 48.31, 1000, centers)
    t = db.list_tiles_for_job(root, jid)[0]
    inv = db.create_investigation(root, gp, "", "", {})
    db.mark_tile_done(root, t["id"], inv)
    up = db.create_candidate(root, gp, inv, 32.100, 48.300, score=9.0)
    down = db.create_candidate(root, gp, inv, 32.105, 48.305, score=-6.0)
    none = db.create_candidate(root, gp, inv, 32.109, 48.309, score=4.0)
    db.add_evidence_link(root, up, "DEM", "primary_detection",
                         detail={"peak_residual_m": 2.43, "area_cells": 5})
    db.add_evidence_link(root, down, "DEM", "primary_detection",
                         detail={"peak_residual_m": -1.12})
    return root, jid, up, down, none


def test_auto_preview_has_signed_relief_and_none_when_missing(tmp_path):
    root, jid, up, down, none = _setup(tmp_path)
    sel = json.loads(gpr.preview_refinement_selection_json(root, jid, 3, min_separation_m=0, skip_flagged=False))
    by = {c["candidate_id"]: c["relief_m"] for c in sel["selected"]}
    assert by == {up: 2.43, down: -1.12, none: None}


def test_selected_preview_has_relief(tmp_path):
    root, jid, up, down, none = _setup(tmp_path)
    sel = json.loads(gpr.preview_selected_refinement_json(root, jid, " ".join([down, none])))
    assert [c["relief_m"] for c in sel["selected"]] == [-1.12, None]


def test_relief_lookup_never_raises(tmp_path):
    assert gpr._relief_by_candidate(str(tmp_path / "nope"), ["x"]) == {"x": None}
    assert gpr._relief_by_candidate(str(tmp_path), []) == {}
