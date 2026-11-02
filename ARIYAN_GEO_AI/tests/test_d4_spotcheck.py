"""d4-v1 (2026-11-02): tank/silo spot-check list. Read-only ranking; verdicts are notes
that never change a status, review, confidence or evidence row."""
import json

import grand_project_db as db
import land_cover_flags as lcf
import spotcheck_tanks as sc


def _lc_row(conn, cid, c_built, r_built, ring_valid=40):
    conn.execute("INSERT INTO candidate_land_cover_v2 (candidate_id, computed_at, source, method, centre_px, "
                 "centre_valid, c_tree, c_built, c_water, c_crop, ring_valid, r_tree, r_built, r_water, r_crop) "
                 "VALUES (?, '2026-11-02', 'test', 'lc-v2', 9, 9, 0, ?, 0, 0, ?, 0, ?, 0, 0)",
                 (cid, c_built, ring_valid, r_built))


def _setup(tmp_path, monkeypatch):
    root = str(tmp_path)
    gid = db.create_grand_project(root, "Default Grand Project", project_id="default")
    inv = db.create_investigation(root, gid, objective="t")
    ids = [db.create_candidate(root, gid, inv, 32.0 + i * 0.01, 48.0, score=6.0 + i) for i in range(5)]
    db.update_candidate_status(root, gid, ids[4], "REJECTED")
    conn = db.get_connection(root)
    try:
        conn.executescript(lcf._TABLE_V2_SQL)
        _lc_row(conn, ids[0], 0.0, 0.40)          # listed, top
        _lc_row(conn, ids[1], 0.1, 0.20)          # listed, second
        _lc_row(conn, ids[2], 0.0, 0.05)          # below MIN_RING_BUILT: not listed
        _lc_row(conn, ids[3], 0.0, 0.60)          # near mapped industry (patched): excluded
        _lc_row(conn, ids[4], 0.0, 0.90)          # rejected: not listed
        conn.commit()
    finally:
        conn.close()
    import industrial_index as ii
    monkeypatch.setattr(ii, "in_coverage", lambda la, lo: True)
    monkeypatch.setattr(ii, "features_within", lambda la, lo, r=300.0:
                        [{"kind": "man_made=storage_tank", "distance_m": 120.0}] if abs(la - 32.03) < 1e-6 else
                        ([{"kind": "landuse=industrial", "distance_m": 1500.0}] if abs(la - 32.0) < 1e-6 else []))
    return root, ids


def _snapshot(root):
    conn = db.get_connection(root)
    try:
        return [tuple(r) for r in conn.execute("SELECT id, status, confidence_band, confidence_numeric FROM candidate ORDER BY id")]
    finally:
        conn.close()


def test_list_ranks_and_excludes(tmp_path, monkeypatch):
    root, ids = _setup(tmp_path, monkeypatch)
    r = json.loads(sc.spotcheck_json(root))
    assert "error" not in r, r
    assert [x["id"] for x in r["rows"]] == [ids[0], ids[1]]
    assert r["summary"]["listed"] == 2 and r["summary"]["excluded_near_mapped_industry"] == 1
    assert r["rows"][0]["industry_2km"] == {"kind": "landuse=industrial", "distance_m": 1500.0}
    assert r["rows"][1]["industry_2km"] is None


def test_verdicts_are_notes_only(tmp_path, monkeypatch):
    root, ids = _setup(tmp_path, monkeypatch)
    before = _snapshot(root)
    assert "error" not in json.loads(sc.record_verdict_json(root, ids[0], "CANT_TELL"))
    assert "error" not in json.loads(sc.record_verdict_json(root, ids[0], "tank_or_silo", "white round tanks"))
    r = json.loads(sc.spotcheck_json(root))
    assert r["rows"][0]["verdict"]["verdict"] == "TANK_OR_SILO"          # newest wins
    assert r["summary"]["checked"] == 1 and r["summary"]["verdicts"]["TANK_OR_SILO"] == 1
    unchecked = json.loads(sc.spotcheck_json(root, 40, False))
    assert [x["id"] for x in unchecked["rows"]] == [ids[1]]
    assert _snapshot(root) == before                                     # nothing else changed
    assert "error" in json.loads(sc.record_verdict_json(root, ids[0], "MAYBE"))
    assert "error" in json.loads(sc.record_verdict_json(root, "nope", "CANT_TELL"))
