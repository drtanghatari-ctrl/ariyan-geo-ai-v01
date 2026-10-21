"""fi-v2 Android bridge (sat_image_mobile): layer over an fi-v1 session."""
import json
import math

import numpy as np
import pytest

import final_image as fi
import final_image_mobile as fim
import sat_image as si
import sat_image_mobile as sim
import ndvi_source_mobile as ndvi
from test_fi_v2 import FakeCDSE, _scenes, B


def _fake_session(lat=32.45, lon=47.27, half=1000.0):
    b = si.bounds_around(lat, lon, half)
    n = 60
    g = fi.Grid(values=np.zeros((n, n)), west=b["west"], north=b["north"],
                dlon=(b["east"] - b["west"]) / n, dlat=(b["north"] - b["south"]) / n, source="test")
    sid = "s" + str(len(fim._SESSIONS))
    fim._SESSIONS[sid] = {"result": {"grid": g, "provenance": {"bounds": b}}, "candidate_id": "c", "t": 0}
    return sid, g


@pytest.fixture
def fake(monkeypatch):
    f = FakeCDSE(_scenes())
    monkeypatch.setattr(sim, "_HTTP", f)
    monkeypatch.setattr(ndvi, "get_access_token", lambda a, b, *k: "tok")
    return f


def test_not_saved_needs_fetch_and_never_fetches_silently(tmp_path, fake):
    sid, _ = _fake_session()
    r = json.loads(sim.open_layer_json(str(tmp_path), sid, "NDVI"))
    assert r["needs_fetch"] and fake.total == 0


def test_fetch_then_reuse_and_rgba_matches_cells(tmp_path, fake):
    sid, g = _fake_session()
    r = json.loads(sim.open_layer_json(str(tmp_path), sid, "THERMAL", "id", "sec", True))
    assert r["allowed"] and r["fetched_now"] and "brightness" in r["caption"].lower()
    p = r["placement"]
    assert p["sx"] > 0 and p["sy"] > 0 and p["x0"] <= 1e-3 and p["y0"] <= 1e-3   # covers the DEM window (bounds rounded to ~1e-6 deg)
    rgba = np.frombuffer(sim.layer_rgba(sid, "THERMAL"), np.uint8)
    w, h = r["grid"]["width"], r["grid"]["height"]
    assert rgba.size == w * h * 4
    calls = fake.calls["process"]
    again = json.loads(sim.open_layer_json(str(tmp_path), sid, "THERMAL"))
    assert again["reused"] and fake.calls["process"] == calls


def test_empty_cells_fully_transparent(tmp_path, fake):
    sid, _ = _fake_session()
    r = json.loads(sim.open_layer_json(str(tmp_path), sid, "NDVI", "id", "sec", True))
    a = np.frombuffer(sim.layer_rgba(sid, "NDVI"), np.uint8).reshape(r["grid"]["height"], r["grid"]["width"], 4)
    empty = a[..., 3] == 0
    assert empty.any() and (a[empty] == 0).all()


def test_failed_self_check_hides_layer(tmp_path, monkeypatch):
    f = FakeCDSE(_scenes(), stats_offset=50.0)
    monkeypatch.setattr(sim, "_HTTP", f)
    monkeypatch.setattr(ndvi, "get_access_token", lambda a, b, *k: "tok")
    sid, _ = _fake_session()
    r = json.loads(sim.open_layer_json(str(tmp_path), sid, "THERMAL", "id", "sec", True))
    assert not r["allowed"] and "hidden" in r["hidden_reason"]
    with pytest.raises(PermissionError):
        sim.layer_rgba(sid, "THERMAL")


def test_no_login_no_saved_image_is_an_honest_error(tmp_path, fake):
    sid, _ = _fake_session()
    r = json.loads(sim.open_layer_json(str(tmp_path), sid, "SAR_VV", "", "", True))
    assert "Copernicus login" in r["error"] and fake.total == 0


def test_status_lists_all_products(tmp_path, fake):
    sid, _ = _fake_session()
    sim.open_layer_json(str(tmp_path), sid, "SAR_VH", "id", "sec", True)
    st = {p["product"]: p for p in json.loads(sim.layers_status_json(str(tmp_path), sid))["products"]}
    assert list(st) == list(si.PRODUCT_ORDER)
    assert st["SAR_VH"]["saved"] and st["SAR_VH"]["allowed"] and not st["NDVI"]["saved"]
