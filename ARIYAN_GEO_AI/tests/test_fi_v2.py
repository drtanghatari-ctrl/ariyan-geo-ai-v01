"""fi-v2 (2026-10-21): satellite image layers. No network: a fake Copernicus
answers catalog, process and statistics requests. Synthetic rasters are
used ONLY as test fixtures."""
import json
import struct
import zlib

import numpy as np
import pytest

import sat_image as si

# --------------------------------------------------------------------------
# GeoTIFF fixture writer (strips or tiles; none / deflate / LZW; predictor 1 or 3)
# --------------------------------------------------------------------------


def _lzw_encode(data: bytes) -> bytes:
    out, bitbuf, nbits = bytearray(), 0, 0
    width = 9

    def emit(code):
        nonlocal bitbuf, nbits
        bitbuf = (bitbuf << width) | code
        nbits += width
        while nbits >= 8:
            nbits -= 8
            out.append((bitbuf >> nbits) & 0xFF)

    table = {bytes([i]): i for i in range(256)}
    nxt = 258
    emit(256)
    w = b""
    for ch in data:
        wc = w + bytes([ch])
        if wc in table:
            w = wc
            continue
        emit(table[w])
        table[wc] = nxt
        nxt += 1
        if nxt >= (1 << width) and width < 12:   # matches libtiff (checked with Pillow)
            width += 1
        if nxt >= 4094:
            emit(256)
            table = {bytes([i]): i for i in range(256)}
            nxt, width = 258, 9
        w = bytes([ch])
    if w:
        emit(table[w])
    emit(257)
    if nbits:
        out.append((bitbuf << (8 - nbits)) & 0xFF)
    return bytes(out)


def _pred3(block):
    be = block.astype(">f4").view(np.uint8).reshape(block.shape[0], block.shape[1], 4)
    planes = be.transpose(0, 2, 1).reshape(block.shape[0], -1)
    diff = planes.copy()
    diff[:, 1:] = (planes[:, 1:].astype(np.int16) - planes[:, :-1]).astype(np.uint8)
    return diff.tobytes()


def write_tiff(arr, west, north, dlon, dlat, *, comp=1, pred=1, tile=None, rps=None,
               point=False):
    arr = np.asarray(arr, dtype=np.float32)
    H, W = arr.shape

    def enc(block):
        raw = _pred3(block) if pred == 3 else block.astype("<f4").tobytes()
        if comp == 8:
            return zlib.compress(raw)
        if comp == 5:
            return _lzw_encode(raw)
        return raw

    blocks = []
    if tile:
        for r in range(0, H, tile):
            for c in range(0, W, tile):
                b = np.full((tile, tile), -9999.0, np.float32)
                part = arr[r:r + tile, c:c + tile]
                b[:part.shape[0], :part.shape[1]] = part
                blocks.append(enc(b))
    else:
        rps = rps or H
        for r in range(0, H, rps):
            blocks.append(enc(arr[r:r + rps]))
    tags = [(256, 4, [W]), (257, 4, [H]), (258, 3, [32]), (259, 3, [comp]),
            (262, 3, [1]), (277, 3, [1]), (284, 3, [1]), (317, 3, [pred]), (339, 3, [3])]
    if tile:
        tags += [(322, 3, [tile]), (323, 3, [tile]), (324, 4, None), (325, 4, [len(b) for b in blocks])]
    else:
        tags += [(273, 4, None), (278, 4, [rps]), (279, 4, [len(b) for b in blocks])]
    tx, ty = (west + dlon / 2, north - dlat / 2) if point else (west, north)
    tags += [(33550, 12, [dlon, dlat, 0.0]), (33922, 12, [0.0, 0.0, 0.0, tx, ty, 0.0]),
             (34735, 3, [1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 2 if point else 1,
                         2048, 0, 1, 4326])]
    tags.sort()
    fmt = {3: "H", 4: "I", 12: "d"}
    sz = {3: 2, 4: 4, 12: 8}
    ifd_off = 8
    ifd_len = 2 + 12 * len(tags) + 4
    extra_off = ifd_off + ifd_len
    extra = bytearray()
    data_off = None
    # first pass: lay out out-of-line values, leave offsets placeholder
    entries = []
    blob_start = extra_off
    payload = []
    for t, ty_, vals in tags:
        entries.append([t, ty_, vals])
    # compute block data position after extras
    tmp_extra = 0
    for t, ty_, vals in entries:
        n = len(vals) if vals is not None else len(blocks)
        if n * sz[ty_] > 4:
            tmp_extra += n * sz[ty_]
    data_off = extra_off + tmp_extra
    offs, p = [], data_off
    for b in blocks:
        offs.append(p)
        p += len(b)
    ifd = bytearray(struct.pack("<H", len(entries)))
    for t, ty_, vals in entries:
        if vals is None:
            vals = offs
        n = len(vals)
        packed = struct.pack("<" + fmt[ty_] * n, *vals)
        if len(packed) <= 4:
            ifd += struct.pack("<HHI", t, ty_, n) + packed.ljust(4, b"\0")
        else:
            ifd += struct.pack("<HHII", t, ty_, n, extra_off + len(extra))
            extra += packed
    ifd += b"\0\0\0\0"
    return b"II*\0" + struct.pack("<I", ifd_off) + bytes(ifd) + bytes(extra) + b"".join(blocks)


