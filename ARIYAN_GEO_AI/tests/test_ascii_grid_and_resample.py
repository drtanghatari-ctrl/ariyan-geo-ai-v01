"""
test_ascii_grid_and_resample.py — Offline correctness tests for the
AAIGrid parser and the bilinear resampler used by dem_source_mobile.py.

These tests do NOT exercise a live OpenTopography call (no network in
this sandbox) -- they verify the two things that are actually testable
offline and that matter most: (1) the parser correctly decodes a
well-formed AAIGrid file and correctly rejects malformed ones, and (2)
the resampler is numerically correct against known analytic inputs.
See test_dem_source_mobile.py for the mocked-HTTP-layer tests, and
verify_real_dem.py for the live smoke test to run once real network
access + an API key are available.
"""
import unittest

import numpy as np

from ascii_grid import parse_ascii_grid, AsciiGridParseError
from np_ops import resample_bilinear


# A small, hand-built, real-format AAIGrid fixture. 4x3 grid (nrows=4,
# ncols=3), values chosen so row/col order is unambiguous to check:
# value = row*10 + col, with row 0 the "top" (north) row per the Esri
# spec -- if the parser mis-transposes or flips this, every value below
# would land in the wrong cell and the assertions would fail.
SAMPLE_AAIGRID = """\
ncols         3
nrows         4
xllcorner     10.0
yllcorner     50.0
cellsize      0.01
NODATA_value  -9999
0 1 2
10 11 12
20 21 -9999
30 31 32
"""


class TestParseAsciiGrid(unittest.TestCase):
    def test_header_fields_parsed_correctly(self):
        grid = parse_ascii_grid(SAMPLE_AAIGRID)
        self.assertEqual(grid.ncols, 3)
        self.assertEqual(grid.nrows, 4)
        self.assertEqual(grid.xll, 10.0)
        self.assertEqual(grid.yll, 50.0)
        self.assertEqual(grid.cellsize, 0.01)
        self.assertFalse(grid.cell_is_center)
        self.assertEqual(grid.nodata_value, -9999)

    def test_values_in_correct_row_major_order(self):
        grid = parse_ascii_grid(SAMPLE_AAIGRID)
        self.assertEqual(grid.values.shape, (4, 3))
        # row 0 = "0 1 2" (northernmost row per Esri spec)
        np.testing.assert_array_equal(grid.values[0], [0, 1, 2])
        np.testing.assert_array_equal(grid.values[1], [10, 11, 12])
        np.testing.assert_array_equal(grid.values[3], [30, 31, 32])

    def test_nodata_becomes_nan(self):
        grid = parse_ascii_grid(SAMPLE_AAIGRID)
        self.assertTrue(np.isnan(grid.values[2, 2]))
        # everything else in that row is real data, not nan
        self.assertFalse(np.isnan(grid.values[2, 0]))
        self.assertFalse(np.isnan(grid.values[2, 1]))

    def test_xllcenter_variant_accepted(self):
        text = SAMPLE_AAIGRID.replace("xllcorner", "xllcenter").replace("yllcorner", "yllcenter")
        grid = parse_ascii_grid(text)
        self.assertTrue(grid.cell_is_center)

    def test_wrapped_body_lines_still_parse(self):
        # Some AAIGrid writers wrap a long row across multiple physical
        # lines. Token-count-based parsing should handle this the same
        # as one-row-per-line.
        wrapped = SAMPLE_AAIGRID.replace("20 21 -9999", "20 21\n-9999")
        grid = parse_ascii_grid(wrapped)
        self.assertEqual(grid.values.shape, (4, 3))
        self.assertTrue(np.isnan(grid.values[2, 2]))

    def test_empty_body_rejected(self):
        with self.assertRaises(AsciiGridParseError):
            parse_ascii_grid("")

    def test_missing_header_field_rejected(self):
        broken = SAMPLE_AAIGRID.replace("cellsize      0.01\n", "")
        with self.assertRaises(AsciiGridParseError):
            parse_ascii_grid(broken)

    def test_wrong_value_count_rejected(self):
        broken = SAMPLE_AAIGRID.replace("30 31 32", "30 31")  # one value short
        with self.assertRaises(AsciiGridParseError):
            parse_ascii_grid(broken)

    def test_non_numeric_value_rejected(self):
        broken = SAMPLE_AAIGRID.replace("30 31 32", "30 31 NaN_not_a_number")
        with self.assertRaises(AsciiGridParseError):
            parse_ascii_grid(broken)

    def test_not_aaigrid_at_all_rejected(self):
        with self.assertRaises(AsciiGridParseError):
            parse_ascii_grid("<html><body>500 Internal Server Error</body></html>")


