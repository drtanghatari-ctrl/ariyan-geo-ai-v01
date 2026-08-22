"""
test_dem_source_mobile.py — Tests for OpenTopographyAAIGridSource with
the network layer mocked out (unittest.mock), since this sandbox has
no outbound network access. This verifies the fetch/parse/resample
LOGIC is correct given a known response; it does NOT verify that a
live OpenTopography server actually behaves the way these mocks
assume. See verify_real_dem.py for the live check to run separately,
once real network access + an API key exist.
"""
import unittest
from unittest.mock import patch, MagicMock

import numpy as np

from coordinate import GeoPoint, build_aoi
from dem_source_mobile import OpenTopographyAAIGridSource, OpenTopographyFetchError


# A 4x6 AAIGrid (deliberately non-square, like a real OpenTopography
# response would generally be) with a simple sloped surface so
# resampling correctness is checkable.
def _make_response_text(nrows=4, ncols=6, nodata_cell=None):
    lines = [
        f"ncols         {ncols}",
        f"nrows         {nrows}",
        "xllcorner     10.0",
        "yllcorner     50.0",
        "cellsize      0.001",
        "NODATA_value  -9999",
    ]
    for r in range(nrows):
        row_vals = []
        for c in range(ncols):
            if nodata_cell == (r, c):
                row_vals.append("-9999")
            else:
                row_vals.append(str(100.0 + r * 2 + c))
        lines.append(" ".join(row_vals))
    return "\n".join(lines)


def _mock_response(status_code=200, text="", json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


class TestOpenTopographyAAIGridSourceSuccess(unittest.TestCase):
    def setUp(self):
        self.aoi = build_aoi(GeoPoint(51.1789, -1.8262), radius_m=200, grid_size=16)

    @patch("requests.get")
    def test_successful_fetch_resamples_to_square_grid(self, mock_get):
        mock_get.return_value = _mock_response(200, _make_response_text(nrows=4, ncols=6))

        source = OpenTopographyAAIGridSource(api_key="fake_key_for_test")
        dem = source.fetch(self.aoi)

        self.assertEqual(dem.elevation_m.shape, (16, 16))  # resampled to aoi.grid_size
        self.assertFalse(dem.synthetic)
        self.assertEqual(dem.source, "OpenTopography:SRTMGL1")
        self.assertIn("resampled", dem.notes.lower())
        self.assertTrue(np.isfinite(dem.elevation_m).all())

    @patch("requests.get")
    def test_native_square_grid_skips_resampling(self, mock_get):
        # grid_size=16 to match aoi; native raster is already 16x16
        mock_get.return_value = _mock_response(200, _make_response_text(nrows=16, ncols=16))
        source = OpenTopographyAAIGridSource(api_key="fake_key_for_test")
        dem = source.fetch(self.aoi)
        self.assertEqual(dem.elevation_m.shape, (16, 16))
        self.assertIn("no resampling needed", dem.notes.lower())

    @patch("requests.get")
    def test_request_params_include_bbox_and_key(self, mock_get):
        mock_get.return_value = _mock_response(200, _make_response_text())
        source = OpenTopographyAAIGridSource(api_key="MYKEY123", demtype="COP30")
        source.fetch(self.aoi)

        _, kwargs = mock_get.call_args
        params = kwargs["params"]
        self.assertEqual(params["demtype"], "COP30")
        self.assertEqual(params["API_Key"], "MYKEY123")
        self.assertEqual(params["outputFormat"], "AAIGrid")
        self.assertAlmostEqual(params["south"], self.aoi.min_lat)
        self.assertAlmostEqual(params["north"], self.aoi.max_lat)


class TestOpenTopographyAAIGridSourceErrors(unittest.TestCase):
    def setUp(self):
        self.aoi = build_aoi(GeoPoint(51.1789, -1.8262), radius_m=200, grid_size=16)
        self.source = OpenTopographyAAIGridSource(api_key="fake_key_for_test")

    def test_empty_api_key_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            OpenTopographyAAIGridSource(api_key="")

    @patch("requests.get")
    def test_401_raises_clear_error(self, mock_get):
        mock_get.return_value = _mock_response(401, "Unauthorized")
        with self.assertRaisesRegex(OpenTopographyFetchError, "API key"):
            self.source.fetch(self.aoi)

    @patch("requests.get")
    def test_429_raises_clear_error(self, mock_get):
        mock_get.return_value = _mock_response(429, "Too Many Requests")
        with self.assertRaisesRegex(OpenTopographyFetchError, "rate limit"):
            self.source.fetch(self.aoi)

    @patch("requests.get")
    def test_other_http_error_raises_with_status_code(self, mock_get):
        mock_get.return_value = _mock_response(500, "Internal Server Error")
        with self.assertRaisesRegex(OpenTopographyFetchError, "500"):
            self.source.fetch(self.aoi)

    @patch("requests.get")
    def test_malformed_body_raises_parse_error(self, mock_get):
        mock_get.return_value = _mock_response(200, "not an aaigrid file at all")
        with self.assertRaisesRegex(OpenTopographyFetchError, "AAIGrid"):
            self.source.fetch(self.aoi)

    @patch("requests.get")
    def test_nodata_in_area_raises_clear_error(self, mock_get):
        mock_get.return_value = _mock_response(
            200, _make_response_text(nrows=4, ncols=6, nodata_cell=(1, 1))
        )
        with self.assertRaisesRegex(OpenTopographyFetchError, "NODATA"):
            self.source.fetch(self.aoi)

    @patch("requests.get")
    def test_timeout_raises_clear_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.Timeout("simulated timeout")
        with self.assertRaisesRegex(OpenTopographyFetchError, "timed out"):
            self.source.fetch(self.aoi)

    @patch("requests.get")
    def test_connection_error_raises_clear_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError("simulated no network")
        with self.assertRaisesRegex(OpenTopographyFetchError, "network error"):
            self.source.fetch(self.aoi)


if __name__ == "__main__":
    unittest.main()
