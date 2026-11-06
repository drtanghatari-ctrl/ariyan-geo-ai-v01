ARIYAN GEO AI — Status & Roadmap (updated 2026-11-06)
This file is the durable source of truth for project status. It is updated at the end of every working session so the project state survives even if a chat session or device is interrupted.

What this is
A real, buildable Android Studio project (Chaquopy: native Kotlin UI + embedded CPython) — a scientific geospatial investigation app for archaeology/buried-feature detection, generalizable to geology/engineering/terrain analysis. Built via GitHub Actions cloud builds (no local Android SDK available), producing a downloadable debug APK artifact. Sideloaded onto a physical Android phone (no emulator). A Windows build also exists (`windows/`, workflow `build-windows.yml`).

Hard requirement standing throughout: nothing in the app is synthetic/fake unless explicitly labeled as such on screen; no claiming verification that didn't actually happen.

NOTE ON THIS UPDATE: the previous version of this file (dated 2026-09-12) was stale. Between 2026-09-12 and 2026-11-04 the repo gained about 300 commits: the Grand Projects Framework (database, sync, report, review, refinement, calibration, historical sync, query layer, screen), the SHA-256 provenance ledger and checker, Mission Control, Settings, Overview, Final Image, the Windows build, the offline industrial index, and a Python test workflow. This version reconciles the file with what is in the repo. Items marked "in repo" were confirmed by reading the code and by the Python test suite passing; they were NOT re-confirmed on a device in this session.

Roadmap status
#	Item	Status
1	Multi-source DEM+NDVI correlation	✅ Complete, on-device verified
2	Device GPS integration	✅ Complete, on-device verified
3	Offline rule-based AI Debate Engine (4 perspectives)	✅ Complete, on-device verified
4	Depth estimation	🟡 Partially done — manual GPR/ERT field-pick entry, GPR-as-evidence, GPR-into-debate all built. Automated GPR/ERT device-export parsing deliberately raises NotImplementedError (blocked on hardware purchase).
5	Real Sentinel-2 NDVI via Copernicus	✅ Complete, on-device verified

Evidence sources beyond the original roadmap — all closed
- GPR field-pick evidence (site-anchored, manual entry only — no hardware yet)
- Thermal (Landsat brightness temperature, core/halo, two-directional)
- Optical (Sentinel-2 visible-band "soilmark" brightness, core/halo, two-directional)
- ERT (site-anchored manual resistivity reading)
- SAR (Sentinel-1, VV/VH tracked separately, its own "radar" independence group)
- Detection Stability / DEM window-sensitivity fix (caps Steward confidence when a candidate fails to reproduce)
- Second independent DEM cross-check against COP30 (unconditional LOW cap when tested and not confirmed; never counted as a new evidence source)
- Evidence-independence weighting (diminishing-weight table per measurement-lineage group)
- Temporal persistence for NDVI/Thermal/Optical (softer cap: SUBSTANTIAL→HIGH only)

Offline whole-country data mode — CLOSED
Pre-downloads DEM+NDVI for offline fallback (Iran pilot). Concurrent-download race, silent Google Drive consent failure, and transient network drops were all found on a real device and fixed (atomic lock file, null-Intent handling, narrow automatic retry for transient errors only — never a definitive HTTP status like 404).

Scientific Steward
- Stage 1 (confidence-ceiling engine: evidence hierarchy A–E, alert types, NO_DATA/LOW/MODERATE/HIGH/SUBSTANTIAL bands) — CLOSED.
- Stage 2 (SHA-256 provenance) — DONE in repo, as follows:
  * `provenance_ledger.py` (Phase 4a): append-only, hash-chained ledger of every evidence row, its sources (offline FILE sha256, LIVE response hash, USER_RECORD), and the code bundle that wrote it.
  * `provenance_check.py` (Phase 4b, checker pc-v1): read-only verdict per evidence row / candidate / job, always with reasons. Runs as a step of `auto_pipeline.py` and is shown in the Grand Project screens (`GrandProjectActivity.kt`, `grand_project_report.py`, `grand_project_query_mobile.py`).
  * The checker is READ-ONLY and does NOT change the Steward's band. The Steward runs BEFORE evidence rows exist, so `debate_mobile.py` passes `provenance_verified=False` on purpose. 2026-11-06: the resulting PROVENANCE_WARNING text was reworded to say exactly that (it previously said lineage "cannot currently be verified", which is no longer true) and the stale "not yet built" comments in `debate_mobile.py` were corrected. No logic changed.
  * Optional future work (not started, not needed for honesty): a second Steward pass after evidence rows are written, so the per-candidate warning could show the real verdict.
- Confounders / HIGH ceiling — HELD CLOSED BY DECISION (2026-11-06). `environmental_confounders_controlled` stays hardcoded False. Reaching HIGH requires direct field investigation, which is not available yet, so no candidate can exceed MODERATE (SUBSTANTIAL additionally needs field data). Parts of the earlier "cc-v1" plan exist in the repo (ccf-v1 elevation-robustness checks in `grand_project_refinement.py`; offline OpenStreetMap industrial check in `industrial_index.py`, built by `tools/build_industrial_index.py`) but are NOT connected to the Steward as a gate. Do not wire them up as if they controlled confounders. Revisit only when field investigation exists.

Known bugs
- "Candidate null" intermittent header bug — deprioritized by user, not being worked on, root cause not found.

Cleanup
- DONE: the stale duplicate files (`investigation_multi_mobile-1.py`, the older root duplicate, `activity_main-2.xml`) are gone from the repo.
- DONE: the failing "Python Package using Conda" workflow was deleted and replaced by `python-tests.yml` (runs the repo's own test suite with PYTHONPATH=app/src/main/python:tests).
- Root `README.md` is still just the title — low priority.

GPR hardware status
Unchanged — user does not own GPR hardware, deferred as a future purchase. Manual pick entry is the only real GPR data path.

Deferred items
- LiDAR: no trustworthy Iran-region data source exists. Permanently skipped, not planned.
- Automated GPR/ERT device-export parsing — parked until hardware exists.
- Visual "decorations"/polish pass — partly started (`AriyanDecor.kt` exists); ask for specifics before continuing.
- Scientific Steward Stage 3 (Team A/Team B/Judge contradiction detection) — not started. `has_contradiction` is currently only a proxy (agreement_level == CONTESTED).

Working infrastructure notes
- GitHub is the source of truth. Recurring past failure mode: uploads/commits not taking effect (drag-and-drop overwrites failing silently, truncated text committed as code, files under wrong names). Standing practice: re-verify file content/size after every commit — never assume a commit "took."
- User has no local Android SDK or working ADB, so error handling favors on-screen UI text over log output. Direct downloads from Google-hosted domains are blocked in the user's network environment; GitHub-hosted alternatives are reachable.
- User's phone sometimes restarts mid-session — this file exists so no progress is lost.

Resume-here checklist (read this first after any interruption)
1. Everything on the roadmap except GPR/ERT file parsing is built; Steward Stage 2 (provenance) is done in the repo.
2. Nothing is mid-flight. The 2026-11-06 session changed only: `steward_warnings.py` (warning wording), `debate_mobile.py` (comments only), and this file.
3. HIGH confidence stays unreachable until field investigation exists. Do not hardcode the confounder flag to True.
4. Lower priority, any time: "Candidate null" bug (deprioritized), root README, visual polish (ask first), Stage 3 (ask first).
