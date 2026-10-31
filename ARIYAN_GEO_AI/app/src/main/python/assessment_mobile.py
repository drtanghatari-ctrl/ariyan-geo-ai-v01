"""
assessment_mobile.py -- asm-v1 (2026-10-31): the Assessment tab of the Final
Image screen. Read-only.

For one candidate it returns what was RECORDED, nothing recomputed:
  * the candidate: stored confidence band/number, status and the latest
    review reason (auto or user), job and its trust;
  * the Steward: the full confidence history (append-only), each row with
    the Steward's own reasoning lines -- which already contain the reason
    the ceiling holds (e.g. environmental confounders not controlled);
  * the AI Debate: the stored debates (dbr-v1) with the four perspectives,
    the synthesis and the debate's own Steward report. Candidates whose runs
    happened before dbr-v1 get an honest "not stored" note; no debate is
    re-created from stored evidence.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import grand_project_db as db

VERSION = "asm-v1"
NOT_STORED = ("The AI Debate for this candidate was run before debates were stored (dbr-v1, "
              "2026-10-31), so its four positions no longer exist. The Steward's verdict from "
              "those runs is kept in the confidence history above. A new run or Pass 2 "
              "refinement of this candidate will store its debate.")
STATEMENT = ("Recorded results only: nothing on this page is recomputed, and nothing here changes "
             "a status, a review or a confidence. The debate is a ranked rule-based opinion, not proof.")


def _history(db_root: str, candidate_id: str) -> List[Dict[str, Any]]:
    out = []
    for r in db.get_confidence_history(db_root, candidate_id):
        reasons = r.get("reasoning_snapshot_json")
        try:
            reasons = json.loads(reasons) if reasons else []
        except ValueError:
            reasons = [str(reasons)]
        out.append({"recorded_at": r.get("recorded_at"), "band": r.get("band"),
                    "numeric": r.get("numeric_confidence"),
                    "investigation_id": r.get("triggering_investigation_id"),
                    "reasoning": reasons if isinstance(reasons, list) else [str(reasons)]})
    return out


def _debates(db_root: str, candidate_id: str) -> List[Dict[str, Any]]:
    import debate_store
    out = []
    for r in debate_store.list_for_candidate(db_root, candidate_id):
        d = r.get("debate") or {}
        st = d.get("steward") or {}
        trace = st.get("reasoning_trace") or {}
        conf = trace.get("confidence") or {}
        out.append({
            "recorded_at": r["recorded_at"], "origin": r["origin"], "investigation_id": r["investigation_id"],
            "engine_sha256": r["engine_sha256"], "store_version": r["store_version"],
            "positions": d.get("positions") or [],
            "synthesis": d.get("synthesis") or {},
            "steward_band": conf.get("band"), "steward_numeric": conf.get("clamped_confidence"),
            "steward_reasoning": conf.get("reasoning") or [],
            "steward_error": d.get("steward_error"),
        })
    return out


def assessment_json(db_root: str, candidate_id: str) -> str:
    try:
        cand = db.get_candidate(db_root, candidate_id)
        if cand is None:
            return json.dumps({"error": "candidate not found"})
        review: Dict[str, Any] = {}
        try:
            import grand_project_review as gr
            review = gr.review_summary_for_project(db_root, cand["grand_project_id"]).get(candidate_id, {})
        except Exception as e:                       # shown, never hidden
            review = {"error": f"{type(e).__name__}: {e}"}
        debates = _debates(db_root, candidate_id)
        return json.dumps({
            "version": VERSION, "candidate_id": candidate_id,
            "candidate": {"lat": cand.get("lat"), "lon": cand.get("lon"), "score": cand.get("score"),
                          "band": cand.get("confidence_band"), "numeric": cand.get("confidence_numeric"),
                          "status": review.get("status_label") or cand.get("status"),
                          "review_source": review.get("review_source"),
                          "review_reason": review.get("last_review_reason"),
                          "job_id": review.get("job_id"), "job_trust": review.get("job_trust"),
                          "job_target": review.get("job_target_label")},
            "history": _history(db_root, candidate_id),
            "debates": debates,
            "debate_note": None if debates else NOT_STORED,
            "statement": STATEMENT,
        }, default=str)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
