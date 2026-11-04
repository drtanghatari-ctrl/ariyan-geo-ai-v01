"""
The job report as a PDF (pdf-v1, win-u5b, 2026-11-04).

Made with Qt's own text engine and PDF writer (already part of the app; no
browser engine): landscape A4, page numbers, the same content as the HTML
report -- banners, caveats, job, provenance, both languages -- with a compact
candidate table laid out for pages (key columns on one line, the known-site and
industry context in English and Persian on the line below) and the satellite
layers as a grid of pictures. Its MD5 is logged with the HTML's.
"""
from __future__ import annotations

import base64
import html as _html
import re
from typing import Any, Dict, List

VERSION = "pdf-v1"


def _e(x) -> str:
    return _html.escape(str(x if x is not None else ""))


def candidate_table(info: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
    import grand_project_report as rep
    exact = info["exact_coords"]
    P = ["<h2>Candidates / \u0646\u0627\u0645\u0632\u062f\u0647\u0627</h2>",
         "<table class='c' width='100%' cellspacing='0' cellpadding='3'><thead><tr>"
         "<th>#</th><th>Candidate</th><th>Lat</th><th>Lon</th><th>DEM z</th><th>Status / \u0648\u0636\u0639\u06cc\u062a</th>"
         "<th>Confidence</th><th>calib-v1</th><th>Terrain (F3)</th></tr></thead>"]
    for i, r in enumerate(rows):
        status = "%s%s / %s" % (r["status_en"], " (auto)" if r["review_source"] == "auto" else "", r["status_fa"])
        terrain = r["terrain_shape"] or ""
        if r["hillside"]:
            terrain += ", hillside %s" % r["hillside"]
        if r["terrain_method"]:
            terrain += " [%s]" % r["terrain_method"]
        bg = "#ffffff" if i % 2 == 0 else "#f3f5f8"
        P.append("<tr style='background:%s'><td>%d</td><td><tt>%s</tt></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                 "<td><b>%s</b></td><td>%s</td><td>%s</td></tr>" % (
                     bg, r["rank"], _e(r["id"][:8]), _e(rep._fmt_coord(r["lat"], exact)),
                     _e(rep._fmt_coord(r["lon"], exact)), _e(rep._fmt_z(r["score"])), _e(status),
                     _e(rep._fmt_conf(r)), "strong" if r["calib_strong"] else "", _e(terrain)))
        ctx = []
        if r.get("known_site_en"):
            ctx.append("Known site: %s" % _e(r["known_site_en"]))
        if r.get("ind_label_en"):
            ctx.append("Industry: %s" % _e(r["ind_label_en"]))
        fa = " \u00b7 ".join(_e(x) for x in (r.get("known_site_fa"), r.get("ind_label_fa")) if x)
        if ctx or fa:
            P.append("<tr style='background:%s'><td></td><td colspan='8' class='ctx'>%s%s</td></tr>" % (
                bg, " \u00b7 ".join(ctx), ("<br><span dir='rtl'>%s</span>" % fa) if fa else ""))
    if not rows:
        P.append("<tr><td colspan='9'>No candidates / \u0628\u062f\u0648\u0646 \u0646\u0627\u0645\u0632\u062f</td></tr>")
    P.append("</table>")
    return "".join(P)


def layers_grid(results: List[Dict[str, Any]], rows_by_id: Dict[str, Dict[str, Any]], exact: bool) -> str:
    from ariyan_win import reportlayers as rl
    n_img = sum(1 for r in results for l in r.get("layers", []) if l.get("uri") and l["product"] != "RELIEF")
    P = ["<h2>Satellite layers of the leading candidates (%s) / <span dir='rtl'>\u0644\u0627\u06cc\u0647\u200c\u0647\u0627\u06cc "
         "\u0645\u0627\u0647\u0648\u0627\u0631\u0647\u200c\u0627\u06cc \u0646\u0627\u0645\u0632\u062f\u0647\u0627\u06cc "
         "\u067e\u06cc\u0634\u0631\u0648</span></h2>" % rl.VERSION,
         "<p class='small'>Relief and every layer saved on this computer for each candidate\u2019s \u00b11 km window, "
         "with scene date, clear share and value range. Missing layers are named, not hidden. Saved images only; "
         "nothing was fetched. %d satellite picture%s.</p>" % (n_img, "" if n_img == 1 else "s")]
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
        cells = []
        for l in r["layers"]:
            if l.get("uri"):
                cells.append("<td class='fig' width='16%%'><img src='%s' width='118' height='118'><br><b>%s</b><br>%s</td>"
                             % (l["uri"], _e(l["label"]), _e(l.get("note") or "")))
            else:
                why = {"NOT_SAVED": "not saved yet", "HIDDEN": "hidden: %s" % (l.get("reason") or "quality check"),
                       "ERROR": "error: %s" % (l.get("reason") or "")}.get(l["state"], l["state"])
                cells.append("<td class='fig miss' width='16%%'><b>%s</b><br><br>%s</td>" % (_e(l["label"]), _e(why)))
        P.append("<table class='g' width='100%' cellspacing='3' cellpadding='4'>")
        for i in range(0, len(cells), 6):
            P.append("<tr>%s</tr>" % "".join(cells[i:i + 6]))
        P.append("</table>")
    return "".join(P)


