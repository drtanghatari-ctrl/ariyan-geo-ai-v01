"""Settings window (win-w4a): API keys (DPAPI-protected, never shown), data folder,
database safety and backups (the phone's rules: 3 newest + the largest protected;
only automatic backups can be deleted, each deletion on the timeline)."""
from __future__ import annotations

import json
import os

from PySide6 import QtCore, QtGui, QtWidgets

from ariyan_win import keys, qtwork

MUTED, ACCENT, ORANGE, ROSE = "#8B9BB0", "#3FB68B", "#D9822B", "#E0607E"


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, root: str, parent=None):
        super().__init__(parent)
        self.root = root
        self.setWindowTitle("Settings \u2014 ARIYAN GEO AI")
        self.resize(760, 680)
        v = QtWidgets.QVBoxLayout(self)
        box = QtWidgets.QGroupBox("API keys on this computer (encrypted for your Windows account)")
        f = QtWidgets.QFormLayout(box)
        st = keys.status()
        self.ot = QtWidgets.QLineEdit()
        self.cid = QtWidgets.QLineEdit()
        self.sec = QtWidgets.QLineEdit()
        for e in (self.ot, self.cid, self.sec):
            e.setEchoMode(QtWidgets.QLineEdit.Password)
        self.ot.setPlaceholderText("set \u2014 leave empty to keep it" if st["opentopography"] else "not set")
        cp = "set \u2014 leave empty to keep it" if st["copernicus"] else "not set"
        self.cid.setPlaceholderText(cp)
        self.sec.setPlaceholderText(cp)
        f.addRow("OpenTopography API key", self.ot)
        f.addRow("Copernicus client ID", self.cid)
        f.addRow("Copernicus client secret", self.sec)
        self.key_state = QtWidgets.QLabel(self._state_text(st))
        self.key_state.setWordWrap(True)
        f.addRow(self.key_state)
        row = QtWidgets.QHBoxLayout()
        save = QtWidgets.QPushButton("Save keys")
        save.clicked.connect(self._save)
        clear = QtWidgets.QPushButton("Remove all keys")
        clear.clicked.connect(self._clear)
        row.addWidget(save)
        row.addWidget(clear)
        row.addStretch(1)
        f.addRow(row)
        if not keys.protected():
            f.addRow(QtWidgets.QLabel("Keys can only be saved on Windows (DPAPI)."))
        v.addWidget(box)
        self.info = QtWidgets.QTextBrowser()
        v.addWidget(self.info, 1)
        self.backups = QtWidgets.QListWidget()
        self.backups.setMaximumHeight(170)
        v.addWidget(QtWidgets.QLabel("Daily backups \u2014 select a \u201csafe to delete\u201d one to delete it:"))
        v.addWidget(self.backups)
        b = QtWidgets.QHBoxLayout()
        dl = QtWidgets.QPushButton("Delete the selected backup")
        dl.clicked.connect(self._delete_backup)
        op = QtWidgets.QPushButton("Open the data folder")
        op.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.root)))
        cl = QtWidgets.QPushButton("Close")
        cl.clicked.connect(self.accept)
        for w in (dl, op):
            b.addWidget(w)
        b.addStretch(1)
        b.addWidget(cl)
        v.addLayout(b)
        self._load()

    @staticmethod
    def _state_text(st):
        return ("OpenTopography: %s \u00b7 Copernicus: %s. Values are never shown, logged or sent in a project bundle."
                % ("set" if st["opentopography"] else "not set", "set" if st["copernicus"] else "not set"))

    def _save(self):
        vals = {}
        if self.ot.text().strip():
            vals["OPENTOPOGRAPHY_API_KEY"] = self.ot.text()
        if self.cid.text().strip() or self.sec.text().strip():
            if not (self.cid.text().strip() and self.sec.text().strip()):
                QtWidgets.QMessageBox.warning(self, "Copernicus", "Enter both the client ID and the client secret.")
                return
            vals["COPERNICUS_CLIENT_ID"], vals["COPERNICUS_CLIENT_SECRET"] = self.cid.text(), self.sec.text()
        if not vals:
            return
        try:
            keys.save(vals)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Not saved", str(e))
            return
        for e in (self.ot, self.cid, self.sec):
            e.clear()
        self.key_state.setText(self._state_text(keys.status()))

    def _clear(self):
        if QtWidgets.QMessageBox.question(self, "Remove keys", "Remove all API keys from this computer?") != \
                QtWidgets.QMessageBox.Yes:
            return
        try:
            keys.save({n: "" for n in keys.NAMES})
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Not removed", str(e))
        self.key_state.setText(self._state_text(keys.status()))

    def _load(self):
        import mission_control as mc
        qtwork.run_async(lambda: json.loads(mc.settings_json(self.root)), self._show)

    def _show(self, o):
        if "error" in o:
            self.info.setPlainText(o["error"])
            return
        d, g, b, c = o.get("database") or {}, o.get("guard") or {}, o.get("backups") or {}, o.get("crash_reports") or {}
        lines = ["<b>Data folder</b>: %s" % o.get("root"),
                 "<b>grand_project.db</b>: %s" % ("%.0f MB" % (d.get("bytes", 0) / 1e6) if d.get("exists") else "missing"),
                 "<b>Size guard</b>: %s" % ("last seen %.0f MB, %s UTC" % (g.get("last_seen_size", 0) / 1e6,
                                                                         str(g.get("last_seen_at", ""))[:16].replace("T", " "))
                                             if g else "no guard file yet"),
                 "<b>ALLOW_NEW_GRAND_PROJECT_DB</b>: %s" % ("PRESENT \u2014 remove it unless you meant it"
                                                            if o.get("allow_new_flag") else "absent (normal)"),
                 "<b>Backups</b>: %s" % b.get("delete_rule", ""),
                 "<b>Crash reports</b>: %s" % (c.get("count") or "none")]
        for fo in o.get("folders", []):
            lines.append("<b>%s</b>: %s files, %.0f MB" % (fo["name"], "{:,}".format(fo["files"]), fo["bytes"] / 1e6))
        self.info.setHtml("<br>".join(lines))
        self.backups.clear()
        for f in b.get("files", []):
            it = QtWidgets.QListWidgetItem("%s \u00b7 %.0f MB \u00b7 %s" % (
                f["name"], f["bytes"] / 1e6, "safe to delete" if f.get("deletable") else "protected: " + str(f.get("protected_reason"))))
            it.setData(QtCore.Qt.UserRole, f["name"] if f.get("deletable") else None)
            it.setForeground(QtGui.QColor(ORANGE if f.get("deletable") else ACCENT))
            self.backups.addItem(it)

    def _delete_backup(self):
        it = self.backups.currentItem()
        name = it.data(QtCore.Qt.UserRole) if it else None
        if not name:
            QtWidgets.QMessageBox.information(self, "Protected", "Choose a backup marked \u201csafe to delete\u201d.")
            return
        if QtWidgets.QMessageBox.question(self, "Delete backup", "Delete %s? This cannot be undone. The 3 newest "
                                          "backups, the largest one and grand_project.db stay untouched." % name) != \
                QtWidgets.QMessageBox.Yes:
            return
        import mission_control as mc
        r = json.loads(mc.delete_backup_json(self.root, name))
        if "error" in r:
            QtWidgets.QMessageBox.warning(self, "Not deleted", r["error"])
        self._load()
