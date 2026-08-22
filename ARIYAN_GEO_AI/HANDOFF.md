# ARIYAN GEO AI — Android vertical slice, build handoff

## What this is

A real, buildable Android Studio project (Chaquopy: native Kotlin UI +
embedded CPython) wired to the actual verified `ariyan_core` Python
pipeline — not a mockup, not simulated tool output. The Kotlin
`MainActivity` calls `investigation_mobile.run_investigation_json()`
directly through Chaquopy and renders the real returned evidence record.

## What it does right now

GPS coordinate (typed in) → AOI → **two DEM sources**:
1. **Synthetic** (default) — offline, no network, every result labeled synthetic on screen.
2. **Real** (opt-in switch) — a live OpenTopography fetch via `dem_source_mobile.OpenTopographyAAIGridSource`.

→ SciPy-free anomaly detection (`np_ops.py` + `anomaly_detection_mobile.py`) → evidence
record JSON → rendered in the UI (confidence statement, candidate list,
limitations).

## The real-DEM path — what was actually solved, and what's still open

The obvious approach (reuse `dem_source.py`'s existing
`OpenTopographyDEMSource`) would have silently failed on Android: it
decodes GeoTIFF via `rasterio`, which needs GDAL's native C++ code, and
**Chaquopy cannot compile native code** — confirmed by a real, documented
build failure other developers have hit (chaquo/chaquopy#427: "Chaquopy
cannot compile native code" attempting to install GDAL).

Instead, `dem_source_mobile.py` requests OpenTopography's plain-text
**AAIGrid** output and decodes it with a new pure-NumPy parser
(`ascii_grid.py`) — no native dependency at all. A second real issue
this surfaced: OpenTopography's returned raster is generally NOT square
(`ncols != nrows`), because SRTM-family datasets are gridded in
arc-seconds, which aren't square in degrees away from the equator, even
though the requested AOI is square in meters. The rest of the pipeline
assumes a single square `grid_size` for both axes, so
`dem_source_mobile.py` resamples the real raster onto that square grid
via a new bilinear resampler (`np_ops.resample_bilinear`) before
returning it — a stated, tested step, not a hidden one.

**What's verified (49 tests, all passing, including a real-data regression against Silbury Hill — see below):** AAIGrid parsing against a
hand-built fixture (including malformed-input rejection), the resampler
against known analytic functions (constant fields, linear ramps,
edge-clamping behavior), and the full HTTP error surface — timeouts,
401, 429, other HTTP errors, malformed bodies, NODATA cells — all mocked
with `unittest.mock` since this build environment has no outbound
network access.

**What's NOT verified:** an actual live call against a real
OpenTopography server — no wait, this IS now verified. On 2026-08-21,
the person building this app fetched real OpenTopography data for
Silbury Hill (lat 51.4155, lon -1.8577 — a real, documented ~30-40m
Neolithic mound) using their own API key, and that response is now a
permanent regression fixture: `tests/fixtures/silbury_hill_real_aaigrid.asc`
+ `tests/test_real_dem_regression.py`. That test confirms the real
raster's actual non-square shape (40 rows x 54 cols) parses and
resamples correctly, and that the anomaly detector correctly flags a
positive-relief anomaly within 100m of Silbury Hill's real coordinates
— not a mock, real fetched data run through the exact same code path
the app uses. Run it with:
```bash
PYTHONPATH=app/src/main/python python3 -m unittest discover -s tests -v
```
(49 tests total, all passing.) `verify_real_dem.py` is still there for
checking *other* sites/datasets on demand, but the core claim — "this
pipeline works on real OpenTopography data" — is now demonstrated, not
just logic-checked.

**In the app:** a "Use real OpenTopography DEM" switch reveals an API
key field (held only in memory this session, never written to disk)
and a dataset field (default `SRTMGL1`). Network errors, bad keys, rate
limits, and NODATA locations (e.g. ocean) all surface as a readable
message in the UI rather than a crash or a silent wrong answer.
`android.permission.INTERNET` is declared in the manifest for this.

## A real bug found and fixed during this session

`investigation_mobile.py` → `evidence_record.py` was importing
`AnomalyCandidate` from `anomaly_detection.py` (the SciPy version) purely
for a type hint. Because `evidence_record.py` sits on the "mobile" import
path, this would have pulled a hard SciPy dependency into the Android
build despite the whole point of `np_ops.py`/`anomaly_detection_mobile.py`
being to avoid that. Verified with a simulated "no scipy" import
environment: failed before the fix, passes after. Changed the import to
`anomaly_detection_mobile.AnomalyCandidate` (same fields, no SciPy).
All 19 existing tests still pass; the desktop SciPy path
(`investigation.py`) is untouched and still uses the real `scipy.ndimage`
implementation.

## Project layout

- `app/src/main/python/` — the ariyan_core v2 modules (mobile-safe ones
  actively used: `coordinate.py`, `dem_source.py`, `np_ops.py`,
  `anomaly_detection_mobile.py`, `evidence_record.py`,
  `investigation_mobile.py`, `correlation.py`, `imagery_source.py`).
  Desktop-only reference modules (`anomaly_detection.py`, `visualize.py`,
  `investigation.py`, `terrain_derivatives.py`) are also included for
  parity with the cumulative project but are **not** imported by the
  Android app and cannot run on-device (they need SciPy/Matplotlib).
- `app/src/main/java/com/ariyan/geoai/AriyanApplication.kt` — starts the
  Chaquopy Python runtime once per process.
- `app/src/main/java/com/ariyan/geoai/MainActivity.kt` — the entire UI:
  lat/lon/radius/grid inputs, a Run button, and a results view. Python
  calls happen on `Dispatchers.Default`, never on the main thread.
- `app/build.gradle.kts` — Chaquopy `pip { install("numpy") }` only, on
  purpose. See the comment there before adding scipy/matplotlib back.

## How to build (on your machine — this sandbox has no Android SDK/NDK
or network access, so none of this was compiled here)

