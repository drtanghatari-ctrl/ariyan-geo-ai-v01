"""fi-v1 (2026-10-16): Final Image engine core. Real DEM only, exact-cell
zoom by default, vector overlays, export with provenance. Synthetic tiles in
the Copernicus file format (float32, Predictor 3, deflate, PixelIsPoint) are
used ONLY as test fixtures."""
import hashlib
import json
import os
import struct
import zlib

import numpy as np
import pytest

import final_image as fi
import offline_dem_store as ods
from geotiff_cog_reader import CopernicusDemTile

LA, LO = 33, 51          # tile SW corner (Kashan area)
S = 1200                 # pixels per degree in the test tile (3 arc-second spacing)


def _encode(block):
    be = block.astype(">f4").view(np.uint8).reshape(block.shape[0], block.shape[1], 4)
    planes = be.transpose(0, 2, 1).reshape(block.shape[0], -1)
    diff = planes.copy()
    diff[:, 1:] = (planes[:, 1:].astype(np.int16) - planes[:, :-1]).astype(np.uint8)
    return zlib.compress(diff.tobytes(), 6)


def write_tile(path, arr, tw=16):
    tiles = [_encode(arr[a:a + tw, b:b + tw]) for a in range(0, S, tw) for b in range(0, S, tw)]
    tags = [
        (256, 3, [S]), (257, 3, [S]), (258, 3, [32]), (259, 3, [8]),
        (277, 3, [1]), (317, 3, [3]), (322, 3, [tw]), (323, 3, [tw]),
        (324, 4, None), (325, 4, [len(t) for t in tiles]), (339, 3, [3]),
        (33550, 12, [1.0 / S, 1.0 / S, 0.0]),
        (33922, 12, [0.0, 0.0, 0.0, float(LO), float(LA + 1), 0.0]),
        (34735, 3, [1, 1, 0, 2, 1024, 0, 1, 2, 1025, 0, 1, 2]),
    ]
    fmt = {3: "H", 4: "I", 12: "d"}
    size_of = {3: 2, 4: 4, 12: 8}
    entries = [[t, ty, v if v is not None else [0] * len(tiles)] for t, ty, v in tags]
    extra_off = 8 + 2 + len(entries) * 12 + 4
    ext_len = sum(len(v) * size_of[t] for _, t, v in entries if len(v) * size_of[t] > 4)
    o, offs = extra_off + ext_len, []
    for t in tiles:
        offs.append(o)
        o += len(t)
    for e in entries:
        if e[0] == 324:
            e[2] = offs
    ifd, extra = bytearray(struct.pack("<H", len(entries))), bytearray()
    for tag, typ, vals in entries:
        raw = struct.pack("<" + fmt[typ] * len(vals), *vals)
        if len(raw) <= 4:
            ifd += struct.pack("<HHI", tag, typ, len(vals)) + raw.ljust(4, b"\0")
        else:
            ifd += struct.pack("<HHII", tag, typ, len(vals), extra_off + len(extra))
            extra += raw
    ifd += struct.pack("<I", 0)
    with open(path, "wb") as f:
        f.write(b"II" + struct.pack("<HI", 42, 8) + ifd + extra + b"".join(tiles))


P = 600                  # mound peak cell (row, col)


def mound_tile():
    r, c = np.mgrid[0:S, 0:S].astype(np.float64)
    base = 900.0 + 0.05 * r                      # gentle plain sloping south
    mound = 12.0 * np.exp(-((r - P) ** 2 + (c - P) ** 2) / (2 * 4.0 ** 2))
    return (base + mound).astype(np.float32)


@pytest.fixture
def env(tmp_path):
    ods.clear_tile_cache()
    root = str(tmp_path)
    lat, lon = LA + 0.5, LO + 0.5
    path = ods.local_tile_path("ir", root, lat, lon)
    os.makedirs(os.path.dirname(path))
    arr = mound_tile()
    write_tile(path, arr)
    yield root, path, arr
    ods.clear_tile_cache()


def _centre():
    return LA + 1 - P / S, LO + P / S          # centre of cell (P, P)


