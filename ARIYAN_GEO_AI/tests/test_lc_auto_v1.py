"""lc-auto-v1 (2026-10-15): WorldCover land cover saved once, and read
automatically after every sweep and before a "Refine selected" run."""
import json
import os
import struct
import zlib

import numpy as np

import grand_project_db as db
import grand_project_refinement as gpr
import land_cover_flags as lc
import wide_area_search_mobile as was
import worldcover_store as wcs

URL = lc.WORLDCOVER_URL.format(tile="N30E048")
PX = 1.0 / 12000.0          # WorldCover pixel size in degrees
X0, Y0 = 48.299, 32.102     # north-west corner of the test image


def _tiff(classes: np.ndarray, tile: int = 32) -> bytes:
    """A real tiled, DEFLATE-compressed, georeferenced 8-bit GeoTIFF of the
    shape WorldCoverHttpTile supports."""
    h, w = classes.shape
    blocks = []
    for bi in range(0, h, tile):
        for bj in range(0, w, tile):
            blk = np.zeros((tile, tile), dtype=np.uint8)
            part = classes[bi:bi + tile, bj:bj + tile]
            blk[:part.shape[0], :part.shape[1]] = part
            blocks.append(zlib.compress(blk.tobytes()))
    n_entries = 12
    ifd_off = 8
    data_off = ifd_off + 2 + n_entries * 12 + 4
    extra = bytearray()

    def ext(b):
        off = data_off + len(extra)
        extra.extend(b)
        return off
    nb = len(blocks)
    scale_off = ext(struct.pack("<3d", PX, PX, 0.0))
    tie_off = ext(struct.pack("<6d", 0, 0, 0, X0, Y0, 0))
    offs_pos = ext(b"\0" * 4 * nb)
    cnts_off = ext(struct.pack(f"<{nb}I", *[len(b) for b in blocks]))
    img_off = data_off + len(extra)
    offsets, cur = [], img_off
    for b in blocks:
        offsets.append(cur)
        cur += len(b)
    extra[offs_pos - data_off:offs_pos - data_off + 4 * nb] = struct.pack(f"<{nb}I", *offsets)

    def e(tag, typ, cnt, val):
        return struct.pack("<HHI", tag, typ, cnt) + val

    def short(v):
        return struct.pack("<HH", v, 0)

    def long_(v):
        return struct.pack("<I", v)
    entries = [
        e(256, 3, 1, short(w)), e(257, 3, 1, short(h)), e(258, 3, 1, short(8)),
        e(259, 3, 1, short(8)), e(277, 3, 1, short(1)), e(317, 3, 1, short(1)),
        e(322, 3, 1, short(tile)), e(323, 3, 1, short(tile)),
        e(324, 4, nb, long_(offs_pos)), e(325, 4, nb, long_(cnts_off)),
        e(33550, 12, 3, long_(scale_off)), e(33922, 12, 6, long_(tie_off)),
    ]
    assert len(entries) == n_entries
    head = b"II" + struct.pack("<HI", 42, ifd_off) + struct.pack("<H", n_entries) \
        + b"".join(entries) + struct.pack("<I", 0)
    return head + bytes(extra) + b"".join(blocks)


class Server:
    """Answers Range requests from an in-memory file and counts them."""
    def __init__(self, data):
        self.data = data
        self.calls = 0

    def __call__(self, url, start, end):
        self.calls += 1
        return self.data[start:end + 1]


def _image():
    img = np.full((96, 96), 60, dtype=np.uint8)   # bare everywhere
    img[0:48, 0:48] = 50                            # built-up north-west quarter
    return img


def _job(tmp_path, pts):
    root = str(tmp_path)
    gp = db.create_grand_project(root, "t")
    centers = [{"tile_index": 0, "center_lat": 32.1, "center_lon": 48.3}]
    jid = db.create_wide_area_search_job(root, gp, "j", "MANUAL_BBOX", 32.09, 32.11, 48.29, 48.31, 1000, centers)
    t = db.list_tiles_for_job(root, jid)[0]
    inv = db.create_investigation(root, gp, "", "", {})
    db.mark_tile_done(root, t["id"], inv)
    ids = [db.create_candidate(root, gp, inv, la, lo, score=5.0) for la, lo in pts]
    return root, jid, ids


BUILT = (Y0 - 20 * PX, X0 + 20 * PX)    # inside the built-up quarter
BARE = (Y0 - 70 * PX, X0 + 70 * PX)     # bare ground


# ----------------------------- store -----------------------------

def test_store_saves_once_and_reuses(tmp_path):
    srv = Server(b"abcdefghij")
    stats = {}
    get = wcs.saved_range_get(str(tmp_path), live=srv, stats=stats)
    assert get(URL, 2, 5) == b"cdef"
    assert get(URL, 2, 5) == b"cdef"
    assert srv.calls == 1 and stats == {"reused": 1, "saved": 1, "live_not_saved": 0}
    d = os.path.join(str(tmp_path), wcs.DIRNAME, "N30E048")
    idx = json.load(open(os.path.join(d, "index.json")))
    assert idx["2-5.bin"]["bytes"] == 4 and len(idx["2-5.bin"]["sha256"]) == 64
    assert wcs.library_summary(str(tmp_path))["tiles"]["N30E048"]["ranges"] == 1


