"""
steward_evidence_matrix.py

Scientific Steward -- Stage 1 (Steward Foundation)

Tracks, per investigation, which evidence categories were available,
their quality, whether they were actually used, and any known
limitation. This is the Steward's "what do we actually know, and what
are we missing" awareness layer.

Absence of evidence must never be silently converted into evidence of
absence -- this module makes the gaps explicit and machine-readable
instead of letting them disappear.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EvidenceCategory(Enum):
    """
    The evidence categories ARIYAN can plausibly have per investigation
    today. New categories can be added here as real sources are wired
    in (this list should track real capability, not aspiration).

    NOTE on GPS: the Steward spec lists GPS coordinates as a Level A
    Direct Evidence example, and it is tracked here for completeness/
    audit purposes -- but GPS only locates a candidate, it does not
    corroborate or contradict any hypothesis ABOUT that candidate.
    It is therefore deliberately excluded from
    EvidenceMatrix.independent_used_sources (see below), so it can
    never silently inflate the confidence ceiling.
    """

    GPS = "GPS"
    DEM = "DEM"
    OPTICAL = "OPTICAL_IMAGERY"
    NDVI = "MULTISPECTRAL_NDVI"
    GPR = "GPR"
    THERMAL = "THERMAL"
    LIDAR = "LIDAR"
    ERT = "ERT"


# Categories that count toward "independent evidence supporting/contradicting
# a hypothesis" for confidence-ceiling purposes (both source-count and
# average-quality calculations). GPS is deliberately excluded (see
# EvidenceCategory docstring above) -- it is positional metadata, not
# corroborating content. Exported (not underscore-prefixed) so other
# Steward modules, e.g. steward_confidence_ceiling.py, share this exact
# definition rather than redefining it and risking drift.
CONTENT_EVIDENCE_CATEGORIES = frozenset(
    {
        EvidenceCategory.DEM,
        EvidenceCategory.OPTICAL,
        EvidenceCategory.NDVI,
        EvidenceCategory.GPR,
        EvidenceCategory.THERMAL,
        EvidenceCategory.LIDAR,
        EvidenceCategory.ERT,
    }
)


# ---------------------------------------------------------------------------
# Evidence-independence weighting (ADDED THIS SESSION)
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS: independent_used_sources (below) is a flat, equally-
# weighted count of distinct used content-evidence categories. It cannot
# distinguish a candidate corroborated by NDVI+Thermal+Optical (three
# sources, but all derived from the SAME Sentinel-2/Landsat overpasses
# via the same Copernicus Statistical API -- same acquisition date, same
# atmospheric conditions, same platform) from one corroborated by
# DEM+GPR+ERT (three sources, three genuinely independent measurement
# mechanisms: elevation raster, a human-operated radar pick, a
# human-operated resistivity pick). Both were previously just "3
# independent sources." This section makes that distinction real and
# auditable, without touching independent_used_sources itself (still
# available, unchanged, for anything that already depends on the raw
# count).

# Groups categories that share a common measurement lineage/mechanism.
# LIDAR is given its own group for when/if it is ever built (currently
# unbuilt, never available in this project). GPS is excluded entirely
# (see CONTENT_EVIDENCE_CATEGORIES above) -- it never participates in
# independence weighting either.
INDEPENDENCE_GROUPS: dict[str, frozenset[EvidenceCategory]] = {
    "elevation": frozenset({EvidenceCategory.DEM}),
    "optical_family": frozenset(
        {EvidenceCategory.NDVI, EvidenceCategory.THERMAL, EvidenceCategory.OPTICAL}
    ),
    "field_verification": frozenset({EvidenceCategory.GPR, EvidenceCategory.ERT}),
    "lidar": frozenset({EvidenceCategory.LIDAR}),
}

# Diminishing-returns weight contributed by ONE independence group, keyed
# by how many of that group's categories were actually used. A fixed,
# explicit lookup table (matching this project's existing convention for
# hand-authored bands, e.g. ert_resistivity_model.py's reference bands,
# steward_confidence_ceiling.py's stability thresholds) rather than a
# continuous formula, so every value here is a deliberate, auditable
# choice, not a curve nobody actually decided on.
#
# THE CAP (1.5, for 3+ used categories in one group) IS THE REAL
# MECHANISM: it is deliberately BELOW the 2.0 "genuinely multiple
# independent groups" threshold used in
# steward_confidence_ceiling.compute_confidence_band(). This guarantees
# that no single group -- no matter how many correlated sources it
# stacks -- can ever, by itself, reach the "multiple independent
# sources" tier. Reaching that tier now requires sources from at least
# two DIFFERENT groups, which is the actual definition of independence
# this fix is trying to encode.
_GROUP_WEIGHT_BY_USED_COUNT: dict[int, float] = {
    0: 0.0,
    1: 1.0,
    2: 1.3,
}
_GROUP_WEIGHT_CAP = 1.5  # applied for 3 or more used categories in one group


def _group_weight(used_count: int) -> float:
    if used_count >= 3:
        return _GROUP_WEIGHT_CAP
    return _GROUP_WEIGHT_BY_USED_COUNT.get(used_count, 0.0)


class EvidenceQuality(Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


@dataclass
class EvidenceMatrixEntry:
    category: EvidenceCategory
    available: bool
    quality: EvidenceQuality
    used: bool
    limitation: str  # "-" if none known

    def as_dict(self) -> dict:
        return {
            "category": self.category.value,
            "available": self.available,
            "quality": self.quality.value,
            "used": self.used,
            "limitation": self.limitation,
        }


@dataclass
class EvidenceMatrix:
    entries: list[EvidenceMatrixEntry] = field(default_factory=list)

    def add(
        self,
        category: EvidenceCategory,
        available: bool,
        quality: EvidenceQuality = EvidenceQuality.UNKNOWN,
        used: bool = False,
        limitation: str = "-",
    ) -> None:
        self.entries.append(
            EvidenceMatrixEntry(category, available, quality, used, limitation)
        )

    @property
    def available_count(self) -> int:
        return sum(1 for e in self.entries if e.available)

    @property
    def used_count(self) -> int:
        return sum(1 for e in self.entries if e.used)

    @property
    def total_count(self) -> int:
        return len(self.entries)

    @property
    def independent_used_sources(self) -> int:
        """
        Number of distinct AVAILABLE-AND-USED CONTENT evidence categories
        (i.e. excluding GPS -- see EvidenceCategory docstring). This is
        the RAW, unweighted count -- unchanged by the evidence-
        independence weighting added this session (see
        effective_independent_sources below for the weighted
        alternative). Kept as-is since other code may already depend on
        this exact raw value.
        """
        return sum(
            1
            for e in self.entries
            if e.used and e.category in CONTENT_EVIDENCE_CATEGORIES
        )

    @property
    def effective_independent_sources(self) -> float:
        """
        Evidence-independence-weighted alternative to
        independent_used_sources (ADDED THIS SESSION). Sources that
        share a common measurement lineage (see INDEPENDENCE_GROUPS
        above) are NOT each credited as a full additional independent
        confirmation -- only the first source in a group counts fully,
        with steeply diminishing credit for additional sources in that
        SAME group (see _GROUP_WEIGHT_BY_USED_COUNT above). Sources in
        DIFFERENT groups always add full weight to each other, since
        they represent genuinely distinct measurement mechanisms.

        Because every group's weight is capped BELOW 2.0 (see
        _GROUP_WEIGHT_CAP's own docstring above), a value >= 2.0 here
        can only be reached by using sources from at least two
        different independence groups -- this is what
        steward_confidence_ceiling.py's compute_confidence_band() now
        gates its "genuinely multiple independent sources" tier on,
        in place of the old raw >= 2 check.
        """
        used_by_category = {e.category for e in self.content_used_entries}
        total = 0.0
        for categories in INDEPENDENCE_GROUPS.values():
            used_count = len(used_by_category & categories)
            total += _group_weight(used_count)
        return round(total, 3)

    def independence_breakdown(self) -> list[dict]:
        """
        Per-group breakdown behind effective_independent_sources
        (ADDED THIS SESSION) -- for reasoning-trace text, so a Steward
        explanation can say WHICH sources were discounted and why,
        rather than just showing a single opaque number. Only includes
        groups with at least one used category.
        """
        used_by_category = {e.category for e in self.content_used_entries}
        breakdown = []
        for group_name, categories in INDEPENDENCE_GROUPS.items():
            used_in_group = sorted(c.value for c in (used_by_category & categories))
            if not used_in_group:
                continue
            breakdown.append(
                {
                    "group": group_name,
                    "used_categories": used_in_group,
                    "weight_contributed": _group_weight(len(used_in_group)),
                }
            )
        return breakdown

    @property
    def content_used_entries(self) -> list[EvidenceMatrixEntry]:
        """Used entries restricted to content evidence categories (excludes GPS)."""
        return [
            e for e in self.entries if e.used and e.category in CONTENT_EVIDENCE_CATEGORIES
        ]

    def completeness_pct(self) -> float:
        """
        Fraction of known evidence categories that were available for
        this investigation. This is availability, not usage -- a
        separate "utilization" figure covers whether available evidence
        was actually incorporated.
        """
        if self.total_count == 0:
            return 0.0
        return round(100.0 * self.available_count / self.total_count, 1)

    def missing_categories(self) -> list[EvidenceCategory]:
        return [e.category for e in self.entries if not e.available]

    def as_table(self) -> list[dict]:
        return [e.as_dict() for e in self.entries]


def build_evidence_matrix(
    has_gps: bool,
    has_dem: bool,
    has_optical: bool,
    has_ndvi: bool,
    has_gpr: bool,
    has_thermal: bool = False,
    has_lidar: bool = False,
    has_ert: bool = False,
    quality_hints: dict | None = None,
    used_hints: dict | None = None,
    limitation_hints: dict | None = None,
) -> EvidenceMatrix:
    """
    Build an EvidenceMatrix from plain booleans describing what a real
    investigation actually gathered. `quality_hints`, `used_hints`, and
    `limitation_hints` are optional dicts keyed by EvidenceCategory.value
    (e.g. "DEM") to override the defaults below with real, caller-supplied
    facts about that investigation's data -- never fabricated here.
    """
    quality_hints = quality_hints or {}
    used_hints = used_hints or {}
    limitation_hints = limitation_hints or {}

    matrix = EvidenceMatrix()
    presence = {
        EvidenceCategory.GPS: has_gps,
        EvidenceCategory.DEM: has_dem,
        EvidenceCategory.OPTICAL: has_optical,
        EvidenceCategory.NDVI: has_ndvi,
        EvidenceCategory.GPR: has_gpr,
        EvidenceCategory.THERMAL: has_thermal,
        EvidenceCategory.LIDAR: has_lidar,
        EvidenceCategory.ERT: has_ert,
    }

    for category, available in presence.items():
        key = category.value
        quality = quality_hints.get(key, EvidenceQuality.UNKNOWN if available else EvidenceQuality.UNKNOWN)
        if isinstance(quality, str):
            quality = EvidenceQuality(quality)
        used = used_hints.get(key, available)  # default: if available, assume used unless told otherwise
        limitation = limitation_hints.get(key, "-" if available else "Missing")
        matrix.add(category, available, quality, used, limitation)

    return matrix