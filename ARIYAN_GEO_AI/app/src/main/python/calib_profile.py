"""
calib_profile.py

Part of ARIYAN GEO AI -- Phase 5b (calib-v1 adoption) and 5c (human-outcome
counter). Added 2026-10-02 after the frozen bench (calib_bench.py, md5
851df73216d2b1bebd34f93a2b9419ca) recorded PASS (INDICATIVE) and the user
approved adoption.

WHAT A PROFILE DOES -- AND DOES NOT DO
An active profile adds ONE label to candidates whose stored DEM z-score
meets the benched threshold ("calib-v1: strong (|z| >= 6)"), and lets the
Candidates tab sort those first. That is all. It never changes a
candidate's status, confidence, band or the MODERATE ceiling; never
auto-rejects; never overrides or reorders the user's reviews; and says
nothing about whether any candidate is a site.

STORAGE: the existing, previously unused `calibration_version` table
(grand_project_db.py, reserved for Phase 5). Append-only: adopting writes
one row, revoking writes another. The newest row decides what is active.
Each change is also written to the timeline.

ADOPTION GATE: calib-v1 can only be adopted if the timeline holds a
CALIBRATION_BENCH event written by the frozen bench script (md5 above)
that reads PASS and chose |z| >= 6. The event's id and full text are
stored inside the profile, so the profile always points back at the bench
run it came from.

SCOPE (shown on the profile screen): the threshold was chosen and tested on
DEM-only, offline-first Copernicus GLO-30 runs in Khuzestan and Kangavar.
Candidates scored on another DEM or in other terrain get the same label by
the same rule, but the bench did not test them.

5c HUMAN-OUTCOME COUNTER: counts the candidates whose status the USER
currently owns as Supported or Rejected (automatic reviews excluded), split
by calib-v1 label. It feeds nothing now; calib-v2 may only be considered
after at least 20 Supported and 20 Rejected.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

import grand_project_db as db
import grand_project_review as review

PROFILE_NAME = "calib-v1"
FROZEN_BENCH_MD5 = "851df73216d2b1bebd34f93a2b9419ca"
FROZEN_THRESHOLD = 6.0
BENCH_JOBS = {"derivation": ["32c858", "32d423"], "holdout": "f43d36"}
OUTCOME_MIN_EACH = 20
LABEL_TEXT = "calib-v1: strong (|z| >= 6)"
SCOPE_NOTE = ("Benched on DEM-only, offline-first Copernicus GLO-30 runs in Khuzestan (Susiana) "
              "and Kangavar. Other DEMs and terrain get the same label by the same rule, untested.")


class ProfileError(Exception):
    pass


def _clean(text: Any) -> str:
    t = " ".join(str(text or "").split())
    if len(t) < 3:
        raise ProfileError("Please write a short reason (at least 3 characters).")
    return t[:500]


def _rows(conn):
    return [dict(r) for r in conn.execute(
        "SELECT id, created_at, description, changed_parameters_json, approved_by_user "
        "FROM calibration_version ORDER BY id").fetchall()]


def _active_from_rows(rows) -> Optional[Dict[str, Any]]:
    if not rows:
        return None
    last = rows[-1]
    try:
        params = json.loads(last["changed_parameters_json"] or "{}")
    except ValueError:
        return None
    if params.get("action") != "adopt" or not last["approved_by_user"]:
        return None
    return dict(params, version_row_id=last["id"], adopted_at=last["created_at"])


def active_profile(db_root: str) -> Optional[Dict[str, Any]]:
    conn = review._connect(db_root)
    try:
        return _active_from_rows(_rows(conn))
    finally:
        conn.close()


def is_strong(score: Any, profile: Optional[Dict[str, Any]]) -> bool:
    if profile is None or score is None:
        return False
    try:
        return abs(float(score)) >= float(profile["threshold_abs_z"])
    except (TypeError, ValueError):
        return False


def _find_bench_event(conn) -> Optional[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, grand_project_id, occurred_at, description FROM timeline_event "
        "WHERE event_type = 'CALIBRATION_BENCH' ORDER BY id DESC").fetchall()
    for r in rows:
        d = r["description"] or ""
        if ("md5 " + FROZEN_BENCH_MD5) in d:
            return dict(r)
    return None


def adopt_calib_v1(db_root: str, grand_project_id: str, approval_note: str) -> Dict[str, Any]:
    note = _clean(approval_note)
    conn = review._connect(db_root)
    try:
        rows = _rows(conn)
        current = _active_from_rows(rows)
        if current is not None:
            raise ProfileError("%s is already active (adopted %s)." % (current["profile"], current["adopted_at"][:19]))
        ev = _find_bench_event(conn)
        if ev is None:
            raise ProfileError("No bench result from the frozen script (md5 %s) is on the timeline; "
                               "calib-v1 cannot be adopted." % FROZEN_BENCH_MD5)
        desc = ev["description"]
        m = re.search(r"chosen \|z\|>=([0-9.]+)", desc)
        if m is None or abs(float(m.group(1)) - FROZEN_THRESHOLD) > 1e-9:
            raise ProfileError("The bench event does not record |z| >= 6; refusing to adopt.")
        if "; PASS" not in desc:
            raise ProfileError("The bench event is not a PASS; nothing can be adopted.")
        try:
            import provenance_ledger
            bundle_md5 = provenance_ledger.code_bundle()[0]
        except Exception:
            bundle_md5 = None
        params = {
            "action": "adopt",
            "profile": PROFILE_NAME,
            "threshold_abs_z": FROZEN_THRESHOLD,
            "effect": "label and sort only",
            "bench_script_md5": FROZEN_BENCH_MD5,
            "bench_event_id": ev["id"],
            "bench_event_at": ev["occurred_at"],
            "bench_event_text": desc,
            "bench_jobs": BENCH_JOBS,
            "code_bundle_md5": bundle_md5,
            "approval_note": note,
            "scope": SCOPE_NOTE,
        }
        with conn:
            cur = conn.execute(
                "INSERT INTO calibration_version (created_at, description, changed_parameters_json, approved_by_user) "
                "VALUES (?, ?, ?, 1)",
                (db._now_iso(), "%s adopted (label + sort only)" % PROFILE_NAME, json.dumps(params)))
            row_id = cur.lastrowid
    finally:
        conn.close()
    db.log_timeline_event(db_root, grand_project_id, "CALIBRATION_ADOPTED",
                          related_entity_type="calibration_version", related_entity_id=str(row_id),
                          description="%s adopted by user: label + sort only, |z| >= 6, from bench event #%s. Note: %s"
                          % (PROFILE_NAME, params["bench_event_id"], note))
    return {"adopted": True, "version_row_id": row_id, "profile": PROFILE_NAME}


def revoke(db_root: str, grand_project_id: str, reason: str) -> Dict[str, Any]:
    why = _clean(reason)
    conn = review._connect(db_root)
    try:
        current = _active_from_rows(_rows(conn))
        if current is None:
            raise ProfileError("No calibration profile is active.")
        params = {"action": "revoke", "profile": current["profile"],
                  "revokes_row_id": current["version_row_id"], "reason": why}
        with conn:
            cur = conn.execute(
                "INSERT INTO calibration_version (created_at, description, changed_parameters_json, approved_by_user) "
                "VALUES (?, ?, ?, 1)",
                (db._now_iso(), "%s revoked" % current["profile"], json.dumps(params)))
            row_id = cur.lastrowid
    finally:
        conn.close()
    db.log_timeline_event(db_root, grand_project_id, "CALIBRATION_REVOKED",
                          related_entity_type="calibration_version", related_entity_id=str(row_id),
                          description="%s revoked by user. Reason: %s" % (current["profile"], why))
    return {"revoked": True, "version_row_id": row_id}


def profile_report(db_root: str, grand_project_id: str) -> Dict[str, Any]:
    conn = review._connect(db_root)
    try:
        rows = _rows(conn)
        prof = _active_from_rows(rows)
        bench_ev = _find_bench_event(conn)
        cands = [dict(r) for r in conn.execute(
            "SELECT id, score, status FROM candidate WHERE grand_project_id = ?", (grand_project_id,)).fetchall()]
        user_owned = review._user_owned_ids(conn)
        kinds = {r["kind"]: r["n"] for r in conn.execute(
            "SELECT kind, COUNT(*) AS n FROM geographic_suggestion WHERE grand_project_id = ? GROUP BY kind",
            (grand_project_id,)).fetchall()}
    finally:
        conn.close()

    probe = prof or {"threshold_abs_z": FROZEN_THRESHOLD}
    strong = sum(1 for c in cands if is_strong(c["score"], probe))
    outcome = {"SUPPORTED": {"strong": 0, "other": 0}, "REJECTED": {"strong": 0, "other": 0}}
    for c in cands:
        if c["id"] in user_owned and c["status"] in outcome:
            outcome[c["status"]]["strong" if is_strong(c["score"], probe) else "other"] += 1
    sup = sum(outcome["SUPPORTED"].values())
    rej = sum(outcome["REJECTED"].values())
    ready = sup >= OUTCOME_MIN_EACH and rej >= OUTCOME_MIN_EACH

    L = []
    if prof:
        L += ["ACTIVE: %s  (adopted %s)" % (prof["profile"], prof["adopted_at"][:19].replace("T", " ")),
              "Rule: label candidates with |DEM z-score| >= %g" % prof["threshold_abs_z"],
              "Effect: label and sort only. Never changes status, confidence or the MODERATE ceiling;",
              "never auto-rejects; never overrides your reviews.",
              "Bench: event #%s, script md5 %s" % (prof["bench_event_id"], prof["bench_script_md5"]),
              "  " + prof["bench_event_text"],
              "Bench jobs: derivation %s, hold-out %s" % (" + ".join(prof["bench_jobs"]["derivation"]),
                                                          prof["bench_jobs"]["holdout"]),
              "Code bundle at adoption: %s" % (prof.get("code_bundle_md5") or "n/a"),
              "Your approval: " + prof["approval_note"]]
    else:
        L += ["No calibration profile is active.",
              ("Bench result available: event #%s\n  %s" % (bench_ev["id"], bench_ev["description"]))
              if bench_ev else "No frozen-bench result on the timeline; calib-v1 cannot be adopted."]
    L += ["", "Scope: " + SCOPE_NOTE, "",
          "This project: %d candidates, %d meet |z| >= %g%s"
          % (len(cands), strong, probe["threshold_abs_z"], "" if prof else " (would be labelled)"),
          "",
          "Your outcomes (your own reviews only, automatic reviews excluded):",
          "  Supported %d  (strong %d / other %d)" % (sup, outcome["SUPPORTED"]["strong"], outcome["SUPPORTED"]["other"]),
          "  Rejected  %d  (strong %d / other %d)" % (rej, outcome["REJECTED"]["strong"], outcome["REJECTED"]["other"]),
          "  calib-v2 can be considered after %d Supported and %d Rejected: %s"
          % (OUTCOME_MIN_EACH, OUTCOME_MIN_EACH, "reached" if ready else "not yet"),
          "",
          "Geographic suggestions in this project (context only, no pre-filter):",
          "  PAIRED %d / DISTANCE_ONLY %d / UNGROUNDED %d"
          % (kinds.get("PAIRED_SUGGESTION", 0), kinds.get("DISTANCE_ONLY", 0), kinds.get("UNGROUNDED_PLACE", 0))]
    return {"active": prof is not None, "can_adopt": prof is None and bench_ev is not None,
            "profile": prof, "strong_in_project": strong, "outcomes": outcome,
            "outcomes_ready_for_v2": ready, "suggestion_kinds": kinds, "report_text": "\n".join(L)}


def _json(fn, *args) -> str:
    try:
        return json.dumps(fn(*args))
    except (ProfileError, review.ReviewError) as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": "calibration profile failed: %s" % e})


def profile_report_json(db_root: str, grand_project_id: str) -> str:
    return _json(profile_report, db_root, grand_project_id)


def adopt_calib_v1_json(db_root: str, grand_project_id: str, approval_note: str) -> str:
    return _json(adopt_calib_v1, db_root, grand_project_id, approval_note)


def revoke_json(db_root: str, grand_project_id: str, reason: str) -> str:
    return _json(revoke, db_root, grand_project_id, reason)
