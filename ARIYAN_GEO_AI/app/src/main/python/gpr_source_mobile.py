"""
gpr_source_mobile.py
=====================
GPR (ground-penetrating radar) evidence source for ARIYAN GEO AI --
manual-pick-entry path, plus an explicitly UNIMPLEMENTED device-export
auto-parser.

HONEST STATE (keep this section truthful, don't just delete it):
No GPR hardware has been purchased yet (deferred as a planned future
purchase per project decision -- current pricing was too high). This
file therefore does NOT contain a parser for any specific device's
export format, because writing one without a real export sample to
test against would mean guessing a binary/file format and then
claiming it works -- exactly what this project's hard rule forbids
(no fabricated data, no claimed-but-untested verification).

What IS real and usable today, with no GPR hardware required at all:
MANUAL PICK ENTRY. A human field investigator can read a two-way
travel-time value directly off ANY radargram -- printed, or displayed
live on a rented/borrowed/third-party GPR unit's own screen -- and
type that real number into this app. That is genuine real-world data
collected by a person looking at a real radar return, even though no
particular device's raw export file is being parsed. This module's
GPRSurvey/GPRPick classes and estimate_depths() support exactly that
path now, wired to the real physics in gpr_depth_model.py.

WHAT REMAINS DEFERRED:
parse_gpr_export_file() below is an explicit placeholder. It raises
GPRSourceNotImplementedError rather than guessing a format. When a
real GPR unit is eventually purchased, its actual export format
(CSV, proprietary binary, image dump, etc. -- these vary a great deal
by manufacturer, as previously scoped) should be implemented here
against a REAL sample export file from that specific device, not
before.

NOT YET INTEGRATED INTO THE LIVE INVESTIGATION FLOW: GPREvidence
below is not yet wired into investigation_multi_mobile.py /
build_investigation_record() / debate_mobile.py / MainActivity.kt.
That wiring is meaningful to build once there is at least one real
GPRSurvey (manually entered or device-parsed) to test it against end
to end -- building and merging untested integration code into the
live app would itself risk the same "claimed but not really verified"
problem this project has hit before (see the AI Debate Engine's own
history). Treat this file as a real, usable, but currently STANDALONE
module until that follow-up integration happens.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from gpr_depth_model import DepthEstimate, depth_from_two_way_time, GPRDepthModelError


class GPRSourceNotImplementedError(NotImplementedError):
    """Raised by parse_gpr_export_file(). Never caught-and-faked upstream
    -- callers must surface this honestly (e.g. "automatic import for
    this device isn't built yet; enter picks manually")."""


@dataclass
class GPRPick:
    """One real reflector/hyperbola-apex pick along a survey line --
    the minimal real data either a human reading a radargram, or (in
    the future) an automatic device-export parser, must supply.

    position_m: distance along the survey line from its start (meters).
    two_way_time_ns: the real two-way travel time to the picked
      reflector (nanoseconds), as read directly off the radargram.
    amplitude: optional real reflection amplitude/strength at the pick,
      if the operator recorded or estimated one (used later for a
      peak-amplitude/hyperbola-shape confidence heuristic -- not yet
      implemented; left None until there's real pick data to design
      that heuristic against, per this project's own repeated "first-
      pass rule-based, refine once real data exists" practice).
    note: optional free-text note from the field operator (e.g. "clear
      hyperbola", "ambiguous, possible multiple").
    """
    position_m: float
    two_way_time_ns: float
    amplitude: float | None = None
    note: str = ""


@dataclass
class GPRSurvey:
    """One real GPR survey line (or a single anchored check at one
    point, with a single pick) tied to a specific investigation
    candidate for provenance.

    lat/lon: the real location this survey line is anchored to (e.g.
      a DEM/NDVI candidate's coordinates, for GPR field-verification of
      that specific candidate).
    soil_preset_key: one of gpr_depth_model.SOIL_VELOCITY_PRESETS's
      keys, chosen by the user based on real, known site soil
      conditions -- never defaulted silently, since an unstated soil
      assumption would misrepresent the depth estimate's basis.
    picks: one or more real GPRPick entries (manually entered or, in
      the future, device-parsed).
    entry_method: "manual" (a human read this off a radargram) or
      "device_export" (parsed from a real device's export file). This
      is recorded on the evidence record for provenance -- exactly the
      same spirit as this project's existing synthetic/real flags on
      every other evidence source.
    device_note: optional free-text description of the actual GPR unit
      used (make/model), if known -- useful provenance even without an
      automatic parser for that unit.
    """
    lat: float
    lon: float
    soil_preset_key: str
    picks: list[GPRPick] = field(default_factory=list)
    entry_method: str = "manual"
    device_note: str = ""


def estimate_depths(survey: GPRSurvey) -> list[DepthEstimate]:
    """Convert every real pick in a GPRSurvey into a DepthEstimate using
    gpr_depth_model.py's real velocity/depth physics. Raises
    GPRDepthModelError (propagated) if the survey has no picks, an
    unrecognized soil_preset_key, or any pick's two_way_time_ns is
    invalid -- never silently skips a bad pick."""
    if not survey.picks:
        raise GPRDepthModelError(
            "GPRSurvey has no picks -- nothing to estimate a depth from."
        )
    return [
        depth_from_two_way_time(pick.two_way_time_ns, survey.soil_preset_key)
        for pick in survey.picks
    ]


class GPREvidence:
    """Wrapper matching this project's existing evidence-source
    interface (.source, .synthetic, .as_evidence_record()) -- same
    shape as RealNdviCoreHaloEvidence in investigation_multi_mobile.py.
    NOT YET WIRED into build_investigation_record()/debate_mobile.py --
    see this module's HONEST STATE docstring above."""

    synthetic = False

    def __init__(self, survey: GPRSurvey, depth_estimates: list[DepthEstimate]):
        self.survey = survey
        self.depth_estimates = depth_estimates
        self.source = (
            f"Ground-penetrating radar ({survey.entry_method} pick entry"
            + (f", {survey.device_note}" if survey.device_note else "")
            + ")"
        )

    def as_evidence_record(self) -> dict:
        return {
            "evidence_type": "GPR",
            "source": self.source,
            "synthetic": self.synthetic,
            "entry_method": self.survey.entry_method,
            "soil_preset": self.survey.soil_preset_key,
            "lat": self.survey.lat,
            "lon": self.survey.lon,
            "depth_estimates_m": [
                {
                    "depth_m": round(d.depth_m, 3),
                    "depth_min_m": round(d.depth_min_m, 3),
                    "depth_max_m": round(d.depth_max_m, 3),
                    "two_way_time_ns": d.two_way_time_ns,
                }
                for d in self.depth_estimates
            ],
            "note": (
                "Depth values are ESTIMATES derived from a published "
                "reference soil velocity range, not a precise "
                "measurement -- see gpr_depth_model.py. Not yet "
                "integrated into automated correlation/debate; field-"
                "verification evidence only at this stage."
            ),
        }


def parse_gpr_export_file(raw_bytes: bytes, device_format: str) -> GPRSurvey:
    """Placeholder for future automatic parsing of a real GPR device's
    export file. Deliberately unimplemented -- see this module's HONEST
    STATE docstring. Always raises GPRSourceNotImplementedError; never
    guesses a format or fabricates a GPRSurvey."""
    raise GPRSourceNotImplementedError(
        f"Automatic parsing for device_format={device_format!r} is not "
        f"implemented -- no real GPR hardware/export sample has been "
        f"acquired yet to build and test a parser against. Use manual "
        f"pick entry (GPRSurvey/GPRPick) instead."
    )