# --------------------------------------------------------------------------
# Reader
# --------------------------------------------------------------------------

def _sample(h=37, w=53, seed=1):
    rng = np.random.default_rng(seed)
    a = rng.normal(0.3, 0.2, (h, w)).astype(np.float32)
    a[5, 7] = -9999.0
    a[20:23, 30:40] = np.nan
    return a


@pytest.mark.parametrize("kw", [
    dict(comp=1), dict(comp=8), dict(comp=5), dict(comp=8, pred=3),
    dict(comp=1, rps=5), dict(comp=8, rps=7), dict(comp=5, rps=4),
    dict(comp=8, tile=16), dict(comp=8, pred=3, tile=16), dict(comp=1, tile=16),
])
def test_reader_roundtrip(kw):
    a = _sample()
    data = write_tiff(a, 51.0, 33.5, 1e-4, 9e-5, **kw)
    v, g = si.read_geotiff(data)
    assert v.shape == a.shape
    np.testing.assert_array_equal(np.isnan(v), np.isnan(a))
    ok = ~np.isnan(a)
    np.testing.assert_array_equal(v[ok], a[ok].astype(np.float64))
    assert g["west"] == pytest.approx(51.0) and g["north"] == pytest.approx(33.5)
    assert g["dlon"] == pytest.approx(1e-4) and g["dlat"] == pytest.approx(9e-5)
    assert g["epsg"] == 4326


def test_reader_pixel_is_point_gives_cell_edges():
    a = _sample()
    v, g = si.read_geotiff(write_tiff(a, 51.0, 33.5, 1e-4, 1e-4, point=True))
    assert g["west"] == pytest.approx(51.0) and g["north"] == pytest.approx(33.5)


def test_reader_rejects_junk():
    with pytest.raises(si.SatImageError):
        si.read_geotiff(b"not a tiff at all")


# --------------------------------------------------------------------------
# Grid, scene choice, request bodies
# --------------------------------------------------------------------------

def test_request_grid_tiles_box_exactly_at_sensor_size():
    b = si.bounds_around(32.4, 47.3, 1060.0)
    for p in si.PRODUCT_ORDER:
        g = si.request_grid(b, si.PRODUCTS[p]["pixel_m"])
        assert g["west"] + g["width"] * g["dlon"] == pytest.approx(g["east"], abs=1e-12)
        assert g["north"] - g["height"] * g["dlat"] == pytest.approx(g["south"], abs=1e-12)
        dy = g["dlat"] * si.M_PER_DEG_LAT
        assert abs(dy - si.PRODUCTS[p]["pixel_m"]) / si.PRODUCTS[p]["pixel_m"] < 0.01


def test_request_grid_refuses_oversize():
    with pytest.raises(ValueError):
        si.request_grid(si.bounds_around(32, 47, 20000.0), 10.0)


def _feat(day, cc=None, sid=None):
    p = {"datetime": day + "T07:12:00Z"}
    if cc is not None:
        p["eo:cloud_cover"] = cc
    return {"id": sid or day, "properties": p}


