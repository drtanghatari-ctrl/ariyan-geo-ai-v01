"""
offline_download_runner.py

Part of ARIYAN GEO AI's OFFLINE MODE extension.

Thin JSON-string wrapper around offline_data_manager.py's real
download_country_dem()/download_country_ndvi() functions, in the same
style as investigation_mobile.run_investigation_json() and
debate_mobile.run_debate_json() already used by MainActivity.kt --
Kotlin calls these via Chaquopy with plain strings and gets back a JSON
string, rather than marshaling Python dataclasses or callables across
the Chaquopy boundary.

SUPERSEDES AN EARLIER VERSION OF THIS FILE (from a previous session,
never actually wired up to any Kotlin Activity -- OfflineDataActivity.kt
did not exist yet when it was written). That earlier version is being
deliberately replaced here, not silently discarded -- the two real
differences, and why this version was chosen:

  1. PROGRESS REPORTING: the earlier version ran both downloads fully
     synchronously with no progress_callback wired in at all -- for a
     whole-country download that can realistically take hours, that
     means zero user-visible feedback the entire time. This version
     reports live progress by writing a small JSON status file
     (offline_status.json, per country folder) after every tile/cell,
     using the progress_callback parameter both download_country_*
     functions already support -- entirely on the Python side, no
     Kotlin callback needs to cross the Chaquopy boundary.
     OfflineDataActivity.kt polls that file periodically while the
     download runs on a background thread. This reuses a mechanism
     already proven in this project (dem_manifest.json /
     ndvi_manifest.json) rather than inventing a new cross-language
     callback path.

  2. ERROR HANDLING: the earlier version wrapped every result in a JSON
     object with an explicit "error" key (null on success, a string on
     failure), reasoning from this project's real "Candidate null" bug
     history (org.json's optString(key, fallback) only substitutes the
     fallback when a key is ABSENT, not when it's present holding JSON
     null -- see MainActivity.kt's debate-section history). That
     reasoning is sound in general, but doesn't actually apply to this
     file's JSON shape: none of the fields this module returns are ever
     legitimately null on success (phase/done/total/detail,
     dem_total/ndvi_total, dem_by_status/ndvi_by_status are always
     populated), so there is no field here that pattern would protect.
     This version instead follows a DIFFERENT precedent already
     established in this same project for a user-initiated action whose
     failure should be visible rather than swallowed:
     investigation_mobile.run_investigation_json() lets a real Python
     exception propagate as a Chaquopy PyException, caught by Kotlin's
     existing try/catch around the call (see OfflineDataActivity.kt's
     onDownloadClicked()) -- as opposed to
     debate_mobile.run_debate_json()'s catch-and-return-JSON-null
     convention, which exists specifically because a debate-engine
     failure is optional supplementary output that must never hide the
     investigation result underneath it. A download failure is not
     optional supplementary output -- the user explicitly asked for
     this operation's outcome -- so the run_investigation_json()
     precedent is the correct one to follow here, not
     run_debate_json()'s.

Neither download_country_dem nor download_country_ndvi is modified by
this file -- both are called exactly as already committed and tested,
unchanged.

TESTED in a local sandbox: list_offline_countries_json() against the
real registry; get_offline_download_status_json()'s honest
"not_started" case before any download has run; run_country_download_json()
end-to-end against fake DEM/NDVI sessions (reusing the same fakes already
proven for offline_data_manager.py's own tests), confirming real progress
snapshots are written during the run (not just at the end) and the final
summary JSON's per-status counts match the real results; and
get_offline_country_summary_json() reading back the real manifests
written by that run.

HONEST STATE: only sandbox/control-flow tested so far, same honest gap
as offline_data_manager.py itself -- the real network calls this wraps
are unverified until this file is actually exercised on-device (the
current step in the agreed build order).
"""

from __future__ import annotations

import json
import os

from offline_country_registry import get_country, list_countries
from offline_data_manager import download_country_dem, download_country_ndvi


def list_offline_countries_json() -> str:
    """{"IR": "Iran", ...} for populating a country picker."""
    return json.dumps(list_countries())


