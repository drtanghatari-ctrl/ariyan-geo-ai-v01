"""
Mission Control workstation (win-w1, 2026-11-03) -- the Windows mock-up, built on
real data only (LiDAR left out, as the user asked):

  left    investigation coordinate, the selected candidate's vital signs (real
          measures only), laboratory system health
  centre  data-source tiles, the 3D terrain of the selected candidate (its real
          DEM window, relief or any SAVED satellite layer as drape, the pins),
          every layer of the window (u1), cross-section A-A', subsurface/Surfer pointer
  right   final scientific assessment (gauge on the highest STORED confidence),
          evidence summary of the selected candidate, the Steward's own words
  bottom  candidate targets (click one to make it the selected candidate), map,
          scientific timeline, AI Debate Studio (the stored debate)

Nothing here changes a status, review, confidence or evidence row. If this
computer has no terrain tile for the candidate yet, the 3D card offers to fetch
that one public Copernicus tile (terrain_tile.ensure_tile).
"""
from __future__ import annotations

import os
import webbrowser
from typing import Any, Dict, List, Optional

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ariyan_win import qtwork, widgets, workstation

ACCENT = "#3FB68B"
TEAL = "#2FA6B8"
GOLD = "#F2C14E"
ORANGE = "#D9822B"
ROSE = "#E0607E"
MUTED = "#8B9BB0"
BAND = widgets.BAND_COLOURS
PERSPECTIVE = ["#2FA6B8", "#D9A62B", "#E0607E", "#3FB68B"]
AGREEMENT = {"LEADING_INTERPRETATION": "Leading interpretation", "CONTESTED": "Contested",
             "WEAK_SIGNAL": "Weak signal", "NO_DATA": "No data"}


def mc_status(s: Optional[str]) -> str:
    return {"GENERATED": "Open", "SUPPORTED": "Supported", "REJECTED": "Rejected",
            "INCONCLUSIVE": "Inconclusive"}.get(s or "", (s or "").title())


def lab(text: str = "", obj: str = "", wrap: bool = True, colour: Optional[str] = None, size: Optional[int] = None,
        bold: bool = False) -> QtWidgets.QLabel:
    w = QtWidgets.QLabel(text)
    if obj:
        w.setObjectName(obj)
    w.setWordWrap(wrap)
    css = []
    if colour:
        css.append("color: %s;" % colour)
    if size:
        css.append("font-size: %dpt;" % size)
    if bold:
        css.append("font-weight: 700;")
    if css:
        w.setStyleSheet(" ".join(css))
    return w


def panel(title: str, tint: str = ACCENT):
    f = QtWidgets.QFrame()
    f.setObjectName("panel")
    lay = QtWidgets.QVBoxLayout(f)
    lay.setContentsMargins(12, 10, 12, 10)
    lay.setSpacing(4)
    t = lab(title, "h", wrap=True)
    t.setStyleSheet("color: %s;" % tint)
    lay.addWidget(t)
    return f, lay


def clear(layout: QtWidgets.QLayout, keep: int = 0):
    while layout.count() > keep:
        it = layout.takeAt(keep)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            clear(it.layout())


STATUS_COLOURS = {"Supported": "#3FB68B", "Open": "#5B8DEF", "Inconclusive": "#D9A62B", "Rejected": "#E0607E"}


class ClickCard(QtWidgets.QFrame):
    """A panel that reacts to a click (layer cards, search results)."""
    clicked = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


def stat_tile(value: str, name: str, colour: str, tint: str) -> QtWidgets.QFrame:
    f = QtWidgets.QFrame()
    f.setObjectName("stat")
    f.setStyleSheet("QFrame#stat { background: %s; border-radius: 10px; }" % tint)
    v = QtWidgets.QVBoxLayout(f)
    v.setContentsMargins(8, 8, 8, 8)
    v.setSpacing(0)
    a = lab(value, wrap=False, colour=colour, size=17, bold=True)
    a.setAlignment(QtCore.Qt.AlignCenter)
    b = lab(name, wrap=False, colour=MUTED)
    b.setAlignment(QtCore.Qt.AlignCenter)
    v.addWidget(a)
    v.addWidget(b)
    return f


def chip(text: str, colour: str) -> QtWidgets.QLabel:
    c = QtGui.QColor(colour)
    w = QtWidgets.QLabel(text)
    w.setStyleSheet("QLabel { color: %s; font-weight: 700; border: 1px solid %s; border-radius: 12px; "
                    "padding: 3px 10px; background: rgba(%d,%d,%d,40); }" % (colour, colour, c.red(), c.green(),
                                                                            c.blue()))
    return w


def fmt(n) -> str:
    return "{:,}".format(n) if isinstance(n, int) else str(n)


