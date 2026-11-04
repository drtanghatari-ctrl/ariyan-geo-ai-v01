"""
The Steward Mentor on screen (sm-v1): a welcome banner at Mission Control and a
step-by-step guide card for the job you are working on. Buttons only take you to
the place (and start what the button names); the Steward never decides for you.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ariyan_win import mentor, qtwork

GOLD, ACCENT, TEAL, MUTED, ROSE = "#F2C14E", "#3FB68B", "#2FA6B8", "#8B9BB0", "#E0607E"
ICON = {"done": ("\u2713", ACCENT), "todo": ("\u25cf", GOLD), "working": ("\u25d4", TEAL),
        "waiting": ("\u25cb", MUTED), "advice": ("\u2726", "#9A7BFF")}

STYLE = """
QFrame#steward { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1E1A0E, stop:1 #111A2B);
                 border: 1px solid #5A4A1E; border-radius: 12px; }
QLabel#stewardHead { color: %s; font-weight: 800; letter-spacing: 2px; font-size: 9pt; }
QLabel#stewardSay { color: #F3E7C4; font-size: 11pt; }
QProgressBar { background: #0E1626; border: 1px solid #22324A; border-radius: 5px; height: 10px; text-align: center;
               color: transparent; }
QProgressBar::chunk { background: %s; border-radius: 4px; }
""" % (GOLD, GOLD)


def _lab(text="", obj="", colour=None, bold=False, wrap=True):
    w = QtWidgets.QLabel(text)
    if obj:
        w.setObjectName(obj)
    w.setWordWrap(wrap)
    css = []
    if colour:
        css.append("color: %s;" % colour)
    if bold:
        css.append("font-weight: 700;")
    if css:
        w.setStyleSheet(" ".join(css))
    return w


def _clear(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            _clear(it.layout())


class _Emblem(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(54, 54)
        try:
            from ariyan_win.app import asset
            pm = QtGui.QPixmap(asset("ariyan_emblem.png"))
            if pm.isNull():
                raise ValueError
            self.setPixmap(pm.scaled(54, 54, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        except Exception:
            self.setText("\u2726")
            self.setAlignment(QtCore.Qt.AlignCenter)
            self.setStyleSheet("color: %s; font-size: 26pt; border: 2px solid %s; border-radius: 27px;" % (GOLD, GOLD))


class StewardBanner(QtWidgets.QFrame):
    """Mission Control: the Steward's welcome, where the project stands, and the first suggestion."""

    def __init__(self, root: str, go: Callable[[str, Optional[str]], None], parent=None):
        super().__init__(parent)
        self.root, self.go = root, go
        self.setObjectName("steward")
        self.setStyleSheet(STYLE)
        h = QtWidgets.QHBoxLayout(self)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(14)
        h.addWidget(_Emblem(), 0, QtCore.Qt.AlignTop)
        mid = QtWidgets.QVBoxLayout()
        mid.setSpacing(3)
        self.head = _lab("THE SCIENTIFIC STEWARD \u00b7 YOUR MENTOR", "stewardHead")
        self.hello = _lab("", colour="#FFFFFF", bold=True)
        self.say = _lab("Reading the project\u2026", "stewardSay")
        mid.addWidget(self.head)
        mid.addWidget(self.hello)
        mid.addWidget(self.say)
        self.jobs_box = QtWidgets.QVBoxLayout()
        self.jobs_box.setSpacing(2)
        self.jobs_wrap = QtWidgets.QWidget()
        self.jobs_wrap.setStyleSheet("background: transparent;")
        self.jobs_wrap.setLayout(self.jobs_box)
        self.jobs_wrap.hide()
        mid.addWidget(self.jobs_wrap)
        h.addLayout(mid, 1)
        right = QtWidgets.QVBoxLayout()
        self.act = QtWidgets.QPushButton("")
        self.act.setObjectName("primary")
        self.act.hide()
        self.act.clicked.connect(self._act)
        self.more = QtWidgets.QPushButton("Every job\u2019s path \u25be")
        self.more.setCheckable(True)
        self.more.toggled.connect(self._toggle)
        right.addWidget(self.act)
        right.addWidget(self.more)
        right.addStretch(1)
        h.addLayout(right)
        self.guide: Dict[str, Any] = {}

    def load(self):
        qtwork.run_async(mentor.project_guide, self._show, self.root)

    def _show(self, g: Dict[str, Any]):
        self.guide = g
        if "error" in g and "say" not in g:
            self.say.setText(g["error"])
            return
        self.hello.setText(g.get("hello", ""))
        self.say.setText(g.get("say", ""))
        if g.get("action_label"):
            self.act.setText(g["action_label"] + "  \u2192")
            self.act.show()
        else:
            self.act.hide()
        _clear(self.jobs_box)
        for j in g.get("jobs", []):
            row = QtWidgets.QHBoxLayout()
            if "error" in j:
                row.addWidget(_lab("%s \u2014 %s" % (j.get("title"), j["error"]), colour=ROSE))
                self.jobs_box.addLayout(row)
                continue
            bar = QtWidgets.QProgressBar()
            bar.setRange(0, j["total"])
            bar.setValue(j["done"])
            bar.setFixedWidth(120)
            bar.setFixedHeight(10)
            name = _lab("%s%s" % ("\u2713 " if j["complete"] else "", j["title"]), colour=ACCENT if j["complete"]
                        else None, bold=True, wrap=False)
            name.setMinimumWidth(170)
            row.addWidget(name)
            row.addWidget(bar)
            row.addSpacing(6)
            row.addWidget(_lab("%d/%d" % (j["done"], j["total"]), colour=MUTED, wrap=False))
            row.addSpacing(10)
            nxt = j.get("next") or {}
            row.addWidget(_lab("complete" if j["complete"] else "next: " + (nxt.get("name") or "waiting"),
                               colour=MUTED, wrap=False), 1)
            if nxt.get("action"):
                b = QtWidgets.QPushButton((nxt.get("action_label") or "Go").replace("&", "&&"))
                b.clicked.connect(lambda _=False, a=nxt["action"], jid=j["job_id"]: self.go(a, jid))
                row.addWidget(b)
            self.jobs_box.addLayout(row)
        self.more.setVisible(bool(g.get("jobs")))

    def _toggle(self, on: bool):
        self.jobs_wrap.setVisible(on)
        self.more.setText("Every job\u2019s path \u25b4" if on else "Every job\u2019s path \u25be")

    def _act(self):
        if self.guide.get("action"):
            self.go(self.guide["action"], self.guide.get("focus_job"))


