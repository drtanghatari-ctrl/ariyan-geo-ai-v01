"""cbv-v1: read-only code bundle view."""
import json

import code_bundle_view as cbv
import grand_project_db as db
import provenance_ledger as pl


def _job_with_record(tmp_path, files):
    root = str(tmp_path)
    gp = db.create_grand_project(root, "t")
    centers = [{"tile_index": 0, "center_lat": 32.1, "center_lon": 48.3}]
    jid = db.create_wide_area_search_job(root, gp, "cbjob", "MANUAL_BBOX", 32.1, 32.11, 48.3, 48.31, 1000, centers)
    t = db.list_tiles_for_job(root, jid)[0]
    inv = db.create_investigation(root, gp, "", "", {})
    db.mark_tile_done(root, t["id"], inv)
    cid = db.create_candidate(root, gp, inv, 32.1, 48.3, score=9.0)
    md5 = "ab12cd34" + "0" * 24
    conn = db.get_connection(root)
    try:
        pl.ensure_schema(conn)
        with conn:
            conn.execute("INSERT INTO provenance_code_bundle VALUES (?,?,?,?)",
                         (md5, json.dumps(files), 1, "2026-10-06T10:00:00Z"))
            for i in range(3):
                conn.execute(
                    "INSERT INTO provenance_record (evidence_link_id, candidate_id, evidence_type, "
                    "evidence_sha256, capture_state, sources_json, code_bundle_md5, ledger_version, "
                    "recorded_at, prev_hash, record_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (900 + i, cid, "DEM", "x", "CAPTURED", "[]", md5, "v", "2026-10-06T1%d:00:00Z" % i, "p", "h"))
    finally:
        conn.close()
    return root, jid, md5


def test_bundle_files_compares_with_installed_code(tmp_path):
    real = cbv._current_md5("grand_project_db", "grand_project_db.py")
    assert real
    files = [{"module": "grand_project_db", "file": "grand_project_db.py", "md5": real},
             {"module": "provenance_ledger", "file": "provenance_ledger.py", "md5": "0" * 32},
             {"module": "gone_module_xyz", "file": "gone_module_xyz.py", "md5": "1" * 32}]
    root, jid, md5 = _job_with_record(tmp_path, files)
    r = cbv.bundle_files(root, md5[:8])
    st = {f["file"]: f["status"] for f in r["files"]}
    assert st == {"grand_project_db.py": "same as now", "provenance_ledger.py": "CHANGED since",
                  "gone_module_xyz.py": "not in app now"}
    assert r["rows_using"] == 3
    assert r["report_text"].index("CHANGED since") < r["report_text"].index("grand_project_db.py  same")


def test_job_bundles_and_errors(tmp_path):
    root, jid, md5 = _job_with_record(tmp_path, [])
    j = cbv.job_bundles(root, jid[:6])
    assert [(b["bundle_md5"], b["rows"]) for b in j["bundles"]] == [(md5, 3)]
    assert j["bundles"][0]["last"] == "2026-10-06T12:00:00Z"
    assert "error" in json.loads(cbv.bundle_files_json(root, "ab1"))
    assert "error" in json.loads(cbv.bundle_files_json(root, "ffffff"))
    assert "error" in json.loads(cbv.job_bundles_json(root, "zzzzzz"))