class TestResampleBilinear(unittest.TestCase):
    def test_same_shape_is_identity_ish(self):
        # Resampling to the exact same shape should reproduce the
        # source almost exactly (pixel-center alignment means it's not
        # bit-exact, but should be extremely close).
        src = np.array([[1.0, 2.0], [3.0, 4.0]])
        out = resample_bilinear(src, 2, 2)
        np.testing.assert_allclose(out, src, atol=1e-9)

    def test_constant_field_stays_constant(self):
        src = np.full((10, 10), 7.5)
        out = resample_bilinear(src, 37, 5)
        np.testing.assert_allclose(out, 7.5, atol=1e-9)

    def test_linear_ramp_preserved_by_interpolation(self):
        # Bilinear interpolation is mathematically exact on an affine
        # function, PROVIDED source and expected values are sampled at
        # cell centers using the same convention resample_bilinear
        # itself uses (dest cell j's center maps to physical position
        # (j+0.5)/out_cols in [0,1)). Defining both sides via that
        # shared physical-position formula is what makes this a real
        # correctness check rather than circular reasoning: it pins
        # down that the r0/c0/r1/c1 index arithmetic and the bilinear
        # weights are correct, not just "whatever the code happens to
        # compute".
        #
        # The very first and last destination pixels are excluded here
        # on purpose: their centers map beyond the source's outermost
        # pixel centers, which resample_bilinear clamps to the nearest
        # edge value rather than extrapolating -- correct, intentional
        # behavior (see test_edge_positions_are_clamped_not_extrapolated),
        # just not what a plain affine formula predicts at the very edge.
        n_in, n_out = 20, 50

        def f(x):
            return 3.0 + 40.0 * x  # arbitrary affine function on [0, 1)

        centers_in = (np.arange(n_in) + 0.5) / n_in
        src = np.tile(f(centers_in), (n_in, 1))  # ramps along columns
        centers_out = (np.arange(n_out) + 0.5) / n_out
        expected_row = f(centers_out)

        out = resample_bilinear(src, n_in, n_out)
        for row in out:
            np.testing.assert_allclose(row[1:-1], expected_row[1:-1], atol=1e-9)

    def test_edge_positions_are_clamped_not_extrapolated(self):
        # Destination pixels whose centers fall outside the source's
        # outermost pixel centers should equal the source's edge value
        # (clamped), never a linearly-extrapolated value beyond the
        # real data's range -- extrapolating elevation past measured
        # terrain would be fabricating data, not resampling it.
        src = np.array([[10.0, 20.0, 30.0, 40.0]])
        src = np.tile(src, (4, 1))
        out = resample_bilinear(src, 4, 40)
        self.assertAlmostEqual(out[0, 0], 10.0, places=6)
        self.assertAlmostEqual(out[0, -1], 40.0, places=6)
        # nothing in the output should exceed the source's own range
        self.assertTrue((out >= 10.0 - 1e-9).all())
        self.assertTrue((out <= 40.0 + 1e-9).all())

    def test_upsampling_and_downsampling_both_work(self):
        src = np.random.default_rng(1).normal(size=(15, 22))
        up = resample_bilinear(src, 40, 40)
        down = resample_bilinear(src, 5, 5)
        self.assertEqual(up.shape, (40, 40))
        self.assertEqual(down.shape, (5, 5))
        # No NaNs/infs introduced.
        self.assertTrue(np.isfinite(up).all())
        self.assertTrue(np.isfinite(down).all())

    def test_rejects_too_small_source(self):
        with self.assertRaises(ValueError):
            resample_bilinear(np.array([[1.0]]), 5, 5)


if __name__ == "__main__":
    unittest.main()
