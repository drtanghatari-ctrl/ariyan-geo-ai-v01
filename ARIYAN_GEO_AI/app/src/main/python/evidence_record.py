"""
evidence_record.py -- Minimal, honest evidence/investigation record.

This intentionally does NOT replicate the hash-chained "custody
governance" pattern found elsewhere in the ARIYAN codebase (append-only
ledgers validating ledgers of ledgers). That pattern produces a large
amount of code that verifies its own bookkeeping without ever
strengthening the underlying science. What actually matters for
scientific defensibility is much simpler and is implemented here:

  - every evidence item states its source and whether it's real or synthetic
  - every derived product states what it was derived from and by what method
  - every anomaly is reported with its supporting numbers, not a verdict
  - the record is a single, inspectable JSON document -- not a tool a
    human must trust without reading

FOURTH EVIDENCE SLOT (Thermal, a prior session): mirrors the existing
`second_evidence`/`second_anomalies` pattern exactly (a single aggregate
wrapper appended to `evidence`, plus a per-candidate detail list kept
OUT of `anomalies[]` and reported in its own `fourth_evidence_detail`
field) rather than the `third_evidence` (GPR) pattern, because Thermal
-- like NDVI -- is a per-DEM-candidate corroborating check, not a
single site-anchored field-verification note. `third_evidence` (GPR)
is unchanged.

FIFTH EVIDENCE SLOT ADDED THIS SESSION (Optical): follows the EXACT same
shape as `fourth_evidence`/`fourth_anomalies` (itself modeled on
`second_evidence`/`second_anomalies`) -- a single aggregate wrapper
object appended to `evidence`, plus a per-candidate detail list kept
OUT of `anomalies[]` and reported in its own `fifth_evidence_detail`
field. Optical (real Sentinel-2 visible-band brightness / soilmark