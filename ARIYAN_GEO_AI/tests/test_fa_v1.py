"""fa-v1 Profile & Section: exact-cell traces, relief, satellite, candidates,
vertical exaggeration, exports with provenance, bridge."""
import csv
import hashlib
import io
import json
import math

import numpy as np
import pytest

import final_image as fi
import final_image_mobile as fim
import profile_section as ps
import profile_section_mobile as psm
import sat_image_mobile as sim
from test_fi_v1 import _png_pixels


# ---------------------------------------------------------------- lattice walk

def test_horizontal_line_hits_every_cell_once_full_length():
    cells = ps.cells_crossed(0.0, 2.5, 10.0, 2.5, 10, 5)
    assert [c for c, r, *_ in cells] == list(range(10))
    assert all(r == 2 for _, r, *_ in cells)
    assert cells[0][2] == 0.0 and cells[-1][3] == 1.0
    assert all(abs((t1 - t0) - 0.1) < 1e-12 for *_, t0, t1 in cells)


def test_diagonal_through_corners_has_no_zero_length_steps():
    cells = ps.cells_crossed(0.0, 0.0, 4.0, 4.0, 4, 4)
    assert [(c, r) for c, r, *_ in cells] == [(0, 0), (1, 1), (2, 2), (3, 3)]


def test_general_line_is_connected_and_covers_its_length():
    rng = np.random.default_rng(1)
    for _ in range(50):
        x0, y0, x1, y1 = rng.uniform(0, 20, 4)
        cells = ps.cells_crossed(x0, y0, x1, y1, 20, 20)
        assert abs(cells[0][2]) < 1e-12 and abs(cells[-1][3] - 1) < 1e-12
        for a, b in zip(cells[:-1], cells[1:]):
            assert abs(a[3] - b[2]) < 1e-12                       # contiguous in t
            assert abs(a[0] - b[0]) + abs(a[1] - b[1]) in (1, 2)  # neighbours
        for c, r, t0, t1 in cells:                                # midpoint really inside
            m = 0.5 * (t0 + t1)
            assert c <= x0 + m * (x1 - x0) <= c + 1 and r <= y0 + m * (y1 - y0) <= r + 1


def test_line_outside_or_partly_outside_is_clipped():
    assert ps.cells_crossed(-5, -5, -1, -1, 4, 4) == []
    cells = ps.cells_crossed(-2.0, 0.5, 6.0, 0.5, 4, 1)
    assert [c for c, *_ in cells] == [0, 1, 2, 3]
    assert abs(cells[0][2] - 0.25) < 1e-12 and abs(cells[-1][3] - 0.75) < 1e-12


# ---------------------------------------------------------------- profile

def _result(values, lat=32.45, lon=47.27, cell_deg=1 / 3600.0, radius=300.0):
    h, w = values.shape
    g = fi.Grid(values=values.astype(float), west=lon - w * cell_deg / 2, north=lat + h * cell_deg / 2,
                dlon=cell_deg, dlat=cell_deg, source="/tiles/test.tif", source_sha256="ab" * 32)
    return {"grid": g, "provenance": {"parameters": {"relief_radius_m": radius}}}


def test_elevation_steps_are_exact_cell_values_no_interpolation():
    z = np.arange(30 * 30, dtype=float).reshape(30, 30)
    res = _result(z)
    p = ps.build_profile(res, 0.0, 10.5, 30.0, 10.5)
    assert p["dem"]["elevation"] == [float(v) for v in z[10]]
    assert p["dem"]["col"] == list(range(30)) and set(p["dem"]["row"]) == {10}
    # every value is a real cell value, never a blend
    p2 = ps.build_profile(res, 0.3, 0.7, 29.1, 27.9)
    vals = set(z.ravel().tolist())
    assert all(v in vals for v in p2["dem"]["elevation"])


def test_step_lengths_are_the_line_inside_each_cell_and_sum_to_length():
    res = _result(np.zeros((40, 40)))
    p = ps.build_profile(res, 1.2, 3.4, 37.9, 35.1)
    d0, d1 = p["dem"]["d0"], p["dem"]["d1"]
    assert d0[0] == 0.0 and abs(d1[-1] - p["length_m"]) < 0.01
    assert all(abs(a - b) < 1e-6 for a, b in zip(d1[:-1], d0[1:]))
    assert all(b > a for a, b in zip(d0, d1))


def test_length_matches_utm_and_cell_size():
    res = _result(np.zeros((60, 60)))
    p = ps.build_profile(res, 0.0, 30.0, 60.0, 30.0)
    dx, _ = res["grid"].cell_size_m()
    assert abs(p["length_m"] - 60 * dx) / (60 * dx) < 2e-3
    assert abs(p["bearing_deg"] - 90.0) < 1.5            # W->E (UTM grid convergence)