1. Open the extracted `ARIYAN_GEO_AI/` folder directly in Android Studio
   (Hedgehog/2023.1 or newer). It will offer to create the Gradle
   wrapper jar automatically on first sync — accept that, or run
   `gradle wrapper` yourself once if you have a local Gradle install.
2. Let Gradle sync. First sync will download the Chaquopy Python 3.10
   build + the Android numpy wheel from Chaquopy's Maven repo — this
   needs network access once.
3. Run on a device or emulator (arm64-v8a recommended; x86_64 emulator
   images work too if you add that ABI back into `abiFilters`).
4. Tap "Run Investigation" with the default coordinates — you should see
   a confidence statement and a candidate list appear within a second or
   two.

## Honest state / what's NOT done

- The real-DEM path's fetch/parse/resample/detect logic is now
  verified against an actual live OpenTopography fetch (Silbury Hill,
  see above and `tests/test_real_dem_regression.py`) — the one
  significant gap from the previous increment is closed. What's NOT
  yet tested live: other datasets (`COP30`, `NASADEM`, etc. — only
  `SRTMGL1` has been fetched for real so far), other kinds of terrain
  (Silbury Hill is one large, obvious mound — a real device test at a
  flatter or more ambiguous site hasn't happened yet), and the actual
  Android/Chaquopy network stack specifically (the real fetch so far
  was via a browser + a Colab/desktop Python run, not through the
  compiled app on a device).
- No multi-source (NDVI) correlation wired into the Android entry point
  yet, even though `correlation.py` and `imagery_source.py` are present
  and tested on desktop (`investigation_multi.py`). Wiring
  `investigation_mobile.py` to optionally run both sources and show
  CORROBORATED/SINGLE_SOURCE status is a natural next step and doesn't
  require new algorithms — only a new entry function.
- No device GPS permission/integration — coordinates are typed in
  manually. Deliberately out of scope for this increment to keep it
  small and verifiable.
- No AI Debate Engine, no depth estimation — per the core README, those
  come after there's genuine, *real-world-verified* multi-source
  evidence to work with.
- API key is held only in memory for the session, never persisted —
  the user has to re-enter it each time the app restarts. Fine for
  this increment; an `EncryptedSharedPreferences`-backed store would be
  the natural next step if that friction matters.
- Launcher icon is a plain vector placeholder, not a designed adaptive
  icon — cosmetic, trivial to replace later.
