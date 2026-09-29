"""
grand_project_calibration.py

Part of ARIYAN GEO AI -- F2 early self-calibration (added 2026-09-29,
user-approved: measure on an IRANIAN job only; first bench = the
Persepolis-area job).

WHAT THIS MEASURES (one Wide-Area Search job at a time, read-only)
1. COVERAGE: the ground this job really examined = the union of its DONE
   tiles. Each DONE tile covers a square of tile_size_m centred on the
   tile centre (wide_area_search_mobile.derive_analysis_window() sizes
   the detector's usable interior to equal the tile). PENDING and FAILED
   tiles are not coverage, so a half-finished job is measured only on
   what it actually scanned.
2. HIT RATE: of the recorded gazetteer POINTS (known_sites_data, Pedersen
   ANE Site Placemarks, Zenodo 10.5281/zenodo.6384045) that lie inside
   the coverage, how many have at least one of THIS job's candidates
   within HIT_RADII_M (500 m primary; 1000 m because the gazetteer points
   were placed by eye and may be a few hundred metres off).
3. CHANCE BASELINE: the fraction of the coverage that lies within the
   same radius of any candidate, measured on a regular sample grid over
   every DONE tile. If candidates were scattered with no relation to
   sites, a site would be "hit" with exactly this probability. Expected
   hits by chance = sites x fraction. The one-sided exact binomial
   probability of getting at least the observed hits by chance is
   reported, with an explicit small-sample warning.

4. DISTANCE TEST (added 2026-09-29, method fixed BEFORE it was run on any
   further job, after the a1f509 run showed a 500 m hit rate cannot
   separate skill from luck when candidates are dense). For each site:
   d = distance to the nearest candidate; p_site = share of the scanned
   area (same sample grid) whose nearest candidate is at most d away,
   i.e. how often a randomly placed site would do at least this well.
   It uses the job's real candidate layout, so clustering is included.
   p_site is floored at 1/(samples+1) so it never reads as impossible.
   Sites are combined with Fisher's method (X = -2 sum ln p, chi-square
   with 2k degrees of freedom). This is the primary skill figure; the
   radius hit rates stay for context.

WHAT THIS DOES NOT MEASURE
- A false-alarm rate. That needs places VERIFIED to hold no site; the
  gazetteer cannot provide them ("not in gazetteer" is not "no site").
  Candidates far from any recorded site are counted and shown, but they
  are NOT called false alarms.
- City outlines (known_sites extents) and line features are not used;
  points only, so every site counts once.

READ-ONLY: never changes candidates, status, confidence or evidence.
Writes exactly one timeline_event (CALIBRATION_RUN) per run so the
measurement is on record. Refuses jobs marked CORRUPTED.

IRAN CHECK: the app has no border polygon, only offline_country_registry's
PADDED Iran box (24.8-40.0 N, 43.9-63.5 E), which also covers parts of
Iraq (e.g. Ctesiphon, 44.5 E). The report states which case applies;
it does not claim a border check it cannot do.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List

import grand_project_db as db
import grand_project_review as review
import known_sites
import offline_country_registry as countries

HIT_RADII_M = (500.0, 1000.0)
PRIMARY_RADIUS_M = 500.0
MAX_SAMPLES = 200000          # cap on baseline sample points (phone speed)
MIN_SAMPLE_STEP_M = 50.0
SMALL_SAMPLE_SITES = 20       # below this, results are indicative only
FAR_FROM_SITE_M = 2000.0
DIST_SEARCH_STEPS_M = (500.0, 1000.0, 2000.0, 5000.0)   # nearest-candidate search, widening

_M_PER_DEG_LAT = 111320.0


class CalibrationError(Exception):
    pass


def _xy(lat0: float, lon0: float, lat: float, lon: float):
    """Local metres east/north of (lat0, lon0); equirectangular, fine at
    tile/job scale."""
    return ((lon - lon0) * _M_PER_DEG_LAT * math.cos(math.radians(lat0)),
            (lat - lat0) * _M_PER_DEG_LAT)


class _CandidateIndex:
    """Grid hash of candidate positions (local metres) for fast
    'any candidate within r' queries."""

    def __init__(self, pts, cell_m: float):
        self.cell = cell_m
        self.grid: Dict[tuple, list] = {}
        for x, y in pts:
            self.grid.setdefault((int(math.floor(x / cell_m)), int(math.floor(y / cell_m))), []).append((x, y))

    def nearest_within(self, x: float, y: float, r: float):
        """Distance to the nearest point if within r, else None."""
        cx, cy = int(math.floor(x / self.cell)), int(math.floor(y / self.cell))
        span = int(math.ceil(r / self.cell))
        best = None
        r2 = r * r
        for i in range(cx - span, cx + span + 1):
            for j in range(cy - span, cy + span + 1):
                for px, py in self.grid.get((i, j), ()):
                    d2 = (px - x) ** 2 + (py - y) ** 2
                    if d2 <= r2 and (best is None or d2 < best):
                        best = d2
        return None if best is None else math.sqrt(best)


def _nearest(idx: "_CandidateIndex", x: float, y: float):
    """Distance to the nearest candidate, searching outward in steps;
    None if none within the last step."""
    for r in DIST_SEARCH_STEPS_M:
        d = idx.nearest_within(x, y, r)
        if d is not None:
            return d
    return None


def _fisher_combined(ps: List[float]) -> float:
    """Fisher's method: P(chi2 with 2k dof >= -2 sum ln p). Exact closed
    form for even degrees of freedom."""
    k = len(ps)
    half_x = -sum(math.log(p) for p in ps)
    term, total = 1.0, 1.0
    for i in range(1, k):
        term *= half_x / i
        total += term
    return min(1.0, math.exp(-half_x) * total)


def _binom_tail(n: int, k: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p), exact."""
    if k <= 0:
        return 1.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    return min(1.0, sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1)))


