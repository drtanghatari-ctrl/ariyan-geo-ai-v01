"""
calib_bench.py

Part of ARIYAN GEO AI -- Phase 5a, the calib-v1 bench (pre-registered and
user-approved 2026-10-02, BEFORE this script was run on any bench job).

WHAT IT ASKS
Does keeping only the stronger DEM candidates (|peak_zscore| >= t) put
ARIYAN's candidates closer to recorded mound/tell sites than chance would,
and closer than keeping every candidate? A threshold is chosen on two
derivation jobs and judged ONCE on a hold-out job never used for any choice.

FROZEN RULES (do not edit after the first run; any change is calib-v2)
1. Bench jobs, fixed by id (Option B: DEM-only, offline-first COP30 re-runs,
   every evidence row provenance-VERIFIED):
     derivation  32c858  calib Susiana v1   (32.12-32.28 N, 48.38-48.60 E)
     derivation  32d423  calib Kangavar v3  (34.430-34.555 N, 47.990-48.090 E)
     hold-out    f43d36  Susiana West box   (32.03-32.30 N, 48.205-48.38 E)
   f43d36's title reads "calib Kangavar v2" by a data-entry slip; its box is
   the Susiana West hold-out (confirmed on device). Recorded, not hidden.
   Not used: d96948 (seam-bug run), 22550e (duplicate hold-out, never run).
2. Score: |candidate.score| (the stored DEM peak_zscore). One feature only.
   Residual, area and polarity are REPORTED for context, never used to choose.
3. Thresholds tried: |z| >= 3, 4, 5, 6, 8. All candidates, any review status.
4. Statistic: grand_project_calibration's F2 distance test, run on the subset:
   per site p = share of the job's scanned sample grid whose nearest SUBSET
   candidate is at most as close as the site's; combined over sites with
   Fisher's method. Subset density is in the baseline, so thinning is not
   rewarded by itself.
5. Choice: pool the per-site p values of both derivation jobs (each against
   its own job's baseline) into one Fisher statistic per threshold; pick the
   largest statistic (= smallest combined p). Exact tie -> the lower t.
6. PASS only if, on the hold-out: the chosen t gives combined p < 0.05 AND
   its Fisher statistic is larger than with all candidates (no threshold).
   Hold-out sites < 20 -> a pass is labelled INDICATIVE.
7. FAIL -> nothing is adopted; the result is recorded with all its numbers.
8. Refuses to run unless all three jobs are COMPLETE, not CORRUPTED, and
   provenance-VERIFIED for every candidate.

READ-ONLY apart from one timeline_event (CALIBRATION_BENCH) holding the
verdict, the numbers and this file's MD5. Changes no candidate, status,
confidence, ceiling or review. Adopting calib-v1 is a separate, later,
user-approved step (5b); this script does not do it.

SPEED: same samples and distances as F2, but nearest-candidate distances
are computed with numpy in blocks (exact, same 5000 m search limit) so 16
subset runs finish on a phone.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from typing import Any, Dict, List, Tuple

import numpy as np

import grand_project_calibration as f2
import grand_project_db as db
import grand_project_review as review
import known_sites
import provenance_check

BENCH_VERSION = "calib-bench-v1"
DERIVATION_JOBS = ("32c858", "32d423")
HOLDOUT_JOB = "f43d36"
THRESHOLDS = (3.0, 4.0, 5.0, 6.0, 8.0)
ALPHA = 0.05
SEARCH_LIMIT_M = f2.DIST_SEARCH_STEPS_M[-1]   # 5000 m, as F2
_BLOCK_M = 2000.0


class BenchError(Exception):
    pass


def _file_md5() -> str:
    """MD5 of this file's own bytes. On the phone Chaquopy serves modules
    from inside the APK (there is no file on disk), so read through the
    module loader first, exactly as provenance_ledger._module_bytes()."""
    loader = globals().get("__loader__")
    if loader is not None and hasattr(loader, "get_data"):
        try:
            return hashlib.md5(loader.get_data(__file__)).hexdigest()
        except Exception:
            pass
    with open(os.path.abspath(__file__), "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


# ----------------------------------------------------------------- loading

def _load_job(db_root: str, prefix: str) -> Dict[str, Any]:
    conn = review._connect(db_root)
    try:
        try:
            job_id = review._resolve_id(conn, "wide_area_search_job", prefix)
        except review.ReviewError as e:
            raise BenchError("bench job %s: %s" % (prefix, e))
        job = dict(conn.execute("SELECT * FROM wide_area_search_job WHERE id = ?", (job_id,)).fetchone())
        trust = review._current_job_trust(conn).get(job_id)
        if trust and trust["trust"] == "CORRUPTED":
            raise BenchError("bench job %s is marked CORRUPTED; the bench refuses it." % prefix)
        tiles = [dict(r) for r in conn.execute(
            "SELECT tile_index, center_lat, center_lon, status, investigation_id "
            "FROM wide_area_search_tile WHERE job_id = ? ORDER BY tile_index", (job_id,)).fetchall()]
        done = [t for t in tiles if t["status"] == "DONE"]
        if not tiles or len(done) != len(tiles):
            raise BenchError("bench job %s is not complete (%d of %d tiles done)."
                             % (prefix, len(done), len(tiles)))
        inv_ids = [t["investigation_id"] for t in done if t["investigation_id"]]
        cands: List[Dict[str, Any]] = []
        for i in range(0, len(inv_ids), 500):
            chunk = inv_ids[i:i + 500]
            cands += [dict(r) for r in conn.execute(
                "SELECT id, lat, lon, score FROM candidate WHERE investigation_id IN (%s)"
                % ",".join("?" * len(chunk)), chunk).fetchall()]
        ctx: Dict[str, Dict[str, Any]] = {}
        ids = [c["id"] for c in cands]
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for r in conn.execute(
                    "SELECT candidate_id, detail_json FROM evidence_link WHERE evidence_type = 'DEM' "
                    "AND relation = 'primary_detection' AND candidate_id IN (%s)"
                    % ",".join("?" * len(chunk)), chunk).fetchall():
                try:
                    ctx[r["candidate_id"]] = json.loads(r["detail_json"] or "{}")
                except ValueError:
                    pass
    finally:
        conn.close()
    missing = [c for c in cands if c["score"] is None]
    if missing:
        raise BenchError("bench job %s: %d candidates have no stored z-score." % (prefix, len(missing)))
    for c in cands:
        c["abs_z"] = abs(float(c["score"]))
        d = ctx.get(c["id"], {})
        c["residual"] = d.get("peak_residual_m")
        c["area"] = d.get("area_cells")
        c["polarity"] = d.get("polarity")
    return {"prefix": prefix, "job_id": job_id, "title": job["title"],
            "tile_size_m": float(job["tile_size_m"]), "done": done, "cands": cands}


def _check_provenance(db_root: str, prefix: str) -> Dict[str, Any]:
    r = provenance_check.check_job(db_root, prefix)
    ok = (r["candidates"] > 0 and r["candidates_verified"] == r["candidates"]
          and not r.get("chain_problem"))
    if not ok:
        raise BenchError("bench job %s is not provenance-VERIFIED (%d of %d candidates); "
                         "the bench refuses to run." % (prefix, r["candidates_verified"], r["candidates"]))
    return {"candidates_verified": r["candidates_verified"], "files": r["files"]}


# ------------------------------------------------------------- geometry

class _Geometry:
    """F2's exact coverage, sites and sample grid for one job."""

    def __init__(self, job: Dict[str, Any]):
        done = job["done"]
        self.half = job["tile_size_m"] / 2.0
        self.lat0 = sum(t["center_lat"] for t in done) / len(done)
        self.lon0 = sum(t["center_lon"] for t in done) / len(done)
        self.tile_xy = [f2._xy(self.lat0, self.lon0, t["center_lat"], t["center_lon"]) for t in done]
        half = self.half

        def covered(x, y):
            return any(abs(x - tx) <= half and abs(y - ty) <= half for tx, ty in self.tile_xy)

        pad = half / f2._M_PER_DEG_LAT + 0.01
        lats = [t["center_lat"] for t in done]
        lons = [t["center_lon"] for t in done]
        lon_pad = pad / max(0.2, math.cos(math.radians(self.lat0)))
        raw = known_sites.sites_in_bbox(min(lats) - pad, min(lons) - lon_pad,
                                        max(lats) + pad, max(lons) + lon_pad)
        self.sites = []
        for s in raw:
            x, y = f2._xy(self.lat0, self.lon0, s["lat"], s["lon"])
            if covered(x, y):
                self.sites.append({"name": s.get("display_name") or s.get("name"), "x": x, "y": y})
        area_m2 = len(done) * (2 * half) ** 2
        step = max(f2.MIN_SAMPLE_STEP_M, math.sqrt(area_m2 / f2.MAX_SAMPLES))
        n_side = max(1, int(round(2 * half / step)))
        offs = [(-half + (i + 0.5) * (2 * half / n_side)) for i in range(n_side)]
        sx, sy = [], []
        for tx, ty in self.tile_xy:
            for ox in offs:
                for oy in offs:
                    sx.append(tx + ox)
                    sy.append(ty + oy)
        self.samples = np.column_stack([np.array(sx), np.array(sy)])
        self.sample_step_m = round(2 * half / n_side, 1)

    def cand_xy(self, cands: List[Dict[str, Any]]) -> np.ndarray:
        if not cands:
            return np.zeros((0, 2))
        return np.array([f2._xy(self.lat0, self.lon0, c["lat"], c["lon"]) for c in cands])


