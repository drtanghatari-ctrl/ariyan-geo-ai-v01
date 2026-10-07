"""cop-bulk-v1 (2026-10-07): Pass 2 COP30 windows cut from the bulk Copernicus
tiles. The real-data proof is csc-v1 on the device (12,960,000 / 12,960,000
cells identical) plus 297/297 random windows vs Pillow on the real AWS
N32/N31 tiles in the build sandbox. These tests use small synthetic tiles in
the Copernicus file format; the writer below is checked against Pillow (an
independent decoder) so it cannot share a mistake with our own reader."""
import json
import os
import struct
import zlib

import numpy as np
import pytest

import cop30_bulk
import dem_library_mobile as dlm
import dem_source_mobile as dsm
import offline_dem_store
import srtm_library
from coordinate import GeoPoint, build_aoi

N, TW = 3600, 512


def _value(grow, gcol):
    # distinct per cell, exact in float32 (multiples of 1/64)
    return (1000.0 + (grow % 3600) * 0.25 + (gcol % 3600) / 64.0).astype(np.float32)


def _encode_tile(block):
    """TIFF Predictor 3 (libtiff fpDiff): big-endian bytes split into 4 planes
    per row, then byte-wise horizontal differencing over the whole row."""
    be = block.astype(">f4").view(np.uint8).reshape(block.shape[0], block.shape[1], 4)
    planes = be.transpose(0, 2, 1).reshape(block.shape[0], -1)
    diff = planes.copy()
    diff[:, 1:] = (planes[:, 1:].astype(np.int16) - planes[:, :-1]).astype(np.uint8)
    return zlib.compress(diff.tobytes(), 6)


def write_cop_tile(path, la, lo, raster_type=2, size=N):
    rows = (89 - la) * 3600 + np.arange(size)
    cols = lo * 3600 + np.arange(size)
    arr = _value(rows[:, None], cols[None, :])
    tiles = []
    for r in range(0, size, TW):
        for c in range(0, size, TW):
            blk = np.zeros((TW, TW), np.float32)
            part = arr[r:r + TW, c:c + TW]
            blk[:part.shape[0], :part.shape[1]] = part
            tiles.append(_encode_tile(blk))
    ntiles = len(tiles)
    # ---- assemble a little-endian TIFF
    entries = []
    extra = bytearray()
    header = 8
    tags = [  # (tag, type, values)
        (256, 3, [size]), (257, 3, [size]), (258, 3, [32]), (259, 3, [8]),
        (277, 3, [1]), (317, 3, [3]), (322, 3, [TW]), (323, 3, [TW]),
        (324, 4, None), (325, 4, [len(t) for t in tiles]), (339, 3, [3]),
        (33550, 12, [1 / 3600, 1 / 3600, 0.0]),
        (33922, 12, [0.0, 0.0, 0.0, float(lo), float(la + 1), 0.0]),
        (34735, 3, [1, 1, 0, 2, 1024, 0, 1, 2, 1025, 0, 1, raster_type]),
    ]
    nent = len(tags)
    ifd_size = 2 + nent * 12 + 4
    extra_off = header + ifd_size
    fmt = {3: "H", 4: "I", 12: "d"}
    size_of = {3: 2, 4: 4, 12: 8}
    # data blob placed after extras; offsets filled once extras are sized
    data_parts, blob = [], b"".join(tiles)
    tile_offs = []
    placeholders = []
    for tag, typ, vals in tags:
        if vals is None:
            vals = [0] * ntiles
            placeholders.append(len(entries))
        entries.append([tag, typ, vals])
    # compute extras size
    ext_len = sum(len(v) * size_of[t] for _, t, v in entries if len(v) * size_of[t] > 4)
    data_off = extra_off + ext_len
    o = data_off
    for t in tiles:
        tile_offs.append(o)
        o += len(t)
    for i in placeholders:
        entries[i][2] = tile_offs
    ifd = bytearray(struct.pack("<H", nent))
    for tag, typ, vals in entries:
        raw = struct.pack("<" + fmt[typ] * len(vals), *vals)
        if len(raw) <= 4:
            ifd += struct.pack("<HHI", tag, typ, len(vals)) + raw.ljust(4, b"\0")
        else:
            ifd += struct.pack("<HHII", tag, typ, len(vals), extra_off + len(extra))
            extra += raw
    ifd += struct.pack("<I", 0)
    with open(path, "wb") as f:
        f.write(b"II" + struct.pack("<HI", 42, header) + ifd + extra + blob)
    return arr


@pytest.fixture(scope="module")
def bulk(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("offline"))
    d = os.path.join(root, "ir", "dem")
    os.makedirs(d)
    arrs = {}
    for la, lo in ((32, 48), (32, 49)):
        arrs[(la, lo)] = write_cop_tile(os.path.join(d, cop30_bulk.bulk_tile_id(la, lo) + ".tif"), la, lo)
    return root, arrs


