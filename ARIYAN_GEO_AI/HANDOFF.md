ARIYAN GEO AI — Status & Roadmap (updated 2026-09-12, SAR BUILD KICKOFF)
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

SAR (Sentinel-1) — BUILD IN PROGRESS, STARTED THIS SESSION
Live-tested successfully on 2026-09-10 via Termux/curl on the user's phone (no laptop available): a real HTTP POST to the Statistical API with `"type":"sentinel-1-grd"` returned real VV/VH backscatter statistics across real 30-day intervals — genuine live data, calibration/terrain-correction handled server-side, same Copernicus account already in use. Cleared to start building.

DESIGN DECISIONS MADE THIS SESSION (grounded in real published literature, not guessed — see citations below):
1. **Two-directional, never one-directional.** Unlike NDVI's clean one-directional "core-below-halo = stress" rule, published research on SAR over buried archaeological features shows detections going BOTH ways — some black ditches and white complex areas were identified with archaeological potential for buried archaeological remains (Mediterranean palaeo-landscape study) — because backscatter is driven by a mix of soil dielectric/moisture and surface roughness that can push either direction depending on season and ground conditions. SAR is therefore architected exactly like Thermal/Optical (core-vs-halo, either-direction "detected" flag), never like NDVI's single-direction rule.
2. **VV and VH tracked and tested separately, not merged.** The same literature notes VV and VH... helped in discriminating and estimating the different contributions due to moisture content and roughness — collapsing them into one number would throw away real, distinguishable information the two channels separately carry.
3. **Honest scope limitation, stated in code comments and surfaced to the user:** genuinely robust SAR-based detection in the literature typically also draws on coherence and interferometry, which the Statistical API's single-date backscatter stats cannot provide — a 2017 study demonstrates that SAR backscatter intensity, coherence and interferometry can [reveal residues] together, implying intensity alone (what this app can access) is real but weaker evidence than a full SAR pipeline. This is documented in the module docstring so nothing overstates its own confidence.
4. **Evidence slot: ninth** (`ninth_evidence` in `evidence_record.py`), following the same core-vs-halo per-candidate pattern as NDVI/Thermal/Optical (15m core / 60m halo radii, matching existing precedent).

BUILT THIS SESSION: `sar_source_mobile.py` — core/halo two-sample z-test for both VV and VH backscatter, mirroring `thermal_source_mobile.py`/`optical_source_mobile.py`'s structure exactly (shared token caching, hard wall-clock deadline via the same `concurrent.futures` pattern, honest None-for-unknown-variance, sentinel ±50.0 for confident-near-zero-variance cases, `SARFetchError` raised only for true hard failures). NOT yet wired into `evidence_record.py` (ninth slot), `investigation_multi_mobile.py` (per-candidate check runner), or `debate_mobile.py` (`_attach_sar_detail()`), and no UI changes yet in `activity_main.xml`/`MainActivity.kt`. Not yet committed.

NEXT SESSION RESUME POINT: wire `sar_source_mobile.py` through the remaining 3 files + UI, exactly mirroring how Thermal/Optical were wired, then sandbox-test before any on-device test (same discipline used for every other evidence source). After SAR is fully closed: second independent DEM cross-check (queue item 3), then Grand Projects Framework (not yet scoped).

Known bugs
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
1. Roadmap items (1)–(3), (5), plus every evidence source through Temporal Persistence, are ALL closed and on-device confirmed. Nothing there is mid-flight.
2. SAR: `sar_source_mobile.py` is built (this session) but NOT yet wired into `evidence_record.py`/`investigation_multi_mobile.py`/`debate_mobile.py`/UI, and NOT yet committed. Continue the wiring next.
3. After SAR closes: second independent DEM cross-check (e.g. NASADEM via OpenTopography), then Grand Projects Framework (not yet scoped — ask for specifics).
4. Lower-priority, can be picked up any time: delete the 2 stale duplicate files; the intermittent "Candidate null" bug (deprioritized). Do NOT investigate the "Python Package using Conda" workflow.
5. Item (4)'s automated GPR device-export parsing stays parked until GPR hardware is affordable.
