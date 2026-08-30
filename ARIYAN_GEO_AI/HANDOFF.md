# ARIYAN GEO AI — Status & Roadmap (updated 2026-08-30, GPR-INTO-DEBATE CONFIRMED ON-DEVICE)

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

## LATEST MILESTONE: GPR-into-debate CONFIRMED on-device — closes the final GPR integration item (2026-08-30)

This was the last unverified piece of the GPR work. Confirmed today
after several earlier non-informative test runs.

**What was built (this session and prior sessions, now all verified
together):**

- `debate_engine.py` gained `_gpr_confirmation()`: when a real manual
  GPR pick is within a colocation radius (`max(30m, cell_size_m*4)`,
  ~42m at the usual 500m-radius/96-grid settings) of a DEM candidate —
  Geomorphology gets -0.15 confidence (a real subsurface reflector
  weakens a pure-natural-terrain explanation), Anthropogenic/
  Archaeological gets +0.20 (applied *after* any synthetic-NDVI
  confidence cap, so real GPR evidence is never capped by an unrelated
  synthetic-NDVI concern), Data Artifact/Skeptic gets -0.15 (a real
  subsurface hit makes a shared cross-instrument artifact less likely).
  Vegetation/Agronomic is deliberately untouched — GPR isn't
  vegetation-related.
- `debate_mobile.py` haversine-matches the GPR pick's single site-
  anchored (lat, lon) to nearby DEM candidates (GPR is not per-candidate
  like NDVI core/halo, so distant candidates correctly get nothing
  added) and adds a top-level `gpr_note` when the pick wasn't close
  enough to any candidate to be used — an honest "not informative"
  state, never a silent guess.
- A related rendering bug in `MainActivity.kt`'s `appendDebateSection()`
  was fixed at the same time: it was computing each position's
  `reasoning[]` list but never displaying it, which would have made the
  new GPR reasoning text invisible on-device even once the logic
  worked. Reasoning bullets now render under each perspective.
- Verified first in a local Python sandbox test (a synthetic co-located
  candidate correctly flipped from Geomorphology-leading to
  Anthropogenic/Archaeological-leading once GPR confirmation was added;
  a distant candidate was correctly unaffected), then build-confirmed
  green on GitHub Actions (runs #63/#64/#65).

**On-device confirmation (2026-08-30):** several real test runs after
build #65 were non-informative — DEM candidates were detected but the
GPR pick (tied to the investigation's overall center coordinate) landed
just outside the ~42m colocation radius each time. Re-centering an
investigation exactly on a prior candidate's own coordinates also
turned out not to reliably reproduce a candidate there, since the DEM
anomaly detector flags deviation from the *local statistical trend
within that run's own AOI window* — it is not a fixed-feature detector,
so the same real terrain can register differently once the window
shifts. A small nudge (~20m, not a full recenter) finally landed a real
GPR pick within range of a real DEM candidate:

- Center (34.97986, 52.72541) → 2 candidates. GPR pick (loam_dry,
  42.0 ns → depth ≈1.79 m, range 1.47-2.10 m) landed ~43.1 m from
  candidate #1 — 1 m outside the 42m radius. Non-informative but useful:
  confirmed the colocation logic is genuinely working to a ~meter
  tolerance, not just roughly.
- A ~20m nudge to (34.980100, 52.725350) → 3 candidates, one of which
  (lat=34.980194, lon=52.725236) landed within range. **Debate output
  visibly shifted as designed:**
  - Geomorphology [MODERATE]: reasoning explicitly noted the GPR-
    detected subsurface reflector "weakens (but does not rule out) a
    natural-terrain-only explanation."
  - Anthropogenic/Archaeological [MODERATE]: reasoning cited the GPR
    pick as "direct subsurface confirmation... treated as stronger
    independent evidence than surface corroboration alone."
  - Data Artifact/Skeptic: reasoning noted the GPR confirmation "makes
    a shared measurement/processing artifact across unrelated
    instruments (DEM/NDVI and GPR) less likely."
  - Synthesis: **CONTESTED** — Anthropogenic/Archaeological (0.53) vs
    Vegetation/Agronomic (0.50). Geomorphology no longer led once GPR
    confirmation was factored in — exactly the intended effect.
  - Other candidates in the same run, too far from the GPR pick, were
    correctly left unaffected (no GPR mention in their reasoning).

**Status: CLOSED.** GPR-as-third-evidence-source and GPR-into-debate
are both genuinely on-device verified end-to-end, matching this
project's standing practice for every other evidence source.

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
  `debate_mobile.py`. **Done, on-device confirmed** — see LATEST
  MILESTONE above.
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
   Item (4)'s hardware-independent half (manual GPR pick entry,
   GPR-as-evidence-source, GPR-into-debate) is ALSO now done and
   on-device verified as of this write (2026-08-30). Nothing urgent is
   mid-flight. Only automated GPR device-export parsing remains, parked
   on hardware purchase.
2. Two things the user has explicitly said they want to discuss in a
   future session, not yet scoped: (a) some ambitious new ideas for the
   project (unspecified — ask what they have in mind), and (b) a visual
   "decorations"/polish pass (likely related to an earlier-shown
   desktop-GIS mockup, "ARIYAN GEO AI Scientific Geospatial Laboratory",
   with a 3D subsurface model among other polish features, deliberately
   deferred until the technical roadmap was done — which it now
   effectively is). Do not start either without asking for specifics
   first.
3. Lower-priority housekeeping still open, can be picked up any time:
   resume the paused cleanup (delete 2 stale duplicate files —
   `investigation_multi_mobile-1.py` and
   `ARIYAN_GEO_AI/investigation_multi_mobile.py`; inspect
   `activity_main-2.xml`); the intermittent "Candidate null" bug
   (deprioritized, not urgent). Do NOT investigate the "Python Package
   using Conda" workflow — permanently deprioritized per user decision,
   see dedicated section above.
4. Item (4) automated GPR device parsing stays parked until GPR
   hardware is affordable — check in on whether that's changed,
   otherwise no action needed there yet.
