"""
Final Image for Windows (win-w3a, 2026-11-03): one candidate's real DEM window,
built by the phone's own final_image_mobile / profile_section_mobile /
surface3d_mobile / sat_image_mobile / overview_mobile on this computer's copy.

  Overview             the phone's Overview card (candidate, Steward, debate,
                       evidence layers checklist, hypotheses, others, map info)
  Contour & Surface    the image with exact cells (no smoothing), contours, UTM
                       grid, pins; any SAVED satellite layer placed where its own
                       cells are; wheel = zoom, drag = pan; "Draw profile line" =
                       click A then B
  Profile & Section    stepped real heights along the line (one step per DEM cell
                       crossed), local relief, the layer's values; presets N-S / E-W
  3D Visualization     the surface with the chosen drape and height scale

Read-only. Fetching layers that are not saved needs the Copernicus login, which
arrives with step W4; until then a missing layer says so.
"""
from __future__ import annotations

import json
import math
import webbrowser
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ariyan_win import qtwork, widgets, workstation

ACCENT, TEAL, GOLD, ORANGE, ROSE, MUTED = "#3FB68B", "#2FA6B8", "#F2C14E", "#D9822B", "#E0607E", "#8B9BB0"
PRODUCTS = [("", "Terrain only"), ("TRUE_COLOR", "True colour (Sentinel-2)"), ("NDVI", "NDVI (Sentinel-2)"),
            ("THERMAL", "Brightness temperature (Landsat 8/9)"), ("SAR_VV", "Radar VV (Sentinel-1)"),
            ("SAR_VH", "Radar VH (Sentinel-1)")]
WINDOWS = [(500.0, "\u00b10.5 km"), (1000.0, "\u00b11 km"), (2500.0, "\u00b12.5 km"), (5000.0, "\u00b15 km")]


def _lab(text="", colour=None, bold=False, wrap=True, size=None):
    w = QtWidgets.QLabel(text)
    w.setWordWrap(wrap)
    css = []
    if colour:
        css.append("color:%s;" % colour)
    if bold:
        css.append("font-weight:700;")
    if size:
        css.append("font-size:%dpt;" % size)
    if css:
        w.setStyleSheet("".join(css))
    return w


# ---------------------------------------------------------------------------
# background work (core calls)
# ---------------------------------------------------------------------------

def _open(root: str, cid: str, half: float, colour_by: str) -> Dict[str, Any]:
    import final_image_mobile as fim
    import overview_mobile as ov
    import surface3d_mobile as s3d
    j = json.loads(fim.open_final_image_json(root, cid, half, colour_by))
    if "error" in j:
        out = {"error": j["error"]}
        if "no saved DEM tile" in j["error"]:
            import terrain_tile
            c = workstation.candidate_detail_light(root, cid)
            out["needs_tile"] = json.loads(terrain_tile.tile_status_json(root, c["lat"], c["lon"]))
        return out
    sid = j["session_id"]
    img = bytes(fim.image_rgba(sid))
    m = json.loads(s3d.open_surface_json(sid))
    heights = None
    if "error" not in m:
        heights = np.frombuffer(bytes(s3d.surface_heights(sid)), dtype="<f4").reshape(m["height"], m["width"]).copy()
    o = json.loads(ov.overview_json(root, sid))
    return {"meta": j, "image": img, "surface": m, "heights": heights, "overview": o}


def _layer(root: str, sid: str, product: str) -> Dict[str, Any]:
    import sat_image_mobile as sim
    r = json.loads(sim.open_layer_json(root, sid, product, "", "", False))
    if r.get("needs_fetch") or "error" in r or not r.get("allowed", True):
        return r
    r["rgba"] = bytes(sim.layer_rgba(sid, product))
    return r


def _profile(sid: str, ax: float, ay: float, bx: float, by: float, product: str, preset: str = "") -> Dict[str, Any]:
    import profile_section_mobile as psm
    if preset:
        return json.loads(psm.preset_profile_json(sid, preset, product))
    return json.loads(psm.profile_json(sid, ax, ay, bx, by, product))


# ---------------------------------------------------------------------------
# map view (exact cells, contours, grid, pins, layer placement, line drawing)
# ---------------------------------------------------------------------------