def test_scene_choice_optical_clearest_then_newest():
    f = [_feat("2026-05-01", 10), _feat("2026-07-01", 2), _feat("2026-08-01", 2),
         _feat("2026-08-01", 30, "b"), _feat("2026-09-01", None)]
    d = si.scene_dates("NDVI", f)
    assert [x["date"] for x in d] == ["2026-08-01", "2026-07-01", "2026-05-01", "2026-09-01"]
    assert d[0]["cloud_cover"] == 2 and len(d[0]["scene_ids"]) == 2


def test_scene_choice_sar_newest():
    f = [_feat("2026-05-01"), _feat("2026-09-12"), _feat("2026-07-01")]
    assert [x["date"] for x in si.scene_dates("SAR_VV", f)] == ["2026-09-12", "2026-07-01", "2026-05-01"]


def test_process_body_is_single_day_nearest_and_honest():
    g = si.request_grid(si.bounds_around(32.4, 47.3, 1000.0), 30.0)
    b = si.process_body("THERMAL", g, "2026-08-14")
    d = b["input"]["data"][0]
    assert d["type"] == "landsat-ot-l1"
    assert d["dataFilter"]["timeRange"] == {"from": "2026-08-14T00:00:00Z", "to": "2026-08-15T00:00:00Z"}
    assert d["processing"]["upsampling"] == "NEAREST" and d["processing"]["downsampling"] == "NEAREST"
    assert "BRIGHTNESS_TEMPERATURE" in b["evalscript"]
    assert "brightness" in si.PRODUCTS["THERMAL"]["caption"].lower()
    assert "not ground temperature" in si.PRODUCTS["THERMAL"]["caption"]
    s = si.process_body("SAR_VH", si.request_grid(si.bounds_around(32.4, 47.3, 1000.0), 10.0), "2026-09-01")
    sd = s["input"]["data"][0]
    assert sd["dataFilter"]["acquisitionMode"] == "IW" and sd["dataFilter"]["polarization"] == "DV"
    assert sd["processing"]["orthorectify"] is True


def test_stats_body_matches_image_grid():
    g = si.request_grid(si.bounds_around(32.4, 47.3, 1000.0), 10.0)
    sb = si.stats_body("NDVI", g, "2026-08-14")
    assert sb["aggregation"]["resx"] == g["dlon"] and sb["aggregation"]["resy"] == g["dlat"]
    assert sb["input"]["bounds"]["bbox"] == si.process_body("NDVI", g, "2026-08-14")["input"]["bounds"]["bbox"]
    # same value() function in both scripts
    assert si.PRODUCTS["NDVI"]["js"] in si.stats_evalscript("NDVI")
    assert si.PRODUCTS["NDVI"]["js"] in si.process_evalscript("NDVI")


# --------------------------------------------------------------------------
# Fake Copernicus
# --------------------------------------------------------------------------

