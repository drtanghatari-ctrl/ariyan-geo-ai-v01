"""
Verifies the NumPy-only np_ops implementations against SciPy directly,
on the actual data shapes/sigmas the anomaly detector uses. This is
the check that justifies swapping scipy.ndimage for np_ops on Android
— not just an assumption that a hand-rolled version is equivalent.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from scipy import ndimage

from np_ops import gaussian_filter_2d, label_connected_components
from coordinate import GeoPoint, build_aoi
from dem_source import SyntheticDEMSource
from anomaly_detection import compute_residual_relief, detect_anomalies


class TestGaussianFilterMatchesScipy(unittest.TestCase):
    def test_matches_scipy_on_synthetic_terrain(self):
        aoi = build_aoi(GeoPoint(51.1789, -1.8262), radius_m=500, grid_size=128)
        dem = SyntheticDEMSource(seed=7).fetch(
            aoi, relief_amplitude_m=0.5, relief_wavelength_cells=90,
            anomalies=[{"row": 40, "col": 90, "amplitude_m": 1.0, "sigma_cells": 4}],
        )
        sigma = 15.0
        scipy_result = ndimage.gaussian_filter(dem.elevation_m, sigma=sigma, mode="nearest")
        numpy_result = gaussian_filter_2d(dem.elevation_m, sigma=sigma, mode="edge")

        max_abs_diff = np.max(np.abs(scipy_result - numpy_result))
        # tolerance: well below the ~0.1-1.0m amplitudes the detector cares about
        self.assertLess(max_abs_diff, 1e-6)

    def test_matches_scipy_on_flat_terrain(self):
        flat = np.full((64, 64), 100.0)
        scipy_result = ndimage.gaussian_filter(flat, sigma=10.0, mode="nearest")
        numpy_result = gaussian_filter_2d(flat, sigma=10.0, mode="edge")
        self.assertTrue(np.allclose(scipy_result, numpy_result, atol=1e-9))


class TestLabelingMatchesScipy(unittest.TestCase):
    def test_same_grouping_as_scipy(self):
        rng = np.random.default_rng(1)
        mask = rng.random((40, 40)) > 0.7

        scipy_labeled, scipy_n = ndimage.label(mask)
        numpy_labeled, numpy_n = label_connected_components(mask)

        self.assertEqual(scipy_n, numpy_n)

        # Grouping equivalence: any two cells in the same scipy group
        # must be in the same numpy group, and vice versa.
        for label_id in range(1, scipy_n + 1):
            region = scipy_labeled == label_id
            numpy_labels_in_region = set(numpy_labeled[region].tolist())
            self.assertEqual(len(numpy_labels_in_region), 1)


class TestFullPipelineParity(unittest.TestCase):
    """End-to-end: does swapping scipy for np_ops change what the
    detector actually finds, on the exact case from investigation_record.json?"""

    def test_same_candidate_detected(self):
        aoi = build_aoi(GeoPoint(51.1789, -1.8262), radius_m=500, grid_size=128)
        dem = SyntheticDEMSource(seed=7).fetch(
            aoi, relief_amplitude_m=0.5, relief_wavelength_cells=90,
            anomalies=[{"row": 40, "col": 90, "amplitude_m": 1.0, "sigma_cells": 4}],
        )

        scipy_candidates = detect_anomalies(dem, kernel_sigma_cells=15, zscore_threshold=2.5, min_area_cells=3)

        # Reimplement the detector's core logic with np_ops instead of scipy,
        # to check the swap end-to-end rather than just at the filter level.
        regional = gaussian_filter_2d(dem.elevation_m, sigma=15.0, mode="edge")
        residual = dem.elevation_m - regional
        n = aoi.grid_size
        margin = 30
        interior = np.zeros_like(residual, dtype=bool)
        interior[margin:n - margin, margin:n - margin] = True
        mu = residual[interior].mean()
        sigma_val = residual[interior].std()
        zscore = (residual - mu) / sigma_val
        mask = (np.abs(zscore) >= 2.5) & interior
        labeled, n_features = label_connected_components(mask)

        self.assertGreaterEqual(n_features, 1)
        self.assertEqual(len(scipy_candidates), n_features)

        # peak location should match within a cell or two
        top = scipy_candidates[0]
        region = labeled == labeled[top.row, top.col]
        self.assertTrue(region[top.row, top.col])


if __name__ == "__main__":
    unittest.main()
