"""dbr-v1 + asm-v1 (2026-10-31): AI Debate results are stored (append-only)
from every run and Pass 2 refinement, and the Final Image Assessment panel
shows only what was recorded. Storing never blocks a run; nothing changes a
candidate's status, review or confidence."""
import json

import debate_mobile
import debate_store
import assessment_mobile as asm
import grand_project_db as db
import grand_project_refinement as gpr
import grand_project_sync as gps
import investigation_multi_mobile as imm
from test_ccf_v1 import _setup, _fake_investigation


def _investigation():
    return {"aoi": {"cell_size_m": 10.4},
            "anomalies": [{"lat": 32.1, "lon": 48.3, "row": 5, "col": 5, "area_cells": 4,
                           "peak_residual_m": 2.5, "mean_residual_m": 1.2, "peak_zscore": 7.5,
                           "polarity": "positive", "evidence_type": "DEM"}],
            "correlation": [], "evidence": [], "sources": ["DEM"]}


def test_real_run_stores_the_whole_debate(tmp_path):
    root = str(tmp_path)
    gp = db.create_grand_project(root, "t")
    inv_json = json.dumps(_investigation())
    debate_json = debate_mobile.run_debate_json(inv_json)          # the REAL debate engine
    assert "debates" in json.loads(debate_json)
    res = gps.record_investigation_results(root, gp, inv_json, debate_json=debate_json)
    cid = res["candidate_ids"][0]
    rows = debate_store.list_for_candidate(root, cid)
    assert len(rows) == 1 and rows[0]["origin"] == "run"
    d = rows[0]["debate"]
    assert {p["perspective"] for p in d["positions"]} and "synthesis" in d
    assert len(rows[0]["engine_sha256"]) == 64 and rows[0]["investigation_id"] == res["investigation_id"]


def test_run_without_debate_stores_nothing_and_still_persists(tmp_path):
    root = str(tmp_path)
    gp = db.create_grand_project(root, "t")
    res = gps.record_investigation_results(root, gp, json.dumps(_investigation()), debate_json=None)
    assert res["candidate_ids"] and debate_store.list_for_candidate(root, res["candidate_ids"][0]) == []


def test_storage_failure_never_blocks(tmp_path, monkeypatch):
    root = str(tmp_path)
    gp = db.create_grand_project(root, "t")
    monkeypatch.setattr(debate_store, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    inv_json = json.dumps(_investigation())
    res = gps.record_investigation_results(root, gp, inv_json, debate_json=debate_mobile.run_debate_json(inv_json))
    assert res["candidate_ids"]


def test_refinement_stores_its_debate(tmp_path, monkeypatch):
    root, cid = _setup(tmp_path)
    monkeypatch.setattr(imm, "run_investigation_multi_json", _fake_investigation(
        {}, [{"lat": 32.1, "lon": 48.3, "peak_zscore": 8.0, "peak_residual_m": 2.0, "evidence_type": "DEM"}], [], []))
    deb = {"candidate_id": "#1", "positions": [{"perspective": "Anthropogenic", "stance": "s",
                                                "confidence_score": 0.5, "confidence_label": "MODERATE",
                                                "reasoning": ["r"], "insufficient_data": False}],
           "synthesis": {"leading_position": "Anthropogenic", "agreement_level": "WEAK_SIGNAL"},
           "steward": {"reasoning_trace": {"confidence": {"band": "MODERATE", "clamped_confidence": 0.55,
                                                          "reasoning": ["ceiling held at MODERATE"]}}}}
    monkeypatch.setattr(debate_mobile, "run_debate_json", lambda _: json.dumps({"debates": [deb]}))
    gpr.refine_candidate(root, cid)
    rows = debate_store.list_for_candidate(root, cid)
    assert len(rows) == 1 and rows[0]["origin"] == "refinement"
    a = json.loads(asm.assessment_json(root, cid))
    assert a["debates"][0]["synthesis"]["leading_position"] == "Anthropogenic"
    assert a["debates"][0]["steward_band"] == "MODERATE" and a["debate_note"] is None
    assert a["history"] and "ceiling held at MODERATE" in a["history"][-1]["reasoning"]


def test_old_candidate_gets_honest_not_stored_note_and_nothing_changes(tmp_path):
    root, cid = _setup(tmp_path)
    db.record_confidence_history(root, cid, band="LOW", numeric_confidence=0.35,
                                 reasoning_snapshot=["Environmental confounders ... ceiling held at MODERATE"])
    conn = db.get_connection(root)
    before = tuple(conn.execute("SELECT * FROM candidate WHERE id=?", (cid,)).fetchone()); conn.close()
    a = json.loads(asm.assessment_json(root, cid))
    assert a["debates"] == [] and "not stored" not in "" and "before debates were stored" in a["debate_note"]
    assert a["history"][0]["band"] == "LOW" and a["history"][0]["numeric"] == 0.35
    assert "Recorded results only" in a["statement"]
    conn = db.get_connection(root)
    after = tuple(conn.execute("SELECT * FROM candidate WHERE id=?", (cid,)).fetchone()); conn.close()
    assert before == after


def test_store_rejects_non_debates_and_bad_origin(tmp_path):
    root, cid = _setup(tmp_path)
    import pytest
    with pytest.raises(ValueError):
        debate_store.record(root, cid, {"no": "positions"}, None, "run")
    with pytest.raises(ValueError):
        debate_store.record(root, cid, {"positions": []}, None, "guess")
    assert debate_store.record_quietly(root, cid, None, None, "run") is None
    assert json.loads(asm.assessment_json(root, "nope"))["error"] == "candidate not found"