class StewardGuide(QtWidgets.QFrame):
    """One job's path, step by step: what is done, what is next and why, and the button for it."""

    def __init__(self, root: str, go: Callable[[str, Optional[str]], None], parent=None, compact: bool = False):
        super().__init__(parent)
        self.root, self.go = root, go
        self.compact = compact
        self.job_id: Optional[str] = None
        self.setObjectName("steward")
        self.setStyleSheet(STYLE)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(4)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(_lab("\u2726  THE STEWARD \u00b7 %s" % ("ITS JOB" if compact else "THIS JOB, STEP BY STEP"),
                           "stewardHead"), 1)
        self.count = _lab("", colour=GOLD, bold=True, wrap=False)
        top.addWidget(self.count)
        v.addLayout(top)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setFixedHeight(10)
        v.addWidget(self.bar)
        self.say = _lab("Select a job and I will guide you through it.", "stewardSay")
        v.addWidget(self.say)
        arow = QtWidgets.QHBoxLayout()
        self.act = QtWidgets.QPushButton("")
        self.act.setObjectName("primary")
        self.act.hide()
        self.act.clicked.connect(self._act)
        arow.addWidget(self.act)
        arow.addStretch(1)
        v.addLayout(arow)
        self.steps = QtWidgets.QGridLayout()
        self.steps.setHorizontalSpacing(8)
        self.steps.setVerticalSpacing(2)
        v.addLayout(self.steps)
        self.guide: Dict[str, Any] = {}

    def load(self, job_id: Optional[str]):
        self.job_id = job_id
        if not job_id:
            _clear(self.steps)
            self.bar.setValue(0)
            self.count.setText("")
            self.act.hide()
            self.say.setText("This candidate comes from a single-point investigation, not a job. Turning it into a "
                             "one-tile job (Grand Project \u2192 Single points) lets me guide it to the end.")
            return
        qtwork.run_async(mentor.job_guide, lambda g, j=job_id: self._show(j, g), self.root, job_id)

    def _show(self, job_id: str, g: Dict[str, Any]):
        if job_id != self.job_id:
            return
        self.guide = g
        _clear(self.steps)
        if "error" in g:
            self.say.setText(g["error"])
            self.act.hide()
            return
        self.bar.setRange(0, g["total"])
        self.bar.setValue(g["done"])
        self.count.setText("\u2713 complete" if g["complete"] else "%d of %d done" % (g["done"], g["total"]))
        self.say.setText("\u201c%s\u201d" % g["say"])
        nxt = g.get("next") or {}
        if nxt.get("action") and nxt.get("state") == "todo":
            self.act.setText(nxt["action_label"].replace("&", "&&") + "  \u2192")
            self.act.show()
        else:
            self.act.hide()
        if self.compact:
            nm = g.get("title") or ""
            self.count.setText(("\u2713 " if g["complete"] else "%d/%d \u00b7 " % (g["done"], g["total"])) + nm[:22])
            return
        for i, s in enumerate(g["steps"]):
            ic, col = ICON.get(s["state"], ("\u25cb", MUTED))
            a = _lab(ic, colour=col, bold=True, wrap=False)
            a.setFixedWidth(16)
            b = _lab(s["name"], colour=col if s["state"] != "waiting" else MUTED, bold=s is nxt, wrap=False)
            b.setMinimumWidth(130)
            short = s["text"].split(". ")[0].rstrip(".") + "."
            c = _lab(short, colour=MUTED if s["state"] in ("done", "waiting") else None)
            c.setToolTip(s["text"])
            self.steps.addWidget(a, i, 0, QtCore.Qt.AlignTop)
            self.steps.addWidget(b, i, 1, QtCore.Qt.AlignTop)
            self.steps.addWidget(c, i, 2)
        self.steps.setColumnStretch(2, 1)

    def _act(self):
        nxt = (self.guide or {}).get("next") or {}
        if nxt.get("action"):
            self.go(nxt["action"], self.job_id)


