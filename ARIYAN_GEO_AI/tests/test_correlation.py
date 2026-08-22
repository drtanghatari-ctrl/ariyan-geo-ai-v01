"""
Tests for correlation.py — the point of these tests is to verify the
engine actually distinguishes "two independent sources agree" from
"only one source sees anything", not just that it runs without error.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from coordinate import GeoPoint, build_aoi
from dem_source import SyntheticDEMSource
from imagery_source import SyntheticNDVISource
from anomaly_detection_mobile import detect_anomalies, detect_raster_anomalies
from correlation import correlate_anomalies


class TestCorrelationEngine(unittest.TestCase):
    def setUp(self):
        self.center = GeoPoint(51.1789, -1.8262)
        self.aoi = build_aoi(self.center, radius_m=500, grid_size=128)

    def test_colocated_anomalies_are_corroborated(self):
        # Inject an anomaly at the SAME row/col in both DEM and NDVI.
        dem = SyntheticDEMSource(seed=7).fetch(
            self.aoi, relief_amplitude_m=0.5, relief_wavelength_cells=90,
            anomalies=[{"row": 40, "col": 90, "amplitude_m": 1.0, "sigma_cells": 4}],
        )
        ndvi = SyntheticNDVISource(seed=11).fetch(
            self.aoi, variability=0.06, variability_wavelength_cells=30,
            anomalies=[{"row": 40, "col": 90, "amplitude": -0.2, "sigma_cells": 4}],
        )

        dem_candidates = detect_anomalies(dem, kernel_sigma_cells=15, zscore_threshold=2.5, min_area_cells=3)
        ndvi_candidates = detect_raster_anomalies(
            self.aoi, ndvi.ndvi, kernel_sigma_cells=15, zscore_threshold=2.0, min_area_cells=3
        )

        self.assertGreaterEqual(len(dem_candidates), 1)
        self.assertGreaterEqual(len(ndvi_candidates), 1)

        results = correlate_anomalies(
            {"DEM": dem_candidates, "NDVI": ndvi_candidates},
            aoi_center=self.center,
            colocation_distance_m=60.0,  # a few cells at this AOI's resolution
        )

        corroborated = [r for r in results if r.status == "CORROBORATED"]
        self.assertGreaterEqual(len(corroborated), 1)
        self.assertEqual(set(corroborated[0].supporting_sources), {"DEM", "NDVI"})

    def test_uncorrelated_anomalies_stay_single_source(self):
        # DEM anomaly at one location, NDVI anomaly at a DIFFERENT,
        # far-away location. These must NOT be reported as corroborated.
        dem = SyntheticDEMSource(seed=7).fetch(
            self.aoi, relief_amplitude_m=0.5, relief_wavelength_cells=90,
            anomalies=[{"row": 40, "col": 90, "amplitude_m": 1.0, "sigma_cells": 4}],
        )
        ndvi = SyntheticNDVISource(seed=11).fetch(
            self.aoi, variability=0.06, variability_wavelength_cells=30,
            anomalies=[{"row": 90, "col": 30, "amplitude": -0.2, "sigma_cells": 4}],
        )

        dem_candidates = detect_anomalies(dem, kernel_sigma_cells=15, zscore_threshold=2.5, min_area_cells=3)
        ndvi_candidates = detect_raster_anomalies(
            self.aoi, ndvi.ndvi, kernel_sigma_cells=15, zscore_threshold=2.0, min_area_cells=3
        )

        results = correlate_anomalies(
            {"DEM": dem_candidates, "NDVI": ndvi_candidates},
            aoi_center=self.center,
            colocation_distance_m=60.0,
        )

        self.assertTrue(all(r.status == "SINGLE_SOURCE" for r in results))
        self.assertEqual(len(results), len(dem_candidates) + len(ndvi_candidates))

    def test_no_anomalies_returns_empty(self):
        results = correlate_anomalies(
            {"DEM": [], "NDVI": []}, aoi_center=self.center, colocation_distance_m=60.0
        )
        self.assertEqual(results, [])

    def test_single_source_only_present(self):
        # Only DEM has any candidates at all — NDVI source unavailable/no anomalies.
        dem = SyntheticDEMSource(seed=7).fetch(
            self.aoi, relief_amplitude_m=0.5, relief_wavelength_cells=90,
            anomalies=[{"row": 40, "col": 90, "amplitude_m": 1.0, "sigma_cells": 4}],
        )
        dem_candidates = detect_anomalies(dem, kernel_sigma_cells=15, zscore_threshold=2.5, min_area_cells=3)

        results = correlate_anomalies(
            {"DEM": dem_candidates, "NDVI": []}, aoi_center=self.center, colocation_distance_m=60.0
        )
        self.assertEqual(len(results), len(dem_candidates))
        self.assertTrue(all(r.status == "SINGLE_SOURCE" for r in results))
        self.assertTrue(all(r.supporting_sources == ["DEM"] for r in results))


if __name__ == "__main__":
    unittest.main()
