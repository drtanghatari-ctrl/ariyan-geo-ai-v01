# ariyan-geo-ai-v01

ARIYAN GEO AI: a scientific geospatial investigation tool for detecting possible buried
features (archaeology first; also geology, engineering and terrain analysis). It combines
several independent kinds of evidence (elevation, vegetation, thermal, optical, radar,
and field data such as GPR and ERT you enter yourself) and reports how strong the evidence
is. It never claims a discovery. Nothing in it is synthetic unless labelled on screen.

## What is in this repository
- `ARIYAN_GEO_AI/`: the Android app (Kotlin screens plus an embedded Python core, via Chaquopy).
  `app/src/main/python` is the scientific core, shared with the Windows app.
- `ARIYAN_GEO_AI/windows/`: the Windows desktop app (PySide6). See its
  [README](ARIYAN_GEO_AI/windows/README.md) and [user guide](ARIYAN_GEO_AI/windows/USER_GUIDE.md).
- `ARIYAN_GEO_AI/tests/`: the Python test suite for the core.
- `ARIYAN_GEO_AI/HANDOFF.md`: the project's status and roadmap. Read this first when resuming work.
- `.github/workflows/`: cloud builds and tests.

## Getting the apps
- **Android**: Actions -> **Build APK** -> newest green run -> download the debug APK.
  See `ARIYAN_GEO_AI/GET_APK_NO_INSTALL.md`.
- **Windows**: Actions -> **Build Windows app** -> newest green run -> download
  **ARIYAN-GEO-AI-Setup**.

## Confidence
Confidence is deliberately capped by what the evidence supports. It cannot currently rise
above MODERATE, because higher levels need direct field investigation.
