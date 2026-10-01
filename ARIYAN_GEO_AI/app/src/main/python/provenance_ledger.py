"""
provenance_ledger.py  --  Phase 4a (ledger version "pl-v1")

PURPOSE: record, for every NEW evidence_link row, where its data came from and
which code produced it, in an append-only, hash-chained table. This module
only RECORDS. The checker that turns these records into Verified / Not
verified is Phase 4b. Nothing here changes any evidence, label, review or
Steward confidence.

WHAT ONE RECORD HOLDS (table provenance_record, one row per evidence row):
  - evidence_sha256: hash of the evidence row exactly as stored (candidate id,
    type, relation, detail JSON text, recorded_at). A later edit of the
    evidence row no longer matches it.
  - sources_json: the data sources behind the row:
      FILE        an offline file (path, name, size, SHA-256)
      LIVE        a live web response (service host, redacted URL / params,
                  SHA-256 of the request body if any, SHA-256 + size of the
                  raw response, fetch time). Only the hashes are kept; secrets
                  (API_Key, tokens, client secret) are never stored, and
                  OAuth token exchanges are not recorded at all.
      USER_RECORD a user-supplied field record (GPR/ERT): SHA-256 of the record.
  - capture_state:
      CAPTURED       the sources were observed while the investigation ran
      EXPLICIT       the writer supplied the sources itself (terrain labels)
      NOT_CAPTURED   no observation exists (reason in capture_note). Such a
                     row can never be Verified later.
  - code_bundle_md5: MD5 over every app Python module loaded at the time; the
    per-file MD5 list is stored once in provenance_code_bundle. With the
    build setting pyc{src=false} the files are the shipped .py sources, so
    each MD5 can be compared with the same file on GitHub.
  - prev_hash / record_hash: each record's hash covers the previous record's
    hash. Editing or deleting any earlier record breaks every later hash.

HOW SOURCES ARE OBSERVED (install(), called once from grand_project_sync):
  thin wrappers, same pattern as sh_backoff.install(), around
    investigation_multi_mobile.run_investigation_multi_json  (opens a capture)
    offline_dem_store._get_cached_tile(path)                  (DEM file)
    offline_ndvi_store._load_cell(path)                       (NDVI file)
    dem_source_mobile.OpenTopographyAAIGridSource._get_with_hard_deadline
    {ndvi,thermal,optical,sar}_source_mobile._urlopen_with_hard_deadline
  The wrappers record and pass every result through unchanged. A wrapper
  that fails to record never changes what the wrapped call returns.
  When a run finishes, its capture is filed under the SHA-256 of the exact
  JSON string the run returned. A writer then calls bind(investigation_json):
  the capture is used only if that exact output is found, so evidence can
  never be attributed to a different run, whichever thread wrote it.

FAILURE RULE: a ledger failure never blocks or rolls back the evidence row.
It is written to provenance_issue and the evidence row simply has no record
(the 4b checker will report it as missing).

Old evidence rows (written before this module existed) get no records here.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

LEDGER_VERSION = "pl-v1"
GENESIS_HASH = "0" * 64

CAPTURED = "CAPTURED"
EXPLICIT = "EXPLICIT"
NOT_CAPTURED = "NOT_CAPTURED"

# evidence_type -> source kinds that can stand behind it
_KINDS_FOR_TYPE = {
    "DEM": ("DEM",),
    "NDVI": ("NDVI",),
    "THERMAL": ("THERMAL",),
    "OPTICAL": ("OPTICAL",),
    "SAR": ("SAR",),
}
_USER_RECORD_TYPES = ("GPR", "ERT")

_URL_TARGETS = (
    ("ndvi_source_mobile", "NDVI"),
    ("thermal_source_mobile", "THERMAL"),
    ("optical_source_mobile", "OPTICAL"),
    ("sar_source_mobile", "SAR"),
)
_SECRET_KEYS = {"api_key", "apikey", "key", "token", "access_token",
                "client_secret", "password", "secret"}

_MAX_KEPT_CAPTURES = 64

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS provenance_record (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        evidence_link_id INTEGER NOT NULL UNIQUE,
        candidate_id     TEXT,
        evidence_type    TEXT,
        evidence_sha256  TEXT NOT NULL,
        capture_state    TEXT NOT NULL,
        capture_note     TEXT,
        capture_id       TEXT,
        output_sha256    TEXT,
        sources_json     TEXT NOT NULL,
        code_bundle_md5  TEXT,
        method_version   TEXT,
        ledger_version   TEXT NOT NULL,
        recorded_at      TEXT NOT NULL,
        prev_hash        TEXT NOT NULL,
        record_hash      TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provenance_source_file (
        path            TEXT PRIMARY KEY,
        size_bytes      INTEGER NOT NULL,
        mtime_ns        INTEGER NOT NULL,
        sha256          TEXT NOT NULL,
        first_hashed_at TEXT NOT NULL,
        last_hashed_at  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provenance_code_bundle (
        bundle_md5  TEXT PRIMARY KEY,
        files_json  TEXT NOT NULL,
        all_py      INTEGER NOT NULL,
        recorded_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provenance_issue (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        occurred_at      TEXT NOT NULL,
        evidence_link_id INTEGER,
        message          TEXT NOT NULL
    )
    """,
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def ensure_schema(conn) -> None:
    for s in _SCHEMA:
        conn.execute(s)