class FakeCDSE:
    """Answers with per-date rasters. scenes[product] = {date: (array, cloud_cover)}."""

    def __init__(self, scenes, stats_offset=0.0, throttle_after=None):
        self.scenes = scenes
        self.calls = {"catalog": 0, "process": 0, "stats": 0}
        self.stats_offset = stats_offset
        self.throttle_after = throttle_after
        self.total = 0

    def _product_of(self, body):
        coll = body["input"]["data"][0]["type"]
        es = body.get("evalscript") or body["aggregation"]["evalscript"]
        for p, cfg in si.PRODUCTS.items():
            if cfg["collection"] == coll and cfg["js"] in es:
                return p
        raise AssertionError("unknown product")

    def _raster(self, body, grid_w, grid_h):
        p = self._product_of(body)
        day = body["input"]["data"][0]["dataFilter"]["timeRange"]["from"][:10]
        base, _ = self.scenes[p][day]
        bh, bw = base.shape                      # repeat the pattern in 2-D
        a = base[np.arange(grid_h) % bh][:, np.arange(grid_w) % bw].astype(np.float32)
        return p, a

    def __call__(self, url, body, headers, timeout):
        self.total += 1
        if self.throttle_after is not None and self.total > self.throttle_after:
            return 429, {"retry-after": "30"}, b"slow down"
        assert headers["Authorization"].startswith("Bearer ")
        b = json.loads(body)
        if url == si.CATALOG_URL:
            self.calls["catalog"] += 1
            coll = b["collections"][0]
            feats = []
            for p, days in self.scenes.items():
                if si.PRODUCTS[p]["catalog"] == coll:
                    for d, (_, cc) in days.items():
                        feats.append(_feat(d, cc, f"{p}-{d}"))
            uniq = {f["id"]: f for f in feats}
            return 200, {}, json.dumps({"features": list(uniq.values())}).encode()
        if url == si.PROCESS_URL:
            self.calls["process"] += 1
            w, h = b["output"]["width"], b["output"]["height"]
            _, a = self._raster(b, w, h)
            out = np.where(np.isnan(a), -9999.0, a)
            bb = b["input"]["bounds"]["bbox"]
            tif = write_tiff(out, bb[0], bb[3], (bb[2] - bb[0]) / w, (bb[3] - bb[1]) / h, comp=8)
            return 200, {"x-processingunits-spent": "1.5"}, tif
        if url == si.STATISTICS_URL:
            self.calls["stats"] += 1
            bb = b["input"]["bounds"]["bbox"]
            w = int(round((bb[2] - bb[0]) / b["aggregation"]["resx"]))
            h = int(round((bb[3] - bb[1]) / b["aggregation"]["resy"]))
            _, a = self._raster(b, w, h)
            ok = np.isfinite(a)
            st = {"sampleCount": int(a.size), "noDataCount": int((~ok).sum()),
                  "mean": float(a[ok].astype(np.float64).mean()) + self.stats_offset}
            return 200, {}, json.dumps({"data": [{"outputs": {"data": {"bands": {"B0": {"stats": st}}}}}]}).encode()
        raise AssertionError(url)


def _scenes(cloudy_first=False):
    ndvi_clear = np.full((8, 8), 0.42, np.float32)
    ndvi_clear[0, :] = np.nan
    ndvi_cloud = np.full((8, 8), np.nan, np.float32)
    ndvi_cloud[0, 0] = 0.1
    s = {
        "NDVI": {"2026-08-01": (ndvi_cloud if cloudy_first else ndvi_clear, 1.0),
                 "2026-06-01": (ndvi_clear, 5.0)},
        "THERMAL": {"2026-07-20": (np.full((4, 4), 305.25, np.float32), 3.0)},
        "SAR_VV": {"2026-09-10": (np.full((5, 5), -8.5, np.float32), None)},
        "SAR_VH": {"2026-09-10": (np.full((5, 5), -15.0, np.float32), None)},
    }
    return s


B = si.bounds_around(32.45, 47.27, 1060.0)


def test_fetch_saves_once_and_crops_without_refetch(tmp_path):
    fake = FakeCDSE(_scenes())
    img = si.fetch_image(str(tmp_path), "NDVI", B, "tok", fake)
    assert not img["reused"] and fake.calls["process"] == 1
    assert img["entry"]["scene_date"] == "2026-08-01"            # clearest first
    v = img["values"]
    assert np.isnan(v[0]).all() and np.nanmax(v) == pytest.approx(0.42, abs=1e-6)
    again = si.fetch_image(str(tmp_path), "NDVI", B, "tok", fake)
    assert again["reused"] and fake.calls["process"] == 1 and fake.calls["catalog"] == 1
    small = si.bounds_around(32.45, 47.27, 500.0)
    c = si.fetch_image(str(tmp_path), "NDVI", small, None, fake)  # offline crop
    assert c["reused"] and c["values"].shape[0] < v.shape[0]
    assert c["geo"]["dlon"] == img["geo"]["dlon"]                  # never resampled
    assert fake.total == 2


def test_cloudy_scene_falls_back_to_next_clearest(tmp_path):
    fake = FakeCDSE(_scenes(cloudy_first=True))
    img = si.fetch_image(str(tmp_path), "NDVI", B, "tok", fake)
    assert img["entry"]["scene_date"] == "2026-06-01"
    assert [t["date"] for t in img["entry"]["tries"]] == ["2026-08-01", "2026-06-01"]
    assert fake.calls["process"] == 2
    # the cloudy try is saved but never offered
    idx = si.library_index(str(tmp_path), "NDVI")
    assert sum(1 for e in idx.values() if e.get("accepted")) == 1


