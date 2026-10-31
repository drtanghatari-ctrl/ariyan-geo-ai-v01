"""
survey_plan.py -- ef-v3 (2026-10-31): value of information. Where should a
field survey look, and with what, to separate the user's own hypotheses?

Inputs are only what the app already holds for the open Final Image window:
the evidence volume (evidence_volume.py: DERIVED raised body, the user's
section and footprint hypotheses, CONTESTED blocks). Output is a PLANNING AID:

  1. CONTESTED zones first -- connected areas where two or more of the user's
     hypotheses claim the same blocks. Measuring there is what can tell the
     competing ideas apart. Larger zones (more contested blocks) rank higher.
  2. Then each single hypothesis, largest claimed volume first.
For every item: where (corner / end coordinates, computed from the user's own
shapes), which depth range, and which methods can resolve it, from a fixed,
qualitative capability table. No detection probability, no depth reach and no
"expected result" is invented; the user and the survey team decide.

Never evidence; never changes a candidate, review, status or confidence;
writes nothing except the optional export files.
"""
from __future__ import annotations

import json
import os
import time
from collections import deque
from typing import Any, Dict, List

import numpy as np

import evidence_volume as ev

VERSION = "svp-v1"

# Qualitative, standard capabilities only. No numbers: real reach depends on
# the soil and the equipment, which the survey team must judge on site.
METHODS = {
    "GPR": ("Ground-penetrating radar: horizontal depth slices and vertical profiles that show buried "
            "interfaces (walls, floors, pit edges). Best for shallow targets; how deep it reaches depends "
            "strongly on the soil (clay-rich or salty ground limits it)."),
    "ERT": ("Electrical resistivity tomography: vertical resistivity sections along a line. Reaches deeper "
            "than GPR with coarser detail; the line must be long enough for the depth you need."),
    "MAG": ("Magnetometry (gradiometer): a fast plan-view map of magnetic contrasts such as fired features "
            "(kilns, hearths), ditch and pit fills, some walls. Shows WHERE, not how deep."),
    "CORE": ("Auger / coring: direct, point-by-point layers (true MEASURED depth and material) but destructive "
             "and needs the proper archaeological permit. Use last, at the spot the other methods point to."),
}
STATEMENT = ("Survey plan (svp-v1): a planning aid from your own hypotheses and the DEM-derived body. "
             "It ranks where measuring would best separate your ideas; it is not evidence, makes no "
             "prediction of what will be found, and changes no status or confidence. Methods and depths "
             "must be confirmed with a survey team on site.")


def _components(mask: np.ndarray) -> List[List[tuple]]:
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    comps = []
    for r0 in range(h):
        for c0 in range(w):
            if mask[r0, c0] and not seen[r0, c0]:
                q = deque([(r0, c0)]); seen[r0, c0] = True; cells = []
                while q:
                    r, c = q.popleft(); cells.append((r, c))
                    for rr, cc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                        if 0 <= rr < h and 0 <= cc < w and mask[rr, cc] and not seen[rr, cc]:
                            seen[rr, cc] = True; q.append((rr, cc))
                comps.append(cells)
    return comps


def _methods_for(top_m: float, bottom_m: float, area_cells: int) -> List[str]:
    """Which methods to list, in order. Purely structural: a plan-view map
    (MAG) and depth slices (GPR) for any area; ERT whenever depth matters;
    coring last. No claim about reach."""
    order = ["MAG", "GPR", "ERT", "CORE"]
    if area_cells <= 1:            # a single cell: a line or point method is more practical than a map
        order = ["GPR", "ERT", "CORE", "MAG"]
    return order


