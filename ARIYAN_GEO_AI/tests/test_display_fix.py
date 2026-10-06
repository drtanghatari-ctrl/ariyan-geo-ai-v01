"""Display fix 2026-10-06: Pass 2 health block and Copernicus sign-in reasons."""
import ndvi_source_mobile
import investigation_multi_mobile as imm
import wide_area_search_mobile as was


def test_pass2_health_shows_library_counts():
    t = was._RunHealth(dem_only=False)
    t.add({"sources": {}})
    t.dem_library = {"library_cuts": 7, "live_calls": 1, "window_cache_hits": 2,
                     "tiles_promoted": 0, "windows_saved": 1}
    text = was._render_run_health(t)
    assert "windows cut from DEM library: 7, live DEM calls: 1" in text
    assert "2 from saved windows" in text and "1 live window(s) saved" in text
    assert "offline library: 0 tiles" not in text


def test_old_health_line_unchanged_without_library():
    t = was._RunHealth(dem_only=False)
    t.add({"sources": {}})
    assert "live: 1 tiles, offline library: 0 tiles" in was._render_run_health(t)


def test_token_failure_reason_is_honest():
    net = ("Could not obtain a Copernicus access token: timed out after 8 s. This usually means "
           "no network connection is available right now, or the credentials are invalid.")
    assert was._short_sat_reason(net) == "Copernicus sign-in failed (network / timeout)"
    bad = ("Could not obtain a Copernicus access token: HTTP 401 invalid_client. This usually "
           "means x, or the credentials are invalid.")
    assert was._short_sat_reason(bad) == "Copernicus credentials rejected"


def test_token_retried_on_network_error_not_on_401(monkeypatch):
    calls = []
    monkeypatch.setattr(imm.time, "sleep", lambda s: None)

    def flaky(cid, sec, timeout=8):
        calls.append(1)
        if len(calls) < 3:
            raise ndvi_source_mobile.NDVIFetchError("timed out")
        return "TOKEN"
    monkeypatch.setattr(ndvi_source_mobile, "get_access_token", flaky)
    assert imm._get_shared_copernicus_token("id", "secret", 8) == ("TOKEN", None)
    assert len(calls) == 3
    calls.clear()

    def rejected(cid, sec, timeout=8):
        calls.append(1)
        raise ndvi_source_mobile.NDVIFetchError("HTTP 401 invalid_client")
    monkeypatch.setattr(ndvi_source_mobile, "get_access_token", rejected)
    tok, err = imm._get_shared_copernicus_token("id", "secret", 8)
    assert tok is None and len(calls) == 1 and "401" in err
