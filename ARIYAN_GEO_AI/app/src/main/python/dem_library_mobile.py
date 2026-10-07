"""
dem_library_mobile.py -- app-facing entry points for the offline DEM
library (srtm_library.py, lib-v1). Added 2026-10-05 (libfill-v1).

Two calls, both JSON-in/JSON-out and never raising:

  dem_library_plan_json(root, job_id)
      Read-only. Which 1-degree tiles the job's bbox (+0.01 deg margin)
      needs, per DEM type, which are already in the library (with
      SHA-256), which are missing, and how many library live calls are
      left in the rolling 24 h budget. No network.

  fill_dem_library_json(root, job_id, api_key, max_calls, spot_check)
      Downloads ONLY the missing tiles (one live call each), at most
      max_calls and never past the rolling 24 h budget. Optional
      spot-check: ONE extra live AAIGrid request over a small window at
      the bbox centre, compared cell-by-cell with the library cut.
      Stops cleanly on quota; never deletes or overwrites a present tile.

Budget: every live call this module makes is appended to
<root>/dem_library/live_calls.json (UTC timestamps). The rolling
24 h cap (DAILY_LIVE_CAP = 40) is the same number the automation design
(ap-v1) uses for Pass 2. Library HITS during Pass 2 cost nothing and
are not logged here.
"""
import json
import os
import threading
import time
import traceback

import srtm_library as lib

VERSION = "libfill-v1.1"  # cop-bulk-v1: bulk COP30 counts as present
DAILY_LIVE_CAP = 40
WINDOW_S = 24 * 3600
SPOT_HALF_DEG = 0.005   # spot-check window: ~1.1 km x ~0.9 km
_log_lock = threading.Lock()


def _log_path(root):
    return os.path.join(root, "dem_library", "live_calls.json")


def _recent_calls(root):
    try:
        with open(_log_path(root)) as f:
            calls = json.load(f)
    except (OSError, ValueError):
        calls = []
    cutoff = time.time() - WINDOW_S
    return [c for c in calls if c.get("t", 0) >= cutoff]


def _record_call(root, label):
    with _log_lock:
        calls = _recent_calls(root)
        calls.append({"t": time.time(), "label": label})
        os.makedirs(os.path.dirname(_log_path(root)), exist_ok=True)
        tmp = _log_path(root) + ".part"
        with open(tmp, "w") as f:
            json.dump(calls, f)
        os.replace(tmp, _log_path(root))


def budget_left(root):
    return max(0, DAILY_LIVE_CAP - len(_recent_calls(root)))


def _job_bbox(root, job_id):
    import grand_project_db as db
    job = db.get_wide_area_search_job(root, job_id)
    if not job:
        raise ValueError(f"job {job_id} not found")
    return job, (job["min_lat"], job["max_lat"], job["min_lon"], job["max_lon"])


def _plan(root, job_id, demtypes):
    job, (s, n, w, e) = _job_bbox(root, job_id)
    out = {"version": VERSION, "job_id": job_id, "title": job.get("title"),
           "bbox": {"south": s, "north": n, "west": w, "east": e},
           "demtypes": {}, "missing_total": 0}
    for dt in demtypes:
        idx = lib.load_index(root, dt)
        needed = lib.tiles_for_box(s - lib.TILE_MARGIN_DEG, n + lib.TILE_MARGIN_DEG,
                                   w - lib.TILE_MARGIN_DEG, e + lib.TILE_MARGIN_DEG)
        present, missing, bulk = [], [], []
        for la, lo in needed:
            name = lib.tile_name(la, lo)
            if name in idx:
                present.append({"tile": name, "sha256": idx[name]["sha256"],
                                "bytes": idx[name].get("bytes"), "source": "library"})
                continue
            bpath = _bulk_cover(root, dt, la, lo)
            if bpath is not None:
                # cop-bulk-v1: cells already on the device in the bulk COP30
                # store; never downloaded again (sha256 shown on demand only --
                # hashing ~40 MB per tile would slow this read-only dialog).
                bulk.append({"tile": name, "source": "bulk",
                             "file": os.path.relpath(bpath, root)})
            else:
                missing.append(name)
        out["demtypes"][dt] = {"needed": len(needed), "present": present,
                               "bulk": bulk, "missing": missing}
        out["missing_total"] += len(missing)
    out["budget_left_24h"] = budget_left(root)
    out["daily_cap"] = DAILY_LIVE_CAP
    return out


