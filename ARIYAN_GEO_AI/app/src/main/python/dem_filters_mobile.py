"""
dem_filters_mobile.py -- fa-v2 (2026-10-22): Kotlin bridge for Filters on
the Final Image screen.

options_json()                     the allowed choices (the dialog shows only these)
open_filter_json(sid, name, params_json)
                                   runs one filter on the open fi-v1 session's DEM
                                   window; keeps the result in memory (one per
                                   session) and returns legend + label + notes.
filter_rgba(sid)                   the filtered image as RGBA bytes on the DEM's
                                   own cells (transparent = no data -> hatched).
export_filter_json(root, sid)      PNG + GeoTIFF + provenance (DERIVED label).
close_filter(sid)                  forget it.

Read-only: no database import, no write anywhere except the export folder.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Dict

import dem_filters as df
import final_image as fi
import final_image_mobile as fim

_FILTERS: Dict[str, Dict] = {}
_LOCK = threading.Lock()


def _grid(sid: str) -> fi.Grid:
    with fim._LOCK:
        s = fim._SESSIONS.get(sid)
    if s is None:
        raise KeyError("final image session expired; reopen the image")
    return s["result"]["grid"]


def active(sid: str) -> Dict:
    with _LOCK:
        f = _FILTERS.get(sid)
    if f is None:
        raise KeyError("no filter is on; choose one from Filters first")
    return f


def options_json() -> str:
    return json.dumps({
        "version": df.FA2_VERSION, "filters": list(df.FILTERS), "defaults": df.DEFAULTS,
        "smooth_methods": list(df.SMOOTH_METHODS), "gauss_sigmas": list(df.GAUSS_SIGMAS),
        "median_sizes": list(df.MEDIAN_SIZES), "residual_radii_m": list(df.RESIDUAL_RADII_M),
        "curv_smooth": list(df.CURV_SMOOTH), "direction_modes": list(df.DIRECTION_MODES),
        "bearings": list(df.DERIV_BEARINGS)})


def open_filter_json(sid: str, name: str, params_json: str = "{}") -> str:
    try:
        grid = _grid(sid)
        params = json.loads(params_json or "{}")
        f = df.apply_filter(grid, name, params)
        with _LOCK:
            _FILTERS[sid] = f
        h, w = grid.shape
        return json.dumps({
            "ok": True, "version": df.FA2_VERSION, "filter": f["filter"], "params": f["params"],
            "label": f["label"], "legend": f["legend"], "units": f["units"],
            "width": w, "height": h, "placement": {"x0": 0.0, "y0": 0.0, "sx": 1.0, "sy": 1.0},
            "cells": f["cells"], "cells_no_data": f["cells_no_data"],
            "border_cells": f["border_cells"], "flat_cells": f["flat_cells"],
            "notes": f["notes"], "statement": f["statement"]}, allow_nan=False)
    except Exception as e:                      # surfaced to the user, never hidden
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def filter_rgba(sid: str) -> bytes:
    f = active(sid)
    return fim._clean_rgba(f["image"]).tobytes()


def export_filter_json(db_root: str, sid: str) -> str:
    try:
        grid = _grid(sid)
        f = active(sid)
        with fim._LOCK:
            cid = fim._SESSIONS[sid]["candidate_id"]
        stem = "fa2_%s_derived_%s_%s" % (cid[:8], f["filter"],
                                         time.strftime("%Y%m%d_%H%M%S", time.gmtime()))
        out_dir = os.path.join(db_root, "exports", "final_image")
        os.makedirs(out_dir, exist_ok=True)
        png = fi.encode_png(f["image"])
        tif = fi.encode_geotiff(grid, f["image"])
        paths = {"png": os.path.join(out_dir, stem + ".png"),
                 "geotiff": os.path.join(out_dir, stem + ".tif"),
                 "provenance": os.path.join(out_dir, stem + ".provenance.json")}
        with open(paths["png"], "wb") as fh:
            fh.write(png)
        with open(paths["geotiff"], "wb") as fh:
            fh.write(tif)
        prov = df.provenance(grid, f, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        prov["outputs"] = {"png_sha256": fi._sha(png), "geotiff_sha256": fi._sha(tif)}
        with open(paths["provenance"], "w", encoding="utf-8") as fh:
            json.dump(prov, fh, indent=2, sort_keys=True, ensure_ascii=False)
        return json.dumps({"ok": True, "paths": paths, "label": f["label"]})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def close_filter(sid: str) -> None:
    with _LOCK:
        _FILTERS.pop(sid, None)
