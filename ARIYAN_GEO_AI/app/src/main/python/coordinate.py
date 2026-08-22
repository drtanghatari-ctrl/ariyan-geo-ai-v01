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


@dataclass(frozen=True)
class AreaOfInterest:
    """A regular lat/lon grid centered on the investigation anchor."""
    center: GeoPoint
    radius_m: float
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    grid_size: int          # cells per side
    cell_size_m: float      # approximate ground size of one cell


def meters_per_degree(lat_deg: float) -> tuple[float, float]:
    """Return (meters per degree latitude, meters per degree longitude)
    at a given latitude, using the WGS84 ellipsoid (real formula, not a
    flat-earth approximation)."""
    lat = math.radians(lat_deg)
    sin_lat = math.sin(lat)

    # Radius of curvature in the meridian (N-S) and prime vertical (E-W)
    m = WGS84_A * (1 - WGS84_E2) / (1 - WGS84_E2 * sin_lat ** 2) ** 1.5
    n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat ** 2)

    meters_per_deg_lat = (math.pi / 180) * m
    meters_per_deg_lon = (math.pi / 180) * n * math.cos(lat)
    return meters_per_deg_lat, meters_per_deg_lon


def haversine_distance_m(a: GeoPoint, b: GeoPoint) -> float:
    """Great-circle distance between two points in meters."""
    r = 6371008.8  # mean earth radius, meters
    lat1, lon1 = math.radians(a.lat), math.radians(a.lon)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lon)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def build_aoi(center: GeoPoint, radius_m: float, grid_size: int = 256) -> AreaOfInterest:
    """Build a square area of interest of the given radius (meters) around
    an anchor coordinate, discretized into a grid_size x grid_size grid.

    radius_m is the half-width of the square (distance from center to edge),
    not a circle radius — this matches how DEM tiles are typically requested.
    """
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")
    if grid_size < 8:
        raise ValueError("grid_size must be at least 8 for meaningful terrain analysis")

    m_per_deg_lat, m_per_deg_lon = meters_per_degree(center.lat)

    dlat = radius_m / m_per_deg_lat
    dlon = radius_m / m_per_deg_lon

    min_lat = center.lat - dlat
    max_lat = center.lat + dlat
    min_lon = center.lon - dlon
    max_lon = center.lon + dlon

    cell_size_m = (2 * radius_m) / grid_size

    return AreaOfInterest(
        center=center,
        radius_m=radius_m,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
        grid_size=grid_size,
        cell_size_m=cell_size_m,
    )
