"""
anomaly_detection.py — Local-relief anomaly detection

Philosophy: a DEM anomaly is not "buried treasure" — it is a location
where local elevation deviates from the surrounding regional trend by
more than would be expected from natural terrain roughness. That's it.
This module makes exactly that claim, with a number attached, and
nothing more.

Method (standard in archaeological micro-relief analysis):
  1. Remove the regional trend with a large-kernel Gaussian low-pass
     filter (the "regional surface").
  2. residual = elevation - regional_surface  (this is the local relief)
  3. z-score the residual against the AOI's own local statistics.
  4. Flag cells above a threshold; group into connected candidate
     features; report each with location, size, and an amplitude —
     never a verdict about what caused it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from dem_source import DEM
from coordinate import GeoPoint, meters_per_degree


@dataclass
class AnomalyCandidate:
    row: int
    col: int
    lat: float
    lon: float
    area_cells: int
    peak_residual_m: float
    mean_residual_m: float
    peak_zscore: float
    polarity: str  # "positive" (raised) or "negative" (depressed)


def _regional_surface(elevation: np.ndarray, kernel_sigma_cells: float) -> np.ndarray:
    """Low-pass filtered elevation = the 'regional trend' to compare against."""
    return ndimage.gaussian_filter(elevation, sigma=kernel_sigma_cells, mode="nearest")


def compute_residual_relief(dem: DEM, kernel_sigma_cells: float = 12.0) -> np.ndarray:
    """Elevation minus its own regional trend — i.e. local micro-relief."""
    regional = _regional_surface(dem.elevation_m, kernel_sigma_cells)
    return dem.elevation_m - regional


def detect_anomalies(
    dem: DEM,
    kernel_sigma_cells: float = 12.0,
    zscore_threshold: float = 2.0,
    min_area_cells: int = 4,
    edge_margin_cells: int | None = None,
) -> list[AnomalyCandidate]:
    """Detect local-relief anomalies in a DEM.

    Returns candidates sorted by |peak z-score| descending. This is
    descriptive statistics on a single DEM, NOT a claim of archaeological
    significance — that requires independent corroborating evidence,
    which this module does not have access to.

    edge_margin_cells: cells within this distance of the AOI border are
    excluded from consideration. Gaussian detrending is only accurate
    away from a raster's edge (boundary padding biases the regional
    surface estimate there), so without this, border pixels regularly
    produce spurious high-z candidates that have nothing to do with the
    terrain. Defaults to 2x the detrend kernel sigma, which is the
    standard rule of thumb for where a Gaussian kernel's edge bias
    becomes negligible.
    """
    if edge_margin_cells is None:
        edge_margin_cells = int(round(2 * kernel_sigma_cells))

    residual = compute_residual_relief(dem, kernel_sigma_cells)

    n = dem.aoi.grid_size
    interior = np.zeros_like(residual, dtype=bool)
    lo, hi = edge_margin_cells, n - edge_margin_cells
    if hi <= lo:
        raise ValueError(
            f"edge_margin_cells={edge_margin_cells} leaves no interior on a "
            f"{n}x{n} grid — use a larger grid_size or smaller detrend kernel"
        )
    interior[lo:hi, lo:hi] = True

    mu = residual[interior].mean()
    sigma = residual[interior].std()
    if sigma < 1e-9:
        return []  # perfectly flat residual, nothing to detect

    zscore = (residual - mu) / sigma

    mask = (np.abs(zscore) >= zscore_threshold) & interior
    labeled, n_features = ndimage.label(mask)

    # Use the same WGS84 ellipsoid formula as coordinate.build_aoi(), instead
    # of a hardcoded equatorial constant, so that anomaly lat/lon and AOI
    # lat/lon are computed by the same math and never silently disagree.
    m_per_deg_lat, m_per_deg_lon = meters_per_degree(dem.aoi.center.lat)
    cell_deg_lat = dem.aoi.cell_size_m / m_per_deg_lat
    cell_deg_lon = dem.aoi.cell_size_m / m_per_deg_lon
    n = dem.aoi.grid_size

    candidates: list[AnomalyCandidate] = []
    for label_id in range(1, n_features + 1):
        region = labeled == label_id
        area = int(region.sum())
        if area < min_area_cells:
            continue

        region_residual = residual[region]
        region_zscore = zscore[region]
        peak_idx_flat = np.argmax(np.abs(region_zscore))
        rows, cols = np.where(region)
        peak_row = int(rows[peak_idx_flat])
        peak_col = int(cols[peak_idx_flat])

        peak_residual = float(residual[peak_row, peak_col])
        peak_z = float(zscore[peak_row, peak_col])

        lat = dem.aoi.min_lat + (n - 1 - peak_row) * cell_deg_lat
        lon = dem.aoi.min_lon + peak_col * cell_deg_lon

        candidates.append(AnomalyCandidate(
            row=peak_row,
            col=peak_col,
            lat=lat,
            lon=lon,
            area_cells=area,
            peak_residual_m=peak_residual,
            mean_residual_m=float(region_residual.mean()),
            peak_zscore=peak_z,
            polarity="positive" if peak_residual > 0 else "negative",
        ))

    candidates.sort(key=lambda c: abs(c.peak_zscore), reverse=True)
    return candidates
