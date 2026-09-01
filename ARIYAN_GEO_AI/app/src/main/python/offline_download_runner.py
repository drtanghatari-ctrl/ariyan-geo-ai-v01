"""
offline_download_runner.py

Part of ARIYAN GEO AI's OFFLINE MODE extension.

The Chaquopy-facing JSON wrapper around offline_data_manager.py's two
bulk downloaders (download_country_dem, download_country_ndvi), matching
this project's existing convention of a thin *_json() wrapper module per
Kotlin-callable entry point (investigation_mobile.py, debate_mobile.py,
etc.). OfflineDataActivity.kt calls only the two functions below --
never offline_data_manager.py's dataclass-returning functions directly.

THIS MODULE IS PART OF THE SEPARATE OFFLINE EXTENSION. It is never
imported by any existing live-pipeline file and does not change how the
live/online investigation flow behaves.

Two entry points:

  - run_offline_download_json(iso_code, offline_data_root): runs BOTH the
    DEM and NDVI downloads for a country (DEM first, matching the agreed
    build order) and returns a JSON summary. This is a long-running,
    real-network call -- Kotlin must invoke it off the main thread (see
    OfflineDataActivity.kt, same pattern as
    MainActivity.runInvestigation()/runDebate()).

  - get_offline_status_json(iso_code, offline_data_root): a fast,
    NETWORK-FREE read of whatever manifest files already exist locally
    (written by a previous run_offline_download_json call), so the UI
    can show "already downloaded" status without re-downloading
    anything. Returns an honest "manifest_present: false" status (never
    a fabricated zero-progress summary) when no manifest exists yet.

Both functions catch every real exception from the underlying downloader
and return it as a JSON "error" field rather than letting a raw Chaquopy
PyException/traceback surface to Kotlin -- matching
debate_mobile.run_debate_json()'s existing defensive-JSON convention.
Unlike that function, though, a download failure here IS surfaced to the
user as a real error rather than silently omitted, since the user is
explicitly asking for this operation's outcome.

JSON SHAPE NOTE: every returned object always has an "error" key, either
JSON null (success) or a string (failure) -- callers on the Kotlin side
MUST check it with JSONObject.isNull("error"), not optString("error", "")
with a fallback. This project already hit exactly this org.json pitfall
once (optString's fallback only applies when a key is ABSENT, not when
it's present holding JSON null) -- see MainActivity.kt's "Candidate
null" bug history for the full story. Per-status counts are nested under
a "counts" sub-object (get_offline_status_json) rather than spread as
top-level keys, specifically so a real status string that happens to
collide with another field name (e.g. a tile status of "downloaded")
can never silently overwrite an unrelated field.

HONEST STATE: only sandbox/control-flow tested so far, same honest gap
as offline_data_manager.py itself -- the real network calls this wraps
are unverified until this file is actually exercised on-device (the
current step in the agreed build order).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List

from offline_country_registry import get_country
from offline_data_manager import download_country_dem, download_country_ndvi


def _summarize_dem(results: List) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    error_details = []
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        if r.status == "error" and len(error_details) < 5:
            error_details.append({"lat": r.lat, "lon": r.lon, "detail": r.detail})
    return {
        "total_tiles": len(results),
        "downloaded": counts.get("downloaded", 0),
        "already_present": counts.get("already_present", 0),
        "not_available": counts.get("not_available", 0),
        "errors": counts.get("error", 0),
        "error_details": error_details,
    }


def _summarize_ndvi(results: List) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    error_details = []
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        if r.status == "error" and len(error_details) < 5:
            error_details.append({"lat": r.lat, "lon": r.lon, "detail": r.detail})
    return {
        "total_cells": len(results),
        "composited": counts.get("composited", 0),
        "already_present": counts.get("already_present", 0),
        "empty_no_scenes": counts.get("empty_no_scenes", 0),
        "errors": counts.get("error", 0),
        "error_details": error_details,
    }


def run_offline_download(iso_code: str, offline_data_root: str) -> Dict[str, Any]:
    """Real function (not JSON) -- run_offline_download_json below is the
    Chaquopy-facing wrapper. Kept separate so this can also be exercised
    from a plain Python test/script without JSON round-tripping."""
    country = get_country(iso_code)
    started_at = time.time()

    dem_results = download_country_dem(country, offline_data_root)
    ndvi_results = download_country_ndvi(country, offline_data_root)

    finished_at = time.time()

    return {
        "country": {"iso_code": country.iso_code, "name": country.name},
        "dem": _summarize_dem(dem_results),
        "ndvi": _summarize_ndvi(ndvi_results),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": finished_at - started_at,
    }


def run_offline_download_json(iso_code: str, offline_data_root: str) -> str:
    try:
        result = run_offline_download(iso_code, offline_data_root)
        result["error"] = None
    except Exception as exc:
        result = {"error": f"{type(exc).__name__}: {exc}"}
    return json.dumps(result)


def _read_manifest(path: str):
    if not os.path.isfile(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def get_offline_status(iso_code: str, offline_data_root: str) -> Dict[str, Any]:
    """Network-free. Reads whatever manifest files already exist on disk
    from a previous real download -- never re-downloads anything and
    never fabricates a status when no manifest exists yet."""
    country = get_country(iso_code)
    country_dir = os.path.join(offline_data_root, country.storage_folder)
    dem_manifest = _read_manifest(os.path.join(country_dir, "dem_manifest.json"))
    ndvi_manifest = _read_manifest(os.path.join(country_dir, "ndvi_manifest.json"))

    dem_status: Dict[str, Any]
    if dem_manifest is None:
        dem_status = {"manifest_present": False}
    else:
        tiles = dem_manifest.get("tiles", [])
        counts: Dict[str, int] = {}
        for t in tiles:
            counts[t["status"]] = counts.get(t["status"], 0) + 1
        dem_status = {"manifest_present": True, "total_tiles": len(tiles), "counts": counts}

    ndvi_status: Dict[str, Any]
    if ndvi_manifest is None:
        ndvi_status = {"manifest_present": False}
    else:
        cells = ndvi_manifest.get("cells", [])
        counts = {}
        for c in cells:
            counts[c["status"]] = counts.get(c["status"], 0) + 1
        ndvi_status = {"manifest_present": True, "total_cells": len(cells), "counts": counts}

    return {
        "country": {"iso_code": country.iso_code, "name": country.name},
        "dem": dem_status,
        "ndvi": ndvi_status,
    }


def get_offline_status_json(iso_code: str, offline_data_root: str) -> str:
    try:
        result = get_offline_status(iso_code, offline_data_root)
        result["error"] = None
    except Exception as exc:
        result = {"error": f"{type(exc).__name__}: {exc}"}
    return json.dumps(result)
