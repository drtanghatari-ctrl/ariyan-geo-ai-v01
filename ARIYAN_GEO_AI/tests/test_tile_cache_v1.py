"""tc-v1 (2026-10-15): offline_dem_store's tile cache re-opens a tile file
that changed on disk (size or mtime), so a re-downloaded tile is served
without restarting the app. Small synthetic tiles in the Copernicus file
format (float32, Predictor 3, deflate, PixelIsPoint); expected values always
come from a FRESH CopernicusDemTile over the file, never from the cache."""
import os
import struct
import zlib

import numpy as np
import pytest

import offline_dem_store as ods
from geotiff_cog_reader import CopernicusDemTile

LA, LO = 32, 48
S = 64  # pixels per degree side in these test tiles


def _encode_tile(block):
    be = block.astype(">f4").view(np.uint8).reshape(block.shape[0], block.shape[1], 4)
    planes = be.transpose(0, 2, 1).reshape(block.shape[0], -1)
    diff = planes.copy()
    diff[:, 1:] = (planes[:, 1:].astype(np.int16) - planes[:, :-1]).astype(np.uint8)
    return zlib.compress(diff.tobytes(), 6)


def write_tile(path, base, tw=16):
    """One 1x1 degree tile (SW corner LA, LO), S x S pixels, internal tiles
    tw x tw. Cell value = base + row * S + col (exact in float32)."""
    r = np.arange(S)
    arr = (base + r[:, None] * S + r[None, :]).astype(np.float32)
    tiles = []
    for a in range(0, S, tw):
        for b in range(0, S, tw):
            tiles.append(_encode_tile(arr[a:a + tw, b:b + tw]))
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


POINTS = [(LA + 0.5, LO + 0.5), (LA + 0.1, LO + 0.9), (LA + 0.93, LO + 0.07)]


@pytest.fixture
def env(tmp_path):
    ods.clear_tile_cache()
    root = str(tmp_path)
    path = ods.local_tile_path("ir", root, LA + 0.5, LO + 0.5)
    os.makedirs(os.path.dirname(path))
    write_tile(path, 100.0)
    yield root, path
    ods.clear_tile_cache()


def _read(root):
    return [ods.get_offline_elevation("ir", root, la, lo) for la, lo in POINTS]


def _fresh(path):
    t = CopernicusDemTile(path)
    return [t.get_elevation(lo, la) for la, lo in POINTS]


def _bump_mtime(path):
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


@pytest.fixture
def opens(monkeypatch):
    count = []

    class Counting(CopernicusDemTile):
        def __init__(self, p):
            count.append(p)
            super().__init__(p)

    monkeypatch.setattr(ods, "CopernicusDemTile", Counting)
    return count


def test_version_tag():
    assert ods.TILE_CACHE_VERSION == "tc-v1"


def test_unchanged_file_opened_once(env, opens):
    root, path = env
    first = _read(root)
    for _ in range(50):
        assert _read(root) == first
    assert len(opens) == 1
    assert first == _fresh(path) and None not in first


def test_replaced_file_served_without_restart(env, opens):
    root, path = env
    old = _read(root)
    tmp = path + ".part"
    write_tile(tmp, 900.0)
    os.replace(tmp, path)          # how a finished download lands
    _bump_mtime(path)              # guard against coarse mtime on test FS
    new = _read(root)
    assert new == _fresh(path)
    assert all(n - o == 800.0 for n, o in zip(new, old))
    assert len(opens) == 2


def test_in_place_rewrite_same_size_detected(env, opens):
    root, path = env
    old = _read(root)
    size = os.path.getsize(path)
    write_tile(path, 100.5)        # same layout -> usually the same byte size
    _bump_mtime(path)
    new = _read(root)
    assert new == _fresh(path)
    assert new != old
    assert len(opens) == 2
    if os.path.getsize(path) == size:
        assert all(n - o == 0.5 for n, o in zip(new, old))


def test_new_internal_layout_never_read_with_old_offsets(env):
    root, path = env
    _read(root)
    write_tile(path, 900.0, tw=8)  # different block offsets and file size
    _bump_mtime(path)
    assert _read(root) == _fresh(path)


def test_deleted_file_is_none_and_evicted(env):
    root, path = env
    _read(root)
    os.remove(path)
    assert _read(root) == [None, None, None]
    with pytest.raises(FileNotFoundError):
        ods._get_cached_tile(path)
    assert path not in ods._tile_cache


def test_clear_tile_cache_still_works(env, opens):
    root, _ = env
    _read(root)
    ods.clear_tile_cache()
    assert ods._tile_cache == {}
    _read(root)
    assert len(opens) == 2


def test_failed_reopen_does_not_leave_stale_entry(env):
    root, path = env
    _read(root)
    with open(path, "wb") as f:    # half-written download: not a TIFF yet
        f.write(b"\0" * 10)
    _bump_mtime(path)
    with pytest.raises(Exception):
        ods._get_cached_tile(path)
    assert path not in ods._tile_cache
    write_tile(path, 900.0)        # download finishes
    _bump_mtime(path)
    assert _read(root) == _fresh(path)
