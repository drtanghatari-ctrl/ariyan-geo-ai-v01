"""Read-only view of the code bundles recorded by the provenance ledger.

cbv-v1 (ADDED 2026-10-06). Every provenance record carries a
code_bundle_md5: an MD5 over every app Python module that was loaded when
the evidence row was written. The per-file list is stored once in
provenance_code_bundle (see provenance_ledger.py). Until now the app only
showed the bundle MD5. This module lets the user see:

  * job_bundles():   which bundle(s) a job's evidence rows were made with,
                     how many rows each, and when;
  * bundle_files():  the file list of one bundle (module, file, MD5 at the
                     time) and, for each file, whether the code in THIS
                     installed app is the same, has changed since, or is
                     no longer present.

It changes nothing: no writes, no network. Comparing "now" re-reads the
installed module source through the import system (the same way the
ledger read it), so it works inside the packaged Android app too.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from typing import Any, Dict, List, Optional

import grand_project_review as review
import provenance_check as pc
import provenance_ledger as pl

VIEW_VERSION = "cbv-v1"
MIN_BUNDLE_PREFIX = 6


class CodeBundleViewError(Exception):
    pass


# ============================ CURRENT CODE ============================

def _current_md5(module: str, file_name: str) -> Optional[str]:
    """MD5 of the module's source as installed now, read the same way the
    ledger read it (loader.get_data on the module's file). None when the
    module cannot be found in this app any more. Never raises."""
    try:
        mod = sys.modules.get(module)
        if mod is not None and getattr(mod, "__file__", None):
            data = pl._module_bytes(mod)
            if data is not None:
                return hashlib.md5(data).hexdigest()
        spec = importlib.util.find_spec(module)
        if spec is None or not spec.origin:
            return None
        if os.path.basename(spec.origin) != file_name:
            return None
        loader = spec.loader
        if loader is not None and hasattr(loader, "get_data"):
            try:
                return hashlib.md5(loader.get_data(spec.origin)).hexdigest()
            except Exception:
                pass
        with open(spec.origin, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return None


def _status(recorded: Optional[str], now: Optional[str]) -> str:
    if not recorded:
        return "not recorded"
    if now is None:
        return "not in app now"
    return "same as now" if now == recorded else "CHANGED since"


# ============================ ONE BUNDLE ============================

def _resolve_bundle(conn, ref: Any) -> str:
    text = str(ref or "").strip().lower()
    if len(text) < MIN_BUNDLE_PREFIX:
        raise CodeBundleViewError(
            "Bundle id %r is too short (use at least %d characters)." % (text, MIN_BUNDLE_PREFIX))
    rows = conn.execute("SELECT bundle_md5 FROM provenance_code_bundle WHERE bundle_md5 LIKE ? LIMIT 3",
                        (text + "%",)).fetchall()
    if not rows:
        raise CodeBundleViewError("No recorded code bundle starts with %r." % text)
    if len(rows) > 1:
        exact = [r["bundle_md5"] for r in rows if r["bundle_md5"] == text]
        if exact:
            return exact[0]
        raise CodeBundleViewError("%r matches more than one bundle; use more characters." % text)
    return rows[0]["bundle_md5"]


def bundle_files(db_root: str, bundle_ref: str) -> Dict[str, Any]:
    conn = review._connect(db_root)
    try:
        pl.ensure_schema(conn)
        md5 = _resolve_bundle(conn, bundle_ref)
        row = dict(conn.execute("SELECT * FROM provenance_code_bundle WHERE bundle_md5 = ?",
                                (md5,)).fetchone())
        used = conn.execute("SELECT COUNT(*) AS n FROM provenance_record WHERE code_bundle_md5 = ?",
                            (md5,)).fetchone()["n"]
    finally:
        conn.close()
    try:
        recorded = json.loads(row["files_json"] or "[]")
    except ValueError:
        recorded = []
    files: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    for f in recorded:
        now = _current_md5(str(f.get("module") or ""), str(f.get("file") or ""))
        st = _status(f.get("md5"), now)
        counts[st] = counts.get(st, 0) + 1
        files.append({"module": f.get("module"), "file": f.get("file"),
                      "md5": f.get("md5"), "md5_now": now, "status": st})
    result = {"view_version": VIEW_VERSION, "bundle_md5": md5,
              "recorded_at": row.get("recorded_at"), "all_py": bool(row.get("all_py")),
              "rows_using": int(used), "files": files, "counts": counts}
    result["report_text"] = _bundle_report(result)
    return result


def _bundle_report(r: Dict[str, Any]) -> str:
    L = ["Code bundle %s" % r["bundle_md5"],
         "First recorded: %s" % (r.get("recorded_at") or "?"),
         "Evidence rows made with it: %d" % r["rows_using"],
         "Files: %d%s" % (len(r["files"]), "" if r["all_py"] else
                          "  (some not plain .py, so their MD5s are weaker evidence)"),
         ""]
    c = r["counts"]
    L.append("Compared with the code in this app now:")
    for k in ("same as now", "CHANGED since", "not in app now", "not recorded"):
        if c.get(k):
            L.append("  %-16s %d" % (k, c[k]))
    L.append("")
    # Changed / missing first, so problems are not buried in a long list.
    order = {"CHANGED since": 0, "not in app now": 1, "not recorded": 2, "same as now": 3}
    for f in sorted(r["files"], key=lambda f: (order.get(f["status"], 9), f["file"] or "")):
        L.append("%s  %s" % (f["file"], f["status"]))
        L.append("   then %s" % ((f["md5"] or "?")[:12]))
        if f["status"] == "CHANGED since":
            L.append("   now  %s" % ((f["md5_now"] or "?")[:12]))
    L.append("")
    L.append("\"CHANGED since\" does not mean a result is wrong: it means re-running "
             "today would use different code than the one that made the result. "
             "Read-only; changes nothing.")
    return "\n".join(L)


def bundle_files_json(db_root: str, bundle_ref: str) -> str:
    try:
        return json.dumps(bundle_files(db_root, bundle_ref))
    except (CodeBundleViewError, review.ReviewError) as e:
        return json.dumps({"error": str(e)})


# ============================ ONE JOB ============================

def job_bundles(db_root: str, job_ref: str) -> Dict[str, Any]:
    conn = review._connect(db_root)
    try:
        pl.ensure_schema(conn)
        job_id = pc._resolve_job(conn, job_ref)
        title = conn.execute("SELECT title FROM wide_area_search_job WHERE id = ?",
                             (job_id,)).fetchone()["title"]
        inv_ids = [r["investigation_id"] for r in conn.execute(
            "SELECT investigation_id FROM wide_area_search_tile WHERE job_id = ? "
            "AND investigation_id IS NOT NULL", (job_id,)).fetchall()]
        cands: List[str] = []
        for i in range(0, len(inv_ids), 500):
            chunk = inv_ids[i:i + 500]
            cands += [r["id"] for r in conn.execute(
                "SELECT id FROM candidate WHERE investigation_id IN (%s)" % ",".join("?" * len(chunk)),
                chunk).fetchall()]
        agg: Dict[Optional[str], Dict[str, Any]] = {}
        for i in range(0, len(cands), 500):
            chunk = cands[i:i + 500]
            for r in conn.execute(
                    "SELECT code_bundle_md5 AS b, COUNT(*) AS n, MIN(recorded_at) AS first, "
                    "MAX(recorded_at) AS last FROM provenance_record WHERE candidate_id IN (%s) "
                    "GROUP BY code_bundle_md5" % ",".join("?" * len(chunk)), chunk).fetchall():
                a = agg.setdefault(r["b"], {"bundle_md5": r["b"], "rows": 0,
                                            "first": r["first"], "last": r["last"]})
                a["rows"] += r["n"]
                a["first"] = min(a["first"], r["first"])
                a["last"] = max(a["last"], r["last"])
    finally:
        conn.close()
    bundles = sorted(agg.values(), key=lambda a: a["last"] or "", reverse=True)
    for a in bundles:
        if a["bundle_md5"]:
            try:
                d = bundle_files(db_root, a["bundle_md5"])
                a["files"] = len(d["files"])
                a["counts"] = d["counts"]
            except Exception:
                a["files"], a["counts"] = None, {}
        else:
            a["files"], a["counts"] = None, {}
    return {"view_version": VIEW_VERSION, "job_id": job_id, "title": title,
            "candidates": len(cands), "bundles": bundles}


def job_bundles_json(db_root: str, job_ref: str) -> str:
    try:
        return json.dumps(job_bundles(db_root, job_ref))
    except (CodeBundleViewError, pc.ProvenanceCheckError, review.ReviewError) as e:
        return json.dumps({"error": str(e)})
