"""
ert_source_mobile.py
======================
ERT (electrical resistivity tomography) evidence source for ARIYAN GEO
AI -- manual-reading-entry path.

HONEST STATE (keep this section truthful, don't just delete it, same
convention as gpr_source_mobile.py):
No ERT hardware has been purchased for this project. This file
therefore does not contain a parser for any specific instrument's raw
survey-line export format. What IS real and usable today, with no ERT
hardware required at all: MANUAL READING ENTRY. A human field
investigator runs an ERT survey with any instrument (borrowed, rented,
or a third party's), inverts it with standard inversion software
(RES2DINV, AGI EarthImager, etc. -- outside this app), reads a real
resistivity value (ohm-meters) directly off that inverted profile at a
specific, already-known depth, and types both numbers into this app.
That is genuine real-world data collected by a person reading a real
inverted resistivity section, even though no particular device's raw
export file is being parsed. This module's ERTSurvey/ERTReading
classes and classify_survey() support exactly that path now, wired to
the real reference-range classification in ert_resistivity_model.py.

WHAT REMAINS DEFERRED: an automatic parser for any specific ERT
instrument's raw survey-line export (as opposed to a human-read,
already-inverted value) is not built -- there is no real export sample
to build and test one against yet. See ERTSourceNotImplementedError
below, reserved for that future work, mirroring
GPRSourceNotImplementedError's own reasoning exactly.

WIRED INTO THE LIVE INVESTIGATION FLOW (unlike gpr_source_mobile.py's
own HONEST STATE note about GPREvidence, which describes GPR's classes
as standalone): ERTEvidence below IS wired end-to-end into
investigation_multi_mobile.py's _build_ert_evidence() /
build_investigation_record() / debate_mobile.py / (MainActivity.kt UI
entry to follow), because it is being built as a direct architectural
mirror of how GPR is ACTUALLY invoked in this project today -- a
single real manual reading anchored at the investigation's own
(lat, lon), exactly like GPR's own actual (not its module docstring's
stale, more cautious) usage.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ert_resistivity_model import (
    ResistivityBand,
    classify_resistivity,
    overall_lean,
    ERTResistivityModelError,
)


class ERTSourceNotImplementedError(NotImplementedError):
    """Reserved for a future real ERT-instrument raw-export parser.
    Never raised by anything in this module today -- this module only
    supports the real manual-reading-entry path (see module docstring).
    Kept here, unused, so a future device-export parser has an obvious,
    already-named place to raise from, mirroring
    gpr_source_mobile.GPRSourceNotImplementedError's own reasoning."""


@dataclass
class ERTReading:
    """One real resistivity reading, already read by a human off an
    already-inverted ERT profile at a known depth -- the minimal real
    data this path needs.

    resistivity_ohm_m: the real resistivity value (ohm-meters) read
      directly off the inverted profile/pseudo-section.
    depth_m: the real depth (meters below ground surface) at which that
      resistivity value applies, as reported by the inversion software
      -- recorded for provenance/reporting; it does NOT itself change
      which reference band(s) the resistivity value is classified into
      (see ert_resistivity_model.py's own docstring -- classification
      is against fixed, depth-independent material bands, not a
      depth-adjusted model; this project does not have the real data
      needed to build a depth-adjusted reference table honestly).
    note: optional free-text note from the field operator (e.g.
      "clear high-resistivity anomaly", "noisy line, low confidence").
    """
    resistivity_ohm_m: float
    depth_m: float
    note: str = ""