def test_no_data_cells_are_gaps_not_filled():
    z = np.ones((20, 20)) * 100.0
    z[10, 5:8] = np.nan
    p = ps.build_profile(_result(z), 0.0, 10.5, 20.0, 10.5)
    assert p["dem"]["elevation"][5:8] == [None, None, None]
    assert p["cells_no_data"] == 3
    json.dumps(p, allow_nan=False)                        # no NaN reaches Kotlin


def test_relief_trace_is_the_colour_map_measure():
    z = np.zeros((61, 61))
    z[28:33, 28:33] = 5.0                                 # a 5 m mound
    res = _result(z)
    p = ps.build_profile(res, 0.0, 30.5, 61.0, 30.5)
    dx, dy = res["grid"].cell_size_m()
    expect = fi.local_relief(z, dx, dy, 300.0)[30]
    assert p["dem"]["relief"] == [round(float(v), 3) for v in expect]
    i = p["dem"]["col"].index(30)
    assert p["dem"]["relief"][i] > 0 and p["relief_radius_m"] == 300.0


def test_line_beyond_window_is_trimmed_to_the_image():
    res = _result(np.zeros((20, 20)))
    p = ps.build_profile(res, -10.0, 5.5, 30.0, 5.5)
    assert p["a"]["x"] == 0.0 and p["b"]["x"] == 20.0
    with pytest.raises(ValueError):
        ps.build_profile(res, -10, -10, -5, -5)


def test_presets_cross_whole_window_through_focus():
    g = _result(np.zeros((50, 40)))["grid"]
    assert ps.preset_line(g, 12.3, 20.0, "NS") == (12.3, 0.0, 12.3, 50.0)
    assert ps.preset_line(g, 12.3, 20.0, "E-W") == (0.0, 20.0, 40.0, 20.0)
    with pytest.raises(ValueError):
        ps.preset_line(g, 1, 1, "diag")


def test_candidates_within_50m_marked_with_stored_status():
    res = _result(np.zeros((60, 60)))
    g = res["grid"]
    dx, dy = g.cell_size_m()
    markers = [
        {"id": "near0001aa", "x": 20.0, "y": 30.0 + 40.0 / dy, "status": "Open",
         "confidence_label": "HIGH", "style": "high", "focus": True},
        {"id": "far00002bb", "x": 40.0, "y": 30.0 + 80.0 / dy, "status": "Rejected",
         "confidence_label": "LOW", "style": "rejected"},
        {"id": "onlin003cc", "x": 45.0, "y": 30.0, "status": "Rejected", "confidence_label": "LOW",
         "style": "rejected"},
    ]
    p = ps.build_profile(res, 0.0, 30.0, 60.0, 30.0, markers=markers)
    ids = [c["id"] for c in p["candidates"]]
    assert ids == ["near0001aa", "onlin003cc"]
    near = p["candidates"][0]
    assert abs(near["offset_m"] - 40.0) < 1.0 and near["side"] == "right"   # south of a W->E line
    assert abs(near["d_m"] - 20 * dx) < 2.0
    assert near["status"] == "Open" and near["confidence_label"] == "HIGH" and near["focus"]
    assert p["candidates"][1]["side"] == "on" and p["candidates"][1]["status"] == "Rejected"
    assert markers[1]["status"] == "Rejected"            # untouched


def test_axis_range_never_inflates_flat_terrain_and_ve_formula():
    assert ps.axis_range([100.0, 100.0]) == (98.9, 101.1)
    lo, hi = ps.axis_range([0.25, 0.25], min_span=1e-6)
    assert hi > lo
    lo, hi = ps.axis_range([0.0, 50.0])
    assert lo < 0 and hi > 50
    assert ps.vertical_exaggeration(1000.0, (0.0, 10.0), 1000, 100) == pytest.approx(10.0)
    assert ps.vertical_exaggeration(1000.0, (0.0, 100.0), 1000, 100) == pytest.approx(1.0)


def test_value_at_reads_the_cell_under_the_point():
    z = np.arange(20 * 20, dtype=float).reshape(20, 20)
    p = ps.build_profile(_result(z), 0.0, 4.5, 20.0, 4.5)
    step = p["length_m"] / 20
    r = ps.value_at(p, step * 7.5)
    assert r["col"] == 7 and r["row"] == 4 and r["elevation"] == z[4, 7]
    assert abs(r["x"] - 7.5) < 1e-6 and abs(r["y"] - 4.5) < 1e-9
    a, b = p["a"], p["b"]
    assert min(a["easting"], b["easting"]) <= r["easting"] <= max(a["easting"], b["easting"])
    assert ps.value_at(p, -5)["col"] == 0 and ps.value_at(p, 1e9)["col"] == 19


# ---------------------------------------------------------------- satellite

