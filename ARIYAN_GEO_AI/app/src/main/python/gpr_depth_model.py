"""
gpr_depth_model.py
===================
Ground-penetrating-radar depth conversion physics for ARIYAN GEO AI.

WHY THIS FILE EXISTS INDEPENDENTLY OF ANY GPR HARDWARE:
Roadmap item (4), depth estimation, has two genuinely separate parts:
  1. The PHYSICS of converting a two-way radar travel time into a depth
     estimate (this file) -- pure arithmetic driven by a soil-type
     electromagnetic wave velocity, a real, well-published relationship
     that does not require owning any specific GPR device to implement
     or reason about correctly.
  2. Getting real two-way-travel-time picks INTO that formula in the
     first place (gpr_source_mobile.py) -- which for automatic device
     parsing DOES depend on a specific unit's export format.

This project's own hard rule is to never fabricate data or claim
untested verification. Part 1 can be built and reasoned about honestly
right now using real, standard, widely-published GPR velocity figures.
Part 2 cannot yet be built as an automatic device parser (no GPR unit
has been purchased -- see project history/HANDOFF.md), so
gpr_source_mobile.py instead supports a real MANUAL PICK entry path
(a human reading two-way-times directly off any radargram, printed or
on a device's own screen) that needs no specific device integration at
all and is genuinely usable today.

SOIL VELOCITY PRESETS:
The values in SOIL_VELOCITY_PRESETS are commonly-published approximate
electromagnetic wave velocity RANGES for GPR, as reproduced across
standard references (e.g. Daniels, "Ground Penetrating Radar", 2nd ed.;
Conyers, "Ground-Penetrating Radar for Archaeology"). They are real,
citable reference figures -- not measurements this app has itself taken
-- and vary meaningfully with actual soil moisture, porosity, and
composition at any real site. Exactly like this project's existing NDVI
halo/core approximation (halo bbox geometrically includes the core
rather than a true annulus, documented rather than hidden), this table
is a DOCUMENTED APPROXIMATION: a reasonable default when no site-
specific velocity calibration (e.g. a common-midpoint survey, or a
known-depth reference target) is available, not a claim of precision.
Every depth estimate derived from these presets carries an explicit
min/max range reflecting the preset's own published range, and every
consumer of DepthEstimate must treat depth_m as a midpoint estimate,
not a precise measurement.
"""
from __future__ import annotations

from dataclasses import dataclass

# Speed of light in a vacuum, in m/ns (used only as the reference point
# for "air", included for completeness/sanity-checking, not because a
# subsurface survey would ever use it).
C_VACUUM_M_PER_NS = 0.2998


@dataclass(frozen=True)
class SoilVelocityPreset:
    key: str
    label: str
    v_min_m_per_ns: float
    v_typical_m_per_ns: float
    v_max_m_per_ns: float
    notes: str


