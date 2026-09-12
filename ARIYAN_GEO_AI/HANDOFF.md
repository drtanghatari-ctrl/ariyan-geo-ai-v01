ARIYAN GEO AI — Status & Roadmap (updated 2026-09-12, SAR + DEM CROSS-CHECK BOTH CLOSED)
This file is the durable source of truth for project status. It is updated at the end of every working session so the project state survives even if a chat session or device is interrupted.

What this is
A real, buildable Android Studio project (Chaquopy: native Kotlin UI + embedded CPython) — a scientific geospatial investigation app for archaeology/buried-feature detection, generalizable to geology/engineering/terrain analysis. Built via GitHub Actions cloud builds (no local Android SDK available), producing a downloadable debug APK artifact. Sideloaded onto a physical Android phone (no emulator).

Hard requirement standing throughout: nothing in the app is synthetic/fake unless explicitly labeled as such on screen; no claiming verification that didn't actually happen.

NOTE ON THIS UPDATE: the previous version of this file (dated 2026-09-02) was significantly stale — a great deal of real work was completed and on-device confirmed between 2026-09-02 and 2026-09-10 that never made it into that snapshot (ERT, DEM window-sensitivity fix, Scientific Steward Stage 1, evidence-independence weighting, temporal persistence). This version reconciles the file with the project's actual current state.

Roadmap status
#	Item	Status
1	Multi-source DEM+NDVI correlation	✅ Complete, on-device verified
2	Device GPS integration	✅ Complete, on-device verified
3	Offline rule-based AI Debate Engine (4 perspectives)	✅ Complete, on-device verified
4	Depth estimation	🟡 Partially done (unchanged) — manual GPR field-pick entry, GPR-as-evidence, GPR-into-debate all built/confirmed. Automated GPR device-export parsing still not started (blocked on GPR hardware purchase).
5	Real Sentinel-2 NDVI via Copernicus	✅ Complete, on-device verified

