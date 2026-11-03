"""
project_bundle.py -- W2 / bundle-v1 (2026-11-02, user-approved plan). Runs on the
phone AND on the Windows app (same file).

Moves the Grand Project between the phone and the laptop as ONE sealed file
(`ARIYAN_project_<when>_<device>.ariyan`, a zip) through Google Drive or USB.
A live database file is never synced: the bundle holds a consistent snapshot
taken with SQLite's online backup API, plus a manifest with its SHA-256.

ONE DEVICE WORKS ON THE PROJECT AT A TIME. Sending writes handoff.json
("SENT", with the fingerprint of the database at that moment). When this device
later receives a project back, the receive is refused -- unless the user
confirms -- if this device's own database changed after it was sent (those
changes would be replaced), or if the incoming bundle is older than the
project on this device.

WHAT TRAVELS: grand_project.db (everything: candidates, reviews, evidence,
debates, calib-v1, timeline, provenance), the saved satellite answers
(sat_library) and saved satellite images (sat_image_library), and imported
field data files (field_data/store). The big terrain libraries do NOT travel
(DEM tiles are gigabytes; each device keeps its own).

RECEIVING NEVER LOSES DATA: the current database is first copied to
db_backups/grand_project_before_receive_<when>.db (a user copy: never pruned and
never deletable from Settings), the incoming file is checked (zip integrity,
SHA-256, SQLite integrity, a Grand Project inside) before anything changes, then
swapped in with one atomic rename; the db-safe-v1 size guard is reset to the new
size. Library files are MERGED: only files missing here are added, an existing
file is never overwritten, and index entries already here are kept.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import grand_project_db as db

VERSION = "bundle-v1"
FORMAT = "ariyan-bundle-v1"
SUFFIX = ".ariyan"
HANDOFF_FILENAME = "handoff.json"
MANIFEST = "manifest.json"
DB_IN_ZIP = "grand_project.db"
LIBRARIES = ("sat_library", "sat_image_library")          # <dir>/<kind>/<files> + <kind>/index.json
PLAIN_FOLDERS = (os.path.join("field_data", "store"),)      # files copied as they are
DEVICES = ("phone", "laptop")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _db_path(root: str) -> str:
    return os.path.join(root, db.DB_FILENAME)


def _read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path: str, data) -> None:
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def handoff(root: str) -> Dict[str, Any]:
    return _read_json(os.path.join(root, HANDOFF_FILENAME), {})


def content_fingerprint(db_file: str) -> str:
    """What the project holds, not its bytes: per table the row count, highest rowid and the
    newest row itself (two devices can each add one different row).
    Reading the project (SQLite tidying pages, empty tables created on first read)
    leaves this unchanged; adding
    candidates, reviews, evidence, events or debates changes it."""
    conn = sqlite3.connect(db_file)
    try:
        parts = []
        for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                                 "ORDER BY name"):
            try:
                n, mx = conn.execute('SELECT COUNT(*), MAX(rowid) FROM "%s"' % t).fetchone()
                last = conn.execute('SELECT * FROM "%s" ORDER BY rowid DESC LIMIT 1' % t).fetchone()
            except sqlite3.DatabaseError:                 # WITHOUT ROWID tables: count only
                n, mx, last = conn.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0], None, None
            if n:                                        # empty tables don't count (some are created on first read)
                parts.append("%s:%s:%s:%s" % (t, n, mx, repr(last)))
        return hashlib.sha256("|".join(parts).encode()).hexdigest()
    finally:
        conn.close()


def _project_facts(db_file: str) -> Dict[str, Any]:
    """Counts and newest activity, read straight from a database file."""
    conn = sqlite3.connect(db_file)                # read only: SELECTs, nothing written
    conn.row_factory = sqlite3.Row
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "grand_project" not in names:
            raise ValueError("no Grand Project inside this database")

        def count(t):
            return conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] if t in names else 0

        last = None
        if "timeline_event" in names:
            last = conn.execute("SELECT MAX(occurred_at) FROM timeline_event WHERE event_type NOT IN "
                                "('PROJECT_SENT', 'PROJECT_RECEIVED')").fetchone()[0]   # real work only
        return {"projects": count("grand_project"), "candidates": count("candidate"),
                "jobs": count("wide_area_search_job"), "investigations": count("investigation"),
                "debates": count("debate_record"), "last_activity": last}
    finally:
        conn.close()


def _snapshot(root: str, dest: str) -> None:
    """Consistent copy of the live database (SQLite online backup API)."""
    src = db.get_connection(root)                  # goes through db-safe-v1 (guard + daily backup)
    try:
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------

KEEP_OUTGOING = 2                                       # older bundles in the outgoing folder are removed


def _tidy_outgoing(out_dir: str, keep_name: str) -> None:
    try:
        olds = sorted(n for n in os.listdir(out_dir) if n.startswith("ARIYAN_project_") and n.endswith(SUFFIX))
    except OSError:
        return
    for n in olds[:-KEEP_OUTGOING]:
        if n != keep_name:
            try:
                os.remove(os.path.join(out_dir, n))
            except OSError:
                pass


def make_bundle(root: str, out_dir: str, device: str, include_libraries: bool = True,
                tidy: bool = False) -> Dict[str, Any]:
    device = (device or "").lower()
    if device not in DEVICES:
        raise ValueError("device must be phone or laptop")
    if not os.path.isfile(_db_path(root)):
        raise FileNotFoundError("there is no grand_project.db on this device to send")
    os.makedirs(out_dir, exist_ok=True)
    when = _now()
    name = "ARIYAN_project_%s_%s%s" % (when.strftime("%Y%m%d_%H%M%S"), device, SUFFIX)
    path = os.path.join(out_dir, name)
    tmpdir = tempfile.mkdtemp(prefix="ariyan_send_")
    try:
        snap = os.path.join(tmpdir, DB_IN_ZIP)
        _snapshot(root, snap)
        facts = _project_facts(snap)
        sha = _sha256(snap)
        content = content_fingerprint(snap)
        files = 0
        part = path + ".part"
        with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            z.write(snap, DB_IN_ZIP)
            if include_libraries:
                for folder in LIBRARIES + PLAIN_FOLDERS:
                    base = os.path.join(root, folder)
                    for dirpath, _dirs, names in os.walk(base):
                        for n in names:
                            if n.endswith(".part"):
                                continue
                            full = os.path.join(dirpath, n)
                            rel = os.path.relpath(full, root).replace("\\", "/")
                            z.write(full, "files/" + rel)
                            files += 1
            manifest = {"format": FORMAT, "version": VERSION, "created_at": when.isoformat(),
                        "from_device": device, "db_sha256": sha, "content": content, "db_bytes": os.path.getsize(snap),
                        "project": facts, "library_files": files,
                        "note": "ARIYAN GEO AI project bundle. Open it with Receive in ARIYAN (phone Settings "
                                "or the Windows app). Only one device works on the project at a time."}
            z.writestr(MANIFEST, json.dumps(manifest, indent=1))
        os.replace(part, path)
        if tidy:
            _tidy_outgoing(out_dir, name)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    _log(root, "PROJECT_SENT", name, "Project sent as %s (%d candidates, %d library files) to the %s."
         % (name, facts["candidates"], files, "laptop" if device == "phone" else "phone"))
    _write_json(os.path.join(root, HANDOFF_FILENAME),            # after the log entry, so it counts as "as sent"
                {"state": "SENT", "bundle": name, "at": when.isoformat(), "to": "laptop" if device == "phone" else "phone",
                 "content_at_send": content_fingerprint(_db_path(root)), "bundle_content": content, "version": VERSION})
    return {"path": path, "name": name, "bytes": os.path.getsize(path), "manifest": manifest}


# ---------------------------------------------------------------------------
# receive
# ---------------------------------------------------------------------------

def inspect_bundle(bundle_path: str) -> Dict[str, Any]:
    """Read and verify a bundle without changing anything on this device."""
    if not zipfile.is_zipfile(bundle_path):
        raise ValueError("this file is not an ARIYAN project bundle (not a zip)")
    with zipfile.ZipFile(bundle_path) as z:
        bad = z.testzip()
        if bad is not None:
            raise ValueError("the bundle is damaged (%s); send it again" % bad)
        try:
            manifest = json.loads(z.read(MANIFEST).decode("utf-8"))
        except KeyError:
            raise ValueError("the bundle has no manifest; it was not made by ARIYAN")
        if manifest.get("format") != FORMAT:
            raise ValueError("unknown bundle format %r" % manifest.get("format"))
        if DB_IN_ZIP not in z.namelist():
            raise ValueError("the bundle holds no database")
        for n in z.namelist():                     # never write outside the data folder
            if n.startswith("/") or ".." in n.replace("\\", "/").split("/"):
                raise ValueError("the bundle contains an unsafe path: %s" % n)
    return manifest


def _local_state(root: str) -> Dict[str, Any]:
    p = _db_path(root)
    if not os.path.isfile(p):
        return {"exists": False}
    facts = None
    try:
        facts = _project_facts(p)
    except Exception:
        facts = None
    return {"exists": True, "content": content_fingerprint(p), "bytes": os.path.getsize(p), "project": facts}


def check_receive(root: str, bundle_path: str) -> Dict[str, Any]:
    """What a receive would do, and whether the user must confirm it first."""
    m = inspect_bundle(bundle_path)
    local = _local_state(root)
    warnings: List[str] = []
    info: List[str] = []
    h = handoff(root)
    if local["exists"]:
        if h.get("state") == "SENT":
            if local["content"] != h.get("content_at_send"):
                warnings.append("This device changed its project AFTER sending it (%s). Receiving replaces those "
                                "changes; they stay only in the safety copy." % h.get("bundle"))
        elif h.get("state") == "RECEIVED" and local["content"] != h.get("content_at_receive"):
            warnings.append("This device changed its project after receiving it (%s) and has not sent it back. "
                            "Receiving replaces those changes; they stay only in the safety copy." % h.get("bundle"))
        elif not h and local["content"] != m.get("content"):
            warnings.append("This device's project was not sent from here, so it may hold work that is not in "
                            "the bundle. Receiving replaces it; it stays in the safety copy.")
        la = (local.get("project") or {}).get("last_activity")
        ba = (m.get("project") or {}).get("last_activity")
        unchanged_since_handoff = (h.get("state") == "SENT" and local["content"] == h.get("content_at_send")) or \
            (h.get("state") == "RECEIVED" and local["content"] == h.get("content_at_receive"))
        if la and ba and la > ba and not unchanged_since_handoff:
            warnings.append("The project on this device has newer activity (%s) than the bundle (%s)."
                            % (la[:16].replace("T", " "), ba[:16].replace("T", " ")))
        if local["content"] == m.get("content"):
            warnings = []
            info.append("This device already has exactly this project; receiving only adds missing library files.")
    return {"manifest": m, "local": local, "handoff": h, "warnings": warnings, "info": info,
            "needs_confirm": bool(warnings)}


def _merge_files(z: zipfile.ZipFile, root: str) -> Dict[str, int]:
    added, kept = 0, 0
    indexes: Dict[str, Dict[str, Any]] = {}
    for n in z.namelist():
        if not n.startswith("files/") or n.endswith("/"):
            continue
        rel = n[len("files/"):]
        dest = os.path.join(root, *rel.split("/"))
        if os.path.basename(rel) == "index.json" and rel.split("/")[0] in LIBRARIES:
            indexes[dest] = json.loads(z.read(n).decode("utf-8") or "{}")
            continue
        if os.path.exists(dest):
            kept += 1                                   # never overwrite a file already here
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with z.open(n) as src, open(dest + ".part", "wb") as out:
            shutil.copyfileobj(src, out)
        os.replace(dest + ".part", dest)
        added += 1
    for dest, incoming in indexes.items():              # index: union, entries already here win
        here = _read_json(dest, {})
        if not isinstance(here, dict) or not isinstance(incoming, dict):
            continue
        merged = dict(incoming)
        merged.update(here)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        _write_json(dest, merged)
    return {"added": added, "kept": kept, "indexes": len(indexes)}


def receive(root: str, bundle_path: str, device: str, confirm: bool = False) -> Dict[str, Any]:
    device = (device or "").lower()
    if device not in DEVICES:
        raise ValueError("device must be phone or laptop")
    chk = check_receive(root, bundle_path)
    if chk["needs_confirm"] and not confirm:
        return dict(chk, received=False)
    m = chk["manifest"]
    os.makedirs(root, exist_ok=True)
    stamp = _now().strftime("%Y%m%d_%H%M%S")
    tmpdir = tempfile.mkdtemp(prefix="ariyan_recv_", dir=root)
    try:
        with zipfile.ZipFile(bundle_path) as z:
            incoming = os.path.join(tmpdir, DB_IN_ZIP)
            with z.open(DB_IN_ZIP) as src, open(incoming, "wb") as out:
                shutil.copyfileobj(src, out)
            if _sha256(incoming) != m["db_sha256"]:
                raise ValueError("the database inside the bundle does not match its fingerprint; send it again")
            conn = sqlite3.connect(incoming)
            try:
                ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                conn.close()
            if ok != "ok":
                raise ValueError("the database inside the bundle failed its integrity check: %s" % ok)
            _project_facts(incoming)                    # must hold a Grand Project
            safety = None
            live = _db_path(root)
            if os.path.isfile(live):
                bdir = os.path.join(root, db.BACKUP_DIRNAME)
                os.makedirs(bdir, exist_ok=True)
                safety = os.path.join(bdir, "grand_project_before_receive_%s.db" % stamp)
                _snapshot(root, safety)
            for sfx in ("-wal", "-shm", "-journal"):    # stale side files of the old database
                if os.path.exists(live + sfx):
                    os.remove(live + sfx)
            os.replace(incoming, live)
            db._write_guard(root, os.path.getsize(live))  # db-safe-v1: the new size is the expected size
            files = _merge_files(z, root)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    _log(root, "PROJECT_RECEIVED", os.path.basename(bundle_path),
         "Project received from the %s (%s); previous database kept as %s; %d library files added, %d already here."
         % (m.get("from_device"), os.path.basename(bundle_path), os.path.basename(safety) if safety else "none",
            files["added"], files["kept"]))
    _write_json(os.path.join(root, HANDOFF_FILENAME),
                {"state": "RECEIVED", "bundle": os.path.basename(bundle_path), "at": _now().isoformat(),
                 "from": m.get("from_device"), "content_at_receive": content_fingerprint(_db_path(root)),
                 "version": VERSION})
    return dict(chk, received=True, safety_copy=safety, files=files)


def _log(root: str, event: str, ref: str, text: str) -> None:
    try:
        conn = db.get_connection(root)
        try:
            db.initialize_schema(conn)
            gp = conn.execute("SELECT id FROM grand_project ORDER BY created_at LIMIT 1").fetchone()
        finally:
            conn.close()
        if gp is not None:
            db.log_timeline_event(root, gp[0], event, "project_bundle", ref, text)
    except Exception:
        pass                                            # the record is a courtesy; never fail the transfer


# ---------------------------------------------------------------------------
# JSON wrappers for the screens
# ---------------------------------------------------------------------------

def _wrap(fn, *a, **k) -> str:
    try:
        return json.dumps(fn(*a, **k), default=str)
    except Exception as e:                              # shown, never hidden
        return json.dumps({"error": "%s: %s" % (type(e).__name__, e)})


def make_bundle_json(root: str, out_dir: str, device: str, tidy: bool = False) -> str:
    return _wrap(make_bundle, root, out_dir, device, True, bool(tidy))


def outgoing_dir(root: str) -> str:
    """The phone's own folder for bundles it made (ARIYAN_GEO_AI/offline_data/sync/outgoing)."""
    return os.path.join(root, "sync", "outgoing")


def incoming_dir(root: str) -> str:
    return os.path.join(root, "sync", "incoming")


def check_receive_json(root: str, bundle_path: str) -> str:
    return _wrap(check_receive, root, bundle_path)


def receive_json(root: str, bundle_path: str, device: str, confirm: bool = False) -> str:
    return _wrap(receive, root, bundle_path, device, bool(confirm))


def status_json(root: str) -> str:
    def st():
        h = handoff(root)
        return {"handoff": h, "local": _local_state(root), "version": VERSION}
    return _wrap(st)
