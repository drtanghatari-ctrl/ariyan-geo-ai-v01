# ARIYAN GEO AI — Status & Roadmap (updated 2026-08-30, VEGETATION/AGRONOMIC BUG FIXED + ON-DEVICE VERIFIED)

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
| 3 | Offline rule-based AI Debate Engine (4 perspectives) | ✅ **Complete, CONFIRMED on-device with real data, including the Vegetation/Agronomic fix.** All 4 perspectives now render correctly for every candidate, with honest reasoning. No open issues. |
| 4 | Depth estimation | ❌ Not started. Deferred — needs real GPR hardware, which is a future purchase (too expensive right now). Kept on roadmap intentionally, not dropped. |
| 5 | Real Sentinel-2 NDVI via Copernicus | ✅ Complete, on-device verified |

**All roadmap items except (4) depth estimation are now genuinely done
and on-device verified.** Item (4) remains blocked on GPR hardware
purchase.

## LATEST MILESTONE: Vegetation/Agronomic fix CONFIRMED on-device (build #71)

User sideloaded build #71's APK and re-ran a real investigation (real
OpenTopography DEM + real Copernicus NDVI + a real GPR field pick,
screenshots reviewed). Result: **the fix works as designed.**

- **2 candidates detected** across 3 evidence sources, both
  SINGLE_SOURCE (DEM only), confidence LOW as expected — no false
  corroboration claimed.
  - #1: lat=34.981926, lon=57.723699, |z|=3.25, area=13 cells, positive
    polarity. Real NDVI core/halo check: core mean=0.0370 vs halo
    mean=0.0236, z=0.00 — no vegetation stress.
  - #2: lat=34.977700, lon=57.726209, |z|=-2.76, area=12 cells, negative
    polarity. Real NDVI: core mean=0.0452 vs halo mean=0.0324, z=0.00
    — no vegetation stress.
- **All 4 perspectives now render for BOTH candidates**, including
  Vegetation/Agronomic — no longer missing, and no longer wrongly
  claiming "no vegetation evidence present." Correct honest wording
  shown for both: *"NDVI (vegetation) evidence is present for this
  candidate... Vegetation signal is not corroborated by elevation data,
  which is consistent with a vegetation-only cause (e.g. soil moisture,
  crop stress) with no underlying earthwork."* — exactly the intended
  fix behavior (checked-but-no-corroboration, correctly distinguished
  from never-checked).
  - Candidate #1 synthesis: **CONTESTED** — Geomorphology (0.64) vs
    Vegetation/Agronomic (0.50), correctly left unresolved.
  - Candidate #2 synthesis: **LEADING_INTERPRETATION** — Geomorphology
    (0.66), with the steward's usual "ranked heuristic opinion, not
    proof" caveat.
- **GPR:** a real GPR field pick was present for this investigation but
  no DEM candidate was within 42m of the pick location, so it was
  honestly reported as "not applied to any candidate's debate" (the
  `gpr_note` path) rather than silently ignored or falsely applied.
- Confidence-scoring/statistical-behavior notes in the app's own
  "Limitations" section were also visible and correctly worded (e.g.
  the z≥2.5 threshold's expected false-positive rate, NDVI's
  bbox-based "not a true annulus" caveat).

**Roadmap item (3) and the Vegetation/Agronomic bug are both now fully
resolved and on-device confirmed.** No open debate-engine issues remain.

## Bug history: Vegetation/Agronomic "no vegetation evidence present" mislabeling — FULLY RESOLVED (2026-08-30)

**Original symptom:** an earlier on-device run showed only 3 of the 4
declared perspectives — Vegetation/Agronomic did not appear at all for
a SINGLE_SOURCE candidate with real NDVI checked and no stress found.

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
  present for this candidate" — which was **factually wrong**, since
  real Copernicus NDVI data genuinely was fetched and evaluated at that
  exact location. An honest "checked, no signal" finding was mislabeled
  as "not checked at all" — a violation of this project's own
  zero-fake-data / honest-labeling principle, just in the opposite
  direction from what was originally suspected (this was never a
  silent-drop bug; it was a mislabeling bug).

**Fix (commit `85e99a1`, 2026-08-30):** `_build_candidate()` now takes
an explicit `checked_sources` parameter (the investigation-level
`context["sources"]`) and sets `candidate["sources"]` to the
order-preserving union of `supporting_sources` and `checked_sources`,
rather than `supporting_sources` alone. A checked-but-no-signal source
can no longer be silently indistinguishable from an unchecked one.
`run_debate_json()` was updated to pass `context.get("sources")` through
at the call site.

**Rebuilt:** build **#71**, conclusion `success`:
https://github.com/drtanghatari-ctrl/ariyan-geo-ai-v01/actions/runs/33274843173

**Verified on-device (2026-08-30):** see "LATEST MILESTONE" above —
sideloaded, re-run with real DEM+NDVI+GPR, confirmed correct behavior
for 2 independent candidates. Status: **CLOSED.**

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
3. **Vegetation/Agronomic "no vegetation evidence present" mislabeling**
   — see dedicated "Bug history" section above. Fixed in
   `debate_mobile.py` (commit `85e99a1`), rebuilt (build #71), and
   **confirmed on-device** across 2 independent real candidates
   (2026-08-30). Closed.

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
fetch and separately on-device (real Tehran coordinates, then real
northern Iran coordinates in this session's build #71 re-run).

## Real-NDVI path (roadmap item 5)

Copernicus Data Space Ecosystem's Sentinel Hub Statistical API, "core vs
halo" bbox check per DEM candidate (documented approximation, not a
true annulus — the underlying Statistical API is bbox-only). Implemented
in `ndvi_source_mobile.py` + `investigation_multi_mobile.py`. Confirmed
working on-device multiple times now, including the build #71
Vegetation/Agronomic fix re-verification.

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
  Anthropogenic/Archaeological perspectives specifically. Confirmed
  on-device (build #71 re-run) that when no candidate is close enough
  to a real GPR pick, this is honestly reported via `gpr_note` rather
  than silently ignored or misapplied.
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

1. Roadmap items (1), (2), (3), (5) are ALL done and on-device verified
   as of this write — including the Vegetation/Agronomic fix, confirmed
   working across 2 independent real candidates on build #71. Nothing
   urgent is mid-flight. Only item (4) remains, parked on GPR hardware.
2. Next real task: resume the paused cleanup (delete 2 stale duplicate
   files — `investigation_multi_mobile-1.py` and
   `ARIYAN_GEO_AI/investigation_multi_mobile.py`; inspect
   `activity_main-2.xml`). Do NOT investigate the "Python Package using
   Conda" workflow — permanently deprioritized per user decision
   (2026-08-30), see dedicated section above.
3. Item (4) depth estimation stays parked until GPR hardware is
   affordable — check in on whether that's changed, otherwise no action
   needed there yet.
