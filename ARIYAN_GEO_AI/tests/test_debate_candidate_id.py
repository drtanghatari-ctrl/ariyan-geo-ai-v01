"""Regression lock for the old 'Candidate null:' bug in the Investigation screen's AI
Debate text: every debated candidate must carry a real, non-null candidate_id (#1, #2, ...),
also in the Steward report, whatever the anomaly records contain."""
import json

import debate_mobile as dm


def _anom(i, **extra):
    a = {"lat": 32.1 + i * 0.001, "lon": 48.3, "row": 5 + i, "col": 5, "area_cells": 4, "peak_residual_m": 2.5,
         "mean_residual_m": 1.2, "peak_zscore": 7.5 - i, "polarity": "positive", "evidence_type": "DEM"}
    a.update(extra)
    return a


def test_every_debate_has_a_real_candidate_id():
    inv = {"aoi": {"cell_size_m": 10.4}, "correlation": [], "evidence": [], "sources": ["DEM"],
           "anomalies": [_anom(0), _anom(1, id=None, candidate_id=None),      # explicit nulls must not leak
                         {"evidence_type": "NDVI", "lat": 32.0, "lon": 48.0},  # skipped, not debated
                         _anom(2)]}
    r = json.loads(dm.run_debate_json(json.dumps(inv)))
    ids = [d["candidate_id"] for d in r["debates"]]
    assert len(ids) == 3 and all(isinstance(x, str) and x and x != "None" for x in ids), ids
    for d in r["debates"]:
        assert d.get("steward", {}).get("candidate_id") not in (None, "None", "null")
