"""pass1-save-once + sat-v1 (2026-10-06): Pass 1 sweeps use the save-once
DEM library, and satellite answers are saved once and reused. Network mocked."""
import json
import os
import urllib.request

import pytest

import sat_response_store as srs
import ndvi_source_mobile as ndvi
import thermal_source_mobile as thermal
import optical_source_mobile as optical
import sar_source_mobile as sar
import provenance_ledger as pl
import dem_source_mobile as dsm
import wide_area_search_mobile as was

URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"


def _req(body=b'{"bbox":[1,2,3,4],"from":"2026-07-08T00:00:00Z"}', url=URL):
    return urllib.request.Request(url, data=body, method="POST")


class Live:
    def __init__(self, text='{"data":[1]}'):
        self.calls, self.text = 0, text

    def __call__(self, req, timeout):
        self.calls += 1
        return self.text


@pytest.fixture(autouse=True)
def _clean():
    srs.disarm()
    yield
    srs.disarm()


def test_unarmed_is_plain_live(tmp_path):
    live = Live()
    srs.through("NDVI", _req(), 5, live)
    srs.through("NDVI", _req(), 5, live)
    assert live.calls == 2
    assert not os.path.exists(tmp_path / "sat_library")


def test_armed_fetches_once_then_reuses(tmp_path):
    srs.arm(str(tmp_path))
    live = Live()
    a = srs.through("NDVI", _req(), 5, live)
    assert srs.take_hit() is None
    b = srs.through("NDVI", _req(), 5, live)
    hit = srs.take_hit()
    assert a == b and live.calls == 1
    assert hit and hit["path"].endswith(".json") and len(hit["sha256"]) == 64
    assert srs.disarm() == {"reused": 1, "saved": 1,
                            "by_kind": {"NDVI": {"reused": 1, "saved": 1}}}


def test_different_body_or_kind_is_not_reused(tmp_path):
    srs.arm(str(tmp_path))
    live = Live()
    srs.through("NDVI", _req(), 5, live)
    srs.through("NDVI", _req(b'{"bbox":[9]}'), 5, live)
    srs.through("SAR", _req(), 5, live)
    assert live.calls == 3


def test_token_calls_never_cached(tmp_path):
    srs.arm(str(tmp_path))
    live = Live('{"access_token":"x"}')
    tok = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    srs.through("NDVI", _req(b"grant_type=client_credentials", tok), 5, live)
    srs.through("NDVI", _req(b"grant_type=client_credentials", tok), 5, live)
    assert live.calls == 2 and not os.path.exists(tmp_path / "sat_library")


def test_tampered_answer_is_fetched_again(tmp_path):
    srs.arm(str(tmp_path))
    live = Live()
    srs.through("NDVI", _req(), 5, live)
    d = tmp_path / "sat_library" / "NDVI"
    f = [p for p in os.listdir(d) if p != "index.json"][0]
    (d / f).write_text("tampered")
    assert srs.through("NDVI", _req(), 5, live) == live.text
    assert live.calls == 2 and srs.take_hit() is None


def test_failed_live_call_saves_nothing(tmp_path):
    srs.arm(str(tmp_path))

    def boom(req, timeout):
        raise ndvi.NDVIFetchError("HTTP 500")
    with pytest.raises(ndvi.NDVIFetchError):
        srs.through("NDVI", _req(), 5, boom)
    assert not os.path.exists(tmp_path / "sat_library" / "NDVI" / "index.json")


def test_time_window_anchored_to_day_only_when_armed(tmp_path):
    srs.arm(str(tmp_path))
    for mod in (ndvi, thermal, optical, sar):
        f, t = mod._default_time_range()
        assert t.endswith("T00:00:00Z") and f.endswith("T00:00:00Z")
        assert mod._default_time_range() == (f, t)    # repeatable -> reusable


@pytest.mark.parametrize("mod,kind", [(ndvi, "NDVI"), (thermal, "THERMAL"),
                                      (optical, "OPTICAL"), (sar, "SAR")])
def test_each_module_goes_through_the_store(tmp_path, monkeypatch, mod, kind):
    live = Live()
    monkeypatch.setattr(mod, "_urlopen_live_with_hard_deadline", live)
    srs.arm(str(tmp_path))
    fn = getattr(mod._urlopen_with_hard_deadline, "__wrapped__", mod._urlopen_with_hard_deadline)
    fn(_req(), 5)
    fn(_req(), 5)
    assert live.calls == 1
    assert os.path.exists(tmp_path / "sat_library" / kind / "index.json")


def test_ledger_records_saved_answer_as_file(tmp_path, monkeypatch):
    notes = []
    monkeypatch.setattr(pl, "_active", lambda: {"_files": set()})
    monkeypatch.setattr(pl, "_note", notes.append)
    srs.arm(str(tmp_path))
    live = Live()
    wrapped = pl._wrap_urlopen(lambda r, t: srs.through("NDVI", r, t, live), "NDVI")
    wrapped(_req(), 5)
    wrapped(_req(), 5)
    assert [n["type"] for n in notes] == ["LIVE", "FILE"]
    assert notes[1]["sha256"] == notes[0]["response_sha256"]


def test_pass1_runner_arms_and_disarms_both_stores(tmp_path, monkeypatch):
    seen = {}

    def impl(data_root, *a, **k):
        seen["dem"] = dsm.dem_library_events() is not None
        seen["sat"] = srs.current() is not None
        return json.dumps({"ok": True})
    monkeypatch.setattr(was, "_run_wide_area_search_job_impl", impl)
    out = json.loads(was.run_wide_area_search_job(str(tmp_path), "j1"))
    assert seen == {"dem": True, "sat": True}
    assert dsm.dem_library_events() is None and srs.current() is None
    assert "dem_library" in out and out["satellite_store"]["reused"] == 0


def test_pass1_health_shows_library_and_satellite_lines():
    t = was._RunHealth(dem_only=True, dem_offline_first=True)
    t.add({"dem_offline_first_miss": True})
    t.dem_library = {"library_cuts": 4, "live_calls": 1, "windows_saved": 1}
    t.sat_store = {"reused": 3, "saved": 2}
    txt = was._render_run_health(t)
    assert "where the offline store had no coverage" in txt
    assert "windows cut from DEM library: 4, live DEM calls: 1" in txt
    assert "satellite answers: 3 reused from saved, 2 fetched live and saved" in txt
