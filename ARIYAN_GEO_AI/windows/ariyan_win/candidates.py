"""
Candidate search, groups and interpretation (win-u2, 2026-11-04), shared by the
INVESTIGATION -> Wide-area jobs tab and the GRAND PROJECT -> Candidates tab.

  CandidateSearch       ID, name (job title or known site) or coordinate; optionally
                        only the job selected next to it (workstation.search_candidates)
  GroupInterpretation   the selected candidate's group (same job, chained within
                        300 m, workstation.candidate_group) and, for the member you
                        click, its interpretation: Steward band and words, the stored
                        debate (every perspective's stance and reasons, the synthesis
                        note), the investigation summary, your reviews, evidence,
                        known-site and same-place notes (workstation.interpretation)

Read-only: nothing here changes a status, review, confidence or evidence row.
"""
from __future__ import annotations

import html
from typing import Any, Callable, Dict, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ariyan_win import qtwork, workstation

ACCENT, TEAL, GOLD, ORANGE, ROSE, MUTED = "#3FB68B", "#2FA6B8", "#F2C14E", "#D9822B", "#E0607E", "#8B9BB0"
BAND = {"SUBSTANTIAL": "#2E7D32", "HIGH": "#3FB68B", "MODERATE": "#D9A62B", "LOW": "#D9822B", "NO_DATA": "#6E7681",
        "NOT_RATED": "#8B9BB0"}
STATUS = {"GENERATED": "Open", "SUPPORTED": "Supported", "REJECTED": "Rejected", "INCONCLUSIVE": "Inconclusive"}
AGREEMENT = {"LEADING_INTERPRETATION": "Leading interpretation", "CONTESTED": "Contested",
             "WEAK_SIGNAL": "Weak signal", "NO_DATA": "No data"}


def _e(t) -> str:
    return html.escape(str(t if t is not None else ""))


def _conf(band: str, numeric) -> str:
    return (band or "NOT_RATED").replace("_", " ").title() + ("" if numeric is None else " %.2f" % numeric)


def _title(text: str, colour: str) -> QtWidgets.QLabel:
    w = QtWidgets.QLabel(text)
    w.setObjectName("h")
    w.setStyleSheet("color: %s;" % colour)
    w.setWordWrap(True)
    return w


class CandidateSearch(QtWidgets.QFrame):
    picked = QtCore.Signal(str)
    opened = QtCore.Signal(str)

    def __init__(self, root: str, job_id: Optional[Callable[[], Optional[str]]] = None, parent=None):
        super().__init__(parent)
        self.root = root
        self._job_id = job_id
        self.setObjectName("panel")
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.addWidget(_title("\u2315  FIND A CANDIDATE \u00b7 ID, name or coordinate", ACCENT))
        row = QtWidgets.QHBoxLayout()
        self.edit = QtWidgets.QLineEdit()
        self.edit.setPlaceholderText("090689e5  \u00b7  Hasanlu  \u00b7  36.9532, 45.5245  (add , 500 m)")
        self.edit.setClearButtonEnabled(True)
        self.edit.returnPressed.connect(self.run)
        row.addWidget(self.edit, 1)
        b = QtWidgets.QPushButton("Search")
        b.setObjectName("primary")
        b.clicked.connect(self.run)
        row.addWidget(b)
        v.addLayout(row)
        self.only_job = None
        if job_id is not None:
            self.only_job = QtWidgets.QCheckBox("Only the selected job")
            self.only_job.setChecked(True)
            self.only_job.toggled.connect(lambda _: self.run() if self.edit.text().strip() else None)
            v.addWidget(self.only_job)
        self.note = QtWidgets.QLabel("Search every candidate of the project.")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: %s;" % MUTED)
        v.addWidget(self.note)
        self.list = QtWidgets.QListWidget()
        self.list.setMinimumHeight(140)
        self.list.itemClicked.connect(lambda it: self.picked.emit(it.data(QtCore.Qt.UserRole)))
        self.list.itemDoubleClicked.connect(lambda it: self.opened.emit(it.data(QtCore.Qt.UserRole)))
        v.addWidget(self.list, 1)

    def run(self):
        q = self.edit.text().strip()
        self.list.clear()
        if not q:
            self.note.setText("Type an ID, a name or a coordinate.")
            return
        jid = self._job_id() if (self._job_id and self.only_job is not None and self.only_job.isChecked()) else None
        if self.only_job is not None and self.only_job.isChecked() and not jid:
            self.note.setText("Select a job on the left first, or untick \u201cOnly the selected job\u201d.")
            return
        self.note.setText("Searching\u2026")
        qtwork.run_async(workstation.search_candidates, lambda r, q=q: self._show(q, r), self.root, q, 60, jid)

    def _show(self, q: str, r: Dict[str, Any]):
        if q != self.edit.text().strip():
            return
        self.list.clear()
        if isinstance(r, dict) and "error" in r and "rows" not in r:
            self.note.setText(r["error"])
            return
        rows = r.get("rows") or []
        self.note.setText("%s  %d found. Click to see its group and interpretation; double-click for its Final "
                          "Image." % (r.get("note", ""), len(rows)))
        for x in rows:
            it = QtWidgets.QListWidgetItem("%s   %.5f, %.5f   %s \u00b7 %s\n      %s" % (
                x["id"][:8], x["lat"], x["lon"], _conf(x["band"], x.get("confidence_numeric")),
                STATUS.get(x.get("status"), x.get("status")), x.get("match") or ""))
            it.setData(QtCore.Qt.UserRole, x["id"])
            it.setForeground(QtGui.QColor(BAND.get(x["band"], "#E6EDF3") if x["band"] != "NOT_RATED" else "#E6EDF3"))
            it.setToolTip("Candidate %s\nJob: %s" % (x["id"], x.get("job_title") or "\u2014"))
            self.list.addItem(it)


