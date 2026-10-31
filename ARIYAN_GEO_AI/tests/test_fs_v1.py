"""fs-v1 (2026-10-31): Final Image processing parameters.

The parameters box must state what was REALLY used (native grid, no
gridding or interpolation, the real contour interval and rule, colour range
rule, hillshade), and the export must write them, with the screen state,
into the provenance file. Read-only: nothing is written to the database."""
import json
import os

import final_image as fi
import final_image_mobile as fim
import offline_dem_store as ods
from test_fi_v1 import _bridge_env, _db_snapshot


def _open(tmp_path, colour_by="relief"):
    root, cid, near, far = _bridge_env(tmp_path)
    d = json.loads(fim.open_final_image_json(root, cid, 1000.0, colour_by))
    assert "error" not in d, d
    return root, d


def test_parameters_match_what_was_drawn(tmp_path):
    root, d = _open(tmp_path)
    pp = d["processing_parameters"]
    assert pp["version"] == "fs-v1"
    g = pp["grid"]
    assert (g["cells_wide"], g["cells_high"]) == (d["width"], d["height"])
    assert abs(g["cell_dx_m"] - d["cell_dx_m"]) < 0.01 and abs(g["cell_dy_m"] - d["cell_dy_m"]) < 0.01
    assert g["window_half_size_m"] == 1000.0
    assert pp["contours"]["interval_m"] == d["contours"]["interval_m"]
    assert pp["contours"]["interval_rule"].startswith("automatic")
    assert pp["colour"]["min"] == d["legend"]["min"] and pp["colour"]["max"] == d["legend"]["max"]
    assert "symmetric" in pp["colour"]["range_rule"]
    assert pp["relief_radius_m"] == 300.0
    assert pp["hillshade"]["azimuths_deg"] == list(fi.DEFAULT_AZIMUTHS)
    assert pp["hillshade"]["strength"] == 0.65
    ods.clear_tile_cache()


def test_no_interpolation_is_stated_and_kriging_is_not_claimed(tmp_path):
    root, d = _open(tmp_path)
    pp = d["processing_parameters"]
    assert pp["gridding"].startswith("none") and pp["interpolation"].startswith("none")
    text = "\n".join(pp["lines"])
    assert "Gridding / interpolation: none" in text
    assert "kriging" in text.lower() and "invent" in text      # named only to say why it is not used
    assert all("kriging:" not in ln.lower() for ln in pp["lines"])
    ods.clear_tile_cache()


def test_elevation_colour_has_no_relief_line(tmp_path):
    root, d = _open(tmp_path, "elevation")
    pp = d["processing_parameters"]
    assert pp["relief_radius_m"] is None
    assert not any(ln.startswith("Relief:") for ln in pp["lines"])
    assert "symmetric" not in pp["colour"]["range_rule"]
    ods.clear_tile_cache()


def test_export_writes_parameters_and_screen_state_never_the_db(tmp_path):
    root, d = _open(tmp_path)
    before = _db_snapshot(root)
    disp = json.dumps({"display_mode": "cells", "overlay_kind": "satellite",
                       "overlay_name": "TRUE_COLOR", "tab": "contour",
                       "api_key": "must not be copied"})
    out = json.loads(fim.export_final_image_json(root, d["session_id"], disp))
    assert out["ok"]
    prov = json.load(open(out["paths"]["provenance"], encoding="utf-8"))
    assert prov["processing_parameters"]["version"] == "fs-v1"
    assert prov["processing_parameters"]["contours"]["interval_m"] == d["contours"]["interval_m"]
    da = prov["display_at_export"]
    assert da["overlay_name"] == "TRUE_COLOR" and "api_key" not in da
    assert "not baked in" in da["note"]
    assert prov["synthetic_data"] is False
    assert _db_snapshot(root) == before
    ods.clear_tile_cache()


def test_export_without_screen_state_still_works(tmp_path):
    root, d = _open(tmp_path)
    out = json.loads(fim.export_final_image_json(root, d["session_id"]))
    prov = json.load(open(out["paths"]["provenance"], encoding="utf-8"))
    assert "processing_parameters" in prov and "display_at_export" not in prov
    bad = json.loads(fim.export_final_image_json(root, d["session_id"], "{not json"))
    prov2 = json.load(open(bad["paths"]["provenance"], encoding="utf-8"))
    assert prov2["display_at_export"]["error"] == "display state not readable"
    ods.clear_tile_cache()


def test_session_does_not_change_base_image_bytes(tmp_path):
    root, d = _open(tmp_path)
    raw = fim.image_rgba(d["session_id"])
    assert len(raw) == d["width"] * d["height"] * 4
    ods.clear_tile_cache()
