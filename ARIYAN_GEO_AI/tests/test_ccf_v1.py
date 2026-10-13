"""ccf-v1: Pass 2 always stability-tests the refined candidate and copies
the stability + COP30 cross-check results into the marker row (inputs for
cc-v1 check 1 / test T2). These tests use stand-in objects for the
selection helper and a recorder in place of the expensive investigation
call; every other step of refine_candidate runs for real."""
import json
from types import SimpleNamespace as NS

import grand_project_db as db
import grand_project_refinement as gpr
import investigation_multi_mobile as imm
import debate_mobile


def _c(lat, lon):
    return NS(lat=lat, lon=lon)


# -- _force_stability_target ------------------------------------------------

def test_no_target_leaves_selection_unchanged():
    a, b = _c(32.0, 48.0), _c(32.01, 48.01)
    sel = [b]
    assert imm._force_stability_target([a, b], sel, None, None, None) is sel
    assert imm._force_stability_target([a, b], sel, 32.0, 48.0, None) is sel
    assert imm._force_stability_target([], sel, 32.0, 48.0, 50.0) is sel


def test_target_within_tolerance_is_prepended():
    a, b = _c(32.0, 48.0), _c(32.01, 48.01)
    out = imm._force_stability_target([a, b], [b], 32.0001, 48.0, 50.0)
    assert out[0] is a and out[1] is b and len(out) == 2


def test_already_selected_target_is_not_duplicated():
    a, b = _c(32.0, 48.0), _c(32.01, 48.01)
    sel = [a, b]
    out = imm._force_stability_target([a, b], sel, 32.0, 48.0, 50.0)
    assert out is sel


def test_nearest_candidate_beyond_tolerance_is_not_forced():
    a = _c(32.0, 48.0)
    out = imm._force_stability_target([a], [], 32.001, 48.0, 50.0) # ~111 m
    assert out == []


# -- _cc_fields ---------------------------------------------------------------

def _stab(lat, lon, score=1.0):
    return {"lat": lat, "lon": lon, "stability_score": score,
            "n_windows_attempted": 2, "n_windows_fetched": 2,
            "n_windows_detected": 2, "target_zscore": 7.5,
            "z_min": 6.9, "z_max": 8.1, "offset_errors": []}


def _xc(lat, lon, confirmed=True, error=None):
    return {"lat": lat, "lon": lon, "cross_dem_confirmed": confirmed,
            "cross_dem_peak_zscore": 6.2 if confirmed else None,
            "cross_dem_peak_residual_m": 1.4 if confirmed else None,
            "distance_m": 12.0 if confirmed else None, "error": error}


def test_cc_fields_not_reproduced_is_untested():
    out = gpr._cc_fields({"seventh_evidence_detail": [_stab(32, 48)]}, None)
    assert out == {"cc_fields_version": "ccf-v1", "stability": None,
                   "dem_cross_check": None}


def test_cc_fields_copies_both_results_for_matched_anomaly():
    inv = {"seventh_evidence_detail": [_stab(32.0, 48.0, 0.5)],
           "tenth_evidence_detail": [_xc(32.0, 48.0)]}
    out = gpr._cc_fields(inv, {"lat": 32.0, "lon": 48.0})
    assert out["stability"]["stability_score"] == 0.5
    assert out["stability"]["n_windows_fetched"] == 2
    assert out["dem_cross_check"] == {
        "tested": True, "confirmed": True, "cross_dem_peak_zscore": 6.2,
        "cross_dem_peak_residual_m": 1.4, "distance_m": 12.0, "error": None}


def test_cc_fields_cross_check_fetch_error_is_not_tested():
    inv = {"tenth_evidence_detail": [_xc(32.0, 48.0, False, "HTTP 503")]}
    out = gpr._cc_fields(inv, {"lat": 32.0, "lon": 48.0})
    assert out["dem_cross_check"]["tested"] is False
    assert out["dem_cross_check"]["confirmed"] is False
    assert out["stability"] is None