def interpretation_html(d: Dict[str, Any]) -> str:
    if "error" in d:
        return "<p style='color:%s'>%s</p>" % (ROSE, _e(d["error"]))
    band = d.get("band") or "NOT_RATED"
    out = ["<h3 style='margin:0'>Candidate %s</h3>" % _e(d["id"][:8]),
           "<p style='color:%s'>%.6f N, %.6f E%s</p>" % (MUTED, d["lat"], d["lon"],
                                                        (" \u00b7 job " + _e(d["job_title"])) if d.get("job_title") else ""),
           "<p><b style='color:%s'>Steward: %s</b> \u00b7 status <b>%s</b> \u00b7 anomaly |z| %s%s</p>" % (
               BAND.get(band, GOLD), _e(_conf(band, d.get("numeric"))), _e(STATUS.get(d.get("status"), d.get("status"))),
               "\u2014" if d.get("z") is None else "%.1f" % abs(d["z"]), " (calib-v1 strong)" if d.get("calib_strong") else "")]
    lines = d.get("steward_lines") or []
    out.append("<p style='color:%s'><b>THE STEWARD\u2019S REASONING</b></p>" % GOLD)
    out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % _e(x) for x in lines) if lines else
               "<p style='color:%s'>No reasoning recorded yet.</p>" % MUTED)
    deb = d.get("debate")
    out.append("<p style='color:%s'><b>AI DEBATE (stored)</b></p>" % ROSE)
    if not deb:
        out.append("<p style='color:%s'>No debate stored for this candidate (debates are kept from 2026-10-31 on)."
                   "</p>" % MUTED)
    else:
        syn = deb.get("synthesis") or {}
        out.append("<p><b>%s</b> \u00b7 leading: %s</p>" % (_e(AGREEMENT.get(syn.get("agreement_level"), "?")),
                                                          _e(syn.get("leading_position") or "none")))
        if syn.get("steward_note"):
            out.append("<p><i>%s</i></p>" % _e(syn["steward_note"]))
        for p in deb.get("positions") or []:
            if p.get("insufficient_data"):
                out.append("<p style='color:%s'>%s \u2014 not enough data to argue a position.</p>" % (
                    MUTED, _e(p.get("perspective"))))
                continue
            out.append("<p><b>%s</b> \u2014 %s (%.2f, %s)</p>" % (_e(p.get("perspective")), _e(p.get("stance")),
                       float(p.get("confidence_score") or 0), _e(p.get("confidence_label") or "")))
            rs = p.get("reasoning") or []
            if rs:
                out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % _e(x) for x in rs[:6]))
        st = deb.get("steward") or {}
        if st.get("band"):
            out.append("<p><b style='color:%s'>Scientific judge: %s %.2f%s</b></p>" % (
                BAND.get(st["band"], GOLD), _e(st["band"].title()), st.get("numeric") or 0,
                "  (capped from %.2f)" % st["raw"] if st.get("capped") and st.get("raw") is not None else ""))
        out.append("<p style='color:%s'>A ranked rule-based opinion, not proof; the Steward\u2019s band is what "
                   "counts.</p>" % MUTED)
    if d.get("investigation_summary"):
        out.append("<p style='color:%s'><b>INVESTIGATION SUMMARY</b></p><p>%s</p>" % (TEAL,
                   _e(d["investigation_summary"])))
    if d.get("hypothesis"):
        out.append("<p style='color:%s'><b>LINKED HYPOTHESIS</b></p><p>%s</p>" % (TEAL, _e(d["hypothesis"])))
    ev = d.get("evidence") or {}
    out.append("<p style='color:%s'><b>EVIDENCE</b></p>" % ACCENT)
    out.append("<ul>%s</ul>" % "".join("<li>%s \u2014 %s</li>" % (_e(et.replace("_", " ").title()), _e(", ".join(
        "%s %d" % (k, v) for k, v in sorted(ev[et].items())))) for et in sorted(ev)) if ev else
               "<p style='color:%s'>No evidence linked yet.</p>" % MUTED)
    rv = d.get("reviews") or []
    if rv:
        out.append("<p style='color:%s'><b>YOUR REVIEWS</b></p><ul>%s</ul>" % (ACCENT, "".join(
            "<li>%s: %s \u2192 %s \u2014 %s</li>" % (_e((r.get("reviewed_at") or "")[:16].replace("T", " ")),
                                                   _e(STATUS.get(r.get("previous_status"), r.get("previous_status"))),
                                                   _e(STATUS.get(r.get("new_status"), r.get("new_status"))),
                                                   _e(r.get("reason"))) for r in rv)))
    if d.get("known_site"):
        out.append("<p style='color:%s'>%s</p>" % (MUTED, _e(d["known_site"])))
    if d.get("same_place"):
        out.append("<p style='color:%s'>Same place as earlier candidate(s): %s</p>" % (GOLD, _e(", ".join(
            "%s (%.0f m)" % (x["id"][:8], x["distance_m"]) for x in d["same_place"][:5]))))
    return "".join(out)


