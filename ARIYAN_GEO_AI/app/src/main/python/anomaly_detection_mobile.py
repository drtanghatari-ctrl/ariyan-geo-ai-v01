"""
anomaly_detection_mobile.py — Same algorithm as anomaly_detection.py
(Gaussian regional-trend removal + z-score thresholding + connected-
component grouping), but built entirely on np_ops instead of
scipy.ndimage, so it has no SciPy dependency at all. This is the
version embedded in the Android app.

Numerically verified equivalent to the scipy-based version — see
tests/test_np_ops_matches_scipy.py, which is what actually justifies
using this instead of just assuming a hand-rolled reimplementation
behaves the same.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dem_source import DEM
from coordinate import meters_per_degree
from np_ops import gaussian_filter_2d, label_connected_components


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


def compute_residual_relief(dem: DEM, kernel_sigma_cells: float = 12.0) -> np.ndarray:
    return detect_raster_residual(dem.elevation_m, kernel_sigma_cells)


def detect_raster_residual(values: np.ndarray, kernel_sigma_cells: float) -> np.ndarray:
    """Regional-trend removal for any 2D raster (elevation, NDVI, etc.) —
    the statistical method doesn't care what physical quantity the raster
    represents, only that local deviation from the regional trend is
    the signal of interest."""
    regional = gaussian_filter_2d(values, sigma=kernel_sigma_cells, mode="edge")
    return values - regional


def detect_raster_anomalies(
    aoi,
    values: np.ndarray,
    kernel_sigma_cells: float = 12.0,
    zscore_threshold: float = 2.0,
    min_area_cells: int = 4,
    edge_margin_cells: int | None = None,
) -> list[AnomalyCandidate]:
    """Generic anomaly detector: works on any AOI-referenced 2D raster,
    not just DEM elevation. detect_anomalies() (DEM-specific, kept for
    backward compatibility) and the NDVI detector in imagery_source
    usage both call into this so there is exactly one implementation of
    the detrend + z-score + connected-component method to trust."""
    if edge_margin_cells is None:
        edge_margin_cells = int(round(2 * kernel_sigma_cells))

    residual = detect_raster_residual(values, kernel_sigma_cells)

    n = aoi.grid_size
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
        return []

    zscore = (residual - mu) / sigma

    mask = (np.abs(zscore) >= zscore_threshold) & interior
    labeled, n_features = label_connected_components(mask)

    m_per_deg_lat, m_per_deg_lon = meters_per_degree(aoi.center.lat)
    cell_deg_lat = aoi.cell_size_m / m_per_deg_lat
    cell_deg_lon = aoi.cell_size_m / m_per_deg_lon

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

        lat = aoi.min_lat + (n - 1 - peak_row) * cell_deg_lat
        lon = aoi.min_lon + peak_col * cell_deg_lon

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


def detect_anomalies(
    dem: DEM,
    kernel_sigma_cells: float = 12.0,
    zscore_threshold: float = 2.0,
    min_area_cells: int = 4,
    edge_margin_cells: int | None = None,
) -> list[AnomalyCandidate]:
    """DEM-specific entry point, kept for backward compatibility with
    existing callers (investigation_mobile.py, tests). Delegates to the
    generic raster detector."""
    return detect_raster_anomalies(
        dem.aoi, dem.elevation_m, kernel_sigma_cells,
        zscore_threshold, min_area_cells, edge_margin_cells,
    )
