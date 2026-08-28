# ARIYAN GEO AI — Status & Roadmap (updated 2026-08-28, build-fix session)

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
| 3 | Offline rule-based AI Debate Engine (4 perspectives) | ⚠️ Code wired in and byte-verified on GitHub. Build was failing on an unrelated infra bug (corrupted debug.keystore, see below) — that's now fixed and a fresh build (run #48) is in flight. Still needs an actual sideload test to confirm the debate section renders before this item is marked complete. |
| 4 | Depth estimation | ❌ Not started. Deferred — needs real GPR hardware, which is a future purchase (too expensive right now). Kept on roadmap intentionally, not dropped. |
| 5 | Real Sentinel-2 NDVI via Copernicus | ✅ Complete, on-device verified |

## LATEST SESSION: build was failing, root cause found and fixed

User reported "Actions got red." Investigation using new GitHub Actions
tooling (see "New tooling" below) found:

- Runs #45/#46 (triggered by the previous HANDOFF.md commit) both
  failed at the **"Build debug APK"** Gradle step, not at setup.
- Root cause: `ARIYAN_GEO_AI/app/debug.keystore` was corrupted. The
  file's raw bytes on GitHub were literally the ASCII text of the
  keystore's base64 representation (e.g. starting with the text
  "MIIKZg..."), not the actual decoded binary. Proof: the Gradle error
  was `KeytoolException: ... toDerInputStream rejects tag type 77` —
  77 is the decimal ASCII code for the letter 'M', the first character
  of that base64 text, confirming keytool was trying to parse text as
  binary DER.
- This happened because the keystore was originally committed through
  a file-upload path that base64-encoded the (already-base64) content
  a second time without ever decoding back to real binary — another
  instance of the general "file uploads/commits don't take effect as
  expected" failure mode already known for this repo.
- **Fix process (worth knowing for next time):** the standard
  `create_or_update_file` GitHub action available through the Zapier
  connector does NOT reliably accept raw/data-URI binary content —
  passing a `data:...;base64,` URI as content just got stored as
  *more* literal text (made it worse on the first fix attempt). The
  reliable fix was writing a small custom Zapier code action
  (`commit_raw_base64_file`) that calls GitHub's Contents API PUT
  endpoint directly, passing the base64 string verbatim as the API's
  `content` field with no re-encoding. That produced a file of the
  correct byte size (2666 bytes, matching a real debug keystore) for
  the first time.
- After the fix, a fresh build was triggered directly via GitHub's
  workflow_dispatch API (not by another commit) — **run #48**,
  https://github.com/drtanghatari-ctrl/ariyan-geo-ai-v01/actions/runs/33187315292
  — was in progress as of this write. Status not yet confirmed complete
  at time of writing; check it first thing on resume.

## New tooling now available (custom Zapier/GitHub code actions)

Discovered/created this session — the GitHub connector previously
seemed limited to basic CRUD, but it actually has (or now has) custom
code actions for real GitHub Actions visibility:

- `list_workflow_runs` (owner, repo, per_page) — lists recent workflow
  runs with id/status/conclusion/branch/commit — use this first to find
  a run_id.
- `get_workflow_run_status` (run_id) — quick status/conclusion check.
- `get_workflow_run_jobs` (run_id) — per-job, per-step status — use to
  find which exact step failed.
- `get_job_log_text` (job_id) — fetches the actual error log text
  (searches for "* What went wrong:" marker) — use this to get the
  real Gradle/build error, not just "failure."
- `trigger_build_apk_workflow` (no params) — dispatches build-apk.yml
  on main directly via workflow_dispatch, without needing a commit.
- `update_build_apk_workflow` (exists, not yet used/inspected this
  session).
- `commit_raw_base64_file` (owner, repo, path, branch, message,
  content_base64, sha?) — NEW this session — the reliable way to commit
  binary files (keystores, images, APKs, etc.) without the text
  double-encoding problem the standard `create_file` action has. **Use
  this instead of `create_file` for any non-text file going forward.**

## Also discovered, not yet investigated