def calibrate_job(db_root: str, job_ref: str) -> Dict[str, Any]:
    conn = review._connect(db_root)
    try:
        try:
            job_id = review._resolve_id(conn, "wide_area_search_job", job_ref)
        except review.ReviewError as e:
            raise CalibrationError(str(e))
        job = dict(conn.execute("SELECT * FROM wide_area_search_job WHERE id = ?", (job_id,)).fetchone())
        trust = review._current_job_trust(conn).get(job_id)
        if trust and trust["trust"] == "CORRUPTED":
            raise CalibrationError(
                "Job %s is marked CORRUPTED (%s); calibration refuses it." % (job_id[:6], trust["reason"]))
        tiles = [dict(r) for r in conn.execute(
            "SELECT tile_index, center_lat, center_lon, status, investigation_id "
            "FROM wide_area_search_tile WHERE job_id = ? ORDER BY tile_index", (job_id,)).fetchall()]
        done = [t for t in tiles if t["status"] == "DONE"]
        if not done:
            raise CalibrationError("Job %s has no DONE tiles; nothing was scanned yet." % job_id[:6])
        inv_ids = [t["investigation_id"] for t in done if t["investigation_id"]]
        cands = []
        for i in range(0, len(inv_ids), 500):
            chunk = inv_ids[i:i + 500]
            cands += [dict(r) for r in conn.execute(
                "SELECT id, lat, lon, status FROM candidate WHERE investigation_id IN (%s)"
                % ",".join("?" * len(chunk)), chunk).fetchall()]
    finally:
        conn.close()

    half = float(job["tile_size_m"]) / 2.0
    lat0 = sum(t["center_lat"] for t in done) / len(done)
    lon0 = sum(t["center_lon"] for t in done) / len(done)
    tile_xy = [_xy(lat0, lon0, t["center_lat"], t["center_lon"]) for t in done]

    def covered(x, y):
        return any(abs(x - tx) <= half and abs(y - ty) <= half for tx, ty in tile_xy)

    # Sites inside the scanned coverage (points only).
    pad = half / _M_PER_DEG_LAT + 0.01
    lats = [t["center_lat"] for t in done]
    lons = [t["center_lon"] for t in done]
    lon_pad = pad / max(0.2, math.cos(math.radians(lat0)))
    raw_sites = known_sites.sites_in_bbox(min(lats) - pad, min(lons) - lon_pad,
                                          max(lats) + pad, max(lons) + lon_pad)
    sites = []
    for s in raw_sites:
        x, y = _xy(lat0, lon0, s["lat"], s["lon"])
        if covered(x, y):
            sites.append(dict(s, x=x, y=y))

    def run_subset(label: str, subset: List[dict]) -> Dict[str, Any]:
        pts = [_xy(lat0, lon0, c["lat"], c["lon"]) for c in subset]
        idx = _CandidateIndex(pts, 500.0)
        area_m2 = len(done) * (2 * half) ** 2
        step = max(MIN_SAMPLE_STEP_M, math.sqrt(area_m2 / MAX_SAMPLES))
        n_side = max(1, int(round(2 * half / step)))
        offs = [(-half + (i + 0.5) * (2 * half / n_side)) for i in range(n_side)]
        per_radius = {}
        for r in HIT_RADII_M:
            near = total = 0
            for tx, ty in tile_xy:
                for ox in offs:
                    for oy in offs:
                        total += 1
                        if idx.nearest_within(tx + ox, ty + oy, r) is not None:
                            near += 1
            frac = near / total if total else 0.0
            hits = 0
            for s in sites:
                if idx.nearest_within(s["x"], s["y"], r) is not None:
                    hits += 1
            n = len(sites)
            per_radius[str(int(r))] = {
                "radius_m": r,
                "sites": n,
                "hits": hits,
                "hit_rate": (hits / n) if n else None,
                "chance_fraction": frac,
                "expected_hits_by_chance": n * frac,
                "p_at_least_this_many_by_chance": _binom_tail(n, hits, frac) if n else None,
                "sample_points": total,
                "sample_step_m": round(2 * half / n_side, 1),
            }
        # Distance test: nearest-candidate distance at every sample point.
        sample_d = []
        for tx, ty in tile_xy:
            for ox in offs:
                for oy in offs:
                    d = _nearest(idx, tx + ox, ty + oy)
                    sample_d.append(float("inf") if d is None else d)
        sample_d.sort()
        n_samp = len(sample_d)
        dist_sites = []
        for s in sites:
            d = _nearest(idx, s["x"], s["y"])
            if d is None:
                p_site = 1.0
            else:
                # share of samples with nearest distance <= d (binary search)
                lo, hi = 0, n_samp
                while lo < hi:
                    mid = (lo + hi) // 2
                    if sample_d[mid] <= d:
                        lo = mid + 1
                    else:
                        hi = mid
                p_site = max(lo / n_samp, 1.0 / (n_samp + 1)) if n_samp else 1.0
            dist_sites.append({"name": s.get("display_name") or s.get("name"),
                               "nearest_candidate_m": None if d is None else round(d, 1),
                               "p_chance_this_close": p_site})
        distance_test = {
            "sites": dist_sites,
            "combined_p": _fisher_combined([x["p_chance_this_close"] for x in dist_sites]) if dist_sites else None,
            "sample_points": n_samp,
            "sample_step_m": round(2 * half / n_side, 1),
        }
        far = 0
        site_idx = _CandidateIndex([(s["x"], s["y"]) for s in sites], 1000.0)
        for x, y in pts:
            if site_idx.nearest_within(x, y, FAR_FROM_SITE_M) is None:
                far += 1
        return {"label": label, "candidates": len(subset), "far_from_any_site": far,
                "by_radius": per_radius, "distance_test": distance_test, "_idx": idx}

    all_res = run_subset("all candidates", cands)
    kept = [c for c in cands if c["status"] != "REJECTED"]
    kept_res = run_subset("not Rejected", kept)

    site_rows = []
    for s in sites:
        d_all = all_res["_idx"].nearest_within(s["x"], s["y"], 5000.0)
        site_rows.append({
            "name": s.get("display_name") or s.get("name"),
            "lat": s["lat"], "lon": s["lon"],
            "nearest_candidate_m": None if d_all is None else round(d_all, 1),
            "hit_500": d_all is not None and d_all <= PRIMARY_RADIUS_M,
        })
    site_rows.sort(key=lambda r: (r["nearest_candidate_m"] is None, r["nearest_candidate_m"] or 0))
    for res in (all_res, kept_res):
        res.pop("_idx", None)

    iran = countries.get_country_for_point(lat0, lon0)
    iran_note = ("inside Iran's PADDED box (no border polygon in the app; the box also covers parts of Iraq)"
                 if iran is not None and iran.iso_code == "IR" else "OUTSIDE Iran's padded box")

    result = {
        "job_id": job_id,
        "job_title": job["title"],
        "job_status": job["status"],
        "job_trust": trust["trust"] if trust else None,
        "tiles_total": len(tiles),
        "tiles_done": len(done),
        "tile_size_m": float(job["tile_size_m"]),
        "coverage_km2": round(len(done) * (2 * half) ** 2 / 1e6, 2),
        "iran_note": iran_note,
        "sites_in_coverage": len(sites),
        "sites": site_rows,
        "all": all_res,
        "not_rejected": kept_res,
        "small_sample": len(sites) < SMALL_SAMPLE_SITES,
        "gazetteer": known_sites.data.SOURCE_CITATION,
        "false_alarm_rate": "not measured (needs verified negatives; the gazetteer cannot supply them)",
    }
    result["report_text"] = _report_text(result)

    p = all_res["by_radius"]["500"]
    try:
        gp = db.get_wide_area_search_job(db_root, job_id)["grand_project_id"]
        db.log_timeline_event(
            db_root, gp, "CALIBRATION_RUN",
            related_entity_type="wide_area_search_job", related_entity_id=job_id,
            description=("F2 calibration: %d/%d tiles scanned, %d gazetteer sites in coverage, "
                         "%d hit within 500 m (chance expectation %.2f, p=%s); "
                         "distance test combined p=%s."
                         % (len(done), len(tiles), p["sites"], p["hits"], p["expected_hits_by_chance"],
                            "n/a" if p["p_at_least_this_many_by_chance"] is None
                            else "%.3g" % p["p_at_least_this_many_by_chance"],
                            "n/a" if all_res["distance_test"]["combined_p"] is None
                            else "%.3g" % all_res["distance_test"]["combined_p"])))
    except Exception:
        pass
    return result


