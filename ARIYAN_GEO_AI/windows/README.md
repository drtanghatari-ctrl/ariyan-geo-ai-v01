# ARIYAN GEO AI for Windows

The desktop version of ARIYAN GEO AI. It runs **the same Python core as the phone**
(`../app/src/main/python`, the very same files), so a candidate gets the same score
on both. Only the screens are new (PySide6 / Qt).

## Plan (approved 2026-11-02)
- **W0** foundation: window, Mission Control read-out, Windows build on GitHub *(this step)*
- **W1** Mission Control workstation (the Windows mock-up, without LiDAR)
- **W2** Send / Receive project between phone and laptop (Google Drive or USB;
  one device works on the project at a time)
- **W3** Final Image (map, layers, cross-section, 3D, subsurface block)
- **W4** investigations, wide-area jobs, Grand Project review, reports
- **W5** installer, user guide, polish

## Install (from GitHub)
Actions -> **Build Windows app** -> newest green run -> download
**ARIYAN-GEO-AI-windows** -> unzip anywhere -> run `ARIYAN GEO AI.exe`.

## Run from source
    cd ARIYAN_GEO_AI/windows
    python -m pip install -r requirements.txt
    python -m ariyan_win

## Data folder
Default `%USERPROFILE%\ARIYAN_GEO_AI\offline_data` (same layout as the phone's
offline_data). Choose another one with **Data folder...**. The choice is kept in
`%APPDATA%\ARIYAN_GEO_AI\settings.json`.

## Self-test
`python -m ariyan_win --selftest` (or `"ARIYAN GEO AI.exe" --selftest`) imports every
core module, builds the window headless and reads Mission Control; the result is
written to `%TEMP%\ariyan_selftest.txt`.
