"""
The job report with every saved layer (lay-v1, win-u4, 2026-11-04).

The core report (grand_project_report, the same as the phone's) is built first;
then, for the leading candidates of the report, a "Satellite layers" section is
put inside the same HTML before it is written: the hillshaded relief and every
layer saved on this computer for the candidate's +/-1 km window (true colour,
NDVI, thermal, radar VV/VH), each with its scene date, clear share and value
range. Layers not saved are listed by name, never silently left out.

The HTML that is written is the HTML whose MD5 goes into the REPORT_EXPORTED
timeline event, so the fingerprint still proves the file. Nothing is fetched:
only saved images are used (the Copernicus login is used only to finish a saved
layer's self-check, as on Mission Control).
"""
from __future__ import annotations

import base64
import html
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import numpy as np

VERSION = "lay-v1"
MAX_CANDIDATES = 20
LEADING = ("SUBSTANTIAL", "HIGH", "MODERATE")


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _png_uri(rgba: bytes, w: int, h: int) -> str:
    import final_image as fi
    a = np.frombuffer(rgba, dtype=np.uint8).reshape(h, w, 4).copy()
    # premultiplied -> straight alpha for the file, so empty cells stay transparent
    al = a[..., 3:4].astype(np.float32)
    nz = al[..., 0] > 0
    a[..., :3][nz] = np.clip(a[..., :3][nz].astype(np.float32) * 255.0 / al[nz], 0, 255).astype(np.uint8)
    return "data:image/png;base64," + base64.b64encode(fi.encode_png(a)).decode("ascii")


def pick_candidates(rows: List[Dict[str, Any]], limit: int = MAX_CANDIDATES) -> List[Dict[str, Any]]:
    """The report's own order; the leading (Moderate or higher, not rejected) first, then the rest."""
    lead = [r for r in rows if (r.get("confidence_band") or "").upper() in LEADING and r.get("status") != "REJECTED"]
    if not lead:
        lead = [r for r in rows if r.get("status") != "REJECTED"][:10]
    return lead[:limit]


def candidate_layers(root: str, cid: str) -> Dict[str, Any]:
    """Every layer of the candidate's +/-1 km window, as small pictures, from saved images only."""
    from ariyan_win import workstation
    import sat_image as si
    t = workstation.terrain(root, cid)
    if "error" in t:
        return {"id": cid, "error": t["error"]}
    out = [{"product": "RELIEF", "label": "Terrain (relief, hillshaded)", "state": "SAVED",
            "note": t["meta"].get("source") or "offline DEM", "uri": _png_uri(t["drape"], t["width"], t["height"])}]
    for l in t["layers"]:
        item = {"product": l["product"], "label": l["label"], "state": l["state"], "reason": l.get("reason")}
        if l["state"] == "SAVED" and l.get("rgba"):
            cf = l.get("clear_fraction")
            lg = l.get("legend") or {}
            unit = si.PRODUCTS[l["product"]].get("unit") or ""
            rng = ""
            if lg.get("data_min") is not None and l["product"] != "TRUE_COLOR":
                rng = "%.3g\u2013%.3g %s" % (lg["data_min"], lg["data_max"], unit)
            item["note"] = " \u00b7 ".join(x for x in [str(l.get("scene_date") or ""),
                                                     "" if cf is None else "%d%% clear" % round(100 * float(cf)),
                                                     rng] if x)
            try:
                item["uri"] = _png_uri(l["rgba"], int(l["width"]), int(l["height"]))
            except Exception as e:
                item["state"], item["reason"] = "ERROR", "%s: %s" % (type(e).__name__, e)
        out.append(item)
    return {"id": cid, "layers": out, "dem": t["meta"].get("source")}


