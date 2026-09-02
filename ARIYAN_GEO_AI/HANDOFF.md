# ARIYAN GEO AI — Status & Roadmap (updated 2026-09-02, OFFLINE DOWNLOAD RACE + DRIVE CONSENT FIXES)

> This file is the durable source of truth for project status. It is
> updated at the end of every working session so the project state
> survives even if a chat session or device is interrupted.

## What this is

A real, buildable Android Studio project (Chaquopy: native Kotlin UI +
embedded CPython) — a scientific geospatial investigation app for
archaeology/buried-feature detection, generalizable to geology/
engineering/terrain analysis. Built via GitHub Actions cloud builds
(no local Android SDK available), producing a downloadable debug APK
artifact. Sideloaded onto a physical Android phone (no emulator).

Hard requirement standing throughout: nothing in the app is
synthetic/fake unless explicitly labeled as such on screen; no claiming
verification that didn't actually happen.

## Roadmap status

| # | Item | Status |
|---|------|--------|
| 1 | Multi-source DEM+NDVI correlation | ✅ Complete, on-device verified |
| 2 | Device GPS integration | ✅ Complete, on-device verified |
| 3 | Offline rule-based AI Debate Engine (4 perspectives) | ✅ Complete, on-device verified, including the Vegetation/Agronomic mislabeling fix and GPR-into-debate confirmation logic. No open issues. |
| 4 | Depth estimation | 🟡 Partially done. Manual GPR field-pick entry (soil preset + two-way time → depth estimate with uncertainty range), GPR-as-third-evidence-source, and GPR-into-debate confidence adjustments are all built and **confirmed on-device**. Still not started: automated GPR device-export parsing (`parse_gpr_export_file()` is an explicit not-yet-implemented placeholder — no real device export sample to build against yet) and any CV-based feature detection from radargrams. Blocked on GPR hardware purchase (deferred, too expensive right now — kept on roadmap intentionally). |
| 5 | Real Sentinel-2 NDVI via Copernicus | ✅ Complete, on-device verified |

**All of roadmap items (1)-(3) and (5) are fully done. Item (4) has its
hardware-independent half (manual-pick GPR evidence + GPR-into-debate)
fully built and on-device confirmed; only automated device-export
parsing remains, and that is blocked on owning real GPR hardware.**

## LATEST WORK: Offline country-data download — concurrent-download race fixed; Drive consent silent-failure fixed (2026-09-02)

This is a separate feature area from the roadmap above (offline
DEM+NDVI package download + Google Drive backup, so an investigation
can run with no network access and survive an uninstall/reinstall).
Both pieces (download flow, Drive consent + backup wiring) were newly
added and, per their own honest-state notes, had NOT yet been run to a
clean success on an actual device. A real on-device test of this
session surfaced two real bugs, both root-caused from actual code (not
guessed) and fixed:

**Bug A — concurrent-download race (the big one).** On-device test of a
full Iran download (started 22:52, checked 23:11) showed: 341/357 DEM
tiles "error" (only 14 actually downloaded), 357/357 NDVI cells
"error" (zero composited), and a crash banner: `FileNotFoundError`
renaming `offline_status.json.part` → `offline_status.json`.

Root cause, confirmed by reading the actual source
(`offline_download_runner.py`, `offline_data_manager.py`,
`OfflineDataActivity.kt`): `run_country_download_json()` is a genuinely
blocking Chaquopy call, run from Kotlin inside
`withContext(Dispatchers.Default)`. Kotlin coroutine cancellation is
cooperative — it does **not** interrupt a blocking native/Python call
already in flight. If `OfflineDataActivity` is destroyed and recreated
while a download is still running (screen rotation, or being
backgrounded long enough to be recreated), the OLD call keeps running
to completion on its own thread even though its old `lifecycleScope`
was cancelled. Tapping "DOWNLOAD OFFLINE DATA" again for the same
country then starts a genuinely SECOND, fully concurrent download run.
Both instances race on the exact same FIXED temp filenames —
`offline_status.json.part`, and every individual tile's `.tif.part` /
cell's `.npz.part` in `offline_data_manager.py` — whichever writer
calls `os.replace()` first yanks the other's temp file out from under
it. That's the literal mechanism behind both the crash AND the inflated
error counts (most of those 341/357 and 357/357 were lost temp-file
races, not real network/API failures — consistent with DEM's partial
14/357 successes: a fast single-GET-per-tile has a much smaller
collision window than NDVI's much slower per-cell STAC-search-plus-
three-band-download, which collided on essentially every cell).