class Workstation(QtWidgets.QScrollArea):
    def __init__(self, root: str, parent=None):
        super().__init__(parent)
        self.root = root
        self.mission: Dict[str, Any] = {}
        self.selected: Optional[str] = None
        self.terrain_data: Dict[str, Any] = {}
        self._layer_images: Dict[str, QtGui.QImage] = {}
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)   # fit the width; scroll down only
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        body = QtWidgets.QWidget()
        self.setWidget(body)
        g = QtWidgets.QGridLayout(body)
        g.setContentsMargins(0, 4, 4, 4)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(10)
        self.grid = g
        # u1: overview row -- the phone's Study Area card, the assessment gauge, candidate search
        self.study_box, self.study = panel("\u25c8  STUDY AREA", TEAL)
        self.study.addWidget(lab("Reading the project\u2026", colour=MUTED))
        self.assess_box, self.assess = panel("\u25c9  FINAL SCIENTIFIC ASSESSMENT", GOLD)
        self.gauge = widgets.Gauge()
        self.assess.addWidget(self.gauge)
        self.assess_text = QtWidgets.QVBoxLayout()
        self.assess.addLayout(self.assess_text)
        self.search_box, srl = panel("\u2315  FIND A CANDIDATE \u00b7 ID, name or coordinate", ACCENT)
        srow = QtWidgets.QHBoxLayout()
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("090689e5  \u00b7  Hasanlu  \u00b7  36.9532, 45.5245  (add , 500 m)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self.run_search)
        srow.addWidget(self.search_edit, 1)
        sbtn = QtWidgets.QPushButton("Search")
        sbtn.setObjectName("primary")
        sbtn.clicked.connect(self.run_search)
        srow.addWidget(sbtn)
        srl.addLayout(srow)
        self.search_note = lab("Search every candidate of the project, not only the top ten.", colour=MUTED)
        srl.addWidget(self.search_note)
        self.search_list = QtWidgets.QListWidget()
        self.search_list.setMinimumHeight(150)
        self.search_list.itemClicked.connect(lambda it: self.select(it.data(QtCore.Qt.UserRole)))
        self.search_list.itemDoubleClicked.connect(lambda it: self.open_final_image(it.data(QtCore.Qt.UserRole)))
        srl.addWidget(self.search_list, 1)
        overview = QtWidgets.QHBoxLayout()
        overview.setSpacing(10)
        for b, st in ((self.study_box, 3), (self.assess_box, 3), (self.search_box, 4)):
            overview.addWidget(b, st)
        # left
        self.coord_box, self.coord = panel("INVESTIGATION COORDINATE", TEAL)
        self.vital_box, self.vital = panel("INVESTIGATION VITAL SIGNS (selected candidate)", ACCENT)
        self.health_box, self.health = panel("LABORATORY SYSTEM HEALTH", "#9A7BFF")
        self.sites_box, self.sites = panel("\u2302  RECORDED SITES AROUND IT (gazetteer)", ORANGE)
        left = QtWidgets.QVBoxLayout()
        for b in (self.coord_box, self.vital_box, self.sites_box, self.health_box):
            left.addWidget(b)
        left.addStretch(1)
        # centre
        self.terrain_box, tl = panel("3D TERRAIN \u00b7 SELECTED CANDIDATE", ORANGE)
        ctrl = QtWidgets.QHBoxLayout()
        ctrl.addWidget(lab("Drape:", wrap=False))
        self.drape_combo = QtWidgets.QComboBox()
        self.drape_combo.currentIndexChanged.connect(self._drape_changed)
        ctrl.addWidget(self.drape_combo, 1)
        self.tile_button = QtWidgets.QPushButton("Download the terrain tile")
        self.tile_button.clicked.connect(self._download_tile)
        self.tile_button.hide()
        ctrl.addWidget(self.tile_button)
        self.fi_button = QtWidgets.QPushButton("Open its Final Image \u2197")
        self.fi_button.clicked.connect(lambda: self.open_final_image(self.selected))
        ctrl.addWidget(self.fi_button)
        tl.addLayout(ctrl)
        self.terrain = widgets.TerrainView()
        self.terrain.setMinimumWidth(300)
        self.terrain.setMinimumHeight(420)
        tl.addWidget(self.terrain, 1)
        self.terrain_caption = lab("", colour=MUTED)
        self.height_line = lab("", colour=GOLD)
        tl.addWidget(self.terrain_caption)
        tl.addWidget(self.height_line)
        small = QtWidgets.QHBoxLayout()
        self.layers_box, lyl = panel("\u25a4  LAYERS FOR THIS WINDOW (saved on this computer \u00b7 click one to drape "
                                     "it on the 3D terrain and the map)", GOLD)
        self.layers_scroll = QtWidgets.QScrollArea()
        self.layers_scroll.setWidgetResizable(True)
        self.layers_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.layers_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.layers_scroll.setMinimumHeight(232)
        inner = QtWidgets.QWidget()
        self.layers_row = QtWidgets.QHBoxLayout(inner)
        self.layers_row.setContentsMargins(0, 0, 0, 0)
        self.layers_row.setSpacing(8)
        self.layers_scroll.setWidget(inner)
        lyl.addWidget(self.layers_scroll)
        self.layers_note = lab("", colour=MUTED)
        lyl.addWidget(self.layers_note)
        self._layer_cards: Dict[str, QtWidgets.QFrame] = {}
        self.section_box, sl = panel("CROSS SECTION A\u2013A\u2032 (real heights)", TEAL)
        self.profile = widgets.ProfileView()
        sl.addWidget(self.profile, 1)
        self.sub_box, subl = panel("3D SUBSURFACE BLOCK \u00b7 SURFER 3D", "#9A7BFF")
        subl.addWidget(lab("Evidence volume, GPR depth slices, ERT cut faces and your hypotheses.", colour=MUTED))
        sb = QtWidgets.QPushButton("Open the Evidence Volume \u2197")
        sb.clicked.connect(lambda: self.open_final_image(self.selected, start_tab=4))
        subl.addWidget(sb)
        subl.addStretch(1)
        for b, s in ((self.section_box, 2), (self.sub_box, 1)):
            small.addWidget(b, s)
        centre = QtWidgets.QVBoxLayout()
        centre.addWidget(self.terrain_box, 1)
        centre.addWidget(self.layers_box)
        centre.addLayout(small)
        # right
        self.evid_box, self.evid = panel("EVIDENCE SUMMARY (selected candidate)", ACCENT)
        self.stew_box, self.stew = panel("THE STEWARD (selected candidate)", GOLD)
        from ariyan_win.stewardui import StewardGuide           # u4: the Steward on the candidate's job
        self.steward_go = None
        self.job_guide = StewardGuide(root, lambda a, j: self.steward_go and self.steward_go(a, j), compact=True)
        self.group_box, gl = panel("\u25ce  ITS GROUP (same job, within 300 m \u00b7 click one)", TEAL)
        self.group_note = lab("", colour=MUTED)
        gl.addWidget(self.group_note)
        self.group_list = QtWidgets.QListWidget()
        self.group_list.setMinimumHeight(170)
        self.group_list.itemClicked.connect(lambda it: self.select(it.data(QtCore.Qt.UserRole)))
        self.group_list.itemDoubleClicked.connect(lambda it: self.open_final_image(it.data(QtCore.Qt.UserRole)))
        gl.addWidget(self.group_list, 1)
        right = QtWidgets.QVBoxLayout()
        for b in (self.job_guide, self.evid_box, self.stew_box, self.group_box):
            right.addWidget(b)
        right.addStretch(1)
        # bottom
        self.targets_box, trl = panel("CANDIDATE TARGETS (click one)", ACCENT)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["#", "ID", "Lat", "Lon", "Confidence", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self._row_selected)
        self.table.itemDoubleClicked.connect(lambda it: self.open_final_image(it.data(QtCore.Qt.UserRole)))
        self.table.setMinimumHeight(220)
        trl.addWidget(self.table)
        self.map_box, ml = panel("CANDIDATE MAP (this window)", TEAL)
        self.map = widgets.MapView()
        ml.addWidget(self.map, 1)
        self.time_box, self.time = panel("SCIENTIFIC TIMELINE", "#9A7BFF")
        self.debate_box, self.debate = panel("AI DEBATE STUDIO (stored debate)", ROSE)
        bottom = QtWidgets.QHBoxLayout()
        for b, s in ((self.targets_box, 3), (self.map_box, 2), (self.time_box, 2), (self.debate_box, 3)):
            bottom.addWidget(b, s)
        self.steward_slot = QtWidgets.QVBoxLayout()          # sm-v1: the Steward's welcome (set by the app)
        g.addLayout(self.steward_slot, 0, 0, 1, 3)
        g.addLayout(overview, 1, 0, 1, 3)
        g.addLayout(left, 2, 0)
        g.addLayout(centre, 2, 1)
        g.addLayout(right, 2, 2)
        g.addLayout(bottom, 3, 0, 1, 3)
        foot = lab("Real Data Only \u00b7 Scientific Integrity \u00b7 No Synthetic Data \u00b7 Uncertainty Quantified "
                   "\u00b7 Human Oversight", "tag")
        foot.setAlignment(QtCore.Qt.AlignCenter)
        g.addWidget(foot, 4, 0, 1, 3)
        purpose = lab("The purpose of this laboratory is not to prove a hypothesis. Its purpose is to discover reality, "
                      "wherever the evidence leads.", colour=MUTED)
        purpose.setAlignment(QtCore.Qt.AlignCenter)
        g.addWidget(purpose, 5, 0, 1, 3)
        g.setColumnStretch(0, 22)
        g.setColumnStretch(1, 52)
        g.setColumnStretch(2, 26)

    # ------------------------------------------------------------------ project
    def show_mission(self, o: Dict[str, Any]):
        self.mission = o
        clear(self.assess_text)
        clear(self.health, 1)
        if "error" in o:
            self.assess_text.addWidget(lab(o["error"], colour=ROSE))
            self._show_study(None, o["error"])
            return
        c = o.get("confidence") or {}
        self.gauge.set(c.get("highest_numeric"), c.get("highest"))

        self.assess_text.addWidget(lab("Highest stored confidence in the project \u00b7 band ceiling %s"
                                       % ("%.2f" % c["highest_ceiling"] if c.get("highest_ceiling") else "\u2014"),
                                       colour=MUTED))
        for b in c.get("bands", []):
            if b["count"]:
                self.assess_text.addWidget(lab("\u25a0 %s  %s" % (b["band"].replace("_", " ").title(), fmt(b["count"])),
                                               colour=BAND.get(b["band"], MUTED)))
        if c.get("why"):
            self.assess_text.addWidget(lab("Why not higher: " + c["why"]))
        p = o.get("project")
        self._show_study(p)
        if p:
            self.health.addWidget(lab("%s \u00b7 %s jobs \u00b7 %s candidates" % (p["name"], fmt(p["jobs"]),
                                                                                  fmt(p["candidates"])), colour=MUTED))
        for s in o.get("sources", []):
            self.health.addWidget(lab(("\u2713 " if s["ok"] else "\u2717 ") + s["name"],
                                      colour=ACCENT if s["ok"] else ORANGE))
        # targets
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for i, t in enumerate(o.get("top", [])):
            self.table.insertRow(i)
            conf = t["band"].title() + ("" if t.get("numeric") is None else " %.2f" % t["numeric"])
            vals = [str(i + 1), t["id"][:8], "%.5f" % t["lat"], "%.5f" % t["lon"], conf, t.get("status") or ""]
            for j, v in enumerate(vals):
                it = QtWidgets.QTableWidgetItem(v)
                it.setData(QtCore.Qt.UserRole, t["id"])
                if j == 4:
                    it.setForeground(QtGui.QColor(BAND.get(t["band"], "#E6EDF3")))
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(5, max(self.table.columnWidth(5), 90))    # Status fully visible
        self.table.blockSignals(False)
        top = o.get("top", [])
        if top:
            ids = [t["id"] for t in top]
            pick = self.selected if self.selected in ids else ids[0]
            self.table.selectRow(ids.index(pick))
            if pick != self.selected or not self.terrain_data:
                self.select(pick)
        else:
            self.terrain.set_message("No candidate targets yet.")
        qtwork.run_async(lambda: workstation.timeline(self.root, 12), self._show_timeline)

    def _show_study(self, p: Optional[Dict[str, Any]], error: str = ""):
        clear(self.study, 1)
        if not p:
            self.study.addWidget(lab(error or "No Grand Project on this computer yet. Use \u201cReceive from phone\u201d.",
                                     colour=ROSE if error else MUTED))
            return
        self.study.addWidget(lab(p.get("name") or "Grand Project", size=15, bold=True))
        tiles = QtWidgets.QHBoxLayout()
        tiles.setSpacing(6)
        tiles.addWidget(stat_tile(fmt(p.get("jobs", 0)), "Jobs", TEAL, "#15263A"))
        tiles.addWidget(stat_tile(fmt(p.get("investigations", 0)), "Investigations", "#6E9BFF", "#16213D"))
        tiles.addWidget(stat_tile(fmt(p.get("candidates", 0)), "Candidates", GOLD, "#262A22"))
        self.study.addLayout(tiles)
        if p.get("jobs_unfinished"):
            self.study.addWidget(lab("%s job%s not finished" % (fmt(p["jobs_unfinished"]),
                                                               "" if p["jobs_unfinished"] == 1 else "s"), colour=MUTED))
        sc = p.get("status_counts") or {}
        order = ["Supported", "Open", "Inconclusive", "Rejected"] + sorted(k for k in sc if k not in STATUS_COLOURS)
        shown = [k for k in order if k in sc]
        for i in range(0, len(shown), 2):
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(6)
            for k in shown[i:i + 2]:
                row.addWidget(chip("%s %s" % (k, fmt(sc[k])), STATUS_COLOURS.get(k, MUTED)))
            row.addStretch(1)
            self.study.addLayout(row)
        last = (p.get("last_activity") or "")[:16].replace("T", " ")
        if last:
            self.study.addWidget(lab("Last activity: %s UTC" % last, colour=MUTED))
        self.study.addStretch(1)
        ob = QtWidgets.QPushButton("Open Investigation")
        ob.setObjectName("primary")
        ob.clicked.connect(lambda: self._goto_tab("INVESTIGATION"))
        self.study.addWidget(ob)

    def _goto_tab(self, name: str):
        w = self.parentWidget()
        while w is not None and not isinstance(w, QtWidgets.QTabWidget):
            w = w.parentWidget()
        if w is not None:
            for i in range(w.count()):
                if w.tabText(i).replace("&&", "&").upper() == name:
                    w.setCurrentIndex(i)
                    return

    def run_search(self):
        q = self.search_edit.text().strip()
        self.search_list.clear()
        if not q:
            self.search_note.setText("Type an ID, a name or a coordinate.")
            return
        self.search_note.setText("Searching\u2026")
        qtwork.run_async(workstation.search_candidates, lambda r, q=q: self._show_search(q, r), self.root, q)

    def _show_search(self, q: str, r: Dict[str, Any]):
        if q != self.search_edit.text().strip():
            return
        self.search_list.clear()
        if isinstance(r, dict) and "error" in r and "rows" not in r:
            self.search_note.setText(r["error"])
            return
        rows = r.get("rows") or []
        self.search_note.setText("%s  %d found%s. Click to select, double-click for its Final Image." % (
            r.get("note", ""), len(rows), " (first %d shown)" % len(rows) if len(rows) >= 60 else ""))
        for x in rows:
            conf = x["band"].replace("_", " ").title() + ("" if x.get("confidence_numeric") is None
                                                          else " %.2f" % x["confidence_numeric"])
            st = mc_status(x.get("status"))
            it = QtWidgets.QListWidgetItem("%s   %.5f, %.5f   %s \u00b7 %s\n      %s" % (
                x["id"][:8], x["lat"], x["lon"], conf, st, x.get("match") or ""))
            it.setData(QtCore.Qt.UserRole, x["id"])
            it.setForeground(QtGui.QColor(BAND.get(x["band"], "#E6EDF3") if x["band"] != "NOT_RATED" else "#E6EDF3"))
            it.setToolTip("Candidate %s\nJob: %s" % (x["id"], x.get("job_title") or "\u2014"))
            self.search_list.addItem(it)

    def _row_selected(self):
        items = self.table.selectedItems()
        if items:
            cid = items[0].data(QtCore.Qt.UserRole)
            if cid and cid != self.selected:
                self.select(cid)

    # ---------------------------------------------------------------- candidate
    def select(self, cid: str):
        self.selected = cid
        self.terrain_data = {}
        self.terrain.set_message("Reading the terrain window\u2026")
        self.tile_button.hide()
        self.drape_combo.blockSignals(True)
        self.drape_combo.clear()
        self.drape_combo.blockSignals(False)
        qtwork.run_async(workstation.candidate_detail, lambda r, c=cid: self._show_detail(c, r), self.root, cid)
        qtwork.run_async(workstation.terrain, lambda r, c=cid: self._show_terrain(c, r), self.root, cid)
        qtwork.run_async(workstation.candidate_context, lambda r, c=cid: self._show_context(c, r), self.root, cid)

    def _show_detail(self, cid: str, d: Dict[str, Any]):
        if cid != self.selected:
            return
        ids = [self.table.item(i, 0).data(QtCore.Qt.UserRole) for i in range(self.table.rowCount())
               if self.table.item(i, 0)]
        if cid not in ids:                             # picked from the search: not one of the top ten
            self.table.blockSignals(True)
            self.table.clearSelection()
            self.table.blockSignals(False)
        for lay in (self.coord, self.vital, self.evid, self.stew, self.debate):
            clear(lay, 1)
        if "error" in d:
            self.vital.addWidget(lab(d["error"], colour=ROSE))
            return
        self.coord.addWidget(lab("%.7f\u00b0 N" % d["lat"], size=16, bold=True, wrap=False))
        self.coord.addWidget(lab("%.7f\u00b0 E" % d["lon"], size=16, bold=True, wrap=False))
        self.coord.addWidget(lab("Candidate %s \u00b7 area of interest \u00b11 km" % cid[:8], colour=MUTED))
        self._ground = lab("Ground height: reading\u2026", colour=MUTED)
        self.coord.addWidget(self._ground)
        mb = QtWidgets.QPushButton("Open in Google Maps \u2197")
        mb.clicked.connect(lambda: webbrowser.open("https://www.google.com/maps/search/?api=1&query=%.5f,%.5f"
                                                   % (d["lat"], d["lon"])))
        self.coord.addWidget(mb)
        band = d.get("band") or "NOT_RATED"

        def vit(name, value, colour=None):
            row = QtWidgets.QHBoxLayout()
            row.addWidget(lab(name, colour=MUTED, wrap=True), 1)
            v = lab(value, colour=colour, wrap=True, bold=True)
            v.setAlignment(QtCore.Qt.AlignRight)
            row.addWidget(v, 1)
            self.vital.addLayout(row)

        vit("Steward band", "%s%s" % (band.title(), "" if d.get("numeric") is None else " %.2f" % d["numeric"]),
            BAND.get(band))
        vit("Status", (d.get("status") or "").title())
        vit("Anomaly |z|", "\u2014" if d.get("z") is None else "%.1f%s" % (abs(d["z"]), "  (calib-v1 strong)"
                                                                        if d.get("calib_strong") else ""))
        vit("Evidence sources linked", str(len(d.get("evidence") or {})))
        deb = d.get("debate")
        vit("Debate agreement", AGREEMENT.get((deb or {}).get("synthesis", {}).get("agreement_level"), "no debate stored"))
        if d.get("job_title"):
            vit("Job", d["job_title"])
        if d.get("known_site"):
            self.vital.addWidget(lab(d["known_site"], colour=MUTED))
        if d.get("same_place"):                       # win-w4c: a repeat run of the same spot (note only)
            self.vital.addWidget(lab("Same place as earlier candidate(s): " + ", ".join(
                "%s (%.0f m)" % (x["id"][:8], x["distance_m"]) for x in d["same_place"][:3]), colour=GOLD))
        ev = d.get("evidence") or {}
        if not ev:
            self.evid.addWidget(lab("No evidence linked to this candidate yet.", colour=MUTED))
        for et in sorted(ev):
            rel = ", ".join("%s %d" % (k, v) for k, v in sorted(ev[et].items()))
            self.evid.addWidget(lab("\u2713 %s \u2014 %s" % (et.replace("_", " ").title(), rel), colour=ACCENT))
        lines = d.get("steward_lines") or []
        if not lines:
            self.stew.addWidget(lab("No reasoning recorded yet.", colour=MUTED))
        for ln in lines[:6]:
            self.stew.addWidget(lab("\u201c%s\u201d" % ln))
        if not deb:
            self.debate.addWidget(lab("No debate stored for this candidate (debates are kept from 2026-10-31 on).",
                                      colour=MUTED))
            return
        syn = deb.get("synthesis") or {}
        self.debate.addWidget(lab("%s \u00b7 leading: %s" % (AGREEMENT.get(syn.get("agreement_level"), "?"),
                                                             syn.get("leading_position") or "none"), bold=True))
        bars = widgets.Bars()
        rows = []
        for i, pos in enumerate(deb.get("positions") or []):
            if pos.get("insufficient_data"):
                continue
            rows.append((pos.get("perspective", "?"), float(pos.get("confidence_score") or 0.0),
                         PERSPECTIVE[i % len(PERSPECTIVE)]))
        bars.set(rows)
        self.debate.addWidget(bars)
        st = deb.get("steward") or {}
        if st.get("band"):
            capped = st.get("capped") and st.get("raw") is not None
            self.debate.addWidget(lab("Scientific judge (Steward): %s %.2f%s" % (st["band"], st.get("numeric") or 0,
                                      "  (capped from %.2f)" % st["raw"] if capped else ""),
                                      colour=BAND.get(st["band"], GOLD), bold=True))
        self.debate.addWidget(lab("A ranked rule-based opinion, not proof; the Steward's band is what counts.",
                                  colour=MUTED))

    def _show_context(self, cid: str, x: Dict[str, Any]):
        if cid != self.selected:
            return
        clear(self.sites, 1)
        if "error" in x and "sites" not in x:
            self.sites.addWidget(lab(x["error"], colour=ROSE))
            return
        st = x.get("sites") or {}
        if "error" in st:
            self.sites.addWidget(lab(st["error"], colour=ROSE))
        else:
            self.sites.addWidget(lab(st.get("text") or "", colour=GOLD if st.get("label") == "NEAR_KNOWN_SITE"
                                     else None, bold=True))
            for e in (st.get("extents") or [])[:2]:
                self.sites.addWidget(lab("\u25a2 %s \u2014 %s" % (e["name"], "inside" if e.get("inside") else
                                                                  "%.0f m" % e["distance_m"]), colour=ORANGE))
            for n in (st.get("nearest") or [])[:6]:
                row = QtWidgets.QHBoxLayout()
                row.addWidget(lab("\u2022 " + n["name"], wrap=True), 1)
                d = n["distance_m"]
                dl = lab("%.0f m" % d if d < 1000 else "%.1f km" % (d / 1000.0), colour=MUTED, wrap=False)
                dl.setAlignment(QtCore.Qt.AlignRight)
                row.addWidget(dl)
                self.sites.addLayout(row)
            if not st.get("nearest"):
                self.sites.addWidget(lab("No recorded site within 50 km.", colour=MUTED))
            self.sites.addWidget(lab("%s recorded points within %s km \u00b7 a known site is context, not evidence." % (
                st.get("density", "?"), st.get("radius_km", "?")), colour=MUTED))
        g = x.get("group") or {}
        self.group_list.clear()
        if "error" in g:
            self.group_note.setText(g["error"])
        else:
            m = g.get("members") or []
            self.group_note.setText("%d candidate%s of %s lie together here." % (len(m), "" if len(m) == 1 else "s",
                                                                                g.get("scope", "")))
            for mm in m:
                conf = mm["band"].replace("_", " ").title() + ("" if mm.get("confidence_numeric") is None
                                                               else " %.2f" % mm["confidence_numeric"])
                it = QtWidgets.QListWidgetItem("%s%s  %s \u00b7 %s  %s" % (
                    "\u25b6 " if mm["selected"] else "", mm["id"][:8], conf, mc_status(mm.get("status")),
                    "" if mm["selected"] else "%.0f m" % mm["distance_m"]))
                it.setData(QtCore.Qt.UserRole, mm["id"])
                if mm["band"] != "NOT_RATED":
                    it.setForeground(QtGui.QColor(BAND.get(mm["band"], "#E6EDF3")))
                self.group_list.addItem(it)
        self.job_guide.load(x.get("job_id"))

    def _show_terrain(self, cid: str, t: Dict[str, Any]):
        if cid != self.selected:
            return
        self.terrain_data = t
        if "error" in t:
            self.terrain.set_message("Terrain not available: " + t["error"])
            nt = t.get("needs_tile") or {}
            if nt.get("covered") and not nt.get("present"):
                self.tile_button.setText("Download terrain tile %s (free Copernicus, about 40 MB)" % nt.get("tile"))
                self.tile_button.show()
                self.terrain.set_message("This computer has no terrain tile for this candidate yet. The phone keeps "
                                         "its country tiles; the laptop fetches only what it needs.\n\nClick "
                                         "\u201cDownload terrain tile\u201d above.")
            self._tile_chips([])
            return
        m, s = t["meta"], t["surface"]
        h = t["heights"]
        self.terrain.set_surface(h, s["cell_dx_m"], s["cell_dy_m"], s.get("ve_auto", 1.0), t["pins"])
        relief = widgets.image_from_rgba(t["drape"], t["width"], t["height"])
        self._layer_images = {"Relief (hillshaded DEM)": relief}
        self._layer_arrays = {"Relief (hillshaded DEM)": workstation.drape_on_dem(
            t["drape"], t["width"], t["height"], None, h.shape[1], h.shape[0])}
        for l in t["layers"]:
            if l.get("state") == "SAVED" and l.get("rgba"):
                self._layer_images[l["label"]] = widgets.image_from_rgba(l["rgba"], l["width"], l["height"])
                self._layer_arrays[l["label"]] = workstation.drape_on_dem(
                    l["rgba"], l["width"], l["height"], l.get("placement"), h.shape[1], h.shape[0])
        self.drape_combo.blockSignals(True)
        self.drape_combo.clear()
        self.drape_combo.addItems(list(self._layer_images))
        keep = getattr(self, "_keep_drape", None)
        self._keep_drape = None
        if keep and keep in self._layer_images:
            self.drape_combo.setCurrentText(keep)
        self.drape_combo.blockSignals(False)
        self.terrain.set_drape_array(self._layer_arrays.get(self.drape_combo.currentText(),
                                                            self._layer_arrays["Relief (hillshaded DEM)"]))
        ve = s.get("ve_auto", 1.0)
        self.terrain_caption.setText("Real DEM window \u00b11 km (%s). Height \u00d7%s (automatic). %d candidate pins; "
                                     "the selected candidate is the large white pin." % (m.get("source"),
                                     ("%g" % ve), len(t["pins"])))
        if s.get("z_min_m") is not None:
            self.height_line.setText("Real ground heights in this window: %.1f to %.1f m (span %.1f m). The view is "
                                     "stretched \u00d7%g, so small rises look tall." % (s["z_min_m"], s["z_max_m"],
                                     s["z_max_m"] - s["z_min_m"], ve))
        fx, fy = m["focus"]["x"], m["focus"]["y"]
        r = int(min(max(round(fy), 0), h.shape[0] - 1))
        c = int(min(max(round(fx), 0), h.shape[1] - 1))
        ha = t["heights_abs"]                         # real heights above sea level, for the read-outs
        zc = ha[r, c]
        if hasattr(self, "_ground"):
            self._ground.setText("Ground height at the candidate: %s" % ("%.1f m" % zc if np.isfinite(zc) else "no data"))
        d = np.arange(h.shape[1]) * float(s["cell_dx_m"])
        self.profile.set(d, ha[r, :], c * float(s["cell_dx_m"]))
        self.map.set(relief, t["pins"], h.shape[1], h.shape[0])
        self._tile_chips(t["layers"])

    def open_final_image(self, cid: Optional[str], start_tab: int = 0):
        if not cid:
            return
        from ariyan_win.finalimage import FinalImageWindow
        w = FinalImageWindow(self.root, cid, self.window(), start_tab=start_tab)
        w.layers_changed.connect(self._layers_changed)
        w.show()

    def _layers_changed(self, cid: str):
        """u3c: a layer was fetched in a Final Image. Saved layers serve every window they cover,
        so re-read the selected candidate's layers (keeping the drape you chose)."""
        if not self.selected:
            return
        self._keep_drape = self.drape_combo.currentText()
        qtwork.run_async(workstation.terrain, lambda r, c=self.selected: self._show_terrain(c, r), self.root,
                         self.selected)

    def _tile_chips(self, layers: List[Dict[str, Any]]):
        """u1: every layer of this window as a card -- the relief and each saved satellite layer with
        its picture, date and clear share; layers not saved yet are shown too, never hidden."""
        clear(self.layers_row)
        self._layer_cards = {}
        if "meta" not in self.terrain_data:
            self.layers_row.addWidget(lab("No terrain window for this candidate on this computer yet.", colour=MUTED))
            self.layers_row.addStretch(1)
            self.layers_note.setText("")
            return
        cards = [("Relief (hillshaded DEM)", "Terrain (relief, hillshaded)", "%s" % (
            self.terrain_data["meta"].get("source") or ""), True, "")]
        missing = 0
        for l in layers:
            state = l.get("state")
            ok = state == "SAVED" and l["label"] in self._layer_images
            if ok:
                cf = l.get("clear_fraction")
                note = " \u00b7 ".join(x for x in [str(l.get("scene_date") or ""),
                                                  "" if cf is None else "%d%% clear" % round(100 * float(cf))] if x)
            elif state == "NOT_SAVED":
                missing += 1
                note = "not saved yet \u2014 fetch it in the Final Image"
            elif state == "HIDDEN":
                note = "hidden: %s" % (l.get("reason") or "failed the quality check")
            else:
                note = "error: %s" % (l.get("reason") or "")
            cards.append((l["label"], l["label"], note, ok, state or ""))
        for key, title, note, ok, state in cards:
            card = ClickCard()
            card.setFixedWidth(178)
            v = QtWidgets.QVBoxLayout(card)
            v.setContentsMargins(6, 6, 6, 6)
            v.setSpacing(3)
            pic = QtWidgets.QLabel()
            pic.setFixedSize(164, 130)
            pic.setAlignment(QtCore.Qt.AlignCenter)
            if ok:
                pic.setPixmap(QtGui.QPixmap.fromImage(self._layer_images[key]).scaled(
                    164, 130, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.FastTransformation).copy(0, 0, 164, 130))
                card.clicked.connect(lambda k=key: self._pick_layer(k))
            else:
                pic.setText("not saved\non this computer" if state == "NOT_SAVED" else "\u2014")
                pic.setStyleSheet("QLabel { background: #0E1626; color: %s; border-radius: 6px; }" % MUTED)
                card.clicked.connect(lambda: self.open_final_image(self.selected))
            v.addWidget(pic)
            v.addWidget(lab(title, bold=True, colour=None if ok else MUTED))
            v.addWidget(lab(note, colour=MUTED))
            v.addStretch(1)
            self.layers_row.addWidget(card)
            self._layer_cards[key] = card
        self.layers_row.addStretch(1)
        self.layers_note.setText(("%d layer%s not saved for this window: click it (or \u201cOpen its Final Image\u201d) "
                                  "and choose it from Satellite (uses Copernicus quota once; saved after)." % (
                                      missing, "" if missing == 1 else "s")) if missing else
                                 "All layers of this window are saved on this computer.")
        self._mark_layer(self.drape_combo.currentText() or "Relief (hillshaded DEM)")

    def _pick_layer(self, key: str):
        i = self.drape_combo.findText(key)
        if i >= 0:
            self.drape_combo.setCurrentIndex(i)

    def _mark_layer(self, key: str):
        for k, c in self._layer_cards.items():
            c.setProperty("on", k == key)
            c.style().unpolish(c)
            c.style().polish(c)

    def _drape_changed(self, _i: int):
        name = self.drape_combo.currentText()
        self._mark_layer(name)
        arr = getattr(self, "_layer_arrays", {}).get(name)
        if arr is not None:
            self.terrain.set_drape_array(arr)              # each layer sits where its own cells are
            if "meta" in self.terrain_data:
                h = self.terrain_data["heights"]
                a = np.ascontiguousarray(arr)
                img = QtGui.QImage(a.data, a.shape[1], a.shape[0], 3 * a.shape[1], QtGui.QImage.Format_RGB888).copy()
                self.map.set(img, self.terrain_data["pins"], h.shape[1], h.shape[0])

    def _download_tile(self):
        if not self.selected:
            return
        self.tile_button.setEnabled(False)
        self.terrain.set_message("Downloading the terrain tile from Copernicus (public, no key)\u2026")
        import terrain_tile
        lat_lon = workstation.candidate_detail_light(self.root, self.selected)

        def done(r):
            self.tile_button.setEnabled(True)
            if isinstance(r, dict) and r.get("status") in ("downloaded", "already_present"):
                self.select(self.selected)
            else:
                msg = r.get("error") or "%s %s" % (r.get("status"), r.get("detail") or "")
                self.terrain.set_message("The tile could not be downloaded: " + msg)
        qtwork.run_async(terrain_tile.ensure_tile, done, self.root, lat_lon["lat"], lat_lon["lon"])

    def _show_timeline(self, rows):
        clear(self.time, 1)
        if isinstance(rows, dict) and "error" in rows:
            self.time.addWidget(lab(rows["error"], colour=ROSE))
            return
        for r in rows:
            self.time.addWidget(lab("%s  %s" % ((r.get("occurred_at") or "")[5:16].replace("T", " "),
                                                (r.get("event_type") or "").replace("_", " ").title()),
                                    colour=MUTED, wrap=True))
        self.time.addStretch(1)