def _nearest_dist(points: np.ndarray, cands: np.ndarray) -> np.ndarray:
    """Exact distance from each point to its nearest candidate; inf when no
    candidate is within SEARCH_LIMIT_M (F2's _nearest returns None there)."""
    out = np.full(len(points), np.inf)
    if len(points) == 0 or len(cands) == 0:
        return out
    bx = np.floor(points[:, 0] / _BLOCK_M).astype(np.int64)
    by = np.floor(points[:, 1] / _BLOCK_M).astype(np.int64)
    keys = bx * 1000003 + by
    order = np.argsort(keys, kind="stable")
    ks = keys[order]
    bounds = np.flatnonzero(np.diff(ks)) + 1
    starts = np.concatenate([[0], bounds])
    ends = np.concatenate([bounds, [len(ks)]])
    for s, e in zip(starts, ends):
        idx = order[s:e]
        pts = points[idx]
        x0, y0 = pts[:, 0].min(), pts[:, 1].min()
        x1, y1 = pts[:, 0].max(), pts[:, 1].max()
        res = np.full(len(idx), np.inf)
        todo = np.ones(len(idx), dtype=bool)
        for margin in f2.DIST_SEARCH_STEPS_M:
            sel = ((cands[:, 0] >= x0 - margin) & (cands[:, 0] <= x1 + margin) &
                   (cands[:, 1] >= y0 - margin) & (cands[:, 1] <= y1 + margin))
            c = cands[sel]
            if len(c):
                p = pts[todo]
                for j in range(0, len(p), 4096):
                    blk = p[j:j + 4096]
                    d2 = ((blk[:, None, 0] - c[None, :, 0]) ** 2 +
                          (blk[:, None, 1] - c[None, :, 1]) ** 2).min(axis=1)
                    d = np.sqrt(d2)
                    pos = np.flatnonzero(todo)[j:j + 4096]
                    hit = d <= margin
                    res[pos[hit]] = d[hit]
            todo = ~np.isfinite(res)
            if not todo.any():
                break
        out[idx] = res
    return out