class MapCanvas(QtWidgets.QWidget):
    line_drawn = QtCore.Signal(float, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 380)
        self.base: Optional[QtGui.QImage] = None
        self.layer: Optional[QtGui.QImage] = None
        self.placement: Optional[Dict[str, float]] = None
        self.w = self.h = 1
        self.contours: List[Tuple[bool, List[float]]] = []
        self.grid_lines: List[Dict] = []
        self.pins: List[Dict] = []
        self.show_contours = self.show_grid = self.show_pins = True
        self.line: Optional[Tuple[float, float, float, float]] = None
        self.drawing = False
        self._a: Optional[Tuple[float, float]] = None
        self.scale = 1.0                                  # screen px per DEM row (north-south cell)
        self.ax = 1.0                                     # cell width / cell height: cells are not square
        self.off = QtCore.QPointF(0, 0)
        self._drag: Optional[QtCore.QPointF] = None
        self.setMouseTracking(True)

    def set_image(self, base: QtGui.QImage, w: int, h: int, contours, grid_lines, pins, aspect: float = 1.0):
        self.base, self.w, self.h, self.ax = base, w, h, float(aspect)
        self.contours, self.grid_lines, self.pins = contours, grid_lines, pins
        self.fit()

    def set_layer(self, img: Optional[QtGui.QImage], placement: Optional[Dict[str, float]]):
        self.layer, self.placement = img, placement
        self.update()

    def fit(self):
        if self.w and self.h:
            self.scale = min(self.width() / (self.w * self.ax), self.height() / self.h) * 0.98
            self.off = QtCore.QPointF((self.width() - self.w * self.ax * self.scale) / 2,
                                      (self.height() - self.h * self.scale) / 2)
        self.update()

    def resizeEvent(self, e):
        self.fit()

    def to_screen(self, x, y):
        return QtCore.QPointF(self.off.x() + x * self.ax * self.scale, self.off.y() + y * self.scale)

    def to_grid(self, p: QtCore.QPointF):
        return (p.x() - self.off.x()) / (self.ax * self.scale), (p.y() - self.off.y()) / self.scale

    def wheelEvent(self, e):
        k = 1.0015 ** e.angleDelta().y()
        p = e.position()
        gx, gy = self.to_grid(p)
        self.scale = max(0.3, min(80.0, self.scale * k))
        self.off = QtCore.QPointF(p.x() - gx * self.ax * self.scale, p.y() - gy * self.scale)
        self.update()

    def mousePressEvent(self, e):
        if self.drawing and e.button() == QtCore.Qt.LeftButton:
            g = self.to_grid(e.position())
            if self._a is None:
                self._a = g
            else:
                a, self._a = self._a, None
                self.drawing = False
                self.line = (a[0], a[1], g[0], g[1])
                self.setCursor(QtCore.Qt.ArrowCursor)
                self.line_drawn.emit(*self.line)
            self.update()
            return
        self._drag = e.position()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.off += e.position() - self._drag
            self._drag = e.position()
            self.update()

    def mouseReleaseEvent(self, _e):
        self._drag = None

    def mouseDoubleClickEvent(self, _e):
        self.fit()

    def start_line(self):
        self.drawing, self._a = True, None
        self.setCursor(QtCore.Qt.CrossCursor)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#0B0E13"))
        if self.base is None:
            p.setPen(QtGui.QColor(MUTED))
            p.drawText(self.rect(), QtCore.Qt.AlignCenter, "Reading the DEM window\u2026")
            p.end()
            return
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, False)     # exact cells
        tl, br = self.to_screen(0, 0), self.to_screen(self.w, self.h)
        p.drawImage(QtCore.QRectF(tl, br), self.base)
        if self.layer is not None and self.placement:
            pl = self.placement
            a = self.to_screen(pl["x0"], pl["y0"])
            b = self.to_screen(pl["x0"] + self.layer.width() * pl["sx"], pl["y0"] + self.layer.height() * pl["sy"])
            p.drawImage(QtCore.QRectF(a, b), self.layer)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        if self.show_contours:
            for index, flat in self.contours:
                pen = QtGui.QPen(QtGui.QColor(0, 0, 0, 150 if index else 90), 1.4 if index else 0.8)
                p.setPen(pen)
                for i in range(0, len(flat) - 3, 4):
                    p.drawLine(self.to_screen(flat[i], flat[i + 1]), self.to_screen(flat[i + 2], flat[i + 3]))
        if self.show_grid:
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 110), 1))
            f = p.font(); f.setPointSize(8); p.setFont(f)
            for ln in self.grid_lines:
                pts = [self.to_screen(x, y) for x, y in ln["points"]]
                for i in range(len(pts) - 1):
                    p.drawLine(pts[i], pts[i + 1])
                lp = min(pts, key=lambda q: q.y()) if ln["axis"] == "easting" else min(pts, key=lambda q: q.x())
                p.drawText(lp + QtCore.QPointF(3, 12), ("E %d" if ln["axis"] == "easting" else "N %d") % ln["value"])
        if self.show_pins:
            f = p.font(); f.setPointSize(8); p.setFont(f)
            for pin in self.pins:
                pt = self.to_screen(pin["x"], pin["y"])
                col = QtGui.QColor("#FFFFFF") if pin.get("focus") else widgets.pin_colour(pin.get("style", ""))
                p.setPen(QtGui.QPen(QtGui.QColor("#000000"), 1.2))
                p.setBrush(col)
                r = 8 if pin.get("focus") else 5
                p.drawEllipse(pt, r, r)
                if self.scale > 2.5 or pin.get("focus"):
                    p.setPen(QtGui.QColor("#FFFFFF"))
                    p.drawText(pt + QtCore.QPointF(r + 3, 4), "%s %s" % (pin["id"][:6], pin.get("confidence_label") or ""))
        if self.line or self._a:
            p.setPen(QtGui.QPen(QtGui.QColor(GOLD), 2))
            if self.line:
                a, b = self.to_screen(self.line[0], self.line[1]), self.to_screen(self.line[2], self.line[3])
                p.drawLine(a, b)
                p.drawText(a + QtCore.QPointF(-12, -6), "A")
                p.drawText(b + QtCore.QPointF(6, -6), "A\u2032")
            if self._a:
                p.drawEllipse(self.to_screen(*self._a), 4, 4)
        # scale bar
        p.setPen(QtGui.QPen(QtGui.QColor("#FFFFFF"), 2))
        if getattr(self, "cell_m", None):
            target = 100
            px_per_m = self.scale / self.cell_m          # cell_m = north-south cell size
            for m in (50, 100, 200, 500, 1000, 2000):
                if m * px_per_m > 90:
                    target = m
                    break
            x0, y0 = 16, self.height() - 18
            p.drawLine(QtCore.QPointF(x0, y0), QtCore.QPointF(x0 + target * px_per_m, y0))
            p.drawText(QtCore.QPointF(x0, y0 - 6), "%d m" % target)
        p.end()