Fixed (commits to `offline_download_runner.py`, `offline_data_manager.py`,
`OfflineDataActivity.kt`, all 2026-09-02):
1. **The real fix**: `offline_download_runner.py` now takes a real,
   atomic (`os.O_CREAT | os.O_EXCL`) per-country lock file
   (`.download.lock`) for the duration of `run_country_download_json()`.
   A second concurrent call for the same country now fails fast and
   clearly with `DownloadAlreadyRunningError` instead of racing. Works
   even across a full process restart, unlike any purely in-memory
   Kotlin-side guard.
2. **Defense in depth**: every `.part`/`.npz.part` temp filename in
   both Python files (`_write_status`, `_download_one_tile`,
   `_download_band_file`, `_write_ndvi_cell`) now includes the process
   PID and a random UUID instead of a fixed suffix, so even in some
   future scenario with a real concurrent writer, they can no longer
   collide on the identical temp path.
3. `OfflineDataActivity.kt` adds an `isDownloadRunning` flag as a
   same-Activity-instance nicety (catches an in-process double-tap
   immediately, no Python round-trip) and now shows a clear message if
   `DownloadAlreadyRunningError` propagates from Python (the case the
   flag can't catch — a different Activity instance after recreation),
   instead of the previous raw race-condition crash text.

**Bug B — silent Drive consent failure.** User report: tapping "Grant
Google Drive Access" shows the system account picker ("Choose an
account"); after picking an account, nothing visible happens.

Root cause, confirmed by reading `OfflineDataActivity.kt`:
`driveConsentLauncher`'s callback only caught `ApiException`. If the
consent flow returns with a null `Intent` (result code other than
`RESULT_OK`, or certain device/Play-Services combinations that don't
attach data even on a real completion), `getAuthorizationResultFromIntent(null)`
throws a `NullPointerException` — not an `ApiException` — which was
uncaught, so nothing updated the status text and nothing else visibly
happened either.

Fixed: the callback now explicitly checks for a null `Intent` first
(with a clear status message) and catches any `Exception` around the
call, so a real failure is always surfaced instead of silently doing
nothing.

**STATUS: fixes committed 2026-09-02, build triggered (run #109) to
confirm they compile. NOT YET re-tested on-device** — the next session
should re-run a fresh country download (ideally without rotating the
screen or backgrounding mid-download, to isolate whether the lock alone
now makes a normal single-run download succeed cleanly) and re-try the
Drive "Grant Google Drive Access" flow, reporting back what the
consent flow actually shows after picking an account (does a second
scope-consent screen appear? is there a Toast/crash? does it return
immediately?) — that detail is still needed to know whether Bug B's fix
fully closes the loop or whether there's a second issue in the consent
flow itself once the null-data path is ruled out.

## Known bugs

1. **Degenerate DEM candidate** (area=0, |z|=NaN, empty polarity) —
   fixed in `evidence_record.py` + `investigation_multi_mobile.py`.
   Closed.
2. **APK reinstall signature mismatch / corrupted keystore** — fixed
   with a real binary keystore + pinned `signingConfigs.debug`. Closed.
3. **Vegetation/Agronomic "no vegetation evidence present" mislabeling**
   — fixed in `debate_mobile.py` (`_build_candidate()` now unions
   `supporting_sources` with the investigation-level `checked_sources`
   instead of letting the narrower list shadow it). Confirmed on-device
   across 2 independent real candidates. Closed.
4. **"Candidate null" intermittent header bug** — the AI Debate section
   occasionally renders "Candidate null:" instead of the real candidate
   number. Confirmed intermittent (most runs render "Candidate #1"/"#2"
   correctly, including every run in the GPR-into-debate testing
   sequence above). Root cause not yet found. **Deprioritized by user
   ("not a big deal for now") — not being actively worked on.**
5. **Offline download concurrent-download race + crash** (DEM/NDVI
   error-flooded on a real Iran run; FileNotFoundError renaming
   offline_status.json.part) — fixed via a per-country lock file +
   unique temp filenames, see "LATEST WORK" above. Fixed 2026-09-02,
   **not yet re-confirmed on-device.**
6. **Offline Drive backup: "Grant Google Drive Access" appears to do
   nothing after picking an account** — root-caused to an uncaught
   NullPointerException on a null consent-flow Intent, fixed 2026-09-02,
   see "LATEST WORK" above. **Not yet re-confirmed on-device** — still
   need to learn whether a second scope-consent screen is supposed to
   appear after account selection and, if so, whether that screen
   itself is the thing silently failing.

## Cleanup — paused, not yet done

- `investigation_multi_mobile-1.py` (repo root) and
  `ARIYAN_GEO_AI/investigation_multi_mobile.py` — confirmed stale/
  superseded duplicates, safe to delete, not yet deleted.
- `activity_main-2.xml` (10113 bytes, repo root) — never inspected.
- Root `README.md` — checked, trivial, low priority.

(Stray "Python Package using Conda" workflow is NOT part of this list —
see dedicated section below; permanently deprioritized per user
decision, do not re-flag.)

## Stray "Python Package using Conda" workflow — permanently deprioritized

A second workflow named **"Python Package using Conda"** exists in
`.github/workflows/` (origin unknown, not intentionally added) and
fails on every push (`EnvironmentFileNotFound` — references a
non-existent `environment.yml`). Does **not** block the real APK build.

**User decision: permanently ignore this. Do not investigate, fix, or
flag it again in future sessions.** Fixing it would require
reauthorizing the Zapier GitHub connection with "Contents: Read and
write" permission — user declined, since the workflow is cosmetic noise
only.

## GPR hardware status

User does not own GPR hardware yet — looked into pricing, found it too
expensive right now. It's a future purchase plan, kept on the roadmap
as deferred rather than dropped. Manual pick entry (a human reads a
two-way travel time off any real radargram and types it in) is
therefore the only real GPR data path in this build, and was built
specifically to be hardware-independent for that reason. This has now
been fully validated on-device, including its effect on the debate
engine — so the app's GPR support is genuinely complete for what's
possible without owning a device.

## Real-DEM path (roadmap item 1 foundation)

`dem_source_mobile.py` + `ascii_grid.py` fetch/parse OpenTopography's
plain-text AAIGrid format (pure NumPy, no GDAL/rasterio — GDAL confirmed
unbuildable via Chaquopy, chaquo/chaquopy#427). `np_ops.resample_bilinear`
handles non-square real rasters. Verified against a real Silbury Hill
fetch and separately on-device across many real coordinate runs
(Tehran, northern Iran, and the GPR-into-debate test sequence above).

## Real-NDVI path (roadmap item 5)

Copernicus Data Space Ecosystem's Sentinel Hub Statistical API, "core vs
halo" bbox check per DEM candidate (documented approximation, not a
true annulus — the underlying Statistical API is bbox-only). Implemented
in `ndvi_source_mobile.py` + `investigation_multi_mobile.py`. Confirmed
working on-device many times, including throughout the GPR testing
sequence above.

(Note: this is the LIVE per-candidate NDVI path used during a normal
investigation, and is separate from the offline whole-country NDVI
composite path in `offline_data_manager.py`/`sentinel2_stac_client.py`
discussed under "LATEST WORK" above — the offline path's own real-network
calls are still unconfirmed on-device, unlike this live path.)

## Depth estimation (roadmap item 4) — hardware-independent half DONE, device-parsing not started

- `gpr_depth_model.py`: real, published GPR electromagnetic-velocity
  ranges per soil/material type (Daniels; Conyers), explicitly flagged
  as an approximation pending real site calibration. Converts a manual
  two-way travel time into a depth ESTIMATE with explicit min/max range,
  never a single precise number. **Done, on-device confirmed.**
- `gpr_source_mobile.py`: `GPRPick`/`GPRSurvey` dataclasses + a
  `GPREvidence` wrapper mirroring `RealNdviCoreHaloEvidence`. Supports a
  real, hardware-independent MANUAL PICK ENTRY path. **Done, on-device
  confirmed.**
- Wired into `evidence_record.py`/`investigation_multi_mobile.py` as an
  optional third_evidence slot (kept out of `anomalies[]` to avoid
  repeating the earlier degenerate-candidate bug). **Done, on-device
  confirmed.**
- UI in `activity_main.xml`/`MainActivity.kt`: soil preset + two-way
  time + optional device note, gated behind NDVI correlation also being
  on. Renders a depth section with explicit uncertainty range. **Done,
  on-device confirmed.**
- GPR-into-debate confidence adjustments in `debate_engine.py` +
  `debate_mobile.py`. **Done, on-device confirmed** — see prior session's
  LATEST MILESTONE note (now superseded above by this session's offline-
  download work as the most recent activity, but still fully closed).
- `parse_gpr_export_file()` remains an explicit placeholder that always
  raises `GPRSourceNotImplementedError` — deliberately not guessing at
  any specific device's real export format without a real sample to
  test against (would violate the project's no-fabrication rule).
  **Not started, blocked on GPR hardware purchase.**
- Field image evidence (separate, doesn't need GPR hardware): geotagged
  photos (EXIF GPS + timestamp) for custody/provenance — near-term tier
  is simple attach-and-display, on-device CV (cropmarks/soil
  discoloration) deferred as a separate project. **Not started.**

## Tooling available (custom Zapier/GitHub code actions)

- `list_workflow_runs`, `get_workflow_run_status`, `get_workflow_run_jobs`,
  `get_job_log_text`, `trigger_build_apk_workflow` — CI visibility/control,
  since the connector has no native way to check Actions runs.
- `commit_raw_base64_file` — the reliable way to commit binary files
  (standard `create_file` double-encodes and corrupts binaries).
- `commit_text_file` — the reliable way to commit plain-text files
  (like this one); handles base64 encoding automatically.
- `get_file_text`, `get_file_text_grep`, `list_dir`, `delete_file`,
  `find_commits_touching_path` — reliable reads/deletes/history search,
  since the standard `get_file_contents`/`repository_v2` actions became
  unreliable partway through the project for this repo.

## Working infrastructure notes

- GitHub accessed via a connected Zapier GitHub connector (account:
  `drtanghatari-ctrl`).
- Recurring past failure mode: file uploads/commits have repeatedly not
  taken effect as expected across sessions (drag-and-drop overwrites
  failing silently, placeholder text committed as code, files swapped
  under wrong names, a keystore once stored as literal base64 text).
  Standing practice: commit via the custom code actions above, re-verify
  file content/size after every commit — never assume a commit "took."
- User's phone spontaneously restarts sometimes mid-session — this file
  and chat memory both exist specifically so no progress is ever lost
  to that.

## Resume-here checklist (read this first after any interruption)

1. Roadmap items (1), (2), (3), (5) are ALL done and on-device verified.
   Item (4)'s hardware-independent half is ALSO done and on-device
   verified. Nothing on the core roadmap is mid-flight.
2. **Immediate next step**: re-test the offline country-data download
   on-device (a fresh, single, non-interrupted run for a country) to
   confirm the concurrent-download race fix actually produces a clean
   result now, and re-try "Grant Google Drive Access" to confirm Bug B
   is really closed — see "LATEST WORK" and Known bugs #5/#6 above for
   exactly what to check and report back.
3. Two things the user has explicitly said they want to discuss in a
   future session, not yet scoped: (a) some ambitious new ideas for the
   project (unspecified — ask what they have in mind), and (b) a visual
   "decorations"/polish pass (likely related to an earlier-shown
   desktop-GIS mockup, "ARIYAN GEO AI Scientific Geospatial Laboratory",
   with a 3D subsurface model among other polish features, deliberately
   deferred until the technical roadmap was done — which it now
   effectively is). Do not start either without asking for specifics
   first.
4. Lower-priority housekeeping still open, can be picked up any time:
   resume the paused cleanup (delete 2 stale duplicate files —
   `investigation_multi_mobile-1.py` and
   `ARIYAN_GEO_AI/investigation_multi_mobile.py`; inspect
   `activity_main-2.xml`); the intermittent "Candidate null" bug
   (deprioritized, not urgent). Do NOT investigate the "Python Package
   using Conda" workflow — permanently deprioritized per user decision,
   see dedicated section above.
5. Item (4) automated GPR device parsing stays parked until GPR
   hardware is affordable — check in on whether that's changed,
   otherwise no action needed there yet.