def _site_ps(geo: _Geometry, cands: List[Dict[str, Any]]) -> List[float]:
    """F2 distance-test p per site for this candidate subset."""
    if not geo.sites:
        return []
    cxy = geo.cand_xy(cands)
    sample_d = np.sort(_nearest_dist(geo.samples, cxy))
    site_xy = np.array([[s["x"], s["y"]] for s in geo.sites])
    site_d = _nearest_dist(site_xy, cxy)
    n = len(sample_d)
    ps = []
    for d in site_d:
        if not np.isfinite(d):
            ps.append(1.0)
        else:
            k = int(np.searchsorted(sample_d, d, side="right"))
            ps.append(max(k / n, 1.0 / (n + 1)))
    return ps


def _fisher(ps: List[float]) -> Dict[str, Any]:
    """Fisher statistic X = -2 sum ln p and log10 of its chi-square(2k)
    tail, computed in log space so tiny p never underflows to 0."""
    k = len(ps)
    if k == 0:
        return {"sites": 0, "X": None, "log10_p": None, "p": None}
    h = -sum(math.log(p) for p in ps)          # X/2
    logs = [0.0]
    term = 0.0
    for i in range(1, k):
        term += math.log(h) - math.log(i) if h > 0 else -math.inf
        logs.append(term)
    m = max(logs)
    log_tail = -h + m + math.log(sum(math.exp(v - m) for v in logs))
    log_tail = min(0.0, log_tail)
    return {"sites": k, "X": 2 * h, "log10_p": log_tail / math.log(10), "p": math.exp(log_tail)}