# Commonly-published approximate GPR velocity ranges by material/soil
# type. See module docstring: real, citable, standard reference figures
# -- not site-specific measurements. Ordered roughly wet-to-dry within
# related groups for readability only; order has no semantic meaning.
SOIL_VELOCITY_PRESETS: dict[str, SoilVelocityPreset] = {
    "air": SoilVelocityPreset(
        "air", "Air (reference only)",
        C_VACUUM_M_PER_NS, C_VACUUM_M_PER_NS, C_VACUUM_M_PER_NS,
        "Included for sanity-checking calibration surveys, not a real "
        "subsurface medium.",
    ),
    "fresh_water": SoilVelocityPreset(
        "fresh_water", "Fresh water",
        0.030, 0.033, 0.036,
        "High dielectric permittivity (~80) makes water by far the "
        "slowest common medium; standing water in a survey area strongly "
        "dominates travel time.",
    ),
    "dry_sand": SoilVelocityPreset(
        "dry_sand", "Dry sand",
        0.12, 0.135, 0.15,
        "One of the most GPR-favorable dry soils (low attenuation, "
        "good penetration).",
    ),
    "saturated_sand": SoilVelocityPreset(
        "saturated_sand", "Saturated / wet sand",
        0.05, 0.055, 0.06,
        "Water content dominates over the sand matrix itself.",
    ),
    "dry_clay": SoilVelocityPreset(
        "dry_clay", "Dry clay",
        0.08, 0.09, 0.10,
        "Clay is highly variable and often the worst GPR medium even "
        "dry (high attenuation); treat this range with extra caution.",
    ),
    "saturated_clay": SoilVelocityPreset(
        "saturated_clay", "Saturated / wet clay",
        0.04, 0.05, 0.06,
        "Very high attenuation in addition to slow velocity -- real "
        "penetration depth may be shallow regardless of this velocity "
        "figure.",
    ),
    "silt_dry": SoilVelocityPreset(
        "silt_dry", "Dry silt",
        0.09, 0.105, 0.12,
        "Intermediate between sand and clay.",
    ),
    "loam_dry": SoilVelocityPreset(
        "loam_dry", "Dry loam / mixed agricultural soil",
        0.07, 0.085, 0.10,
        "Common archaeological-survey topsoil; real value depends "
        "heavily on organic content and moisture at time of survey.",
    ),
    "limestone": SoilVelocityPreset(
        "limestone", "Limestone (dry)",
        0.11, 0.12, 0.13,
        "Karst/void features can locally violate this range severely; "
        "treat with caution in known karst terrain.",
    ),
    "granite": SoilVelocityPreset(
        "granite", "Granite / crystalline bedrock (dry)",
        0.10, 0.115, 0.13,
        "",
    ),
    "concrete_dry": SoilVelocityPreset(
        "concrete_dry", "Concrete / masonry (dry)",
        0.10, 0.115, 0.13,
        "Useful when a candidate is suspected to involve a constructed "
        "masonry feature rather than natural soil.",
    ),
    "ice": SoilVelocityPreset(
        "ice", "Ice / permafrost",
        0.15, 0.16, 0.17,
        "",
    ),
}


def list_soil_presets() -> list[dict]:
    """UI-facing listing (e.g. for a dropdown), key+label only."""
    return [
        {"key": p.key, "label": p.label}
        for p in SOIL_VELOCITY_PRESETS.values()
    ]


@dataclass
class DepthEstimate:
    two_way_time_ns: float
    soil_preset_key: str
    soil_preset_label: str
    depth_m: float
    depth_min_m: float
    depth_max_m: float
    is_estimate: bool = True  # always True; never remove this flag


class GPRDepthModelError(Exception):
    """Raised for invalid inputs (unknown soil preset, negative/zero
    travel time, etc). Never silently clamps or guesses a substitute
    value."""


def depth_from_two_way_time(
    two_way_time_ns: float,
    soil_preset_key: str,
) -> DepthEstimate:
    """Convert a real two-way radar travel time (nanoseconds, as read or
    picked from a radargram) into an estimated depth using the standard
    GPR relationship depth = velocity * two_way_time / 2.

    Returns a DepthEstimate whose depth_m is the midpoint using the
    preset's v_typical, and depth_min_m/depth_max_m bracket the preset's
    own published v_min/v_max -- an explicit uncertainty range, not a
    single precise number, matching this project's existing honesty
    conventions for approximated evidence (see module docstring).

    Raises GPRDepthModelError if two_way_time_ns is not a positive
    number, or soil_preset_key is not a recognized key in
    SOIL_VELOCITY_PRESETS (never silently substitutes a default soil).
    """
    if two_way_time_ns is None or two_way_time_ns <= 0:
        raise GPRDepthModelError(
            f"two_way_time_ns must be a positive number, got "
            f"{two_way_time_ns!r}."
        )
    preset = SOIL_VELOCITY_PRESETS.get(soil_preset_key)
    if preset is None:
        raise GPRDepthModelError(
            f"Unknown soil_preset_key {soil_preset_key!r}. Valid keys: "
            f"{sorted(SOIL_VELOCITY_PRESETS.keys())}."
        )

    depth_m = preset.v_typical_m_per_ns * two_way_time_ns / 2.0
    depth_min_m = preset.v_min_m_per_ns * two_way_time_ns / 2.0
    depth_max_m = preset.v_max_m_per_ns * two_way_time_ns / 2.0

    return DepthEstimate(
        two_way_time_ns=two_way_time_ns,
        soil_preset_key=preset.key,
        soil_preset_label=preset.label,
        depth_m=depth_m,
        depth_min_m=depth_min_m,
        depth_max_m=depth_max_m,
    )