def plan(states: np.ndarray, counts: np.ndarray, hyps: List[Dict[str, Any]], body: Dict[str, Any],
         pixel_to_lonlat, slice_m: float = ev.SLICE_M) -> Dict[str, Any]:
    """Pure planner (tested directly). pixel_to_lonlat(x, y) -> (lon, lat)."""
    h, w, k = counts.shape
    items: List[Dict[str, Any]] = []
    # 1) contested zones
    contested_any = (counts >= 2).any(axis=2)
    for cells in _components(contested_any):
        rows = [r for r, _ in cells]; cols = [c for _, c in cells]
        ks = sorted({i for (r, c) in cells for i in range(k) if counts[r, c, i] >= 2})
        names = sorted({hp["label"] for hp in hyps
                        if set(map(tuple, hp["cells"])) & set(cells)})
        x0, x1, y0, y1 = min(cols), max(cols) + 1, min(rows), max(rows) + 1
        corners = [pixel_to_lonlat(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        top, bottom = ks[0] * slice_m, (ks[-1] + 1) * slice_m
        items.append({
            "kind": "CONTESTED", "hypotheses": names, "blocks": int(sum((counts[r, c, :] >= 2).sum() for r, c in cells)),
            "cells": len(cells), "depth_top_m": top, "depth_bottom_m": bottom,
            "area_corners_latlon": [[round(lat, 6), round(lon, 6)] for lon, lat in corners],
            "why": "Two or more of your hypotheses claim these blocks; a measurement here can tell them apart.",
            "methods": _methods_for(top, bottom, len(cells)),
        })
    items.sort(key=lambda it: -it["blocks"])
    # 2) single hypotheses, largest claimed volume first
    singles = []
    for hp in hyps:
        cells = sorted(set(map(tuple, hp["cells"])))
        if not cells:
            continue
        n_slices = sum(1 for i in range(k) if i * slice_m < hp["bottom_m"] and (i + 1) * slice_m > hp["top_m"])
        rows = [r for r, _ in cells]; cols = [c for _, c in cells]
        x0, x1, y0, y1 = min(cols), max(cols) + 1, min(rows), max(rows) + 1
        corners = [pixel_to_lonlat(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        singles.append({
            "kind": "HYPOTHESIS", "hypotheses": [hp["label"]], "hypothesis_kind": hp.get("kind"),
            "blocks": len(cells) * n_slices, "cells": len(cells),
            "depth_top_m": float(hp["top_m"]), "depth_bottom_m": float(hp["bottom_m"]),
            "area_corners_latlon": [[round(lat, 6), round(lon, 6)] for lon, lat in corners],
            "why": ("Tests your hypothesis directly. A " + ("section line" if hp.get("kind") == "section" else "footprint")
                    + " is surveyed across its whole extent and a margin around it, so its edges can be seen."),
            "methods": _methods_for(hp["top_m"], hp["bottom_m"], len(cells)),
        })
    singles.sort(key=lambda it: -it["blocks"])
    items.extend(singles)
    for i, it in enumerate(items):
        it["rank"] = i + 1
    return {
        "version": VERSION, "items": items,
        "methods": METHODS,
        "body": {kk: v for kk, v in (body or {}).items() if kk != "mask_cells"},
        "empty_reason": None if items else
            "No hypotheses of yours are placed in this window, so there is nothing to separate yet. "
            "Add a section or footprint hypothesis first (3D tab).",
        "statement": STATEMENT,
    }


def plan_json(db_root: str, session_id: str) -> str:
    try:
        v = ev._build(db_root, session_id)
        s = ev._session(session_id)
        grid = s["result"]["grid"]
        hyps = ev._hyp_cells(db_root, s)
        p = plan(v["states"], v["counts"], hyps, v["summary"].get("body"), grid.pixel_to_lonlat)
        p["candidate_id"] = s["candidate_id"]
        p["source"] = grid.source
        p["source_sha256"] = grid.source_sha256
        return json.dumps(p)
    except Exception as e:                        # shown, never hidden
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def export_plan_json(db_root: str, session_id: str) -> str:
    """Writes the plan as JSON + a readable text file for a survey team."""
    try:
        p = json.loads(plan_json(db_root, session_id))
        if "error" in p:
            return json.dumps(p)
        stem = "survey_plan_%s_%s" % (p["candidate_id"][:8], time.strftime("%Y%m%d_%H%M%S", time.gmtime()))
        out_dir = os.path.join(db_root, "exports", "survey_plan")
        os.makedirs(out_dir, exist_ok=True)
        jp = os.path.join(out_dir, stem + ".json")
        tp = os.path.join(out_dir, stem + ".txt")
        p["created_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(jp, "w", encoding="utf-8") as f:
            json.dump(p, f, indent=2, sort_keys=True)
        lines = ["ARIYAN GEO AI -- SURVEY PLAN (%s)" % VERSION, "Candidate " + p["candidate_id"],
                 "Created " + p["created_utc"], "", STATEMENT, ""]
        if not p["items"]:
            lines.append(p["empty_reason"])
        for it in p["items"]:
            lines.append("%d. %s: %s" % (it["rank"], it["kind"], ", ".join(it["hypotheses"])))
            lines.append("   depth %.1f-%.1f m below ground; %d cells" % (it["depth_top_m"], it["depth_bottom_m"], it["cells"]))
            lines.append("   area corners (lat, lon): " + "; ".join("%.6f, %.6f" % (a, b) for a, b in it["area_corners_latlon"]))
            lines.append("   why: " + it["why"])
            lines.append("   methods, in order: " + ", ".join(it["methods"]))
            lines.append("")
        lines.append("METHODS")
        for key, txt in METHODS.items():
            lines.append("  %s: %s" % (key, txt))
        with open(tp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return json.dumps({"ok": True, "paths": {"text": tp, "json": jp}})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
