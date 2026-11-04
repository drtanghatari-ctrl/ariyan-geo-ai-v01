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

W2 (2026-11-02): "Receive from phone" and "Send to phone" (project_bundle, the
same module the phone uses). Bundles travel through Google Drive for desktop
(G:\\My Drive) or USB; one device works on the project at a time.

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
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 6px 6px; font-weight: 600; font-size: 8.5pt; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:disabled {{ color: #4A5868; }}
QTabWidget::pane {{ border: none; }}
QPushButton {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 8px; padding: 7px 11px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #4A5868; }}
QTableWidget {{ background: {PANEL}; gridline-color: {LINE}; border: none; }}
QHeaderView::section {{ background: {BG}; color: {MUTED}; border: none; padding: 4px; font-weight: 600; }}
QFrame#card {{ background: #0F1828; border: 1px solid {LINE}; border-radius: 10px; }}
QFrame#card:hover {{ border-color: {GOLD}; }}
QFrame#card[on="true"] {{ border: 2px solid {GOLD}; background: #1A1F24; }}
QPushButton#primary {{ background: {ACCENT}; color: #06221A; border: none; font-weight: 700; }}
QPushButton#primary:hover {{ background: #52C99D; }}
QPushButton#primary:disabled {{ background: #173029; color: #5E7C72; }}
QPushButton:disabled {{ color: #5E6B7D; }}
QLineEdit {{ background: #0E1626; border: 1px solid {LINE}; border-radius: 8px; padding: 7px 10px; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QListWidget {{ background: #0E1626; border: 1px solid {LINE}; border-radius: 8px; }}
QListWidget::item {{ padding: 5px 6px; border-bottom: 1px solid #172338; }}
QListWidget::item:selected {{ background: #1B3A33; }}
QListWidget::item:hover {{ background: #142236; }}
QFrame#header {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #102236, stop:0.55 #0D1726, stop:1 #0B1220);
                 border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#sep {{ background: {LINE}; border: none; margin: 4px 0; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabWidget QTabWidget QTabBar::tab {{ background: #0F1828; border: 1px solid {LINE}; border-radius: 8px; margin-right: 4px;
                                     padding: 5px 12px; color: {MUTED}; }}
QTabWidget QTabWidget QTabBar::tab:selected {{ background: #183B32; color: #FFFFFF; border-color: {ACCENT}; }}
QPushButton#danger {{ color: #F2A5B5; }}
QPushButton#danger:hover {{ border-color: {ROSE}; background: #2A1520; }}
QPushButton#cloud {{ color: #BFE3FF; }}
QPushButton#cloud:hover {{ border-color: #6FB8FF; }}
QComboBox, QSpinBox, QDoubleSpinBox {{ background: #0E1626; border: 1px solid {LINE}; border-radius: 8px; padding: 5px 8px; }}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {ACCENT}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: #0E1626; border: 1px solid {LINE}; selection-background-color: #1B3A33; }}
QCheckBox {{ spacing: 8px; background: transparent; }}
QTextBrowser, QTextEdit, QPlainTextEdit {{ background: #0E1626; border: 1px solid {LINE}; border-radius: 8px; padding: 4px; }}
QTableWidget {{ alternate-background-color: #111D30; selection-background-color: #1B3A33; border: 1px solid {LINE};
                border-radius: 8px; }}
QTableCornerButton::section {{ background: {BG}; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2A3B55; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3A5070; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2A3B55; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{ background: #13203A; color: {TEXT}; border: 1px solid {GOLD}; padding: 5px; border-radius: 6px; }}
QProgressBar {{ background: #0E1626; border: 1px solid {LINE}; border-radius: 5px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QStatusBar {{ background: transparent; color: {MUTED}; }}
QMessageBox {{ background: {PANEL}; }}
QGroupBox {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; margin-top: 14px; padding: 14px 10px 8px 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 12px; top: 2px; padding: 0 4px;
                    color: {ACCENT}; font-weight: 700; font-size: 9pt; letter-spacing: 1px; }}
"""


def _imports():
    from PySide6 import QtCore, QtGui, QtWidgets
    return QtCore, QtGui, QtWidgets


def asset(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "ariyan_win", "assets", name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", name)


def sync_folder() -> str:
    """Where bundles are usually found: the folder used last, else Google Drive for desktop."""
    last = config.load().get("sync_folder")
    if last and os.path.isdir(last):
        return last
    for cand in ("G:\\My Drive", os.path.join(os.path.expanduser("~"), "Google Drive"),
                 os.path.join(os.path.expanduser("~"), "My Drive"), os.path.join(os.path.expanduser("~"), "Downloads")):
        if os.path.isdir(cand):
            return cand
    return os.path.expanduser("~")


def remember_sync_folder(path: str) -> None:
    s = config.load()
    s["sync_folder"] = path
    config.save(s)


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
            scr = QtGui.QGuiApplication.primaryScreen()
            avail = scr.availableGeometry() if scr else QtCore.QRect(0, 0, 1440, 900)
            self.resize(min(1440, avail.width()), min(900, avail.height()))   # never larger than the screen
            central = QtWidgets.QWidget()
            self.setCentralWidget(central)
            v = QtWidgets.QVBoxLayout(central)
            v.setContentsMargins(12, 10, 12, 10)
            head = QtWidgets.QFrame()
            head.setObjectName("header")
            head.setLayout(self._header())
            v.addWidget(head)
            self.tabs = QtWidgets.QTabWidget()
            from ariyan_win.mission import Workstation
            from ariyan_win.debates import DebateStudio
            self.mission = Workstation(root)
            self.tabs.addTab(self.mission, "MISSION CONTROL")
            from ariyan_win.dataev import DataEvidence
            from ariyan_win.runs import InvestigationTab, JobsTab

            def selected_coords():
                t = self.mission.terrain_data.get("meta") if self.mission.terrain_data else None
                return (t["lat"], t["lon"]) if t else None
            inv = QtWidgets.QTabWidget()
            self.investigation = InvestigationTab(root, self.mission.open_final_image, selected_coords)
            self.jobs = JobsTab(root)
            inv.addTab(self.investigation, "Single point")
            inv.addTab(self.jobs, "Wide-area jobs")
            from ariyan_win.ui import PageFrame, VisualizationPage, decorate_tabs, decorate_button, vline, unwrap
            self.tabs.addTab(PageFrame("INVESTIGATION", inv), "INVESTIGATION")
            self.dataev = DataEvidence(root)
            self.tabs.addTab(PageFrame("DATA & EVIDENCE", self.dataev), "DATA && EVIDENCE")
            self.debates = DebateStudio(root, self.mission.open_final_image)
            self.tabs.addTab(PageFrame("AI DEBATE STUDIO", self.debates), "AI DEBATE STUDIO")
            self.visual = VisualizationPage(root, self.mission)                # u6: one card per view
            self.tabs.addTab(PageFrame("VISUALIZATION", self.visual), "VISUALIZATION")
            from ariyan_win.grandproject import GrandProject, HistoricalResearch
            self.grand = GrandProject(root)
            self.grand.candidates.search.opened.connect(self.mission.open_final_image)
            self.grand.candidates.view.opened.connect(self.mission.open_final_image)
            self.jobs.open_final_image = self.mission.open_final_image
            from ariyan_win.stewardui import StewardBanner          # sm-v1: the Steward as mentor
            self.steward = StewardBanner(root, self.steward_go)
            self.mission.steward_slot.addWidget(self.steward)
            self.jobs.steward_go = self.steward_go
            self.mission.steward_go = self.steward_go
            self.inv_tabs = inv
            self.tabs.addTab(PageFrame("GRAND PROJECT", self.grand), "GRAND PROJECT")
            self.history = HistoricalResearch(root)
            self.tabs.addTab(PageFrame("HISTORICAL RESEARCH", self.history), "HISTORICAL RESEARCH")
            from ariyan_win.review import AnalysisModels, ReportArchive
            self.models = AnalysisModels(root)
            self.tabs.addTab(PageFrame("ANALYSIS & MODELS", self.models), "ANALYSIS && MODELS")
            self.report = ReportArchive(root, self.mission.open_final_image)
            self.report_index = self.tabs.addTab(PageFrame("REPORT & ARCHIVE", self.report), "REPORT && ARCHIVE")
            decorate_tabs(self.tabs)
            v.addWidget(self.tabs, 1)
            from ariyan_win.stewardui import StewardBar              # u3d: the Steward on every page
            self.steward_bar = StewardBar(root, self.steward_go)
            self.steward_bar.fallback = self._page_context
            self.tabs.currentChanged.connect(lambda i: self.steward_bar.show_tab(self.tabs.tabText(i)))
            self.inv_tabs.currentChanged.connect(lambda i: (self.steward_bar.by_tab.pop("INVESTIGATION", None),
                                                            self.steward_bar.show_tab("INVESTIGATION")))
            v.addWidget(self.steward_bar)
            self.toolbar = QtWidgets.QWidget()
            self.toolbar.setLayout(self._bottom())
            self.toolbar.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
            v.addWidget(self.toolbar)
            for t in self.findChildren(QtWidgets.QTableWidget):              # u6: easier to read rows
                t.setAlternatingRowColors(True)
            self.status = label("", "muted")
            self.statusBar().addWidget(self.status)
            self.reload()

        # ---------------------------------------------------------------- steward
        def _goto(self, top: str, sub: Optional[str] = None):
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i).replace("&&", "&") == top:
                    self.tabs.setCurrentIndex(i)
                    from ariyan_win.ui import unwrap
                    w = unwrap(self.tabs.widget(i))
                    if sub and isinstance(w, QtWidgets.QTabWidget):
                        for k in range(w.count()):
                            if w.tabText(k).replace("&&", "&") == sub:
                                w.setCurrentIndex(k)
                    return w
            return None

        def _page_context(self, tab: str):
            """What each page is already showing, for the Steward bar when you arrive on it."""
            if tab == "MISSION CONTROL" and self.mission.selected:
                return ("candidate", self.mission.selected)
            if tab == "INVESTIGATION":
                if self.inv_tabs.currentWidget() is self.jobs and self.jobs._job_id():
                    return ("job", self.jobs._job_id())
                it = self.investigation.cands.currentItem() or (self.investigation.cands.item(0)
                                                                if self.investigation.cands.count() else None)
                if self.inv_tabs.currentWidget() is self.investigation and it:
                    return ("candidate", it.data(QtCore.Qt.UserRole))
            if tab == "GRAND PROJECT" and getattr(self.grand.candidates.view, "shown", None):
                return ("candidate", self.grand.candidates.view.shown)
            if tab == "REPORT & ARCHIVE" and self.report.cid:
                return ("candidate", self.report.cid)
            return None

        def steward_go(self, action: str, job_id: Optional[str] = None, cid: Optional[str] = None):
            """Take the user to where the Steward's suggestion is done (and start what the button names)."""
            from ariyan_win import mentor
            top, sub = mentor.WHERE.get(action, (None, None))
            if action == "receive":
                self.receive_from_phone()
                return
            if action == "final_image":
                self.mission.open_final_image(cid or job_id)
                return
            if action == "review_cand":
                self._goto("REPORT & ARCHIVE")
                rep = self.report
                if not rep._jobs_loaded:
                    rep._load_jobs()
                rep.job.setCurrentIndex(0)
                rep.status.setCurrentIndex(0)
                rep.band.setCurrentIndex(0)
                rep.find.setText((cid or "")[:8])
                rep.pending_select = cid
                rep.load(0)
                return
            if action == "rerun_point":
                self._goto("INVESTIGATION", "Single point")
                try:
                    from ariyan_win import workstation
                    c = workstation.candidate_detail_light(self.root, cid)
                    self.investigation.lat.setValue(c["lat"])
                    self.investigation.lon.setValue(c["lon"])
                except Exception:
                    pass
                return
            if top:
                self._goto(top, sub)
            if action in ("auto", "retry", "run_job", "new_job"):
                if job_id:
                    for i in range(self.jobs.jobs.count()):
                        if self.jobs.jobs.item(i).data(QtCore.Qt.UserRole) == job_id:
                            self.jobs.jobs.setCurrentRow(i)
                if action == "auto" and job_id:
                    self.jobs._auto()
                elif action == "retry" and job_id:
                    self.jobs._retry()
                elif action == "new_job":
                    self.jobs._new_job()
            elif action in ("target", "trust"):
                t = self.grand.jobs
                for r in range(t.rowCount()):
                    it = t.item(r, 0)
                    if it and it.data(QtCore.Qt.UserRole) == job_id:
                        t.selectRow(r)
                        (self.grand._target if action == "target" else self.grand._trust)()
                        break
            elif action in ("review", "report"):
                rep = self.report
                if not rep._jobs_loaded:
                    rep._load_jobs()
                i = rep.job.findData(job_id)
                if i >= 0:
                    rep.job.setCurrentIndex(i)
                if action == "review":
                    rep.status.setCurrentIndex(max(0, rep.status.findData("GENERATED")))
                    rep.load(0)
                else:
                    rep.generate_report()
            self.steward.load()
            self.steward_bar.refresh()

        # ---------------------------------------------------------------- header
        def _header(self):
            h = QtWidgets.QHBoxLayout()
            h.setContentsMargins(12, 6, 12, 6)
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
            recv = QtWidgets.QPushButton("Receive from phone")
            recv.clicked.connect(self.receive_from_phone)
            send = QtWidgets.QPushButton("Send to phone")
            send.clicked.connect(self.send_to_phone)
            from ariyan_win.ui import decorate_button, vline, glyph_icon
            self._tools = []                     # (button, full text): shortened to icons when space is short
            decorate_button(recv, "Choose a project bundle (.ariyan) the phone made, from a folder or a USB stick")
            decorate_button(send, "Make a project bundle for the phone, in a folder or on a USB stick")
            h.setSpacing(6)
            h.addWidget(recv)
            h.addWidget(send)
            cloud = QtWidgets.QPushButton("\u2601  Google Drive")             # win-u5: online storage
            cloud.setObjectName("cloud")
            cloud.setToolTip("Upload this project to your Google Drive, or download and receive one from it")
            cloud.clicked.connect(self.open_cloud)
            cloud.setText("Google Drive")
            cloud.setIcon(glyph_icon("\u2601", "#BFE3FF", 16))
            cloud.setIconSize(QtCore.QSize(14, 14))
            h.addWidget(cloud)
            h.addSpacing(4)
            h.addWidget(vline())
            h.addSpacing(4)
            newinv = QtWidgets.QPushButton("New Investigation")
            decorate_button(newinv, "Go to Investigation: a single point or a wide-area job")
            newinv.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
            h.addWidget(newinv)
            gen = QtWidgets.QPushButton("Generate Report")
            gen.clicked.connect(lambda: (self.tabs.setCurrentIndex(self.report_index), self.report.generate_report()))
            exr = QtWidgets.QPushButton("Export Results")
            exr.clicked.connect(lambda: self.report.export_results())
            decorate_button(gen, "Write the job report: HTML, CSV and PDF, with the satellite layers")
            decorate_button(exr, "Export all results as CSV and GeoJSON")
            h.addWidget(gen)
            h.addWidget(exr)
            h.addStretch(1)
            sett = QtWidgets.QPushButton("Settings")
            sett.clicked.connect(self.open_settings)
            h.addWidget(sett)
            choose = QtWidgets.QPushButton("Data folder\u2026")
            choose.clicked.connect(self.choose_root)
            opendir = QtWidgets.QPushButton("Open data folder")
            opendir.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.root)))
            refresh = QtWidgets.QPushButton("Refresh")
            refresh.clicked.connect(self.reload)
            quit_ = QtWidgets.QPushButton("Exit Laboratory")
            quit_.clicked.connect(self.close)
            decorate_button(sett, "Keys for OpenTopography and Copernicus, and other settings")
            decorate_button(choose, "Choose which data folder (offline_data) this computer works on")
            decorate_button(opendir, "Open the data folder in Windows Explorer")
            decorate_button(refresh, "Read the project again from the database")
            decorate_button(quit_, "Close ARIYAN GEO AI")
            quit_.setObjectName("danger")
            h.addSpacing(4)
            h.addWidget(vline())
            h.addSpacing(4)
            for b in (choose, opendir, refresh):
                h.addWidget(b)
            h.addSpacing(4)
            h.addWidget(vline())
            h.addSpacing(4)
            h.addWidget(quit_)
            # the order in which labels give way to icons (least used first; Exit and Drive keep theirs longest)
            for b in (opendir, choose, refresh, sett, exr, newinv, gen, send, recv, cloud, quit_):
                self._tools.append((b, b.text()))
                if not b.toolTip():
                    b.setToolTip(b.text())
            return h

        def _fit_toolbar(self):
            """Labels give way to icons, one by one, until the toolbar fits the window."""
            room = self.centralWidget().width() - 30
            for b, t in self._tools:
                b.setText(t)
            for b, t in self._tools:
                if self.toolbar.layout().sizeHint().width() <= room:
                    break
                b.setText("")
                b.setMinimumWidth(38)

        def resizeEvent(self, e):
            super().resizeEvent(e)
            if hasattr(self, "_tools"):
                self._fit_toolbar()
            # safety net: the window never grows past the screen by itself
            if not (self.isMaximized() or self.isFullScreen()):
                scr = self.screen() or QtGui.QGuiApplication.primaryScreen()
                if scr is not None:
                    a = scr.availableGeometry()
                    fw, fh = self.frameGeometry().width() - self.width(), self.frameGeometry().height() - self.height()
                    mw, mh = a.width() - fw, a.height() - fh
                    if self.width() > mw or self.height() > mh:
                        QtCore.QTimer.singleShot(0, lambda: self.resize(min(self.width(), mw), min(self.height(), mh)))

        # ---------------------------------------------------------------- W2 transfer
        def _run_blocking(self, title: str, fn, *args):
            """Run a core call off the screen thread with a small 'working' window."""
            dlg = QtWidgets.QProgressDialog(title, None, 0, 0, self)
            dlg.setWindowTitle("ARIYAN GEO AI")
            dlg.setWindowModality(QtCore.Qt.WindowModal)
            dlg.setMinimumDuration(0)
            box: Dict[str, Any] = {}
            loop = QtCore.QEventLoop()
            w = Worker(fn, *args)
            w.setAutoDelete(False)
            w.signals.done.connect(lambda r: (box.update(r=r), loop.quit()))
            self._xfer = w
            QtCore.QThreadPool.globalInstance().start(w)
            dlg.show()
            loop.exec()
            dlg.close()
            return box.get("r", {"error": "no answer"})

        def receive_from_phone(self):
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Choose the project bundle the phone sent (.ariyan)", sync_folder(),
                "ARIYAN project bundle (*.ariyan);;All files (*)")
            if not path:
                return
            self.receive_path(path)

        def receive_path(self, path: str, where: str = "the phone") -> bool:
            """Check and receive one bundle file (from a folder, a USB stick or Google Drive)."""
            import project_bundle as pb
            chk = self._run_blocking("Checking the bundle\u2026", lambda: json.loads(pb.check_receive_json(self.root, path)))
            if "error" in chk:
                QtWidgets.QMessageBox.warning(self, "Not received", chk["error"])
                return False
            m, p = chk.get("manifest", {}), chk.get("manifest", {}).get("project", {})
            text = ("From the %s, made %s UTC\n%s candidates \u00b7 %s jobs \u00b7 %s library files\n\n"
                    % (m.get("from_device"), (m.get("created_at") or "")[:16].replace("T", " "),
                       "{:,}".format(p.get("candidates", 0)), "{:,}".format(p.get("jobs", 0)),
                       "{:,}".format(m.get("library_files", 0))))
            text += "".join("\u26a0 %s\n\n" % w for w in chk.get("warnings", []))
            text += "The current project (if any) is kept as a safety copy in db_backups before anything changes."
            confirm = chk.get("needs_confirm", False)
            ans = QtWidgets.QMessageBox.question(self, "Replace this computer's project?" if confirm else "Receive this project?",
                                                 text, QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel)
            if ans != QtWidgets.QMessageBox.Yes:
                return False
            r = self._run_blocking("Receiving the project\u2026",
                                   lambda: json.loads(pb.receive_json(self.root, path, "laptop", confirm)))
            if "error" in r or not r.get("received"):
                QtWidgets.QMessageBox.warning(self, "Not received", r.get("error", "Nothing was changed."))
                self.reload()
                return False
            else:
                f = r.get("files", {})
                QtWidgets.QMessageBox.information(self, "Project received",
                    "This computer now has the project from %s.\n%s library files added, %s already here.\n"
                    "Previous project kept as: %s" % (where, "{:,}".format(f.get("added", 0)), "{:,}".format(f.get("kept", 0)),
                                                      os.path.basename(r.get("safety_copy") or "") or "none"))
            self.reload()
            return True

        def send_to_phone(self):
            out = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Where to put the bundle (your Google Drive folder, or a USB stick)", sync_folder())
            if not out:
                return
            import project_bundle as pb
            r = self._run_blocking("Preparing the project bundle\u2026",
                                   lambda: json.loads(pb.make_bundle_json(self.root, out, "laptop")))
            if "error" in r:
                QtWidgets.QMessageBox.warning(self, "Not sent", r["error"])
                return
            remember_sync_folder(out)
            QtWidgets.QMessageBox.information(self, "Bundle ready",
                "%s (%.0f MB) is in\n%s\n\nOn the phone: Settings \u2192 Receive project from laptop, then choose "
                "this file in Google Drive. Work on the phone from now on, until you send it back."
                % (r["name"], r["bytes"] / 1e6, out))
            self.reload()

        def open_cloud(self):
            from ariyan_win.cloud import CloudDialog
            CloudDialog(self).exec()
            self.reload()

        def open_settings(self):
            from ariyan_win.settingsdlg import SettingsDialog
            SettingsDialog(self.root, self).exec()
            self.reload()

        def choose_root(self):
            d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose the ARIYAN data folder (offline_data)", self.root)
            if d:
                config.set_data_root(d)
                self.root = d
                self.mission.root = d
                self.mission.selected = None
                self.debates.root = d
                self.dataev.root = d
                self.investigation.root = d
                self.jobs.root = d
                self.jobs.cand_search.root = d
                self.jobs.guide.root = d
                self.mission.job_guide.root = d
                self.steward.root = d
                self.steward_bar.root = d
                self.report.root = d
                self.models.root = d
                self.grand.root = d
                self.grand.candidates.set_root(d)
                self.history.root = d
                self.reload()

        # ---------------------------------------------------------------- data
        def reload(self):
            if getattr(self, "_busy", False):        # one read at a time (never two first-time opens at once)
                return
            self._busy = True
            self.mission.terrain_data = {}             # re-read the selected candidate too
            if hasattr(self, "steward"):
                self.steward.load()
            if hasattr(self, "steward_bar"):
                self.steward_bar.refresh()
            if hasattr(self, "debates"):
                self.debates.load(append=False)
            if hasattr(self, "dataev"):
                self.dataev.load()
            if hasattr(self, "jobs"):
                self.jobs.load()
            if hasattr(self, "report"):
                self.report._jobs_loaded = False
                self.report.load(0)
            if hasattr(self, "grand"):
                self.grand.load()
                self.history.load_saved()
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
            try:
                import project_bundle as pb
                h = pb.handoff(self.root)
            except Exception:
                h = {}
            if h.get("state") == "SENT":
                self._pill("Sent to the phone: work there", False)
            elif h.get("state") == "RECEIVED":
                self._pill("Received from the " + str(h.get("from")), True)
            self.status.setText("Data folder: " + self.root)
            if o.get("project") is None and "error" not in o:
                self.mission.terrain.set_message((o.get("empty_note") or "") + "\n\nUse \u201cReceive from phone\u201d "
                                                 "below to load your phone's project here.")
            self.mission.show_mission(o)

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
    # win-w4a.1: open filling the screen, so the bottom bar (Settings, Receive/Send, ...) is always visible
    w.showMaximized()
    return app.exec()
