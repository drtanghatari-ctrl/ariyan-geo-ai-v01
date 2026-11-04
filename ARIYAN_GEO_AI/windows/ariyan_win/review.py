"""
REPORT & ARCHIVE and ANALYSIS & MODELS tabs (win-w4c, 2026-11-03).

Review: every candidate of the project, filtered by job / status / band / id,
best first, each with the "same place as earlier candidate ..." note (another
candidate within one DEM cell, 30 m; a note only, nothing is merged). Your
judgement -- Supported, Rejected, Inconclusive, Open, or Auto (hand back to the
automatic review) -- is recorded with your reason by the phone's own
grand_project_review.set_candidate_status (history kept, timeline event).
Reports: the phone's own job report (HTML + CSV with MD5s, provenance check,
REPORT_EXPORTED on the timeline); Export Results writes every candidate as CSV
and GeoJSON. Analysis & Models lists the rules and models in use, read from the
code and the database (mission_control.models_json) plus the calib-v1 report.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ariyan_win import qtwork, widgets, workstation

ACCENT, TEAL, GOLD, ORANGE, ROSE, MUTED = "#3FB68B", "#2FA6B8", "#F2C14E", "#D9822B", "#E0607E", "#8B9BB0"
STATUS_NAMES = {"GENERATED": "Open", "SUPPORTED": "Supported", "REJECTED": "Rejected", "INCONCLUSIVE": "Inconclusive"}


def _gid(root):
    import grand_project_sync as gps
    return str(gps.get_or_create_default_grand_project(root))


class ReportArchive(QtWidgets.QWidget):
    def __init__(self, root: str, open_final_image, parent=None):
        super().__init__(parent)
        self.root, self.open_final_image = root, open_final_image
        self.offset = 0
        self.cid: Optional[str] = None
        v = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        f = QtWidgets.QHBoxLayout()
        self.job = QtWidgets.QComboBox()
        self.job.addItem("All jobs", None)
        self.status = QtWidgets.QComboBox()
        for k, n in (("", "Any status"), ("GENERATED", "Open"), ("SUPPORTED", "Supported"), ("REJECTED", "Rejected"),
                     ("INCONCLUSIVE", "Inconclusive")):
            self.status.addItem(n, k)
        self.band = QtWidgets.QComboBox()
        for k in ("", "SUBSTANTIAL", "HIGH", "MODERATE", "LOW", "NOT_RATED"):
            self.band.addItem(k.replace("_", " ").capitalize() or "Any band", k)
        self.find = QtWidgets.QLineEdit()
        self.find.setPlaceholderText("id starts with\u2026")
        for w in (self.job, self.status, self.band, self.find):
            f.addWidget(w)
        left.addLayout(f)
        for w in (self.job, self.status, self.band):
            w.currentIndexChanged.connect(lambda *_: self.load(0))
        self.find.returnPressed.connect(lambda: self.load(0))
        self.count = QtWidgets.QLabel("")
        left.addWidget(self.count)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "Lat", "Lon", "Confidence", "Status", "Same place as"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self._picked)
        self.table.itemDoubleClicked.connect(lambda it: self.open_final_image(it.data(QtCore.Qt.UserRole)))
        left.addWidget(self.table, 1)
        pg = QtWidgets.QHBoxLayout()
        self.prev = QtWidgets.QPushButton("\u2039 Previous 100")
        self.next = QtWidgets.QPushButton("Next 100 \u203a")
        self.prev.clicked.connect(lambda: self.load(max(0, self.offset - 100)))
        self.next.clicked.connect(lambda: self.load(self.offset + 100))
        pg.addWidget(self.prev)
        pg.addWidget(self.next)
        pg.addStretch(1)
        rep = QtWidgets.QPushButton("Generate job report\u2026")
        rep.clicked.connect(self.generate_report)
        exp = QtWidgets.QPushButton("Export all results (CSV + GeoJSON)")
        exp.clicked.connect(self.export_results)
        pg.addWidget(rep)
        pg.addWidget(exp)
        left.addLayout(pg)
        v.addLayout(left, 3)
        right = QtWidgets.QVBoxLayout()
        self.detail = QtWidgets.QTextBrowser()
        right.addWidget(self.detail, 1)
        rb = QtWidgets.QGridLayout()
        for i, (key, name, col) in enumerate((("SUPPORTED", "Supported", ACCENT), ("REJECTED", "Rejected", ROSE),
                                              ("INCONCLUSIVE", "Inconclusive", GOLD), ("OPEN", "Open", TEAL),
                                              ("AUTO", "Hand back to Auto", MUTED))):
            b = QtWidgets.QPushButton(name)
            b.setStyleSheet("color:%s;" % col)
            b.clicked.connect(lambda _=False, k=key: self._review(k))
            rb.addWidget(b, i // 3, i % 3)
        right.addLayout(rb)
        fi = QtWidgets.QPushButton("Open its Final Image \u2197")
        fi.clicked.connect(lambda: self.cid and self.open_final_image(self.cid))
        right.addWidget(fi)
        right.addWidget(QtWidgets.QLabel("Your judgement is recorded with your reason; the history is kept and the "
                                         "Steward's band is never changed by a review."))
        v.addLayout(right, 2)
        self._jobs_loaded = False
        self.load(0)

    def _load_jobs(self):
        import wide_area_search_mobile as wa
        rows = json.loads(wa.list_wide_area_search_jobs_json(self.root, _gid(self.root)))
        cur = self.job.currentData()
        self.job.blockSignals(True)
        self.job.clear()
        self.job.addItem("All jobs", None)
        for j in rows:
            self.job.addItem("%s (%d tiles)" % (j["title"], j["n_tiles"]), j["id"])
        if cur:
            i = self.job.findData(cur)
            self.job.setCurrentIndex(max(0, i))
        self.job.blockSignals(False)
        self._jobs_loaded = True

    def load(self, offset: int = 0):
        if not self._jobs_loaded:
            try:
                self._load_jobs()
            except Exception:
                pass
        self.offset = offset
        args = (self.root, self.job.currentData(), self.status.currentData(), self.band.currentData(),
                self.find.text(), offset)
        qtwork.run_async(workstation.candidate_page, self._shown, *args)

    def _shown(self, r: Dict[str, Any]):
        if "error" in r:
            self.count.setText(r["error"])
            return
        self.table.setRowCount(0)
        for i, c in enumerate(r["rows"]):
            self.table.insertRow(i)
            band = c.get("confidence_band") or "NOT_RATED"
            same = ", ".join("%s (%.0f m)" % (x["id"][:8], x["distance_m"]) for x in c["same_place"][:2])
            vals = [c["id"][:8], "%.5f" % c["lat"], "%.5f" % c["lon"],
                    band.replace("_", " ").capitalize() + ("" if c.get("confidence_numeric") is None else " %.2f" % c["confidence_numeric"]),
                    STATUS_NAMES.get(c["status"], c["status"]), same]
            for j, val in enumerate(vals):
                it = QtWidgets.QTableWidgetItem(val)
                it.setData(QtCore.Qt.UserRole, c["id"])
                if j == 3:
                    it.setForeground(QtGui.QColor(widgets.BAND_COLOURS.get(band, "#E6EDF3")))
                if j == 5 and same:
                    it.setForeground(QtGui.QColor(GOLD))
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        want = getattr(self, "pending_select", None)
        self.pending_select = None
        if want:
            for i in range(self.table.rowCount()):
                if self.table.item(i, 0).data(QtCore.Qt.UserRole) == want:
                    self.table.selectRow(i)
                    break
        self.count.setText("%s candidate(s); showing %d\u2013%d" % ("{:,}".format(r["total"]), r["offset"] + 1 if r["rows"] else 0,
                                                                  r["offset"] + len(r["rows"])))
        self.prev.setEnabled(r["offset"] > 0)
        self.next.setEnabled(r["offset"] + len(r["rows"]) < r["total"])

    def _picked(self):
        it = self.table.selectedItems()
        if not it:
            return
        self.cid = it[0].data(QtCore.Qt.UserRole)
        from ariyan_win.stewardui import focus_candidate
        focus_candidate(self.cid, self)
        import grand_project_query_mobile as q
        cid = self.cid
        qtwork.run_async(lambda: {"d": json.loads(q.get_candidate_detail_json(self.root, cid)),
                                  "same": workstation.same_place(self.root, cid)},
                         lambda r, c=cid: self._detail(c, r))

    def _detail(self, cid, r):
        if cid != self.cid:
            return
        if "error" in r:
            self.detail.setPlainText(r["error"])
            return
        d = r["d"]
        if "error" in d:
            self.detail.setPlainText(d["error"])
            return
        c = d.get("candidate") or {}
        band = c.get("confidence_band") or "NOT_RATED"
        html = ["<h3>Candidate %s</h3>" % cid[:8],
                "<p>%.6f, %.6f \u00b7 <b style='color:%s'>%s%s</b> \u00b7 %s \u00b7 |z| %s</p>" % (
                    c.get("lat", 0), c.get("lon", 0), widgets.BAND_COLOURS.get(band, "#E6EDF3"), band.replace("_", " ").capitalize(),
                    "" if c.get("confidence_numeric") is None else " %.2f" % c["confidence_numeric"],
                    STATUS_NAMES.get(c.get("status"), c.get("status")),
                    "" if c.get("score") is None else "%.1f" % abs(c["score"]))]
        if r["same"]:
            html.append("<p style='color:%s'><b>Same place as earlier candidate(s):</b> %s \u2014 a repeat of the same "
                        "spot; both are kept.</p>" % (GOLD, ", ".join("%s (%.0f m, %s)" % (
                            x["id"][:8], x["distance_m"], STATUS_NAMES.get(x["status"], x["status"])) for x in r["same"])))
        rv = d.get("review") or {}
        if rv:
            html.append("<p><b>Review:</b> %s%s%s</p>" % (rv.get("status_label") or rv.get("status"),
                                                        (" (%s)" % rv["review_source"]) if rv.get("review_source") else "",
                                                           (" \u00b7 job trust: %s" % rv["job_trust"]) if rv.get("job_trust") else ""))
        ev = d.get("evidence") or []
        html.append("<p><b>Evidence linked (%d):</b></p><ul>%s</ul>" % (len(ev), "".join(
            "<li>%s \u2014 %s</li>" % (e.get("evidence_type"), e.get("relation")) for e in ev)))
        ch = d.get("confidence_history") or []
        if ch:
            last = ch[-1]
            reasons = last.get("reasoning_snapshot") or last.get("reasoning_snapshot_json") or []
            if isinstance(reasons, str):
                try:
                    reasons = json.loads(reasons)
                except ValueError:
                    reasons = [reasons]
            html.append("<p><b>Steward:</b></p><ul>%s</ul>" % "".join("<li>%s</li>" % x for x in (reasons or [])[:8]))
        inv = d.get("investigation") or {}
        if inv:
            html.append("<p style='color:%s'>Investigation %s \u00b7 %s</p>" % (MUTED, str(inv.get("id", ""))[:8],
                                                                              (inv.get("created_at") or "")[:16]))
        self.detail.setHtml("".join(html))

    def _review(self, key):
        if not self.cid:
            return
        reason, ok = QtWidgets.QInputDialog.getText(self, "Review %s" % self.cid[:8],
                                                    "Your reason (kept on record):")
        if not ok:
            return
        if key != "AUTO" and not reason.strip():
            QtWidgets.QMessageBox.information(self, "Reason needed", "Please give a short reason; it is kept with the "
                                              "review.")
            return
        import grand_project_query_mobile as q
        r = json.loads(q.set_candidate_status_json(self.root, self.cid, key, reason.strip()))
        if "error" in r:
            QtWidgets.QMessageBox.warning(self, "Not recorded", r["error"])
            return
        self.load(self.offset)
        self._picked()

    def generate_report(self):
        if not self.job.currentData():
            QtWidgets.QMessageBox.information(self, "Choose a job", "Choose the job to report on in the first list.")
            return
        n, ok = QtWidgets.QInputDialog.getInt(self, "Job report", "How many candidates (0 = all)?", 50, 0, 100000)
        if not ok:
            return
        exact = QtWidgets.QMessageBox.question(
            self, "Coordinates", "Put exact coordinates in the report?\n\nNo = rounded (safer to share; sites can be "
            "looted).") == QtWidgets.QMessageBox.Yes
        jid = self.job.currentData()
        from ariyan_win import reportlayers                       # u4: the report carries every saved layer

        def make():
            try:
                return reportlayers.export_job_report_with_layers(self.root, _gid(self.root), jid, n, exact)
            except Exception as e:
                return {"error": "%s: %s" % (type(e).__name__, e)}
        self.count.setText("Writing the job report with the satellite layers of its leading candidates\u2026")
        qtwork.run_async(make, self._reported)

    def _reported(self, r):
        if "error" in r:
            QtWidgets.QMessageBox.warning(self, "No report", r["error"])
            return
        QtWidgets.QMessageBox.information(self, "Report written", r.get("summary_text") or json.dumps(r, indent=1))
        if r.get("html_path"):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(r["html_path"]))

    def export_results(self):
        qtwork.run_async(workstation.export_results, self._exported, self.root)

    def _exported(self, r):
        if "error" in r:
            QtWidgets.QMessageBox.warning(self, "Not exported", r["error"])
            return
        QtWidgets.QMessageBox.information(self, "Results exported", "%s candidates\n%s\n%s\n\n%s" % (
            "{:,}".format(r["rows"]), r["csv"], r["geojson"], r["note"]))


class AnalysisModels(QtWidgets.QWidget):
    def __init__(self, root: str, parent=None):
        super().__init__(parent)
        self.root = root
        v = QtWidgets.QVBoxLayout(self)
        self.text = QtWidgets.QTextBrowser()
        v.addWidget(self.text, 1)
        b = QtWidgets.QPushButton("Refresh")
        b.clicked.connect(self.load)
        v.addWidget(b)
        self.load()

    def load(self):
        import mission_control as mc

        def get():
            m = json.loads(mc.models_json(self.root))
            calib = None
            try:
                import grand_project_query_mobile as q
                if hasattr(q, "calib_profile_report_json"):
                    calib = json.loads(q.calib_profile_report_json(self.root, _gid(self.root)))
            except Exception as e:
                calib = {"error": str(e)}
            return {"models": m, "calib": calib}
        qtwork.run_async(get, self._show)

    def _show(self, r):
        if "error" in r:
            self.text.setPlainText(r["error"])
            return
        m = r["models"]
        html = ["<h2>Analysis &amp; Models</h2><p style='color:%s'>%s</p>" % (MUTED, m.get("statement", ""))]
        for i, x in enumerate(m.get("models", [])):
            col = ["#2FA6B8", "#D9A62B", "#E0607E", "#3FB68B", "#9A7BFF", "#4C8DFF"][i % 6]
            html.append("<h3 style='color:%s'>%s <span style='font-size:9pt'>[%s]</span></h3><p>%s</p>"
                        "<p style='color:%s'>%s</p>" % (col, x["name"], x["version"], x["role"], MUTED, x["limits"]))
        c = r.get("calib")
        if isinstance(c, dict) and "error" not in c:
            html.append("<h3>calib-v1 profile report</h3><pre>%s</pre>" % json.dumps(c, indent=1, default=str)[:4000])
        self.text.setHtml("".join(html))
