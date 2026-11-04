"""u5 (gd-v1): Google Drive sign-in (PKCE, loopback), folder, chunked resumable upload with
MD5 check, list, download with MD5 check, and trash -- against a stand-in Google server."""
import hashlib
import json
import os
import sys
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from ariyan_win import gdrive, keys  # noqa: E402

FILES = {}
BLOBS = {}
SESS = {}
STATE = {"corrupt": False, "n": 0}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj=None, headers=None, raw=None):
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        body = raw if raw is not None else (json.dumps(obj).encode() if obj is not None else b"")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        b = self._body()
        if u.path == "/token":
            f = urllib.parse.parse_qs(b.decode())
            if f["grant_type"][0] == "authorization_code":
                assert f["code"][0] == "CODE1" and len(f["code_verifier"][0]) >= 43
                return self._send(200, {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600})
            assert f["refresh_token"][0] == "RT"
            return self._send(200, {"access_token": "AT2", "expires_in": 3600})
        if u.path == "/revoke":
            return self._send(200, {})
        if u.path == "/drive/v3/files":
            m = json.loads(b)
            STATE["n"] += 1
            fid = "F%d" % STATE["n"]
            FILES[fid] = dict(m, id=fid)
            return self._send(200, {"id": fid})
        if u.path == "/upload/drive/v3/files":
            m = json.loads(b)
            STATE["n"] += 1
            sid = "S%d" % STATE["n"]
            SESS[sid] = {"meta": m, "data": b"", "size": int(self.headers["X-Upload-Content-Length"])}
            return self._send(200, {}, {"Location": "http://127.0.0.1:%d/session/%s" % (PORT, sid)})
        self._send(404, {"error": {"message": "no " + u.path}})

    def do_PUT(self):
        sid = self.path.rsplit("/", 1)[1]
        s = SESS[sid]
        s["data"] += self._body()
        if len(s["data"]) < s["size"]:
            return self._send(308, None, {"Range": "bytes=0-%d" % (len(s["data"]) - 1)})
        STATE["n"] += 1
        fid = "F%d" % STATE["n"]
        FILES[fid] = dict(s["meta"], id=fid, size=str(s["size"]), md5Checksum=hashlib.md5(s["data"]).hexdigest(),
                          createdTime="2026-11-04T09:00:00Z")
        BLOBS[fid] = s["data"]
        self._send(200, {"id": fid})

    def do_PATCH(self):
        fid = urllib.parse.urlparse(self.path).path.rsplit("/", 1)[1]
        FILES[fid]["trashed"] = json.loads(self._body()).get("trashed")
        self._send(200, {"id": fid})

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        assert self.headers["Authorization"].startswith("Bearer ")
        if u.path == "/drive/v3/about":
            return self._send(200, {"user": {"emailAddress": "dr.test@gmail.com"}})
        if u.path == "/drive/v3/files":
            qq = q["q"][0]
            live = [f for f in FILES.values() if not f.get("trashed")]
            if "mimeType=" in qq:
                return self._send(200, {"files": [f for f in live if f.get("mimeType") == gdrive.FOLDER_MIME]})
            parent = qq.split("'")[1]
            return self._send(200, {"files": [f for f in live if parent in (f.get("parents") or [])]})
        fid = u.path.rsplit("/", 1)[1]
        if q.get("alt") == ["media"]:
            data = BLOBS[fid]
            return self._send(200, raw=(data[:-1] + b"X") if STATE["corrupt"] else data)
        return self._send(200, FILES[fid])


@pytest.fixture()
def fake(monkeypatch, tmp_path):
    global PORT
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    PORT = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % PORT
    for k, v in (("AUTH_URL", base + "/auth"), ("TOKEN_URL", base + "/token"), ("REVOKE_URL", base + "/revoke"),
                 ("API", base + "/drive/v3"), ("UPLOAD", base + "/upload/drive/v3/files"), ("CHUNK", 256 * 1024)):
        monkeypatch.setattr(gdrive, k, v)
    monkeypatch.setattr(keys, "_path", lambda: str(tmp_path / "keys.dat"))
    FILES.clear(), BLOBS.clear(), SESS.clear()
    STATE.update(corrupt=False, n=0)
    yield base
    srv.shutdown()


