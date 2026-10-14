"""rp-v1: the automatic review counts a live Pass 2 reproduction as
Supported only when the matching anomaly had the SAME polarity as the
Pass 1 detection, and its reason quotes the T3 and T4 measurements
(rp-v1.1, 2026-10-14)."""
import grand_project_db as db
import grand_project_review as review


def _cand(tmp_path, score=7.0, p1_polarity="positive"):
    root = str(tmp_path)
    gp = db.create_grand_project(root, "t")
    inv = db.create_investigation(root, gp, "", "", {})
    cid = db.create_candidate(root, gp, inv, 32.1, 48.3, score=score)
    if p1_polarity:
        db.add_evidence_link(root, cid, evidence_type="DEM", relation="primary_detection",
                             detail={"polarity": p1_polarity, "peak_zscore": score})
    return root, cid


def _marker(root, cid, **detail):
    base = {"reproduced": True, "dem_source": "LIVE", "dem_type": "SRTMGL1",
            "match_distance_m": 20.0}
    base.update(detail)
    db.add_evidence_link(root, cid, evidence_type="DEM", relation="refinement_dem_check",
                         detail=base)


def _verdict(root, cid):
    conn = review._connect(root)
    try:
        v, unreadable = review._refinement_verdicts(root, conn, {cid})
    finally:
        conn.close()
    assert not unreadable
    return v[cid]


def test_pol_v1_reproduction_is_supported_with_t3_note(tmp_path):
    root, cid = _cand(tmp_path)
    _marker(root, cid, polarity_rule="pol-v1", pass1_polarity="positive",
            refinement_anomaly={"polarity": "positive"})
    status, why = _verdict(root, cid)
    assert status == review.STATUS_SUPPORTED
    assert "same polarity" in why and "T3" in why and "not a confirmed site" in why
    assert "T4" in why and "37%" in why and "6%" in why and "p = 0.03 and 0.001" in why


def test_evidence_note_quotes_both_tests_and_keeps_the_caveat():
    note = review.REPRODUCTION_EVIDENCE_NOTE
    assert note.startswith("Supporting evidence only")
    for part in ("T3", "26%", "8%", "T4", "37%", "6%", "Urmia", "Deh Luran",
                 "Most real sites are not reproduced", "not a confirmed site"):
        assert part in note


def test_old_row_same_polarity_still_supported(tmp_path):
    root, cid = _cand(tmp_path)
    _marker(root, cid, refinement_anomaly={"peak_residual_m": 3.0})
    assert _verdict(root, cid)[0] == review.STATUS_SUPPORTED


def test_old_row_bump_matched_by_hollow_is_inconclusive(tmp_path):
    root, cid = _cand(tmp_path)  # the b626e79c case
    _marker(root, cid, refinement_anomaly={"polarity": "negative", "peak_residual_m": -4.9})
    status, why = _verdict(root, cid)
    assert status == review.STATUS_INCONCLUSIVE and "OPPOSITE polarity" in why


def test_old_row_hollow_matched_by_hollow_supported_via_score_sign(tmp_path):
    root, cid = _cand(tmp_path, score=-7.0, p1_polarity=None)
    _marker(root, cid, refinement_anomaly={"peak_zscore": -3.1})
    assert _verdict(root, cid)[0] == review.STATUS_SUPPORTED


def test_unreadable_polarity_is_inconclusive(tmp_path):
    root, cid = _cand(tmp_path, score=None, p1_polarity=None)
    _marker(root, cid, refinement_anomaly={})
    status, why = _verdict(root, cid)
    assert status == review.STATUS_INCONCLUSIVE and "could not be read" in why


def test_later_good_row_wins_over_earlier_bad_row(tmp_path):
    root, cid = _cand(tmp_path)
    _marker(root, cid, refinement_anomaly={"polarity": "negative"})
    _marker(root, cid, polarity_rule="pol-v1", pass1_polarity="positive",
            refinement_anomaly={"polarity": "positive"})
    assert _verdict(root, cid)[0] == review.STATUS_SUPPORTED


def test_not_reproduced_live_unchanged(tmp_path):
    root, cid = _cand(tmp_path)
    _marker(root, cid, reproduced=False, polarity_rule="pol-v1", pass1_polarity="positive")
    status, why = _verdict(root, cid)
    assert status == review.STATUS_INCONCLUSIVE and "not evidence against" in why