@dataclass
class ERTSurvey:
    """One real ERT reading (or, in principle, several) tied to a
    specific investigation for provenance -- mirrors GPRSurvey's own
    shape exactly.

    lat/lon: the real location this reading is anchored to (e.g. a DEM
      candidate's coordinates, for ERT field-verification of that
      specific candidate).
    readings: one or more real ERTReading entries. Only the FIRST
      reading is currently used end-to-end by ERTEvidence.
      as_evidence_record() below -- this mirrors how GPRSurvey/GPRPick
      are actually invoked in investigation_multi_mobile.py today (a
      single pick per investigation), even though the dataclass itself
      is written generally enough to hold more than one, exactly as
      GPRSurvey already does.
    entry_method: "manual" (a human read this off an inverted profile)
      -- recorded on the evidence record for provenance, same spirit as
      every other evidence source's synthetic/real flag.
    device_note: optional free-text description of the actual ERT
      instrument/inversion software used, if known.
    """
    lat: float
    lon: float
    readings: list[ERTReading] = field(default_factory=list)
    entry_method: str = "manual"
    device_note: str = ""


@dataclass
class ClassifiedERTReading:
    reading: ERTReading
    matched_bands: list[ResistivityBand]
    lean: str  # "natural" | "anthropogenic" | "ambiguous"


def classify_survey(survey: ERTSurvey) -> list[ClassifiedERTReading]:
    """Classify every real reading in an ERTSurvey against
    ert_resistivity_model.py's real reference bands. Raises
    ERTResistivityModelError (propagated) if the survey has no
    readings, or any reading's resistivity_ohm_m is invalid -- never
    silently skips a bad reading."""
    if not survey.readings:
        raise ERTResistivityModelError(
            "ERTSurvey has no readings -- nothing to classify."
        )
    out: list[ClassifiedERTReading] = []
    for reading in survey.readings:
        bands = classify_resistivity(reading.resistivity_ohm_m)
        out.append(ClassifiedERTReading(
            reading=reading,
            matched_bands=bands,
            lean=overall_lean(bands),
        ))
    return out


class ERTEvidence:
    """Wrapper matching this project's existing evidence-source
    interface (.source, .synthetic, .as_evidence_record()) -- same
    shape as GPREvidence in gpr_source_mobile.py. Wired into
    evidence_record.py's sixth_evidence slot (single, site-anchored --
    not per-candidate, exactly like GPR's third_evidence)."""

    synthetic = False

    def __init__(self, survey: ERTSurvey, classified: list[ClassifiedERTReading]):
        self.survey = survey
        self.classified = classified
        self.source = (
            f"Electrical resistivity tomography ({survey.entry_method} "
            f"reading entry"
            + (f", {survey.device_note}" if survey.device_note else "")
            + ")"
        )

    def as_evidence_record(self) -> dict:
        # Only the first reading is used end-to-end today -- see
        # ERTSurvey's own docstring for why (mirrors GPR's actual,
        # single-pick wiring in investigation_multi_mobile.py).
        first = self.classified[0] if self.classified else None
        resistivity_ohm_m = None
        depth_m = None
        overall = None
        matched_bands: list[dict] = []
        if first is not None:
            resistivity_ohm_m = first.reading.resistivity_ohm_m
            depth_m = first.reading.depth_m
            overall = first.lean
            matched_bands = [
                {
                    "key": b.key,
                    "label": b.label,
                    "ohm_m_min": b.ohm_m_min,
                    "ohm_m_max": b.ohm_m_max,
                    "lean": b.lean,
                }
                for b in first.matched_bands
            ]
        return {
            "evidence_type": "ERT",
            "source": self.source,
            "synthetic": self.synthetic,
            "entry_method": self.survey.entry_method,
            "lat": self.survey.lat,
            "lon": self.survey.lon,
            "resistivity_ohm_m": resistivity_ohm_m,
            "depth_m": depth_m,
            "matched_bands": matched_bands,
            "overall_lean": overall,
            "note": (
                "Classification is against fixed, documented reference "
                "resistivity ranges (see ert_resistivity_model.py), not a "
                "site-calibrated inversion -- several real materials "
                "genuinely overlap in resistivity, and where a reading "
                "matches more than one band, 'overall_lean' honestly "
                "reports that ambiguity ('ambiguous') rather than forcing "
                "a single natural/anthropogenic interpretation."
            ),
        }
