"""
Mission Control workstation (win-w1, 2026-11-03) -- the Windows mock-up, built on
real data only (LiDAR left out, as the user asked):

  left    investigation coordinate, the selected candidate's vital signs (real
          measures only), laboratory system health
  centre  data-source tiles, the 3D terrain of the selected candidate (its real
          DEM window, relief or any SAVED satellite layer as drape, the pins),
          thermal, cross-section A-A', subsurface/Surfer pointer (Final Image, W3)
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
        # left
        self.coord_box, self.coord = panel("INVESTIGATION COORDINATE", TEAL)
        self.vital_box, self.vital = panel("INVESTIGATION VITAL SIGNS (selected candidate)", ACCENT)
        self.health_box, self.health = panel("LABORATORY SYSTEM HEALTH", "#9A7BFF")
        left = QtWidgets.QVBoxLayout()
        for b in (self.coord_box, self.vital_box, self.health_box):
            left.addWidget(b)
        left.addStretch(1)
        # centre
        self.tiles_row = QtWidgets.QHBoxLayout()
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
        self.thermal_box, thl = panel("THERMAL (saved, this window)", ROSE)
        self.thermal_img = QtWidgets.QLabel()
        self.thermal_img.setMinimumSize(110, 120)
        self.thermal_img.setAlignment(QtCore.Qt.AlignCenter)
        thl.addWidget(self.thermal_img, 1)
        self.thermal_note = lab("", colour=MUTED)
        thl.addWidget(self.thermal_note)
        self.section_box, sl = panel("CROSS SECTION A\u2013A\u2032 (real heights)", TEAL)
        self.profile = widgets.ProfileView()
        sl.addWidget(self.profile, 1)
        self.sub_box, subl = panel("3D SUBSURFACE BLOCK \u00b7 SURFER 3D", "#9A7BFF")
        subl.addWidget(lab("Evidence volume, GPR depth slices, ERT cut faces and your hypotheses open in the "
                           "Final Image (step W3).", colour=MUTED))
        subl.addStretch(1)
        for b, s in ((self.thermal_box, 1), (self.section_box, 2), (self.sub_box, 1)):
            small.addWidget(b, s)
        centre = QtWidgets.QVBoxLayout()
        centre.addLayout(self.tiles_row)
        centre.addWidget(self.terrain_box, 1)
        centre.addLayout(small)
        # right
        self.assess_box, self.assess = panel("FINAL SCIENTIFIC ASSESSMENT", GOLD)
        self.gauge = widgets.Gauge()
        self.assess.addWidget(self.gauge)
        self.assess_text = QtWidgets.QVBoxLayout()
        self.assess.addLayout(self.assess_text)
        self.evid_box, self.evid = panel("EVIDENCE SUMMARY (selected candidate)", ACCENT)
        self.stew_box, self.stew = panel("THE STEWARD (selected candidate)", GOLD)
        right = QtWidgets.QVBoxLayout()
        for b in (self.assess_box, self.evid_box, self.stew_box):
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
        g.addLayout(left, 0, 0)
        g.addLayout(centre, 0, 1)
        g.addLayout(right, 0, 2)
        g.addLayout(bottom, 1, 0, 1, 3)
        foot = lab("Real Data Only \u00b7 Scientific Integrity \u00b7 No Synthetic Data \u00b7 Uncertainty Quantified "
                   "\u00b7 Human Oversight", "tag")
        foot.setAlignment(QtCore.Qt.AlignCenter)
        g.addWidget(foot, 2, 0, 1, 3)
        purpose = lab("The purpose of this laboratory is not to prove a hypothesis. Its purpose is to discover reality, "
                      "wherever the evidence leads.", colour=MUTED)
        purpose.setAlignment(QtCore.Qt.AlignCenter)
        g.addWidget(purpose, 3, 0, 1, 3)
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
            return
        c = o.get("confidence") or {}
        self.gauge.set(c.get("highest_numeric"), c.get("highest"))
        self.assess_text.addWidget(lab("Highest stored confidence in the project \u00b7 band ceiling %s"
                                       % ("%.2f" % c["highest_ceiling"] if c.get("highest_ceiling") else "\u2014"),
                                       colour=MUTED))
        for b in c.get("bands", []):
            if b["count"]:
                self.assess_text.addWidget(lab("\u25a0 %s  %s" % (b["band"].title(), fmt(b["count"])),
                                               colour=BAND.get(b["band"], MUTED)))
        if c.get("why"):
            self.assess_text.addWidget(lab("Why not higher: " + c["why"]))
        p = o.get("project")
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

    def _show_detail(self, cid: str, d: Dict[str, Any]):
        if cid != self.selected:
            return
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

    def _show_terrain(self, cid: str, t: Dict[str, Any]):
        if cid != self.selected:
            return
        self.terrain_data = t
        clear(self.tiles_row)
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
        self.drape_combo.blockSignals(False)
        self.terrain.set_drape_array(self._layer_arrays["Relief (hillshaded DEM)"])
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
        th = self._layer_images.get(next((l["label"] for l in t["layers"] if l["product"] == "THERMAL"), ""), None)
        if th is not None:
            self.thermal_img.setPixmap(QtGui.QPixmap.fromImage(th).scaled(
                self.thermal_img.width(), self.thermal_img.height(), QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.FastTransformation))
            self.thermal_note.setText(next(("%s" % (l.get("scene_date") or "") for l in t["layers"]
                                            if l["product"] == "THERMAL"), ""))
        else:
            self.thermal_img.clear()
            self.thermal_note.setText("Not saved for this window. Open the Final Image to fetch it (W3).")
        self._tile_chips(t["layers"])

    def open_final_image(self, cid: Optional[str]):
        if not cid:
            return
        from ariyan_win.finalimage import FinalImageWindow
        w = FinalImageWindow(self.root, cid, self.window())
        w.show()

    def _tile_chips(self, layers: List[Dict[str, Any]]):
        clear(self.tiles_row)
        dem_ok = "meta" in self.terrain_data
        chips = [("DEM / terrain", dem_ok, "this window" if dem_ok else "tile missing")]
        for l in layers:
            ok = l.get("state") == "SAVED"
            short = {"TRUE_COLOR": "True colour", "NDVI": "NDVI", "THERMAL": "Thermal", "SAR_VV": "Radar VV",
                     "SAR_VH": "Radar VH"}.get(l.get("product"), l["label"].split(" (")[0])
            chips.append((short, ok, "saved" if ok else ("not saved" if l.get("state") == "NOT_SAVED" else "hidden")))
        for name, ok, note in chips:
            box = QtWidgets.QFrame()
            box.setObjectName("panel")
            v = QtWidgets.QVBoxLayout(box)
            v.setContentsMargins(8, 6, 8, 6)
            v.addWidget(lab(name, wrap=True, bold=True, colour=ACCENT if ok else MUTED))
            v.addWidget(lab(("\u2713 " if ok else "\u2013 ") + note, wrap=True, colour=ACCENT if ok else MUTED))
            self.tiles_row.addWidget(box)
        self.tiles_row.addStretch(1)

    def _drape_changed(self, _i: int):
        name = self.drape_combo.currentText()
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
