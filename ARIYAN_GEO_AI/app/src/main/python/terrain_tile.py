"""
terrain_tile.py -- W1 (2026-11-02). One terrain tile, on demand.

The Windows app does not carry the phone's 12 GB of country DEM tiles (they
never travel in a project bundle). When the Mission Control workstation or a
Final Image needs the terrain around a candidate, this fetches just the one
Copernicus GLO-30 tile that covers it (about 25-60 MB), from the same public
source and into the same place the phone's country download uses
(<offline_data>/<country>/dem/<tile>.tif), with the same downloader
(offline_data_manager._download_one_tile: atomic write, retries, a 404 means
"no public tile here"). No key is needed. Nothing else is changed.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Dict

VERSION = "tt-v1"


def tile_status(db_root: str, lat: float, lon: float) -> Dict[str, Any]:
    import offline_country_registry as reg
    import offline_dem_store as ods
    country = reg.get_country_for_point(float(lat), float(lon))
    if country is None:
        return {"covered": False, "present": False, "reason": "no offline country package covers this point"}
    path = ods.local_tile_path(country.storage_folder, db_root, float(lat), float(lon))
    return {"covered": True, "present": os.path.isfile(path), "path": path,
            "tile": os.path.splitext(os.path.basename(path))[0], "country": country.iso_code
            if hasattr(country, "iso_code") else None}


def ensure_tile(db_root: str, lat: float, lon: float, session=None) -> Dict[str, Any]:
    import offline_country_registry as reg
    import offline_data_manager as odm
    st = tile_status(db_root, lat, lon)
    if not st["covered"] or st["present"]:
        return dict(st, status="already_present" if st.get("present") else "not_covered")
    country = reg.get_country_for_point(float(lat), float(lon))
    r = odm._download_one_tile(country, db_root, int(math.floor(float(lat))), int(math.floor(float(lon))), session)
    st = tile_status(db_root, lat, lon)
    return dict(st, status=r.status, detail=r.detail)


def tile_status_json(db_root: str, lat: float, lon: float) -> str:
    try:
        return json.dumps(tile_status(db_root, lat, lon))
    except Exception as e:
        return json.dumps({"error": "%s: %s" % (type(e).__name__, e)})


def ensure_tile_json(db_root: str, lat: float, lon: float) -> str:
    try:
        return json.dumps(ensure_tile(db_root, lat, lon))
    except Exception as e:
        return json.dumps({"error": "%s: %s" % (type(e).__name__, e)})