# ---------------------------------------------------------------------------
# profile plot (stepped: one flat step per DEM cell crossed)
# ---------------------------------------------------------------------------

class ProfilePlot(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(380)
        self.prof: Optional[Dict[str, Any]] = None

    def set(self, prof: Optional[Dict[str, Any]]):
        self.prof = prof
        self.update()

    def _panel(self, p, rect, title, d0, d1, vals, axis, colour, units, cands=()):
        p.setPen(QtGui.QColor("#22324A"))
        p.drawRect(rect)
        p.setPen(QtGui.QColor(MUTED))
        f = p.font(); f.setPointSize(8); p.setFont(f)
        p.drawText(QtCore.QRectF(rect.left(), rect.top() - 16, rect.width(), 14), QtCore.Qt.AlignLeft, title)
        lo, hi = axis
        if hi <= lo:
            hi = lo + 1e-6
        length = max(d1) if d1 else 1.0
        p.drawText(QtCore.QRectF(rect.left() - 64, rect.top() - 6, 60, 14), QtCore.Qt.AlignRight, "%g %s" % (round(hi, 2), units))
        p.drawText(QtCore.QRectF(rect.left() - 64, rect.bottom() - 8, 60, 14), QtCore.Qt.AlignRight, "%g %s" % (round(lo, 2), units))
        pen = QtGui.QPen(QtGui.QColor(colour), 2)
        p.setPen(pen)
        X = lambda d: rect.left() + d / length * rect.width()
        Y = lambda v: rect.bottom() - (v - lo) / (hi - lo) * rect.height()
        prev = None
        for a, b, v in zip(d0, d1, vals):
            if v is None:
                prev = None
                continue
            if prev is not None and abs(prev[0] - a) < 1e-6:     # riser between touching cells
                p.drawLine(QtCore.QPointF(X(a), Y(prev[1])), QtCore.QPointF(X(a), Y(v)))
            p.drawLine(QtCore.QPointF(X(a), Y(v)), QtCore.QPointF(X(b), Y(v)))
            prev = (b, v)
        for c in cands:
            x = X(c.get("d_m", c.get("along_m", 0)))
            p.setPen(QtGui.QPen(QtGui.QColor("#FFFFFF" if c.get("focus") else GOLD), 1, QtCore.Qt.DashLine))
            p.drawLine(QtCore.QPointF(x, rect.top()), QtCore.QPointF(x, rect.bottom()))

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor("#0B0E13"))
        pr = self.prof
        if not pr or "error" in pr:
            p.setPen(QtGui.QColor(MUTED))
            p.drawText(self.rect(), QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap,
                       (pr or {}).get("error") or "Choose N\u2013S or E\u2013W, or draw a line on the map.")
            p.end()
            return
        dem = pr["dem"]
        panels = [("ELEVATION (m), one step per DEM cell", dem["elevation"], pr["elevation_axis"], ACCENT, "m"),
                  ("LOCAL RELIEF (m relative to surroundings)", dem["relief"], pr["relief_axis"], GOLD, "m")]
        sat = pr.get("sat")
        if sat:
            panels.append(("%s (%s), scene %s" % (sat.get("label"), sat.get("units") or "", sat.get("scene_date") or ""),
                           sat["steps"]["value"], sat["axis"], ROSE, sat.get("units") or ""))
        n = len(panels)
        top, bottom, left, right = 26, 34, 74, 14
        ph = (self.height() - top - bottom - 22 * (n - 1)) / n
        for i, (title, vals, axis, col, units) in enumerate(panels):
            rect = QtCore.QRectF(left, top + i * (ph + 22), self.width() - left - right, ph)
            if i == 2:
                st = sat["steps"]
                self._panel(p, rect, title, st["d0"], st["d1"], vals, axis, col, units)
            else:
                self._panel(p, rect, title, dem["d0"], dem["d1"], vals, axis, col, units, pr.get("candidates", []))
        p.setPen(QtGui.QColor(MUTED))
        p.drawText(QtCore.QRectF(left, self.height() - 20, self.width() - left, 16), QtCore.Qt.AlignLeft,
                   "A  \u2192  A\u2032   %.0f m, bearing %.0f\u00b0, %d cells (%d without data)"
                   % (pr["length_m"], pr["bearing_deg"], pr["cells"], pr["cells_no_data"]))
        p.end()


