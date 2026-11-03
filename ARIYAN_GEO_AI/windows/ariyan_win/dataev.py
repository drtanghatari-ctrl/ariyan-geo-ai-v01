"""Data & Evidence tab (win-w4a): what this computer holds, and fetching the
terrain of the whole study area (one public Copernicus tile per 1-degree cell
covered by your wide-area jobs; no key). Field data (GPR/ERT) is imported from a
candidate's Final Image (Evidence Volume / Profile tabs), as on the phone."""
from __future__ import annotations

import json
import os

from PySide6 import QtCore, QtGui, QtWidgets

from ariyan_win import keys, qtwork

MUTED, ACCENT, ORANGE = "#8B9BB0", "#3FB68B", "#D9822B"


class DataEvidence(QtWidgets.QWidget):
    def __init__(self, root: str, parent=None):
        super().__init__(parent)
        self.root = root
        v = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        self.summary = QtWidgets.QLabel("Reading\u2026")
        self.summary.setWordWrap(True)
        top.addWidget(self.summary, 1)
        rb = QtWidgets.QPushButton("Refresh")
        rb.clicked.connect(self.load)
        top.addWidget(rb)
        v.addLayout(top)
        g = QtWidgets.QGroupBox("TERRAIN TILES FOR YOUR STUDY AREA (Copernicus GLO-30, public, no key, about 25\u201360 MB each)")
        gl = QtWidgets.QVBoxLayout(g)
        self.tiles = QtWidgets.QListWidget()
        gl.addWidget(self.tiles, 1)
        row = QtWidgets.QHBoxLayout()
        self.dl = QtWidgets.QPushButton("Download the missing tiles")
        self.dl.clicked.connect(self._download_missing)
        row.addWidget(self.dl)
        self.progress = QtWidgets.QLabel("")
        row.addWidget(self.progress, 1)
        gl.addLayout(row)
        v.addWidget(g, 2)
        f = QtWidgets.QGroupBox("FIELD DATA (GPR / ERT) IN THIS PROJECT")
        fl = QtWidgets.QVBoxLayout(f)
        self.field = QtWidgets.QListWidget()
        fl.addWidget(self.field, 1)
        fl.addWidget(QtWidgets.QLabel("Import a survey from the candidate's Final Image: Evidence Volume \u2192 Import GPR, "
                                      "or Profile & Section \u2192 Import ERT on this line."))
        v.addWidget(f, 1)
        b = QtWidgets.QHBoxLayout()
        for name, sub in (("Open the data folder", ""), ("Open the exports folder", "exports"),
                          ("Open the field-data inbox", os.path.join("field_data", "inbox"))):
            bt = QtWidgets.QPushButton(name)
            bt.clicked.connect(lambda _=False, s=sub: self._open(s))
            b.addWidget(bt)
        b.addStretch(1)
        v.addLayout(b)
        self.load()

    def _open(self, sub: str):
        p = os.path.join(self.root, sub) if sub else self.root
        os.makedirs(p, exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(p))

    def load(self):
        import terrain_tile
        qtwork.run_async(lambda: json.loads(terrain_tile.study_area_tiles_json(self.root)), self._show_tiles)
        qtwork.run_async(self._field_rows, self._show_field)

    def _field_rows(self):
        import grand_project_db as db
        conn = db.get_connection(self.root)
        try:
            db.initialize_schema(conn)
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='field_dataset'").fetchone():
                return []
            return [dict(r) for r in conn.execute("SELECT id, candidate_id, method, label, source_filename, created_at "
                                                  "FROM field_dataset ORDER BY created_at DESC")]
        finally:
            conn.close()

    def _show_field(self, rows):
        self.field.clear()
        if isinstance(rows, dict):
            self.field.addItem(rows.get("error", "?"))
            return
        for r in rows:
            self.field.addItem("%s \u00b7 %s \u00b7 candidate %s \u00b7 %s \u00b7 %s" % (
                r["method"], r["label"], r["candidate_id"][:8], r["source_filename"], r["created_at"][:10]))
        if not rows:
            self.field.addItem("No GPR or ERT survey imported yet.")

    def _show_tiles(self, o):
        self.tiles.clear()
        st = keys.status()
        if "error" in o:
            self.summary.setText(o["error"])
            return
        self._missing = [t for t in o["tiles"] if t["covered"] and not t["present"]]
        n = len(o["tiles"])
        self.summary.setText("%d wide-area job(s) cover %d terrain tile(s); %d on this computer, %d missing. "
                             "Keys: OpenTopography %s, Copernicus %s (Settings)." % (
                                 o["jobs"], n, n - o["missing"], o["missing"],
                                 "set" if st["opentopography"] else "not set", "set" if st["copernicus"] else "not set"))
        for t in o["tiles"]:
            it = QtWidgets.QListWidgetItem("%s \u00b7 %s \u00b7 jobs: %s" % (
                t["tile"] or "%d,%d" % (t["lat"], t["lon"]),
                "on this computer" if t["present"] else ("missing" if t["covered"] else "outside the country package"),
                ", ".join(t["jobs"][:4]) + ("\u2026" if len(t["jobs"]) > 4 else "")))
            it.setForeground(QtGui.QColor(ACCENT if t["present"] else ORANGE))
            self.tiles.addItem(it)
        self.dl.setEnabled(bool(self._missing))

    def _download_missing(self):
        todo = list(getattr(self, "_missing", []))
        if not todo:
            return
        if QtWidgets.QMessageBox.question(self, "Download terrain", "Download %d tile(s) (about %d\u2013%d MB in total)?"
                                          % (len(todo), 25 * len(todo), 60 * len(todo))) != QtWidgets.QMessageBox.Yes:
            return
        self.dl.setEnabled(False)
        self._done = {"ok": 0, "fail": []}
        self._next(todo, len(todo))

    def _next(self, todo, total):
        import terrain_tile
        if not todo:
            self.progress.setText("Done: %d downloaded%s." % (self._done["ok"], (", not available: " +
                                  ", ".join(self._done["fail"])) if self._done["fail"] else ""))
            self.load()
            return
        t = todo[0]
        self.progress.setText("Downloading %s (%d of %d)\u2026" % (t["tile"], total - len(todo) + 1, total))

        def done(r, rest=todo[1:]):
            if isinstance(r, dict) and r.get("status") in ("downloaded", "already_present"):
                self._done["ok"] += 1
            else:
                self._done["fail"].append("%s (%s)" % (t["tile"], (r or {}).get("status") or (r or {}).get("error")))
            self._next(rest, total)
        qtwork.run_async(terrain_tile.ensure_tile, done, self.root, t["lat"] + 0.5, t["lon"] + 0.5)
