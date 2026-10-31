"""
overview_mobile.py -- ov-v1 (2026-10-31): the Overview tab of the Final Image
screen (the mock-up's dashboard, phone-sized). Read-only.

Everything shown is already stored or already computed for the open window;
nothing is recomputed into a new result and nothing is written:
  * candidate details: position, stored confidence, status + review reason,
    job and trust, evidence types linked to it (evidence_link);
  * Steward: the latest recorded band/number and its first reasoning lines;
  * AI Debate: how many stored, and the latest synthesis;
  * evidence layers checklist: what really exists for THIS candidate/window --
    DEM (always: the image's tile), each satellite layer (linked as evidence /
    saved for this window / not available), GPR and ERT field datasets,
    magnetometry (not supported yet) -- never a tick for something absent;
  * the user's hypotheses (section + footprint) counts;
  * the other candidates in the window with distance and confidence;
  * map information: UTM zone, cell size, DEM source and SHA-256, window.
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List

import grand_project_db as db
import utm_projection as up

VERSION = "ov-v1"
STATEMENT = ("Overview of recorded results only. Nothing here is recomputed or changes a status, a review "
             "or a confidence. Confidence stays capped by the Steward until field data exists.")
SAT_EVIDENCE_TYPES = {"NDVI": "NDVI", "THERMAL": "THERMAL", "SAR_VV": "SAR", "SAR_VH": "SAR", "TRUE_COLOR": None}


def _session(session_id: str):
    import final_image_mobile as fim
    with fim._LOCK:
        s = fim._SESSIONS.get(session_id)
    if s is None:
        raise KeyError("final image session expired; reopen the image")
    return s


def _evidence_types(db_root: str, candidate_id: str) -> Dict[str, Dict[str, int]]:
    conn = db.get_connection(db_root)
    try:
        db.initialize_schema(conn)
        out: Dict[str, Dict[str, int]] = {}
        for r in conn.execute("SELECT evidence_type, relation, COUNT(*) AS n FROM evidence_link "
                              "WHERE candidate_id = ? GROUP BY evidence_type, relation", (candidate_id,)):
            out.setdefault(str(r["evidence_type"]).upper(), {})[str(r["relation"])] = int(r["n"])
        return out
    finally:
        conn.close()


def _count_active(fn, db_root: str, cid: str) -> int:
    try:
        return len(fn(db_root, cid))
    except Exception:
        return 0


def overview_json(db_root: str, session_id: str) -> str:
    try:
        s = _session(session_id)
        cid = s["candidate_id"]
        cand = db.get_candidate(db_root, cid)
        if cand is None:
            return json.dumps({"error": "candidate not found"})
        res = s["result"]
        grid = res["grid"]
        dx, dy = grid.cell_size_m()
        h, w = grid.shape

        review: Dict[str, Any] = {}
        try:
            import grand_project_review as gr
            review = gr.review_summary_for_project(db_root, cand["grand_project_id"]).get(cid, {})
        except Exception:
            review = {}
        ev = _evidence_types(db_root, cid)

        hist = db.get_confidence_history(db_root, cid)
        steward = None
        if hist:
            last = hist[-1]
            try:
                reasons = json.loads(last.get("reasoning_snapshot_json") or "[]")
            except ValueError:
                reasons = [str(last.get("reasoning_snapshot_json"))]
            steward = {"band": last.get("band"), "numeric": last.get("numeric_confidence"),
                       "recorded_at": last.get("recorded_at"), "ratings": len(hist),
                       "reasoning": reasons[:2] if isinstance(reasons, list) else [str(reasons)]}

        debate = {"stored": 0}
        try:
            import debate_store
            ds = debate_store.list_for_candidate(db_root, cid)
            if ds:
                syn = (ds[-1].get("debate") or {}).get("synthesis") or {}
                debate = {"stored": len(ds), "recorded_at": ds[-1]["recorded_at"], "origin": ds[-1]["origin"],
                          "leading": syn.get("leading_position"), "agreement": syn.get("agreement_level")}
        except Exception:
            pass

        # satellite layers saved for this window (no fetching)
        saved: Dict[str, bool] = {}
        try:
            import sat_image as si
            import sat_image_mobile as sim
            b = sim._dem_bounds(s)
            for p in si.LAYER_ORDER:
                saved[p] = si.find_saved(db_root, p, b) is not None
            labels = {p: si.PRODUCTS[p]["label"] for p in si.LAYER_ORDER}
        except Exception:
            labels = {}

        import field_data as fd
        fds = fd.list_for_candidate(db_root, cid)
        n_gpr = sum(1 for r in fds if r["method"] == "GPR")
        n_ert = sum(1 for r in fds if r["method"] == "ERT")

        layers: List[Dict[str, Any]] = [{
            "name": "DEM (terrain)", "state": "USED",
            "detail": "%s; this image's %.1f x %.1f m cells" % (grid.source, dx, dy)
                      + ("; linked as evidence" if "DEM" in ev else "")}]
        for p, lab in labels.items():
            et = SAT_EVIDENCE_TYPES.get(p)
            if et and et in ev:
                state, detail = "EVIDENCE", "linked to this candidate (%s)" % ", ".join(sorted(ev[et]))
            elif saved.get(p):
                state, detail = "SAVED", "image saved for this window (context, not evidence)"
            else:
                state, detail = "NONE", "not fetched for this window"
            layers.append({"name": lab, "state": state, "detail": detail})
        layers.append({"name": "GPR (field)", "state": "MEASURED" if n_gpr else "NONE",
                       "detail": ("%d dataset(s) imported" % n_gpr) if n_gpr else "no survey imported"})
        ert_manual = sum(ev.get("ERT", {}).values())
        layers.append({"name": "ERT (field)", "state": "MEASURED" if (n_ert or ert_manual) else "NONE",
                       "detail": ("%d section(s) imported" % n_ert if n_ert else "no section imported")
                                 + ("; %d manual reading(s)" % ert_manual if ert_manual else "")})
        layers.append({"name": "Magnetometry", "state": "NONE", "detail": "not supported yet"})

        import section_hypothesis as sh
        import footprint_hypothesis as fph
        hyps = {"section": _count_active(sh.list_for_candidate, db_root, cid),
                "footprint": _count_active(fph.list_for_candidate, db_root, cid)}

        fx, fy = s.get("focus") or (w / 2.0, h / 2.0)
        others = []
        for m in s.get("markers") or []:
            if m.get("focus"):
                continue
            dist = math.hypot((m["x"] - fx) * dx, (m["y"] - fy) * dy)
            others.append({"id": m["id"], "label": m["id"][:8], "style": m.get("style"),
                           "confidence_label": m.get("confidence_label"), "status": m.get("status"),
                           "distance_m": round(dist, 0)})
        others.sort(key=lambda o: o["distance_m"])

        lon, lat = float(cand["lon"]), float(cand["lat"])
        p = up.utm_forward(lat, lon)
        params = res.get("provenance", {}).get("parameters", {}) or {}
        return json.dumps({
            "version": VERSION, "candidate_id": cid,
            "candidate": {"lat": lat, "lon": lon, "band": cand.get("confidence_band"),
                          "numeric": cand.get("confidence_numeric"),
                          "status": review.get("status_label") or cand.get("status"),
                          "review_source": review.get("review_source"),
                          "review_reason": review.get("last_review_reason"),
                          "job_id": review.get("job_id"), "job_trust": review.get("job_trust"),
                          "evidence_types": sorted(ev)},
            "steward": steward, "debate": debate, "layers": layers, "hypotheses": hyps,
            "field_datasets": {"gpr": n_gpr, "ert": n_ert},
            "others": others,
            "map": {"utm_zone": p.zone, "hemisphere": "N" if p.northern else "S",
                    "easting": round(p.easting, 1), "northing": round(p.northing, 1),
                    "cell_dx_m": round(dx, 2), "cell_dy_m": round(dy, 2), "cells": [int(w), int(h)],
                    "window_half_m": params.get("half_size_m"), "source": grid.source,
                    "source_sha256": grid.source_sha256},
            "statement": STATEMENT,
        }, default=str)
    except Exception as e:                          # shown, never hidden
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