def _browser(url):
    """Stands in for the user approving in the browser: Google redirects to ARIYAN's page."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["scope"] == [gdrive.SCOPE] and q["code_challenge_method"] == ["S256"]
    back = q["redirect_uri"][0] + "?" + urllib.parse.urlencode({"code": "CODE1", "state": q["state"][0]})
    threading.Thread(target=lambda: urllib.request.urlopen(back, timeout=10).read(), daemon=True).start()


def test_whole_drive_round_trip(fake, tmp_path):
    with pytest.raises(gdrive.DriveError):
        gdrive.save_client("not-a-client-id", "x", True)
    gdrive.save_client("123-abc.apps.googleusercontent.com", "GOCSPX-s", True)
    r = gdrive.sign_in(_browser, True, timeout_s=20)
    assert r["account"] == "dr.test@gmail.com" and gdrive.status(True)["signed_in"]
    assert "RT" not in json.dumps(gdrive.status(True))                  # the token is never shown
    d = gdrive.Drive(True)
    src = tmp_path / "ariyan_project_laptop.ariyan"
    src.write_bytes(os.urandom(700 * 1024))                              # three chunks of 256 KiB
    seen = []
    up = d.upload(str(src), {"from_device": "laptop"}, lambda a, b: seen.append(a))
    assert up["md5"] == hashlib.md5(src.read_bytes()).hexdigest() and seen[-1] == 700 * 1024 and len(seen) == 3
    rows = d.bundles()
    assert [x["name"] for x in rows] == [src.name] and rows[0]["from_device"] == "laptop"
    assert d.folder() == d.folder()                                       # one folder, found again
    out = d.download(rows[0]["id"], str(tmp_path / "dl"), rows[0]["md5"])
    assert open(out, "rb").read() == src.read_bytes()
    STATE["corrupt"] = True
    with pytest.raises(gdrive.DriveError, match="checksum"):
        d.download(rows[0]["id"], str(tmp_path / "dl2"), rows[0]["md5"])
    assert not os.listdir(tmp_path / "dl2")                               # the bad copy is discarded
    d.delete(rows[0]["id"])
    assert d.bundles() == []
    gdrive.sign_out(True)
    assert not gdrive.status(True)["signed_in"]


def test_wrong_state_is_refused(fake):
    gdrive.save_client("123-abc.apps.googleusercontent.com", "GOCSPX-s", True)

    def evil(url):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        back = q["redirect_uri"][0] + "?code=CODE1&state=forged"
        threading.Thread(target=lambda: urllib.request.urlopen(back, timeout=10).read(), daemon=True).start()
    with pytest.raises(gdrive.DriveError, match="did not match"):
        gdrive.sign_in(evil, True, timeout_s=20)
    assert not gdrive.status(True)["signed_in"]


def test_cloud_window_builds(fake):
    from PySide6 import QtWidgets
    from ariyan_win.cloud import CloudDialog
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])

    class Main(QtWidgets.QWidget):
        root = "/nowhere"
    d = CloudDialog(Main(), allow_unprotected=True)
    assert d.setup_box.isVisibleTo(d) and not d.up_btn.isEnabled()
    assert "Desktop app" in d.steps.text()
    d.close()


def test_cloud_window_upload_then_download_hands_to_receive(fake, tmp_path, monkeypatch):
    from PySide6 import QtWidgets
    from ariyan_win import core_path, qtwork
    core_path.install()
    import grand_project_db as db
    from ariyan_win import cloud
    root = str(tmp_path / "proj")
    os.makedirs(root)
    db.create_grand_project(root, "Default Grand Project", project_id="default")
    gdrive.save_client("123-abc.apps.googleusercontent.com", "GOCSPX-s", True)
    gdrive.sign_in(_browser, True, timeout_s=20)
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    got = []

    class Main(QtWidgets.QWidget):
        pass
    m = Main()
    m.root = root
    m.receive_path = lambda p, where: (got.append((open(p, "rb").read()[:2], where)), True)[1]
    d = cloud.CloudDialog(m, allow_unprotected=True)

    def pump():
        for _ in range(4):
            qtwork.wait_all(30000)
            qa.processEvents()
    pump()
    assert d.up_btn.isEnabled() and not d.setup_box.isVisibleTo(d)
    d._upload()
    pump()
    assert d.list.count() == 1 and "Uploaded" in d.state.text() or "bundle" in d.state.text()
    d.list.setCurrentRow(0)
    d._download()
    pump()
    assert got and got[0][1] == "Google Drive" and got[0][0] == b"PK"
    d.close()
