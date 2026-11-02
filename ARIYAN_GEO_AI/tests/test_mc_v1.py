"""mc-v1 + dbe-v1 (2026-11-02): Mission Control start page and AI Debate Engine
screen. Read-only: recorded results only, nothing recomputed or changed."""
import hashlib
import json
import os

import debate_store
import grand_project_db as db
import mission_control as mc


def _debate(leading="Anthropogenic", agreement="WEAK_SIGNAL", band="MODERATE", clamped=True):
    return {"candidate_id": "#1",
            "positions": [{"perspective": p, "stance": "s " + p, "confidence_score": 0.5, "confidence_label": "MODERATE",
                           "reasoning": ["r"], "insufficient_data": False}
                          for p in ("Geomorphology", "Anthropogenic", "Artifact Skeptic", "Vegetation")],
            "synthesis": {"leading_position": leading, "leading_confidence": 0.62, "agreement_level": agreement,
                          "steward_note": "note"},
            "steward": {"reasoning_trace": {"confidence": {"band": band, "clamped_confidence": 0.55,
                                                           "raw_confidence": 0.62, "was_clamped": clamped,
                                                           "reasoning": ["ceiling held at MODERATE"]}}}}


def _project(root):
    gid = db.create_grand_project(root, "Default Grand Project", project_id="default")
    inv = db.create_investigation(root, gid, objective="t")
    ids = []
    for i, (band, num, status, z) in enumerate([("MODERATE", 0.55, "SUPPORTED", 7.0),
                                                ("MODERATE", 0.55, "GENERATED", 9.0),
                                                ("LOW", 0.30, "GENERATED", 12.0),
                                                ("MODERATE", 0.55, "REJECTED", 20.0),
                                                (None, None, "GENERATED", 3.0)]):
        cid = db.create_candidate(root, gid, inv, 32.0 + i * 0.01, 48.0, score=z)
        if band:
            db.update_candidate_confidence(root, cid, band, num)
        if status != "GENERATED":
            db.update_candidate_status(root, gid, cid, status)
        ids.append(cid)
    db.record_confidence_history(root, ids[0], band="MODERATE", numeric_confidence=0.55,
                                 reasoning_snapshot=["two sources agree",
                                                     "Environmental confounders not controlled: ceiling held at MODERATE"])
    return gid, ids


