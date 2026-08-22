"""
Automated tests for the ARIYAN core vertical slice.
Run with: python3 -m unittest discover -s tests -v
(uses stdlib unittest since pytest isn't installed in this environment)
"""
import math
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from coordinate import GeoPoint, build_aoi, haversine_distance_m, meters_per_degree
from dem_source import DEM, SyntheticDEMSource
from terrain_derivatives import compute_slope_deg, compute_aspect_deg, compute_profile_curvature
from anomaly_detection import detect_anomalies


class TestCoordinate(unittest.TestCase):
    def test_meters_per_degree_equator_matches_known_value(self):
        mlat, mlon = meters_per_degree(0.0)
        self.assertAlmostEqual(mlat, 110574, delta=50)
        self.assertAlmostEqual(mlon, 111320, delta=50)

    def test_aoi_half_width_matches_haversine(self):
        center = GeoPoint(51.1789, -1.8262)
        aoi = build_aoi(center, radius_m=500, grid_size=64)
        edge = GeoPoint(center.lat, aoi.max_lon)
        d = haversine_distance_m(center, edge)
        self.assertAlmostEqual(d, 500, delta=10)

    def test_invalid_latitude_rejected(self):
        with self.assertRaises(ValueError):
            GeoPoint(91.0, 0.0)

    def test_grid_too_small_rejected(self):
        with self.assertRaises(ValueError):
            build_aoi(GeoPoint(0, 0), radius_m=100, grid_size=4)


class TestTerrainDerivatives(unittest.TestCase):
    def _make_plane_dem(self, slope_deg, n=64, cell_size=8.0):
        aoi = build_aoi(GeoPoint(0, 0), radius_m=n * cell_size / 2, grid_size=n)
        yy, xx = np.mgrid[0:n, 0:n].astype(float)
        rise = math.tan(math.radians(slope_deg)) * cell_size
        elevation = xx * rise
        return DEM(aoi=aoi, elevation_m=elevation, source="TEST", synthetic=True, resolution_m=cell_size)

    def test_slope_matches_known_plane(self):
        dem = self._make_plane_dem(30.0)
        result = compute_slope_deg(dem)
        interior = result.values[8:-8, 8:-8]
        self.assertAlmostEqual(float(interior.mean()), 30.0, places=3)
        self.assertLess(float(interior.std()), 1e-6)

    def test_aspect_faces_downhill(self):
        # Elevation rises to the east -> downhill direction is west (270deg)
        dem = self._make_plane_dem(15.0)
        result = compute_aspect_deg(dem)
        center = result.values[32, 32]
        self.assertAlmostEqual(center, 270.0, delta=1.0)

    def test_flat_terrain_has_zero_slope(self):
        aoi = build_aoi(GeoPoint(0, 0), radius_m=500, grid_size=32)
        flat = np.full((32, 32), 100.0)
        dem = DEM(aoi=aoi, elevation_m=flat, source="TEST", synthetic=True, resolution_m=aoi.cell_size_m)
        result = compute_slope_deg(dem)
        self.assertAlmostEqual(float(result.values.max()), 0.0, places=6)

    def test_dome_has_positive_curvature_at_apex(self):
        n = 64
        aoi = build_aoi(GeoPoint(0, 0), radius_m=n * 8 / 2, grid_size=n)
        yy, xx = np.mgrid[0:n, 0:n].astype(float)
        dome = 50 - 0.01 * ((xx - 32) ** 2 + (yy - 32) ** 2)
        dem = DEM(aoi=aoi, elevation_m=dome, source="TEST", synthetic=True, resolution_m=8.0)
        result = compute_profile_curvature(dem)
        self.assertGreater(result.values[32, 32], 0)


class TestAnomalyDetection(unittest.TestCase):
    def test_detects_injected_anomaly_at_correct_location(self):
        aoi = build_aoi(GeoPoint(51.1789, -1.8262), radius_m=500, grid_size=128)
        dem = SyntheticDEMSource(seed=7).fetch(
            aoi, relief_amplitude_m=0.5, relief_wavelength_cells=90,
            anomalies=[{"row": 40, "col": 90, "amplitude_m": 1.0, "sigma_cells": 4}],
        )
        found = detect_anomalies(dem, kernel_sigma_cells=15, zscore_threshold=2.5, min_area_cells=3)
        self.assertGreaterEqual(len(found), 1)
        top = found[0]
        dist = math.hypot(top.row - 40, top.col - 90)
        self.assertLessEqual(dist, 2.0)

    def test_flat_terrain_produces_no_anomalies(self):
        aoi = build_aoi(GeoPoint(0, 0), radius_m=500, grid_size=64)
        flat = np.full((64, 64), 100.0)
        dem = DEM(aoi=aoi, elevation_m=flat, source="TEST", synthetic=True, resolution_m=aoi.cell_size_m)
        found = detect_anomalies(dem, kernel_sigma_cells=10, zscore_threshold=2.5, min_area_cells=3)
        self.assertEqual(found, [])

    def test_edge_margin_excludes_border_artifacts(self):
        aoi = build_aoi(GeoPoint(51.1789, -1.8262), radius_m=500, grid_size=128)
        dem = SyntheticDEMSource(seed=3).fetch(
            aoi, relief_amplitude_m=0.5, relief_wavelength_cells=90,
        )
        found = detect_anomalies(dem, kernel_sigma_cells=15, zscore_threshold=2.5, min_area_cells=3)
        margin = 30  # 2x kernel_sigma_cells
        n = aoi.grid_size
        for c in found:
            self.assertTrue(margin <= c.row <= n - margin)
            self.assertTrue(margin <= c.col <= n - margin)


if __name__ == "__main__":
    unittest.main()