def test_offline_without_saved_image_says_so(tmp_path):
    with pytest.raises(si.SatImageError, match="offline"):
        si.fetch_image(str(tmp_path), "NDVI", B, None, FakeCDSE(_scenes()))


def test_tampered_file_is_not_served(tmp_path):
    fake = FakeCDSE(_scenes())
    img = si.fetch_image(str(tmp_path), "SAR_VV", B, "tok", fake)
    path = tmp_path / si.LIBRARY_DIR / img["entry"]["file"]
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0xFF
    path.write_bytes(bytes(raw))
    with pytest.raises(si.SatImageError):
        si.fetch_image(str(tmp_path), "SAR_VV", B, None, fake)


def test_self_check_passes_once_then_never_repeats(tmp_path):
    fake = FakeCDSE(_scenes())
    a = si.ensure_layer(str(tmp_path), "THERMAL", B, "tok", fake)
    assert a["allowed"] and fake.calls["stats"] == 1
    rec = si.self_check_record(str(tmp_path), "THERMAL")
    assert rec["pass"] and rec["image_mean"] == pytest.approx(305.25)
    other = si.bounds_around(32.9, 47.9, 1060.0)
    b = si.ensure_layer(str(tmp_path), "THERMAL", other, "tok", fake)
    assert b["allowed"] and fake.calls["stats"] == 1


def test_self_check_failure_hides_layer(tmp_path):
    fake = FakeCDSE(_scenes(), stats_offset=0.5)
    a = si.ensure_layer(str(tmp_path), "SAR_VH", B, "tok", fake)
    assert not a["allowed"] and "mean differs" in a["check"]


def test_layer_payload_honest_fields(tmp_path):
    fake = FakeCDSE(_scenes())
    img = si.ensure_layer(str(tmp_path), "NDVI", B, "tok", fake)
    p = si.layer_payload("NDVI", img)
    assert p["scene_date"] == "2026-08-01" and p["pixel_m"] == 10.0
    assert 0.8 < p["clear_fraction_window"] < 1.0
    assert p["provenance"]["sha256"] and p["provenance"]["resampling"].startswith("NEAREST")
    rgba = si.colorize("NDVI", img["values"], *si.display_range("NDVI", img["values"]))
    assert (rgba[np.isnan(img["values"])] == 0).all()        # empty stays empty
    assert (rgba[~np.isnan(img["values"]), 3] == 255).all()


# --------------------------------------------------------------------------
# Queue: strongest to weakest
# --------------------------------------------------------------------------

def _c(i, status="GENERATED", band="MODERATE", conf=0.55, z=3.0, lat=32.4, lon=47.3):
    return {"id": f"c{i:02d}" + "x" * 30, "status": status, "confidence_band": band,
            "confidence_numeric": conf, "score": z, "lat": lat + i * 0.05, "lon": lon}


def test_queue_order_strongest_first():
    cands = [
        _c(1, "SUPPORTED", z=4.0), _c(2, "SUPPORTED", z=-9.0), _c(3, "SUPPORTED", z=7.0),
        _c(4, "GENERATED", "MODERATE", z=12.0), _c(5, "GENERATED", "HIGH", 0.8, z=2.0),
        _c(6, "REJECTED", "HIGH", 0.9, z=20.0), _c(7, "GENERATED", "LOW", 0.2, z=30.0),
        _c(8, "GENERATED", "SUBSTANTIAL", 0.7, z=1.0), _c(9, "INCONCLUSIVE", "MODERATE", z=6.5),
    ]
    q = si.queue_order(cands, strong_threshold=6.0)
    ids = [c["id"][:3] for c in q]
    assert ids == ["c05", "c08",            # tier 0, higher confidence first
                   "c02", "c03", "c01",     # Supported: strong |z| first, then |z|
                   "c04", "c09"]            # MODERATE not Supported: |z| order
    assert [c["tier"] for c in q] == [0, 0, 1, 1, 1, 2, 2]
    assert q[2]["calib_strong"] and not q[4]["calib_strong"]