def test_cc_fields_ignores_results_for_another_anomaly():
    inv = {"seventh_evidence_detail": [_stab(32.0002, 48.0)], # ~22 m away
           "tenth_evidence_detail": [_xc(32.0002, 48.0)]}
    out = gpr._cc_fields(inv, {"lat": 32.0, "lon": 48.0})
    assert out["stability"] is None and out["dem_cross_check"] is None


# -- refine_candidate end to end (investigation call replaced) ---------------

def _setup(tmp_path):
    root = str(tmp_path)
    gp = db.create_grand_project(root, "t")
    centers = [{"tile_index": 0, "center_lat": 32.1, "center_lon": 48.3}]
    jid = db.create_wide_area_search_job(root, gp, "j", "MANUAL_BBOX",
                                         32.1, 32.11, 48.3, 48.31, 1000, centers)
    t = db.list_tiles_for_job(root, jid)[0]
    inv = db.create_investigation(root, gp, "", "", {})
    db.mark_tile_done(root, t["id"], inv)
    cid = db.create_candidate(root, gp, inv, 32.1, 48.3, score=9.0)
    return root, cid


def _marker(root, cid):
    import sqlite3
    con = sqlite3.connect(db._db_path(root))
    rows = con.execute(
        "SELECT detail_json FROM evidence_link WHERE candidate_id=? "
        "AND relation='refinement_dem_check'", (cid,)).fetchall()
    con.close()
    assert len(rows) == 1
    return json.loads(rows[0][0])


def _fake_investigation(seen, anomalies, seventh, tenth):
    def run(lat, lon, radius_m, grid_size, **kw):
        seen.update(kw, lat=lat, lon=lon)
        return json.dumps({"aoi": {"cell_size_m": 10.4}, "anomalies": anomalies,
                           "correlation": [], "evidence": [],
                           "seventh_evidence_detail": seventh,
                           "tenth_evidence_detail": tenth})
    return run


def _no_debate(_):
    raise RuntimeError("debate not part of this test")


def test_refine_forces_stability_and_records_results(tmp_path, monkeypatch):
    root, cid = _setup(tmp_path)
    seen = {}
    monkeypatch.setattr(imm, "run_investigation_multi_json", _fake_investigation(
        seen, [{"lat": 32.1, "lon": 48.3, "peak_zscore": 8.0,
                "peak_residual_m": 2.0, "evidence_type": "DEM"}],
        [_stab(32.1, 48.3, 1.0)], [_xc(32.1, 48.3)]))
    monkeypatch.setattr(debate_mobile, "run_debate_json", _no_debate)
    gpr.refine_candidate(root, cid)
    assert seen["stability_target_lat"] == 32.1
    assert seen["stability_target_lon"] == 48.3
    assert seen["stability_target_tolerance_m"] >= gpr.MIN_MATCH_TOLERANCE_M
    m = _marker(root, cid)
    assert m["cc_fields_version"] == "ccf-v1"
    assert m["stability"]["stability_score"] == 1.0
    assert m["dem_cross_check"]["tested"] is True
    assert m["dem_cross_check"]["confirmed"] is True


def test_refine_not_reproduced_records_untested(tmp_path, monkeypatch):
    root, cid = _setup(tmp_path)
    seen = {}
    far = 32.1 + 0.005  # ~550 m north: outside any match tolerance
    monkeypatch.setattr(imm, "run_investigation_multi_json", _fake_investigation(
        seen, [{"lat": far, "lon": 48.3, "peak_zscore": 8.0,
                "peak_residual_m": 2.0, "evidence_type": "DEM"}],
        [_stab(far, 48.3)], [_xc(far, 48.3)]))
    monkeypatch.setattr(debate_mobile, "run_debate_json", _no_debate)
    gpr.refine_candidate(root, cid)
    m = _marker(root, cid)
    assert m["stability"] is None and m["dem_cross_check"] is None
