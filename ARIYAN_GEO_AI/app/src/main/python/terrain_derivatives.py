"""
terrain_derivatives.py — Derived Evidence: slope, aspect, hillshade, curvature

Standard Horn (1981) finite-difference formulas, the same ones used by
GDAL/ArcGIS/QGIS. These are DERIVED evidence, not direct evidence: they
carry no new information beyond what's already in the DEM, only make
patterns in it visible. That distinction is preserved by tagging every
output with derived_from + method.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from dem_source import DEM


@dataclass
class DerivedRaster:
    values: np.ndarray
    derived_from: str      # DEM.source
    method: str             # formula/algorithm name
    units: str


def _horn_gradients(z: np.ndarray, cell_size_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Horn (1981) 3x3 weighted finite-difference gradient estimate.
    Returns (dz/dx, dz/dy) in units of rise/run (dimensionless)."""
    # Pad by edge-replication so the 3x3 kernel is defined at borders.
    zp = np.pad(z, 1, mode="edge")

    z1 = zp[0:-2, 0:-2]; z2 = zp[0:-2, 1:-1]; z3 = zp[0:-2, 2:]
    z4 = zp[1:-1, 0:-2];                       z6 = zp[1:-1, 2:]
    z7 = zp[2:, 0:-2];   z8 = zp[2:, 1:-1];    z9 = zp[2:, 2:]

    dzdx = ((z3 + 2 * z6 + z9) - (z1 + 2 * z4 + z7)) / (8 * cell_size_m)
    dzdy = ((z7 + 2 * z8 + z9) - (z1 + 2 * z2 + z3)) / (8 * cell_size_m)
    return dzdx, dzdy


def compute_slope_deg(dem: DEM) -> DerivedRaster:
    dzdx, dzdy = _horn_gradients(dem.elevation_m, dem.resolution_m)
    slope_rad = np.arctan(np.sqrt(dzdx ** 2 + dzdy ** 2))
    slope_deg = np.degrees(slope_rad)
    return DerivedRaster(slope_deg, dem.source, "Horn(1981) 3x3 finite difference", "degrees")


def compute_aspect_deg(dem: DEM) -> DerivedRaster:
    """Compass aspect: 0=North, 90=East, 180=South, 270=West.
    Flat cells (near-zero gradient) are set to -1 (undefined), matching
    standard GIS convention."""
    dzdx, dzdy = _horn_gradients(dem.elevation_m, dem.resolution_m)
    aspect_rad = np.arctan2(dzdy, -dzdx)
    aspect_deg = np.degrees(aspect_rad)
    aspect_deg = (90.0 - aspect_deg) % 360.0

    flat = (np.abs(dzdx) < 1e-9) & (np.abs(dzdy) < 1e-9)
    aspect_deg = np.where(flat, -1.0, aspect_deg)
    return DerivedRaster(aspect_deg, dem.source, "Horn(1981) 3x3 finite difference", "degrees")


def compute_hillshade(dem: DEM, azimuth_deg: float = 315.0, altitude_deg: float = 45.0) -> DerivedRaster:
    """Standard analytical hillshade (same formula as GDAL's gdaldem hillshade)."""
    dzdx, dzdy = _horn_gradients(dem.elevation_m, dem.resolution_m)
    slope_rad = np.arctan(np.sqrt(dzdx ** 2 + dzdy ** 2))

    aspect_rad = np.arctan2(dzdy, -dzdx)

    az_rad = math.radians(360.0 - azimuth_deg + 90.0)
    alt_rad = math.radians(altitude_deg)

    shade = (np.sin(alt_rad) * np.cos(slope_rad)
             + np.cos(alt_rad) * np.sin(slope_rad) * np.cos(az_rad - aspect_rad))
    shade = np.clip(shade, 0, 1) * 255.0
    return DerivedRaster(shade, dem.source, "gdaldem-equivalent analytical hillshade", "0-255")


def compute_profile_curvature(dem: DEM) -> DerivedRaster:
    """Second-derivative curvature (Zevenbergen & Thorne 1987, simplified).
    Positive = convex (ridge-like), negative = concave (channel-like).
    Useful because subtle buried linear features often show as thin
    curvature anomalies before they're visible in slope or hillshade."""
    z = dem.elevation_m
    cs = dem.resolution_m
    zp = np.pad(z, 1, mode="edge")

    z_n = zp[0:-2, 1:-1]; z_s = zp[2:, 1:-1]
    z_e = zp[1:-1, 2:]; z_w = zp[1:-1, 0:-2]
    z_c = zp[1:-1, 1:-1]

    d2zdx2 = (z_e - 2 * z_c + z_w) / (cs ** 2)
    d2zdy2 = (z_n - 2 * z_c + z_s) / (cs ** 2)
    curvature = -(d2zdx2 + d2zdy2)  # negative sign: convention where ridges are positive
    return DerivedRaster(curvature, dem.source, "Zevenbergen-Thorne (simplified)", "1/m")
