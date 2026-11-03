"""win-w4b: a single-point investigation and a wide-area job run on this computer with
the phone's own pipeline (fixture DEM tile from the core tests, offline only, no keys),
and the results are saved to the project exactly as on the phone."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ariyan_win import core_path  # noqa: E402

core_path.install()

from test_fi_v1 import _bridge_env  # noqa: E402

from ariyan_win import runs  # noqa: E402


def test_single_point_investigation_is_saved_with_its_debate(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))       # no keys: offline tiles only
    root, *_ = _bridge_env(tmp_path)
    r = runs.run_investigation(root, 33.5, 51.5, 500, 96, "SRTMGL1", False)
    assert "error" not in r, r
    assert r["record"]["evidence"] and r["save_error"] is None
    assert r["saved"]["investigation_id"] and r["saved"]["candidate_ids"]
    assert r["saved"].get("single_point_job_id")                  # sp-v1: refine / auto run possible
    assert r["debate"].get("debates")


def test_wide_area_job_runs_offline_and_counts_tiles(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    root, *_ = _bridge_env(tmp_path)
    import wide_area_search_mobile as wa
    j = json.loads(wa.create_wide_area_search_job_json(root, runs._gid(root), "t", "bbox", 33.49, 33.51, 51.49,
                                                       51.51, 1000.0))
    out = runs.run_job(root, j["job_id"], "dem_offline")
    assert out.get("total") == j["n_tiles"] and out.get("done") == j["n_tiles"] and out.get("failed") == 0


def test_one_run_at_a_time(tmp_path):
    assert runs._RUN_LOCK.acquire(blocking=False)
    try:
        assert "Another run" in runs.run_job(str(tmp_path), "x", "full")["error"]
        assert "Another run" in runs.run_investigation(str(tmp_path), 1, 1, 500, 96, "SRTMGL1", False)["error"]
    finally:
        runs._RUN_LOCK.release()


def test_auto_runner_stops_between_steps(monkeypatch):
    import auto_pipeline as ap
    calls = []

    def fake_slice(root, rid, *a):
        calls.append(rid)
        return json.dumps({"state": "RUNNING", "next_step": "sweep"})
    monkeypatch.setattr(ap, "run_slice_json", fake_slice)
    ar = runs.AutoRunner()
    ticks = []

    def tick(s):
        ticks.append(s)
        ar.stop_flag = True                                         # user presses Stop during the first step
    r = ar.run("/tmp/x", "run1", tick)
    assert r["stopped_by_user"] and len(calls) == 1 and ticks


def test_runs_refused_after_sending_the_project(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    root, *_ = _bridge_env(tmp_path)
    import project_bundle as pb
    pb.make_bundle(root, str(tmp_path / "drive"), "laptop")
    assert "sent the project" in runs.run_investigation(root, 33.5, 51.5, 500, 96, "SRTMGL1", False)["error"]
    assert "sent the project" in runs.run_job(root, "any", "full")["error"]