class GroupInterpretation(QtWidgets.QSplitter):
    """Left: the selected candidate's group. Right: the interpretation of the member clicked."""
    opened = QtCore.Signal(str)

    def __init__(self, root: str, parent=None):
        super().__init__(QtCore.Qt.Horizontal, parent)
        self.root = root
        self.current: Optional[str] = None
        self.shown: Optional[str] = None
        gbox = QtWidgets.QFrame()
        gbox.setObjectName("panel")
        gl = QtWidgets.QVBoxLayout(gbox)
        gl.setContentsMargins(12, 10, 12, 10)
        gl.addWidget(_title("\u25ce  ITS GROUP OF CANDIDATES", TEAL))
        self.gnote = QtWidgets.QLabel("Pick a candidate to see the candidates lying together with it.")
        self.gnote.setWordWrap(True)
        self.gnote.setStyleSheet("color: %s;" % MUTED)
        gl.addWidget(self.gnote)
        self.group = QtWidgets.QListWidget()
        self.group.currentItemChanged.connect(lambda it, _p: it and self._interpret(it.data(QtCore.Qt.UserRole)))
        self.group.itemDoubleClicked.connect(lambda it: self.opened.emit(it.data(QtCore.Qt.UserRole)))
        gl.addWidget(self.group, 1)
        ibox = QtWidgets.QFrame()
        ibox.setObjectName("panel")
        il = QtWidgets.QVBoxLayout(ibox)
        il.setContentsMargins(12, 10, 12, 10)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(_title("\u2726  INTERPRETATION", GOLD), 1)
        self.fi = QtWidgets.QPushButton("Open its Final Image \u2197")
        self.fi.setEnabled(False)
        self.fi.clicked.connect(lambda: self.shown and self.opened.emit(self.shown))
        top.addWidget(self.fi)
        il.addLayout(top)
        self.text = QtWidgets.QTextBrowser()
        self.text.setOpenExternalLinks(True)
        il.addWidget(self.text, 1)
        self.addWidget(gbox)
        self.addWidget(ibox)
        self.setStretchFactor(0, 2)
        self.setStretchFactor(1, 3)

    def show_candidate(self, cid: str):
        if not cid:
            return
        self.current = cid
        self.group.clear()
        self.gnote.setText("Finding its group\u2026")
        qtwork.run_async(workstation.candidate_group, lambda r, c=cid: self._grouped(c, r), self.root, cid)
        self._interpret(cid)

    def _grouped(self, cid: str, r: Dict[str, Any]):
        if cid != self.current:
            return
        self.group.blockSignals(True)
        self.group.clear()
        if "error" in r:
            self.gnote.setText(r["error"])
            self.group.blockSignals(False)
            return
        m = r.get("members") or []
        self.gnote.setText("%d candidate%s. %s%s" % (len(m), "" if len(m) == 1 else "s", r.get("note", ""),
                                                     " (first %d shown)" % len(m) if r.get("capped") else ""))
        for x in m:
            label = "%s%s   %s \u00b7 %s   %s" % (
                "\u25b6 " if x["selected"] else "   ", x["id"][:8], _conf(x["band"], x.get("confidence_numeric")),
                STATUS.get(x.get("status"), x.get("status")),
                "selected" if x["selected"] else "%.0f m away" % x["distance_m"])
            it = QtWidgets.QListWidgetItem(label)
            it.setData(QtCore.Qt.UserRole, x["id"])
            if x["band"] != "NOT_RATED":
                it.setForeground(QtGui.QColor(BAND.get(x["band"], "#E6EDF3")))
            if x["selected"]:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            self.group.addItem(it)
            if x["selected"]:
                self.group.setCurrentItem(it)
        self.group.blockSignals(False)

    def _interpret(self, cid: str):
        self.shown = cid
        self.fi.setEnabled(True)
        self.text.setHtml("<p style='color:%s'>Reading\u2026</p>" % MUTED)
        qtwork.run_async(workstation.interpretation, lambda d, c=cid: c == self.shown and
                         self.text.setHtml(interpretation_html(d)), self.root, cid)


