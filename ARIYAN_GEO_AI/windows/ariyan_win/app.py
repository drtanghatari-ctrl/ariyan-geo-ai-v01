"""
ARIYAN GEO AI for Windows -- W0 (2026-11-02): the foundation.

* Same Python core as the phone (core_path.py loads the very same .py files).
* Main window in the Windows mock-up's layout language: emblem header, status
  pills, tab bar, Mission Control first, bottom action bar.
* W0's Mission Control is a real but simple read-out of mission_control.mission_json
  (study area, Steward band and ceiling, top targets, data sources). The full
  workstation (3D terrain, gauge, panels) is W1. Tabs and bottom buttons that
  belong to later steps are visible but disabled and say which step brings them.
* Nothing here writes to the project; it only reads.

Run from source:  python -m ariyan_win
Self-test (CI):   python -m ariyan_win --selftest   (works headless, offscreen)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from typing import Any, Dict, List, Optional

from ariyan_win import VERSION, config, core_path

BG = "#0B1220"
PANEL = "#111A2B"
LINE = "#22324A"
TEXT = "#E6EDF3"
MUTED = "#8B9BB0"
ACCENT = "#3FB68B"
TEAL = "#2FA6B8"
GOLD = "#F2C14E"
AMBER = "#D9A62B"
ORANGE = "#D9822B"
ROSE = "#E0607E"
BAND_COLOURS = {"SUBSTANTIAL": "#2E7D32", "HIGH": ACCENT, "MODERATE": AMBER, "LOW": ORANGE,
                "NO_DATA": "#6E7681", "NOT_RATED": "#3A414A"}

STYLE = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-family: 'Segoe UI', 'Noto Sans', sans-serif; font-size: 10pt; }}
QLabel {{ background: transparent; }}
QFrame#panel {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; }}
QLabel#title {{ font-size: 20pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#sub {{ color: {MUTED}; font-size: 9pt; letter-spacing: 2px; }}
QLabel#tag {{ color: {ACCENT}; font-size: 11pt; font-weight: 600; }}
QLabel#h {{ color: {ACCENT}; font-size: 9pt; font-weight: 700; letter-spacing: 1px; background: transparent; }}
QLabel#muted {{ color: {MUTED}; background: transparent; }}
QLabel#pill {{ border: 1px solid {LINE}; border-radius: 6px; padding: 4px 10px; background: {PANEL}; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 16px; font-weight: 600; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:disabled {{ color: #4A5868; }}
QTabWidget::pane {{ border: none; }}
QPushButton {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 8px; padding: 8px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #4A5868; }}
QTableWidget {{ background: {PANEL}; gridline-color: {LINE}; border: none; }}
QHeaderView::section {{ background: {BG}; color: {MUTED}; border: none; padding: 4px; font-weight: 600; }}
"""


def _imports():
    from PySide6 import QtCore, QtGui, QtWidgets
    return QtCore, QtGui, QtWidgets