def _sat_dict(values, place):
    return {"product": "NDVI", "label": "NDVI", "units": None, "scene_date": "2026-10-16",
            "values": values, "placement": place, "provenance": {"sha256": "cd" * 32}}


def test_satellite_trace_on_its_own_cells():
    z = np.zeros((30, 30))
    res = _result(z)
    sv = np.arange(90 * 90, dtype=float).reshape(90, 90) / 1000.0   # 3x finer than DEM
    sv[45, 10:20] = np.nan
    p = ps.build_profile(res, 0.0, 15.1667, 30.0, 15.1667,
                         sat=_sat_dict(sv, {"x0": 0.0, "y0": 0.0, "sx": 1 / 3, "sy": 1 / 3}))
    s = p["sat"]
    assert s["cells"] == 90 and set(s["steps"]["row"]) == {45}
    assert s["steps"]["value"][10:20] == [None] * 10 and s["cells_no_data"] == 10
    assert s["steps"]["value"][30] == round(sv[45, 30], 3)
    assert abs(s["steps"]["d1"][-1] - p["length_m"]) < 0.01
    assert p["cells"] == 30                                  # DEM trace keeps its own cells
    r = ps.value_at(p, p["length_m"] * 30.5 / 90)
    assert r["sat"] == round(sv[45, 30], 3)


def test_satellite_coarser_than_dem_gives_longer_steps():
    res = _result(np.zeros((30, 30)))
    sv = np.arange(9.0).reshape(3, 3)
    p = ps.build_profile(res, 0.0, 15.0, 30.0, 15.0,
                         sat=_sat_dict(sv, {"x0": 0.0, "y0": 0.0, "sx": 10.0, "sy": 10.0}))
    assert p["sat"]["steps"]["value"] == [3.0, 4.0, 5.0]


# ---------------------------------------------------------------- export

def test_export_csv_png_provenance(tmp_path):
    z = np.arange(30 * 30, dtype=float).reshape(30, 30)
    z[12, 3] = np.nan
    res = _result(z)
    sv = np.full((30, 30), 0.25)
    p = ps.build_profile(res, 0.0, 12.5, 30.0, 12.5,
                         markers=[{"id": "cand1234xyz", "x": 15.0, "y": 12.5, "status": "Open",
                                   "confidence_label": "MODERATE", "style": "moderate"}],
                         sat=_sat_dict(sv, {"x0": 0.0, "y0": 0.0, "sx": 1.0, "sy": 1.0}))
    paths = ps.export_profile(p, res["grid"], str(tmp_path), "prof", "2026-10-21T10:00:00Z")
    rows = list(csv.DictReader(open(paths["csv"])))
    assert len(rows) == 30 and rows[3]["elevation_m"] == ""
    assert float(rows[5]["elevation_m"]) == z[12, 5] and rows[5]["col"] == "5"
    lat = float(rows[0]["cell_centre_lat"])
    assert abs(lat - res["grid"].pixel_to_lonlat(0.5, 12.5)[1]) < 1e-7
    srows = list(csv.DictReader(open(paths["sat_csv"])))
    assert len(srows) == 30 and float(srows[0]["ndvi_value"]) == 0.25
    png = open(paths["png"], "rb").read()
    px = _png_pixels(png)
    assert px.shape[1] == 1400 and (px[..., :3] < 100).any()       # something drawn
    prov = json.load(open(paths["provenance"]))
    assert prov["source_sha256"] == "ab" * 32 and prov["synthetic_data"] is False
    assert prov["outputs"]["png_sha256"] == hashlib.sha256(png).hexdigest()
    assert prov["outputs"]["csv_sha256"] == hashlib.sha256(open(paths["csv"], "rb").read()).hexdigest()
    assert set(prov["parameters"]["vertical_exaggeration"]) == {"elevation", "relief"}   # no VE for non-metre sat values
    assert prov["candidates_marked"][0]["id"] == "cand1234xyz"
    assert "nothing downloaded" in prov["satellite"]["note"]


def test_font_covers_every_char_used_in_png_text():
    p = ps.build_profile(_result(np.zeros((10, 10))), 0, 5, 10, 5)
    text = " ".join(ps._prov_lines(p, "2026-10-21T10:00:00Z")).upper()
    text += "PROFILE A-A' BEARING ELEVATION (M) RELIEF M ABOVE/BELOW SURROUNDINGS, R=300 VE X1.5"
    missing = {c for c in text if c not in ps._FONT}
    assert not missing


# ---------------------------------------------------------------- bridge

def _session(z):
    res = _result(z)
    res["provenance"]["bounds"] = {}
    sid = "fa" + str(len(fim._SESSIONS))
    fim._SESSIONS[sid] = {"result": res, "candidate_id": "cand0001zz", "t": 0,
                          "markers": [{"id": "cand0001zz", "x": 10.0, "y": 8.0, "status": "Open",
                                       "confidence_label": "HIGH", "style": "high", "focus": True}],
                          "focus": (10.0, 8.0)}
    return sid