# =========================== CAPTURE (observation) ===========================

_tl = threading.local()
_lock = threading.Lock()
_finished: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_installed: Dict[str, Any] = {}


def _active() -> Optional[Dict[str, Any]]:
    return getattr(_tl, "capture", None)


def _note(entry: Dict[str, Any]) -> None:
    """Add one observed source to the running capture (if any). Never raises."""
    try:
        cap = _active()
        if cap is None:
            return
        key = _canon({k: v for k, v in entry.items() if k != "fetched_at"})
        if key not in cap["_keys"]:
            cap["_keys"].add(key)
            cap["sources"].append(entry)
    except Exception:
        pass


def _redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in _SECRET_KEYS]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), ""))
    except Exception:
        return "(unparseable url)"


def _is_token_url(url: str) -> bool:
    low = (url or "").lower()
    return low.rstrip("/").endswith("/token") or "openid-connect" in low or "/oauth" in low


def _wrap_run(orig: Callable[..., Any]) -> Callable[..., Any]:
    def wrapped(*args, **kwargs):
        if _active() is not None:          # nested call: belongs to the outer run
            return orig(*args, **kwargs)
        cap = {"capture_id": "cap-" + uuid.uuid4().hex[:16],
               "started_at": _now_iso(), "sources": [], "_keys": set(), "_files": set()}
        _tl.capture = cap
        try:
            result = orig(*args, **kwargs)
        finally:
            _tl.capture = None
        try:
            if isinstance(result, str):
                out = _sha256_bytes(result.encode("utf-8"))
                cap["output_sha256"] = out
                cap["finished_at"] = _now_iso()
                cap.pop("_keys", None)
                cap.pop("_files", None)
                with _lock:
                    _finished[out] = cap
                    _finished.move_to_end(out)
                    while len(_finished) > _MAX_KEPT_CAPTURES:
                        _finished.popitem(last=False)
        except Exception:
            pass
        return result
    wrapped.__wrapped__ = orig  # type: ignore[attr-defined]
    return wrapped


def _wrap_file(orig: Callable[..., Any], kind: str) -> Callable[..., Any]:
    def wrapped(path, *args, **kwargs):
        result = orig(path, *args, **kwargs)
        cap = _active()
        if result is not None and cap is not None and (kind, path) not in cap["_files"]:
            cap["_files"].add((kind, path))
            _note({"kind": kind, "type": "FILE", "path": str(path),
                   "name": os.path.basename(str(path))})
        return result
    wrapped.__wrapped__ = orig  # type: ignore[attr-defined]
    return wrapped