def asset(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "ariyan_win", "assets", name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", name)


def load_mission(root: str) -> Dict[str, Any]:
    import mission_control
    return json.loads(mission_control.mission_json(root, 10))


def build_window(root: str):
    QtCore, QtGui, QtWidgets = _imports()

    class Signals(QtCore.QObject):
        done = QtCore.Signal(dict)

    class Worker(QtCore.QRunnable):
        """Runs a core call off the screen thread; the result comes back as a signal."""
        def __init__(self, fn, *args):
            super().__init__()
            self.fn, self.args = fn, args
            self.signals = Signals()

        def run(self):
            try:
                r = self.fn(*self.args)
            except Exception as e:                       # shown, never hidden
                r = {"error": "%s: %s" % (type(e).__name__, e)}
            self.signals.done.emit(r)

    def label(text: str, obj: str = "", wrap: bool = False):
        w = QtWidgets.QLabel(text)
        if obj:
            w.setObjectName(obj)
        w.setWordWrap(wrap)
        return w

    def panel(title: str):
        f = QtWidgets.QFrame()
        f.setObjectName("panel")
        lay = QtWidgets.QVBoxLayout(f)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.addWidget(label(title, "h"))
        return f, lay

    class Main(QtWidgets.QMainWindow):
        def __init__(self):
            super().__init__()
            self.root = root
            self.setWindowTitle("ARIYAN GEO AI \u2014 Scientific Geospatial Laboratory")
            self.setWindowIcon(QtGui.QIcon(asset("ariyan.ico")))
            self.resize(1440, 900)
            central = QtWidgets.QWidget()
            self.setCentralWidget(central)
            v = QtWidgets.QVBoxLayout(central)
            v.setContentsMargins(12, 10, 12, 10)
            v.addLayout(self._header())
            self.tabs = QtWidgets.QTabWidget()
            self.mission = QtWidgets.QWidget()
            self.tabs.addTab(self.mission, "MISSION CONTROL")
            for name, step in (("INVESTIGATION", "W4"), ("DATA & EVIDENCE", "W4"), ("AI DEBATE STUDIO", "W1"),
                               ("ANALYSIS & MODELS", "W1"), ("VISUALIZATION", "W3"), ("REPORT & ARCHIVE", "W4")):
                w = QtWidgets.QWidget()
                QtWidgets.QVBoxLayout(w).addWidget(label("%s arrives in step %s." % (name.title(), step), "muted"))
                i = self.tabs.addTab(w, name.replace("&", "&&"))   # a single & would become a shortcut mark
                self.tabs.setTabEnabled(i, False)
                self.tabs.setTabToolTip(i, "Arrives in step " + step)
            v.addWidget(self.tabs, 1)
            v.addLayout(self._bottom())
            self.mission_layout = QtWidgets.QGridLayout(self.mission)
            self.mission_layout.setSpacing(10)
            self.status = label("", "muted")
            self.statusBar().addWidget(self.status)
            self.reload()

        # ---------------------------------------------------------------- header
        def _header(self):
            h = QtWidgets.QHBoxLayout()
            logo = QtWidgets.QLabel()
            pm = QtGui.QPixmap(asset("ariyan_emblem.png"))
            if not pm.isNull():
                logo.setPixmap(pm.scaled(72, 72, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            h.addWidget(logo)
            t = QtWidgets.QVBoxLayout()
            t.addWidget(label("ARIYAN GEO AI", "title"))
            t.addWidget(label("SCIENTIFIC GEOSPATIAL LABORATORY", "sub"))
            t.addWidget(label("Evidence.  Reasoning.  Confidence.", "tag"))
            h.addLayout(t)
            h.addStretch(1)
            self.pills = QtWidgets.QHBoxLayout()
            h.addLayout(self.pills)
            return h

        def _pill(self, text: str, ok: bool):
            p = label(("\u2713  " if ok else "\u2717  ") + text, "pill")
            p.setStyleSheet("color: %s;" % (ACCENT if ok else ORANGE))
            self.pills.addWidget(p)

        # ---------------------------------------------------------------- bottom bar
        def _bottom(self):
            h = QtWidgets.QHBoxLayout()
            later = (("New Investigation", "W4"), ("Open Project", "W2"), ("Receive from phone", "W2"),
                     ("Send to phone", "W2"), ("Generate Report", "W4"), ("Export Results", "W4"))
            for name, step in later:
                b = QtWidgets.QPushButton(name)
                b.setEnabled(False)
                b.setToolTip("Arrives in step " + step)
                h.addWidget(b)
            h.addStretch(1)
            choose = QtWidgets.QPushButton("Data folder\u2026")
            choose.clicked.connect(self.choose_root)
            opendir = QtWidgets.QPushButton("Open data folder")
            opendir.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.root)))
            refresh = QtWidgets.QPushButton("Refresh")
            refresh.clicked.connect(self.reload)
            quit_ = QtWidgets.QPushButton("Exit Laboratory")
            quit_.clicked.connect(self.close)
            for b in (choose, opendir, refresh, quit_):
                h.addWidget(b)
            return h

        def choose_root(self):
            d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose the ARIYAN data folder (offline_data)", self.root)
            if d:
                config.set_data_root(d)
                self.root = d
                self.reload()

        # ---------------------------------------------------------------- data
        def reload(self):
            if getattr(self, "_busy", False):        # one read at a time (never two first-time opens at once)
                return
            self._busy = True
            while self.mission_layout.count():
                it = self.mission_layout.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            while self.pills.count():
                it = self.pills.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            self.status.setText("Reading %s \u2026" % self.root)
            w = Worker(load_mission, self.root)
            w.setAutoDelete(False)
            w.signals.done.connect(self.show_mission)
            self._worker = w                      # keep a reference while it runs
            QtCore.QThreadPool.globalInstance().start(w)

        def show_mission(self, o: Dict[str, Any]):
            self._busy = False
            self.render_mission(o)

        def render_mission(self, o: Dict[str, Any]):
            db_ok = os.path.isfile(os.path.join(self.root, "grand_project.db"))
            self._pill("Offline laboratory", True)
            self._pill("Core " + VERSION, True)
            self._pill("Project database" if db_ok else "No project database yet", db_ok)
            self.status.setText("Data folder: " + self.root)
            g = self.mission_layout
            if "error" in o:
                f, lay = panel("COULD NOT READ THE PROJECT")
                lay.addWidget(label(o["error"], wrap=True))
                g.addWidget(f, 0, 0)
                return
            # study area
            f, lay = panel("STUDY AREA")
            p = o.get("project")
            if p is None:
                lay.addWidget(label(o.get("empty_note", ""), wrap=True))
                lay.addWidget(label("Step W2 brings \u201cReceive from phone\u201d, which loads your phone's project here.",
                                    "muted", wrap=True))
            else:
                lay.addWidget(label(p["name"]))
                lay.addWidget(label("{:,} wide-area jobs \u00b7 {:,} investigations \u00b7 {:,} candidates".format(
                    p["jobs"], p["investigations"], p["candidates"]), "muted"))
                sc = p.get("status_counts", {})
                lay.addWidget(label("  \u00b7  ".join("%s %s" % (k, "{:,}".format(v)) for k, v in sc.items()), "muted"))
            lay.addStretch(1)
            g.addWidget(f, 0, 0)
            # assessment
            f, lay = panel("FINAL SCIENTIFIC ASSESSMENT")
            c = o.get("confidence") or {}
            hi = c.get("highest")
            big = label((hi or "Not rated") + ("   %.2f" % c["highest_numeric"] if c.get("highest_numeric") is not None else ""))
            big.setStyleSheet("font-size: 22pt; font-weight: 700; color: %s; background: transparent;" % BAND_COLOURS.get(hi or "", TEXT))
            lay.addWidget(big)
            if c.get("why"):
                lay.addWidget(label("Why not higher: " + c["why"], wrap=True))
            for b in c.get("bands", []):
                if b["count"]:
                    lay.addWidget(label("\u25a0 %s  %s" % (b["band"].title(), "{:,}".format(b["count"])), "muted"))
            lay.addWidget(label("The round gauge and the 3D terrain arrive in step W1.", "muted", wrap=True))
            lay.addStretch(1)
            g.addWidget(f, 0, 1)
            # targets
            f, lay = panel("CANDIDATE TARGETS")
            t = QtWidgets.QTableWidget(0, 6)
            t.setHorizontalHeaderLabels(["ID", "Latitude", "Longitude", "Band", "Status", "Recorded site"])
            t.verticalHeader().setVisible(False)
            t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            for r in o.get("top", []):
                i = t.rowCount()
                t.insertRow(i)
                vals = [r["id"][:8], "%.5f" % r["lat"], "%.5f" % r["lon"],
                        "%s%s" % (r["band"].title(), "" if r.get("numeric") is None else " %.2f" % r["numeric"]),
                        r.get("status") or "", r.get("known_site") or ""]
                for j, s in enumerate(vals):
                    t.setItem(i, j, QtWidgets.QTableWidgetItem(s))
            t.horizontalHeader().setStretchLastSection(True)
            t.resizeColumnsToContents()
            lay.addWidget(t)
            g.addWidget(f, 1, 0, 1, 2)
            # sources
            f, lay = panel("DATA SOURCES (on this computer)")
            for s in o.get("sources", []):
                x = label(("\u2713  " if s["ok"] else "\u2717  ") + s["name"] + " \u2014 " + s["detail"], wrap=True)
                x.setStyleSheet("color: %s; background: transparent;" % (ACCENT if s["ok"] else ORANGE))
                lay.addWidget(x)
            lay.addStretch(1)
            g.addWidget(f, 0, 2, 2, 1)
            foot = label("Real Data Only \u00b7 Scientific Integrity \u00b7 No Synthetic Data \u00b7 "
                         "Uncertainty Quantified \u00b7 Human Oversight", "tag")
            foot.setAlignment(QtCore.Qt.AlignCenter)
            g.addWidget(foot, 2, 0, 1, 3)
            g.setColumnStretch(0, 3); g.setColumnStretch(1, 3); g.setColumnStretch(2, 2)

    return Main()


