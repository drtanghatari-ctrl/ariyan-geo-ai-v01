"""
debate_mobile.py -- Chaquopy entry point wrapping debate_engine.py for
MainActivity.kt.

Kotlin calls debate_mobile.run_debate_json(investigation_json: str) and
expects a JSON string back (see MainActivity.kt's runDebate() /
appendDebateSection()). debate_engine.py's public API works on Python
dicts, not JSON strings, and expects candidate dicts using its own alias
vocabulary (z_score, elevation_delta_m, correlation_status, sources,
ndvi_synthetic -- see debate_engine.py's module docstring and _get()
helper). This module is the translation layer between the two: it does
NOT modify debate_engine.py's core rule logic for existing fields (per
that file's own docstring recommendation -- "the rule logic itself does
not need to change"), it only maps this project's REAL InvestigationRecord
schema (confirmed by reading evidence_record.py, anomaly_detection_mobile.py,
correlation.py, and investigation_multi_mobile.py directly, not guessed)
onto the field names debate_engine.py already knows how to read.

REAL SCHEMA NOTES (why this file looks the way it does):
- anomalies[] entries are AnomalyCandidate dicts: row, col, lat, lon,
  area_cells, peak_residual_m, mean_residual_m, peak_zscore, polarity
  (+ "evidence_type": "DEM"/"NDVI" in multi-source runs; ABSENT entirely
  in single-source investigation_mobile.py output). There is no natural
  id/candidate_id field anywhere in this schema, so this module assigns
  one itself: each debated candidate gets "id" set to its own 1-based
  position in THIS RUN'S OWN anomalies[] list (e.g. the first anomaly
  entry becomes "#1", matching the numbering MainActivity.kt's
  renderResult() already shows in its "Candidates: #N ..." listing).
- correlation[] entries (when present) are CorrelatedCandidate dicts:
  lat, lon, status ("CORROBORATED"/"SINGLE_SOURCE"), supporting_sources,
  distance_between_peaks_m, note. In real-NDVI mode