A second, unfamiliar workflow named **"Python Package using Conda"**
is also present in this repo and is ALSO failing on every push (runs
#42-#46 all failure). This is not a workflow we intentionally added —
origin unknown (possibly an old template/default file). It doesn't
block the real APK build, but it's a stray failing workflow worth
cleaning up or investigating: check `.github/workflows/` for a file
other than `build-apk.yml` and decide whether to fix or delete it.

## Debate Engine — what happened and current state

- Roadmap item (3) had previously been recorded as complete, but was
  discovered to never have actually existed in the repo (confirmed via
  full git history search — no `debate_engine.py`/`debate_mobile.py`
  anywhere). The only trace was a stray draft file, `MainActivity-3.kt`
  (never merged into the real app), which called a `debate_mobile`
  module that didn't exist.
- User supplied the real `debate_engine.py` (rule-based, offline,
  stdlib-only, ~480 lines, 4 perspectives: Geomorphology,
  Anthropogenic/Archaeological, Data Artifact/Skeptic,
  Vegetation/Agronomic; synthesis ranks LEADING_INTERPRETATION /
  CONTESTED / WEAK_SIGNAL / NO_DATA, never declares a winner; caps
  confidence honestly whenever NDVI evidence is synthetic).
- `debate_mobile.py` (the JSON-string Chaquopy wrapper `MainActivity.kt`
  calls) did not exist and was newly written, reading the real schema
  directly from `evidence_record.py` / `anomaly_detection_mobile.py` /
  `correlation.py` / `investigation_multi_mobile.py` — not guessed.
  `debate_engine.py`'s built-in field aliases did NOT match this
  project's actual schema, so `debate_mobile.py` translates real
  `anomalies[]` + `correlation[]` + `evidence[]` fields into
  `debate_engine.py`'s expected vocabulary, without modifying
  `debate_engine.py` itself.
- Both files committed to `app/src/main/python/`. `MainActivity.kt`
  updated to call `runDebate()`/`appendDebateSection()`.
- All three files (`debate_engine.py`, `debate_mobile.py`,
  `MainActivity.kt`) were re-fetched fresh from GitHub and re-verified
  (byte-for-byte diff on `debate_engine.py`, content match on the other
  two) — confirmed correctly committed at the right paths.
- **What remains unverified:** actual on-device/compiled-APK behavior.
  Run #48 (see above) is the first build attempt since the keystore fix
  — check its result first on resume.

## Known bugs — fixed and verified

1. **Degenerate DEM candidate** (area=0, |z|=NaN, empty polarity slipping
   through the detector) — root cause was a real NDVI core/halo result
   (different schema than `AnomalyCandidate`) being merged into the same
   `anomalies[]` list that `MainActivity.kt` reads assuming uniform
   fields. Fixed in `evidence_record.py` + `investigation_multi_mobile.py`.
2. **APK reinstall signature mismatch** — originally "fixed" by
   committing a pinned `app/debug.keystore` and wiring
   `signingConfigs.debug` in `build.gradle.kts` — but that commit
   itself corrupted the keystore file (see "LATEST SESSION" above),
   which is now properly re-fixed with real binary content.

## Cleanup — paused, not yet done

- `investigation_multi_mobile-1.py` (repo root) and
  `ARIYAN_GEO_AI/investigation_multi_mobile.py` — identical to each
  other (confirmed via SHA), confirmed stale/superseded duplicates of
  the real build-used file at `app/src/main/python/investigation_multi_mobile.py`.
  Safe to delete, not yet deleted.
- `activity_main-2.xml` (10113 bytes, repo root) — never inspected.
- Root `README.md` — checked, trivial ("# ariyan-geo-ai-v01"), low
  priority.
- Stray "Python Package using Conda" workflow (see above) — not yet
  investigated.

## Real-DEM path (roadmap item 1 foundation)

`dem_source_mobile.py` + `ascii_grid.py` fetch/parse OpenTopography's
plain-text AAIGrid format (pure NumPy, no GDAL/rasterio — GDAL confirmed
unbuildable via Chaquopy, chaquo/chaquopy#427). `np_ops.resample_bilinear`
handles non-square real rasters (SRTM-family data isn't square in
degrees away from the equator). Verified against a real Silbury Hill
fetch (permanent regression fixture
`tests/fixtures/silbury_hill_real_aaigrid.asc`) and separately on-device
with real coordinates near Tehran (35.74, 51.41).

## Real-NDVI path (roadmap item 5)

Copernicus Data Space Ecosystem's Sentinel Hub Statistical API computes
NDVI server-side (no raster to device, sidestepping the GDAL blocker)
but only returns AOI-level aggregate stats — so instead of a full-grid
scan, built a per-DEM-candidate "core vs halo" bbox check: for each DEM
anomaly, fetch real NDVI mean+stddev for a small core bbox at the point
and a larger halo bbox around it, flag `vegetation_stress_detected` when
core is significantly below halo (z-score vs halo stddev). Implemented
in `ndvi_source_mobile.py` and `investigation_multi_mobile.py`
(`CorrelatedCandidate` per DEM candidate — CORROBORATED if real stress
detected, SINGLE_SOURCE otherwise, or a per-candidate `NDVIFetchError`
caught and recorded honestly rather than failing the whole run).

Confirmed working on-device with real credentials: real DEM fetch
(native 32x40 raster resampled to 96x96), real NDVI core/halo values
(core mean=-0.0061 vs halo mean=-0.0021, z=0.00), synthetic=false on
both evidence sources, correctly classified SINGLE_SOURCE.

## Depth estimation (roadmap item 4) — scoped, not built

Detailed scoping already agreed, waiting on GPR hardware purchase:

- `gpr_source_mobile.py` parallel to `dem_source_mobile.py`, ingesting a
  real radargram export from an actual field GPR device (no synthetic
  data).
- Depth via two-way travel time converted using a documented soil-type
  velocity preset table (dry sand/clay/loam etc., user-selected), with
  depth explicitly flagged as an estimate with uncertainty range (mirrors
  the NDVI core/halo approximation-flagging pattern).
- Feature detection: first-pass rule-based peak-amplitude + hyperbola-
  shape heuristic (full ML hyperbola fitting deferred as stretch goal).
- Output as a `GPREvidence` class mirroring `RealNdviCoreHaloEvidence`,
  feeding `build_investigation_record`.
- Field image evidence (separate, doesn't need GPR hardware): geotagged
  photos (EXIF GPS + timestamp) tied to a specific investigation
  candidate for custody/provenance — simple attach-and-display as the
  near-term tier, on-device image analysis (cropmarks/soil discoloration)
  deferred as a separate CV project.
- Debate Engine integration: GPR would be a strong new input to the
  Geomorphology and Anthropogenic/Archaeological perspectives,
  potentially upgrading confidence tiers when GPR confirms a DEM/NDVI-
  flagged candidate.
- **Blocker:** GPR hardware not yet owned. Consumer/prosumer units
  export in very different formats (some proprietary, some simple
  CSV/image dumps) — the actual parser scope depends on which unit is
  eventually bought. Proceeding with the rest of the roadmap in the
  meantime, per user's request.

## Working infrastructure notes

- GitHub is accessed via a connected Zapier GitHub connector (account:
  `drtanghatari-ctrl`). Standard actions (branch/get_file_contents/
  repository_v2/repo_issue/repo_pull/user/create_file/etc.) plus a
  growing set of custom code actions for GitHub Actions visibility (see
  "New tooling" above).
- **For any binary file commit, use `commit_raw_base64_file`, not
  `create_file`.** The latter double-encodes text-ish content and will
  corrupt binaries.
- Recurring past failure mode (now avoided): file uploads/commits
  historically failed silently via drag-and-drop, once resulting in
  placeholder chat text getting committed as real code, once in two
  files' contents getting swapped under the wrong filenames, and now
  once in a keystore binary being stored as literal base64 text.
  Standing practice: commit via API (not drag-and-drop), and re-verify
  file content/size after every commit — never assume a commit "took."

## Resume-here checklist (read this first after any interruption)

1. Check the status of build run #48
   (https://github.com/drtanghatari-ctrl/ariyan-geo-ai-v01/actions/runs/33187315292)
   — use `get_workflow_run_status` with run_id 33187315292, or just
   check the Actions tab.
2. If it succeeded: get the APK artifact, sideload it, run an
   investigation with real DEM + real NDVI enabled at a known location,
   confirm the Debate Engine section renders with real debate JSON
   (4 perspectives, a synthesis with agreement_level + steward_note).
3. If it FAILED again: use `get_workflow_run_jobs` then
   `get_job_log_text` on the failed job to find the new root cause —
   don't assume it's the same keystore issue, verify the actual error.
4. If step 2 confirmed working: mark roadmap item (3) fully complete in
   this file.
5. Then: resume the paused cleanup (delete the two confirmed-stale
   duplicate `investigation_multi_mobile` files; inspect
   `activity_main-2.xml`; investigate/clean up the stray "Python
   Package using Conda" workflow).
6. After that: item (4) depth estimation remains the only open roadmap
   item, blocked on GPR hardware purchase — check in on whether that's
   changed, otherwise no action needed there yet.
