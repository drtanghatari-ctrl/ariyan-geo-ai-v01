# ARIYAN GEO AI for Windows

The desktop version of ARIYAN GEO AI. It runs **the same Python core as the phone**
(`../app/src/main/python`, the very same files), so a candidate gets the same score
on both. Only the screens are new (PySide6 / Qt).

New to the app? Read the **[user guide](USER_GUIDE.md)**.

## Plan (approved 2026-11-02) and status
- **W0** foundation: window, Mission Control read-out, Windows build on GitHub (done)
- **W1** Mission Control workstation (the Windows mock-up, without LiDAR) (done)
- **W2** Send / Receive project between phone and laptop (Google Drive, folder or USB;
  one device works on the project at a time) (done)
- **W3** Final Image (map, layers, cross-section, 3D, subsurface block) (done)
- **W4** investigations, wide-area jobs, Grand Project review, reports (done)
- **W5** installer (W5a, done), user guide (W5b, done: see `USER_GUIDE.md`); polish was U6

Not done: automatic upload of a project from the phone straight to Google Drive (today the
phone shares a `.ariyan` file and you choose Google Drive in the share menu). The installer
is not signed with a paid certificate.

## Install (from GitHub)
Actions -> **Build Windows app** -> newest green run -> download
**ARIYAN-GEO-AI-Setup** -> unzip -> run `ARIYAN_GEO_AI_Setup_<version>.exe` (win-w5a).
It installs for you only (no administrator rights) in
`%LOCALAPPDATA%\Programs\ARIYAN GEO AI`, with a Start-menu entry, an optional desktop
icon and an uninstaller (Settings > Apps). A newer setup updates the program in place.
Install, upgrade and uninstall never touch the data folder, the settings, the saved
keys or the Google Drive sign-in. Windows may say "Windows protected your PC" (the setup
is not signed with a paid certificate): **More info -> Run anyway**.

Without installing: download **ARIYAN-GEO-AI-windows** instead, unzip anywhere and run
`ARIYAN GEO AI.exe`.

The installer is `installer/ariyan.iss` (Inno Setup 6). CI builds it, installs it
silently, self-tests the installed program, uninstalls it and checks that the data
folder is still there before uploading it.

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