def annex_html(results: List[Dict[str, Any]], rows_by_id: Dict[str, Dict[str, Any]], exact: bool) -> str:
    n_img = sum(1 for r in results for l in r.get("layers", []) if l.get("uri") and l["product"] != "RELIEF")
    P = ["<h2 id='layers'>Satellite layers of the leading candidates (%s) / "
         "<span dir='rtl'>\u0644\u0627\u06cc\u0647\u200c\u0647\u0627\u06cc \u0645\u0627\u0647\u0648\u0627\u0631\u0647\u200c\u0627\u06cc "
         "\u0646\u0627\u0645\u0632\u062f\u0647\u0627\u06cc \u067e\u06cc\u0634\u0631\u0648</span></h2>" % VERSION,
         "<p class='small'>For each candidate: the hillshaded relief and every layer saved on this computer for its "
         "\u00b11 km window, with the scene date, the clear share of the window and the value range. Layers not "
         "saved are named, not hidden. Pictures are saved images only; nothing was fetched for this report. %d "
         "satellite picture%s in total.</p>" % (n_img, "" if n_img == 1 else "s"),
         "<style>.lyr{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 18px}.lyr figure{margin:0;width:168px;"
         "border:1px solid #ccc;border-radius:6px;padding:4px;background:#fafafa}.lyr img{width:160px;height:160px;"
         "object-fit:cover;image-rendering:pixelated;display:block;background:#eee}.lyr figcaption{font-size:11px;"
         "line-height:1.3}.lyr .miss{width:160px;height:160px;display:flex;align-items:center;justify-content:center;"
         "color:#888;background:#f0f0f0;font-size:11px;text-align:center}</style>"]
    for r in results:
        row = rows_by_id.get(r["id"], {})
        band = (row.get("confidence_band") or "NOT_RATED").replace("_", " ").title()
        num = row.get("confidence_numeric")
        lat, lon = row.get("lat"), row.get("lon")
        coord = ("%.6f, %.6f" % (lat, lon)) if exact and lat is not None else (
            "%.2f, %.2f (rounded)" % (lat, lon) if lat is not None else "")
        P.append("<h3>Candidate %s \u00b7 %s%s \u00b7 %s</h3>" % (_e(r["id"][:8]), _e(band),
                                                                  "" if num is None else " %.2f" % num, _e(coord)))
        if "error" in r:
            P.append("<p class='small'>Layers not shown: %s</p>" % _e(r["error"]))
            continue
        P.append("<div class='lyr'>")
        missing = []
        for l in r["layers"]:
            if l.get("uri"):
                P.append("<figure><img src='%s' alt='%s'><figcaption><b>%s</b><br>%s</figcaption></figure>" % (
                    l["uri"], _e(l["label"]), _e(l["label"]), _e(l.get("note") or "")))
            else:
                why = {"NOT_SAVED": "not saved yet", "HIDDEN": "hidden: %s" % (l.get("reason") or "quality check"),
                       "ERROR": "error: %s" % (l.get("reason") or "")}.get(l["state"], l["state"])
                missing.append("%s (%s)" % (l["label"], why))
                P.append("<figure><div class='miss'>%s<br>%s</div><figcaption><b>%s</b></figcaption></figure>" % (
                    _e(l["label"].split(" (")[0]), _e(why), _e(l["label"])))
        P.append("</div>")
        if missing:
            P.append("<p class='small'>Missing for this window: %s. Fetch them in its Final Image (each uses the "
                     "Copernicus quota once, then stays saved) and export the report again.</p>" % _e("; ".join(missing)))
    return "".join(P)


def export_job_report_with_layers(root: str, gid: str, job_id: str, top_n: int, exact: bool,
                                  progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """The core job report plus the layers section, written and logged like the core export."""
    import grand_project_db as db
    import grand_project_report as rep
    now = datetime.now(timezone.utc)
    built = rep.build_job_report(root, gid, job_id, top_n, exact, now)
    info, rows = built["info"], built["rows"]
    picked = pick_candidates(rows)
    results = []
    for i, r in enumerate(picked):
        if progress:
            progress(i, len(picked))
        try:
            results.append(candidate_layers(root, r["id"]))
        except Exception as e:                       # shown in the report, never hidden
            results.append({"id": r["id"], "error": "%s: %s" % (type(e).__name__, e)})
    annex = annex_html(results, {r["id"]: r for r in rows}, info["exact_coords"])
    page = built["html"]
    k = page.rfind("</body>")
    page = (page[:k] + annex + page[k:]) if k >= 0 else page + annex
    out_dir = rep._reports_dir(root)
    os.makedirs(out_dir, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    base = "ariyan_report_%s_%s%s" % (info["job_id"][:6], stamp, "_EXACT" if info["exact_coords"] else "")
    html_bytes = page.encode("utf-8")
    csv_bytes = built["csv"].encode("utf-8-sig")
    html_path = os.path.join(out_dir, base + ".html")
    csv_path = os.path.join(out_dir, base + ".csv")
    rep._write_atomic(html_path, html_bytes)
    rep._write_atomic(csv_path, csv_bytes)
    html_md5, csv_md5 = rep._md5_bytes(html_bytes), rep._md5_bytes(csv_bytes)
    n_img = sum(1 for r in results for l in r.get("layers", []) if l.get("uri") and l["product"] != "RELIEF")
    desc = ("Report %s + %s exported for job %s: %s rows of %d, %s coordinates, provenance %s; layers for %d "
            "candidate(s), %d satellite picture(s). HTML %s md5 %s; CSV %s md5 %s"
            % (rep.REPORT_VERSION, VERSION, info["job_id"][:6],
               "all" if info["top_n"] <= 0 else "top %d" % info["top_n"], info["candidates_total"],
               "EXACT" if info["exact_coords"] else "rounded (0.01 deg)",
               "VERIFIED" if info["provenance_verified"] else "NOT VERIFIED", len(results), n_img,
               os.path.basename(html_path), html_md5, os.path.basename(csv_path), csv_md5))
    logged = True
    try:
        db.log_timeline_event(root, gid, rep.EVENT_TYPE, related_entity_type="wide_area_search_job",
                              related_entity_id=info["job_id"], description=desc)
    except Exception:
        logged = False
    summary = rep._export_summary(info, html_path, csv_path, html_md5, csv_md5, logged)
    summary += "\n\nSatellite layers (%s): %d candidate(s), %d picture(s) from saved images." % (
        VERSION, len(results), n_img)
    return {"job_id": info["job_id"], "html_path": html_path, "csv_path": csv_path, "html_md5": html_md5,
            "csv_md5": csv_md5, "layers_candidates": len(results), "layers_pictures": n_img,
            "timeline_event_logged": logged, "summary_text": summary}
