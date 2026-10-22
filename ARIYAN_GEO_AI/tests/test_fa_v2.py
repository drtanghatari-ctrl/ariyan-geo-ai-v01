"""fa-v2 Filters: smoothing, residual, curvature, slope, direction; strict
support (no invented edge values), DERIVED labels, raw DEM untouched, bridge,
exports with provenance, DERIVED profile trace."""
import ast
import json
import math
import os

import numpy as np
import pytest

import dem_filters as df
import dem_filters_mobile as dfm
import final_image as fi
import final_image_mobile as fim
import profile_section as ps
import profile_section_mobile as psm

CELL = 1 / 3600.0


def _grid(values, lat=32.61, lon=47.31):
    h, w = values.shape
    return fi.Grid(values=values.astype(float), west=lon - w * CELL / 2, north=lat + h * CELL / 2,
                   dlon=CELL, dlat=CELL, source="/tiles/t.tif", source_sha256="cd" * 32)


def _plane(h=40, w=40, ax=0.0, ay=0.0, c=100.0):
    r, cc = np.mgrid[0:h, 0:w]
    return c + ax * cc + ay * r


def _mound(h=41, w=41, amp=5.0, s=4.0):
    r, c = np.mgrid[0:h, 0:w]
    return 100 + amp * np.exp(-((r - h // 2) ** 2 + (c - w // 2) ** 2) / (2 * s * s))


# ---------------------------------------------------------------- honesty

@pytest.mark.parametrize("name,params", [
    ("smooth", {"method": "gaussian", "sigma": 2}), ("smooth", {"method": "median", "size": 5}),
    ("residual", {"radius_m": 60}), ("curvature", {}), ("slope", {}),
    ("direction", {"mode": "aspect"}), ("direction", {"mode": "derivative", "bearing": 45})])
def test_raw_dem_never_changed_and_label_is_derived(name, params):
    z = _mound()
    z[5, 7] = np.nan
    g = _grid(z)
    before = g.values.copy()
    f = df.apply_filter(g, name, params)
    assert np.array_equal(before, g.values, equal_nan=True)
    assert f["label"].startswith("DERIVED: ")
    assert f["legend"]["label"] == f["label"]
    assert f["values"].shape == z.shape and f["image"].shape == z.shape + (4,)
    # transparent exactly where there is no value -> hatched on screen
    assert np.array_equal(f["image"][..., 3] == 0, ~np.isfinite(f["values"]))
    assert f["cells_no_data"] == int((~np.isfinite(f["values"])).sum())


def test_strict_support_border_and_gaps_are_no_data_not_guessed():
    z = _plane(30, 30, 1.0, 0.5)
    z[15, 15] = np.nan
    f = df.apply_filter(_grid(z), "smooth", {"method": "gaussian", "sigma": 1})
    r = f["border_cells"]
    v = f["values"]
    assert r >= 3
    assert np.isnan(v[:3]).all() and np.isnan(v[:, -3:]).all()
    assert np.isnan(v[12:19, 12:19]).all()                       # around the gap
    assert np.isfinite(v[r:-r, r:r + 5]).all()


def test_support_mask_matches_brute_force():
    rng = np.random.default_rng(3)
    z = rng.normal(size=(12, 15))
    z[rng.random(z.shape) < 0.1] = np.nan
    m = df.support_mask(z, 2, 1)
    for i in range(12):
        for j in range(15):
            inside = 2 <= i < 10 and 1 <= j < 14
            exp = inside and np.isfinite(z[i - 2:i + 3, j - 1:j + 2]).all()
            assert m[i, j] == exp


def test_module_never_touches_the_database_or_scoring():
    for mod in (df, dfm):
        tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
        names = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                 for a in n.names} | {n.module for n in ast.walk(tree)
                                      if isinstance(n, ast.ImportFrom) and n.module}
        assert not any(("db" in x or "review" in x or "steward" in x or "score" in x)
                       for x in names), names


# ---------------------------------------------------------------- maths

def test_gaussian_and_median_keep_a_plane_and_median_kills_a_spike():
    z = _plane(30, 30, 0.5, -0.25)
    g = df.gaussian(z, 2)[0]
    ok = np.isfinite(g)
    assert np.allclose(g[ok], z[ok], atol=1e-9)
    z2 = np.full((20, 20), 50.0)
    z2[10, 10] = 80.0
    m = df.median(z2, 3)[0]
    assert m[10, 10] == 50.0
    assert df.gaussian(z2, 1)[0][10, 10] < 80.0


def test_residual_of_plane_is_zero_and_mound_positive():
    z = _plane(50, 50, 0.3, 0.2)
    for rad in df.RESIDUAL_RADII_M:
        v = df.apply_filter(_grid(z), "residual", {"radius_m": rad})["values"]
        assert np.nanmax(np.abs(v)) < 1e-9
    v = df.apply_filter(_grid(_mound()), "residual", {"radius_m": 150})["values"]
    assert v[20, 20] > 1.0


def test_residual_radius_sets_window_in_cells():
    g = _grid(_plane(60, 60))
    dx, dy = g.cell_size_m()
    f = df.apply_filter(g, "residual", {"radius_m": 300})
    assert f["border_cells"] == max(round(300 / dx), round(300 / dy))


def test_curvature_convex_mound_warm_concave_pit_cool():
    m = df.apply_filter(_grid(_mound()), "curvature", {"smooth_sigma": 1})
    assert m["values"][20, 20] > 0
    pit = df.apply_filter(_grid(200 - _mound()), "curvature", {"smooth_sigma": 0})
    assert pit["values"][20, 20] < 0
    assert df.apply_filter(_grid(_plane(30, 30, 1, 1)), "curvature", {"smooth_sigma": 0})["values"][15, 15] \
        == pytest.approx(0, abs=1e-9)


def test_slope_of_known_plane():
    g = _grid(_plane(20, 20, 0, 0))
    dx, _ = g.cell_size_m()
    g = _grid(_plane(20, 20, dx * math.tan(math.radians(10)), 0))   # rises 10 deg eastward
    v = df.apply_filter(g, "slope", {})["values"]
    assert v[10, 10] == pytest.approx(10.0, abs=1e-6)
    assert np.isnan(v[0, 5]) and np.isnan(v[5, -1])


@pytest.mark.parametrize("ax,ay,expect", [(1.0, 0, 270.0), (-1.0, 0, 90.0), (0, -1.0, 180.0), (0, 1.0, 0.0)])
def test_aspect_is_downslope_bearing(ax, ay, expect):
    # ay>0: values grow southward (rows go south) -> ground falls to the north
    asp, flat = df.aspect(_plane(10, 10, ax, ay), 30.0, 30.0)
    d = (asp[5, 5] - expect + 180) % 360 - 180
    assert abs(d) < 1e-6 and not flat[5, 5]


def test_flat_aspect_is_grey_not_no_data():
    f = df.apply_filter(_grid(np.full((10, 10), 7.0)), "direction", {"mode": "aspect"})
    assert f["flat_cells"] == 64 and f["image"][5, 5, 3] == 255
    assert tuple(f["image"][5, 5, :3]) == df.FLAT_RGB


def test_directional_derivative_sign_and_units():
    g = _grid(_plane(20, 20, 0, 0))
    dx, dy = g.cell_size_m()
    g = _grid(_plane(20, 20, 0.01 * dx, 0))                  # 1 m per 100 m toward east
    e = df.apply_filter(g, "direction", {"mode": "derivative", "bearing": 90})["values"]
    n = df.apply_filter(g, "direction", {"mode": "derivative", "bearing": 0})["values"]
    assert e[10, 10] == pytest.approx(1.0, abs=1e-9) and n[10, 10] == pytest.approx(0.0, abs=1e-9)


def test_unknown_settings_are_refused_not_replaced():
    g = _grid(_plane())
    for name, p in [("blur", {}), ("smooth", {"method": "gaussian", "sigma": 4}),
                    ("smooth", {"method": "median", "size": 4}), ("residual", {"radius_m": 200}),
                    ("direction", {"mode": "derivative", "bearing": 30}), ("curvature", {"smooth_sigma": 5})]:
        with pytest.raises(ValueError):
            df.apply_filter(g, name, p)


def test_labels_carry_settings():
    assert df.label("residual", {"radius_m": 60.0}) == "DERIVED: Residual relief (radius 60 m)"
    assert "median 5\u00d75" in df.label("smooth", {"method": "median", "size": 5})
    assert "bearing 135" in df.label("direction", {"mode": "derivative", "bearing": 135.0})


# ---------------------------------------------------------------- bridge, export, profile

def _session(z):
    g = _grid(z)
    sid = "fa2" + str(len(fim._SESSIONS))
    res = {"grid": g, "provenance": {"parameters": {"relief_radius_m": 300.0}}}
    fim._SESSIONS[sid] = {"result": res, "candidate_id": "09a8862dzz", "t": 0,
                          "markers": [], "focus": (z.shape[1] / 2, z.shape[0] / 2)}
    return sid


def test_bridge_open_rgba_export(tmp_path):
    sid = _session(_mound())
    o = json.loads(dfm.options_json())
    assert o["filters"] == list(df.FILTERS)
    r = json.loads(dfm.open_filter_json(sid, "slope", "{}"))
    assert r["ok"] and r["label"].startswith("DERIVED") and r["placement"]["sx"] == 1.0
    b = dfm.filter_rgba(sid)
    assert len(b) == r["width"] * r["height"] * 4
    e = json.loads(dfm.export_filter_json(str(tmp_path), sid))
    assert e["ok"] and "derived_slope" in os.path.basename(e["paths"]["png"])
    prov = json.load(open(e["paths"]["provenance"], encoding="utf-8"))
    assert prov["derived"] is True and prov["label"].startswith("DERIVED")
    assert prov["source_sha256"] == "cd" * 32 and "raw DEM not modified" in prov["method_rules"]
    import hashlib
    assert prov["outputs"]["png_sha256"] == hashlib.sha256(open(e["paths"]["png"], "rb").read()).hexdigest()
    assert "error" in json.loads(dfm.open_filter_json(sid, "smooth", '{"sigma": 9}'))
    assert "error" in json.loads(dfm.open_filter_json("nope", "slope"))
    dfm.close_filter(sid)
    assert "no filter" in json.loads(dfm.export_filter_json(str(tmp_path), sid))["error"]


def test_profile_derived_trace_is_filter_value_of_each_cell(tmp_path):
    z = _mound()
    sid = _session(z)
    assert "error" in json.loads(psm.profile_json(sid, 0, 20.5, 41, 20.5, "DERIVED"))  # none on
    dfm.open_filter_json(sid, "residual", '{"radius_m": 60}')
    p = json.loads(psm.profile_json(sid, 0, 20.5, 41, 20.5, "DERIVED"))
    d = p["derived"]
    v = dfm.active(sid)["values"]
    assert d["label"].startswith("DERIVED") and "sat" not in p
    for c, r, val in zip(d["steps"]["col"], d["steps"]["row"], d["steps"]["value"]):
        assert (val is None) == (not np.isfinite(v[r, c]))
        if val is not None:
            assert val == pytest.approx(v[r, c], abs=1e-4)
    e = json.loads(psm.export_profile_json(str(tmp_path), sid, 0, 20.5, 41, 20.5, "DERIVED"))
    assert e["ok"] and "derived_csv" in e["paths"]
    assert open(e["paths"]["derived_csv"], encoding="utf-8").readline().startswith("# DERIVED")
    prov = json.load(open(e["paths"]["provenance"], encoding="utf-8"))
    assert prov["derived"]["filter"] == "residual"
    # plain profile still works and has no derived trace
    assert "derived" not in json.loads(psm.profile_json(sid, 0, 20.5, 41, 20.5))


def test_ascii_text_is_font_safe():
    s = ps.ascii_text("DERIVED: Smoothed elevation (Gaussian \u03c3=2 cells)")
    assert all(ch in ps._FONT_ROWS for ch in s)
    assert "SIGMA=2" in s
