# ARIYAN GEO AI — Status & Roadmap (updated 2026-08-28, DEBATE ENGINE CONFIRMED)

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
| 3 | Offline rule-based AI Debate Engine (4 perspectives) | ✅ **Complete, CONFIRMED on-device with real data** (see below). One anomaly flagged, not yet resolved — see "Known issue" section. |
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

## Known issue — not yet resolved

The on-device debate output showed only **3 of the 4** declared
perspectives. **Vegetation/Agronomic was missing entirely** from the
rendered output — not shown, not even flagged as `insufficient_data`
the way a thin-data perspective normally would be.

Suspected cause: `debate_mobile.py` may be silently dropping the
Vegetation/Agronomic perspective specifically when NDVI shows no stress
/ correlation is SINGLE_SOURCE, rather than including it honestly with
a "no signal detected" stance like the other perspectives do under thin
data. Needs investigation: check `debate_mobile.py`'s perspective-
inclusion/filtering logic against what `debate_engine.py` actually
produces — confirm whether this is a real bug (perspective silently
dropped) or intentional design (perspective omitted on purpose when its
underlying evidence type is absent) that should at least be labeled
honestly in the output either way, per this project's zero-fake-data
principle.

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
- `get_workflow_run_status` (run_id) — quick status/conclusion check.
- `get_workflow_run_jobs` (run_id) — per-job, per-step status.
- `get_job_log_text` (job_id) — fetches the actual error log text.
- `trigger_build_apk_workflow` (no params) — dispatches build-apk.yml
  on main directly via workflow_dispatch, without needing a commit.
- `commit_raw_base64_file` (owner, repo, path, branch, message,
  content_base64, sha?) — **the reliable way to commit binary files.
  Use this instead of `create_file` for any non-text file going
  forward.**

## Also discovered, not yet investigated

A second workflow named **"Python Package using Conda"** exists in
`.github/workflows/` (origin unknown, not intentionally added) and
fails on every push. Doesn't block the real APK build, but worth
cleaning up or investigating.

## Known bugs — fixed and verified

1. **Degenerate DEM candidate** (area=0, |z|=NaN, empty polarity) —
   fixed in `evidence_record.py` + `investigation_multi_mobile.py`.
2. **APK reinstall signature mismatch / corrupted keystore** — now
   properly fixed with real binary keystore content (see above);
   confirmed via a fully green build.

## Cleanup — paused, not yet done

- `investigation_multi_mobile-1.py` (repo root) and
  `ARIYAN_GEO_AI/investigation_multi_mobile.py` — confirmed stale/
  superseded duplicates, safe to delete, not yet deleted.
- `activity_main-2.xml` (10113 bytes, repo root) — never inspected.
- Root `README.md` — checked, trivial, low priority.
- Stray "Python Package using Conda" workflow — not yet investigated.

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
  corrupt binaries.
- Recurring past failure mode: file uploads/commits have repeatedly not
  taken effect as expected across sessions (drag-and-drop overwrites
  failing silently, placeholder text committed as code, files swapped
  under wrong names, and now a keystore stored as literal base64 text).
  Standing practice: commit via API, re-verify file content/size after
  every commit — never assume a commit "took."

## Resume-here checklist (read this first after any interruption)

1. All roadmap items except (4) are done and on-device verified as of
   this write. Nothing urgent is mid-flight.
2. Next real task: investigate the missing Vegetation/Agronomic
   perspective in the debate output (see "Known issue" above) — read
   `debate_mobile.py`'s perspective-filtering logic and compare against
   `debate_engine.py`'s actual output for a candidate with no NDVI
   stress detected.
3. After that: resume paused cleanup (delete 2 stale duplicate files;
   inspect `activity_main-2.xml`; investigate the stray "Python Package
   using Conda" workflow).
4. Item (4) depth estimation stays parked until GPR hardware is
   affordable — check in on whether that's changed, otherwise no action
   needed there yet.
