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

BUGFIX (2026-09-02) -- CONCURRENT-DOWNLOAD RACE, found from a real
on-device Iran run (screenshots: 341/357 DEM tiles "error", 357/357
NDVI cells "error", and a crash: FileNotFoundError renaming
offline_status.json.part -> offline_status.json).

Root cause: run_country_download_json() is a long blocking call, run
from OfflineDataActivity.kt inside `withContext(Dispatchers.Default)`.
Kotlin coroutine cancellation is cooperative -- it does NOT interrupt a
blocking Chaquopy/native call already in flight. If the Activity is
destroyed and recreated while a download is still running (screen
rotation, or the app being backgrounded long enough for the OS to
recreate the Activity), the OLD call keeps running to completion on its
own thread even though the OLD lifecycleScope was cancelled. If the
user then taps "DOWNLOAD OFFLINE DATA" again for the same country, a
genuinely second, fully concurrent run_country_download_json() call
starts. Both instances then race on the exact same FIXED temp
filenames -- offline_status.json.part here, and every individual
tile's .tif.part / cell's .npz.part in offline_data_manager.py --
whichever writer calls os.replace() first yanks the other's temp file
out from under it, producing exactly the observed FileNotFoundError
and inflating the DEM/NDVI "error" counts (a lost temp-file race, not a
real network/API failure, for most of those entries -- consistent with
DEM's partial 14/357 successes: a fast, single-GET-per-tile operation
has a much smaller collision window than NDVI's much slower per-cell
STAC-search-plus-three-band-download operation, which collided on
essentially every cell).

Fixed two ways:
  1. THE ACTUAL FIX: a real, atomic (os.O_CREAT | os.O_EXCL) per-country
     lock file (.download.lock in that country's storage folder) --
     _acquire_lock()/_release_lock() below. A second concurrent
     run_country_download_json() call for the same country now fails
     FAST and CLEARLY with DownloadAlreadyRunningError instead of
     silently racing. This works even across a full process restart,
     unlike any purely in-memory Kotlin-side guard (which OfflineData
     Activity.kt also now has, as a same-instance-only nicety -- see
     that file's own bugfix note).
  2. DEFENSE IN DEPTH: _write_status()'s temp filename is no longer a
     fixed ".part" -- it now includes this process's PID and a random
     UUID, so even in some future scenario where two writers
     legitimately end up running concurrently (a bug elsewhere, or
     simply while the lock above is being added/removed across a
     version boundary), they can no longer collide on the identical
     temp path. The equivalent fix was made in offline_data_manager.py
     for DEM tile files, NDVI band downloads, and NDVI cell files (see
     that file's own bugfix note).
"""

from __future__ import annotations

import json
import os
import time
import uuid

from offline_country_registry import get_country, list_countries
from offline_data_manager import download_country_dem, download_country_ndvi


class DownloadAlreadyRunningError(Exception):
    """Raised when run_country_download_json() is called for a country
    that already has an active lock file -- i.e. a previous call for the
    same country is (or at least appears to be) still running. Prevents
    two concurrent downloads from racing on the same tile/cell/status
    files -- see module docstring's 2026-09-02 BUGFIX note for the real
    on-device bug this closes."""


def list_offline_countries_json() -> str:
    """{"IR": "Iran", ...} for populating a country picker."""
    return json.dumps(list_countries())


def _status_path(offline_data_root: str, country_iso: str) -> str:
    return os.path.join(offline_data_root, country_iso.lower(), "offline_status.json")


def _lock_path(offline_data_root: str, country_iso: str) -> str:
    return os.path.join(offline_data_root, country_iso.lower(), ".download.lock")


def _acquire_lock(offline_data_root: str, country_iso: str) -> None:
    """Atomically creates the lock file. os.O_EXCL makes the create fail
    if the file already exists, with no check-then-create race window
    (unlike `if not os.path.isfile(path): open(path, 'w')`, which two
    threads could both pass before either creates the file). Raises
    DownloadAlreadyRunningError if another run already holds the lock."""
    path = _lock_path(offline_data_root, country_iso)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise DownloadAlreadyRunningError(
            f"A download for {country_iso} is already running (or a previous run "
            f"didn't clean up its lock file at {path}, e.g. because the app process "
            f"was killed mid-download). Wait for the other download to finish. If "
            f"you're sure nothing is actually running anymore, delete that lock file "
            f"and try again."
        )
    with os.fdopen(fd, "w") as f:
        f.write(str(time.time()))


def _release_lock(offline_data_root: str, country_iso: str) -> None:
    path = _lock_path(offline_data_root, country_iso)
    if os.path.exists(path):
        os.remove(path)


def _write_status(offline_data_root, country_iso, phase, done, total, detail=""):
    path = _status_path(offline_data_root, country_iso)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Unique per call (pid + random uuid), not a fixed ".part" name --
    # see module docstring's 2026-09-02 BUGFIX note. Defense in depth on
    # top of the lock above: even if two writers somehow ran
    # concurrently, they can no longer race on the identical temp path.
    tmp = f"{path}.{os.getpid()}.{uuid.uuid4().hex}.part"
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

    ACQUIRES A PER-COUNTRY LOCK for the duration of the run (see module
    docstring's 2026-09-02 BUGFIX note): if a download for this country
    is already running, this raises DownloadAlreadyRunningError
    immediately instead of starting a second, colliding run. The lock
    is always released in a finally block, including when a real
    download error propagates -- a failed run must not permanently
    block all future attempts for that country.
    """
    country = get_country(country_iso)
    _acquire_lock(offline_data_root, country_iso)
    try:
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
    finally:
        _release_lock(offline_data_root, country_iso)
