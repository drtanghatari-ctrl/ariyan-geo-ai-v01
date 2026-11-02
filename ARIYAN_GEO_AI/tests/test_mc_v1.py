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
