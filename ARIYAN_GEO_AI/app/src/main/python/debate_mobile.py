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
  (investigation_multi_mobile.py's per-candidate path) each entry's
  lat/lon is copied directly from its one DEM candidate, so matching by
  nearest lat/lon is always exact. In synthetic-NDVI mode, correlate_
  anomalies() sorts correlation[] independently of anomalies[] order and
  uses a centroid lat/lon for CORROBORATED (2+ source) groups -- still
  exact for SINGLE_SOURCE entries (centroid of one point is that point),
  and a close match for CORROBORATED ones (centroid of co-located points
  within colocation_distance_m by construction). Nearest-match is
  therefore correct, not a guess, across both modes.
- TWO DISTINCT "sources" CONCEPTS, KEPT SEPARATE (a prior session -- see
  SOURCES-SPLIT FIX note below for the full story): "which sources
  actually CORROBORATED this candidate" (precise, drives correlation-
  status reasoning text) and "which sources were CHECKED/attempted for
  this candidate regardless of outcome" (broader, drives the Vegetation/
  Agronomic perspective's "was NDVI evaluated at all" question). These
  used to be silently merged into one field; conflating them was the
  root cause of a real on-device bug, now fixed and unaffected by
  Optical's, ERT's, or Stability's addition (each follows its own
  documented, distinct match strategy, never touching this split).
- SCOPE: only anomalies[] entries with evidence_type == "DEM" (or no
  evidence_type at all -- single-source runs) are debated. In synthetic-
  NDVI mode, anomalies[] can also hold NDVI-raster-detected candidates
  (evidence_type == "NDVI") that were never individually corroborated
  against a specific DEM candidate; debating those through perspectives
  written around "elevation anomaly magnitude" would not be a faithful
  use of the tool, so they're skipped and reported as a count instead of
  silently dropped. Skipped candidates are NOT counted when assigning
  "id" to the debated ones -- id is always the anomaly's own position in
  the full anomalies[] list, so it stays aligned with the "Candidates:"
  section's own #N numbering regardless of how many others were skipped.

GPR (ground-penetrating radar) EXTENSION: a real GPR field pick
(evidence_record.py's third evidence slot, see
gpr_source_mobile.GPREvidence.as_evidence_record()) is anchored at the
investigation's own (lat, lon) -- it is a single site-anchored check,
not a per-candidate one like NDVI/Thermal/Optical core/halo. This module
therefore matches the GPR pick to whichever DEM candidate(s) are close
enough (within a distance tolerance derived from the AOI's cell size,
same reasoning as investigation_multi_mobile.py's own default
colocation_distance_m) to plausibly be about the same physical location,
and attaches gpr_confirmed/gpr_distance_m/gpr_depth_min_m/gpr_depth_max_m
to just those candidates. A candidate that's too far from the GPR pick
gets nothing added -- GPR wasn't informative for it, which is the honest
state, not a guess either way. If GPR evidence exists but no candidate
was close enough to use it, that is reported in the result's "gpr_note"
field rather than silently discarded.