def _wrap_urlopen(orig: Callable[..., Any], kind: str) -> Callable[..., Any]:
    def wrapped(req, timeout):
        result = orig(req, timeout)
        try:
            url = getattr(req, "full_url", "") or ""
            if _active() is not None and not _is_token_url(url):
                body = getattr(req, "data", None)
                raw = result.encode("utf-8") if isinstance(result, str) else (
                    result if isinstance(result, (bytes, bytearray)) else _canon(result).encode())
                _note({"kind": kind, "type": "LIVE",
                       "service": urlsplit(url).netloc,
                       "method": req.get_method() if hasattr(req, "get_method") else None,
                       "url": _redact_url(url),
                       "request_body_sha256": _sha256_bytes(body) if isinstance(body, (bytes, bytearray)) else None,
                       "response_sha256": _sha256_bytes(bytes(raw)),
                       "response_bytes": len(raw),
                       "fetched_at": _now_iso()})
        except Exception:
            pass
        return result
    wrapped.__name__ = getattr(orig, "__name__", "_urlopen_with_hard_deadline")
    wrapped.__wrapped__ = orig  # type: ignore[attr-defined]
    return wrapped


def _wrap_opentopo(orig: Callable[..., Any]) -> Callable[..., Any]:
    def wrapped(self, params):
        resp = orig(self, params)
        try:
            if _active() is not None and getattr(resp, "status_code", None) == 200:
                content = resp.content or b""
                _note({"kind": "DEM", "type": "LIVE",
                       "service": urlsplit(getattr(self, "BASE_URL", "")).netloc or "opentopography",
                       "method": "GET",
                       "params": {k: v for k, v in dict(params).items()
                                  if k.lower() not in _SECRET_KEYS},
                       "response_sha256": _sha256_bytes(content),
                       "response_bytes": len(content),
                       "fetched_at": _now_iso()})
        except Exception:
            pass
        return resp
    wrapped.__wrapped__ = orig  # type: ignore[attr-defined]
    return wrapped


def install() -> Dict[str, bool]:
    """Install every observation wrapper exactly once. Idempotent. A module
    that is missing or has changed shape is skipped (that source is then
    simply not observed). Returns {target: installed?}."""
    with _lock:
        def patch(mod_name: str, attr: str, maker: Callable[[Any], Any], cls_name: Optional[str] = None):
            tag = "%s.%s%s" % (mod_name, (cls_name + ".") if cls_name else "", attr)
            if tag in _installed:
                return
            try:
                mod = importlib.import_module(mod_name)
                holder = getattr(mod, cls_name) if cls_name else mod
                orig = getattr(holder, attr)
                setattr(holder, attr, maker(orig))
                _installed[tag] = orig
            except Exception:
                pass

        patch("investigation_multi_mobile", "run_investigation_multi_json", _wrap_run)
        patch("offline_dem_store", "_get_cached_tile", lambda o: _wrap_file(o, "DEM"))
        patch("offline_ndvi_store", "_load_cell", lambda o: _wrap_file(o, "NDVI"))
        patch("dem_source_mobile", "_get_with_hard_deadline", _wrap_opentopo,
              cls_name="OpenTopographyAAIGridSource")
        for mod_name, kind in _URL_TARGETS:
            patch(mod_name, "_urlopen_with_hard_deadline", lambda o, k=kind: _wrap_urlopen(o, k))
        return dict((k, True) for k in _installed)


def installed_targets() -> List[str]:
    return sorted(_installed)


# =========================== BINDING (writer side) ===========================

def bind(investigation_json: Optional[str]) -> str:
    """Attach the capture of the run that produced exactly this output to
    the calling thread's following evidence writes. Returns the capture
    state that will be used. Never raises."""
    try:
        if not isinstance(investigation_json, str):
            _tl.bound = {"state": NOT_CAPTURED, "note": "no investigation output to bind"}
            return NOT_CAPTURED
        out = _sha256_bytes(investigation_json.encode("utf-8"))
        with _lock:
            cap = _finished.get(out)
        if cap is None:
            note = ("observation wrappers were not installed when this investigation ran"
                    if not _installed else
                    "no capture matches this investigation output (run outside the observed path)")
            _tl.bound = {"state": NOT_CAPTURED, "note": note, "output_sha256": out}
            return NOT_CAPTURED
        _tl.bound = {"state": CAPTURED, "capture": cap, "output_sha256": out}
        return CAPTURED
    except Exception as exc:
        _tl.bound = {"state": NOT_CAPTURED, "note": "bind failed: %s" % type(exc).__name__}
        return NOT_CAPTURED


def unbind() -> None:
    _tl.bound = None


# =========================== FILE HASHES ===========================

_file_cache: Dict[Tuple[str, int, int], str] = {}


