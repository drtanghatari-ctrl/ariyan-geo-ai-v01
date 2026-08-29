# ARIYAN GEO AI — Status & Roadmap (updated 2026-08-30, BUILD #71 GREEN, AWAITING ON-DEVICE RE-VERIFICATION)

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
| 3 | Offline rule-based AI Debate Engine (4 perspectives) | ✅ **Complete, CONFIRMED on-device with real data.** Vegetation/Agronomic mislabeling bug fixed in source (2026-08-30, commit `85e99a1`) and rebuilt (build #71, green) — APK artifact ready; sideload + on-device re-run still pending. See "Known issue" section. |
| 4 | Depth estimation | ❌ Not started. Deferred — needs real GPR hardware, which is a future purchase (too expensive right now). Kept on roadmap intentionally, not dropped. |
| 5 | Real Sentinel-2 NDVI via Copernicus | ✅ Complete, on-device verified |

**All roadmap items except (4) depth estimation are now genuinely done
and on-device verified.** Item (4) remains blocked on GPR hardware
purchase.

## LATEST MILESTONE: Debate Engine confirmed on-device with real data

User ran a real investigation on the compiled app (screenshots
reviewed) with real OpenTopography DEM + real Copernicus NDVI both
enabled:

- **DEM:** OpenTopography SRTMGL1, live fetch, AAIGrid decoded without
  GDAL/rasterio, native 32x40 raster resampled to 96x96. 1 candidate
  found: lat=35.742615, lon=51.410988, |z|=-2.56, area=5 cells,
  negative polarity.
- **NDVI:** real Copernicus Sentinel-2 core/halo check at that
  candidate — core mean=0.0791 vs halo mean=-0.0149, z=0.00, no
  significant vegetation stress. Correlation: SINGLE_SOURCE, confidence
  LOW (expected — no corroboration found).
- **Debate Engine — rendered real content on-device:**
  - Geomorphology [MODERATE]: natural landform / terrain variation
  - Anthropogenic/Archaeological [LOW]: possible constructed /
    human-modified feature
  - Data Artifact/Skeptic [MODERATE]: possible measurement noise /
    processing artifact, not a real feature
  - Synthesis: **CONTESTED** — 'Geomorphology' (0.63) and 'Data
    Artifact/Skeptic' (0.53) are close in confidence; correctly treated
    as genuinely ambiguous, not resolved (per the engine's own
    never-declare-a-winner design).

**Roadmap item (3) is now genuinely complete** — not just schema-mapped
or byte-verified on GitHub, but confirmed rendering real debate output
from real evidence on the actual compiled APK.

## Known issue — FIXED IN SOURCE + REBUILT (2026-08-30), on-device re-verification still pending

**Original symptom:** the on-device debate output above showed only
**3 of the 4** declared perspectives. Vegetation/Agronomic did not
appear at all.

**Root cause found by tracing the full chain (`debate_mobile.py` →
`debate_engine.py` → `MainActivity.kt`):**

- `MainActivity.kt`'s `appendDebateSection()` was confirmed innocent —
  it unconditionally renders every entry in the `positions[]` array,
  including any marked `insufficient_data`, labeled `[insufficient
  data]`. It never filters or drops anything.
- `debate_engine.py`'s `_PERSPECTIVES` tuple always calls all 4
  perspective functions, so `run_debate()` always returns exactly 4
  `Position` objects. It cannot silently omit one either.
- The actual bug was in `debate_mobile.py`'s `_build_candidate()`: for
  a `SINGLE_SOURCE` correlation entry, `correlation_entry["supporting_
  sources"]` only lists the source that *positively detected* the
  anomaly (e.g. `["DEM"]`) — it does NOT include a source like NDVI
  that was genuinely checked at that exact candidate location but
  simply found no corroborating signal. This narrower list was written
  straight into `candidate["sources"]`, which then **overwrote/shadowed**
  the correct, broader investigation-level list (`context["sources"]`,
  which correctly included `"NDVI"`) inside `debate_engine.py`'s
  `_sources_present()` — that function returns the candidate-level list
  the moment it's non-empty, never falling back to context.
- Net effect: `_vegetation_position()` saw `sources = ["DEM"]`,
  concluded `"NDVI" not in sources`, and returned an honestly-labeled
  `insufficient_data` position with stance "no vegetation evidence
  present for this candidate" — which was **factually wrong** for this
  candidate, since real Copernicus NDVI data genuinely was fetched and
  evaluated at that exact location. An honest "checked, no signal"
  finding was mislabeled as "not checked at all" — a violation of this
  project's own zero-fake-data / honest-labeling principle, just in the
  opposite direction from what was originally suspected (this was never
  a silent-drop bug; it was a mislabeling bug).

**Fix applied (commit `85e99a1`, 2026-08-30):** `_build_candidate()` now
takes an explicit `checked_sources` parameter (the investigation-level
`context["sources"]`) and sets `candidate["sources"]` to the
order-preserving union of `supporting_sources` and `checked_sources`,
rather than `supporting_sources` alone. A checked-but-no-signal source
can no longer be silently indistinguishable from an unchecked one.
`run_debate_json()` was updated to pass `context.get("sources")` through
at the call site.

**Rebuilt (2026-08-30):** build **#71** dispatched off the fix commit,
completed with conclusion `success`, and produced a fresh debug APK
artifact (`ariyan-geo-ai-debug-apk`, ~35.8 MB):
https://github.com/drtanghatari-ctrl/ariyan-geo-ai-v01/actions/runs/33274843173

**Still pending — on-device re-verification:** the fix and rebuild are
both done, but nobody has sideloaded run #71's APK onto the physical
phone yet or re-run a real investigation against it. Next session (or
later this session): sideload it, re-run the same/a similar
investigation (real DEM + real NDVI, single DEM candidate, no
vegetation stress), and confirm the on-device output now shows
Vegetation/Agronomic as `[insufficient data]: NDVI evidence checked for
this candidate but showed no significant stress signal` (or similar
honest wording) — NOT the old "no vegetation evidence present" stance,
and NOT absent from the list. Do not mark roadmap item (3) or this bug
as fully resolved until that on-device confirmation actually happens.

## Previous session: build was failing, root cause found and fixed

User reported "Actions got red." Investigation found:

- The **"Build debug APK"** Gradle step was failing, not setup.
- Root cause: `ARIYAN_GEO_AI/app/debug.keystore` was corrupted — its
  raw repo bytes were literally the ASCII text of the keystore's base64
  encoding, not the actual decoded binary (proof: Gradle error
  `KeytoolException: ... toDerInputStream rejects tag type 77` — 77 is
  the decimal ASCII code for 'M', the first character of that base64
  text).
- This happened via a file-upload path that base64-encoded already-
  base64 content a second time without ever decoding to real binary —
  another instance of the general "file uploads/commits don't take
  effect as expected" failure mode already known for this repo.
- **Fix:** the standard `create_file` GitHub action does NOT reliably
  accept raw/data-URI binary content — a `data:...;base64,` prefix just
  got stored as more literal text on the first attempt. The reliable
  fix was writing a custom Zapier code action (`commit_raw_base64_file`)
  that calls GitHub's Contents API PUT endpoint directly, passing the
  base64 string verbatim with no re-encoding. Produced a file of
  correct byte size (2666 bytes) for the first time.
- Build run #47 (triggered by the fix commit) came back fully green —
  every step including "Build debug APK" and "Upload APK artifact"
  succeeded: https://github.com/drtanghatari-ctrl/ariyan-geo-ai-v01/actions/runs/33187295956

## Tooling now available (custom Zapier/GitHub code actions)

- `list_workflow_runs` (owner, repo, per_page) — lists recent workflow
  runs with id/status/conclusion/branch/commit.
- `get_workflow_run_status` (run_id) — quick status/conclusion check;
  also returns `artifacts[]` (id, name, size_in_bytes, download URL)
  once a run has completed.
- `get_workflow_run_jobs` (run_id) — per-job, per-step status.
- `get_job_log_text` (job_id) — fetches the actual error log text.
- `trigger_build_apk_workflow` (no params) — dispatches build-apk.yml
  on main directly via workflow_dispatch, without needing a commit.
- `commit_raw_base64_file` (owner, repo, path, branch, message,
  content_base64, sha?) — **the reliable way to commit binary files.
  Use this instead of `create_file` for any non-text file going
  forward.**
- `commit_text_file` (path, branch, message, content_text, sha?) — the
  reliable way to commit plain-text files (like this one); handles
  base64 encoding automatically.
- `find_commits_touching_path` (path_query) — code-search + commit
  history for a filename fragment; used this session to locate
  `debate_mobile.py`/`debate_engine.py`/`MainActivity.kt` without
  knowing their exact repo paths.
- `get_file_text` (path) — fetch a text file's full decoded content
  directly (no manual base64 decoding needed).
- `get_file_text_grep` (path, pattern) — fetch a text file plus grep-
  style matches with surrounding context; useful for large files.

## Stray "Python Package using Conda" workflow — permanently deprioritized (2026-08-30)

A second workflow named **"Python Package using Conda"** exists in
`.github/workflows/` (origin unknown, not intentionally added) and
fails on every push (`EnvironmentFileNotFound` — references a
non-existent `environment.yml`). It does **not** block the real APK
build and is unrelated to the actual Chaquopy/Kotlin+Python build path.

**User decision (2026-08-30): permanently ignore this. Do not
investigate, fix, or flag it again in future sessions.** It had
required reauthorizing the Zapier GitHub connection with "Contents:
Read and write" permission to delete/fix — user declined to pursue
this, since the workflow is cosmetic noise only (fails independently,
no functional impact).

## Known bugs — fixed and verified

1. **Degenerate DEM candidate** (area=0, |z|=NaN, empty polarity) —
   fixed in `evidence_record.py` + `investigation_multi_mobile.py`.
2. **APK reinstall signature mismatch / corrupted keystore** — now
   properly fixed with real binary keystore content (see above);
   confirmed via a fully green build.

## Known bugs — fixed in source + rebuilt, awaiting on-device re-verification

3. **Vegetation/Agronomic "no vegetation evidence present" mislabeling**
   — see "Known issue" section above. Fixed in `debate_mobile.py`
   (commit `85e99a1`, 2026-08-30); rebuilt cleanly as build #71
   (green, APK artifact ready). Not yet sideloaded/re-run on a physical
   device.

## Cleanup — paused, not yet done

- `investigation_multi_mobile-1.py` (repo root) and
  `ARIYAN_GEO_AI/investigation_multi_mobile.py` — confirmed stale/
  superseded duplicates, safe to delete, not yet deleted.
- `activity_main-2.xml` (10113 bytes, repo root) — never inspected.
- Root `README.md` — checked, trivial, low priority.

(Stray "Python Package using Conda" workflow removed from this list —
see dedicated section above; permanently deprioritized, not part of
cleanup scope.)

## Real-DEM path (roadmap item 1 foundation)

`dem_source_mobile.py` + `ascii_grid.py` fetch/parse OpenTopography's
plain-text AAIGrid format (pure NumPy, no GDAL/rasterio — GDAL confirmed
unbuildable via Chaquopy, chaquo/chaquopy#427). `np_ops.resample_bilinear`
handles non-square real rasters. Verified against a real Silbury Hill
fetch and separately on-device (this session: real Tehran coordinates).

## Real-NDVI path (roadmap item 5)

Copernicus Data Space Ecosystem's Sentinel Hub Statistical API, "core vs
halo" bbox check per DEM candidate (documented approximation, not a
true annulus — the underlying Statistical API is bbox-only). Implemented
in `ndvi_source_mobile.py` + `investigation_multi_mobile.py`. Confirmed
working on-device multiple times now, including this session.

## Depth estimation (roadmap item 4) — scoped, not built

- `gpr_source_mobile.py` parallel to `dem_source_mobile.py`, ingesting a
  real radargram export from an actual field GPR device (no synthetic
  data).
- Depth via two-way travel time + soil-type velocity preset table,
  explicitly flagged as an estimate with uncertainty range.
- Feature detection: first-pass rule-based peak-amplitude + hyperbola-
  shape heuristic (full ML deferred as stretch goal).
- `GPREvidence` class mirroring `RealNdviCoreHaloEvidence`.
- Field image evidence (separate, doesn't need GPR): geotagged photos
  (EXIF GPS + timestamp) for custody/provenance — near-term tier is
  simple attach-and-display.
- Debate Engine integration: GPR would strengthen Geomorphology and
  Anthropogenic/Archaeological perspectives specifically.
- **Blocker:** GPR hardware not yet owned — future purchase, format
  depends on which unit is eventually bought. Proceeding with the rest
  of the roadmap meanwhile, per user's request.

## Working infrastructure notes

- GitHub accessed via a connected Zapier GitHub connector (account:
  `drtanghatari-ctrl`).
- **For any binary file commit, use `commit_raw_base64_file`, not
  `create_file`.** The latter double-encodes text-ish content and will
  corrupt binaries. For plain-text files, `commit_text_file` is the
  reliable option.
- Recurring past failure mode: file uploads/commits have repeatedly not
  taken effect as expected across sessions (drag-and-drop overwrites
  failing silently, placeholder text committed as code, files swapped
  under wrong names, and now a keystore stored as literal base64 text).
  Standing practice: commit via API, re-verify file content/size after
  every commit — never assume a commit "took."

## Resume-here checklist (read this first after any interruption)

1. Roadmap items (1), (2), (5) are done and on-device verified. Item
   (3) the Debate Engine is functionally complete; its
   Vegetation/Agronomic mislabeling bug was fixed in source (2026-08-30,
   commit `85e99a1`) AND rebuilt (build #71, green, APK artifact ready)
   — **but nobody has sideloaded it or re-run a real investigation on
   the new build yet.** Item (4) stays parked (see below).
2. Next real task: sideload build #71's APK
   (https://github.com/drtanghatari-ctrl/ariyan-geo-ai-v01/actions/runs/33274843173)
   onto the physical phone, then re-run a real investigation (real DEM
   + real NDVI, a candidate with no vegetation stress) to confirm
   Vegetation/Agronomic now renders an honest "NDVI checked, no signal"
   position rather than either the old wrong "no vegetation evidence
   present" stance or being absent. Only mark this fully resolved once
   that on-device confirmation actually happens.
3. After that: resume paused cleanup (delete 2 stale duplicate files;
   inspect `activity_main-2.xml`). Do NOT investigate the "Python
   Package using Conda" workflow — permanently deprioritized per user
   decision (2026-08-30), see dedicated section above.
4. Item (4) depth estimation stays parked until GPR hardware is
   affordable — check in on whether that's changed, otherwise no action
   needed there yet.
