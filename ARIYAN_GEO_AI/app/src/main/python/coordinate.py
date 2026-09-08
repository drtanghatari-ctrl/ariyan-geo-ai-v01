"""
coordinate.py — Coordinate Intelligence

Turns a GPS anchor point + investigation radius into a concrete,
georeferenced area of interest (AOI) that downstream modules can use
to request evidence (DEM, imagery, etc.) on a regular grid.

Everything here is real, verifiable geodesy (WGS84 ellipsoid math) —
no placeholders.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

WGS84_A = 6378137.0          # semi-major axis, meters
WGS84_F = 1 / 298.257223563  # flattening
WGS84_B = WGS84_A * (1 - WGS84_F)
WGS84_E2 = 1 - (WGS84_B ** 2) / (WGS84_A ** 2)


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float

    def __post_init__(self):
        if not (-90.0 <= self.lat <= 90.0):
            raise ValueError(f"latitude out of range: {self.lat}")
        if not (-180.0 <= self.lon <= 180.0):
            raise ValueError(f"longitude out of range: {self.lon}")