def file_sha256(path: str) -> Tuple[str, int, int]:
    """(sha256, size, mtime_ns) of a file, re-hashed only when size or
    modification time changed. Raises OSError if unreadable."""
    st = os.stat(path)
    key = (path, st.st_size, st.st_mtime_ns)
    h = _file_cache.get(key)
    if h is None:
        d = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                d.update(block)
        h = d.hexdigest()
        _file_cache[key] = h
    return h, st.st_size, st.st_mtime_ns


def _register_file(conn, path: str, sha: str, size: int, mtime_ns: int, now: str) -> None:
    conn.execute(
        "INSERT INTO provenance_source_file (path, size_bytes, mtime_ns, sha256, first_hashed_at, last_hashed_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(path) DO UPDATE SET "
        "size_bytes = excluded.size_bytes, mtime_ns = excluded.mtime_ns, "
        "sha256 = excluded.sha256, last_hashed_at = excluded.last_hashed_at",
        (path, size, mtime_ns, sha, now, now))


# =========================== CODE BUNDLE ===========================

_bundle_cache: Dict[frozenset, Tuple[str, List[Dict[str, Any]], bool]] = {}
_APP_DIR = os.path.dirname(os.path.abspath(__file__))


def _module_bytes(mod) -> Optional[bytes]:
    path = getattr(mod, "__file__", None)
    loader = getattr(mod, "__loader__", None)
    if loader is not None and hasattr(loader, "get_data") and path:
        try:
            return loader.get_data(path)
        except Exception:
            pass
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None


def code_bundle() -> Tuple[str, List[Dict[str, Any]], bool]:
    """(bundle_md5, [{module, file, md5}], all_py) over every loaded app module."""
    mods = []
    for name, mod in list(sys.modules.items()):
        path = getattr(mod, "__file__", None)
        if not path or name == "__main__" or str(path).startswith("<"):
            continue
        try:
            if os.path.dirname(os.path.abspath(path)) != _APP_DIR:
                continue
        except Exception:
            continue
        mods.append((name, mod, path))
    key = frozenset(n for n, _, _ in mods)
    hit = _bundle_cache.get(key)
    if hit is not None:
        return hit
    files = []
    for name, mod, path in sorted(mods, key=lambda t: t[0]):
        data = _module_bytes(mod)
        files.append({"module": name, "file": os.path.basename(path),
                      "md5": hashlib.md5(data).hexdigest() if data is not None else None})
    all_py = all(f["file"].endswith(".py") and f["md5"] for f in files)
    bundle_md5 = hashlib.md5(_canon(files).encode()).hexdigest()
    result = (bundle_md5, files, all_py)
    _bundle_cache[key] = result
    return result


# =========================== WRITING RECORDS ===========================

def _log_issue(conn, evidence_link_id: Optional[int], message: str) -> None:
    try:
        conn.execute("INSERT INTO provenance_issue (occurred_at, evidence_link_id, message) VALUES (?, ?, ?)",
                     (_now_iso(), evidence_link_id, message[:1000]))
    except Exception:
        pass


def _resolve_sources(conn, sources: List[Dict[str, Any]], now: str) -> List[Dict[str, Any]]:
    out = []
    for s in sources:
        s = dict(s)
        if s.get("type") == "FILE" and s.get("path") and not s.get("sha256"):
            try:
                sha, size, mtime_ns = file_sha256(s["path"])
                s["sha256"], s["size_bytes"] = sha, size
                _register_file(conn, s["path"], sha, size, mtime_ns, now)
            except OSError as exc:
                s["sha256"] = None
                s["hash_error"] = "%s: %s" % (type(exc).__name__, exc)
        elif s.get("type") == "FILE" and s.get("path") and s.get("sha256"):
            try:
                st = os.stat(s["path"])
                s.setdefault("size_bytes", st.st_size)
                _register_file(conn, s["path"], s["sha256"], st.st_size, st.st_mtime_ns, now)
            except OSError:
                pass
        out.append(s)
    return out


