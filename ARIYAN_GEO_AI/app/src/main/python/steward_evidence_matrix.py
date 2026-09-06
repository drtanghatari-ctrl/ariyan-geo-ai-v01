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
        (i.e. excluding GPS -- see EvidenceCategory docstring). Used by
        the confidence ceiling as a proxy for dataset independence
        (more independent used content sources = higher permissible
        ceiling). GPS is tracked in the matrix for completeness/audit
        but never counted here, so it can't silently inflate confidence.
        """
        return sum(
            1
            for e in self.entries
            if e.used and e.category in CONTENT_EVIDENCE_CATEGORIES
        )

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