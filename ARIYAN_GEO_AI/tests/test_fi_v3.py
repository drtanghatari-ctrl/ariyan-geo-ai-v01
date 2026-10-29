"""fi-v3 (2026-10-29): Sentinel-2 true-colour layer. No network: the fi-v2
fake Copernicus answers. Synthetic rasters are test fixtures only."""
import json

import numpy as np
import pytest

import ndvi_source_mobile as ndvi
import profile_section_mobile as psm
import sat_image as si
import sat_image_mobile as sim
from test_fi_v2 import FakeCDSE, _scenes, B
from test_fi_v2_mobile import _fake_session


def _q(v):
    """Python mirror of the evalscript's q(): clamp to 0..0.5, 255 steps."""
    x = min(max(v, 0.0), si.TC_FULL_SCALE) / si.TC_FULL_SCALE
    return int(np.floor(x * 255 + 0.5))          # JS Math.round on non-negatives


def _pack(r, g, b):
    return _q(r) * 65536 + _q(g) * 256 + _q(b)


def _tc_array():
    a = np.full((6, 6), float(_pack(0.21, 0.17, 0.12)), np.float32)   # bare soil
    a[2, :] = float(_pack(0.05, 0.09, 0.04))                           # a green strip
    a[0, 0] = np.nan                                                   # cloud cell
    return a


def _scenes_tc():
    s = _scenes()
    s["TRUE_COLOR"] = {"2026-08-01": (_tc_array(), 1.0)}
    return s


@pytest.fixture
def fake(monkeypatch):
    f = FakeCDSE(_scenes_tc())
    monkeypatch.setattr(sim, "_HTTP", f)
    monkeypatch.setattr(ndvi, "get_access_token", lambda a, b, *k: "tok")
    return f


def test_packing_is_exact_in_float32():
    top = _pack(9, 9, 9)                         # clamps to 255, 255, 255
    assert top == 2 ** 24 - 1
    assert float(np.float32(top)) == top
    assert float(np.float32(_pack(0.21, 0.17, 0.12))) == _pack(0.21, 0.17, 0.12)


def test_decode_round_trip_within_one_step():
    v = np.array([[_pack(0.21, 0.17, 0.12), np.nan]], dtype=np.float32)
    rgb = si.decode_true_color(v)
    assert rgb.shape == (1, 2, 3)
    assert np.allclose(rgb[0, 0], [0.21, 0.17, 0.12], atol=si.TC_FULL_SCALE / 255)
    assert np.isnan(rgb[0, 1]).all()


def test_evalscript_uses_rgb_bands_and_ndvi_cloud_mask():
    es = si.process_evalscript("TRUE_COLOR")
    for band in ("B02", "B03", "B04", "SCL", "dataMask"):
        assert band in es
    assert "[0, 1, 3, 8, 9, 10, 11]" in es and "[0, 1, 3, 8, 9, 10, 11]" in si.PRODUCTS["NDVI"]["js"]
    assert si.PRODUCTS["TRUE_COLOR"]["collection"] == si.PRODUCTS["NDVI"]["collection"]
    assert si.PRODUCTS["TRUE_COLOR"]["uses_cloud"]          # clearest scene first, like NDVI


def test_menu_order_and_auto_run_unchanged():
    assert si.LAYER_ORDER[0] == "TRUE_COLOR"
    assert "TRUE_COLOR" not in si.PRODUCT_ORDER             # Auto run images step unchanged
    assert set(si.LAYER_ORDER) == set(si.PRODUCTS)


def test_one_stretch_for_all_bands_keeps_colour_balance():
    v = _tc_array()
    lo, hi = si.display_range("TRUE_COLOR", v)
    rgb = si.decode_true_color(v)
    f = rgb[np.isfinite(rgb)]
    assert lo == pytest.approx(np.percentile(f, 2)) and hi == pytest.approx(np.percentile(f, 98))
    out = si.colorize("TRUE_COLOR", v, lo, hi)
    soil, green = out[1, 1], out[2, 1]
    assert soil[0] > soil[1] > soil[2]                      # reddish-brown stays reddish-brown
    assert green[1] > green[0] and green[1] > green[2]      # vegetation stays green
    assert (out[0, 0] == 0).all()                           # cloud cell fully transparent


def test_fetch_self_check_and_payload_in_reflectance(tmp_path, fake):
    img = si.ensure_layer(str(tmp_path), "TRUE_COLOR", B, "tok", fake)
    assert img["allowed"] and fake.calls["stats"] == 1
    pl = si.layer_payload("TRUE_COLOR", img)
    assert pl["kind"] == "rgb" and pl["unit"] == "reflectance"
    assert 0.0 <= pl["legend"]["data_min"] < pl["legend"]["data_max"] <= si.TC_FULL_SCALE
    assert "not evidence" in pl["caption"]
    calls = dict(fake.calls)
    si.ensure_layer(str(tmp_path), "TRUE_COLOR", B, "tok", fake)  # save-once: nothing re-sent
    assert fake.calls == calls


def test_failed_self_check_hides_true_colour(tmp_path, monkeypatch):
    f = FakeCDSE(_scenes_tc(), stats_offset=5000.0)
    img = si.ensure_layer(str(tmp_path), "TRUE_COLOR", B, "tok", f)
    assert not img["allowed"]


def test_mobile_layer_draws_real_colours(tmp_path, fake):
    sid, _ = _fake_session()
    r = json.loads(sim.open_layer_json(str(tmp_path), sid, "TRUE_COLOR", "id", "sec", True))
    assert r["allowed"] and r["product"] == "TRUE_COLOR"
    a = np.frombuffer(sim.layer_rgba(sid, "TRUE_COLOR"), np.uint8).reshape(
        r["grid"]["height"], r["grid"]["width"], 4)
    shown = a[a[..., 3] == 255]
    assert shown.size and len({tuple(px[:3]) for px in shown}) >= 2   # soil and green both drawn
    empty = a[..., 3] == 0
    assert empty.any() and (a[empty] == 0).all()
    st = json.loads(sim.layers_status_json(str(tmp_path), sid))["products"]
    assert st[0]["product"] == "TRUE_COLOR" and st[0]["saved"]


def test_profile_never_traces_the_photo():
    assert psm._sat("any-session", "TRUE_COLOR") is None
