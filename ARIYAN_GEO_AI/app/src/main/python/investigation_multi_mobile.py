"""
investigation_multi_mobile.py -- Multi-evidence-source investigation entry
point called from Kotlin (via Chaquopy): DEM + NDVI + Thermal + Optical
correlation.

Mirrors investigation_mobile.py's pattern (JSON string return, no
scipy, no file I/O) but runs DEM through anomaly detection, then
independently checks each DEM candidate against real Copernicus
Sentinel-2 NDVI, real Landsat 8/9 thermal data, AND real Sentinel-2
visible-band optical brightness, cross-referencing all four via a
per-candidate combiner to produce CORROBORATED / SINGLE_SOURCE status --
and now which of NDVI, THERMAL, and/or OPTICAL actually corroborated
each candidate.

REWRITTEN A PRIOR SESSION -- SYNTHETIC PATH REMOVED ENTIRELY, BOTH DEM AND
NDVI. Previously, DEM had a use_real_dem switch (default False,
SyntheticDEMSource) and NDVI was ALWAYS SyntheticNDVISource unless a
SEPARATE use_real_ndvi switch was also flipped on -- meaning by default
this whole function ran on two independent kinds of fabricated terrain.
That directly violated this project's hard requirement (nothing
synthetic/fake -- data must actually be gathered) the moment synthetic
became the actual default rather than an explicit opt-in dev/test mode.

NEW DEM BEHAVIOR (identical pattern to investigation_mobile.py): a real,
live OpenTopography fetch is ALWAYS attempted first -- no toggle. On
failure (network/HTTP/parse error, or no api_key configured yet), falls
back to offline_evidence_fallback.fetch_offline_dem() (this device's
own previously-downloaded offline DEM library). If both fail, raises a
single combined, honest OpenTopographyFetchError.

NEW NDVI BEHAVIOR: a real, live, per-DEM-candidate Copernicus