def _status_path(offline_data_root: str, country_iso: str) -> str:
    return os.path.join(offline_data_root, country_iso.lower(), "offline_status.json")


def _write_status(offline_data_root, country_iso, phase, done, total, detail=""):
    path = _status_path(offline_data_root, country_iso)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w") as f:
        json.dump({"phase": phase, "done": done, "total": total, "detail": detail}, f)
    os.replace(tmp, path)


def get_offline_download_status_json(offline_data_root: str, country_iso: str) -> str:
    """Reads the current progress status, or an honest 'not_started'
    status if no download has ever been run for this country -- never
    fabricates progress data."""
    path = _status_path(offline_data_root, country_iso)
    if not os.path.isfile(path):
        return json.dumps({"phase": "not_started", "done": 0, "total": 0, "detail": ""})
    with open(path) as f:
        return f.read()


def get_offline_country_summary_json(offline_data_root: str, country_iso: str) -> str:
    """Reads back dem_manifest.json / ndvi_manifest.json if they exist,
    summarizing real counts per status -- used to show 'already
    downloaded: X/Y DEM tiles, X/Y NDVI cells' without re-scanning every
    file. Returns honest zero counts (not an error) if a manifest
    doesn't exist yet -- matches this project's existing distinction
    between 'no data yet' and 'a real error occurred'."""
    country = get_country(country_iso)
    root = os.path.join(offline_data_root, country.storage_folder)

    def _summarize(manifest_name, list_key):
        path = os.path.join(root, manifest_name)
        if not os.path.isfile(path):
            return {"total": 0, "by_status": {}}
        with open(path) as f:
            manifest = json.load(f)
        items = manifest.get(list_key, [])
        by_status = {}
        for item in items:
            s = item.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
        return {"total": len(items), "by_status": by_status}

    return json.dumps({
        "country_iso": country.iso_code,
        "country_name": country.name,
        "dem": _summarize("dem_manifest.json", "tiles"),
        "ndvi": _summarize("ndvi_manifest.json", "cells"),
    })


def run_country_download_json(offline_data_root: str, country_iso: str) -> str:
    """Blocking call -- runs the real DEM download, then the real NDVI
    download, for one country, writing live progress to
    offline_status.json throughout (see module docstring). Meant to be
    called from a background thread (Kotlin's
    withContext(Dispatchers.Default), matching every other Chaquopy call
    in this app -- see MainActivity.kt's runInvestigation()/runDebate()).

    Returns a JSON summary of what actually happened -- real per-status
    counts for both halves, never a fabricated 'success' -- so a
    partially-failed real-world download (e.g. no network partway
    through) is visible to the user rather than silently reported as
    complete.

    A real exception (e.g. a network failure) is deliberately NOT caught
    here -- it propagates to Kotlin as a Chaquopy PyException, matching
    investigation_mobile.run_investigation_json()'s precedent for a
    user-initiated action whose failure should be visible, not
    debate_mobile.run_debate_json()'s swallow-and-omit convention (see
    module docstring for why that convention doesn't fit here).
    """
    country = get_country(country_iso)

    def dem_progress(done, total, result):
        _write_status(offline_data_root, country_iso, "dem", done, total,
                      detail=f"{result.status} ({result.lat},{result.lon})")

    def ndvi_progress(done, total, result):
        _write_status(offline_data_root, country_iso, "ndvi", done, total,
                      detail=f"{result.status} ({result.lat},{result.lon})")

    _write_status(offline_data_root, country_iso, "starting", 0, 0)

    dem_results = download_country_dem(country, offline_data_root, progress_callback=dem_progress)
    ndvi_results = download_country_ndvi(country, offline_data_root, progress_callback=ndvi_progress)

    def _count_by_status(results):
        counts = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts

    total_done = len(dem_results) + len(ndvi_results)
    _write_status(offline_data_root, country_iso, "done", total_done, total_done)

    return json.dumps({
        "country_iso": country.iso_code,
        "dem_total": len(dem_results),
        "dem_by_status": _count_by_status(dem_results),
        "ndvi_total": len(ndvi_results),
        "ndvi_by_status": _count_by_status(ndvi_results),
    })