def test_version_and_default_mode():
    assert fi.FI_VERSION == "fi-v1"
    assert fi.DEFAULT_MODE == "cells"


def test_window_is_the_real_lattice_no_resampling(env):
    root, path, arr = env
    lat, lon = _centre()
    g = fi.read_dem_window("ir", root, lat, lon, half_size_m=3000)
    fresh = CopernicusDemTile(path)
    h, w = g.shape
    for r, c in [(0, 0), (h // 2, w // 2), (h - 1, w - 1), (3, w - 2)]:
        lo, la = g.pixel_to_lonlat(c + 0.5, r + 0.5)
        assert g.values[r, c] == fresh.get_elevation(lo, la)
    # the mound peak sits exactly on a cell of the window
    x, y = g.lonlat_to_pixel(LO + P / S, LA + 1 - P / S)
    assert g.values[int(y), int(x)] == arr[P, P]
    assert g.source_sha256 == hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_missing_tile_is_an_error_not_a_guess(tmp_path):
    with pytest.raises(FileNotFoundError):
        fi.read_dem_window("ir", str(tmp_path), 33.5, 51.5, 500)


def test_edge_window_is_clipped_never_filled(env):
    root, _, _ = env
    g = fi.read_dem_window("ir", root, LA + 0.999, LO + 0.001, 4000)
    assert any("clipped" in n for n in g.notes)
    assert np.isfinite(g.values).all()


def test_validate_flags_gaps_and_flat():
    v = np.full((10, 10), 5.0)
    g = fi.Grid(v, 0, 1, 0.001, 0.001, "t")
    assert any("flat" in p for p in fi.validate(g))
    v2 = v + np.arange(10)[None, :]
    v2[:, :3] = np.nan
    assert any("only" in p for p in fi.validate(fi.Grid(v2, 0, 1, 0.001, 0.001, "t")))
    assert fi.validate(fi.Grid(np.full((5, 5), np.nan), 0, 1, .001, .001, "t")) == [
        "no DEM measurements in this window"]


def test_hillshade_flat_and_multidirectional_symmetry():
    flat = np.full((9, 9), 100.0)
    hs = fi.hillshade(flat, 30, 30, 315, 45)
    assert np.allclose(hs, np.sin(np.radians(45)))
    r, c = np.mgrid[-10:11, -10:11]
    cone = -np.hypot(r, c) * 3.0
    m = fi.hillshade_multi(cone, 10, 10, azimuths=(0, 90, 180, 270))
    # four evenly spaced suns light a cone the same on all four sides
    assert m[10, 3] == pytest.approx(m[10, 17], abs=1e-9)
    assert m[3, 10] == pytest.approx(m[17, 10], abs=1e-9)


def test_local_relief_mound_positive_plain_zero(env):
    root, _, _ = env
    lat, lon = _centre()
    g = fi.read_dem_window("ir", root, lat, lon, 3000)
    dx, dy = g.cell_size_m()
    lrm = fi.local_relief(g.values, dx, dy, radius_m=1500)
    h, w = g.shape
    assert lrm[h // 2, w // 2] > 8.0
    flat = np.full((20, 20), 50.0)
    assert np.allclose(fi.local_relief(flat, 30, 30, 90), 0.0)


def test_cells_mode_is_exact_blocks_no_new_values():
    img = np.zeros((3, 3, 4), np.uint8)
    img[..., 0] = np.arange(9).reshape(3, 3) * 20
    img[..., 3] = 255
    out = fi.render_view(img, 0, 0, 3, 3, 24, 24, "cells")
    # each cell becomes an 8x8 crisp block, exactly the source value
    for r in range(3):
        for c in range(3):
            blk = out[r * 8:(r + 1) * 8, c * 8:(c + 1) * 8, 0]
            assert (blk == img[r, c, 0]).all()
    assert set(np.unique(out[..., 0])) <= set(np.unique(img[..., 0]))


def test_cells_mode_zoomed_subwindow_and_outside_is_transparent():
    img = np.full((4, 4, 4), 200, np.uint8)
    out = fi.render_view(img, 3, 3, 5, 5, 20, 20, "cells")   # half outside
    assert (out[:10, :10, 3] == 200).all()
    assert (out[10:, :, 3] == 0).all() and (out[:, 10:, 3] == 0).all()


def test_smooth_mode_interpolates_but_never_into_no_data():
    img = np.zeros((1, 2, 4), np.uint8)
    img[0, 0] = [0, 0, 0, 255]
    img[0, 1] = [200, 0, 0, 255]
    out = fi.render_view(img, 0, 0, 2, 1, 8, 1, "smooth")
    vals = out[0, :, 0].astype(int)
    assert vals[0] == 0 and vals[-1] == 200 and (np.diff(vals) >= 0).all()
    assert 0 < vals[4] < 200
    img[0, 1, 3] = 0                       # second cell is "no data"
    out2 = fi.render_view(img, 0, 0, 2, 1, 8, 1, "smooth")
    assert (out2[0, 2:6, 3] == 0).all()    # not smoothed across into a gap


def test_bad_mode_rejected():
    with pytest.raises(ValueError):
        fi.render_view(np.zeros((2, 2, 4), np.uint8), 0, 0, 2, 2, 4, 4, "sharpen")


def test_view_info_states_native_resolution(env):
    root, _, _ = env
    lat, lon = _centre()
    g = fi.read_dem_window("ir", root, lat, lon, 2000)
    info = fi.view_info(g, 10, 14, 400, "cells")
    assert info["beyond_native"] and "exact cells" in info["label"]
    assert info["native_resolution_m"] == g.native_resolution_m()


def test_contours_on_a_plane_are_straight_and_placed_right():
    z = np.tile(np.arange(10, dtype=float) * 10.0, (6, 1))   # rises 10 m per cell eastwards
    segs = fi.contour_segments(z, 45.0)
    assert segs
    for x0, y0, x1, y1 in segs:
        assert x0 == pytest.approx(5.0) and x1 == pytest.approx(5.0)   # between cells 4 and 5
    z[2, 4] = np.nan
    assert all(not (s[1] <= 3 and s[3] >= 2) for s in fi.contour_segments(z, 45.0))
    c = fi.contours(z, 20.0)
    assert c["interval_m"] == 20.0 and [lv["level_m"] for lv in c["levels"]] == [20, 40, 60, 80]


def test_candidate_style_is_read_not_changed(env):
    root, _, _ = env
    lat, lon = _centre()
    g = fi.read_dem_window("ir", root, lat, lon, 2000)
    cands = [
        {"id": "a1", "lat": lat, "lon": lon, "status": "Supported (auto)",
         "confidence_label": "MODERATE", "confidence": 0.55},
        {"id": "b2", "lat": lat + 0.003, "lon": lon, "status": "Rejected (auto)",
         "confidence_label": "LOW", "confidence": 0.35},
        {"id": "far", "lat": lat + 0.5, "lon": lon, "status": "Open"},
    ]
    before = json.dumps(cands, sort_keys=True)
    out = fi.candidate_overlay(g, cands)
    assert [o["id"] for o in out] == ["a1", "b2"]
    assert out[0]["style"] == "moderate" and out[0]["confidence"] == 0.55
    assert out[1]["style"] == "rejected"
    assert json.dumps(cands, sort_keys=True) == before


def test_utm_grid_zone_and_lines(env):
    root, _, _ = env
    lat, lon = _centre()
    g = fi.read_dem_window("ir", root, lat, lon, 3000)
    ug = fi.utm_grid(g)
    assert ug["zone"] == 39 and ug["hemisphere"] == "N"
    axes = {ln["axis"] for ln in ug["lines"]}
    assert axes == {"easting", "northing"}
    assert all(v % ug["spacing_m"] == 0 for v in (ln["value"] for ln in ug["lines"]))


def _png_pixels(b):
    assert b[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(b):
        n = struct.unpack(">I", b[pos:pos + 4])[0]
        tag, data = b[pos + 4:pos + 8], b[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            w, h = struct.unpack(">II", data[:8])
        if tag == b"IDAT":
            idat += data
        pos += 12 + n
    raw = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(h, 1 + w * 4)
    return raw[:, 1:].reshape(h, w, 4)


def test_png_roundtrip():
    rgba = np.random.default_rng(1).integers(0, 256, (7, 5, 4), dtype=np.uint8)
    assert (_png_pixels(fi.encode_png(rgba)) == rgba).all()


def test_build_and_export_with_provenance(env, tmp_path):
    root, path, _ = env
    lat, lon = _centre()
    cands = [{"id": "a1", "lat": lat, "lon": lon, "status": "Open", "confidence_label": "LOW"}]
    res = fi.build_final_image("ir", root, lat, lon, 2500, candidates=cands,
                               created_utc="2026-10-16T08:00:00Z")
    assert res["ok"] and res["version"] == "fi-v1"
    assert res["image"].shape[:2] == res["grid"].shape
    assert res["contours"]["levels"] and res["candidates"][0]["id"] == "a1"
    paths = fi.export_files(res, str(tmp_path / "out"), "fi_test")
    prov = json.load(open(paths["provenance"]))
    assert prov["synthetic_data"] is False and prov["version"] == "fi-v1"
    assert prov["source_sha256"] == hashlib.sha256(open(path, "rb").read()).hexdigest()
    for k, p in (("png_sha256", paths["png"]), ("geotiff_sha256", paths["geotiff"])):
        assert prov["outputs"][k] == hashlib.sha256(open(p, "rb").read()).hexdigest()
    assert (_png_pixels(open(paths["png"], "rb").read()) == res["image"]).all()


def test_geotiff_is_georeferenced_and_holds_the_pixels(env):
    root, _, _ = env
    lat, lon = _centre()
    res = fi.build_final_image("ir", root, lat, lon, 1500)
    b = fi.encode_geotiff(res["grid"], res["image"])
    assert b[:4] == b"II*\x00"
    off = struct.unpack("<I", b[4:8])[0]
    n = struct.unpack("<H", b[off:off + 2])[0]
    tags = {}
    for i in range(n):
        tag, typ, cnt, val = struct.unpack("<HHII", b[off + 2 + 12 * i: off + 14 + 12 * i])
        tags[tag] = (typ, cnt, val)
    h, w = res["grid"].shape
    assert tags[256][2] == w and tags[257][2] == h
    tp = struct.unpack("<6d", b[tags[33922][2]:tags[33922][2] + 48])
    assert tp[3] == pytest.approx(res["grid"].west) and tp[4] == pytest.approx(res["grid"].north)
    data = np.frombuffer(b[tags[273][2]:tags[273][2] + tags[279][2]], np.uint8).reshape(h, w, 4)
    assert (data == res["image"]).all()


def test_nodata_sentinel_is_masked(tmp_path):
    ods.clear_tile_cache()
    root = str(tmp_path)
    path = ods.local_tile_path("ir", root, LA + 0.5, LO + 0.5)
    os.makedirs(os.path.dirname(path))
    arr = mound_tile()
    arr[P - 2:P + 3, P - 2:P + 3] = -32767.0
    write_tile(path, arr)
    lat, lon = _centre()
    res = fi.build_final_image("ir", root, lat, lon, 2000)
    g = res["grid"]
    assert np.isnan(g.values).sum() == 25
    assert (res["image"][..., 3][np.isnan(g.values)] == 0).all()
    ods.clear_tile_cache()


def test_hillshade_matches_existing_gdaldem_equivalent():
    """Same formula as terrain_derivatives.compute_hillshade on square cells."""
    import terrain_derivatives as td
    from types import SimpleNamespace
    z = mound_tile()[P - 20:P + 20, P - 20:P + 20].astype(np.float64)
    ref = td.compute_hillshade(SimpleNamespace(elevation_m=z, resolution_m=30.0, source="t"),
                               315.0, 45.0).values / 255.0
    assert np.allclose(fi.hillshade(z, 30.0, 30.0, 315.0, 45.0), ref)