class CandidatesPage(QtWidgets.QSplitter):
    """GRAND PROJECT -> Candidates: search on the left, group and interpretation on the right."""

    def __init__(self, root: str, open_final_image: Optional[Callable[[str], None]] = None, parent=None):
        super().__init__(QtCore.Qt.Horizontal, parent)
        self.root = root
        self.search = CandidateSearch(root)
        self.view = GroupInterpretation(root)
        self.search.picked.connect(self.view.show_candidate)
        if open_final_image:
            self.search.opened.connect(open_final_image)
            self.view.opened.connect(open_final_image)
        self.addWidget(self.search)
        self.addWidget(self.view)
        self.setStretchFactor(0, 2)
        self.setStretchFactor(1, 5)
        self.setSizes([400, 960])
        self.view.setSizes([380, 580])

    def set_root(self, root: str):
        self.root = self.search.root = self.view.root = root


class CandidateDialog(QtWidgets.QDialog):
    """A candidate picked from a job's search: its group and interpretation in a window."""

    def __init__(self, root: str, cid: str, open_final_image=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Candidate %s \u2014 group and interpretation" % cid[:8])
        self.resize(1100, 680)
        v = QtWidgets.QVBoxLayout(self)
        self.view = GroupInterpretation(root)
        if open_final_image:
            self.view.opened.connect(open_final_image)
        v.addWidget(self.view, 1)
        b = QtWidgets.QPushButton("Close")
        b.clicked.connect(self.accept)
        v.addWidget(b, 0, QtCore.Qt.AlignRight)
        self.view.show_candidate(cid)
