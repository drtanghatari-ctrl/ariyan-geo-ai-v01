"""job-lease-v1: one live runner per wide-area search job (Golestan bb3530
double-processing fix, 2026-10-24)."""
import json
import os
import threading
import time

import pytest

import auto_pipeline as ap
import grand_project_db as db
import grand_project_sync
import investigation_multi_mobile
import debate_mobile
import wide_area_search_mobile as was


def _job(root, n=4):
    gp = db.create_grand_project(root, "t")
    centers = [{"tile_index": i, "center_lat": 32.1 + i * 0.01, "center_lon": 48.3} for i in range(n)]
    jid = db.create_wide_area_search_job(root, gp, "lease", "MANUAL_BBOX", 32.1, 32.15, 48.3, 48.31, 1000, centers)
    return gp, jid


@pytest.fixture
def fake_tiles(monkeypatch):
    """Replaces the expensive per-tile work; counts investigations."""
    calls = {"n": 0, "gate": None}

    def inv(lat, lon, *a, **k):
        calls["n"] += 1
        if calls["gate"] is not None:
            calls["gate"].wait(5)
        return json.dumps({"lat": lat, "lon": lon})

    def record(root, gp, inv_json, **k):
        return {"investigation_id": db.create_investigation(root, gp, "", "", {})}

    monkeypatch.setattr(investigation_multi_mobile, "run_investigation_multi_json", inv)
    monkeypatch.setattr(debate_mobile, "run_debate_json", lambda j: None)
    monkeypatch.setattr(grand_project_sync, "record_investigation_results", record)
    monkeypatch.setattr(was, "parse_tile_health", lambda j: None)
    return calls


def test_acquire_refuses_live_holder_and_release_frees(tmp_path):
    root = str(tmp_path)
    _, jid = _job(root)
    owner = db.acquire_job_run_lease(root, jid)
    # same thread, still holding -> a second acquire is refused
    with pytest.raises(db.JobBusyError):
        db.acquire_job_run_lease(root, jid)
    db.release_job_run_lease(root, jid, owner)
    db.release_job_run_lease(root, jid, db.acquire_job_run_lease(root, jid))


def test_takeover_when_holder_thread_died(tmp_path):
    root = str(tmp_path)
    _, jid = _job(root)
    t = threading.Thread(target=lambda: db.acquire_job_run_lease(root, jid))  # never released
    t.start(); t.join()
    db.acquire_job_run_lease(root, jid)   # holder thread is gone -> allowed


def test_takeover_when_stale_or_process_dead(tmp_path, monkeypatch):
    root = str(tmp_path)
    _, jid = _job(root)
    db.acquire_job_run_lease(root, jid)
    conn = db.get_connection(root)
    with conn:
        conn.execute("UPDATE wide_area_search_job_lease SET owner_pid = 999999999")
    conn.close()
    monkeypatch.setattr(db, "_pid_alive", lambda pid: False)
    db.acquire_job_run_lease(root, jid)          # dead process -> allowed
    conn = db.get_connection(root)
    with conn:
        conn.execute("UPDATE wide_area_search_job_lease SET owner_pid = 999999999, heartbeat_ts = ?",
                     (time.time() - db.JOB_LEASE_STALE_S - 5,))
    conn.close()
    monkeypatch.setattr(db, "_pid_alive", lambda pid: True)
    db.acquire_job_run_lease(root, jid)          # alive but silent too long -> allowed


def test_second_concurrent_run_is_refused_and_no_tile_runs_twice(tmp_path, fake_tiles):
    root = str(tmp_path)
    _, jid = _job(root, n=4)
    gate = threading.Event()
    fake_tiles["gate"] = gate
    out = {}
    a = threading.Thread(target=lambda: out.setdefault("a", was.run_wide_area_search_job(
        root, jid, read_land_cover=False)))
    a.start()
    for _ in range(100):
        if fake_tiles["n"]:
            break
        time.sleep(0.02)
    with pytest.raises(db.JobBusyError):
        was.run_wide_area_search_job(root, jid, read_land_cover=False)
    gate.set(); a.join(10)
    assert json.loads(out["a"])["done"] == 4
    assert fake_tiles["n"] == 4                      # exactly one investigation per tile
    tiles = db.list_tiles_for_job(root, jid)
    assert len({t["investigation_id"] for t in tiles}) == 4
    # lease released afterwards: a re-run is allowed and does nothing
    was.run_wide_area_search_job(root, jid, read_land_cover=False)
    assert fake_tiles["n"] == 4


def test_runner_skips_tile_that_stopped_being_pending(tmp_path, fake_tiles, monkeypatch):
    root = str(tmp_path)
    gp, jid = _job(root, n=3)
    tiles = db.list_tiles_for_job(root, jid)
    real_pending = db.list_pending_tiles_for_job

    def stale_list(r, j):
        rows = real_pending(r, j)
        db.mark_tile_done(r, tiles[1]["id"], db.create_investigation(r, gp, "", "", {}))
        return rows                                   # still contains tile 1
    monkeypatch.setattr(db, "list_pending_tiles_for_job", stale_list)
    was.run_wide_area_search_job(root, jid, read_land_cover=False)
    assert fake_tiles["n"] == 2


def test_auto_pipeline_pauses_when_job_busy(tmp_path, monkeypatch):
    root = str(tmp_path)
    _, jid = _job(root)

    def busy(*a, **k):
        raise db.JobBusyError("busy")
    monkeypatch.setattr(was, "run_wide_area_search_job", busy)
    run = {"job_id": jid, "options": {"sweep_demtype": "COP30"}}
    with pytest.raises(ap.PauseStep) as e:
        ap._step_sweep(root, run, {"api_key": ""}, time.time() + 60)
    assert e.value.retry_after_s == ap.JOB_BUSY_PAUSE_S