def record_evidence(conn, evidence_link_id: int, row: Tuple[str, str, str, Optional[str], str],
                    sources: Optional[List[Dict[str, Any]]] = None,
                    method_version: Optional[str] = None) -> Optional[str]:
    """Write the ledger record for one just-inserted evidence row, inside the
    caller's open transaction (call it right after the INSERT, so the write
    lock already held keeps the chain in order). `row` is exactly what was
    stored: (candidate_id, evidence_type, relation, detail_json, recorded_at).
    `sources` given => EXPLICIT; otherwise the thread's bound capture is used.
    Returns the record hash, or None on failure (logged, never raised)."""
    try:
        ensure_schema(conn)
        candidate_id, evidence_type, relation, detail_json, recorded_at = row
        now = _now_iso()
        evidence_sha = _sha256_bytes(_canon([candidate_id, evidence_type, relation,
                                             detail_json, recorded_at]).encode())
        if method_version is None and detail_json:
            try:
                mv = json.loads(detail_json).get("method_version")
                method_version = mv if isinstance(mv, str) else None
            except Exception:
                pass

        capture_id = output_sha = note = None
        if sources is not None:
            state = EXPLICIT
            chosen = sources
        else:
            bound = getattr(_tl, "bound", None) or {"state": NOT_CAPTURED,
                                                     "note": "evidence written without bind()"}
            state = bound["state"]
            note = bound.get("note")
            output_sha = bound.get("output_sha256")
            chosen = []
            if state == CAPTURED:
                cap = bound["capture"]
                capture_id = cap.get("capture_id")
                kinds = _KINDS_FOR_TYPE.get(evidence_type)
                if kinds is not None:
                    chosen = [s for s in cap["sources"] if s.get("kind") in kinds]
                    if not chosen:
                        note = "run was observed but no %s source was read or fetched" % evidence_type
                elif evidence_type not in _USER_RECORD_TYPES:
                    chosen = list(cap["sources"])
            if evidence_type in _USER_RECORD_TYPES:
                chosen = chosen + [{"kind": evidence_type, "type": "USER_RECORD",
                                    "sha256": _sha256_bytes((detail_json or "").encode())}]
        resolved = _resolve_sources(conn, chosen, now)

        bundle_md5, files, all_py = code_bundle()
        conn.execute("INSERT OR IGNORE INTO provenance_code_bundle (bundle_md5, files_json, all_py, recorded_at) "
                     "VALUES (?, ?, ?, ?)", (bundle_md5, _canon(files), 1 if all_py else 0, now))

        last = conn.execute("SELECT record_hash FROM provenance_record ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = last[0] if last else GENESIS_HASH
        sources_json = _canon(resolved)
        body = {"ledger_version": LEDGER_VERSION, "prev_hash": prev_hash,
                "evidence_link_id": evidence_link_id, "evidence_sha256": evidence_sha,
                "capture_state": state, "capture_note": note, "capture_id": capture_id,
                "output_sha256": output_sha, "sources_json": sources_json,
                "code_bundle_md5": bundle_md5, "method_version": method_version,
                "recorded_at": now}
        record_hash = _sha256_bytes(_canon(body).encode())
        conn.execute(
            "INSERT INTO provenance_record (evidence_link_id, candidate_id, evidence_type, evidence_sha256, "
            "capture_state, capture_note, capture_id, output_sha256, sources_json, code_bundle_md5, "
            "method_version, ledger_version, recorded_at, prev_hash, record_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (evidence_link_id, candidate_id, evidence_type, evidence_sha, state, note, capture_id,
             output_sha, sources_json, bundle_md5, method_version, LEDGER_VERSION, now,
             prev_hash, record_hash))
        return record_hash
    except Exception as exc:
        _log_issue(conn, evidence_link_id, "ledger write failed: %s: %s" % (type(exc).__name__, exc))
        return None


def record_hash_of(row: Dict[str, Any]) -> str:
    """Recompute a stored record's hash from its columns (used by 4b)."""
    body = {k: row.get(k) for k in ("ledger_version", "prev_hash", "evidence_link_id",
                                    "evidence_sha256", "capture_state", "capture_note",
                                    "capture_id", "output_sha256", "sources_json",
                                    "code_bundle_md5", "method_version", "recorded_at")}
    return _sha256_bytes(_canon(body).encode())


def evidence_sha256_of(candidate_id, evidence_type, relation, detail_json, recorded_at) -> str:
    return _sha256_bytes(_canon([candidate_id, evidence_type, relation, detail_json, recorded_at]).encode())