# Third-party packages a few desktop-only research tools use (charts, GDAL); the
# app's screens never need them, so a module that only lacks one is skipped, not failed.
OPTIONAL_EXTRAS = {"matplotlib", "rasterio", "pystac_client", "scipy"}


def selftest() -> int:
    """Headless check used by CI and by the built .exe: every core module imports,
    the window builds, and Mission Control reads a fresh empty data folder."""
    out_path = os.path.join(tempfile.gettempdir(), "ariyan_selftest.txt")
    lines: List[str] = []
    ok = True

    def note(msg: str) -> None:                 # written as it goes, so a crash still leaves a trail
        lines.append(msg)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        d = core_path.install()
        note("core: " + d)
        failed = []
        for m in core_path.core_modules():
            try:
                if os.environ.get("ARIYAN_SELFTEST_TRACE"):
                    note("importing " + m)
                __import__(m)
            except ModuleNotFoundError as e:
                if (e.name or "").split(".")[0] in OPTIONAL_EXTRAS:
                    note("  skipped %s (needs optional %s, desktop tool only)" % (m, e.name))
                else:
                    failed.append("%s (%s: %s)" % (m, type(e).__name__, e))
            except Exception as e:
                failed.append("%s (%s: %s)" % (m, type(e).__name__, e))
        note("core modules checked: %d, failed: %d" % (len(core_path.core_modules()), len(failed)))
        for f in failed:
            note("  FAILED " + f)
        ok = ok and not failed
        QtCore, QtGui, QtWidgets = _imports()
        note("qt imported")
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["ariyan", "-platform", "offscreen"])
        note("qt application started")
        tmp = tempfile.mkdtemp(prefix="ariyan_selftest_")
        w = build_window(tmp)
        QtCore.QThreadPool.globalInstance().waitForDone(30000)   # the window's own first read
        note("window built")
        o = load_mission(tmp)
        w.render_mission(o)
        QtCore.QThreadPool.globalInstance().waitForDone(30000)   # let the window's own read finish
        note("mission control on an empty folder: " + ("error " + o["error"] if "error" in o else "ok"))
        ok = ok and "error" not in o
        w.close()
        app.processEvents()
    except Exception:
        ok = False
        note(traceback.format_exc())
    note("SELFTEST " + ("PASS" if ok else "FAIL") + " " + VERSION)
    try:
        print("\n".join(lines))
    except Exception:
        pass                                   # a windowed .exe has no console
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv or sys.argv)
    if "--selftest" in argv:
        return selftest()
    core_path.install()
    QtCore, QtGui, QtWidgets = _imports()
    app = QtWidgets.QApplication(argv)
    app.setApplicationName("ARIYAN GEO AI")
    app.setWindowIcon(QtGui.QIcon(asset("ariyan.ico")))
    app.setStyleSheet(STYLE)
    w = build_window(config.data_root())
    w.show()
    return app.exec()
