"""lc-v2: land cover judges the evidence, not the place (2026-10-07)."""
import json

import numpy as np

import grand_project_db as db
import grand_project_query_mobile as q
import grand_project_review as review
import land_cover_flags as lc


class FakeReader:
    """13 x 13 window around pixel (100, 100); class map set per test."""
    height = width = 1000

    def __init__(self, window):
        self.w = np.asarray(window, dtype=np.uint8)

    def pixel_of(self, lon, lat):
        return 100.5, 100.5

    def read_window(self, r0, r1, c0, c1):
        full = np.zeros((1000, 1000), dtype=np.uint8)
        full[94:107, 94:107] = self.w
        return full[r0:r1, c0:c1]


def _win(centre, ring):
    w = np.full((13, 13), ring, dtype=np.uint8)
    w[5:8, 5:8] = centre
    return w


def test_centre_ring_shares_and_rules():
    w = _win(60, 60)          # bare everywhere
    w[0:4, :] = 10            # trees in the ring only (52 of 160 ring px)
    s = lc.sample_centre_ring(FakeReader(w), 0, 0)
    assert s["centre_valid"] == 9 and s["c_tree"] == 0.0
    assert abs(s["r_tree"] - 52 / 160) < 1e-9
    assert lc.flag_reason_v2(s) is None            # trees nearby: kept
    assert lc.ring_labels(s) == ["trees"]
    # old rule rejects the same window (tree >= 20 % of the 13x13 window)
    assert lc.flag_reason({"center_class": 60, "frac_tree": 52 / 169,
                           "frac_built": 0, "frac_water": 0}) == "tree_or_built"


def test_centre_covered_rejects_with_dominant_reason():
    s = lc.sample_centre_ring(FakeReader(_win(80, 60)), 0, 0)
    assert lc.flag_reason_v2(s) == "water"
    s = lc.sample_centre_ring(FakeReader(_win(10, 60)), 0, 0)
    assert lc.flag_reason_v2(s) == "tree_or_built"
    w = _win(60, 60)
    w[5, 5:8] = 50   # 3 of 9 built + 1 water = 44 % < 50 %: kept
    w[6, 5] = 80
    assert lc.flag_reason_v2(lc.sample_centre_ring(FakeReader(w), 0, 0)) is None
    w[6, 6] = 50     # 5 of 9 = 56 %: rejected
    assert lc.flag_reason_v2(lc.sample_centre_ring(FakeReader(w), 0, 0)) == "tree_or_built"


def test_too_few_valid_centre_pixels_never_rejects():
    w = _win(0, 60)
    w[5, 5] = 80
    s = lc.sample_centre_ring(FakeReader(w), 0, 0)
    assert s["centre_valid"] == 1 and lc.flag_reason_v2(s) is None


def _job(tmp_path):
    root = str(tmp_path)
    gp = db.create_grand_project(root, "t")
    centers = [{"tile_index": 0, "center_lat": 32.1, "center_lon": 48.3}]
    jid = db.create_wide_area_search_job(root, gp, "j", "MANUAL_BBOX", 32.1, 32.11, 48.3, 48.31, 1000, centers)
    t = db.list_tiles_for_job(root, jid)[0]
    inv = db.create_investigation(root, gp, "", "", {})
    db.mark_tile_done(root, t["id"], inv)
    a = db.create_candidate(root, gp, inv, 32.100, 48.300, score=5.0)
    b = db.create_candidate(root, gp, inv, 32.101, 48.301, score=5.0)
    return root, gp, jid, a, b


def _ensure(root, jid, monkeypatch, windows):
    it = iter(windows)
    monkeypatch.setattr(lc, "WorldCoverHttpTile", lambda url, http_get=None: _Seq(it))
    return lc.ensure_job_land_cover(root, jid)


class _Seq(FakeReader):
    """Returns the next window for each candidate (both reads of one
    candidate see the same window)."""
    def __init__(self, it):
        self.it = it
        self.cur = None
        self.calls = 0

    def read_window(self, r0, r1, c0, c1):
        if r1 - r0 == 13 and self.calls % 2 == 0:
            self.cur = np.asarray(next(self.it), dtype=np.uint8)
        if r1 - r0 == 13:
            self.calls += 1
        full = np.zeros((1000, 1000), dtype=np.uint8)
        full[94:107, 94:107] = self.cur
        return full[r0:r1, c0:c1]


def test_job_flags_and_auto_review_use_lc_v2(tmp_path, monkeypatch):
    root, gp, jid, a, b = _job(tmp_path)
    near_trees = _win(60, 60)
    near_trees[0:4, :] = 10
    r = _ensure(root, jid, monkeypatch, [near_trees, _win(80, 60)])
    assert r["newly_checked"] == 2 and r["method"] == "lc-v2"
    f = lc.job_flags(root, jid)
    rejected = set(f["flagged"])
    assert len(rejected) == 1 and f["by_method"] == {"lc-v2": 1}
    review.auto_review_project(root, gp)
    s = review.review_summary_for_project(root, gp)
    statuses = sorted(v["status"] for v in s.values())
    assert statuses.count("REJECTED") == 1
    kept = [cid for cid in (a, b) if cid not in rejected][0]
    assert s[kept]["status"] != "REJECTED"
    rows = {r["id"]: r for r in json.loads(q.list_candidates_json(root, gp))}
    assert rows[kept]["land_cover_text"] == "near trees (context only, not a rejection)"
    assert "lc-v2" in rows[[x for x in rejected][0]]["land_cover_text"]


def test_old_rows_keep_old_rule_until_reread(tmp_path, monkeypatch):
    root, gp, jid, a, b = _job(tmp_path)
    conn = db.get_connection(root)
    lc._ensure_table(conn)
    with conn:
        conn.execute("INSERT INTO candidate_land_cover (candidate_id, computed_at, source, window_px, "
                     "valid_px, center_class, frac_tree, frac_built, frac_water) "
                     "VALUES (?, 'x', 'wc', 13, 169, 60, 0.3, 0, 0)", (a,))
    conn.close()
    f = lc.job_flags(root, jid)
    assert f["flagged"] == {a: "tree_or_built"} and f["by_method"] == {"lc-v1": 1}
    near_trees = _win(60, 60)
    near_trees[0:4, :] = 10
    _ensure(root, jid, monkeypatch, [near_trees, near_trees])
    f = lc.job_flags(root, jid)
    assert f["flagged"] == {} and f["checked"] == 2