PDF_STYLE = ("<style>body{font-family:'Segoe UI',Tahoma,sans-serif;font-size:9pt;color:#111}"
             "h1{font-size:15pt;color:#0B3D2E}h2{font-size:11.5pt;color:#0B3D2E;margin-top:12px}"
             "h3{font-size:10pt;margin-top:8px}.banner{background:#fee;color:#900;font-weight:bold}"
             ".caveat{background:#f4f4f4}.small{color:#555;font-size:8pt}"
             "table.c{font-size:7.5pt;border-collapse:collapse}table.c th{background:#0B3D2E;color:#fff;text-align:left}"
             ".ctx{color:#444;font-size:7pt}.fa{font-family:Tahoma,'Segoe UI',sans-serif}"
             "td.fig{font-size:7pt;vertical-align:top;border:1px solid #ccc}"
             "td.miss{color:#888;background:#f2f2f2}table.kv td{padding:1px 8px 1px 0;vertical-align:top}"
             "td.k{font-weight:bold;color:#333;width:24%}</style>")


def pdf_html(built: Dict[str, Any], results: List[Dict[str, Any]], html_name: str, html_md5: str) -> str:
    info, rows = built["info"], built["rows"]
    page = built["html"]
    # the wide web table is replaced by the page-friendly one
    page = re.sub(r"<h2>Candidates / .*?</table></div>", lambda m: candidate_table(info, rows), page, count=1,
                  flags=re.S)
    page = re.sub(r"<style>.*?</style>", PDF_STYLE, page, count=1, flags=re.S)

    def kv(m):                                   # definition lists read better as a two-column table here
        pairs = re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", m.group(1), flags=re.S)
        rows = []
        for k, v in pairs:
            if re.search("[\u0600-\u06ff]", k):    # Persian: the key on the right, read right to left
                rows.append("<tr><td align='right' dir='rtl'>%s</td><td class='k' align='right' dir='rtl'>%s</td></tr>"
                            % (v, k))
            else:
                rows.append("<tr><td class='k'>%s</td><td>%s</td></tr>" % (k, v))
        return "<table class='kv' width='100%%'>%s</table>" % "".join(rows)
    page = re.sub(r"<dl>(.*?)</dl>", kv, page, flags=re.S)
    head = ("<p class='small'>PDF copy (%s) of %s \u00b7 HTML MD5 %s. The PDF\u2019s own MD5 is recorded on the "
            "project timeline with the HTML\u2019s.</p>" % (VERSION, _e(html_name), _e(html_md5)))
    page = page.replace("<body>", "<body>" + head, 1)
    grid = layers_grid(results, {r["id"]: r for r in rows}, info["exact_coords"])
    k = page.rfind("</body>")
    return page[:k] + grid + page[k:]


def write_pdf(page_html: str, path: str, title: str = "ARIYAN GEO AI report") -> int:
    """Lays the HTML out on landscape A4 pages and writes the PDF; returns the page count."""
    from PySide6 import QtCore, QtGui
    res: Dict[str, str] = {}

    def sub(m):
        k = "ariyan-img-%d" % len(res)
        res[k] = m.group(1)
        return "src='%s'" % k
    body = re.sub(r"src='data:image/png;base64,([^']+)'", sub, page_html)
    doc = QtGui.QTextDocument()
    doc.setDocumentMargin(0)
    f = QtGui.QFont("Segoe UI")
    f.setPointSizeF(9.5)
    doc.setDefaultFont(f)
    for k, b in res.items():
        doc.addResource(QtGui.QTextDocument.ImageResource, QtCore.QUrl(k),
                        QtGui.QImage.fromData(base64.b64decode(b), "PNG"))
    doc.setHtml(body)
    w = QtGui.QPdfWriter(path)
    w.setTitle(title)
    w.setCreator("ARIYAN GEO AI")
    w.setPageSize(QtGui.QPageSize(QtGui.QPageSize.A4))
    w.setPageOrientation(QtGui.QPageLayout.Landscape)
    w.setPageMargins(QtCore.QMarginsF(12, 10, 12, 12), QtGui.QPageLayout.Millimeter)
    w.setResolution(144)
    doc.print_(w)
    del w                                         # closes the file
    with open(path, "rb") as fh:
        return len(re.findall(rb"/Type\s*/Page[^s]", fh.read()))
