"""
debate_store.py -- dbr-v1 (2026-10-31): keep every AI Debate result.

Until now the four perspectives (Geomorphology, Anthropogenic, Artifact
Skeptic, Vegetation), their synthesis and the full Steward report were
computed on every run and then thrown away; only the Steward's confidence
band/number/reasoning reached the database (confidence_history). From this
version on, each debated candidate's complete debate dict is stored here,
append-only, exactly as debate_mobile.run_debate_json() produced it, with
the investigation it came from, where it came from (a run or a Pass 2
refinement) and the SHA-256 of debate_engine.py + debate_mobile.py that
produced it.

Never re-creates a debate. Never changes a candidate, a review, a status or
a confidence. A storage failure must never hide or block a run, so the
callers wrap record() and carry on.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional

import grand_project_db as db

VERSION = "dbr-v1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS debate_record (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id     TEXT NOT NULL,
    investigation_id TEXT,
    origin           TEXT NOT NULL,
    recorded_at      TEXT NOT NULL,
    store_version    TEXT NOT NULL,
    engine_sha256    TEXT NOT NULL,
    debate_json      TEXT NOT NULL,
    FOREIGN KEY (candidate_id) REFERENCES candidate(id)
)
"""

_ENGINE_SHA: Optional[str] = None


def engine_sha256() -> str:
    """SHA-256 over debate_engine.py + debate_mobile.py bytes (the rules that
    produced a stored debate), read from the files themselves."""
    global _ENGINE_SHA
    if _ENGINE_SHA is None:
        h = hashlib.sha256()
        here = os.path.dirname(os.path.abspath(__file__))
        for name in ("debate_engine.py", "debate_mobile.py"):
            try:
                with open(os.path.join(here, name), "rb") as f:
                    h.update(f.read())
            except OSError:
                h.update(("missing:" + name).encode())
        _ENGINE_SHA = h.hexdigest()
    return _ENGINE_SHA


def _conn(db_root: str):
    conn = db.get_connection(db_root)
    db.initialize_schema(conn)
    conn.execute(_SCHEMA)
    return conn


def record(db_root: str, candidate_id: str, debate: Dict[str, Any], investigation_id: Optional[str],
           origin: str) -> int:
    if origin not in ("run", "refinement"):
        raise ValueError("origin must be 'run' or 'refinement'")
    if not isinstance(debate, dict) or "positions" not in debate:
        raise ValueError("not a debate result")
    conn = _conn(db_root)
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO debate_record (candidate_id, investigation_id, origin, recorded_at, store_version, "
                "engine_sha256, debate_json) VALUES (?,?,?,?,?,?,?)",
                (candidate_id, investigation_id, origin, db._now_iso(), VERSION, engine_sha256(),
                 json.dumps(debate, sort_keys=True, default=str)))
            return cur.lastrowid
    finally:
        conn.close()


def record_quietly(db_root: str, candidate_id: str, debate: Optional[Dict[str, Any]],
                   investigation_id: Optional[str], origin: str) -> Optional[int]:
    """For the run/refinement paths: storing a debate must never break them."""
    if not debate:
        return None
    try:
        return record(db_root, candidate_id, debate, investigation_id, origin)
    except Exception:
        return None


def list_for_candidate(db_root: str, candidate_id: str) -> List[Dict[str, Any]]:
    """All stored debates for a candidate, oldest first (each with its parsed debate)."""
    conn = _conn(db_root)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM debate_record WHERE candidate_id = ? ORDER BY id", (candidate_id,))]
    finally:
        conn.close()
    for r in rows:
        try:
            r["debate"] = json.loads(r.pop("debate_json"))
        except ValueError:
            r["debate"] = None
    return rows