def _expected(s, n, w, e):
    r0, nr, c0, nc, _ = srtm_library.window_indices(s, n, w, e)
    rows = r0 + np.arange(nr)
    cols = c0 + np.arange(nc)
    return _value(rows[:, None], cols[None, :]).astype(np.float64)


def test_writer_agrees_with_pillow(bulk):
    Image = pytest.importorskip("PIL.Image")
    root, arrs = bulk
    try:
        got = np.array(Image.open(os.path.join(root, "ir", "dem", "N32_E048.tif")))
    except Exception as exc:  # Pillow built without predictor-3 support
        pytest.skip(f"Pillow cannot decode: {exc}")
    assert np.array_equal(got, arrs[(32, 48)])


def test_interior_window_matches_global_lattice(bulk):
    root, _ = bulk
    box = (32.4512, 32.4598, 48.3011, 48.3099)
    g, why = cop30_bulk.cut_window(root, *box)
    assert why == "ok" and g["library_tile"] == "N32_E048"
    assert np.array_equal(g["values"], _expected(*box))
    assert g["bulk_files"][0]["sha256"] == cop30_bulk.file_sha256(
        os.path.join(root, "ir", "dem", "N32_E048.tif"))


def test_window_across_degree_line_is_assembled(bulk):
    root, _ = bulk
    box = (32.5001, 32.5052, 48.9963, 49.0041)
    g, why = cop30_bulk.cut_window(root, *box)
    assert why == "ok" and g["library_tile"] == "N32_E048+N32_E049"
    assert np.array_equal(g["values"], _expected(*box))


def test_missing_neighbour_is_a_miss(bulk):
    root, _ = bulk
    g, why = cop30_bulk.cut_window(root, 32.9963, 33.0041, 48.5, 48.506)
    assert g is None and why.startswith("bulk_tile_missing N33_E048")


def test_pixel_is_area_file_refused(tmp_path):
    root = str(tmp_path)
    d = os.path.join(root, "xx", "dem")
    os.makedirs(d)
    write_cop_tile(os.path.join(d, "N32_E048.tif"), 32, 48, raster_type=1)
    g, why = cop30_bulk.cut_window(root, 32.45, 32.46, 48.30, 48.31)
    assert g is None and "PixelIsPoint" in why
    assert cop30_bulk.covered(root, 32, 48) is None


def test_pass2_cop30_fetch_served_from_bulk(bulk, monkeypatch):
    root, _ = bulk
    src = dsm.OpenTopographyAAIGridSource("KEY", "COP30", offline_data_root=root)
    monkeypatch.setattr(src, "_get_with_hard_deadline", lambda p: pytest.fail("no live call"))
    monkeypatch.setattr(srtm_library, "cut_window", lambda *a: pytest.fail("bulk comes first"))
    aoi = build_aoi(GeoPoint(32.4567, 48.4567), 300.0, 32)
    dsm.arm_dem_library(root)
    try:
        dem = src.fetch(aoi)
        summ = dsm.dem_library_summary(dsm.dem_library_events())
    finally:
        dsm.disarm_dem_library()
    assert "bulk Copernicus" in dem.notes and "N32_E048" in dem.notes
    assert summ["bulk_cop30_cuts"] == 1 and summ["library_cuts"] == 1 and summ["live_calls"] == 0


def test_srtm_never_uses_bulk(bulk, monkeypatch):
    root, _ = bulk
    monkeypatch.setattr(cop30_bulk, "cut_window", lambda *a: pytest.fail("COP30 only"))
    monkeypatch.setattr(srtm_library, "cut_window", lambda *a: (None, "not_in_library"))
    dsm.arm_dem_library(root)
    try:
        assert dsm._try_library("SRTMGL1", build_aoi(GeoPoint(32.4567, 48.4567), 300.0, 32)) is None
    finally:
        dsm.disarm_dem_library()


def test_plan_and_fill_skip_bulk_covered_cop30(bulk, monkeypatch):
    root, _ = bulk
    job = {"title": "t", "min_lat": 32.3, "max_lat": 32.4, "min_lon": 48.3, "max_lon": 48.4}
    monkeypatch.setattr(dlm, "_job_bbox", lambda r, j: (job, (32.3, 32.4, 48.3, 48.4)))
    plan = json.loads(dlm.dem_library_plan_json(root, "j1"))
    cop = plan["demtypes"]["COP30"]
    assert cop["missing"] == [] and [b["tile"] for b in cop["bulk"]] == ["N32E048"]
    assert plan["demtypes"]["SRTMGL1"]["missing"] == ["N32E048"] and plan["missing_total"] == 1
    got = []
    monkeypatch.setattr(srtm_library, "download_tile",
                        lambda r, dt, la, lo, key: got.append((dt, la, lo)) or
                        {"tile": "N32E048", "demtype": dt, "sha256": "x", "bytes": 1})
    r = json.loads(dlm.fill_dem_library_json(root, "j1", "KEY", 10, False))
    assert got == [("SRTMGL1", 32, 48)] and r["calls"] == 1