def _bulk_cover(root, demtype, la, lo):
    """Path of a usable bulk COP30 tile for this degree, else None."""
    if demtype != "COP30":
        return None
    try:
        import cop30_bulk
        return cop30_bulk.covered(root, la, lo)
    except Exception:
        return None


def dem_library_plan_json(root, job_id, demtypes_csv="SRTMGL1,COP30"):
    try:
        dts = [d for d in demtypes_csv.split(",") if d in lib.SUPPORTED_DEMTYPES]
        return json.dumps(_plan(root, job_id, dts))
    except Exception as ex:
        return json.dumps({"error": f"{type(ex).__name__}: {ex}"})


def _bulk_cut_ok(root, win):
    try:
        import cop30_bulk
        return cop30_bulk.cut_window(root, *win)[0] is not None
    except Exception:
        return False


def fill_dem_library_json(root, job_id, api_key, max_calls=10, spot_check=True,
                          demtypes_csv="SRTMGL1,COP30"):
    try:
        if not api_key:
            return json.dumps({"error": "No OpenTopography API key saved."})
        dts = [d for d in demtypes_csv.split(",") if d in lib.SUPPORTED_DEMTYPES]
        _, (s, n, w, e) = _job_bbox(root, job_id)
        started = time.time()

        def gate(label):
            if budget_left(root) <= 0:
                return False
            _record_call(root, label)
            return True

        report = lib.ensure_tiles(root, dts, s, n, w, e, api_key, int(max_calls), on_live_call=gate,
                                  covered=lambda dt, la, lo: _bulk_cover(root, dt, la, lo) is not None)
        report["downloaded"] = [{k: d[k] for k in ("tile", "demtype", "sha256", "bytes")}
                                for d in report["downloaded"]]

        checks = []
        if spot_check and report["stopped"] is None:
            cy, cx = (s + n) / 2.0, (w + e) / 2.0
            win = (cy - SPOT_HALF_DEG, cy + SPOT_HALF_DEG, cx - SPOT_HALF_DEG, cx + SPOT_HALF_DEG)
            for dt in dts:
                use_bulk = False
                if lib.cut_window(root, dt, *win)[0] is None:
                    use_bulk = dt == "COP30" and _bulk_cut_ok(root, win)
                    if not use_bulk:
                        checks.append({"demtype": dt, "skipped": "window not cuttable (near-tie or tile missing)"})
                        continue
                if not gate(f"{dt}/spot_check"):
                    checks.append({"demtype": dt, "skipped": "24 h budget used up"})
                    continue
                try:
                    if use_bulk:
                        import cop30_bulk
                        r = cop30_bulk.spot_check(root, *win, api_key)
                    else:
                        r = lib.spot_check(root, dt, *win, api_key)
                    checks.append({"demtype": dt, **{k: v for k, v in r.items()
                                                     if isinstance(v, (bool, int, float, str, list, type(None)))}})
                except Exception as ex:
                    checks.append({"demtype": dt, "ok": False, "error": f"{type(ex).__name__}: {ex}"[:300]})
        report["spot_checks"] = checks
        report["plan_after"] = _plan(root, job_id, dts)
        report["seconds"] = round(time.time() - started, 1)
        report["version"] = VERSION
        return json.dumps(report)
    except Exception as ex:
        return json.dumps({"error": f"{type(ex).__name__}: {ex}",
                           "trace": traceback.format_exc()[-1500:]})
