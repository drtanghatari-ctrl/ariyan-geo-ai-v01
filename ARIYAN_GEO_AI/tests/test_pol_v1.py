"""pol-v1: a Pass 2 anomaly reproduces a Pass 1 candidate only if it has
the SAME polarity (raised bump vs hollow). Same stand-in pattern as
test_ccf_v1.py: the expensive investigation call is replaced, every other
step of refine_candidate runs for real."""
import json

import grand_project_db as db
import grand_project_refinement as gpr
import investigation_multi_mobile as imm
import debate_mobile

NORTH_20M = 0.00018  # ~20 m of latitude


def _setup(tmp_path, score=9.0, p1_detail=None):
    root = str(tmp_path)
    gp = db.create_grand_project(root, "t")
    centers = [{"tile_index": 0, "center_lat": 32.1, "center_lon": 48.3}]
    jid = db.create_wide_area_search_job(root, gp, "j", "MANUAL_BBOX",
                                         32.1, 32.11, 48.3, 48.31, 1000, centers)
    t = db.list_tiles_for_job(root, jid)[0]
    inv = db.create_investigation(root, gp, "", "", {})
    db.mark_tile_done(root, t["id"], inv)
    cid = db.create_candidate(root, gp, inv, 32.1, 48.3, score=score)
    if p1_detail is not None:
        db.add_evidence_link(root, cid, evidence_type="DEM",
                             relation="primary_detection", detail=p1_detail)
    return root, cid


def _anom(lat, residual, polarity=None):
    a = {"lat": lat, "lon": 48.3, "peak_zscore": 3.0 if residual > 0 else -3.0,
         "peak_residual_m": residual, "evidence_type": "DEM"}
    if polarity is not None:
        a["polarity"] = polarity
    return a


def _run(root, cid, monkeypatch, anomalies):
    def inv(lat, lon, radius_m, grid_size, **kw):
        return json.dumps({"aoi": {"cell_size_m": 10.4}, "anomalies": anomalies,
                           "correlation": [], "evidence": [],
                           "seventh_evidence_detail": [], "tenth_evidence_detail": []})

    def no_debate(_):
        raise RuntimeError("debate not part of this test")
    monkeypatch.setattr(imm, "run_investigation_multi_json", inv)
    monkeypatch.setattr(debate_mobile, "run_debate_json", no_debate)
    return gpr.refine_candidate(root, cid)


def _marker(root, cid):
    import sqlite3
    con = sqlite3.connect(db._db_path(root))
    rows = con.execute(
        "SELECT detail_json FROM evidence_link WHERE candidate_id=? "
        "AND relation='refinement_dem_check'", (cid,)).fetchall()
    con.close()
    assert len(rows) == 1
    return json.loads(rows[0][0])


def test_polarity_of():
    assert gpr._polarity_of({"polarity": "negative", "peak_residual_m": 2.0}) == "negative"
    assert gpr._polarity_of({"peak_residual_m": -1.2}) == "negative"
    assert gpr._polarity_of({"peak_zscore": 6.5}) == "positive"
    assert gpr._polarity_of({"peak_zscore": 0}) is None
    assert gpr._polarity_of({"peak_zscore": True}) is None
    assert gpr._polarity_of({}) is None and gpr._polarity_of(None) is None


def test_bump_is_not_reproduced_by_hollow(tmp_path, monkeypatch):
    # the b626e79c case: raised Pass 1 bump, only a hollow on the spot
    root, cid = _setup(tmp_path, p1_detail={"polarity": "positive",
                                            "peak_zscore": 6.85, "peak_residual_m": 1.7})
    r = _run(root, cid, monkeypatch, [_anom(32.1, -4.9, "negative")])
    assert r["reproduced"] is False
    m = _marker(root, cid)
    assert m["reproduced"] is False and m["polarity_rule"] == "pol-v1"
    assert m["pass1_polarity"] == "positive"
    assert m["opposite_polarity_within_tolerance"]["polarity"] == "negative"
    assert m["nearest_unmatched_anomaly"] is None  # no same-sign anomaly at all
    assert m["stability"] is None and m["dem_cross_check"] is None


def test_same_sign_anomaly_wins_over_nearer_opposite(tmp_path, monkeypatch):
    root, cid = _setup(tmp_path, p1_detail={"polarity": "positive"})
    r = _run(root, cid, monkeypatch,
             [_anom(32.1, -4.0), _anom(32.1 + NORTH_20M, 3.0)])
    assert r["reproduced"] is True
    m = _marker(root, cid)
    assert m["refinement_anomaly"]["peak_residual_m"] == 3.0
    assert 15.0 < m["match_distance_m"] < 25.0
    assert m["opposite_polarity_within_tolerance"]["distance_m"] < 1.0


def test_hollow_reproduced_by_hollow(tmp_path, monkeypatch):
    root, cid = _setup(tmp_path, score=-7.5,
                       p1_detail={"polarity": "negative", "peak_zscore": -7.5})
    r = _run(root, cid, monkeypatch, [_anom(32.1, -3.6)])
    assert r["reproduced"] is True
    m = _marker(root, cid)
    assert m["pass1_polarity"] == "negative"
    assert m["opposite_polarity_within_tolerance"] is None


def test_detection_row_polarity_beats_score_sign(tmp_path, monkeypatch):
    root, cid = _setup(tmp_path, score=9.0, p1_detail={"polarity": "negative"})
    r = _run(root, cid, monkeypatch, [_anom(32.1, 2.0)])
    assert r["reproduced"] is False
    assert _marker(root, cid)["pass1_polarity"] == "negative"


def test_score_sign_used_when_no_detection_row(tmp_path, monkeypatch):
    root, cid = _setup(tmp_path, score=-6.0)
    r = _run(root, cid, monkeypatch, [_anom(32.1, 2.0)])
    assert r["reproduced"] is False
    assert _marker(root, cid)["pass1_polarity"] == "negative"


def test_unknown_polarity_falls_back_to_any_sign(tmp_path, monkeypatch):
    root, cid = _setup(tmp_path, score=None)
    r = _run(root, cid, monkeypatch, [_anom(32.1, -4.0)])
    assert r["reproduced"] is True
    m = _marker(root, cid)
    assert m["pass1_polarity"] is None and m["polarity_rule"] == "pol-v1"
    assert m["opposite_polarity_within_tolerance"] is None
