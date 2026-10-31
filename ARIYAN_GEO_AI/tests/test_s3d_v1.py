"""s3d-v1 (2026-10-31): data for the 3D surface. Stored cells only, holes
stay holes, automatic exaggeration with a written rule, snapshot export with
provenance, never a database write."""
import json
import os

import numpy as np
import pytest

import final_image as fi
import final_image_mobile as fim
import offline_dem_store as ods
import surface3d_mobile as s3d
from test_fi_v1 import _bridge_env, _db_snapshot


def _open(tmp_path):
    root, cid, near, far = _bridge_env(tmp_path)
    d = json.loads(fim.open_final_image_json(root, cid, 1000.0, "relief"))
    assert "error" not in d, d
    return root, d


def test_heights_are_the_stored_cells_minus_median(tmp_path):
    root, d = _open(tmp_path)
    m = json.loads(s3d.open_surface_json(d["session_id"]))
    assert "error" not in m, m
    hgt = np.frombuffer(s3d.surface_heights(d["session_id"]), "<f4").reshape(m["height"], m["width"])
    z = fim._SESSIONS[d["session_id"]]["result"]["grid"].values
    assert hgt.shape == z.shape == (d["height"], d["width"])
    fin = np.isfinite(z)
    assert np.allclose(hgt[fin] + m["z_ref_m"], z[fin], atol=1e-2)
    assert np.isnan(hgt[~fin]).all()
    ods.clear_tile_cache()


def test_no_data_cells_stay_holes():
    z = np.arange(36, dtype=float).reshape(6, 6)
    z[2, 3] = np.nan
    g = fi.Grid(values=z, west=50.0, north=33.0, dlon=0.0003, dlat=0.0003, source="t")
    fim._SESSIONS["h1"] = {"result": {"grid": g, "provenance": {"bounds": {}}}, "candidate_id": "c", "t": 0}
    m = json.loads(s3d.open_surface_json("h1"))
    assert m["cells_no_data"] == 1
    hgt = np.frombuffer(s3d.surface_heights("h1"), "<f4").reshape(6, 6)
    assert np.isnan(hgt[2, 3]) and np.isfinite(hgt).sum() == 35
    fim._SESSIONS.pop("h1")


def test_auto_exaggeration_rule():
    # 2 km square, 7 m span -> raw 0.1*2000/7 = 28.6 -> 20x (largest allowed step <= raw)
    z = np.linspace(0, 7, 100 * 100).reshape(100, 100)
    ve, info = s3d.auto_exaggeration(z, 20.0, 20.0)
    assert info["across_m"] == 2000.0 and 6.5 < info["span_m"] < 7.0
    assert ve == 20.0 and ve <= info["raw"]
    # steep: never below 1x
    ve2, _ = s3d.auto_exaggeration(np.linspace(0, 5000, 100).reshape(10, 10), 20.0, 20.0)
    assert ve2 == 1.0
    # very flat: capped at 50x
    ve3, _ = s3d.auto_exaggeration(np.linspace(0, 0.01, 100).reshape(10, 10), 200.0, 200.0)
    assert ve3 == 50.0
    # flat plane: 1x with the rule saying so
    ve4, info4 = s3d.auto_exaggeration(np.zeros((10, 10)), 30.0, 30.0)
    assert ve4 == 1.0 and info4["raw"] is None
    assert all(v in s3d.NICE_VE for v in (ve, ve2, ve3, ve4))


def test_rule_text_states_the_numbers(tmp_path):
    root, d = _open(tmp_path)
    m = json.loads(s3d.open_surface_json(d["session_id"]))
    assert m["ve_auto"] in s3d.NICE_VE
    assert m["ve_rule"].startswith("automatic")
    assert "not archaeological proof" in m["statement"]
    ods.clear_tile_cache()


def test_snapshot_export_writes_png_and_provenance_not_db(tmp_path):
    root, d = _open(tmp_path)
    before = _db_snapshot(root)
    png = fi.encode_png(np.full((4, 4, 4), 200, np.uint8))
    state = json.dumps({"ve": 20, "ve_mode": "auto", "azimuth_deg": 200, "tilt_deg": 40,
                        "drape": "TRUE_COLOR", "secret": "no"})
    r = json.loads(s3d.export_snapshot_json(root, d["session_id"], png, state))
    assert r["ok"], r
    assert open(r["paths"]["png"], "rb").read() == png
    prov = json.load(open(r["paths"]["provenance"], encoding="utf-8"))
    import hashlib
    assert prov["outputs"]["png_sha256"] == hashlib.sha256(png).hexdigest()
    assert prov["view"]["drape"] == "TRUE_COLOR" and "secret" not in prov["view"]
    assert prov["synthetic_data"] is False and prov["dem"]["source_sha256"]
    assert prov["processing_parameters"]["version"] == "fs-v1"
    assert _db_snapshot(root) == before
    ods.clear_tile_cache()


def test_snapshot_rejects_non_png_and_expired_session(tmp_path):
    root, d = _open(tmp_path)
    assert "not a PNG" in json.loads(s3d.export_snapshot_json(root, d["session_id"], b"hello"))["error"]
    assert "expired" in json.loads(s3d.open_surface_json("gone"))["error"]
    with pytest.raises(KeyError):
        s3d.surface_heights("gone")
    ods.clear_tile_cache()