def test_fetch_queue_cap_tier0_exempt_and_resume(tmp_path):
    fake = FakeCDSE(_scenes())
    cands = [_c(0, "GENERATED", "HIGH", 0.8)] + [_c(i, "SUPPORTED", z=10 - i) for i in range(1, 5)]
    q = si.queue_order(cands, 6.0)
    s = si.fetch_queue(str(tmp_path), q, "tok", fake, cap=2)
    assert s["order"] == [q[0]["id"], q[1]["id"], q[2]["id"]]
    assert s["counted"] == 2 and s["stopped"] == "cap" and s["remaining"] == 2
    assert not s["failed"]
    s2 = si.fetch_queue(str(tmp_path), q, "tok", fake, cap=2)
    assert s2["already"] == 3 and s2["order"] == [q[3]["id"], q[4]["id"]]
    assert s2["remaining"] == 0


def test_fetch_queue_stops_on_throttle_and_keeps_rest(tmp_path):
    fake = FakeCDSE(_scenes(), throttle_after=3)
    q = si.queue_order([_c(i, "SUPPORTED", z=9 - i) for i in range(3)], 6.0)
    s = si.fetch_queue(str(tmp_path), q, "tok", fake)
    assert s["stopped"] == "throttled" and s["remaining"] == 3 and len(s["order"]) == 1


def test_fetch_queue_never_raises_on_bad_candidate(tmp_path):
    scenes = _scenes()
    scenes["THERMAL"] = {}                         # no thermal scene anywhere
    fake = FakeCDSE(scenes)
    q = si.queue_order([_c(1, "SUPPORTED")], 6.0)
    s = si.fetch_queue(str(tmp_path), q, "tok", fake)
    assert s["failed"] and "THERMAL" in s["failed"][0]["error"] and s["stopped"] is None


def test_module_never_writes_candidates():
    src = open(si.__file__).read()
    for word in ("UPDATE candidate", "INSERT INTO candidate", "set_candidate", "record_review"):
        assert word not in src


# --- 2026-10-21: strongest-to-weakest ordering hardened ---------------------

def test_queue_order_high_before_substantial_even_with_lower_numeric():
    cands = [
        {"id": "sub", "status": "", "confidence_band": "SUBSTANTIAL", "confidence_numeric": 0.95, "score": 5, "lat": 0, "lon": 0},
        {"id": "high", "status": "", "confidence_band": "HIGH", "confidence_numeric": 0.80, "score": 1, "lat": 0, "lon": 0},
        {"id": "mod", "status": "", "confidence_band": "MODERATE", "confidence_numeric": 0.99, "score": 9, "lat": 0, "lon": 0},
    ]
    q = si.queue_order(cands, 2.0)
    assert [c["id"] for c in q] == ["high", "sub", "mod"]
    assert [c["rank"] for c in q] == [1, 2, 3]


def test_queue_order_drops_duplicate_rows_from_tile_join():
    row = {"id": "a", "status": "", "confidence_band": "HIGH", "confidence_numeric": 0.9, "score": 3, "lat": 0, "lon": 0}
    q = si.queue_order([row, dict(row), dict(row, id="b", confidence_numeric=0.5)], 2.0)
    assert [c["id"] for c in q] == ["a", "b"]


def test_fetch_queue_reorders_a_shuffled_ranked_queue(tmp_path):
    cands = [{"id": f"c{i}", "status": "", "confidence_band": "MODERATE",
              "confidence_numeric": i / 10, "score": 1, "lat": 30 + i * 0.1, "lon": 47}
             for i in range(5)]
    q = si.queue_order(cands, 2.0)
    shuffled = list(reversed(q))
    def http(url, body, headers, timeout):
        raise si.SatImageError("offline")
    r = si.fetch_queue(str(tmp_path), shuffled, "tok", http=http, cap=10)
    assert r["order"] == ["c4", "c3", "c2", "c1", "c0"]


def test_catalog_search_asks_for_geojson(tmp_path):
    """Copernicus STAC search answers HTTP 406 to Accept: application/json."""
    fake = FakeCDSE(_scenes())
    seen = []

    def http(url, body, headers, timeout):
        seen.append((url, headers.get("Accept")))
        return fake(url, body, headers, timeout)

    si.fetch_image(str(tmp_path), "SAR_VV", B, "tok", http)
    acc = {u.rsplit("/", 1)[-1]: a for u, a in seen}
    assert acc["search"] == "application/geo+json"
    assert acc["process"] == "image/tiff"