def test_damaged_file_is_refetched_not_trusted(tmp_path):
    srv = Server(b"abcdefghij")
    get = wcs.saved_range_get(str(tmp_path), live=srv)
    get(URL, 0, 3)
    path = os.path.join(str(tmp_path), wcs.DIRNAME, "N30E048", "0-3.bin")
    open(path, "wb").write(b"XXXX")
    assert get(URL, 0, 3) == b"abcd" and srv.calls == 2
    assert open(path, "rb").read() == b"abcd"


def test_save_failure_never_fails_the_read(tmp_path):
    blocker = tmp_path / "file_not_dir"
    blocker.write_text("x")
    stats = {}
    get = wcs.saved_range_get(str(blocker), live=Server(b"abcdef"), stats=stats)
    assert get(URL, 1, 2) == b"bc" and stats["live_not_saved"] == 1


def test_live_error_propagates_unchanged(tmp_path):
    def boom(url, s, e):
        raise lc.LandCoverDataUnavailable("offline")
    get = wcs.saved_range_get(str(tmp_path), live=boom)
    try:
        get(URL, 0, 1)
        assert False
    except lc.LandCoverDataUnavailable:
        pass


def test_other_urls_get_their_own_folder():
    assert wcs.tile_key(URL) == "N30E048"
    assert wcs.tile_key("https://x/y.tif").startswith("url_")


# --------------------- end to end, real TIFF bytes ---------------------

def test_real_tiff_reads_and_second_job_is_fully_offline(tmp_path, monkeypatch):
    srv = Server(_tiff(_image()))
    monkeypatch.setattr(lc, "_http_range", srv)
    root, jid, (built, bare) = _job(tmp_path, [BUILT, BARE])
    r = lc.ensure_job_land_cover(root, jid)
    assert "problem" not in r and r["newly_checked"] == 2
    assert r["worldcover_store"]["saved"] == srv.calls > 0
    flags = lc.job_flags(root, jid)["flagged"]
    assert built in flags and bare not in flags            # lc-v2 rule unchanged
    # Same tile, new job: everything comes from the offline library.
    root2, jid2, _ = _job(tmp_path / "b", [BUILT, BARE])
    import shutil
    shutil.copytree(os.path.join(root, wcs.DIRNAME), os.path.join(root2, wcs.DIRNAME))
    before = srv.calls
    r2 = lc.ensure_job_land_cover(root2, jid2)
    assert r2["newly_checked"] == 2 and srv.calls == before
    assert r2["worldcover_store"]["saved"] == 0 and r2["worldcover_store"]["reused"] > 0


def test_explicit_http_get_bypasses_store(tmp_path):
    srv = Server(_tiff(_image()))
    root, jid, _ = _job(tmp_path, [BARE])
    r = lc.ensure_job_land_cover(root, jid, http_get=srv)
    assert "worldcover_store" not in r
    assert not os.path.exists(os.path.join(root, wcs.DIRNAME))


# ----------------------------- quiet helper -----------------------------

def test_quiet_helper_never_raises(tmp_path, monkeypatch):
    r = lc.read_job_land_cover_quietly(str(tmp_path), "no-such-job")
    assert r["version"] == "lc-auto-v1" and "problem" in r

    def boom(url, s, e):
        raise lc.LandCoverDataUnavailable("offline")
    monkeypatch.setattr(lc, "_http_range", boom)
    root, jid, _ = _job(tmp_path / "c", [BARE])
    r = lc.read_job_land_cover_quietly(root, jid)
    assert "offline" in r["problem"] and r["could_not_read"] == 1


# ----------------------------- automatic reads -----------------------------

def test_sweep_reads_land_cover_unless_paused_or_auto(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(lc, "read_job_land_cover_quietly",
                        lambda r, j: calls.append(j) or {"newly_checked": 3, "version": "lc-auto-v1"})
    payload = {"total": 1, "done": 1, "pending": 0}
    monkeypatch.setattr(was, "_run_wide_area_search_job_impl", lambda *a, **k: json.dumps(payload))
    out = json.loads(was.run_wide_area_search_job(str(tmp_path), "j1"))
    assert out["land_cover"]["newly_checked"] == 3 and calls == ["j1"]
    out = json.loads(was.run_wide_area_search_job(str(tmp_path), "j1", read_land_cover=False))
    assert "land_cover" not in out and calls == ["j1"]
    payload["paused"] = True
    out = json.loads(was.run_wide_area_search_job(str(tmp_path), "j1"))
    assert "land_cover" not in out and calls == ["j1"]


def test_selected_refinement_reads_land_cover_but_never_filters(tmp_path, monkeypatch):
    root, jid, (built, bare) = _job(tmp_path, [BUILT, BARE])
    monkeypatch.setattr(lc, "_http_range", Server(_tiff(_image())))
    seen = {}

    def loop(data_root, job_id, refs, *a, **k):
        seen["refs"] = [c["id"] for c in refs]
        return {"attempted": len(refs)}
    monkeypatch.setattr(gpr, "_run_refinement_loop", loop)
    out = gpr.run_selected_refinement(root, jid, f"{built} {bare}", require_live_dem=False)
    assert out["land_cover"]["newly_checked"] == 2
    assert seen["refs"] == [built, bare]                    # flagged one still refined
    assert built in lc.job_flags(root, jid)["flagged"]
    out = gpr.run_selected_refinement(root, jid, bare, require_live_dem=False, read_land_cover=False)
    assert "land_cover" not in out