def test_bridge_profile_and_presets():
    sid = _session(np.arange(400, dtype=float).reshape(20, 20))
    p = json.loads(psm.profile_json(sid, 0, 8.5, 20, 8.5))
    assert p["cells"] == 20 and p["candidates"][0]["focus"]
    ns = json.loads(psm.preset_profile_json(sid, "NS"))
    assert ns["preset"] == "NS" and set(ns["dem"]["col"]) == {10} and ns["cells"] == 20
    ew = json.loads(psm.preset_profile_json(sid, "EW"))
    assert set(ew["dem"]["row"]) == {8}


def test_bridge_satellite_only_if_already_open_never_downloads():
    sid = _session(np.zeros((20, 20)))
    r = json.loads(psm.profile_json(sid, 0, 5, 20, 5, "THERMAL"))
    assert "not open" in r["error"] and "never downloads" in r["error"]
    sim._LAYERS[sid] = {"THERMAL": {"values": np.full((20, 20), 318.0), "payload": {
        "allowed": True, "label": "Thermal", "unit": "K", "scene_date": "2026-09-26",
        "placement": {"x0": 0, "y0": 0, "sx": 1, "sy": 1}, "legend": {"vmin": 317, "vmax": 320},
        "pixel_m": 30, "provenance": {}}}}
    try:
        r = json.loads(psm.profile_json(sid, 0, 5, 20, 5, "THERMAL"))
        assert r["sat"]["steps"]["value"][0] == 318.0 and r["sat"]["units"] == "K"
        sim._LAYERS[sid]["THERMAL"]["payload"]["allowed"] = False
        assert "self-check" in json.loads(psm.profile_json(sid, 0, 5, 20, 5, "THERMAL"))["error"]
    finally:
        sim._LAYERS.pop(sid, None)


def test_bridge_export_and_errors(tmp_path):
    sid = _session(np.ones((20, 20)))
    r = json.loads(psm.export_profile_json(str(tmp_path), sid, 0, 3, 20, 17))
    assert r["ok"] and r["paths"]["png"].endswith(".png") and "/exports/profile/" in r["paths"]["csv"]
    assert "expired" in json.loads(psm.profile_json("nope", 0, 0, 1, 1))["error"]
    assert "error" in json.loads(psm.profile_json(sid, -9, -9, -8, -8))


# ---- fa-v1.1 (2026-10-22): candidate labels never stack ----------------------
from profile_section import layout_labels, _fmt  # noqa: E402

_W = lambda t: 6 * len(t)


def _no_overlap(labels, gap=0):
    by_row = {}
    for o in labels:
        by_row.setdefault(o["row"], []).append((o["x"], o["x"] + _W(o["text"])))
    for spans in by_row.values():
        spans.sort()
        for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
            assert a1 + gap <= b0, (spans,)


def test_labels_close_together_use_separate_rows():
    xs = [300.0, 310.0, 320.0]
    out = layout_labels(xs, ["09a8862d", "1b2c3d4e", "77aa0011"], _W, 0, 600)
    assert sorted(o["row"] for o in out) == [0, 1, 2]
    assert sorted(m for o in out for m in o["members"]) == [0, 1, 2]
    _no_overlap(out)


def test_overflow_folds_into_plus_n_and_keeps_every_candidate():
    xs = [300.0 + i for i in range(6)]
    texts = [f"cand{i:04d}" for i in range(6)]
    out = layout_labels(xs, texts, _W, 0, 600, max_rows=3)
    assert len(out) == 3
    assert sorted(m for o in out for m in o["members"]) == list(range(6))
    assert any("+" in o["text"] for o in out)
    _no_overlap(out)


def test_label_near_right_edge_flips_left_and_stays_inside():
    out = layout_labels([598.0], ["09a8862d"], _W, 0, 600)
    assert out[0]["x"] + _W(out[0]["text"]) <= 600
    assert out[0]["x"] < 598


def test_focus_candidate_gets_first_row():
    xs = [100.0, 105.0]
    out = layout_labels(xs, ["aaaa", "bbbb"], _W, 0, 600, max_rows=1, focus=[False, True])
    assert out[0]["members"][0] == 1 and out[0]["text"] == "bbbb +1"


def test_far_apart_labels_share_row_zero():
    out = layout_labels([50.0, 300.0, 550.0], ["aaaa", "bbbb", "cccc"], _W, 0, 600)
    assert all(o["row"] == 0 for o in out)


def test_fmt_has_no_negative_zero():
    assert _fmt(-0.0) == "0" and _fmt(-1e-12) == "0"