# ---------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------

class FinalImageWindow(QtWidgets.QMainWindow):
    def __init__(self, root: str, cid: str, parent=None):
        super().__init__(parent)
        self.root, self.cid = root, cid
        self.sid: Optional[str] = None
        self.data: Dict[str, Any] = {}
        self.layer_payload: Optional[Dict[str, Any]] = None
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setWindowTitle("Final Image \u00b7 %s" % cid[:8])
        self.resize(1280, 860)
        c = QtWidgets.QWidget()
        self.setCentralWidget(c)
        v = QtWidgets.QVBoxLayout(c)
        self.title = QtWidgets.QPushButton("Final Image \u00b7 %s" % cid[:8])
        self.title.setFlat(True)
        self.title.setStyleSheet("font-size:16pt; font-weight:700; text-align:left; border:none;")
        self.title.setToolTip("Open in Google Maps")
        self.title.clicked.connect(self._maps)
        v.addWidget(self.title)
        bar = QtWidgets.QHBoxLayout()
        self.win_combo = QtWidgets.QComboBox()
        for half, name in WINDOWS:
            self.win_combo.addItem("Window: " + name, half)
        self.win_combo.setCurrentIndex(1)
        self.colour_combo = QtWidgets.QComboBox()
        self.colour_combo.addItem("Colour: local relief", "relief")
        self.colour_combo.addItem("Colour: elevation", "elevation")
        self.layer_combo = QtWidgets.QComboBox()
        for prod, name in PRODUCTS:
            self.layer_combo.addItem("Layer: " + name, prod)
        self.cb_contours = QtWidgets.QCheckBox("Contours")
        self.cb_grid = QtWidgets.QCheckBox("UTM grid")
        self.cb_pins = QtWidgets.QCheckBox("Candidates")
        for cb in (self.cb_contours, self.cb_grid, self.cb_pins):
            cb.setChecked(True)
            cb.toggled.connect(self._toggles)
        for wdg in (self.win_combo, self.colour_combo, self.layer_combo, self.cb_contours, self.cb_grid, self.cb_pins):
            bar.addWidget(wdg)
        bar.addStretch(1)
        v.addLayout(bar)
        self.layer_note = _lab("", colour=MUTED)
        v.addWidget(self.layer_note)
        self.tabs = QtWidgets.QTabWidget()
        v.addWidget(self.tabs, 1)
        # overview
        self.ov_scroll = QtWidgets.QScrollArea()
        self.ov_scroll.setWidgetResizable(True)
        self.ov_body = QtWidgets.QWidget()
        self.ov = QtWidgets.QVBoxLayout(self.ov_body)
        self.ov_scroll.setWidget(self.ov_body)
        self.tabs.addTab(self.ov_scroll, "Overview")
        # map
        mapw = QtWidgets.QWidget()
        ml = QtWidgets.QVBoxLayout(mapw)
        self.canvas = MapCanvas()
        self.canvas.line_drawn.connect(self._line_drawn)
        mb = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Draw profile line (click A, then A\u2032)")
        b.clicked.connect(self.canvas.start_line)
        mb.addWidget(b)
        fitb = QtWidgets.QPushButton("Fit")
        fitb.clicked.connect(self.canvas.fit)
        mb.addWidget(fitb)
        mb.addStretch(1)
        ml.addLayout(mb)
        ml.addWidget(self.canvas, 1)
        self.map_caption = _lab("", colour=MUTED)
        ml.addWidget(self.map_caption)
        self.tabs.addTab(mapw, "Contour && Surface")
        # profile
        pw = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(pw)
        pb = QtWidgets.QHBoxLayout()
        for name, which in (("North \u2013 South through the candidate", "NS"), ("West \u2013 East through the candidate", "EW")):
            bb = QtWidgets.QPushButton(name)
            bb.clicked.connect(lambda _=False, w=which: self._preset(w))
            pb.addWidget(bb)
        pb.addStretch(1)
        pl.addLayout(pb)
        self.plot = ProfilePlot()
        pl.addWidget(self.plot, 1)
        self.prof_caption = _lab("", colour=MUTED)
        pl.addWidget(self.prof_caption)
        self.tabs.addTab(pw, "Profile && Section")
        # 3D
        tw = QtWidgets.QWidget()
        t3 = QtWidgets.QVBoxLayout(tw)
        tb = QtWidgets.QHBoxLayout()
        tb.addWidget(_lab("Height scale:", wrap=False))
        self.ve_combo = QtWidgets.QComboBox()
        self.ve_combo.currentIndexChanged.connect(self._ve_changed)
        tb.addWidget(self.ve_combo)
        tb.addStretch(1)
        t3.addLayout(tb)
        self.view3d = widgets.TerrainView()
        t3.addWidget(self.view3d, 1)
        self.caption3d = _lab("", colour=MUTED)
        t3.addWidget(self.caption3d)
        self.tabs.addTab(tw, "3D Visualization")
        self.win_combo.currentIndexChanged.connect(self.reopen)
        self.colour_combo.currentIndexChanged.connect(self.reopen)
        self.layer_combo.currentIndexChanged.connect(self._layer_changed)
        self.reopen()

    # ------------------------------------------------------------- open / close
    def reopen(self, *_):
        self._close_session()
        self.canvas.base = None
        self.canvas.update()
        self.view3d.set_message("Reading the DEM window\u2026")
        qtwork.run_async(_open, self._opened, self.root, self.cid, self.win_combo.currentData(),
                         self.colour_combo.currentData())

    def _close_session(self):
        if self.sid:
            try:
                import final_image_mobile as fim
                import sat_image_mobile as sim
                sim.close_layers(self.sid)
                fim.close_session(self.sid)
            except Exception:
                pass
            self.sid = None

    def closeEvent(self, e):
        self._close_session()
        super().closeEvent(e)

    def _maps(self):
        m = self.data.get("meta")
        if m:
            webbrowser.open("https://www.google.com/maps/search/?api=1&query=%.5f,%.5f" % (m["lat"], m["lon"]))

    def _opened(self, d: Dict[str, Any]):
        if "error" in d:
            msg = d["error"]
            nt = d.get("needs_tile") or {}
            if nt.get("covered") and not nt.get("present"):
                msg = ("This computer has no terrain tile %s for this candidate yet. On Mission Control, select it and "
                       "click \u201cDownload terrain tile\u201d." % nt.get("tile"))
            self.view3d.set_message(msg)
            self.layer_note.setText(msg)
            return
        self.data = d
        m = d["meta"]
        self.sid = m["session_id"]
        self.title.setText("Final Image \u00b7 %s  (%.5f, %.5f) \u2197" % (self.cid[:8], m["lat"], m["lon"]))
        base = widgets.image_from_rgba(d["image"], m["width"], m["height"])
        contours = [(lv.get("index"), lv["flat"]) for lv in m["contours"]["levels"]]
        self.canvas.cell_m = m["cell_dy_m"]
        self.canvas.set_image(base, m["width"], m["height"], contours, m["utm_grid"]["lines"], m["candidates"],
                              aspect=m["cell_dx_m"] / m["cell_dy_m"])
        lg = m.get("legend") or {}
        self.map_caption.setText("%s \u00b7 native %s m \u00b7 cells %.1f \u00d7 %.1f m \u00b7 contours every %s m \u00b7 colour %s %s \u2026 %s %s "
                                 "\u00b7 UTM zone %s%s \u00b7 exact cells, no smoothing" % (
                                     m.get("source"), m.get("native_resolution_m"), m["cell_dx_m"], m["cell_dy_m"],
                                     m["contours"]["interval_m"], lg.get("colour_by"), lg.get("min"), lg.get("max"),
                                     lg.get("units", ""), m["utm_grid"]["zone"], m["utm_grid"]["hemisphere"]))
        s = d["surface"]
        if d["heights"] is not None:
            self.view3d.set_surface(d["heights"], s["cell_dx_m"], s["cell_dy_m"], s.get("ve_auto", 1.0), m["candidates"])
            self._relief_arr = workstation.drape_on_dem(d["image"], m["width"], m["height"], None,
                                                        d["heights"].shape[1], d["heights"].shape[0])
            self.view3d.set_drape_array(self._relief_arr)
            self.ve_combo.blockSignals(True)
            self.ve_combo.clear()
            for ve in s.get("ve_choices", [1, 2, 5, 10, 20, 50]):
                self.ve_combo.addItem("\u00d7%g%s" % (ve, " (automatic)" if ve == s.get("ve_auto") else ""), ve)
            if s.get("ve_auto") in s.get("ve_choices", []):
                self.ve_combo.setCurrentIndex(s["ve_choices"].index(s["ve_auto"]))
            self.ve_combo.blockSignals(False)
            self.caption3d.setText("Real ground heights %.1f to %.1f m (span %.1f m). Height \u00d7%g: small rises look tall. "
                                   "Drag to rotate, wheel to zoom, double-click to reset." % (
                                       s["z_min_m"], s["z_max_m"], s["z_max_m"] - s["z_min_m"], s.get("ve_auto", 1.0)))
        self._overview(d.get("overview") or {})
        self._layer_changed()
        self._preset("EW")

    # ------------------------------------------------------------------ layers
    def _layer_changed(self, *_):
        prod = self.layer_combo.currentData()
        self.layer_payload = None
        if not self.sid:
            return
        if not prod:
            self.canvas.set_layer(None, None)
            if getattr(self, "_relief_arr", None) is not None:
                self.view3d.set_drape_array(self._relief_arr)
            self.layer_note.setText("")
            self._preset(getattr(self, "_last_preset", "EW"))
            return
        self.layer_note.setText("Opening the saved layer\u2026")
        qtwork.run_async(_layer, lambda r, p=prod: self._layer_opened(p, r), self.root, self.sid, prod)

    def _layer_opened(self, prod: str, r: Dict[str, Any]):
        if prod != self.layer_combo.currentData():
            return
        if r.get("needs_fetch"):
            self.layer_note.setText("%s is not saved for this window. Fetching it needs the Copernicus login on this "
                                    "computer (step W4); or fetch it on the phone and send the project." % r.get("label"))
            self.canvas.set_layer(None, None)
            return
        if "error" in r:
            self.layer_note.setText(r["error"])
            return
        if not r.get("allowed", True):
            self.layer_note.setText("Hidden: %s" % r.get("hidden_reason"))
            return
        self.layer_payload = r
        g = r["grid"]
        img = widgets.image_from_rgba(r["rgba"], g["width"], g["height"])
        self.canvas.set_layer(img, r["placement"])
        h = self.data["heights"]
        if h is not None:
            self.view3d.set_drape_array(workstation.drape_on_dem(r["rgba"], g["width"], g["height"], r["placement"],
                                                                 h.shape[1], h.shape[0]))
        self.layer_note.setText("%s \u00b7 scene %s \u00b7 %.0f%% of the window clear \u00b7 %s m cells \u00b7 %s" % (
            r["label"], r.get("scene_date"), 100 * (r.get("clear_fraction_window") or 0), r.get("pixel_m"),
            r.get("caption") or ""))
        self._preset(getattr(self, "_last_preset", "EW"))

    def _toggles(self, *_):
        self.canvas.show_contours = self.cb_contours.isChecked()
        self.canvas.show_grid = self.cb_grid.isChecked()
        self.canvas.show_pins = self.cb_pins.isChecked()
        self.canvas.update()

    def _ve_changed(self, *_):
        ve = self.ve_combo.currentData()
        if ve and self.view3d.heights is not None:
            self.view3d.ve = float(ve)
            self.view3d.update()

    # ----------------------------------------------------------------- profile
    def _product(self) -> str:
        return self.layer_combo.currentData() if self.layer_payload else ""

    def _preset(self, which: str):
        if not self.sid:
            return
        self._last_preset = which
        qtwork.run_async(_profile, self._profiled, self.sid, 0, 0, 0, 0, self._product(), which)

    def _line_drawn(self, ax, ay, bx, by):
        self._last_preset = "EW"
        qtwork.run_async(_profile, self._profiled, self.sid, ax, ay, bx, by, self._product(), "")
        self.tabs.setCurrentIndex(2)

    def _profiled(self, pr: Dict[str, Any]):
        self.plot.set(pr)
        if pr and "error" not in pr:
            self.canvas.line = (pr["a"]["x"], pr["a"]["y"], pr["b"]["x"], pr["b"]["y"])
            self.canvas.update()
            near = ", ".join("%s %.0f m off" % (c["id"][:6], c.get("offset_m", 0)) for c in pr.get("candidates", [])[:6])
            self.prof_caption.setText("A %.5f, %.5f \u2192 A\u2032 %.5f, %.5f \u00b7 source %s. %s" % (
                pr["a"]["lat"], pr["a"]["lon"], pr["b"]["lat"], pr["b"]["lon"], pr.get("source"),
                ("Candidates near the line: " + near) if near else ""))

    # ---------------------------------------------------------------- overview
    def _overview(self, o: Dict[str, Any]):
        lay = self.ov
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if "error" in o:
            lay.addWidget(_lab(o["error"], colour=ROSE))
            return

        def card(title, tint):
            f = QtWidgets.QFrame()
            f.setObjectName("panel")
            l = QtWidgets.QVBoxLayout(f)
            l.addWidget(_lab(title, colour=tint, bold=True))
            lay.addWidget(f)
            return l

        c = o.get("candidate") or {}
        l = card("CANDIDATE", ACCENT)
        l.addWidget(_lab("%s %s \u00b7 %s%s" % ((c.get("band") or "not rated").title(),
                                             "" if c.get("numeric") is None else "%.2f" % c["numeric"],
                                             c.get("status") or "", " (%s)" % c["review_source"] if c.get("review_source") else ""),
                         bold=True, colour=widgets.BAND_COLOURS.get(c.get("band") or "", "#E6EDF3")))
        if c.get("review_reason"):
            l.addWidget(_lab("Last review: " + str(c["review_reason"]), colour=MUTED))
        st = o.get("steward") or {}
        l = card("THE STEWARD", GOLD)
        if not st:
            l.addWidget(_lab("Not rated yet.", colour=MUTED))
        else:
            l.addWidget(_lab("%s %s \u00b7 %s rating(s), latest %s" % (st.get("band"), st.get("numeric"), st.get("ratings"),
                                                                      (st.get("recorded_at") or "")[:16].replace("T", " ")),
                             colour=widgets.BAND_COLOURS.get(st.get("band") or "", GOLD), bold=True))
            for x in st.get("reasoning") or []:
                l.addWidget(_lab("\u201c%s\u201d" % x))
        db_ = o.get("debate")
        l = card("AI DEBATE", ROSE)
        if not db_ or not db_.get("stored"):
            l.addWidget(_lab("No debate stored yet (runs before dbr-v1 were not kept).", colour=MUTED))
        else:
            l.addWidget(_lab("%s debate(s) stored \u00b7 latest %s (%s) \u00b7 %s \u00b7 leading: %s" % (
                db_["stored"], (db_.get("recorded_at") or "")[:16].replace("T", " "), db_.get("origin"),
                (db_.get("agreement") or "").replace("_", " ").title(), db_.get("leading") or "none")))
        l = card("EVIDENCE LAYERS (this candidate / window)", ACCENT)
        marks = {"EVIDENCE": ("\u2713", ACCENT), "USED": ("\u2713", ACCENT), "MEASURED": ("\u25c9", TEAL), "SAVED": ("\u25cb", MUTED), "NONE": ("\u2013", MUTED)}
        for ly in o.get("layers", []):
            sym, col = marks.get(ly.get("state"), ("?", MUTED))
            l.addWidget(_lab("%s %s \u2014 %s" % (sym, ly.get("name"), ly.get("detail")), colour=col))
        h = o.get("hypotheses") or {}
        l = card("YOUR HYPOTHESES", TEAL)
        l.addWidget(_lab(", ".join("%s %s" % (k.replace("_", " "), v) for k, v in h.items()) or "none", colour=MUTED))
        fd = o.get("field_datasets") or {}
        l.addWidget(_lab("Field data: %s GPR \u00b7 %s ERT" % (fd.get("gpr", 0), fd.get("ert", 0)), colour=MUTED))
        l = card("OTHER CANDIDATES IN THIS WINDOW (double-click to open)", ACCENT)
        lst = QtWidgets.QListWidget()
        lst.setMinimumHeight(160)
        for oc in o.get("others", [])[:40]:
            it = QtWidgets.QListWidgetItem("%s \u00b7 %s \u00b7 %s \u00b7 %.0f m away" % (
                oc["id"][:8], oc.get("confidence_label") or oc.get("band") or "", oc.get("status") or "", oc.get("distance_m", 0)))
            it.setData(QtCore.Qt.UserRole, oc["id"])
            lst.addItem(it)
        lst.itemDoubleClicked.connect(lambda it: FinalImageWindow(self.root, it.data(QtCore.Qt.UserRole),
                                                                  self.parent()).show())
        l.addWidget(lst)
        mp = o.get("map") or {}
        l = card("MAP INFORMATION", TEAL)
        l.addWidget(_lab("UTM %s%s \u00b7 E %s N %s \u00b7 cells %s \u00d7 %s m \u00b7 %s cells \u00b7 window \u00b1%s m" % (
            mp.get("utm_zone"), mp.get("hemisphere"), mp.get("easting"), mp.get("northing"), mp.get("cell_dx_m"),
            mp.get("cell_dy_m"), mp.get("cells"), mp.get("window_half_m")), colour=MUTED))
        l.addWidget(_lab("DEM %s \u00b7 SHA-256 %s" % (mp.get("source"), (mp.get("source_sha256") or "")[:16]), colour=MUTED))
        if o.get("statement"):
            lay.addWidget(_lab(o["statement"], colour=MUTED))
        lay.addStretch(1)