REAL THERMAL EXTENSION (a prior session): unlike GPR's single
site-anchored pick, real Landsat thermal (evidence_record.py's fourth
evidence slot -- see thermal_source_mobile.py and
investigation_multi_mobile.py's _run_thermal_checks) is a per-DEM-
candidate check, run at EACH candidate's own exact (lat, lon) --
matching is therefore a TIGHT-tolerance exact match (a few meters, to
absorb only floating-point noise, not GPR's colocation-radius-style
"was this nearby" match), via _attach_thermal_detail() below. This uses
fourth_evidence_detail's own per-candidate error field directly, so it
correctly distinguishes "Thermal genuinely checked and succeeded for
this candidate" from "Thermal was attempted for this run but failed for
this specific candidate".

REAL OPTICAL EXTENSION (a prior session): like Thermal, real Sentinel-2
visible-brightness (evidence_record.py's fifth evidence slot -- see
optical_source_mobile.py and investigation_multi_mobile.py's
_run_optical_checks) is a per-DEM-candidate check, run at EACH
candidate's own exact (lat, lon). _attach_optical_detail() below
mirrors _attach_thermal_detail() exactly -- same tight-tolerance
exact-match approach against fifth_evidence_detail by lat/lon, checking
that specific entry's own error field, for the same reasons documented
on _attach_thermal_detail() itself.

REAL ERT EXTENSION (a prior session): unlike Thermal/Optical, real
ERT (evidence_record.py's sixth evidence slot -- see
ert_source_mobile.py) is a SINGLE, site-anchored field-verification
reading, architecturally like GPR -- NOT a per-candidate check. This
module therefore matches the ERT reading to whichever DEM candidate(s)
are close enough via the SAME colocation-radius-style approach as GPR
(see _ert_colocation_distance_m() below, identical logic to
_gpr_colocation_distance_m() -- kept as a separate small function
rather than reusing/renaming the GPR one, to avoid touching that
already-proven code path), and attaches ert_confirmed/ert_distance_m/
ert_resistivity_ohm_m/ert_depth_m/ert_matched_bands/ert_lean to just
those candidates via _attach_ert() below. A candidate too far from the
ERT reading gets nothing added, exactly like GPR. If ERT evidence
exists but no candidate was close enough to use it, that is reported
in the result's "ert_note" field, mirroring "gpr_note".

DETECTION STABILITY EXTENSION, ADDED A PRIOR SESSION: unlike GPR/ERT
(single site-anchored readings) and unlike Thermal/Optical (run for
EVERY DEM candidate), Detection Stability (evidence_record.py's
seventh evidence slot -- see investigation_multi_mobile.py's
_run_stability_check()) is a per-candidate check run only for the
borderline subset of candidates that automatically qualified this run
(possibly zero, possibly all, typically a small number -- see that
module's _select_stability_candidates()). Each result IS anchored at
its own specific candidate's exact (lat, lon) (mirrors Thermal/
Optical's per-candidate anchoring, not GPR/ERT's colocation-radius
"was this nearby" style), so matching uses the SAME tight-tolerance
exact-match approach as _attach_thermal_detail()/_attach_optical_detail()
via the shared _attach_per_candidate_detail() helper -- see
_attach_stability_detail() below. Unlike Thermal/Optical's boolean
"checked" flag, this attaches the REAL stability_score (and, when
detected in at least one window, the real z_min/z_max range) onto the
candidate, since Scientific Steward needs the actual score value, not
just a yes/no -- see _build_steward_report() below for exactly how it's
read and passed through to steward_engine.evaluate_candidate().

SOURCES-SPLIT FIX (a prior session -- REAL on-device bug, unaffected by
Optical's, ERT's, or Stability's addition): candidate["sources"] is the
PRECISE list of sources that actually corroborated this candidate
(drives debate_engine.py's Anthropogenic/Geomorphology reasoning text
via _sources_present()). candidate["checked_sources"] is the BROADER
union of every source genuinely checked for this candidate regardless
of outcome (drives debate_engine.py's Vegetation/Agronomic perspective
via _sources_checked_present(), and this module's own
_build_steward_report() below for has_dem/has_ndvi). Optical follows
this exact same split from the start: it is exact-match-precise (via
_attach_optical_detail(), just like Thermal) rather than routed through
the whole-run union checked_sources -- see the NDVI PRECISION FIX note
below for how NDVI now follows this same precise pattern too, closing
the imprecision this section used to flag as deferred. ERT does not
participate in this "sources"/"checked_sources" concept at all -- like
GPR, it is read only via its own dedicated ert_confirmed/... fields,
never folded into either sources list, since neither GPR nor ERT ever
participates in correlation(). Detection Stability doesn't participate
in it either, for a different reason: it isn't a corroborating evidence
source at all (a stable detection isn't NEW evidence for a hypothesis,
it's a statement about how much the existing DEM evidence can be
trusted) -- see steward_confidence_ceiling.py's own docstring for why
it's read as a confidence-ceiling modifier instead, never counted as an
EvidenceCategory or folded into either sources list here.

NDVI PRECISION FIX (this session -- REAL on-device bug, previously
flagged as deferred): a real investigation run showed candidate
["checked_sources"] including "NDVI" purely because
investigation_multi_mobile.py always appends a RealNdviCoreHaloEvidence
aggregate wrapper to evidence[] whenever NDVI was ATTEMPTED this run --
regardless of whether the live per-candidate check, or the offline
raster fallback, actually SUCCEEDED for any candidate. On that run,
NDVI failed for every candidate (live check: no network; offline
fallback: no downloaded composite for the AOI), yet
debate_engine.py's Vegetation/Agronomic perspective still argued from
"NDVI (vegetation) evidence is present for this candidate" -- because
_build_context()'s context["sources"] (the whole-run union of every
evidence_type present in evidence[], used verbatim as the
`checked_sources` argument to every _build_candidate() call) had no way
to distinguish "NDVI was attempted somewhere this run" from "NDVI
genuinely succeeded for THIS candidate". This changed that candidate's
synthesis from what would otherwise have been an unambiguous leading
interpretation into a CONTESTED one -- a real, on-device-confirmed
wrong output, not a theoretical gap. Fixed by giving NDVI the SAME
exact-match precision Thermal/Optical/Stability already had (see
_attach_ndvi_detail() below, built on the same shared
_attach_per_candidate_detail() helper, matched against
second_evidence_detail -- the real per-candidate NdviCoreHaloResult
list investigation_multi_mobile.py already produces whenever the live
per-candidate NDVI path ran, success or failure). run_debate_json()
below now strips any "NDVI" entry that candidate["checked_sources"]
would otherwise have inherited from the whole-run union, and only adds
it back when either (a) NDVI genuinely corroborated this candidate
(already precise, unaffected -- candidate["sources"] already had this
right) or (b) this candidate's own real per-candidate check succeeded
(candidate["ndvi_checked"], newly attached). When the offline-raster
NDVI fallback ran instead of the live per-candidate path,
second_evidence_detail is empty (that path has no per-candidate
correspondence to lean on -- see this module's own SCOPE note above on
why non-DEM candidates from that path are skipped entirely), so
ndvi_checked correctly defaults to False there too, rather than
guessing. has_ndvi in _build_steward_report() below needed NO separate
change -- it already reads candidate["checked_sources"], which is now
precise by the time that function runs.

KNOWN, FLAGGED, NOT-YET-FIXED IMPRECISION -- NOW FIXED (see NDVI
PRECISION FIX above; this section kept as history rather than deleted,
per this project's own preference for an honest, visible record over a
silently rewritten one): this used to read "candidate["checked_sources"]
... cannot distinguish 'NDVI genuinely succeeded for THIS candidate'
from 'NDVI evidence exists somewhere in this run but genuinely failed
for EVERY candidate'. The SAME exact-match technique now used for
Thermal, Optical, and Stability could fix this too, if wanted --
deliberately not applied to NDVI here without asking first, since it
would change already-proven on-device behavior." That question has now
been asked and answered, with a real on-device case demonstrating the
imprecision produced a wrong synthesis -- see NDVI PRECISION FIX above
for the applied fix.

SCIENTIFIC STEWARD STAGE 1 EXTENSION: after debate_engine.run_debate()
returns its positions + synthesis for a candidate, this module also
calls steward_engine.evaluate_candidate() (see steward_engine.py) and
attaches the result under a new "steward" key on that same debate dict.
This is purely additive -- MainActivity.kt's existing
appendDebateSection() rendering is completely unaffected by the extra
key until it's explicitly updated to read it.

HONEST MAPPING NOTES (read before changing _build_steward_report below):
this module has REAL data for some Steward inputs and does NOT for
others -- the mapping below is deliberately conservative rather than
guessing, per this project's zero-fabrication rule:
  - has_dem: real, taken from candidate["checked_sources"] (the broader
    union -- see SOURCES-SPLIT FIX above). DEM is unaffected by the NDVI
    PRECISION FIX above -- every debated candidate originates from a DEM
    anomaly, so "DEM" is always genuinely present.
  - has_ndvi: real, taken from candidate["checked_sources"] -- now
    PRECISE as of this session (see NDVI PRECISION FIX above): "NDVI"
    only appears there when this specific candidate's real per-candidate
    check genuinely succeeded, or NDVI genuinely corroborated it. This
    function itself needed no code change -- it already read
    checked_sources; the fix happened upstream, in run_debate_json(),
    before this function is ever called.
  - has_gpr / has_field_validation: real, taken directly from
    candidate["gpr_confirmed"] (see _attach_gpr() above -- set only
    when a real GPR pick colocated with this specific candidate).
  - has_thermal: real, taken directly from candidate["thermal_checked"]
    (see _attach_thermal_detail() below -- set only when a real per-
    candidate Thermal check genuinely succeeded, i.e. its own error
    field was None, for THIS EXACT candidate).
  - has_optical: real, taken directly from candidate["optical_checked"]
    (see _attach_optical_detail() below -- same "genuinely succeeded
    for THIS EXACT candidate" semantics as has_thermal).
  - has_ert: real, taken directly from candidate["ert_confirmed"] (see
    _attach_ert() below -- set only when a real ERT reading colocated
    with this specific candidate, exactly like has_gpr/
    has_field_validation above). Note has_field_validation below is NOT
    updated to include ERT -- it remains gpr-only, since the Scientific
    Steward spec's "field validation" concept was defined around GPR
    specifically in Stage 1; revisiting that definition to also include
    ERT is a Steward-side decision, not something to fold in silently
    here.
  - has_lidar: always False. LiDAR has not been built (no real data
    source available for this project's operating region). Deliberate,
    not an oversight.
  - stability_score / stability_windows_detected /
    stability_windows_fetched / stability_z_range: real, taken directly
    from candidate["stability_score"] etc. (see _attach_stability_detail()
    below -- set only when this specific candidate qualified for and
    completed the automatic detection-stability check this run, via a
    tight exact-match against seventh_evidence_detail, same style as
    has_thermal/has_optical). A candidate that never qualified (well
    above dem_zscore_threshold, or the per-investigation cap was already
    reached by other candidates) has NO stability entry at all -- these
    four values all default to None, meaning "not tested," not
    "unstable." See steward_confidence_ceiling.py's own docstring for
    exactly how these feed into the confidence ceiling.
  - raw_debate_confidence: real, taken directly from
    synthesis["leading_confidence"] (0.0 when NO_DATA / absent, which
    correctly yields the Steward's NO_DATA band).
  - has_contradiction: an APPROXIMATION, not a true independent-evidence
    contradiction detector -- mapped from agreement_level == "CONTESTED"
    (two perspectives closely competing). This is honestly a proxy, not
    the real Team-A/Team-B/Judge contradiction detection the Scientific
    Steward spec describes for Stage 3.
  - environmental_confounders_controlled: always False for Stage 1.
  - provenance_verified: always False for Stage 1 (Stage 2, SHA-256
    evidence validation, not yet built).
  - quality_hints / requested_precision_m / effective_resolution_m: left
    unset (UNKNOWN / None). Not currently tracked as explicit
    per-candidate fields anywhere in this schema.
  - hypothesis / alternative_hypotheses / debate_summary: real, built
    directly from the SAME positions[]/synthesis{} debate_engine.py
    already produced.

A Steward evaluation failure for one candidate is caught and reported as
a "steward_error" string on that candidate's debate dict instead of
raising -- consistent with this file's existing "never raise across the
Chaquopy boundary" contract for run_debate_json as a whole.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from coordinate import GeoPoint, haversine_distance_m
from debate_engine import run_debate
from steward_engine import evaluate_candidate as steward_evaluate_candidate

# Tolerance for matching a DEM candidate to its OWN per-candidate NDVI,
# Thermal, Optical, or Stability detail entry. Deliberately tight (a few
# meters) -- unlike GPR's/ERT's colocation-radius-style tolerance for
# "was this nearby", NDVI/Thermal/Optical/Stability detail entries are
# all built directly from the SAME dem_candidate.lat/lon (see
# investigation_multi_mobile.py's _run_ndvi_checks/_run_thermal_checks/
# _run_optical_checks/_run_stability_check), so any real distance here
# should only ever reflect floating-point noise, not a genuine
# "different but nearby location" case. Shared by _attach_ndvi_detail(),
# _attach_thermal_detail(), _attach_optical_detail(), and
# _attach_stability_detail().
_PER_CANDIDATE_DETAIL_MATCH_TOLERANCE_M = 5.0


def _nearest_correlation_entry(anomaly: dict, correlation: list[dict]) -> Optional[dict]:
    if not correlation:
        return None
    try:
        a_point = GeoPoint(anomaly["lat"], anomaly["lon"])
    except (KeyError, TypeError):
        return None
    best = None
    best_dist = None
    for entry in correlation:
        try:
            e_point = GeoPoint(entry["lat"], entry["lon"])
            dist = haversine_distance_m(a_point, e_point)
        except (KeyError, TypeError):
            continue
        if best_dist is None or dist < best_dist:
            best = entry
            best_dist = dist
    return best


def _ndvi_synthetic_flag(evidence: list[dict]) -> Optional[bool]:
    for item in evidence or []:
        if item.get("evidence_type") == "NDVI":
            val = item.get("synthetic")
            return bool(val) if val is not None else None
    return None


def _gpr_evidence_item(evidence: list[dict]) -> Optional[dict]:
    for item in evidence or []:
        if item.get("evidence_type") == "GPR":
            return item
    return None


def _ert_evidence_item(evidence: list[dict]) -> Optional[dict]:
    """Mirrors _gpr_evidence_item() exactly -- finds the single ERT
    evidence item (evidence_record.py's sixth_evidence slot), if any."""
    for item in evidence or []:
        if item.get("evidence_type") == "ERT":
            return item
    return None


def _gpr_colocation_distance_m(investigation: dict) -> float:
    aoi = investigation.get("aoi") or {}
    cell_size_m = aoi.get("cell_size_m")
    try:
        cell_size_m = float(cell_size_m) if cell_size_m is not None else None
    except (TypeError, ValueError):
        cell_size_m = None
    if cell_size_m is None:
        return 50.0
    return max(30.0, cell_size_m * 4)


def _ert_colocation_distance_m(investigation: dict) -> float:
    """Identical logic to _gpr_colocation_distance_m() above -- kept as
    a separate function (small, deliberate duplication) rather than
    reusing or renaming the GPR one, to avoid any risk of touching
    GPR's already-proven-on-device code path while adding ERT."""
    aoi = investigation.get("aoi") or {}
    cell_size_m = aoi.get("cell_size_m")
    try:
        cell_size_m = float(cell_size_m) if cell_size_m is not None else None
    except (TypeError, ValueError):
        cell_size_m = None
    if cell_size_m is None:
        return 50.0
    return max(30.0, cell_size_m * 4)


def _attach_gpr(candidate: dict, anomaly: dict, gpr_item: Optional[dict], max_distance_m: float) -> bool:
    if gpr_item is None:
        return False
    try:
        anomaly_point = GeoPoint(anomaly["lat"], anomaly["lon"])
        gpr_point = GeoPoint(gpr_item["lat"], gpr_item["lon"])
        distance = haversine_distance_m(anomaly_point, gpr_point)
    except (KeyError, TypeError):
        return False
    if distance > max_distance_m:
        return False

    depth_estimates = gpr_item.get("depth_estimates_m") or []
    depth_mins = [d["depth_min_m"] for d in depth_estimates if d.get("depth_min_m") is not None]
    depth_maxs = [d["depth_max_m"] for d in depth_estimates if d.get("depth_max_m") is not None]

    candidate["gpr_confirmed"] = True
    candidate["gpr_distance_m"] = round(distance, 1)
    if depth_mins:
        candidate["gpr_depth_min_m"] = round(min(depth_mins), 3)
    if depth_maxs:
        candidate["gpr_depth_max_m"] = round(max(depth_maxs), 3)
    return True


def _attach_ert(candidate: dict, anomaly: dict, ert_item: Optional[dict], max_distance_m: float) -> bool:
    """Mirrors _attach_gpr() exactly -- ERT (evidence_record.py's
    sixth_evidence slot) is a single, site-anchored reading, not a
    per-candidate check, so it uses the same colocation-radius match
    style as GPR rather than the tight exact-match style used by
    NDVI/Thermal/Optical/Stability below. Sets ert_confirmed/ert_distance_m/
    ert_resistivity_ohm_m/ert_depth_m/ert_matched_bands/ert_lean on the
    candidate only when the ERT reading is close enough to plausibly be
    about the same physical location."""
    if ert_item is None:
        return False
    try:
        anomaly_point = GeoPoint(anomaly["lat"], anomaly["lon"])
        ert_point = GeoPoint(ert_item["lat"], ert_item["lon"])
        distance = haversine_distance_m(anomaly_point, ert_point)
    except (KeyError, TypeError):
        return False
    if distance > max_distance_m:
        return False

    candidate["ert_confirmed"] = True
    candidate["ert_distance_m"] = round(distance, 1)
    if ert_item.get("resistivity_ohm_m") is not None:
        candidate["ert_resistivity_ohm_m"] = ert_item["resistivity_ohm_m"]
    if ert_item.get("depth_m") is not None:
        candidate["ert_depth_m"] = ert_item["depth_m"]
    matched_bands = ert_item.get("matched_bands") or []
    if matched_bands:
        candidate["ert_matched_bands"] = [b.get("label") for b in matched_bands if b.get("label")]
    if ert_item.get("overall_lean"):
        candidate["ert_lean"] = ert_item["overall_lean"]
    return True


def _attach_per_candidate_detail(
    candidate: dict,
    anomaly: dict,
    detail_list: list[dict],
    flag_key: str,
    tolerance_m: float = _PER_CANDIDATE_DETAIL_MATCH_TOLERANCE_M,
) -> None:
    """Shared exact-match logic for _attach_ndvi_detail(),
    _attach_thermal_detail(), and _attach_optical_detail() below --
    sets candidate[flag_key] = True only when a real per-candidate
    result exists for THIS exact candidate (tight tolerance) AND that
    result's own error field is None (i.e. the check genuinely
    succeeded for this candidate, regardless of whether it detected an
    anomaly). False for: no detail present at all (this source never
    attempted this run, or -- for NDVI specifically -- the offline
    raster fallback ran instead of the live per-candidate path, so
    there is no per-candidate detail to match against), a detail entry
    existing only for a different/distant candidate, or a genuinely
    matched entry whose error field is set (this candidate's own check
    failed).

    NDVI's, Thermal's, and Optical's identical matching logic isn't
    duplicated verbatim -- each public function below is a thin wrapper
    naming its own detail list and flag key, preserving each one's own
    previously-proven behavior unchanged. Not used by GPR/ERT -- both
    are site-anchored (colocation-radius match via _attach_gpr()/
    _attach_ert() above), not per-candidate. Not used directly by
    Stability either -- see _attach_stability_detail() below, which
    needs the real stability_score value, not just a boolean, so it
    uses its own small nearest-match loop instead of this boolean-only
    helper.
    """
    best = None
    best_dist = None
    for entry in detail_list:
        try:
            e_point = GeoPoint(entry["lat"], entry["lon"])
            a_point = GeoPoint(anomaly["lat"], anomaly["lon"])
            dist = haversine_distance_m(a_point, e_point)
        except (KeyError, TypeError):
            continue
        if best_dist is None or dist < best_dist:
            best = entry
            best_dist = dist

    if best is None or best_dist is None or best_dist > tolerance_m:
        candidate[flag_key] = False
        return
    candidate[flag_key] = best.get("error") is None


def _attach_ndvi_detail(
    candidate: dict,
    anomaly: dict,
    second_evidence_detail: list[dict],
    tolerance_m: float = _PER_CANDIDATE_DETAIL_MATCH_TOLERANCE_M,
) -> None:
    """Sets candidate["ndvi_checked"] -- ADDED THIS SESSION, mirrors
    _attach_thermal_detail()/_attach_optical_detail() exactly via the
    shared _attach_per_candidate_detail() helper above. See module
    docstring, NDVI PRECISION FIX, for the full real on-device reasoning
    (closes the imprecision that section used to flag as deliberately
    deferred). second_evidence_detail is investigation_multi_mobile.py's
    real per-candidate NdviCoreHaloResult list (populated only when the
    live per-candidate NDVI path ran this investigation, success or
    failure -- schema-compatible with fourth/fifth_evidence_detail's
    lat/lon/error shape); it is empty when the offline-raster NDVI
    fallback ran instead, so ndvi_checked correctly defaults to False in
    that case too (that path is a full-grid geometric scan with no
    per-candidate correspondence to lean on -- see this module's own
    SCOPE note on why non-DEM candidates from that path are skipped
    entirely, rather than this function guessing at a match)."""
    _attach_per_candidate_detail(candidate, anomaly, second_evidence_detail, "ndvi_checked", tolerance_m)


def _attach_thermal_detail(
    candidate: dict,
    anomaly: dict,
    fourth_evidence_detail: list[dict],
    tolerance_m: float = _PER_CANDIDATE_DETAIL_MATCH_TOLERANCE_M,
) -> None:
    """Sets candidate["thermal_checked"] -- see
    _attach_per_candidate_detail()'s own docstring for the exact
    matching semantics."""
    _attach_per_candidate_detail(candidate, anomaly, fourth_evidence_detail, "thermal_checked", tolerance_m)


def _attach_optical_detail(
    candidate: dict,
    anomaly: dict,
    fifth_evidence_detail: list[dict],
    tolerance_m: float = _PER_CANDIDATE_DETAIL_MATCH_TOLERANCE_M,
) -> None:
    """Sets candidate["optical_checked"] -- mirrors
    _attach_thermal_detail() exactly via the shared
    _attach_per_candidate_detail() helper above."""
    _attach_per_candidate_detail(candidate, anomaly, fifth_evidence_detail, "optical_checked", tolerance_m)


def _attach_stability_detail(
    candidate: dict,
    anomaly: dict,
    seventh_evidence_detail: list[dict],
    tolerance_m: float = _PER_CANDIDATE_DETAIL_MATCH_TOLERANCE_M,
) -> None:
    """Sets candidate["stability_score"], candidate["stability_windows_
    detected"], candidate["stability_windows_fetched"], and (when at
    least one offset window detected a match)
    candidate["stability_z_range"] -- added a prior session.

    Unlike _attach_ndvi_detail()/_attach_thermal_detail()/
    _attach_optical_detail() (which set a single boolean via the shared
    _attach_per_candidate_detail() helper), Scientific Steward needs the
    REAL stability_score value (and the real z-range, when available),
    not just a yes/no -- so this uses its own small tight-tolerance
    nearest-match loop instead of reusing that boolean-only helper.

    A candidate with no matching entry in seventh_evidence_detail
    (either because it never qualified for the automatic check, or the
    per-investigation cap meant it was never tested) gets NO stability
    keys set on it at all -- candidate.get("stability_score") will
    correctly return None downstream in _build_steward_report(),
    which is exactly "not tested," never "unstable" (see
    steward_confidence_ceiling.py's own docstring)."""
    best = None
    best_dist = None
    for entry in seventh_evidence_detail:
        try:
            e_point = GeoPoint(entry["lat"], entry["lon"])
            a_point = GeoPoint(anomaly["lat"], anomaly["lon"])
            dist = haversine_distance_m(a_point, e_point)
        except (KeyError, TypeError):
            continue
        if best_dist is None or dist < best_dist:
            best = entry
            best_dist = dist

    if best is None or best_dist is None or best_dist > tolerance_m:
        return  # no matching entry -- leave every stability_* key unset

    candidate["stability_score"] = best.get("stability_score")
    if best.get("n_windows_detected") is not None:
        candidate["stability_windows_detected"] = best["n_windows_detected"]
    if best.get("n_windows_fetched") is not None:
        candidate["stability_windows_fetched"] = best["n_windows_fetched"]
    z_min = best.get("z_min")
    z_max = best.get("z_max")
    if z_min is not None and z_max is not None:
        candidate["stability_z_range"] = (z_min, z_max)


def _build_candidate(
    anomaly: dict,
    correlation_entry: Optional[dict],
    checked_sources: Optional[list[str]] = None,
    original_index: Optional[int] = None,
) -> dict:
    """Builds the candidate dict debate_engine.py consumes.

    candidate["sources"] is set to ONLY this candidate's own
    supporting_sources -- precise, exactly what corroborated THIS
    candidate (already correctly includes OPTICAL whenever
    investigation_multi_mobile.py's _build_correlated_candidates()
    determined it genuinely corroborated this candidate, with no
    changes needed here -- this function already treats
    correlation_entry["supporting_sources"] generically, however many
    real source types it lists). ERT (like GPR) never appears here --
    neither ever participates in correlation(). Detection Stability
    doesn't participate here either, for a different reason -- it
    isn't a corroborating evidence source at all, see this module's own
    docstring, SOURCES-SPLIT FIX note.

    candidate["checked_sources"] carries the whole-run union
    (supporting_sources + checked_sources param, deduplicated) -- read
    by debate_engine.py's _sources_checked_present() (Vegetation/
    Agronomic perspective) and this module's own _build_steward_report()
    below for has_dem/has_ndvi. AS OF THIS SESSION, the caller
    (run_debate_json() below) POST-PROCESSES this field immediately
    after _build_candidate() returns, to correct "NDVI"'s membership
    from whole-run-attempted to per-candidate-succeeded precision (see
    module docstring, NDVI PRECISION FIX) -- this function itself is
    UNCHANGED and still performs the original, simple whole-run merge;
    the precision fix is applied as a deliberate, clearly-marked
    post-processing step in the caller, not folded silently in here, so
    this function's own well-understood behavior stays easy to reason
    about in isolation. Optical does NOT feed into this broader/
    imprecise union at all (even before the caller's post-processing) --
    it uses the precise exact-match _attach_optical_detail() above
    instead, exactly like Thermal. ERT does not feed into it either, for
    the same reason GPR doesn't -- it's read only via its own dedicated
    ert_confirmed/... fields. Detection Stability doesn't feed into it
    either -- it's read only via its own dedicated stability_score/...
    fields, same reasoning.
    """
    candidate: dict[str, Any] = {
        "location": {"lat": anomaly.get("lat"), "lon": anomaly.get("lon")},
    }
    if original_index is not None:
        candidate["id"] = f"#{original_index + 1}"
    if anomaly.get("peak_zscore") is not None:
        candidate["z_score"] = anomaly["peak_zscore"]
    if anomaly.get("peak_residual_m") is not None:
        candidate["elevation_delta_m"] = anomaly["peak_residual_m"]

    supporting_sources = []
    if correlation_entry is not None:
        if correlation_entry.get("status"):
            candidate["correlation_status"] = correlation_entry["status"]
        if correlation_entry.get("supporting_sources"):
            supporting_sources = list(correlation_entry["supporting_sources"])

    if supporting_sources:
        candidate["sources"] = supporting_sources

    merged_sources = list(dict.fromkeys([*supporting_sources, *(checked_sources or [])]))
    if merged_sources:
        candidate["checked_sources"] = merged_sources

    return candidate


def _build_context(investigation: dict) -> dict:
    evidence = investigation.get("evidence") or []
    context: dict[str, Any] = {
        "sources": [e.get("evidence_type") for e in evidence if e.get("evidence_type")],
    }
    ndvi_synth = _ndvi_synthetic_flag(evidence)
    if ndvi_synth is not None:
        context["ndvi_synthetic"] = ndvi_synth
    return context


def _build_steward_report(debate: dict, candidate: dict) -> dict:
    """Scientific Steward Stage 1 wiring. See HONEST MAPPING NOTES (in
    this module's own docstring) for exactly which inputs are real vs.
    deliberately conservative placeholders.

    has_ndvi below needed NO code change for the NDVI PRECISION FIX (see
    module docstring) -- it already reads candidate["checked_sources"],
    which run_debate_json() now corrects for NDVI precision BEFORE this
    function is ever called for that candidate.

    stability_score/stability_windows_detected/stability_windows_fetched/
    stability_z_range are real -- see this module's own docstring,
    HONEST MAPPING NOTES, for exactly what "real" means here (a
    candidate that qualified for and completed the automatic detection-
    stability check this run, via candidate["stability_score"] etc set
    by _attach_stability_detail()). All four default to None for a
    candidate that was never tested -- see steward_confidence_ceiling.py
    for why that must never be treated as "unstable"."""
    checked_sources = candidate.get("checked_sources") or []
    has_dem = "DEM" in checked_sources
    has_ndvi = "NDVI" in checked_sources
    has_gpr = bool(candidate.get("gpr_confirmed"))
    has_thermal = bool(candidate.get("thermal_checked"))
    has_optical = bool(candidate.get("optical_checked"))
    has_ert = bool(candidate.get("ert_confirmed"))

    stability_score = candidate.get("stability_score")
    stability_windows_detected = candidate.get("stability_windows_detected")
    stability_windows_fetched = candidate.get("stability_windows_fetched")
    stability_z_range = candidate.get("stability_z_range")

    synthesis = debate.get("synthesis") or {}
    raw_confidence = float(synthesis.get("leading_confidence") or 0.0)
    agreement_level = synthesis.get("agreement_level", "NO_DATA")
    has_contradiction = agreement_level == "CONTESTED"

    positions = debate.get("positions") or []
    leader_name = synthesis.get("leading_position")
    leader_position = next((p for p in positions if p.get("perspective") == leader_name), None)
    hypothesis = leader_position.get("stance", "") if leader_position else ""
    alternative_hypotheses = [
        p.get("stance", "")
        for p in positions
        if p.get("perspective") != leader_name and not p.get("insufficient_data")
    ]

    z_score = candidate.get("z_score")
    if z_score is not None:
        observation = f"A candidate elevation anomaly (|z|={float(z_score):.2f}) was detected via DEM analysis."
    else:
        observation = "A candidate anomaly was detected."

    steward_note = synthesis.get("steward_note", "")
    candidate_id = debate.get("candidate_id") or "?"

    report = steward_evaluate_candidate(
        candidate_id=str(candidate_id),
        observation=observation,
        has_gps=True,
        has_dem=has_dem,
        has_optical=has_optical,
        has_ndvi=has_ndvi,
        has_gpr=has_gpr,
        has_thermal=has_thermal,
        has_ert=has_ert,
        raw_debate_confidence=raw_confidence,
        has_field_validation=has_gpr,
        environmental_confounders_controlled=False,
        has_contradiction=has_contradiction,
        stability_score=stability_score,
        stability_windows_detected=stability_windows_detected,
        stability_windows_fetched=stability_windows_fetched,
        stability_z_range=stability_z_range,
        interpretation=steward_note,
        hypothesis=hypothesis,
        alternative_hypotheses=alternative_hypotheses,
        debate_summary=steward_note,
        provenance_verified=False,
    )
    return report.as_dict()


def run_debate_json(investigation_json: str) -> str:
    try:
        investigation = json.loads(investigation_json)
        anomalies = investigation.get("anomalies") or []
        correlation = investigation.get("correlation") or []
        evidence = investigation.get("evidence") or []
        second_evidence_detail = investigation.get("second_evidence_detail") or []
        fourth_evidence_detail = investigation.get("fourth_evidence_detail") or []
        fifth_evidence_detail = investigation.get("fifth_evidence_detail") or []
        seventh_evidence_detail = investigation.get("seventh_evidence_detail") or []
        context = _build_context(investigation)

        gpr_item = _gpr_evidence_item(evidence)
        gpr_max_distance_m = _gpr_colocation_distance_m(investigation)
        ert_item = _ert_evidence_item(evidence)
        ert_max_distance_m = _ert_colocation_distance_m(investigation)

        debates = []
        n_skipped_non_dem = 0
        any_gpr_confirmed = False
        any_ert_confirmed = False
        for original_index, anomaly in enumerate(anomalies):
            evidence_type = anomaly.get("evidence_type", "DEM")
            if evidence_type != "DEM":
                n_skipped_non_dem += 1
                continue
            correlation_entry = _nearest_correlation_entry(anomaly, correlation)
            candidate = _build_candidate(anomaly, correlation_entry, context.get("sources"), original_index)
            if _attach_gpr(candidate, anomaly, gpr_item, gpr_max_distance_m):
                any_gpr_confirmed = True
            if _attach_ert(candidate, anomaly, ert_item, ert_max_distance_m):
                any_ert_confirmed = True
            _attach_ndvi_detail(candidate, anomaly, second_evidence_detail)
            _attach_thermal_detail(candidate, anomaly, fourth_evidence_detail)
            _attach_optical_detail(candidate, anomaly, fifth_evidence_detail)
            _attach_stability_detail(candidate, anomaly, seventh_evidence_detail)

            # NDVI PRECISION FIX (this session -- see module docstring):
            # candidate["checked_sources"] was built above from
            # context["sources"], the whole-run union, which includes
            # "NDVI" whenever NDVI was ATTEMPTED this run (an aggregate
            # RealNdviCoreHaloEvidence wrapper is always appended to
            # evidence[] regardless of success/failure) -- not whenever
            # it genuinely succeeded for THIS candidate. Correct it now
            # using the precise candidate["ndvi_checked"] flag just
            # attached above: strip any imprecise "NDVI" entry, then add
            # it back only if NDVI already genuinely corroborated this
            # candidate (candidate["sources"] -- already precise,
            # unaffected by this fix) or this candidate's own real
            # per-candidate check genuinely succeeded (ndvi_checked).
            checked = [s for s in (candidate.get("checked_sources") or []) if s != "NDVI"]
            ndvi_already_corroborating = "NDVI" in (candidate.get("sources") or [])
            if ndvi_already_corroborating or candidate.get("ndvi_checked"):
                checked.append("NDVI")
            if checked:
                candidate["checked_sources"] = checked
            elif "checked_sources" in candidate:
                del candidate["checked_sources"]

            debate = run_debate(candidate, context)

            try:
                debate["steward"] = _build_steward_report(debate, candidate)
            except Exception as steward_exc:
                debate["steward_error"] = str(steward_exc)

            debates.append(debate)

        result: dict[str, Any] = {"debates": debates}
        if n_skipped_non_dem:
            result["note"] = (
                f"{n_skipped_non_dem} NDVI-raster-detected candidate(s) were "
                f"not individually debated -- see debate_mobile.py's SCOPE note."
            )
        if gpr_item is not None and not any_gpr_confirmed:
            result["gpr_note"] = (
                f"Real GPR field-pick evidence was present for this "
                f"investigation, but no DEM candidate was within "
                f"{gpr_max_distance_m:.0f}m of the GPR pick location, so it "
                f"was not applied to any candidate's debate."
            )
        if ert_item is not None and not any_ert_confirmed:
            result["ert_note"] = (
                f"Real ERT field-reading evidence was present for this "
                f"investigation, but no DEM candidate was within "
                f"{ert_max_distance_m:.0f}m of the ERT reading location, so "
                f"it was not applied to any candidate's debate."
            )
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})
