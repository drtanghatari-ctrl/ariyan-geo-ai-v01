"""
sat_image_mobile.py -- fi-v2 (2026-10-21): Kotlin bridge for the satellite
image layers of the Final Image screen (FinalImageActivity.kt).

The layers sit on top of an open fi-v1 session (final_image_mobile), over
the SAME window as the DEM image:

layers_status_json(root, sid)            which products are saved / checked
open_layer_json(root, sid, product, id, secret, fetch)
                                         the layer's caption, scene date,
                                         clear fraction, self-check state,
                                         legend, provenance and its placement
                                         on the DEM cell grid
layer_rgba(sid, product)                 the colourised cells, RGBA, one
                                         pixel per real image cell; empty
                                         (cloud / no data) cells are fully
                                         transparent so the terrain shows

Nothing is resampled: Kotlin draws the image's own cells with an affine
placement (scale + offset) onto the DEM grid.

The layer is hidden until the product's one-time self-check against the
Statistical API has passed (sat_image.layer_allowed); the reason is shown.

Read-only on the database: this module never writes a candidate, a review,
a status or a confidence. It only fetches with explicit fetch=True.
"""
from __future__ import annotations

import json
import threading
from typing import Dict, Optional

import numpy as np

import final_image_mobile as fim
import sat_image as si

_LAYERS: Dict[str, Dict[str, Dict]] = {}       # sid -> product -> {values, payload}
_LOCK = threading.Lock()
_HTTP = None                                    # tests inject a fake Copernicus


def _session(sid: str) -> Dict:
    with fim._LOCK:
        s = fim._SESSIONS.get(sid)
    if s is None:
        raise KeyError("final image session expired; reopen the image")
    return s


def _dem_bounds(s: Dict) -> Dict[str, float]:
    b = s["result"]["provenance"]["bounds"]
    return {k: float(b[k]) for k in ("south", "north", "west", "east")}


def placement(dem_grid, geo: Dict) -> Dict[str, float]:
    """Where image pixel (0,0) and one image pixel land in DEM-cell units."""
    return {"x0": (geo["west"] - dem_grid.west) / dem_grid.dlon,
            "y0": (dem_grid.north - geo["north"]) / dem_grid.dlat,
            "sx": geo["dlon"] / dem_grid.dlon,
            "sy": geo["dlat"] / dem_grid.dlat}


def _token(client_id: str, secret: str) -> Optional[str]:
    if not (client_id and secret):
        return None
    import ndvi_source_mobile as ndvi
    return ndvi.get_access_token(client_id, secret)


def layers_status_json(db_root: str, sid: str) -> str:
    try:
        b = _dem_bounds(_session(sid))
        out = []
        for p in si.PRODUCT_ORDER:
            ok, why = si.layer_allowed(db_root, p)
            out.append({"product": p, "label": si.PRODUCTS[p]["label"],
                        "saved": si.find_saved(db_root, p, b) is not None,
                        "allowed": ok, "check": why})
        return json.dumps({"products": out})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def open_layer_json(db_root: str, sid: str, product: str, client_id: str = "",
                    client_secret: str = "", fetch: bool = False) -> str:
    try:
        if product not in si.PRODUCTS:
            return json.dumps({"error": f"unknown layer {product}"})
        s = _session(sid)
        b = _dem_bounds(s)
        saved = si.find_saved(db_root, product, b)
        token = None
        if saved is None:
            if not fetch:
                return json.dumps({"product": product, "needs_fetch": True,
                                   "label": si.PRODUCTS[product]["label"],
                                   "note": "not saved for this window yet"})
            token = _token(client_id, client_secret)
            if token is None:
                return json.dumps({"error": "no saved image for this window and no Copernicus "
                                            "login saved; add it in Settings, then fetch"})
        elif si.self_check_record(db_root, product) is None:
            # saved but never checked: check now if we can, else stay hidden
            try:
                token = _token(client_id, client_secret)
            except Exception:
                token = None
        img = si.ensure_layer(db_root, product, b, token, _HTTP or si.http_post)
        payload = si.layer_payload(product, img)
        payload["placement"] = placement(s["result"]["grid"], img["geo"])
        payload["fetched_now"] = not payload["reused"]
        if not payload["allowed"]:
            payload["hidden_reason"] = payload["check"]
        with _LOCK:
            _LAYERS.setdefault(sid, {})[product] = {"values": img["values"], "payload": payload}
            for k in [k for k in _LAYERS if k not in fim._SESSIONS]:
                _LAYERS.pop(k, None)               # sessions closed by fi-v1
        return json.dumps(payload)
    except si.SatImageThrottled as e:
        return json.dumps({"error": f"Copernicus quota/rate limit reached; try again later ({e})",
                           "throttled": True})
    except Exception as e:                          # surfaced to the user, never hidden
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def layer_rgba(sid: str, product: str) -> bytes:
    with _LOCK:
        l = (_LAYERS.get(sid) or {}).get(product)
    if l is None:
        raise KeyError("layer not open; choose it again")
    if not l["payload"]["allowed"]:
        raise PermissionError("layer hidden until its self-check passes: " + str(l["payload"]["check"]))
    lg = l["payload"]["legend"]
    rgba = si.colorize(product, l["values"], lg["vmin"], lg["vmax"])
    rgba[rgba[..., 3] == 0] = 0                    # premultiplied: empty = 0,0,0,0
    return np.ascontiguousarray(rgba).tobytes()


def close_layers(sid: str) -> None:
    with _LOCK:
        _LAYERS.pop(sid, None)