Evidence sources beyond the original roadmap — all closed
Built up over several sessions past the original 5-item roadmap. All CLOSED and on-device confirmed unless noted:
- GPR field-pick evidence (site-anchored, manual entry only — no hardware yet)
- Thermal (Landsat brightness temperature, core/halo, two-directional)
- Optical (Sentinel-2 visible-band "soilmark" brightness, core/halo, two-directional)
- ERT (site-anchored manual resistivity reading; all 3 reachable lean branches — natural/anthropogenic/ambiguous — confirmed; the "anthropogenic" branch's design gap was resolved by a deliberate band-relabeling decision, permanently closing it barring a future magnetometer source)
- Detection Stability / DEM window-sensitivity fix (borderline candidates automatically re-tested across offset sampling windows; caps Steward confidence when a candidate fails to reproduce)
- Evidence-independence weighting (Steward no longer treats NDVI+Thermal+Optical, which share Sentinel-2/Landsat lineage, as 3 fully independent sources; diminishing-weight table caps any single measurement-lineage group)
- Temporal persistence for NDVI/Thermal/Optical (checks whether a core/halo anomaly reproduces across multiple real acquisition dates, not just one snapshot; feeds a softer Steward cap — SUBSTANTIAL→HIGH only — than Detection Stability's harder cap)
- Scientific Steward Stage 1 (confidence-ceiling engine: evidence hierarchy A–E, 7 alert types, NO_DATA/LOW/MODERATE/HIGH/SUBSTANTIAL bands; `environmental_confounders_controlled` and `provenance_verified` both intentionally hardcoded False pending Stage 2)

Offline whole-country data mode — CLOSED
Pre-downloads DEM+NDVI for offline fallback (Iran pilot). Two real bugs found via on-device testing and fixed:
- Concurrent-download race (screen rotation/backgrounding could spawn two downloads racing on the same temp filenames) — fixed via a per-country atomic lock file (`offline_download_runner.py`) plus PID+UUID unique temp filenames as defense in depth (`offline_data_manager.py`).
- Silent Google Drive consent failure (a null Intent on some consent-flow returns threw an uncaught NullPointerException) — fixed with explicit null-Intent handling and broader exception catching.
- A follow-up real Iran retest surfaced a third, separate issue: genuine DNS-resolution failures and mid-transfer drops during long downloads (consistent with Android Doze/battery-management cutting network mid-run). Fixed with a small, narrowly-scoped automatic retry (`MAX_TRANSIENT_ATTEMPTS = 3`) that only retries genuine transient network errors — never a definitive HTTP status like 404, which stays a real, non-retried outcome.
All three confirmed fixed and working on real device. CLOSED.

SAR (Sentinel-1) — CLOSED, CI GREEN
Live-tested successfully on 2026-09-10 via Termux/curl (real VV/VH backscatter returned). Built and wired this session: `sar_source_mobile.py` (two-directional, VV/VH tracked separately -- grounded in real published Sentinel-1 archaeology literature, not guessed), plus the ninth evidence slot across `evidence_record.py`, `investigation_multi_mobile.py`, `steward_evidence_matrix.py` (SAR gets its OWN "radar" independence group, separate from NDVI/Thermal/Optical's "optical_family"), `steward_engine.py`, and `debate_mobile.py`. All 5 files sandbox-verified (correlation logic, full investigation run, `effective_independent_sources` math, full debate run) before delivery. No Kotlin/XML changes needed -- SAR mirrors Thermal/Optical's automatic no-toggle design. User committed, confirmed CI green. **CLOSED.**

SECOND INDEPENDENT DEM CROSS-CHECK (queue item 4) — CLOSED, ALL FILES SANDBOX-VERIFIED
Cross-validates the elevation VALUE of each DEM candidate against a second, genuinely independent global elevation dataset -- distinct from the closed window-sensitivity fix (which re-tests ONE source across sampling windows, not a second source).

DATASET CHOICE, VERIFIED AGAINST REAL OPENTOPOGRAPHY DOCUMENTATION (corrects an earlier casual assumption): NASADEM was the obvious first guess, but OpenTopography's own dataset documentation confirms NASADEM is explicitly a reprocessing of the SAME underlying SRTM radar acquisitions this project's primary DEM (SRTMGL1) already uses -- cross-checking against it would not be genuinely independent. **COP30 (Copernicus GLO-30)** was chosen instead: derived from the TanDEM-X mission, a different agency (ESA), a different acquisition period (2011-2015 vs. SRTM's 2000 campaign) -- a real independent confirmation. COP30 is also OpenTopography's own current default dataset.

DESIGN DECISION: unlike SAR, this does NOT count as a new independent evidence source -- a second DEM measures the SAME physical quantity (elevation) via a different pipeline, not a different physical mechanism. Follows Detection Stability's/Temporal Persistence's philosophy (no `derived_products` entry, never folds into `correlation()`/`supporting_sources`), not SAR's (no new `INDEPENDENCE_GROUPS` entry). Feeds Scientific Steward as an UNCONDITIONAL cap, mirroring Stability's own priority tier (not Temporal Persistence's softer one) -- a candidate that fails to reproduce in COP30 is not rescued by any amount of other evidence.

FULLY BUILT AND SANDBOX-VERIFIED THIS SESSION: evidence_record.py's tenth slot, `investigation_multi_mobile.py`'s `DemCrossCheckResult`/`_run_dem_cross_check()`/`DemCrossCheckEvidence` (ONE extra COP30 fetch per investigation, reused for every candidate via nearest-match -- much cheaper than Stability's per-candidate multi-offset re-fetch), `debate_mobile.py`'s `_attach_dem_cross_check_detail()`, and -- once the user supplied their real current content -- `steward_confidence_ceiling.py`'s new tri-state `dem_cross_check_confirmed` gate (unconditional LOW cap when False, at the SAME priority tier as `stability_score`, before source count/field validation are ever consulted) and `steward_warnings.py`'s new `DEM_CROSS_CHECK_WARNING` (fires only when the check genuinely ran and did not reproduce -- re-checked directly, no derived "capped" flag needed, since this gate is unconditional and never hidden behind a downstream branch, unlike Temporal Persistence's softer one). `steward_engine.py` threads `dem_cross_check_confirmed` through to both. `debate_mobile.py`'s `_build_steward_report()` now computes the real tri-state value from the attached candidate flags (None when never tested or the second dataset's fetch failed -- never a stale/undefined boolean) and passes it straight through.

Three real end-to-end scenarios sandbox-verified: (1) COP30 mismatch → Steward band correctly capped to LOW with `DEM_CROSS_CHECK_WARNING` present; (2) COP30 confirms → no cap, no warning (informative only); (3) COP30 fetch fails entirely → honestly treated as "not tested," no cap, no warning -- absence of a test is never treated as evidence against a candidate. **CLOSED.**

NEXT UP: Grand Projects Framework (not yet scoped — ask user for specifics before starting).

Known bugsKnown bugsKnown bugs
- "Candidate null" intermittent header bug — deprioritized by user, not being worked on, root cause not found.

Cleanup — paused, not yet done
- `investigation_multi_mobile-1.py` (repo root) and `ARIYAN_GEO_AI/investigation_multi_mobile.py` — confirmed stale/superseded duplicates, safe to delete, not yet deleted.
- `activity_main-2.xml` (repo root) — never inspected.
- Root `README.md` — checked, trivial, low priority.
- "Python Package using Conda" stray workflow — permanently deprioritized per user decision. Do not investigate again.

GPR hardware status
Unchanged — user does not own GPR hardware, deferred as a future purchase, kept on roadmap. Manual pick entry is the only real GPR data path today, fully built and confirmed.

Deferred items (all unchanged, listed for completeness)
- LiDAR: no trustworthy Iran-region data source exists (OpenTopography/USGS 3DEP/NOAA are all US/Canada/Europe-only). Permanently skipped, not planned.
- Scientific Steward Stage 2+ (SHA-256 provenance ledger, real confounder-control detection) — queued after Grand Projects Framework.
- Visual "decorations"/polish pass (desktop-GIS mockup with a 3D subsurface model) — deliberately deferred, ask for specifics before starting.
- Grand Projects Framework (persistent, long-term multi-site investigation environment: Organization→Grand Project→Region→Site→Mission→Investigation Session→Evidence→Observations→Hypotheses→Conclusions→Validation) — not yet scoped, comes after SAR + second DEM cross-check.

Tooling available (custom Zapier/GitHub code actions)
list_workflow_runs, get_workflow_run_status, get_workflow_run_jobs, get_job_log_text, trigger_build_apk_workflow — CI visibility/control.
commit_raw_base64_file — reliable way to commit binary files.
commit_text_file — reliable way to commit plain-text files; handles base64 encoding automatically.
get_file_text, get_file_text_grep, list_dir, delete_file, find_commits_touching_path — reliable reads/deletes/history search.

Working infrastructure notes
- GitHub accessed via a connected Zapier GitHub connector (account: drtanghatari-ctrl). Zapier connector periodically hits its task limit — fallback is pasting current file contents into chat for a full replacement.
- Recurring past failure mode: file uploads/commits have repeatedly not taken effect as expected (drag-and-drop overwrites failing silently, placeholder/truncated text committed as code, files swapped under wrong names). Standing practice: commit via the custom code actions above, re-verify file content/size after every commit — never assume a commit "took."
- User has no local Android SDK or working ADB (root unavailable, ADB grant blocked by sanctions in their network environment) — no logcat debugging available; error handling favors on-screen UI text over log output. Direct downloads from Google-hosted domains are blocked in the user's network environment; GitHub-hosted alternatives are reachable.
- User's phone spontaneously restarts sometimes mid-session — this file and chat memory both exist specifically so no progress is ever lost to that.

Resume-here checklist (read this first after any interruption)
1. Roadmap items (1)–(3), (5), plus every evidence source through SAR, are ALL closed and on-device/CI confirmed. Nothing there is mid-flight.
2. Second independent DEM cross-check (queue item 4) is fully CLOSED and sandbox-verified end-to-end, including the Steward-side cap and warning.
3. Grand Projects Framework is next (not yet scoped — ask user for specifics before starting).
4. Lower-priority, can be picked up any time: delete the 2 stale duplicate files; the intermittent "Candidate null" bug (deprioritized). Do NOT investigate the "Python Package using Conda" workflow.
5. Item (4) [roadmap]'s automated GPR device-export parsing stays parked until GPR hardware is affordable.
