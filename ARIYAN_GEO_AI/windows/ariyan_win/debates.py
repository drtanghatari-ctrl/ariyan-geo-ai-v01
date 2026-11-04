"""AI Debate Studio tab (win-w3a): every debate stored by dbr-v1, read-only
(mission_control.debates_json / debate_detail_json, the same as the phone's
AI Debate Engine screen)."""
from __future__ import annotations

import json
from typing import Any, Dict

from PySide6 import QtCore, QtWidgets

from ariyan_win import qtwork, widgets

FILTERS = [("ALL", "All"), ("LEADING_INTERPRETATION", "Leading"), ("CONTESTED", "Contested"),
           ("WEAK_SIGNAL", "Weak signal"), ("NO_DATA", "No data")]
NAMES = {"LEADING_INTERPRETATION": "Leading interpretation", "CONTESTED": "Contested", "WEAK_SIGNAL": "Weak signal",
         "NO_DATA": "No data"}
COLOURS = ["#2FA6B8", "#D9A62B", "#E0607E", "#3FB68B"]


class DebateStudio(QtWidgets.QWidget):
    def __init__(self, root: str, open_final_image, parent=None):
        super().__init__(parent)
        self.root, self.open_final_image = root, open_final_image
        self.agreement, self.offset = "ALL", 0
        v = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        row = QtWidgets.QHBoxLayout()
        self.buttons = {}
        for key, name in FILTERS:
            b = QtWidgets.QPushButton(name)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.set_filter(k))
            row.addWidget(b)
            self.buttons[key] = b
        row.addStretch(1)
        left.addLayout(row)
        self.summary = QtWidgets.QLabel("Reading stored debates\u2026")
        self.summary.setWordWrap(True)
        left.addWidget(self.summary)
        self.list = QtWidgets.QListWidget()
        self.list.currentItemChanged.connect(self._picked)
        left.addWidget(self.list, 1)
        self.more = QtWidgets.QPushButton("Load 50 more")
        self.more.clicked.connect(lambda: self.load(append=True))
        left.addWidget(self.more)
        v.addLayout(left, 2)
        right = QtWidgets.QVBoxLayout()
        self.detail_title = QtWidgets.QLabel("Choose a debate")
        self.detail_title.setWordWrap(True)
        self.detail_title.setStyleSheet("font-weight:700; font-size:12pt;")
        right.addWidget(self.detail_title)
        self.bars = widgets.Bars()
        right.addWidget(self.bars)
        self.detail = QtWidgets.QTextBrowser()
        right.addWidget(self.detail, 1)
        self.fi = QtWidgets.QPushButton("Open its Final Image \u2197")
        self.fi.setEnabled(False)
        self.fi.clicked.connect(lambda: self.open_final_image(self._cid))
        right.addWidget(self.fi)
        v.addLayout(right, 3)
        self._cid = None
        self.set_filter("ALL")

    def set_filter(self, key: str):
        self.agreement = key
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        self.load(append=False)

    def load(self, append: bool):
        import mission_control as mc
        if not append:
            self.offset = 0
            self.list.clear()
        self._req = getattr(self, "_req", 0) + 1         # only the newest request may fill the list
        req, want, off = self._req, self.agreement, self.offset
        qtwork.run_async(lambda: json.loads(mc.debates_json(self.root, want, 50, off)),
                         lambda r, q=req, a=append: self._loaded(q, a, r))

    def _loaded(self, req: int, append: bool, o: Dict[str, Any]):
        if req != self._req:
            return
        if "error" in o:
            self.summary.setText(o["error"])
            return
        s = o.get("summary") or {}
        if not append:
            if not s or not s.get("debates"):
                self.summary.setText(o.get("note") or "No debates stored yet.")
            else:
                lead = ", ".join("%s %d" % (k, v) for k, v in sorted((s.get("by_leading") or {}).items(), key=lambda x: -x[1]))
                agr = ", ".join("%s %d" % (NAMES.get(k, k), v) for k, v in (s.get("by_agreement") or {}).items() if v)
                capped = (" \u00b7 the Steward capped %d of %d" % (s["steward_capped"], s["steward_rated"])
                          if s.get("steward_rated") else "")
                self.summary.setText("%d debate(s) on %d candidate(s) \u00b7 leading: %s \u00b7 %s%s\n%s" % (
                    s["debates"], s["candidates"], lead, agr, capped, o.get("statement", "")))
        for r in o.get("rows", []):
            it = QtWidgets.QListWidgetItem("%s \u00b7 %s \u00b7 %s \u00b7 Steward %s%s \u00b7 %s" % (
                r["candidate_id"][:8], r.get("leading") or "no leading view", NAMES.get(r.get("agreement"), ""),
                r.get("steward_band") or "not rated", " (capped)" if r.get("steward_capped") else "",
                (r.get("recorded_at") or "")[:16].replace("T", " ")))
            it.setData(QtCore.Qt.UserRole, r["id"])
            self.list.addItem(it)
        self.offset += len(o.get("rows", []))
        self.more.setVisible(bool(o.get("more")))

    def _picked(self, it, _prev=None):
        if it is None:
            return
        import mission_control as mc
        rid = it.data(QtCore.Qt.UserRole)
        qtwork.run_async(lambda: json.loads(mc.debate_detail_json(self.root, rid)), self._show)

    def _show(self, d: Dict[str, Any]):
        if d.get("candidate_id"):
            from ariyan_win.stewardui import focus_candidate
            focus_candidate(d["candidate_id"], self)
        if "error" in d:
            self.detail.setPlainText(d["error"])
            return
        self._cid = d["candidate_id"]
        self.fi.setEnabled(True)
        c = d.get("candidate") or {}
        syn = d.get("synthesis") or {}
        self.detail_title.setText("Candidate %s \u00b7 %.5f, %.5f \u00b7 %s \u00b7 %s" % (
            d["candidate_id"][:8], c.get("lat") or 0, c.get("lon") or 0, c.get("status") or "",
            NAMES.get(syn.get("agreement_level"), "")))
        self.bars.set([(p.get("perspective", "?"), float(p.get("confidence_score") or 0), COLOURS[i % 4])
                       for i, p in enumerate(d.get("positions") or []) if not p.get("insufficient_data")])
        html = []
        if syn.get("steward_note"):
            html.append("<p><i>%s</i></p>" % syn["steward_note"])
        for i, p in enumerate(d.get("positions") or []):
            html.append("<h4 style='color:%s'>%s</h4>" % (COLOURS[i % 4], p.get("perspective", "").upper()))
            if p.get("insufficient_data"):
                html.append("<p>Insufficient data to argue a position.</p>")
                continue
            html.append("<p><b>%s</b> (%.2f, %s)</p><ul>%s</ul>" % (
                p.get("stance"), p.get("confidence_score") or 0, p.get("confidence_label"),
                "".join("<li>%s</li>" % r for r in p.get("reasoning") or [])))
        st = d.get("steward") or {}
        html.append("<h4 style='color:#F2C14E'>STEWARD (the judge)</h4>")
        if st.get("band"):
            html.append("<p><b>%s %.2f</b>%s</p>" % (st["band"], st.get("numeric") or 0,
                        " (capped from %.2f)" % st["raw"] if st.get("capped") and st.get("raw") is not None else ""))
        html.append("<ul>%s</ul>" % "".join("<li>%s</li>" % r for r in st.get("reasoning") or []))
        html.append("<p style='color:#8B9BB0'>%s</p>" % d.get("statement", ""))
        self.detail.setHtml("".join(html))
