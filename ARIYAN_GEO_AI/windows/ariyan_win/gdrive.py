"""
Google Drive inside ARIYAN (gd-v1, win-u5, 2026-11-04).

Sign-in: your own Google Cloud OAuth client of type "Desktop app" (client ID and
secret pasted once in the Cloud window), the standard installed-app flow with a
one-time page on 127.0.0.1 and PKCE (S256). Scope: drive.file only -- ARIYAN
sees and changes only the files ARIYAN itself put in your Drive, nothing else.
The refresh token is kept encrypted with Windows DPAPI (keys.py), never shown,
logged or bundled.

Storage: one folder "ARIYAN GEO AI" in My Drive, made by ARIYAN. Upload sends a
project bundle (the same .ariyan file as "Send to phone") with a resumable
upload, then compares Drive's MD5 with the file's own; a mismatch is reported
and the copy on Drive is deleted. Download streams a bundle to a temporary
file, checks the MD5 again, and only then hands it to the normal Receive, with
its own checks and safety copy. Plain urllib: no Google library is needed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, List, Optional

VERSION = "gd-v1"
SCOPE = "https://www.googleapis.com/auth/drive.file"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_NAME = "ARIYAN GEO AI"
FOLDER_MIME = "application/vnd.google-apps.folder"
CHUNK = 8 * 1024 * 1024                       # resumable upload chunk (multiple of 256 KiB)
SIGNIN_TIMEOUT_S = 300


class DriveError(Exception):
    pass


# ---------------------------------------------------------------- keys
def _keys(allow_unprotected: bool = False) -> Dict[str, str]:
    from ariyan_win import keys
    return keys.load(allow_unprotected)


def _save(values: Dict[str, str], allow_unprotected: bool = False):
    from ariyan_win import keys
    keys.save(values, allow_unprotected)


def status(allow_unprotected: bool = False) -> Dict[str, Any]:
    k = _keys(allow_unprotected)
    return {"client": bool(k.get("GOOGLE_CLIENT_ID") and k.get("GOOGLE_CLIENT_SECRET")),
            "signed_in": bool(k.get("GOOGLE_REFRESH_TOKEN")), "account": k.get("GOOGLE_ACCOUNT", "")}


def save_client(client_id: str, client_secret: str, allow_unprotected: bool = False):
    cid, sec = (client_id or "").strip(), (client_secret or "").strip()
    if not cid.endswith(".apps.googleusercontent.com"):
        raise DriveError("That does not look like a Google OAuth client ID (it ends with "
                         ".apps.googleusercontent.com).")
    if not sec:
        raise DriveError("The client secret is empty.")
    _save({"GOOGLE_CLIENT_ID": cid, "GOOGLE_CLIENT_SECRET": sec, "GOOGLE_REFRESH_TOKEN": "", "GOOGLE_ACCOUNT": ""},
          allow_unprotected)


# ---------------------------------------------------------------- http
def _req(method: str, url: str, data: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None,
         timeout: float = 60.0):
    r = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        return urllib.request.urlopen(r, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
            j = json.loads(body)
            err = j.get("error")
            if isinstance(err, dict):
                body = err.get("message") or body
            else:
                body = j.get("error_description") or err or body
        except Exception:
            pass
        raise DriveError("Google answered %d: %s" % (e.code, str(body)[:300]))
    except urllib.error.URLError as e:
        raise DriveError("No connection to Google: %s" % e.reason)


def _json(method: str, url: str, data: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None):
    with _req(method, url, data, headers) as r:
        raw = r.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def _form(d: Dict[str, str]) -> bytes:
    return urllib.parse.urlencode(d).encode("ascii")


# ---------------------------------------------------------------- sign-in
class _Catch(BaseHTTPRequestHandler):
    result: Dict[str, str] = {}

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" not in q and "error" not in q:
            self.send_response(404)
            self.end_headers()
            return
        type(self).result = {k: v[0] for k, v in q.items()}
        ok = "code" in q
        page = ("<html><body style='font-family:sans-serif;background:#0B1220;color:#E6EDF3;padding:40px'>"
                "<h2 style='color:%s'>%s</h2><p>You can close this tab and return to ARIYAN GEO AI.</p>"
                "</body></html>" % ("#3FB68B" if ok else "#E0607E",
                                    "ARIYAN GEO AI is signed in to Google Drive." if ok else
                                    "Sign-in was not completed: %s" % q.get("error", ["?"])[0]))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def log_message(self, *a):
        pass


def sign_in(open_browser: Callable[[str], Any], allow_unprotected: bool = False,
            timeout_s: float = SIGNIN_TIMEOUT_S) -> Dict[str, Any]:
    """Opens Google's sign-in page in the browser and waits for the answer on 127.0.0.1."""
    k = _keys(allow_unprotected)
    cid, sec = k.get("GOOGLE_CLIENT_ID"), k.get("GOOGLE_CLIENT_SECRET")
    if not (cid and sec):
        raise DriveError("Paste your Google OAuth client ID and secret first (step 1 of the setup).")
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    srv = HTTPServer(("127.0.0.1", 0), _Catch)
    srv.timeout = 1.0
    port = srv.server_address[1]
    redirect = "http://127.0.0.1:%d/" % port
    _Catch.result = {}
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        "access_type": "offline", "prompt": "consent"})
    try:
        open_browser(url)
        t0 = time.time()
        while not _Catch.result and time.time() - t0 < timeout_s:
            srv.handle_request()
    finally:
        srv.server_close()
    res = _Catch.result
    if not res:
        raise DriveError("No answer from the browser within %d minutes; nothing was saved." % (timeout_s // 60))
    if res.get("state") != state:
        raise DriveError("The sign-in answer did not match this request; nothing was saved.")
    if "error" in res:
        raise DriveError("Google sign-in was not completed: %s" % res["error"])
    tok = _json("POST", TOKEN_URL, _form({"client_id": cid, "client_secret": sec, "code": res["code"],
                                          "code_verifier": verifier, "grant_type": "authorization_code",
                                          "redirect_uri": redirect}),
                {"Content-Type": "application/x-www-form-urlencoded"})
    if not tok.get("refresh_token"):
        raise DriveError("Google gave no lasting sign-in (refresh token). Remove ARIYAN's access at "
                         "myaccount.google.com \u2192 Security \u2192 Third-party access, then sign in again.")
    about = _json("GET", API + "/about?fields=user(emailAddress,displayName)",
                  headers={"Authorization": "Bearer " + tok["access_token"]})
    email = (about.get("user") or {}).get("emailAddress", "")
    _save({"GOOGLE_REFRESH_TOKEN": tok["refresh_token"], "GOOGLE_ACCOUNT": email}, allow_unprotected)
    return {"signed_in": True, "account": email}


def sign_out(allow_unprotected: bool = False) -> Dict[str, Any]:
    k = _keys(allow_unprotected)
    rt = k.get("GOOGLE_REFRESH_TOKEN")
    revoked = False
    if rt:
        try:
            _req("POST", REVOKE_URL, _form({"token": rt}), {"Content-Type": "application/x-www-form-urlencoded"})
            revoked = True
        except DriveError:
            revoked = False
    _save({"GOOGLE_REFRESH_TOKEN": "", "GOOGLE_ACCOUNT": ""}, allow_unprotected)
    return {"signed_in": False, "revoked": revoked}


class Drive:
    """A signed-in session: an access token refreshed when it runs out."""

    def __init__(self, allow_unprotected: bool = False):
        self.allow = allow_unprotected
        k = _keys(allow_unprotected)
        self.cid, self.sec, self.rt = k.get("GOOGLE_CLIENT_ID"), k.get("GOOGLE_CLIENT_SECRET"), \
            k.get("GOOGLE_REFRESH_TOKEN")
        if not (self.cid and self.sec):
            raise DriveError("Google Drive is not set up yet (no OAuth client).")
        if not self.rt:
            raise DriveError("Not signed in to Google Drive.")
        self._tok, self._exp = None, 0.0

    def token(self) -> str:
        if self._tok and time.time() < self._exp - 60:
            return self._tok
        try:
            t = _json("POST", TOKEN_URL, _form({"client_id": self.cid, "client_secret": self.sec,
                                                "refresh_token": self.rt, "grant_type": "refresh_token"}),
                      {"Content-Type": "application/x-www-form-urlencoded"})
        except DriveError as e:
            if "invalid_grant" in str(e) or "expired" in str(e).lower() or "revoked" in str(e).lower():
                _save({"GOOGLE_REFRESH_TOKEN": "", "GOOGLE_ACCOUNT": ""}, self.allow)
                raise DriveError("The Google sign-in has expired or was removed. Please sign in again.")
            raise
        self._tok, self._exp = t["access_token"], time.time() + float(t.get("expires_in", 3600))
        return self._tok

    def _h(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        h = {"Authorization": "Bearer " + self.token()}
        h.update(extra or {})
        return h

    # --- folder
    def folder(self) -> str:
        q = ("mimeType='%s' and name='%s' and trashed=false and appProperties has {key='ariyan' and "
             "value='bundles'}" % (FOLDER_MIME, FOLDER_NAME))
        r = _json("GET", API + "/files?" + urllib.parse.urlencode({"q": q, "fields": "files(id,name)",
                                                                   "spaces": "drive"}), headers=self._h())
        if r.get("files"):
            return r["files"][0]["id"]
        meta = {"name": FOLDER_NAME, "mimeType": FOLDER_MIME, "appProperties": {"ariyan": "bundles"}}
        r = _json("POST", API + "/files?fields=id", json.dumps(meta).encode("utf-8"),
                  self._h({"Content-Type": "application/json; charset=UTF-8"}))
        return r["id"]

    # --- list
    def bundles(self) -> List[Dict[str, Any]]:
        fid = self.folder()
        q = "'%s' in parents and trashed=false" % fid
        r = _json("GET", API + "/files?" + urllib.parse.urlencode({
            "q": q, "orderBy": "createdTime desc", "pageSize": "50",
            "fields": "files(id,name,size,createdTime,md5Checksum,appProperties)"}), headers=self._h())
        out = []
        for f in r.get("files", []):
            if not f["name"].endswith(".ariyan"):
                continue
            ap = f.get("appProperties") or {}
            out.append({"id": f["id"], "name": f["name"], "bytes": int(f.get("size") or 0),
                        "created": f.get("createdTime"), "md5": f.get("md5Checksum"),
                        "from_device": ap.get("from_device", ""), "candidates": ap.get("candidates", "")})
        return out

    # --- upload
    def upload(self, path: str, props: Optional[Dict[str, str]] = None,
               progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
        size = os.path.getsize(path)
        md5 = hashlib.md5()
        with open(path, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                md5.update(b)
        local_md5 = md5.hexdigest()
        meta = {"name": os.path.basename(path), "parents": [self.folder()],
                "appProperties": dict({"ariyan": "bundle", "gd": VERSION}, **(props or {}))}
        with _req("POST", UPLOAD + "?uploadType=resumable&fields=id", json.dumps(meta).encode("utf-8"),
                  self._h({"Content-Type": "application/json; charset=UTF-8",
                           "X-Upload-Content-Type": "application/octet-stream",
                           "X-Upload-Content-Length": str(size)})) as r:
            session = r.headers.get("Location")
        if not session:
            raise DriveError("Google did not open an upload session.")
        sent = 0
        file_id = None
        with open(path, "rb") as f:
            while sent < size or size == 0:
                chunk = f.read(CHUNK)
                end = sent + len(chunk) - 1
                hdr = {"Content-Length": str(len(chunk)),
                       "Content-Range": ("bytes %d-%d/%d" % (sent, end, size)) if size else "bytes */0"}
                req = urllib.request.Request(session, data=chunk, method="PUT", headers=hdr)
                try:
                    with urllib.request.urlopen(req, timeout=300) as rr:
                        file_id = json.loads(rr.read().decode("utf-8")).get("id")
                        sent = size
                except urllib.error.HTTPError as e:
                    if e.code == 308:                    # resume incomplete: Google kept this chunk
                        rng = e.headers.get("Range")
                        sent = int(rng.split("-")[1]) + 1 if rng else sent + len(chunk)
                        f.seek(sent)
                    else:
                        raise DriveError("Upload stopped: Google answered %d." % e.code)
                if progress:
                    progress(sent, size)
                if size == 0:
                    break
        if not file_id:
            raise DriveError("The upload did not finish.")
        info = _json("GET", API + "/files/%s?fields=id,name,size,md5Checksum" % file_id, headers=self._h())
        if info.get("md5Checksum") != local_md5:
            try:
                self.delete(file_id)
            except DriveError:
                pass
            raise DriveError("The copy on Drive does not match the file (MD5 %s vs %s); it was removed. Nothing "
                                 "else changed. Please upload again." % (info.get("md5Checksum"), local_md5))
        return {"id": file_id, "name": info.get("name"), "bytes": int(info.get("size") or size), "md5": local_md5}

    # --- download
    def download(self, file_id: str, dest_dir: str, expect_md5: Optional[str] = None,
                 progress: Optional[Callable[[int, int], None]] = None) -> str:
        info = _json("GET", API + "/files/%s?fields=id,name,size,md5Checksum" % file_id, headers=self._h())
        name = os.path.basename(info.get("name") or "bundle.ariyan")
        size = int(info.get("size") or 0)
        os.makedirs(dest_dir, exist_ok=True)
        part = os.path.join(dest_dir, name + ".part")
        md5 = hashlib.md5()
        got = 0
        with _req("GET", API + "/files/%s?alt=media" % file_id, headers=self._h(), timeout=300) as r, \
                open(part, "wb") as f:
            for b in iter(lambda: r.read(1 << 20), b""):
                f.write(b)
                md5.update(b)
                got += len(b)
                if progress:
                    progress(got, size)
        want = expect_md5 or info.get("md5Checksum")
        if want and md5.hexdigest() != want:
            os.remove(part)
            raise DriveError("The downloaded file does not match Drive's checksum; it was discarded. Nothing "
                             "changed. Please try again.")
        final = os.path.join(dest_dir, name)
        os.replace(part, final)
        return final

    def delete(self, file_id: str):
        """Moves the file to the Drive bin (recoverable for 30 days), never a permanent delete."""
        _req("PATCH", API + "/files/%s?fields=id" % file_id, json.dumps({"trashed": True}).encode("utf-8"),
             self._h({"Content-Type": "application/json; charset=UTF-8"})).close()


def free_port_ok() -> bool:
    """The sign-in needs a page on 127.0.0.1; true when this computer allows one."""
    try:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.close()
        return True
    except OSError:
        return False


def run_threaded(fn: Callable[[], Any]) -> threading.Thread:
    t = threading.Thread(target=fn, daemon=True)
    t.start()
    return t
