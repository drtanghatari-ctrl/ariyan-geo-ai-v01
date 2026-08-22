"""
test_real_dem_regression.py — A real, not mocked, not synthetic,
regression test for the entire mobile DEM pipeline.

fixtures/silbury_hill_real_aaigrid.asc is an ACTUAL response fetched
live from OpenTopography's Global DEM API (SRTMGL1) for Silbury Hill,
Wiltshire, UK -- a real, documented ~30-40m prominence Neolithic mound
-- captured by the person building this app, on 2026-08-21, via a
direct browser request against the real API with their own key. This
is the "known real landform" regression check the core's own README
calls for, and the thing verify_real_dem.py exists to make possible --
this test file is what turns that one-off manual check into a
permanent, automated one.

What this proves, precisely: given data OpenTopography actually
returned for a real place, ascii_grid.py parses it correctly, the
raster's real (non-square: 40 rows x 54 cols) shape gets resampled
correctly onto the pipeline's square-grid convention, and
anomaly_detection_mobile correctly flags a positive-relief anomaly
very close to Silbury Hill's real coordinates.

What this does NOT prove: that this code correctly detects subtle,
buried archaeological features. Silbury Hill is a ~30m tall, extremely
prominent surface mound -- if the anomaly detector couldn't find that,
nothing else it does would be trustworthy, but finding an obvious
30m mound is a much lower bar than finding a subtle buried feature.
Treat this as "the real-DEM pipeline works end-to-end on real data",
not "this app can find archaeology."
"""
import os
import unittest

import numpy as np

from ascii_grid import parse_ascii_grid
from np_ops import resample_bilinear
from coordinate import GeoPoint, build_aoi, haversine_distance_m
from dem_source import DEM
from anomaly_detection_mobile import detect_anomalies
from evidence_record import build_investigation_record

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "silbury_hill_real_aaigrid.asc")

# Real coordinates used for the actual fetch that produced this fixture.
SILBURY_HILL_CENTER = GeoPoint(51.4155, -1.8577)
FETCH_RADIUS_M = 300.0
GRID_SIZE = 64


class TestRealDemRegression(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE_PATH) as f:
            self.raw_text = f.read()

    def test_fixture_parses_to_expected_real_shape(self):
        grid = parse_ascii_grid(self.raw_text)
        # This is the real, non-square shape OpenTopography actually
        # returned -- confirming the "real rasters aren't square" claim
        # dem_source_mobile.py's docstring makes, with real data, not
        # just reasoning about arc-seconds.
        self.assertEqual(grid.nrows, 40)
        self.assertEqual(grid.ncols, 54)
        self.assertFalse(np.isnan(grid.values).any())

    def test_fixture_elevation_range_is_plausible_for_silbury_hill(self):
        grid = parse_ascii_grid(self.raw_text)
        # Real, observed range from the actual fetch: 145-193m. Assert
        # a slightly wider envelope so trivial future re-fetches (SRTM
        # data doesn't change, but this guards against a too-brittle
        # test) still pass.
        self.assertGreaterEqual(grid.values.min(), 100.0)
        self.assertLessEqual(grid.values.max(), 220.0)

    def test_full_pipeline_detects_anomaly_near_real_coordinates(self):
        """The end-to-end check that matters: real fetched data, run
        through the exact same resample -> detect -> evidence-record
        path investigation_mobile.py uses, correctly locates a
        positive-relief anomaly close to Silbury Hill's real
        coordinates."""
        grid = parse_ascii_grid(self.raw_text)
        aoi = build_aoi(SILBURY_HILL_CENTER, radius_m=FETCH_RADIUS_M, grid_size=GRID_SIZE)
        resampled = resample_bilinear(grid.values, GRID_SIZE, GRID_SIZE)

        dem = DEM(
            aoi=aoi, elevation_m=resampled, source="OpenTopography:SRTMGL1",
            synthetic=False, resolution_m=30.0, acquisition_date=None,
            notes="Real fixture: live OpenTopography fetch, Silbury Hill.",
        )

        anomalies = detect_anomalies(dem, kernel_sigma_cells=12.0, zscore_threshold=2.5, min_area_cells=3)
        self.assertGreaterEqual(len(anomalies), 1, "expected at least one anomaly at a real, prominent mound")

        best = max(anomalies, key=lambda a: abs(a.peak_zscore))
        self.assertEqual(best.polarity, "positive")  # a mound is a rise, not a depression

        detected_point = GeoPoint(best.lat, best.lon)
        distance_m = haversine_distance_m(SILBURY_HILL_CENTER, detected_point)
        # Silbury Hill's summit is a broad feature; being within 100m of
        # the requested center coordinate is a meaningful location check
        # without being brittle about the exact summit pixel.
        self.assertLess(distance_m, 100.0,
                         f"detected anomaly {distance_m:.1f}m from requested center -- too far to be Silbury Hill itself")

        record = build_investigation_record(aoi, dem, anomalies, 2.5, 12.0)
        self.assertFalse(record.evidence[0]["synthetic"])


if __name__ == "__main__":
    unittest.main()