def _subset(cands: List[Dict[str, Any]], t: float) -> List[Dict[str, Any]]:
    return [c for c in cands if c["abs_z"] >= t]


def _median(vals: List[float]):
    v = sorted(x for x in vals if isinstance(x, (int, float)))
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else 0.5 * (v[n // 2 - 1] + v[n // 2])


def _context(cands: List[Dict[str, Any]]) -> Dict[str, Any]:
    pos = sum(1 for c in cands if c["polarity"] == "positive")
    return {"candidates": len(cands),
            "median_peak_residual_m": _median([c["residual"] for c in cands]),
            "median_area_cells": _median([c["area"] for c in cands]),
            "share_positive": (pos / len(cands)) if cands else None}


# ------------------------------------------------------------------ bench

def run_bench(db_root: str) -> Dict[str, Any]:
    md5 = _file_md5()
    prov = {p: _check_provenance(db_root, p) for p in DERIVATION_JOBS + (HOLDOUT_JOB,)}
    jobs = {p: _load_job(db_root, p) for p in DERIVATION_JOBS + (HOLDOUT_JOB,)}
    geos = {p: _Geometry(jobs[p]) for p in jobs}

    # Derivation: one pooled Fisher statistic per threshold.
    deriv_rows = []
    for t in THRESHOLDS:
        ps_all: List[float] = []
        per_job = {}
        for p in DERIVATION_JOBS:
            sub = _subset(jobs[p]["cands"], t)
            ps = _site_ps(geos[p], sub)
            ps_all += ps
            per_job[p] = dict(_fisher(ps), **_context(sub))
        deriv_rows.append({"threshold": t, "pooled": _fisher(ps_all), "per_job": per_job})
    if not any(r["pooled"]["sites"] for r in deriv_rows):
        raise BenchError("derivation jobs contain no gazetteer sites; nothing to choose on.")
    best = deriv_rows[0]
    for r in deriv_rows[1:]:
        if r["pooled"]["X"] > best["pooled"]["X"] + 1e-9:   # exact tie keeps the lower t
            best = r
    chosen = best["threshold"]

    # Context only: derivation with no threshold.
    deriv_all = {}
    for p in DERIVATION_JOBS:
        ps = _site_ps(geos[p], jobs[p]["cands"])
        deriv_all[p] = dict(_fisher(ps), **_context(jobs[p]["cands"]))

    # Hold-out: judged once, chosen threshold vs no threshold.
    ho = jobs[HOLDOUT_JOB]
    ho_t = _fisher(_site_ps(geos[HOLDOUT_JOB], _subset(ho["cands"], chosen)))
    ho_all = _fisher(_site_ps(geos[HOLDOUT_JOB], ho["cands"]))
    sig = ho_t["p"] is not None and ho_t["p"] < ALPHA
    better = (ho_t["X"] is not None and ho_all["X"] is not None and ho_t["X"] > ho_all["X"])
    passed = bool(sig and better)
    indicative = len(geos[HOLDOUT_JOB].sites) < f2.SMALL_SAMPLE_SITES
    verdict = ("PASS (INDICATIVE: %d hold-out sites < %d)" % (len(geos[HOLDOUT_JOB].sites), f2.SMALL_SAMPLE_SITES)
               if passed and indicative else "PASS" if passed else "FAIL")

    result = {
        "bench_version": BENCH_VERSION,
        "script_md5": md5,
        "thresholds": list(THRESHOLDS),
        "alpha": ALPHA,
        "jobs": {p: {"job_id": jobs[p]["job_id"], "title": jobs[p]["title"],
                     "role": "hold-out" if p == HOLDOUT_JOB else "derivation",
                     "tiles": len(jobs[p]["done"]), "candidates": len(jobs[p]["cands"]),
                     "sites": len(geos[p].sites), "sample_points": int(len(geos[p].samples)),
                     "sample_step_m": geos[p].sample_step_m,
                     "provenance": prov[p]} for p in jobs},
        "derivation": deriv_rows,
        "derivation_no_threshold": deriv_all,
        "chosen_threshold": chosen,
        "holdout": {"chosen": dict(ho_t, **_context(_subset(ho["cands"], chosen))),
                    "no_threshold": dict(ho_all, **_context(ho["cands"])),
                    "p_below_alpha": sig, "beats_no_threshold": better},
        "verdict": verdict,
        "passed": passed,
        "indicative": indicative,
        "note": ("Read-only. A PASS does not switch anything on: adopting calib-v1 (label and sort only) "
                 "is a separate user-approved step. Nothing here changes status, confidence or the "
                 "MODERATE ceiling, or says whether any candidate is a site."),
    }
    result["report_text"] = _report(result)
    try:
        gp = db.get_wide_area_search_job(db_root, jobs[HOLDOUT_JOB]["job_id"])["grand_project_id"]
        db.log_timeline_event(
            db_root, gp, "CALIBRATION_BENCH",
            related_entity_type="wide_area_search_job", related_entity_id=jobs[HOLDOUT_JOB]["job_id"],
            description=("%s md5 %s: chosen |z|>=%g; hold-out p=%s vs no threshold p=%s; %s."
                         % (BENCH_VERSION, md5, chosen, _fmt_p(ho_t), _fmt_p(ho_all), verdict)))
    except Exception:
        pass
    return result


def _fmt_p(f: Dict[str, Any]) -> str:
    if f["p"] is None:
        return "n/a"
    if f["p"] >= 1e-4:
        return "%.4f" % f["p"]
    e = math.floor(f["log10_p"])
    return "%.1fe%d" % (10 ** (f["log10_p"] - e), e)


def _report(r: Dict[str, Any]) -> str:
    L = ["%s  (script md5 %s)" % (r["bench_version"], r["script_md5"]),
         "Read-only. Rules frozen before the first run.", ""]
    L.append("VERDICT: %s" % r["verdict"])
    L.append("Chosen on derivation: |z| >= %g" % r["chosen_threshold"])
    h = r["holdout"]
    L.append("Hold-out %s: chosen p = %s, no threshold p = %s" % (
        HOLDOUT_JOB, _fmt_p(h["chosen"]), _fmt_p(h["no_threshold"])))
    L.append("  p < %.2f: %s   beats no threshold: %s" % (
        r["alpha"], "yes" if h["p_below_alpha"] else "no", "yes" if h["beats_no_threshold"] else "no"))
    L.append("  candidates kept: %d of %d" % (h["chosen"]["candidates"], h["no_threshold"]["candidates"]))
    L.append("")
    L.append("Bench jobs")
    for p, j in r["jobs"].items():
        L.append("  %s %-10s %s" % (p, j["role"], j["title"]))
        L.append("     %d tiles, %d candidates, %d sites, provenance %d verified"
                 % (j["tiles"], j["candidates"], j["sites"], j["provenance"]["candidates_verified"]))
    L.append("  (f43d36's title is a data-entry slip; its box is Susiana West.)")
    L.append("")
    L.append("Derivation (pooled %s): threshold -> candidates kept, combined p" % "+".join(DERIVATION_JOBS))
    for row in r["derivation"]:
        kept = sum(row["per_job"][p]["candidates"] for p in DERIVATION_JOBS)
        mark = "  <- chosen" if row["threshold"] == r["chosen_threshold"] else ""
        L.append("  |z|>=%-3g %5d  p=%s%s" % (row["threshold"], kept, _fmt_p(row["pooled"]), mark))
    L.append("  no threshold: " + ", ".join(
        "%s p=%s" % (p, _fmt_p(r["derivation_no_threshold"][p])) for p in DERIVATION_JOBS))
    L.append("")
    L.append("Context only (never used to choose): chosen subset on hold-out")
    c = h["chosen"]
    L.append("  median peak residual %s m, median area %s cells, positive %s"
             % ("n/a" if c["median_peak_residual_m"] is None else "%.2f" % c["median_peak_residual_m"],
                "n/a" if c["median_area_cells"] is None else "%g" % c["median_area_cells"],
                "n/a" if c["share_positive"] is None else "%.0f%%" % (100 * c["share_positive"])))
    L.append("")
    L.append(r["note"])
    return "\n".join(L)


def run_bench_json(db_root: str) -> str:
    try:
        return json.dumps(run_bench(db_root))
    except (BenchError, review.ReviewError) as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": "bench failed: %s" % e})