def _db_md5(root):
    with open(os.path.join(root, db.DB_FILENAME), "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def test_empty_store_has_no_project_and_still_lists_sources(tmp_path):
    m = json.loads(mc.mission_json(str(tmp_path)))
    assert "error" not in m and m["project"] is None and m["empty_note"]
    assert any(s["name"].startswith("Terrain DEM") and not s["ok"] for s in m["sources"])
    assert m["principles"][0] == "Real Data Only"


def test_bands_exclude_rejected_and_report_the_ceiling(tmp_path):
    root = str(tmp_path)
    _project(root)
    m = json.loads(mc.mission_json(root))
    bands = {b["band"]: b["count"] for b in m["confidence"]["bands"]}
    assert bands["MODERATE"] == 2 and bands["LOW"] == 1 and bands["NOT_RATED"] == 1 and bands["HIGH"] == 0
    c = m["confidence"]
    assert c["rejected"] == 1 and c["highest"] == "MODERATE" and c["highest_ceiling"] == 0.55
    assert c["highest_numeric"] == 0.55          # mc-v1.1 gauge needle: a stored value, never invented
    assert "GPR/ERT" in c["why"]
    assert c["steward_words"] == ["Environmental confounders not controlled: ceiling held at MODERATE"]
    assert m["project"]["candidates"] == 5 and m["project"]["status_counts"]["Rejected"] == 1


def test_targets_order_band_then_supported_and_no_rejected(tmp_path):
    root = str(tmp_path)
    _, ids = _project(root)
    top = json.loads(mc.mission_json(root, 10))["top"]
    assert [t["id"] for t in top] == [ids[0], ids[1], ids[2], ids[4]]       # rejected id[3] absent
    assert top[0]["status"] == "Supported" and top[-1]["band"] == "NOT_RATED"


def test_mission_changes_nothing(tmp_path):
    root = str(tmp_path)
    _project(root)
    mc.mission_json(root)                    # first call may take today's backup
    before = _db_md5(root)
    mc.mission_json(root)
    mc.debates_json(root)
    assert _db_md5(root) == before


def test_data_sources_count_real_files(tmp_path):
    root = str(tmp_path)
    _project(root)
    os.makedirs(os.path.join(root, "ir", "dem"))
    open(os.path.join(root, "ir", "dem", "N32_E048.tif"), "wb").write(b"x" * 10)
    os.makedirs(os.path.join(root, "dem_library", "SRTMGL1"))
    open(os.path.join(root, "dem_library", "SRTMGL1", "N32E048.tif"), "wb").write(b"x")
    src = {s["name"]: s for s in json.loads(mc.mission_json(root))["sources"]}
    assert src["Terrain DEM, bulk COP30 (Pass 1)"]["ok"] and "1 tile" in src["Terrain DEM, bulk COP30 (Pass 1)"]["detail"]
    assert src["DEM library SRTMGL1 (Pass 2)"]["ok"] and not src["DEM library COP30 (Pass 2)"]["ok"]
    assert not src["Field data (GPR/ERT)"]["ok"]


def test_gauge_value_ignores_rejected_and_lower_bands(tmp_path):
    root = str(tmp_path)
    gid, ids = _project(root)
    db.update_candidate_confidence(root, ids[3], "MODERATE", 0.70)          # Rejected: must not move the needle
    db.update_candidate_confidence(root, ids[2], "LOW", 0.34)
    c = json.loads(mc.mission_json(root))["confidence"]
    assert c["highest"] == "MODERATE" and c["highest_numeric"] == 0.55


def test_empty_project_has_no_needle(tmp_path):
    root = str(tmp_path)
    db.create_grand_project(root, "Default Grand Project", project_id="default")
    c = json.loads(mc.mission_json(root))["confidence"]
    assert c["highest"] is None and c["highest_numeric"] is None


def test_debates_list_summary_filter_and_detail(tmp_path):
    root = str(tmp_path)
    _, ids = _project(root)
    debate_store.record(root, ids[0], _debate(), None, "run")
    debate_store.record(root, ids[1], _debate("Geomorphology", "CONTESTED", clamped=False), None, "refinement")
    debate_store.record(root, ids[0], _debate(), None, "refinement")
    r = json.loads(mc.debates_json(root))
    s = r["summary"]
    assert s["debates"] == 3 and s["candidates"] == 2
    assert s["by_agreement"]["WEAK_SIGNAL"] == 2 and s["by_agreement"]["CONTESTED"] == 1
    assert s["by_leading"] == {"Anthropogenic": 2, "Geomorphology": 1}
    assert s["steward_capped"] == 2 and s["steward_rated"] == 3
    assert [x["candidate_id"] for x in r["rows"]] == [ids[0], ids[1], ids[0]]           # newest first
    only = json.loads(mc.debates_json(root, "CONTESTED"))["rows"]
    assert len(only) == 1 and only[0]["leading"] == "Geomorphology"
    page = json.loads(mc.debates_json(root, "ALL", 2, 0))
    assert len(page["rows"]) == 2 and page["more"] is True
    d = json.loads(mc.debate_detail_json(root, r["rows"][0]["id"]))
    assert len(d["positions"]) == 4 and d["steward"]["band"] == "MODERATE" and d["debates_for_candidate"] == 2


def test_python_fallback_matches_json_functions(tmp_path, monkeypatch):
    root = str(tmp_path)
    _, ids = _project(root)
    debate_store.record(root, ids[0], _debate(), None, "run")
    debate_store.record(root, ids[1], _debate("Geomorphology", "CONTESTED", clamped=False), None, "run")
    a = json.loads(mc.debates_json(root, "CONTESTED"))
    monkeypatch.setattr(mc, "_json_functions", lambda conn: False)
    b = json.loads(mc.debates_json(root, "CONTESTED"))
    assert a["summary"]["by_agreement"] == b["summary"]["by_agreement"]
    assert [x["id"] for x in a["rows"]] == [x["id"] for x in b["rows"]]


def test_no_debates_and_bad_input_are_reported_not_hidden(tmp_path):
    root = str(tmp_path)
    _project(root)
    r = json.loads(mc.debates_json(root))
    assert r["rows"] == [] and r["note"]
    assert "error" in json.loads(mc.debates_json(root, "MAYBE"))
    assert "error" in json.loads(mc.debate_detail_json(root, 999))


# --- mc-v1.3 layer thumbnails: saved images only, never a fetch ----------------

def test_thumbs_never_fetch_and_report_each_layer(tmp_path, monkeypatch):
    import sat_image as si
    import sat_image_mobile as sim
    import ndvi_source_mobile as ndvi
    from test_fi_v2 import FakeCDSE, _scenes
    from test_fi_v2_mobile import _fake_session
    fake = FakeCDSE(_scenes())
    monkeypatch.setattr(sim, "_HTTP", fake)
    monkeypatch.setattr(ndvi, "get_access_token", lambda a, b, *k: "tok")
    root = str(tmp_path)
    sid, _ = _fake_session()
    r = json.loads(mc.thumbs_json(root, sid))
    assert [x["product"] for x in r["layers"]] == list(si.LAYER_ORDER)
    assert all(x["state"] == "NOT_SAVED" for x in r["layers"]) and fake.total == 0
    json.loads(sim.open_layer_json(root, sid, "THERMAL", "id", "sec", True))        # the user fetched it once
    before = fake.total
    r = json.loads(mc.thumbs_json(root, sid))
    states = {x["product"]: x for x in r["layers"]}
    assert states["THERMAL"]["state"] == "SAVED" and states["THERMAL"]["width"] > 0
    assert states["NDVI"]["state"] == "NOT_SAVED"
    assert fake.total == before                                                     # thumbnails fetched nothing
    assert len(sim.layer_rgba(sid, "THERMAL")) == states["THERMAL"]["width"] * states["THERMAL"]["height"] * 4


def test_thumbs_bad_session_is_reported(tmp_path):
    r = json.loads(mc.thumbs_json(str(tmp_path), "nope"))
    assert all(x["state"] == "ERROR" for x in r["layers"])


# --- mc-v1.3 Analysis & Models + Settings ------------------------------------------

def test_models_read_from_code_and_db(tmp_path):
    root = str(tmp_path)
    _project(root)
    m = json.loads(mc.models_json(root))
    names = {r["name"]: r for r in m["models"]}
    assert names["Pass 2 reproduction rule"]["version"] == "pol-v1"
    assert names["Land cover rule"]["version"] == "lc-v2"
    assert names["Terrain labels / Hillside"]["version"] == "f3-v2"
    assert names["calib-v1 score threshold"]["version"] == "not adopted"      # nothing adopted in this store
    assert all(r["version"] for r in m["models"])


def test_settings_reports_backups_guard_and_changes_nothing(tmp_path):
    root = str(tmp_path)
    _project(root)
    os.makedirs(os.path.join(root, "crash_reports"))
    open(os.path.join(root, "crash_reports", "crash_20261102T101010Z.txt"), "w").write("x")
    os.makedirs(os.path.join(root, db.BACKUP_DIRNAME), exist_ok=True)
    open(os.path.join(root, db.BACKUP_DIRNAME, "grand_project_auto_20261102.db"), "wb").write(b"x" * 5)
    before = _db_md5(root)
    s = json.loads(mc.settings_json(root))
    assert s["database"]["exists"] and s["database"]["bytes"] > 0
    assert s["guard"] is not None and not s["allow_new_flag"]
    assert s["backups"]["files"] and s["backups"]["files"][0]["name"].startswith("grand_project_auto_")
    assert s["crash_reports"] == {"count": 1, "newest": "crash_20261102T101010Z.txt"}
    assert _db_md5(root) == before


# --- mc-v1.4 backups: safe-to-delete marks and deleting one ------------------------

def _backups(root, spec):
    d = os.path.join(root, db.BACKUP_DIRNAME)
    os.makedirs(d, exist_ok=True)
    for old in os.listdir(d):                 # drop the real backup taken today by get_connection()
        os.remove(os.path.join(d, old))
    for name, size in spec:
        with open(os.path.join(d, name), "wb") as f:
            f.write(b"x" * size)
    return d


def test_backup_rule_three_newest_and_largest_protected(tmp_path):
    root = str(tmp_path)
    _project(root)
    _backups(root, [("grand_project_auto_20261102.db", 30), ("grand_project_auto_20261031.db", 30),
                    ("grand_project_auto_20261030.db", 30), ("grand_project_auto_20261024.db", 50),
                    ("grand_project_auto_20261023.db", 10), ("grand_project_auto_20261021.db", 10),
                    ("my_copy_before_test.db", 5)])
    marks = {f["name"]: f for f in mc.backup_list(root)}
    for n in ("grand_project_auto_20261102.db", "grand_project_auto_20261031.db", "grand_project_auto_20261030.db"):
        assert not marks[n]["deletable"] and "newest" in marks[n]["protected_reason"]
    assert not marks["grand_project_auto_20261024.db"]["deletable"]                 # the largest
    assert marks["grand_project_auto_20261023.db"]["deletable"] and marks["grand_project_auto_20261021.db"]["deletable"]
    assert not marks["my_copy_before_test.db"]["deletable"]


def test_delete_only_a_safe_one_and_it_is_logged(tmp_path):
    root = str(tmp_path)
    _project(root)
    d = _backups(root, [("grand_project_auto_20261102.db", 30), ("grand_project_auto_20261031.db", 30),
                        ("grand_project_auto_20261030.db", 30), ("grand_project_auto_20261021.db", 10)])
    r = json.loads(mc.delete_backup_json(root, "grand_project_auto_20261021.db"))
    assert r["deleted"] == "grand_project_auto_20261021.db" and r["logged"]
    assert not os.path.exists(os.path.join(d, "grand_project_auto_20261021.db"))
    conn = db.get_connection(root)
    try:
        ev = conn.execute("SELECT * FROM timeline_event WHERE event_type = 'BACKUP_DELETED_BY_USER'").fetchall()
    finally:
        conn.close()
    assert len(ev) == 1 and ev[0]["related_entity_id"] == "grand_project_auto_20261021.db"


def test_delete_refuses_protected_live_db_paths_and_own_copies(tmp_path):
    root = str(tmp_path)
    _project(root)
    d = _backups(root, [("grand_project_auto_20261102.db", 30), ("grand_project_auto_20261031.db", 30),
                        ("grand_project_auto_20261030.db", 30), ("my_copy.db", 5)])
    for bad in ("grand_project_auto_20261102.db",            # newest
                "grand_project.db",                           # the live database
                "../grand_project.db", "my_copy.db",          # path trick, own copy
                "grand_project_auto_20990101.db"):            # does not exist
        assert "error" in json.loads(mc.delete_backup_json(root, bad))
    assert os.path.exists(os.path.join(root, db.DB_FILENAME))
    assert sorted(os.listdir(d)) == sorted(["grand_project_auto_20261102.db", "grand_project_auto_20261031.db",
                                            "grand_project_auto_20261030.db", "my_copy.db"])
