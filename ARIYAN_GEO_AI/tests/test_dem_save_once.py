"""Save-once (2026-10-06): with the DEM library armed, nothing fetched live
is fetched twice. Network mocked; srtm_library tile I/O mocked where a real
GeoTIFF would be needed."""
import json
import os
from unittest.mock import MagicMock

import numpy as np
import pytest

import dem_library_mobile as dlm
import dem_source_mobile as dsm
import srtm_library
from coordinate import GeoPoint, build_aoi

TEXT = "\n".join(["ncols 6", "nrows 4", "xllcorner 48.3", "yllcorner 32.1",
                  "cellsize 0.000277777778", "NODATA_value -9999"] +
                 [" ".join(str(1500 + r * 2 + c) for c in range(6)) for r in range(4)])


def _resp(text=TEXT):
    r = MagicMock()
    r.status_code, r.text, r.content = 200, text, text.encode()
    return r


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = str(tmp_path)
    src = dsm.OpenTopographyAAIGridSource("KEY", "COP30", offline_data_root=root)
    calls = []
    monkeypatch.setattr(src, "_get_with_hard_deadline", lambda p: (calls.append(p), _resp())[1])
    aoi = build_aoi(GeoPoint(32.4567, 48.4567), 300.0, 32)
    dsm.arm_dem_library(root)
    yield root, src, aoi, calls
    dsm.disarm_dem_library()


def _log(root):
    with open(os.path.join(root, "dem_library", "live_calls.json")) as f:
        return [c["label"] for c in json.load(f)]


def test_live_window_saved_then_reused(env, monkeypatch):
    root, src, aoi, calls = env
    monkeypatch.setattr(srtm_library, "cut_window", lambda *a: (None, "near_tie"))
    d1 = src.fetch(aoi)
    d2 = src.fetch(aoi)
    assert len(calls) == 1                                  # fetched once only
    assert np.array_equal(d1.elevation_m, d2.elevation_m)
    assert "saved live windows" in d2.notes
    summ = dsm.dem_library_summary(dsm.dem_library_events())
    assert summ["live_calls"] == 1 and summ["windows_saved"] == 1 and summ["window_cache_hits"] == 1
    assert summ["library_misses"] == {"near_tie": 1}
    assert _log(root) == ["window COP30"]


def test_tampered_window_is_refetched(env, monkeypatch):
    root, src, aoi, calls = env
    monkeypatch.setattr(srtm_library, "cut_window", lambda *a: (None, "near_tie"))
    src.fetch(aoi)
    d = os.path.join(root, "dem_library", "COP30", "windows")
    asc = [f for f in os.listdir(d) if f.endswith(".asc")][0]
    with open(os.path.join(d, asc), "a") as f:
        f.write(" ")
    src.fetch(aoi)
    assert len(calls) == 2


def test_missing_tile_promoted_instead_of_window(env, monkeypatch):
    root, src, aoi, calls = env
    state = {"have": False}
    grid = {"values": np.full((4, 6), 1600.0), "ncols": 6, "nrows": 4, "xll": 48.3, "yll": 32.1,
            "cellsize": srtm_library.ARCSEC, "library_tile": "N32E048", "library_sha256": "ab" * 32,
            "library_version": srtm_library.VERSION}
    monkeypatch.setattr(srtm_library, "cut_window",
                        lambda *a: (grid, "ok") if state["have"] else (None, "not_in_library"))
    dl = []
    monkeypatch.setattr(srtm_library, "download_tile",
                        lambda r, dt, la, lo, key: (dl.append((dt, la, lo)), state.update(have=True)))
    d = src.fetch(aoi)
    assert dl == [("COP30", 32, 48)] and calls == []          # tile, not window
    assert "downloaded into the offline DEM library" in d.notes
    src.fetch(aoi)
    assert len(dl) == 1                                         # second time: plain cut
    summ = dsm.dem_library_summary(dsm.dem_library_events())
    assert summ["tiles_promoted"] == 1 and summ["live_calls"] == 1 and summ["library_cuts"] == 2
    assert _log(root) == ["promote COP30/N32E048"]


def test_failed_promotion_falls_back_and_is_not_retried(env, monkeypatch):
    root, src, aoi, calls = env
    monkeypatch.setattr(srtm_library, "cut_window", lambda *a: (None, "not_in_library"))
    tries = []

    def boom(*a):
        tries.append(1)
        raise srtm_library.LibraryError("HTTP 500: busy")
    monkeypatch.setattr(srtm_library, "download_tile", boom)
    src.fetch(aoi)
    other = build_aoi(GeoPoint(32.5567, 48.5567), 300.0, 32)
    src.fetch(other)
    assert len(tries) == 1 and len(calls) == 2              # live windows, both saved
    assert dsm.dem_library_summary(dsm.dem_library_events())["windows_saved"] == 2


def test_no_promotion_without_budget(env, monkeypatch):
    root, src, aoi, calls = env
    for _ in range(dlm.DAILY_LIVE_CAP):
        dlm._record_call(root, "x")
    monkeypatch.setattr(srtm_library, "cut_window", lambda *a: (None, "not_in_library"))
    monkeypatch.setattr(srtm_library, "download_tile", lambda *a: pytest.fail("must not download"))
    src.fetch(aoi)
    assert len(calls) == 1


def test_unarmed_fetch_saves_nothing(tmp_path, monkeypatch):
    src = dsm.OpenTopographyAAIGridSource("KEY", "COP30", offline_data_root=str(tmp_path))
    monkeypatch.setattr(src, "_get_with_hard_deadline", lambda p: _resp())
    src.fetch(build_aoi(GeoPoint(32.4567, 48.4567), 300.0, 32))
    assert not os.path.exists(os.path.join(str(tmp_path), "dem_library"))


def test_tile_for_window_edges():
    assert srtm_library.tile_for_window(32.2, 32.3, 48.2, 48.3) == (32, 48)
    assert srtm_library.tile_for_window(32.995, 32.9995, 48.2, 48.3) == (32, 48)
    assert srtm_library.tile_for_window(32.995, 33.005, 48.2, 48.3) == (33, 48)   # in its margin
    assert srtm_library.tile_for_window(32.98, 33.02, 48.2, 48.3) is None         # straddles
