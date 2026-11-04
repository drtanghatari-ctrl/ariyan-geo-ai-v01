"""
The Cloud window (win-u5): Google Drive set up, sign in, upload this project,
and download and receive a bundle -- separate from Send/Receive by folder or USB.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import webbrowser
from typing import Any, Dict, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ariyan_win import gdrive, qtwork

GOLD, ACCENT, TEAL, MUTED, ROSE = "#F2C14E", "#3FB68B", "#2FA6B8", "#8B9BB0", "#E0607E"

SETUP_STEPS = [
    "Open <a href='https://console.cloud.google.com/projectcreate'>console.cloud.google.com/projectcreate</a>, "
    "sign in with the Google account whose Drive you want, name the project <b>ARIYAN GEO AI</b> and press "
    "<b>Create</b>.",
    "Open <a href='https://console.cloud.google.com/apis/library/drive.googleapis.com'>Google Drive API</a> "
    "(check the new project is selected at the top) and press <b>Enable</b>.",
    "Open <a href='https://console.cloud.google.com/auth/branding'>Google Auth Platform \u2192 Branding</a>, press "
    "<b>Get started</b>: app name <b>ARIYAN GEO AI</b>, your e-mail as support and contact e-mail, audience "
    "<b>External</b>, agree, <b>Create</b>.",
    "Open <a href='https://console.cloud.google.com/auth/audience'>Audience</a>: press <b>Publish app</b> and "
    "confirm. (ARIYAN only asks for \u201cfiles it created\u201d, which needs no Google review; publishing stops "
    "the sign-in from expiring every 7 days.)",
    "Open <a href='https://console.cloud.google.com/auth/clients'>Clients</a> \u2192 <b>Create client</b>: type "
    "<b>Desktop app</b>, name <b>ARIYAN laptop</b>, <b>Create</b>. Copy the <b>Client ID</b> and the <b>Client "
    "secret</b> into the two boxes below and press <b>Save</b>.",
    "Press <b>Sign in with Google</b>. Your browser opens; choose your account. Google may say the app is "
    "unverified: press <b>Advanced \u2192 Go to ARIYAN GEO AI</b> (it is your own app), then <b>Continue</b>. "
    "When the page says ARIYAN is signed in, come back here.",
]


def _lab(t="", colour=None, bold=False, rich=False):
    w = QtWidgets.QLabel(t)
    w.setWordWrap(True)
    if rich:
        w.setTextFormat(QtCore.Qt.RichText)
        w.setOpenExternalLinks(True)
    css = []
    if colour:
        css.append("color:%s;" % colour)
    if bold:
        css.append("font-weight:700;")
    if css:
        w.setStyleSheet(" ".join(css))
    return w


def _panel(title: str, colour: str):
    f = QtWidgets.QFrame()
    f.setObjectName("panel")
    v = QtWidgets.QVBoxLayout(f)
    v.setContentsMargins(12, 10, 12, 10)
    h = QtWidgets.QLabel(title)
    h.setObjectName("h")
    h.setStyleSheet("color:%s;" % colour)
    v.addWidget(h)
    return f, v


class _Job:
    """A background task with a progress share the window can poll."""

    def __init__(self):
        self.done, self.total, self.text = 0, 0, ""

    def __call__(self, d, t):
        self.done, self.total = d, t


class CloudDialog(QtWidgets.QDialog):
    def __init__(self, main, allow_unprotected: bool = False):
        super().__init__(main)
        self.main, self.allow = main, allow_unprotected
        self.setWindowTitle("ARIYAN GEO AI \u2014 Google Drive")
        self.resize(980, 720)
        root = QtWidgets.QVBoxLayout(self)
        head = _lab("\u2601  ONLINE STORAGE \u00b7 GOOGLE DRIVE", GOLD, True)
        root.addWidget(head)
        root.addWidget(_lab("Separate from Send/Receive by folder or USB. ARIYAN can see only the files it put in "
                            "your Drive (folder \u201cARIYAN GEO AI\u201d), nothing else. Every upload and download "
                            "is checked by MD5, and Receive keeps a safety copy as always.", MUTED))
        body = QtWidgets.QHBoxLayout()
        root.addLayout(body, 1)
        # left: setup + sign in
        left = QtWidgets.QVBoxLayout()
        body.addLayout(left, 5)
        self.setup_box, sv = _panel("SET UP ONCE (about 10 minutes)", TEAL)
        self.steps = QtWidgets.QLabel()
        self.steps.setTextFormat(QtCore.Qt.RichText)
        self.steps.setOpenExternalLinks(True)
        self.steps.setWordWrap(True)
        self.steps.setText("<ol style='margin-left:-20px'>%s</ol>" % "".join(
            "<li style='margin-bottom:6px'>%s</li>" % x.replace("<a href", "<a style='color:#7CC4FF' href")
            for x in SETUP_STEPS))
        sc = QtWidgets.QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QtWidgets.QFrame.NoFrame)
        sc.setWidget(self.steps)
        sv.addWidget(sc, 1)
        form = QtWidgets.QFormLayout()
        self.cid = QtWidgets.QLineEdit()
        self.cid.setPlaceholderText("123456789-abc\u2026.apps.googleusercontent.com")
        self.sec = QtWidgets.QLineEdit()
        self.sec.setEchoMode(QtWidgets.QLineEdit.Password)
        self.sec.setPlaceholderText("GOCSPX-\u2026")
        form.addRow("Client ID", self.cid)
        form.addRow("Client secret", self.sec)
        sv.addLayout(form)
        save = QtWidgets.QPushButton("Save the client")
        save.clicked.connect(self._save_client)
        sv.addWidget(save)
        left.addWidget(self.setup_box, 1)
        self.acct_box, av = _panel("YOUR GOOGLE ACCOUNT", ACCENT)
        self.acct = _lab("", None, True)
        av.addWidget(self.acct)
        row = QtWidgets.QHBoxLayout()
        self.signin = QtWidgets.QPushButton("Sign in with Google")
        self.signin.setObjectName("primary")
        self.signin.clicked.connect(self._sign_in)
        self.signout = QtWidgets.QPushButton("Sign out")
        self.signout.clicked.connect(self._sign_out)
        row.addWidget(self.signin)
        row.addWidget(self.signout)
        row.addStretch(1)
        av.addLayout(row)
        left.addWidget(self.acct_box)
        # right: transfer
        right = QtWidgets.QVBoxLayout()
        body.addLayout(right, 6)
        up, uv = _panel("\u2191  UPLOAD THIS COMPUTER\u2019S PROJECT", GOLD)
        uv.addWidget(_lab("Makes the same bundle as \u201cSend to phone\u201d and puts it in Drive \u203a ARIYAN GEO AI. "
                          "Work on the other device from then on, until you send it back.", MUTED))
        self.up_btn = QtWidgets.QPushButton("Upload project to Google Drive")
        self.up_btn.setObjectName("primary")
        self.up_btn.clicked.connect(self._upload)
        uv.addWidget(self.up_btn)
        right.addWidget(up)
        dn, dv = _panel("\u2193  BUNDLES IN YOUR DRIVE (newest first)", TEAL)
        self.list = QtWidgets.QListWidget()
        self.list.setMinimumHeight(220)
        dv.addWidget(self.list, 1)
        r2 = QtWidgets.QHBoxLayout()
        self.dn_btn = QtWidgets.QPushButton("Download and receive")
        self.dn_btn.setObjectName("primary")
        self.dn_btn.clicked.connect(self._download)
        self.ref_btn = QtWidgets.QPushButton("Refresh list")
        self.ref_btn.clicked.connect(self._list)
        self.del_btn = QtWidgets.QPushButton("Delete from Drive")
        self.del_btn.clicked.connect(self._delete)
        for b in (self.dn_btn, self.ref_btn, self.del_btn):
            r2.addWidget(b)
        dv.addLayout(r2)
        dv.addWidget(_lab("Bundles from the phone appear here once the phone uploads with the same sign-in "
                          "(coming to the phone next). A bundle you saved to Drive from the phone\u2019s Drive app "
                          "is not visible to ARIYAN; use \u201cReceive from phone\u201d and pick it in your Drive "
                          "folder instead.", MUTED))
        right.addWidget(dn, 1)
        self.state = _lab("", MUTED)
        root.addWidget(self.state)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        root.addWidget(close, 0, QtCore.Qt.AlignRight)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._job: Optional[_Job] = None
        self._refresh()

    # --- state
    def _refresh(self):
        st = gdrive.status(self.allow)
        self.setup_box.setVisible(not st["client"] or not st["signed_in"])
        if st["signed_in"]:
            self.acct.setText("\u2713 Signed in as %s" % (st["account"] or "your Google account"))
            self.acct.setStyleSheet("color:%s; font-weight:700;" % ACCENT)
        elif st["client"]:
            self.acct.setText("Client saved. Not signed in yet.")
            self.acct.setStyleSheet("color:%s; font-weight:700;" % GOLD)
        else:
            self.acct.setText("Not set up yet: follow the steps above.")
            self.acct.setStyleSheet("color:%s; font-weight:700;" % MUTED)
        self.signin.setEnabled(st["client"] and not st["signed_in"])
        self.signout.setEnabled(st["signed_in"])
        for b in (self.up_btn, self.dn_btn, self.ref_btn, self.del_btn):
            b.setEnabled(st["signed_in"])
        if st["signed_in"]:
            self._list()

    def _say(self, t: str, colour: str = MUTED):
        self.state.setText(t)
        self.state.setStyleSheet("color:%s;" % colour)

    def _tick(self):
        j = self._job
        if j and j.total:
            self._say("%s %.0f of %.0f MB (%d%%)" % (j.text, j.done / 1e6, j.total / 1e6, 100 * j.done // j.total))

    def _busy(self, on: bool):
        for b in (self.up_btn, self.dn_btn, self.ref_btn, self.del_btn, self.signin, self.signout):
            b.setEnabled(not on and b is not self.signin)
        if on:
            self._timer.start(400)
        else:
            self._timer.stop()
            self._job = None

    @staticmethod
    def _wrap(fn):
        def run(*a):
            try:
                return fn(*a)
            except gdrive.DriveError as e:
                return {"error": str(e)}
            except Exception as e:                     # shown, never hidden
                return {"error": "%s: %s" % (type(e).__name__, e)}
        return run

    # --- setup and sign-in
    def _save_client(self):
        try:
            gdrive.save_client(self.cid.text(), self.sec.text(), self.allow)
        except (gdrive.DriveError, OSError) as e:
            QtWidgets.QMessageBox.warning(self, "Not saved", str(e))
            return
        self.cid.clear()
        self.sec.clear()
        self._say("Client saved (encrypted for this Windows account). Now press \u201cSign in with Google\u201d.",
                  ACCENT)
        self._refresh()

    def _sign_in(self):
        self._say("Your browser is open on Google\u2019s sign-in page. Choose your account and allow access; this "
                  "window waits up to 5 minutes.", GOLD)
        self._busy(True)
        qtwork.run_async(self._wrap(lambda: gdrive.sign_in(webbrowser.open, self.allow)), self._signed)

    def _signed(self, r: Dict[str, Any]):
        self._busy(False)
        if "error" in r:
            self._say(r["error"], ROSE)
        else:
            self._say("Signed in as %s." % (r.get("account") or "your account"), ACCENT)
        self._refresh()

    def _sign_out(self):
        if QtWidgets.QMessageBox.question(self, "Sign out", "Sign ARIYAN out of Google Drive on this computer? "
                                          "Your files in Drive stay where they are.") != QtWidgets.QMessageBox.Yes:
            return
        r = self._wrap(lambda: gdrive.sign_out(self.allow))()
        self._say("Signed out%s." % ("" if r.get("revoked") else " (Google could not be reached to cancel the "
                                     "access; you can also remove it at myaccount.google.com \u2192 Security)"))
        self.list.clear()
        self._refresh()

    # --- list
    def _list(self):
        self.list.clear()
        self._say("Reading your Drive folder\u2026")
        qtwork.run_async(self._wrap(lambda: {"rows": gdrive.Drive(self.allow).bundles()}), self._listed)

    def _listed(self, r):
        self.list.clear()
        if "error" in r:
            self._say(r["error"], ROSE)
            self._refresh_buttons_after_error(r["error"])
            return
        rows = r["rows"]
        for b in rows:
            it = QtWidgets.QListWidgetItem("%s\n      %s \u00b7 %.1f MB%s" % (
                b["name"], (b["created"] or "")[:16].replace("T", " ") + " UTC", b["bytes"] / 1e6,
                (" \u00b7 from the %s" % b["from_device"]) if b.get("from_device") else ""))
            it.setData(QtCore.Qt.UserRole, b)
            self.list.addItem(it)
        if rows:
            self.list.setCurrentRow(0)
        self._say("%d bundle%s in Drive \u203a ARIYAN GEO AI." % (len(rows), "" if len(rows) == 1 else "s"))

    def _refresh_buttons_after_error(self, err: str):
        if "sign in again" in err.lower():
            self._refresh()

    # --- upload
    def _upload(self):
        import json as _j
        import project_bundle as pb
        root = self.main.root
        tmp = tempfile.mkdtemp(prefix="ariyan_up_")
        job = _Job()
        job.text = "Uploading\u2026"
        self._job = job

        def work():
            try:
                b = _j.loads(pb.make_bundle_json(root, tmp, "laptop"))
                if "error" in b:
                    return b
                path = b.get("path") or os.path.join(tmp, b["name"])
                props = {"from_device": "laptop"}
                try:
                    props["candidates"] = str(int(((b.get("manifest") or {}).get("project") or {}).get(
                        "candidates", 0)))
                except Exception:
                    pass
                up = gdrive.Drive(self.allow).upload(path, props, job)
                up["bundle_bytes"] = b.get("bytes")
                return up
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        self._say("Preparing the project bundle\u2026")
        self._busy(True)
        qtwork.run_async(self._wrap(work), self._uploaded)

    def _uploaded(self, r):
        self._busy(False)
        self._refresh()
        if "error" in r:
            self._say(r["error"], ROSE)
            QtWidgets.QMessageBox.warning(self, "Not uploaded", r["error"])
            return
        self._say("Uploaded %s (%.1f MB), checked by MD5." % (r["name"], r["bytes"] / 1e6), ACCENT)
        QtWidgets.QMessageBox.information(self, "In your Drive",
                                          "%s (%.1f MB) is in Google Drive \u203a ARIYAN GEO AI, checked by MD5.\n\n"
                                          "Work on the other device from now on, until you send it back."
                                          % (r["name"], r["bytes"] / 1e6))

    # --- download
    def _download(self):
        it = self.list.currentItem()
        if not it:
            self._say("Choose a bundle in the list first.", GOLD)
            return
        b = it.data(QtCore.Qt.UserRole)
        tmp = tempfile.mkdtemp(prefix="ariyan_dn_")
        job = _Job()
        job.text = "Downloading\u2026"
        self._job = job
        self._tmp = tmp
        self._say("Downloading %s\u2026" % b["name"])
        self._busy(True)
        qtwork.run_async(self._wrap(lambda: {"path": gdrive.Drive(self.allow).download(b["id"], tmp, b.get("md5"),
                                                                                         job)}), self._downloaded)

    def _downloaded(self, r):
        self._busy(False)
        self._refresh()
        if "error" in r:
            shutil.rmtree(getattr(self, "_tmp", ""), ignore_errors=True)
            self._say(r["error"], ROSE)
            QtWidgets.QMessageBox.warning(self, "Not downloaded", r["error"])
            return
        self._say("Downloaded and checked by MD5. Now the usual Receive checks\u2026", ACCENT)
        try:
            ok = self.main.receive_path(r["path"], "Google Drive")
        finally:
            shutil.rmtree(getattr(self, "_tmp", ""), ignore_errors=True)
        self._say("Received from Google Drive." if ok else "Nothing was changed on this computer.",
                  ACCENT if ok else MUTED)

    def _delete(self):
        it = self.list.currentItem()
        if not it:
            return
        b = it.data(QtCore.Qt.UserRole)
        if QtWidgets.QMessageBox.question(self, "Delete from Drive", "Move %s to your Drive's bin?\n\nThe project on "
                                          "this computer does not change." % b["name"]) != QtWidgets.QMessageBox.Yes:
            return
        r = self._wrap(lambda: (gdrive.Drive(self.allow).delete(b["id"]), {})[1])()
        if "error" in r:
            self._say(r["error"], ROSE)
        self._list()