# ---------------------------------------------------------------- u3d: the Steward everywhere
class _Bus(QtCore.QObject):
    """Every page tells the Steward what you are looking at; the Steward bar follows."""
    candidate = QtCore.Signal(str)
    job = QtCore.Signal(str)


_BUS: Optional[_Bus] = None


def bus() -> _Bus:
    global _BUS
    if _BUS is None:
        _BUS = _Bus()
    return _BUS


def _seen(source) -> bool:
    """Only a page you are looking at moves the Steward (pages filling in the background do not)."""
    try:
        return source is None or source.isVisible()
    except Exception:
        return True


def focus_candidate(cid: Optional[str], source=None):
    if cid and _seen(source):
        bus().candidate.emit(str(cid))


def focus_job(jid: Optional[str], source=None):
    if jid and _seen(source):
        bus().job.emit(str(jid))


class StewardBar(QtWidgets.QFrame):
    """Always on screen, above the toolbar: guidance for what you are looking at -- a candidate,
    a job or the page -- with the next step and its button. "Path" shows every step."""

    def __init__(self, root: str, go: Callable[..., None], parent=None, follow: bool = True):
        super().__init__(parent)
        self.root, self.go = root, go
        self.setObjectName("steward")
        self.setStyleSheet(STYLE)
        self.context: Optional[tuple] = None          # ("candidate"|"job", id)
        self.by_tab: Dict[str, tuple] = {}
        self.fallback: Optional[Callable[[str], Optional[tuple]]] = None   # what the page already shows
        self.tab = "MISSION CONTROL"
        self.guide: Dict[str, Any] = {}
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(10, 6, 10, 6)
        v.setSpacing(4)
        h = QtWidgets.QHBoxLayout()
        h.setSpacing(10)
        em = QtWidgets.QLabel("\u2726")
        em.setFixedSize(30, 30)
        em.setAlignment(QtCore.Qt.AlignCenter)
        em.setStyleSheet("color: %s; font-size: 14pt; border: 1px solid %s; border-radius: 15px;" % (GOLD, GOLD))
        h.addWidget(em, 0, QtCore.Qt.AlignTop)
        mid = QtWidgets.QVBoxLayout()
        mid.setSpacing(1)
        self.head = _lab("THE SCIENTIFIC STEWARD", "stewardHead", wrap=False)
        self.say = _lab("", "stewardSay")
        mid.addWidget(self.head)
        mid.addWidget(self.say)
        h.addLayout(mid, 1)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setFixedSize(90, 10)
        self.bar.hide()
        h.addWidget(self.bar, 0, QtCore.Qt.AlignVCenter)
        self.act = QtWidgets.QPushButton("")
        self.act.setObjectName("primary")
        self.act.hide()
        self.act.clicked.connect(self._act)
        h.addWidget(self.act, 0, QtCore.Qt.AlignVCenter)
        self.path = QtWidgets.QPushButton("Path \u25b4")
        self.path.setCheckable(True)
        self.path.hide()
        self.path.toggled.connect(self._toggle)
        h.addWidget(self.path, 0, QtCore.Qt.AlignVCenter)
        self.steps_wrap = QtWidgets.QWidget()
        self.steps_wrap.setStyleSheet("background: transparent;")
        self.steps = QtWidgets.QGridLayout(self.steps_wrap)
        self.steps.setContentsMargins(40, 0, 0, 0)
        self.steps.setHorizontalSpacing(8)
        self.steps.setVerticalSpacing(1)
        self.steps_wrap.hide()
        v.addWidget(self.steps_wrap)
        v.addLayout(h)
        if follow:
            bus().candidate.connect(lambda c: self.show_context(("candidate", c)))
            bus().job.connect(lambda j: self.show_context(("job", j)))
        self.show_tab(self.tab)

    # --- what to show
    def show_tab(self, name: str):
        self.tab = name.replace("&&", "&")
        ctx = self.by_tab.get(self.tab)
        if not ctx and self.fallback:
            try:
                ctx = self.fallback(self.tab)
            except Exception:
                ctx = None
        if ctx:
            self.context = ctx
            self._load()
        else:
            self.context = None
            self.guide = {}
            self.head.setText("THE SCIENTIFIC STEWARD \u00b7 %s" % self.tab)
            self.say.setText(mentor.TAB_HINTS.get(self.tab, "I am here on every page."))
            self.act.hide()
            self.bar.hide()
            self.path.hide()
            self.steps_wrap.hide()

    def show_context(self, ctx: tuple):
        self.by_tab[self.tab] = ctx
        self.context = ctx
        self._load()

    def refresh(self):
        if self.context:
            self._load()

    def _load(self):
        kind, ident = self.context
        fn = mentor.candidate_guide if kind == "candidate" else mentor.job_guide
        self.say.setText("Reading\u2026")
        qtwork.run_async(fn, lambda g, c=self.context: self._show(c, g), self.root, ident)

    def _show(self, ctx: tuple, g: Dict[str, Any]):
        if ctx != self.context:
            return
        self.guide = g
        _clear(self.steps)
        if "error" in g:
            self.say.setText(g["error"])
            self.act.hide()
            return
        title = g.get("title") or ""
        self.head.setText("THE SCIENTIFIC STEWARD \u00b7 %s \u00b7 %s" % (
            title, "\u2713 complete" if g["complete"] else "%d of %d done" % (g["done"], g["total"])))
        self.say.setText("\u201c%s\u201d" % g["say"])
        self.bar.setRange(0, g["total"] or 1)
        self.bar.setValue(g["done"])
        self.bar.show()
        nxt = g.get("next") or {}
        if nxt.get("action") and nxt.get("state") == "todo":
            self.act.setText(nxt["action_label"].replace("&", "&&") + "  \u2192")
            self.act.show()
        else:
            self.act.hide()
        self.path.show()
        for i, s in enumerate(g["steps"]):
            ic, col = ICON.get(s["state"], ("\u25cb", MUTED))
            self.steps.addWidget(_lab(ic, colour=col, bold=True, wrap=False), i, 0)
            self.steps.addWidget(_lab(s["name"], colour=col if s["state"] != "waiting" else MUTED, wrap=False), i, 1)
            t = _lab(s["text"].split(". ")[0].rstrip(".") + ".", colour=MUTED if s["state"] in ("done", "waiting")
                     else None)
            t.setToolTip(s["text"])
            self.steps.addWidget(t, i, 2)
            if s.get("action") and s["state"] in ("todo", "advice"):
                b = QtWidgets.QPushButton((s.get("action_label") or "Go").replace("&", "&&"))
                b.clicked.connect(lambda _=False, a=s["action"]: self._go(a))
                self.steps.addWidget(b, i, 3)
        self.steps.setColumnStretch(2, 1)

    def _toggle(self, on: bool):
        self.steps_wrap.setVisible(on)
        self.path.setText("Path \u25be" if on else "Path \u25b4")

    def _go(self, action: str):
        if not self.context:
            return
        kind, ident = self.context
        if kind == "candidate":
            self.go(action, ident if action in ("final_image", "review_cand", "rerun_point")
                    else (self.guide.get("job_id") or None), cid=ident)
        else:
            self.go(action, ident)

    def _act(self):
        nxt = (self.guide or {}).get("next") or {}
        if nxt.get("action"):
            self._go(nxt["action"])
