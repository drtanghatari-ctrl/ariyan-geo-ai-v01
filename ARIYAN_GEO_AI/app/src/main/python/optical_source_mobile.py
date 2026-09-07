"""
optical_source_mobile.py
=========================
REAL Sentinel-2 optical (visible-band) brightness for Android, via the same
Copernicus Data Space Ecosystem Sentinel Hub Statistical API used by
ndvi_source_mobile.py and thermal_source_mobile.py -- same account, same
"push the computation server-side, parse plain JSON on-device" pattern, no
raster ever reaches the device.

WHAT THIS CHECKS AND WHY IT IS A GENUINELY DIFFERENT SIGNAL FROM NDVI:
NDVI measures vegetation VIGOR (a live-plant signal). This module measures
broadband VISIBLE REFLECTANCE -- how bright or dark the ground looks in
ordinary red/green/blue light, averaged across bands B04 (red), B03
(green), B02 (blue). This is the real remote-sensing signature aerial
archaeologists call a "soilmark": backfilled ditches, robbed-out wall
foundations, and other disturbed ground often show as an anomalously
bright or dark patch in bare-earth imagery for reasons that have nothing
to do with plant health -- disturbed/looser subsoil retains moisture
differently than undisturbed ground (darker when damp), or contains
different material entirely (chalk/limestone rubble reads brighter;
organic-rich pit/ditch fill reads darker). This is the same "core vs
halo" per-DEM-candidate architecture as NDVI and Thermal, but a
physically distinct phenomenon -- not a repackaging of the vegetation
signal, and not double-counting a single canopy measurement as two
independent sources (see debate_mobile.py's HONEST MAPPING NOTES on
why has_optical was deliberately kept False until this file existed).

MASKING DESIGN DECISION (documented here so it's not silently assumed):
this evalscript masks out water (SCL==6) via the exact same approach as
ndvi_source_mobile.py's NDVI_EVALSCRIPT, and relies on the same
maxCloudCoverage=40 scene-level filter -- it does NOT additionally