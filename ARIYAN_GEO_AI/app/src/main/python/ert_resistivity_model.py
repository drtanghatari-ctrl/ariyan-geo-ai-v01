"""
ert_resistivity_model.py
==========================
Electrical Resistivity Tomography (ERT) reference-range classification
physics for ARIYAN GEO AI.

WHY THIS FILE EXISTS INDEPENDENTLY OF ANY ERT HARDWARE:
Same reasoning as gpr_depth_model.py (see that file's own docstring):
no ERT hardware has been purchased for this project. This file can
still be built and reasoned about honestly right now, because
classifying a resistivity reading against real, published reference
ranges does not require owning any specific ERT instrument -- only the
real value itself, which a human reads directly off an already-
INVERTED resistivity profile / pseudo-section (produced by dedicated
inversion software such as RES2DINV or AGI EarthImager, outside this
app) at a specific, already-known depth.

HOW THIS DIFFERS ARCHITECTURALLY FROM gpr_depth_model.py:
GPR's model converts a raw measurement (two-way travel time) into a
derived quantity (depth) via a chosen soil velocity -- a DEPTH
CONVERSION model. ERT's real-world workflow already produces depth
directly as part of the inversion process the human performs before
ever opening this app. This model's job is therefore NOT depth
conversion -- it is CLASSIFICATION: given a real resistivity value
(ohm-meters) already read at a known depth, which reference material
band(s) does it plausibly fall into?

REFERENCE RANGES:
The bands in RESISTIVITY_BANDS are commonly-published approximate DC
resistivity ranges for common natural and anthropogenic subsurface
materials, as reproduced across standard archaeogeophysics references
(e.g. Reynolds, "An Introduction to Applied and Environmental
Geophysics", 2nd ed.; Clark, "Seeing Beneath the Soil"; Palacky's 1987
resistivity compilation). They are real, citable reference figures --
not measurements this app has itself taken -- and, exactly like
gpr_depth_model.py's soil velocity presets, they are a DOCUMENTED
APPROXIMATION, not a claim of precision.

HONEST, DELIBERATE AMBIGUITY -- READ BEFORE "FIXING" THE OVERLAPS:
Several of these bands genuinely, legitimately overlap in real-world
resistivity: compacted anthropogenic fill/masonry and natural dry
sand/weathered bedrock occupy much the same range; an air-filled void
could be a natural karst cavity or a human-made tomb/tunnel/cellar; a
water-filled void could be a natural saturated pocket or a flooded
anthropogenic chamber. This is a REAL, well-known limitation of
single-value DC resistivity interpretation (site context -- known
local geology, GPR/other corroboration -- is what normally resolves
it), not a gap in this model. classify_resistivity() therefore
deliberately returns EVERY band a value plausibly matches (never just
the "best" one), and overall_lean() honestly reports "ambiguous" rather
than forcing a single natural/anthropogenic call whenever the matched
bands don't agree. Every consumer of this module's output must treat
that as real, reportable ambiguity, not a defect to average away.

WHY "conductive_metal" IS LABELED "ambiguous", NOT "anthropogenic"
(decided 2026-09-08, see the module's git history / HANDOFF.md for the
full discussion that led here):
An earlier version of this file labeled conductive_metal's lean as
"anthropogenic", on the reasoning that very low resistivity (0-10
ohm-m) is typical of buried metal (rebar, pipes, metal artifacts).
That claim does not survive scrutiny against the same standard
references this file already cites: saline groundwater and saline
clay can genuinely read below 10 ohm-m (published field-calibrated
studies report saline clay as low as <5 ohm-m, and fresh-water-bearing
clay <15 ohm-m), and even non-saline, fully natural saturated fine
sediment (e.g. saturated loess) has been directly measured at ~10
ohm-m with no salinity or metal involved at all. There is no floor
below which "it must be metal, not natural saturated ground" holds --
as salinity rises, natural material resistivity can drop arbitrarily
low (seawater itself is ~0.2 ohm-m). So water_filled_void's overlap
with conductive_metal's full range is not a bug to fix by narrowing
the bands -- narrowing them would mean inventing a boundary the
literature does not support, exactly the kind of fabricated precision
this project's evidence sources must never produce.
The only real, physics-based way to add trustworthy discriminating
power here is a second, independent method -- magnetometry is the
standard one: ferrous metal produces a genuine magnetic dipole
anomaly that plain water/void/clay does not, so it can make a clean
metal call that resistivity alone cannot. Induced Polarization
(chargeability) was also considered and rejected for this file: it CAN
rule out a plain water-filled void (water has no polarization
mechanism), but it cannot cleanly separate metal from clay (both
polarize, via different mechanisms -- electrode polarization for
metal, membrane polarization for clay), and it has no universal
numeric reference table the way resistivity does (chargeability units
and typical values vary by instrument, with no standard equivalent to
RESISTIVITY_BANDS). Building either path into this app now, without
owning the hardware or a confirmed real data source, would repeat the
mistake this project has deliberately avoided elsewhere (see LiDAR:
parked indefinitely, no real data source, never built speculatively).
So: conductive_metal is honestly "ambiguous", overall_lean() currently
can never return "anthropogenic" from any resistivity value in this
model, and that is a correct, permanent statement about what a single
DC resistivity reading can tell you -- not an open bug. It only
changes if a magnetometer (or other independent method) is added as a
genuinely new evidence source, which is not currently planned/owned.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResistivityBand:
    key: str
    label: str
    ohm_m_min: float
    ohm_m_max: float | None  # None = open-ended upper bound
    lean: str  # "natural" | "anthropogenic" | "ambiguous"
    notes: str


# Commonly-published approximate DC resistivity ranges by
# material/feature type. See module docstring: real, citable, standard
# reference figures -- not site-specific measurements. `lean` is this
# model's own interpretive judgment of which explanation a reading in
# this band, ON ITS OWN, tends to support -- "ambiguous" where the real
# range itself spans both natural and constructed possibilities (see
# module docstring's HONEST, DELIBERATE AMBIGUITY section).
RESISTIVITY_BANDS: dict[str, ResistivityBand] = {
    "conductive_metal": ResistivityBand(
        "conductive_metal", "Metal / highly conductive material (metal or saline/saturated ground)",
        0.0, 10.0, "ambiguous",
        "Buried metal objects, rebar, pipes, or similarly conductive "
        "man-made material CAN read this low -- but so can purely "
        "natural saline groundwater, saline clay, or ordinary saturated "
        "fine sediment (published field studies report natural material "
        "reading well below 10 ohm-m with no metal or human activity "
        "involved). Resistivity alone cannot distinguish these -- see "
        "module docstring's note on why this band is not labeled "
        "anthropogenic. A magnetometer reading (not currently an "
        "evidence source in this app) is the real, trustworthy way to "
        "confirm metal specifically.",
    ),
    "water_filled_void": ResistivityBand(
        "water_filled_void", "Water-filled void / saturated conductive fill",
        0.0, 30.0, "ambiguous",
        "Standing water in a cavity or highly saturated fill reads very "
        "low. Could be a natural saturated pocket/karst feature or a "
        "flooded anthropogenic chamber (cistern, tomb, cellar) -- "
        "resistivity alone cannot distinguish these.",
    ),
    "wet_clay_silt": ResistivityBand(
        "wet_clay_silt", "Wet clay / saturated silt",
        10.0, 100.0, "natural",
        "Common natural background in fine-grained saturated ground.",
    ),
    "saturated_sand_gravel": ResistivityBand(
        "saturated_sand_gravel", "Saturated sand / gravel",
        20.0, 200.0, "natural",
        "Common natural background where the water table is shallow.",
    ),
    "compacted_fill_masonry": ResistivityBand(
        "compacted_fill_masonry", "Compacted fill / stone-brick-mortar foundation",
        200.0, 2000.0, "ambiguous",
        "GENUINELY AMBIGUOUS BAND: this range overlaps natural dry "
        "sand/gravel and weathered bedrock as well as constructed "
        "masonry or compacted anthropogenic fill. Resistivity alone "
        "cannot distinguish these -- see module docstring.",
    ),
    "dry_sand_gravel_weathered_bedrock": ResistivityBand(
        "dry_sand_gravel_weathered_bedrock", "Dry sand/gravel / weathered bedrock",
        200.0, 1000.0, "natural",
        "Common natural dry background; overlaps compacted_fill_masonry's "
        "range (see that band's own notes).",
    ),
    "solid_bedrock": ResistivityBand(
        "solid_bedrock", "Solid, unweathered bedrock (limestone, granite)",
        1000.0, None, "natural",
        "Very high resistivity, essentially insulating; overlaps "
        "air_filled_void's range at the low end.",
    ),
    "air_filled_void": ResistivityBand(
        "air_filled_void", "Air-filled void (cavity, tomb, tunnel)",
        2000.0, None, "ambiguous",
        "Very high resistivity, often the highest reading in a survey. "
        "Could be a natural karst cavity or a human-made tomb/tunnel/"
        "cellar -- context (known local geology, GPR or other "
        "corroboration) is needed to distinguish these, not resistivity "
        "alone.",
    ),
}


def list_resistivity_bands() -> list[dict]:
    """UI-facing listing (e.g. for a reference table display), not used
    to drive classification (classify_resistivity() checks every band
    itself; a human does not pick one)."""
    return [
        {"key": b.key, "label": b.label, "ohm_m_min": b.ohm_m_min,
         "ohm_m_max": b.ohm_m_max, "lean": b.lean}
        for b in RESISTIVITY_BANDS.values()
    ]


class ERTResistivityModelError(Exception):
    """Raised for invalid inputs (non-positive resistivity, etc). Never
    silently clamps or guesses a substitute value."""


def classify_resistivity(resistivity_ohm_m: float) -> list[ResistivityBand]:
    """Return EVERY reference band whose real published range contains
    resistivity_ohm_m (a real value the user read off an already-
    inverted ERT profile at a known depth), sorted by ohm_m_min
    ascending. Deliberately returns all matches, not just one -- see
    module docstring, HONEST, DELIBERATE AMBIGUITY.

    Raises ERTResistivityModelError if resistivity_ohm_m is not a
    positive number (resistivity cannot be zero or negative for a real
    material). Returning an empty list is not currently possible given
    RESISTIVITY_BANDS' coverage (every positive value matches at least
    one band), but callers should not assume that will always remain
    true if bands are edited later.
    """
    if resistivity_ohm_m is None or resistivity_ohm_m <= 0:
        raise ERTResistivityModelError(
            f"resistivity_ohm_m must be a positive number, got "
            f"{resistivity_ohm_m!r}."
        )
    matches = [
        band for band in RESISTIVITY_BANDS.values()
        if resistivity_ohm_m >= band.ohm_m_min
        and (band.ohm_m_max is None or resistivity_ohm_m <= band.ohm_m_max)
    ]
    return sorted(matches, key=lambda b: b.ohm_m_min)


def overall_lean(bands: list[ResistivityBand]) -> str:
    """Combine the lean of every matched band into one honest overall
    judgment:
      - "natural" only if EVERY matched band leans natural
      - "anthropogenic" only if EVERY matched band leans anthropogenic
      - "ambiguous" otherwise (no matches, any band itself ambiguous, or
        matched bands disagree -- e.g. one natural-leaning and one
        anthropogenic-leaning band both matched)

    This is deliberately conservative: a reading that plausibly matches
    both a natural and an anthropogenic band is genuinely ambiguous and
    must not be forced toward either interpretation.

    NOTE (2026-09-08): with the current RESISTIVITY_BANDS, no band is
    labeled "anthropogenic" (see conductive_metal's notes and the
    module docstring's "WHY conductive_metal IS LABELED ambiguous"
    section) -- so this function currently can never return
    "anthropogenic" for any input. That is intentional and correct,
    not a bug: it reflects that a single DC resistivity reading, on its
    own, cannot trustworthily confirm anthropogenic origin. The logic
    below is left exactly as originally written (untouched) so that if
    a future evidence source (e.g. magnetometry) ever justifies adding
    a real anthropogenic-leaning band, "anthropogenic" becomes
    reachable again with zero changes needed here.
    """
    if not bands:
        return "ambiguous"
    leans = {b.lean for b in bands}
    if leans == {"natural"}:
        return "natural"
    if leans == {"anthropogenic"}:
        return "anthropogenic"
    return "ambiguous"