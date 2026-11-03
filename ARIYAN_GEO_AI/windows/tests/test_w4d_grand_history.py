"""win-w4d: Grand Project and Historical Research tabs use the phone's own modules;
trust and target need a reason; a historical search result is saved once and a job
starts only from a located finding with the user's own radius (no network here)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ariyan_win import core_path  # noqa: E402

core_path.install()

import grand_project_db as db  # noqa: E402


def _pump(qa, n=5):
    from ariyan_win import qtwork
    for _ in range(n):
        qtwork.wait_all(30000)
        qa.processEvents()


def test_grand_project_tab_reads_dashboard_hypotheses_and_timeline(tmp_path):
    from PySide6 import QtWidgets
    from ariyan_win.grandproject import GrandProject
    import grand_project_query_mobile as q
    import wide_area_search_mobile as wa
    root = str(tmp_path)
    gid = db.create_grand_project(root, "Default Grand Project", project_id="default")
    j = json.loads(wa.create_wide_area_search_job_json(root, gid, "U2 Solduz", "bbox", 36.9, 36.92, 45.5, 45.52, 1000.0))
    q.create_hypothesis_json(root, gid, "A tell under the village edge")
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    w = GrandProject(root)
    _pump(qa)
    assert w.jobs.rowCount() == 1 and w.jobs.item(0, 0).text() == "U2 Solduz"
    assert "tell under the village" in w.hyps.item(0).text()
    assert w.timeline.rowCount() >= 2
    r = json.loads(q.set_job_trust_json(root, j["job_id"], "TRUSTED", "checked on the phone"))
    assert "error" not in r
    w.close()


def test_historical_save_and_job_from_located_finding(tmp_path, monkeypatch):
    from PySide6 import QtWidgets
    from ariyan_win.grandproject import HistoricalResearch
    import historical_research_mobile as hr
    import wide_area_search_mobile as wa
    root = str(tmp_path)
    gid = db.create_grand_project(root, "Default Grand Project", project_id="default")
    result = {"query": "Hasanlu", "source_counts": {"wikidata": 1}, "source_errors": {},
              "located_findings": [{"key": "wd:Q1", "title_en": "Hasanlu", "best_tier": "B", "in_iran": True,
                                    "coordinates": [{"tier": "B", "source": "wikidata", "lat": 37.0045,
                                                     "lon": 45.4583}], "links": {}}],
              "unlocated_findings": [], "literature": []}
    monkeypatch.setattr(hr, "run_historical_search_json", lambda q, *a: json.dumps(result))
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    w = HistoricalResearch(root)
    w.query.setText("Hasanlu")
    w._search()
    _pump(qa)
    assert w.found.count() == 1 and "Hasanlu" in w.found.item(0).text()
    saved = json.loads(hr.save_located_finding_json(root, gid, w.search_json, "wd:Q1"))
    assert "error" not in saved
    rows = json.loads(hr.list_geographic_suggestions_json(root, gid))
    assert len(rows) == 1 and rows[0]["kind"] == "LOCATED_FINDING"
    r = json.loads(wa.create_wide_area_search_job_from_suggestion_json(root, gid, "hist: Hasanlu", rows[0]["lat"],
                                                                       rows[0]["lon"], 1.0,
                                                                       geographic_suggestion_id=rows[0]["id"]))
    assert r.get("n_tiles", 0) > 0
    w.close()
