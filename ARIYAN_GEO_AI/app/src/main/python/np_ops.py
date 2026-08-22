"""
np_ops.py — NumPy-only replacements for the two SciPy operations the
anomaly detector needs (gaussian_filter, connected-component labeling).

Why this exists: the desktop/dev pipeline uses scipy.ndimage, which is
correct and well-tested, but SciPy's Fortran-backed native code is a
poor fit for an Android/Chaquopy build (large, and not reliably
available as a prebuilt Android wheel). Rather than take that risk
silently, this module reimplements the same two operations using only
NumPy, and its correctness is checked against SciPy directly (see
tests/test_np_ops_matches_scipy.py) rather than assumed.
"""
from __future__ import annotations

import numpy as np


def gaussian_kernel_1d(sigma: float, truncate: float = 4.0) -> np.ndarray:
    """Same discretization SciPy uses: radius = truncate * sigma, rounded."""
    radius = int(truncate * sigma + 0.5)
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel /= kernel.sum()
    return kernel


def gaussian_filter_2d(arr: np.ndarray, sigma: float, mode: str = "edge") -> np.ndarray:
    """Separable 2D Gaussian filter, edge-replicated padding (matches
    scipy.ndimage.gaussian_filter(..., mode='nearest')). Pure NumPy —
    no scipy dependency, so it builds cleanly for Android via Chaquopy."""
    kernel = gaussian_kernel_1d(sigma)
    radius = (len(kernel) - 1) // 2

    padded = np.pad(arr, radius, mode=mode)

    # Convolve along columns (axis=1), then rows (axis=0).
    tmp = np.empty((padded.shape[0], arr.shape[1]), dtype=np.float64)
    for i in range(padded.shape[0]):
        tmp[i, :] = np.convolve(padded[i, :], kernel, mode="valid")

    out = np.empty((arr.shape[0], arr.shape[1]), dtype=np.float64)
    for j in range(tmp.shape[1]):
        out[:, j] = np.convolve(tmp[:, j], kernel, mode="valid")

    return out


def label_connected_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connectivity flood-fill labeling, drop-in replacement for
    scipy.ndimage.label(mask) (same return shape: (labeled_array,
    n_features); label IDs need not match scipy's exactly, only the
    grouping of connected True cells, which is all downstream code
    relies on)."""
    labeled = np.zeros(mask.shape, dtype=np.int32)
    n_rows, n_cols = mask.shape
    current_label = 0

    for start_r in range(n_rows):
        for start_c in range(n_cols):
            if not mask[start_r, start_c] or labeled[start_r, start_c] != 0:
                continue
            current_label += 1
            stack = [(start_r, start_c)]
            labeled[start_r, start_c] = current_label
            while stack:
                r, c = stack.pop()
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < n_rows and 0 <= nc < n_cols:
                        if mask[nr, nc] and labeled[nr, nc] == 0:
                            labeled[nr, nc] = current_label
                            stack.append((nr, nc))

    return labeled, current_label


def resample_bilinear(values: np.ndarray, out_rows: int, out_cols: int) -> np.ndarray:
    """Resample a 2D array to (out_rows, out_cols) via bilinear
    interpolation on a regular grid. Pure NumPy -- no scipy.

    Why this exists: a real DEM fetched for a given AOI generally does
    NOT come back as a square raster (SRTM-family datasets are gridded
    in arc-seconds, which are not square in degrees away from the
    equator, even though the AOI itself is square in meters -- see
    coordinate.build_aoi). The rest of this pipeline
    (anomaly_detection_mobile.py) assumes a single square grid_size for
    both axes. This function is the explicit, tested step that bridges
    a real raster's native shape onto that square-grid convention,
    rather than the mismatch being silently ignored somewhere.

    Source and destination grids are treated as corner-aligned (both
    cover the same physical extent edge-to-edge), matching how
    coordinate.build_aoi defines an AOI's bounds.
    """
    in_rows, in_cols = values.shape
    if in_rows < 2 or in_cols < 2:
        raise ValueError("resample_bilinear needs at least a 2x2 source grid")
    if out_rows < 1 or out_cols < 1:
        raise ValueError("resample_bilinear needs a positive output size")

    # Destination pixel centers mapped into source index space.
    row_pos = (np.arange(out_rows) + 0.5) / out_rows * in_rows - 0.5
    col_pos = (np.arange(out_cols) + 0.5) / out_cols * in_cols - 0.5
    row_pos = np.clip(row_pos, 0, in_rows - 1)
    col_pos = np.clip(col_pos, 0, in_cols - 1)

    r0 = np.floor(row_pos).astype(int)
    c0 = np.floor(col_pos).astype(int)
    r1 = np.clip(r0 + 1, 0, in_rows - 1)
    c1 = np.clip(c0 + 1, 0, in_cols - 1)

    rw = (row_pos - r0)[:, None]   # shape (out_rows, 1)
    cw = (col_pos - c0)[None, :]   # shape (1, out_cols)

    v00 = values[np.ix_(r0, c0)]
    v01 = values[np.ix_(r0, c1)]
    v10 = values[np.ix_(r1, c0)]
    v11 = values[np.ix_(r1, c1)]

    top = v00 * (1 - cw) + v01 * cw
    bottom = v10 * (1 - cw) + v11 * cw
    return top * (1 - rw) + bottom * rw
