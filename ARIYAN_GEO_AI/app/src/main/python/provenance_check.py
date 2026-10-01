"""
provenance_check.py  --  Phase 4b (checker "pc-v1")

Turns the Phase 4a ledger (provenance_ledger.py) into a plain verdict:
Verified / Not verified, always with the reasons. READ-ONLY: it changes no
evidence, review, label, status or confidence.

AN EVIDENCE ROW IS VERIFIED ONLY IF ALL OF THESE HOLD
  1. it has a ledger record                (else "lineage not recorded")
  2. the evidence row still hashes to the value in its record
  3. its record is intact in the chain     (its own hash recomputes, and no
     earlier record is broken, missing or re-ordered)
  4. its sources were observed (CAPTURED) or supplied by the writer
     (EXPLICIT), and at least one source stands behind it
  5. every offline file it used is still on this phone and still has the
     SHA-256 recorded at the time (re-hashed now, no cache)
  6. the code that wrote it was recorded as shipped .py files
  7. its job is not marked CORRUPTED
LIVE responses cannot be fetched again to compare; they count as recorded
at fetch time, and the report says so.

A CANDIDATE IS VERIFIED only if it has at least one evidence row and every
one of its evidence rows is verified. A JOB is reported as counts.

WHAT THIS DOES NOT DO: lift the Steward's MODERATE ceiling. The Steward's
ceiling is held by uncontrolled environmental confounders, not by
provenance (see steward_confidence_ceiling.py). The Steward also runs
BEFORE the evidence rows exist, so it cannot see this verdict; its
"Evidence lineage cannot currently be verified" warning is superseded by
this check for rows that pass it.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import grand_project_db as db
import grand_project_review as review
import provenance_ledger as pl

CHECKER_VERSION = "pc-v1"


class ProvenanceCheckError(Exception):
    pass


# =========================== shared state per check ===========================

class _Context:
    def __init__(self, conn):
        self.conn = conn
        self.file_hash_now: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
        self.bundle_all_py: Dict[str, Optional[bool]] = {}
        self.trust = review._current_job_trust(conn)
        self.chain_ok_ids, self.chain_problem = self._walk_chain()

    def _walk_chain(self) -> Tuple[set, Optional[str]]:
        """Walk the whole chain once. Returns (ids of records that are intact
        AND come before any break, description of the first break or None)."""
        ok = set()
        prev = pl.GENESIS_HASH
        try:
            rows = self.conn.execute("SELECT * FROM provenance_record ORDER BY id").fetchall()
        except Exception:
            return ok, None  # no ledger table yet
        for r in rows:
            d = dict(r)
            if d["prev_hash"] != prev:
                return ok, ("chain broken at ledger record %d (a record before it was "
                            "changed, removed or re-ordered)" % d["id"])
            if pl.record_hash_of(d) != d["record_hash"]:
                return ok, "ledger record %d was changed after it was written" % d["id"]
            ok.add(d["id"])
            prev = d["record_hash"]
        return ok, None

    def file_now(self, path: str) -> Tuple[Optional[str], Optional[str]]:
        """(sha256 now, problem) -- re-hashed from disk, never from cache."""
        if path not in self.file_hash_now:
            try:
                h = hashlib.sha256()
                with open(path, "rb") as f:
                    for block in iter(lambda: f.read(1 << 20), b""):
                        h.update(block)
                self.file_hash_now[path] = (h.hexdigest(), None)
            except FileNotFoundError:
                self.file_hash_now[path] = (None, "no longer on this phone")
            except OSError as exc:
                self.file_hash_now[path] = (None, "unreadable (%s)" % type(exc).__name__)
        return self.file_hash_now[path]

    def all_py(self, bundle_md5: Optional[str]) -> Optional[bool]:
        if not bundle_md5:
            return None
        if bundle_md5 not in self.bundle_all_py:
            row = self.conn.execute("SELECT all_py FROM provenance_code_bundle WHERE bundle_md5 = ?",
                                    (bundle_md5,)).fetchone()
            self.bundle_all_py[bundle_md5] = None if row is None else bool(row["all_py"])
        return self.bundle_all_py[bundle_md5]


def _job_of_investigation(conn, investigation_id: str) -> Optional[str]:
    row = conn.execute("SELECT job_id FROM wide_area_search_tile WHERE investigation_id = ? LIMIT 1",
                       (investigation_id,)).fetchone()
    return row["job_id"] if row else None


# =========================== one evidence row ===========================

def _check_row(ctx: _Context, ev: Dict[str, Any], rec: Optional[Dict[str, Any]],
               job_id: Optional[str]) -> Dict[str, Any]:
    reasons: List[str] = []
    notes: List[str] = []
    out = {"evidence_link_id": ev["id"], "evidence_type": ev["evidence_type"],
           "relation": ev["relation"], "recorded_at": ev["recorded_at"]}

    if job_id and ctx.trust.get(job_id, {}).get("trust") == "CORRUPTED":
        reasons.append("job %s is marked CORRUPTED" % job_id[:6])

    if rec is None:
        issue = ctx.conn.execute(
            "SELECT message FROM provenance_issue WHERE evidence_link_id = ? ORDER BY id DESC LIMIT 1",
            (ev["id"],)).fetchone() if _has_table(ctx.conn, "provenance_issue") else None
        reasons.append("ledger write failed: %s" % issue["message"] if issue
                       else "lineage not recorded (written before the ledger existed)")
        out.update(verified=False, reasons=reasons, notes=notes, sources=[])
        return out

    if pl.evidence_sha256_of(ev["candidate_id"], ev["evidence_type"], ev["relation"],
                             ev["detail_json"], ev["recorded_at"]) != rec["evidence_sha256"]:
        reasons.append("evidence row was changed after it was recorded")
    if rec["id"] not in ctx.chain_ok_ids:
        reasons.append(ctx.chain_problem or "ledger record failed the chain check")

    state = rec["capture_state"]
    if state == pl.NOT_CAPTURED:
        reasons.append("sources not observed: %s" % (rec["capture_note"] or "no reason recorded"))

    try:
        sources = json.loads(rec["sources_json"] or "[]")
    except ValueError:
        sources = []
        reasons.append("source list unreadable")
    if state in (pl.CAPTURED, pl.EXPLICIT) and not sources:
        reasons.append(rec["capture_note"] or "no source stands behind this row")

    shown = []
    for s in sources:
        t = s.get("type")
        if t == "FILE":
            name = s.get("name") or os.path.basename(s.get("path") or "?")
            if not s.get("sha256"):
                reasons.append("file %s could not be hashed when recorded" % name)
                shown.append({"type": "FILE", "name": name, "status": "not hashed"})
                continue
            now, problem = ctx.file_now(s.get("path") or "")
            if problem:
                reasons.append("file %s %s; cannot re-check it" % (name, problem))
                status = problem
            elif now != s["sha256"]:
                reasons.append("file %s has changed since it was used" % name)
                status = "CHANGED"
            else:
                status = "matches"
            shown.append({"type": "FILE", "kind": s.get("kind"), "name": name,
                          "sha256": s["sha256"][:16], "status": status})
        elif t == "LIVE":
            shown.append({"type": "LIVE", "kind": s.get("kind"), "service": s.get("service"),
                          "sha256": (s.get("response_sha256") or "")[:16],
                          "status": "recorded at fetch time"})
        elif t == "USER_RECORD":
            shown.append({"type": "USER_RECORD", "kind": s.get("kind"),
                          "sha256": (s.get("sha256") or "")[:16], "status": "user record"})
    if any(x["type"] == "LIVE" for x in shown):
        notes.append("live responses cannot be fetched again to compare")

    ap = ctx.all_py(rec["code_bundle_md5"])
    if ap is None:
        reasons.append("code version not recorded")
    elif not ap:
        reasons.append("code was recorded as compiled files, so its version cannot be matched to GitHub")

    out.update(verified=not reasons, reasons=reasons, notes=notes, sources=shown,
               capture_state=state, code_bundle_md5=rec["code_bundle_md5"],
               ledger_record_id=rec["id"], method_version=rec["method_version"])
    return out


def _has_table(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _records_for(conn, evidence_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    if not evidence_ids or not _has_table(conn, "provenance_record"):
        return out
    for i in range(0, len(evidence_ids), 500):
        chunk = evidence_ids[i:i + 500]
        for r in conn.execute("SELECT * FROM provenance_record WHERE evidence_link_id IN (%s)"
                              % ",".join("?" * len(chunk)), chunk).fetchall():
            out[r["evidence_link_id"]] = dict(r)
    return out


def _candidate_verdict(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"verified": False, "summary": "Not verified: no evidence rows"}
    bad = [r for r in rows if not r["verified"]]
    if not bad:
        return {"verified": True, "summary": "Verified (%d of %d evidence rows)" % (len(rows), len(rows))}
    reasons: Dict[str, int] = {}
    for r in bad:
        for x in r["reasons"]:
            reasons[x] = reasons.get(x, 0) + 1
    return {"verified": False,
            "summary": "Not verified (%d of %d evidence rows fail)" % (len(bad), len(rows)),
            "reasons": reasons}


# =========================== public: one candidate ===========================

def check_candidate(db_root: str, candidate_id: str) -> Dict[str, Any]:
    conn = review._connect(db_root)
    try:
        pl.ensure_schema(conn)
        cand = conn.execute("SELECT id, investigation_id FROM candidate WHERE id = ?",
                            (candidate_id,)).fetchone()
        if cand is None:
            raise ProvenanceCheckError("No candidate %r." % candidate_id)
        ctx = _Context(conn)
        job_id = _job_of_investigation(conn, cand["investigation_id"])
        evs = [dict(r) for r in conn.execute(
            "SELECT * FROM evidence_link WHERE candidate_id = ? ORDER BY id", (candidate_id,)).fetchall()]
        recs = _records_for(conn, [e["id"] for e in evs])
        rows = [_check_row(ctx, e, recs.get(e["id"]), job_id) for e in evs]
        v = _candidate_verdict(rows)
        return {"checker_version": CHECKER_VERSION, "candidate_id": candidate_id,
                "job_id": job_id, "verified": v["verified"], "summary": v["summary"],
                "reasons": v.get("reasons", {}), "rows": rows,
                "chain_problem": ctx.chain_problem}
    finally:
        conn.close()


def check_candidate_json(db_root: str, candidate_id: str) -> str:
    try:
        return json.dumps(check_candidate(db_root, candidate_id))
    except ProvenanceCheckError as e:
        return json.dumps({"error": str(e)})


# =========================== public: one job ===========================

def _resolve_job(conn, job_ref: str) -> str:
    try:
        return review._resolve_id(conn, "wide_area_search_job", job_ref)
    except review.ReviewError as first:
        text = str(job_ref or "").strip()
        rows = conn.execute("SELECT id FROM wide_area_search_job WHERE lower(title) = lower(?)",
                            (text,)).fetchall()
        if len(rows) == 1:
            return rows[0]["id"]
        if len(rows) > 1:
            raise ProvenanceCheckError("Several jobs are titled %r; use the job id." % text)
        raise ProvenanceCheckError(str(first))


def check_job(db_root: str, job_ref: str) -> Dict[str, Any]:
    conn = review._connect(db_root)
    try:
        pl.ensure_schema(conn)
        job_id = _resolve_job(conn, job_ref)
        job = dict(conn.execute("SELECT * FROM wide_area_search_job WHERE id = ?", (job_id,)).fetchone())
        inv_ids = [r["investigation_id"] for r in conn.execute(
            "SELECT investigation_id FROM wide_area_search_tile WHERE job_id = ? AND investigation_id IS NOT NULL",
            (job_id,)).fetchall()]
        cands: List[str] = []
        for i in range(0, len(inv_ids), 500):
            chunk = inv_ids[i:i + 500]
            cands += [r["id"] for r in conn.execute(
                "SELECT id FROM candidate WHERE investigation_id IN (%s)" % ",".join("?" * len(chunk)),
                chunk).fetchall()]
        ctx = _Context(conn)
        evs_by_cand: Dict[str, List[Dict[str, Any]]] = {c: [] for c in cands}
        for i in range(0, len(cands), 500):
            chunk = cands[i:i + 500]
            for r in conn.execute("SELECT * FROM evidence_link WHERE candidate_id IN (%s) ORDER BY id"
                                  % ",".join("?" * len(chunk)), chunk).fetchall():
                evs_by_cand[r["candidate_id"]].append(dict(r))
        all_ids = [e["id"] for es in evs_by_cand.values() for e in es]
        recs = _records_for(conn, all_ids)

        n_rows = n_rows_ok = 0
        n_cand_ok = 0
        reason_counts: Dict[str, int] = {}
        by_type: Dict[str, List[int]] = {}
        files: Dict[str, str] = {}
        for cid in cands:
            rows = [_check_row(ctx, e, recs.get(e["id"]), job_id) for e in evs_by_cand[cid]]
            if _candidate_verdict(rows)["verified"]:
                n_cand_ok += 1
            for r in rows:
                n_rows += 1
                t = by_type.setdefault(r["evidence_type"], [0, 0])
                t[0] += 1
                if r["verified"]:
                    n_rows_ok += 1
                    t[1] += 1
                for x in r["reasons"]:
                    reason_counts[x] = reason_counts.get(x, 0) + 1
                for s in r["sources"]:
                    if s["type"] == "FILE":
                        files[s["name"]] = "%s  %s" % (s.get("sha256", ""), s["status"])
        result = {"checker_version": CHECKER_VERSION, "job_id": job_id, "title": job.get("title"),
                  "candidates": len(cands), "candidates_verified": n_cand_ok,
                  "evidence_rows": n_rows, "evidence_rows_verified": n_rows_ok,
                  "by_type": by_type, "reasons": reason_counts, "files": files,
                  "chain_problem": ctx.chain_problem,
                  "job_trust": ctx.trust.get(job_id, {}).get("trust")}
        result["report_text"] = _job_report(result)
        return result
    finally:
        conn.close()


def _job_report(r: Dict[str, Any]) -> str:
    L = []
    L.append("Job %s  %s" % (r["job_id"][:6], r.get("title") or ""))
    L.append("Checker %s (read-only; changes nothing)" % r["checker_version"])
    L.append("")
    if r["candidates"] == 0:
        L.append("This job has no candidates.")
    else:
        verdict = "VERIFIED" if r["candidates_verified"] == r["candidates"] else "NOT VERIFIED"
        L.append("Verdict: %s" % verdict)
        L.append("Candidates verified: %d of %d" % (r["candidates_verified"], r["candidates"]))
        L.append("Evidence rows verified: %d of %d" % (r["evidence_rows_verified"], r["evidence_rows"]))
        for t, (n, ok) in sorted(r["by_type"].items()):
            L.append("  %-16s %d of %d" % (t, ok, n))
    if r.get("job_trust"):
        L.append("Job trust mark: %s" % r["job_trust"])
    if r.get("chain_problem"):
        L.append("")
        L.append("LEDGER CHAIN: %s" % r["chain_problem"])
    if r["reasons"]:
        L.append("")
        L.append("Why rows are not verified (rows affected):")
        for k, v in sorted(r["reasons"].items(), key=lambda kv: -kv[1]):
            L.append("  %d  %s" % (v, k))
    if r["files"]:
        L.append("")
        L.append("Offline files behind this job (SHA-256, first 16):")
        for name, line in sorted(r["files"].items()):
            L.append("  %s  %s" % (name, line))
    L.append("")
    L.append("Verified means the data and code behind each row can be traced and are unchanged. "
             "It does not raise the Steward's confidence ceiling (held at MODERATE by "
             "uncontrolled confounders), and it says nothing about whether a candidate is a site.")
    return "\n".join(L)


def check_job_json(db_root: str, job_ref: str) -> str:
    try:
        return json.dumps(check_job(db_root, job_ref))
    except (ProvenanceCheckError, review.ReviewError) as e:
        return json.dumps({"error": str(e)})
