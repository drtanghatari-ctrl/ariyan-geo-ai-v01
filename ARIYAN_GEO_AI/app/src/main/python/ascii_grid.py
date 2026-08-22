"""
ascii_grid.py — Pure-Python/NumPy parser for the Esri/Arc ASCII Grid
(AAIGrid) raster format.

Why this exists: OpenTopography's Global DEM API can return elevation
data as AAIGrid (plain text) instead of GeoTIFF. GeoTIFF requires
GDAL/rasterio to decode, and Chaquopy cannot compile GDAL's native C++
code for Android -- confirmed by a real build failure other developers
have hit (chaquo/chaquopy issue #427: "Chaquopy cannot compile native
code" when attempting to install GDAL). AAIGrid is just whitespace-
separated text, so decoding it needs nothing beyond NumPy -- the same
reasoning that produced np_ops.py (NumPy standing in for SciPy).

Format: a header of key/value pairs (ncols, nrows, xllcorner or
xllcenter, yllcorner or yllcenter, cellsize, optionally nodata_value),
followed by nrows rows of ncols whitespace-separated numbers. Row 0 is
the northernmost row and column 0 is the westernmost column (Esri's
own spec: data is listed "starting in the upper-left corner").
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class AsciiGridParseError(ValueError):
    """Raised when text doesn't parse as a valid AAIGrid file. Kept as
    its own exception type (not a bare ValueError) so callers can
    distinguish "this wasn't AAIGrid at all" from other value errors."""


@dataclass
class AsciiGrid:
    values: np.ndarray       # shape (nrows, ncols), float64; NODATA -> np.nan
    ncols: int
    nrows: int
    xll: float                # left edge, degrees longitude
    yll: float                # bottom edge, degrees latitude
    cellsize: float           # degrees per cell (square cells assumed)
    cell_is_center: bool      # True if header used *llcenter, not *llcorner
    nodata_value: float | None


_HEADER_KEYS = {
    "ncols", "nrows", "xllcorner", "yllcorner", "xllcenter", "yllcenter",
    "cellsize", "nodata_value",
}


def parse_ascii_grid(text: str) -> AsciiGrid:
    """Parse Esri ASCII Grid text into an AsciiGrid.

    Deliberately strict: raises AsciiGridParseError on anything that
    doesn't look like a valid file, rather than guessing. Silently
    returning a wrong-shaped array here would corrupt every downstream
    computation without any visible error -- a loud failure is the
    honest behavior for a scientific pipeline.
    """
    if not text or not text.strip():
        raise AsciiGridParseError("empty response body")

    lines = text.strip().splitlines()

    header: dict[str, float] = {}
    body_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            body_start = i + 1
            continue
        parts = stripped.split()
        key = parts[0].lower()
        if key in _HEADER_KEYS and len(parts) == 2:
            try:
                header[key] = float(parts[1])
            except ValueError:
                raise AsciiGridParseError(f"malformed header line: {line!r}")
            body_start = i + 1
        else:
            break

    missing = {"ncols", "nrows", "cellsize"} - header.keys()
    if missing:
        raise AsciiGridParseError(
            f"AAIGrid header missing required field(s): {sorted(missing)}. "
            f"Header keys found: {sorted(header.keys())}"
        )
    if "xllcorner" not in header and "xllcenter" not in header:
        raise AsciiGridParseError("AAIGrid header missing xllcorner/xllcenter")
    if "yllcorner" not in header and "yllcenter" not in header:
        raise AsciiGridParseError("AAIGrid header missing yllcorner/yllcenter")

    ncols = int(header["ncols"])
    nrows = int(header["nrows"])
    if ncols <= 0 or nrows <= 0:
        raise AsciiGridParseError(f"invalid grid dimensions: ncols={ncols}, nrows={nrows}")
    cellsize = header["cellsize"]
    cell_is_center = "xllcenter" in header
    xll = header.get("xllcenter", header.get("xllcorner"))
    yll = header.get("yllcenter", header.get("yllcorner"))
    nodata = header.get("nodata_value")

    # Some AAIGrid writers wrap long rows across more physical lines
    # than nrows, so parse the body by total token count, not by
    # counting exactly nrows lines.
    body_text = "\n".join(lines[body_start:])
    tokens = body_text.split()
    expected = ncols * nrows
    if len(tokens) != expected:
        raise AsciiGridParseError(
            f"AAIGrid body has {len(tokens)} values, expected "
            f"ncols*nrows = {ncols}*{nrows} = {expected}"
        )
    try:
        flat = np.array(tokens, dtype=np.float64)
    except ValueError as e:
        raise AsciiGridParseError(f"non-numeric value in AAIGrid body: {e}")

    values = flat.reshape(nrows, ncols)
    if nodata is not None:
        values = np.where(values == nodata, np.nan, values)

    return AsciiGrid(
        values=values, ncols=ncols, nrows=nrows,
        xll=xll, yll=yll, cellsize=cellsize,
        cell_is_center=cell_is_center, nodata_value=nodata,
    )
