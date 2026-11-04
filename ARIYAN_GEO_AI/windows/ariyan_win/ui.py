"""
The look of the laboratory (win-u6, 2026-11-04): drawn glyph icons for tabs and
buttons, a titled frame around every page, and the Visualization page (a
launcher for each view of the Final Image, with the selected candidate).
Appearance only: nothing here reads or writes project data beyond what the
pages it frames already do.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional

from PySide6 import QtCore, QtGui, QtWidgets

ACCENT, TEAL, GOLD, ORANGE, ROSE, VIOLET, MUTED = ("#3FB68B", "#2FA6B8", "#F2C14E", "#D9822B", "#E0607E",
                                                   "#9A7BFF", "#8B9BB0")

# tab -> (glyph, colour, title, one line about the page)
PAGES: Dict[str, tuple] = {
    "MISSION CONTROL": ("\u25c8", ACCENT, "Mission Control", ""),
    "INVESTIGATION": ("\u2316", TEAL, "Investigation",
                      "Run a single point, or create and lead a wide-area job to a finished, reported result."),
    "DATA & EVIDENCE": ("\u25a4", GOLD, "Data & Evidence",
                        "Terrain tiles on this computer and the field data (GPR, ERT) that let evidence go further."),
    "AI DEBATE STUDIO": ("\u2696", ROSE, "AI Debate Studio",
                         "Every stored debate: four perspectives argue each candidate; the Steward\u2019s band counts."),
    "VISUALIZATION": ("\u25d0", VIOLET, "Visualization",
                      "Every view of the selected candidate\u2019s Final Image: map, profile, 3D and evidence volume."),
    "GRAND PROJECT": ("\u2756", ACCENT, "Grand Project",
                      "Jobs, candidates with their groups and interpretation, hypotheses, single points, timeline."),
    "HISTORICAL RESEARCH": ("\u2711", ORANGE, "Historical Research",
                            "Search history in English and Persian; a promising place becomes a single point."),
    "ANALYSIS & MODELS": ("\u2211", TEAL, "Analysis & Models",
                          "The rules the laboratory applies, read from its own code and database."),
    "REPORT & ARCHIVE": ("\u2399", GOLD, "Report & Archive",
                         "Decide every leading candidate with your reason, then export the job report (HTML, CSV, PDF)."),
}

BUTTON_GLYPHS = {"Receive from phone": "\u21e9", "Send to phone": "\u21e7", "New Investigation": "\u2316",
                 "Generate Report": "\u2399", "Export Results": "\u21aa", "Settings": "\u2699",
                 "Data folder\u2026": "\u25a3", "Open data folder": "\u25a2", "Refresh": "\u21bb",
                 "Exit Laboratory": "\u23fb"}


def glyph_icon(glyph: str, colour: str, size: int = 18) -> QtGui.QIcon:
    pm = QtGui.QPixmap(size * 2, size * 2)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setRenderHint(QtGui.QPainter.TextAntialiasing)
    f = QtGui.QFont("Segoe UI Symbol")
    f.setPixelSize(int(size * 1.55))
    p.setFont(f)
    p.setPen(QtGui.QColor(colour))
    p.drawText(pm.rect(), QtCore.Qt.AlignCenter, glyph)
    p.end()
    pm.setDevicePixelRatio(2.0)
    return QtGui.QIcon(pm)


def decorate_tabs(tabs: QtWidgets.QTabWidget):
    tabs.setIconSize(QtCore.QSize(13, 13))
    tabs.tabBar().setElideMode(QtCore.Qt.ElideNone)
    for i in range(tabs.count()):
        name = tabs.tabText(i).replace("&&", "&")
        g = PAGES.get(name)
        if g:
            tabs.setTabIcon(i, glyph_icon(g[0], g[1]))
            tabs.setTabToolTip(i, g[3] or g[2])


def decorate_button(b: QtWidgets.QPushButton, tip: str = ""):
    g = BUTTON_GLYPHS.get(b.text())
    if g:
        b.setIcon(glyph_icon(g, "#C9D4E2", 16))
        b.setIconSize(QtCore.QSize(14, 14))
    if tip:
        b.setToolTip(tip)


def vline() -> QtWidgets.QFrame:
    f = QtWidgets.QFrame()
    f.setFrameShape(QtWidgets.QFrame.VLine)
    f.setObjectName("sep")
    f.setFixedWidth(1)
    return f


class PageFrame(QtWidgets.QWidget):
    """A page with its title strip (glyph, name, what it is for) above the page itself."""

    def __init__(self, name: str, inner: QtWidgets.QWidget, parent=None):
        super().__init__(parent)
        self.inner = inner
        glyph, colour, title, about = PAGES.get(name, ("\u25c6", ACCENT, name.title(), ""))
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(8)
        strip = QtWidgets.QFrame()
        strip.setObjectName("pagehead")
        c = QtGui.QColor(colour)
        strip.setStyleSheet("QFrame#pagehead { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                            "stop:0 rgba(%d,%d,%d,48), stop:0.7 rgba(15,24,40,0), stop:1 rgba(15,24,40,0)); "
                            "border-left: 3px solid %s; border-radius: 6px; }" % (c.red(), c.green(), c.blue(), colour))
        h = QtWidgets.QHBoxLayout(strip)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(10)
        ic = QtWidgets.QLabel(glyph)
        ic.setStyleSheet("color: %s; font-size: 17pt;" % colour)
        h.addWidget(ic)
        t = QtWidgets.QLabel(title)
        t.setStyleSheet("color: #FFFFFF; font-size: 13pt; font-weight: 700;")
        h.addWidget(t)
        if about:
            a = QtWidgets.QLabel(about)
            a.setStyleSheet("color: %s;" % MUTED)
            a.setWordWrap(True)
            h.addWidget(a, 1)
        else:
            h.addStretch(1)
        v.addWidget(strip)
        sc = QtWidgets.QScrollArea()                 # a page that does not fit scrolls; it never enlarges the window
        sc.setWidgetResizable(True)
        sc.setFrameShape(QtWidgets.QFrame.NoFrame)
        sc.setWidget(inner)
        self.scroll = sc
        v.addWidget(sc, 1)


def unwrap(w: QtWidgets.QWidget) -> QtWidgets.QWidget:
    return w.inner if isinstance(w, PageFrame) else w


class _Card(QtWidgets.QFrame):
    clicked = QtCore.Signal()

    def __init__(self, glyph: str, colour: str, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setMinimumHeight(132)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        top = QtWidgets.QHBoxLayout()
        g = QtWidgets.QLabel(glyph)
        g.setStyleSheet("color:%s; font-size: 22pt;" % colour)
        top.addWidget(g)
        top.addStretch(1)
        go = QtWidgets.QLabel("\u2197")
        go.setStyleSheet("color:%s; font-size: 13pt;" % MUTED)
        top.addWidget(go)
        v.addLayout(top)
        tl = QtWidgets.QLabel(title)
        tl.setStyleSheet("font-size: 11.5pt; font-weight: 700;")
        v.addWidget(tl)
        d = QtWidgets.QLabel(text)
        d.setWordWrap(True)
        d.setStyleSheet("color:%s;" % MUTED)
        v.addWidget(d)
        v.addStretch(1)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


VIEWS = [(0, "\u25a6", ACCENT, "Overview", "The candidate at a glance: band, evidence, the Steward and its saved "
          "layers."),
         (1, "\u25ce", TEAL, "Contour & Surface", "The map with exact cells, contours, UTM grid and any saved "
          "satellite layer; fetch missing layers here."),
         (2, "\u223f", GOLD, "Profile & Section", "Real heights along A\u2013A\u2032 and any line you draw; where a "
          "rise really is."),
         (3, "\u25d2", VIOLET, "3D Visualization", "The terrain in 3D with your choice of drape and height stretch."),
         (4, "\u25a7", ROSE, "Evidence Volume", "The Surfer-3D block: GPR depth slices, ERT faces and your "
          "hypotheses.")]


class VisualizationPage(QtWidgets.QWidget):
    """Every view of the selected candidate's Final Image, one click each."""

    def __init__(self, root: str, mission, parent=None):
        super().__init__(parent)
        self.root, self.mission = root, mission
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        self.who = QtWidgets.QFrame()
        self.who.setObjectName("panel")
        wl = QtWidgets.QHBoxLayout(self.who)
        wl.setContentsMargins(14, 10, 14, 10)
        self.who_text = QtWidgets.QLabel("No candidate selected yet: pick one on Mission Control or in a search.")
        self.who_text.setWordWrap(True)
        wl.addWidget(self.who_text, 1)
        pick = QtWidgets.QPushButton("Choose on Mission Control")
        pick.clicked.connect(self._to_mission)
        wl.addWidget(pick)
        v.addWidget(self.who)
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(10)
        for k, (tab, glyph, colour, title, text) in enumerate(VIEWS):
            c = _Card(glyph, colour, title, text)
            c.clicked.connect(lambda t=tab: self._open(t))
            grid.addWidget(c, k // 3, k % 3)
        rep = _Card("\u2399", GOLD, "Job report (HTML \u00b7 CSV \u00b7 PDF)", "Every candidate of a job with its "
                    "context, and the satellite layers of the leading ones, in Report & Archive.")
        rep.clicked.connect(lambda: self._to_tab("REPORT & ARCHIVE"))
        grid.addWidget(rep, 1, 2)
        v.addLayout(grid)
        v.addStretch(1)

    def showEvent(self, e):
        self.refresh()
        super().showEvent(e)

    def refresh(self):
        cid = getattr(self.mission, "selected", None)
        if not cid:
            self.who_text.setText("No candidate selected yet: pick one on Mission Control or in a search.")
            return
        meta = (self.mission.terrain_data or {}).get("meta") or {}
        self.who_text.setText("<b>Candidate %s</b>%s \u00b7 every card opens its Final Image at that view." % (
            cid[:8], ("  \u00b7  %.5f N, %.5f E" % (meta["lat"], meta["lon"])) if meta.get("lat") is not None else ""))

    def _open(self, tab: int):
        cid = getattr(self.mission, "selected", None)
        if not cid:
            QtWidgets.QMessageBox.information(self, "Visualization", "Pick a candidate first: on Mission Control, "
                                              "or with a search in Grand Project or Investigation.")
            return
        self.mission.open_final_image(cid, start_tab=tab)

    def _to_mission(self):
        self._to_tab("MISSION CONTROL")

    def _to_tab(self, name: str):
        w = self.parentWidget()
        while w is not None and not isinstance(w, QtWidgets.QTabWidget):
            w = w.parentWidget()
        if w is not None:
            for i in range(w.count()):
                if w.tabText(i).replace("&&", "&") == name:
                    w.setCurrentIndex(i)
