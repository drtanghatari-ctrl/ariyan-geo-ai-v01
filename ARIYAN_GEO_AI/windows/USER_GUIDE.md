# ARIYAN GEO AI for Windows: user guide

ARIYAN is a scientific tool that looks for features that may be buried (archaeology first, but also geology and terrain work) by comparing several independent kinds of satellite and field evidence. It reports **how strong the evidence is, never that something has been found**. A candidate is a place worth a closer look, not a discovery.

The Windows app runs the same scoring code as the phone, so a candidate gets the same score on both.

## 1. Install
1. On GitHub open **Actions → Build Windows app**, pick the newest green run, and download **ARIYAN-GEO-AI-Setup**.
2. Unzip it and run `ARIYAN_GEO_AI_Setup_<version>.exe`. It installs for your Windows account only (no administrator rights needed).
3. Windows may say "Windows protected your PC", because the setup is not signed with a paid certificate. Choose **More info → Run anyway**.

Installing, updating or uninstalling never touches your data folder, your settings, your saved keys or your Google Drive sign-in.

If you prefer not to install, download **ARIYAN-GEO-AI-windows** instead, unzip it anywhere and run `ARIYAN GEO AI.exe`.

## 2. First start
1. Press **Settings** (bottom bar) and enter your keys:
   - **OpenTopography API key** (elevation data)
   - **Copernicus client ID** and **client secret** (Sentinel satellite data)

   Keys are encrypted for your Windows account. Leave a box empty to keep the stored value. **Remove all keys** deletes them.
2. Press **Data folder…** if you want the data somewhere other than the default, `%USERPROFILE%\ARIYAN_GEO_AI\offline_data`. **Open data folder** shows it in Explorer.

## 3. The pages (tabs)
- **MISSION CONTROL**: the overview. Search for a place or coordinates, see candidates, download the terrain tile, open a candidate's Final Image or the Evidence Volume. The Steward banner here suggests the next step.
- **INVESTIGATION**: two sub-tabs. *Single point* runs one investigation at a coordinate. *Wide-area jobs* scans a larger area in tiles (full evidence, DEM-only, offline first, retry failed tiles, or an automatic run that does the whole chain).
- **DATA & EVIDENCE**: which terrain and satellite data you have, and which tiles are missing (it can download them).
- **AI DEBATE STUDIO**: the four-perspective debate for each candidate.
- **VISUALIZATION**: map, layers, cross-section and 3D views.
- **GRAND PROJECT**: the long-term project record: dashboard and jobs, candidates and groups, hypotheses you state yourself, single points, timeline and calibration.
- **HISTORICAL RESEARCH**: search historical sources for a place or event (English or Persian), save findings, and start a wide-area job around a saved finding.
- **ANALYSIS & MODELS** and **REPORT & ARCHIVE**: review results and write reports.

## 4. A typical workflow
1. Mission Control: search a place or paste "latitude, longitude" (for example from Google Maps).
2. Investigation: run a single point, or create a wide-area job (**New job…**, **Look up the place**).
3. Review candidates on Mission Control, Grand Project or Report & Archive. Select one and open its **Final Image**.
4. Write your own hypotheses in Grand Project if you want them on record.
5. **Generate Report** (HTML, CSV and PDF with the satellite layers) or **Export Results** (CSV and GeoJSON).

## 5. The Final Image
Opens for one candidate with these tabs: *Overview*, *Contour & Surface*, *Profile & Section*, *3D Visualization* and *Evidence Volume*. You can fetch Copernicus data for it, draw a profile line or a footprint hypothesis, import ERT or GPR survey data you collected, and export images (PNG and GeoTIFF with provenance) and profiles (PNG and CSV).

## 6. How to read the confidence
Confidence is limited by what the evidence can support:
- Evidence sources that share the same satellite lineage (vegetation, thermal, optical) count as less than fully independent.
- A candidate that does not reproduce when the data is re-sampled, or that is not confirmed in a second independent elevation dataset, is capped low.
- **The app currently cannot rise above MODERATE.** Higher levels need environmental confounders controlled and field data (GPR/ERT), which requires direct field investigation. This is by design, not a fault.
- Each candidate also shows a provenance check (SHA-256) saying whether the data and code behind each piece of evidence are traceable and unchanged. It does not raise confidence.

## 7. Moving a project between phone and laptop
Only one device should work on a project at a time.
- **Send to phone**: choose a folder (your Google Drive folder or a USB stick). It makes one `.ariyan` file. On the phone use Settings → Receive project from laptop.
- **Receive from phone**: choose the `.ariyan` file the phone made. Your current project is first kept as a safety copy in `db_backups`.
- **Google Drive** button: sign in with Google, upload the project to Drive › ARIYAN GEO AI, or download and receive a bundle from there. The app can only see files it put there itself. A bundle from the phone's own Drive app must be picked with **Receive from phone**.

## 8. Backups and troubleshooting
- A daily backup of the project database is kept. **Settings** lists them and lets you delete the ones marked "safe to delete".
- **Refresh** (bottom bar) re-reads the project from the database.
- Self-test: run `"ARIYAN GEO AI.exe" --selftest`. The result is written to `%TEMP%\ariyan_selftest.txt`.
- If a download stops, run it again; temporary network failures are retried automatically, but a definitive error (such as "not found") is reported, not hidden.