def _pct(x):
    return "n/a" if x is None else "%.0f%%" % (100 * x)


def _report_text(r: Dict[str, Any]) -> str:
    L = []
    L.append("Job %s  %s" % (r["job_id"][:6], r["job_title"]))
    L.append("status %s, trust %s" % (r["job_status"], r["job_trust"] or "not marked"))
    L.append("Location: %s" % r["iran_note"])
    L.append("Scanned: %d of %d tiles (%.2f km2, tile %.0f m)"
             % (r["tiles_done"], r["tiles_total"], r["coverage_km2"], r["tile_size_m"]))
    L.append("Recorded sites inside scanned area: %d (gazetteer points only)" % r["sites_in_coverage"])
    L.append("")
    for key in ("all", "not_rejected"):
        res = r[key]
        L.append("[%s: %d candidates]" % (res["label"], res["candidates"]))
        dt = res["distance_test"]
        if dt["sites"]:
            L.append("  DISTANCE TEST (primary):")
            for s in dt["sites"]:
                dist = "none within 5 km" if s["nearest_candidate_m"] is None else "%.0f m" % s["nearest_candidate_m"]
                L.append("    %s: nearest %s, chance this close %.3g"
                         % (s["name"], dist, s["p_chance_this_close"]))
            L.append("    combined chance with no real skill: %.3g (Fisher, %d sites)"
                     % (dt["combined_p"], len(dt["sites"])))
            L.append("    (sample grid %d points, step %.0f m)" % (dt["sample_points"], dt["sample_step_m"]))
        for rad in ("500", "1000"):
            b = res["by_radius"][rad]
            if not b["sites"]:
                L.append("  %s m: no recorded sites in coverage -- cannot measure" % rad)
                continue
            L.append("  within %s m: hit %d of %d (%s)" % (rad, b["hits"], b["sites"], _pct(b["hit_rate"])))
            L.append("    by chance: %s of area near a candidate -> %.2f hits expected"
                     % (_pct(b["chance_fraction"]), b["expected_hits_by_chance"]))
            L.append("    chance of >= %d hits with no real skill: %.3g"
                     % (b["hits"], b["p_at_least_this_many_by_chance"]))
        L.append("  candidates > 2 km from any recorded site: %d (NOT false alarms -- unknown)"
                 % res["far_from_any_site"])
        L.append("")
    L.append("Per site (nearest candidate, all candidates):")
    for s in r["sites"]:
        d = "none within 5 km" if s["nearest_candidate_m"] is None else "%.0f m" % s["nearest_candidate_m"]
        L.append("  %s %s  -- %s" % ("HIT " if s["hit_500"] else "miss", s["name"], d))
    L.append("")
    if r["small_sample"]:
        L.append("WARNING: only %d recorded sites -- indicative only, not a reliable "
                 "performance figure." % r["sites_in_coverage"])
    L.append("False-alarm rate: " + r["false_alarm_rate"] + ".")
    L.append("Gazetteer: " + r["gazetteer"])
    return "\n".join(L)


def calibrate_job_json(db_root: str, job_ref: str) -> str:
    try:
        return json.dumps(calibrate_job(db_root, job_ref))
    except (CalibrationError, review.ReviewError) as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": "calibration failed: %s" % e})
