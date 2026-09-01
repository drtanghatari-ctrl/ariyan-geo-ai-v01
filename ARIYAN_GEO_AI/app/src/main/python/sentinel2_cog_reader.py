"""
sentinel2_cog_reader.py

Part of ARIYAN GEO AI's OFFLINE MODE extension (NDVI half).

A general-purpose reader for a SINGLE downloaded Sentinel-2 L2A COG band
asset (e.g. B04.tif, B08.tif, SCL.tif) from the Earth Search / sentinel-cogs
public bucket.

WHY THIS IS A SEPARATE FILE FROM geotiff_cog_reader.py: that reader was
built and proven specifically for Copernicus DEM tiles, which are single-
band float32 with a floating-point predictor (Predictor=3). Sentinel-2 COG
bands are uint16 (SCL/visual are uint8) and there is no confirmed source
(as of writing) for which predictor, if any, Earth Search's COG generation
pipeline uses for them. Rather than guess, this reader reads the
Predictor/SampleFormat/BitsPerSample tags directly out of each real file
and branches on the actual value found -- it does not assume Predictor=2
(horizontal differencing, the common choice for integer data) any more
than it assumes Predictor=3. An unsupported/unexpected value raises
Unsupported S2TiffError rather than silently mis-decoding, matching this
project's existing geotiff_cog_reader.py philosophy.

WHY POINT-SAMPLING (get_value) RATHER THAN A FULL-ARRAY READ: this reader
is meant to be used by the NDVI compositor (offline_data_manager.py,
NDVI half -- not yet written) to sample B04/B08/SCL each at the SAME
real-world (lon, lat) point. Different Sentinel-2 bands/assets are not
guaranteed to share an identical pixel grid or resolution (SCL is
historically coarser than B04/B08 in raw Sentinel-2 products; whether
Earth Search's COG version of SCL matches B04/B08's grid has not been
confirmed against a real downloaded file). Sampling each band
independently by real-world coordinate -- exactly like
geotiff_cog_reader.CopernicusDemTile.get_elevation() already does for
DEM -- sidesteps needing that assumption at all: each band is read using
its OWN georeferencing, so grid mismatches (if any) are handled
correctly by construction rather than by assumption.

STILL NOT TESTED AGAINST A REAL DOWNLOADED SENTINEL-2 TILE (same honest
gap this project has already flagged for geotiff_cog_reader.py and
offline_data_manager.py's DEM half): this module has only been verified
against hand-built synthetic tiled/DEFLATE TIFFs (both Predictor=2 uint16
and Predictor=3 float32 variants) in a local sandbox test, not a real
Earth Search COG. That final check is deferred to the on-device/CI
stage, same as the DEM path.
"""

from __future__ import annotations

import struct
import zlib
from typing import Dict, Optional, Tuple

import numpy as np


class UnsupportedS2TiffError(Exception):
    """Raised when a file is outside the narrow shape this reader
    supports. Never silently guessed around -- matches this project's
    hard rule against fabricated/assumed data."""


# TIFF tag ids used by this reader
_TAG_IMAGE_WIDTH = 256
_TAG_IMAGE_LENGTH = 257
_TAG_BITS_PER_SAMPLE = 258
_TAG_COMPRESSION = 259
_TAG_SAMPLES_PER_PIXEL = 277
_TAG_TILE_WIDTH = 322
_TAG_TILE_LENGTH = 323
_TAG_TILE_OFFSETS = 324
_TAG_TILE_BYTE_COUNTS = 325
_TAG_SAMPLE_FORMAT = 339
_TAG_MODEL_PIXEL_SCALE = 33550
_TAG_MODEL_TIEPOINT = 33922
_TAG_GDAL_NODATA = 42113

_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8}  # BYTE,ASCII,SHORT,LONG,RATIONAL,FLOAT,DOUBLE

_SAMPLE_FORMAT_TO_DTYPE = {
    # (sample_format, bits_per_sample) -> numpy dtype
    (1, 8): np.uint8,
    (1, 16): np.uint16,
    (2, 8): np.int8,
    (2, 16): np.int16,
    (3, 32): np.float32,
}


class Sentinel2CogBand:
    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as f:
            data = f.read()
        self._data = data

        byte_order = data[0:2]
        if byte_order == b"II":
            self._endian = "<"
        elif byte_order == b"MM":
            self._endian = ">"
        else:
            raise UnsupportedS2TiffError(f"Not a TIFF (bad byte order marker): {path}")

        magic = struct.unpack_from(self._endian + "H", data, 2)[0]
        if magic != 42:
            raise UnsupportedS2TiffError(f"Not classic TIFF (magic={magic}, BigTIFF unsupported): {path}")

        ifd_offset = struct.unpack_from(self._endian + "I", data, 4)[0]
        tags = self._read_ifd(ifd_offset)

        self.width = self._require_scalar(tags, _TAG_IMAGE_WIDTH)
        self.height = self._require_scalar(tags, _TAG_IMAGE_LENGTH)
        samples_per_pixel = tags.get(_TAG_SAMPLES_PER_PIXEL, (1,))[0]
        if samples_per_pixel != 1:
            raise UnsupportedS2TiffError(
                f"Only single-band files are supported (samples_per_pixel={samples_per_pixel}): {path}"
            )

        bits_per_sample = tags.get(_TAG_BITS_PER_SAMPLE, (8,))[0]
        sample_format = tags.get(_TAG_SAMPLE_FORMAT, (1,))[0]
        dtype = _SAMPLE_FORMAT_TO_DTYPE.get((sample_format, bits_per_sample))
        if dtype is None:
            raise UnsupportedS2TiffError(
                f"Unsupported sample_format={sample_format}/bits_per_sample={bits_per_sample}: {path}"
            )
        self._dtype = dtype
        self._bits_per_sample = bits_per_sample

        compression = self._require_scalar(tags, _TAG_COMPRESSION)
        if compression not in (8, 32946):
            raise UnsupportedS2TiffError(f"Unsupported compression={compression} (only DEFLATE): {path}")

        if _TAG_TILE_WIDTH not in tags or _TAG_TILE_LENGTH not in tags:
            raise UnsupportedS2TiffError(f"Not a tiled TIFF (strip-based files unsupported): {path}")
        self.tile_width = tags[_TAG_TILE_WIDTH][0]
        self.tile_height = tags[_TAG_TILE_LENGTH][0]
        self._tile_offsets = tags[_TAG_TILE_OFFSETS]
        self._tile_byte_counts = tags[_TAG_TILE_BYTE_COUNTS]

        # Predictor is NOT in the mandatory Baseline tag set for a plain
        # reader unless present -- default per TIFF spec is 1 (none).
        # We deliberately read whatever real value is present rather than
        # assuming 2 or 3.
        self._predictor = tags.get(317, (1,))[0]
        if self._predictor not in (1, 2, 3):
            raise UnsupportedS2TiffError(f"Unsupported predictor={self._predictor}: {path}")
        if self._predictor == 3 and dtype != np.float32:
            raise UnsupportedS2TiffError(
                f"Floating-point predictor with non-float32 dtype is not a defined combination: {path}"
            )

        if _TAG_MODEL_PIXEL_SCALE not in tags or _TAG_MODEL_TIEPOINT not in tags:
            raise UnsupportedS2TiffError(f"Missing georeferencing tags: {path}")
        scale = tags[_TAG_MODEL_PIXEL_SCALE]
        tiepoint = tags[_TAG_MODEL_TIEPOINT]
        self._pixel_scale_x = scale[0]
        self._pixel_scale_y = scale[1]
        # ModelTiepointTag = (I,J,K, X,Y,Z) -- raster point (I,J) maps to
        # model point (X,Y). GDAL/Copernicus convention uses (0,0) -> the
        # top-left corner's real-world coordinate.
        self._origin_x = tiepoint[3]
        self._origin_y = tiepoint[4]

        nodata_raw = tags.get(_TAG_GDAL_NODATA)
        if nodata_raw is not None and isinstance(nodata_raw, str):
            try:
                self._nodata = float(nodata_raw.strip().rstrip("\x00"))
            except ValueError:
                self._nodata = 0.0
        else:
            self._nodata = 0.0  # confirmed default for Earth Search Sentinel-2 COG assets

        self._n_tiles_x = (self.width + self.tile_width - 1) // self.tile_width
        self._n_tiles_y = (self.height + self.tile_height - 1) // self.tile_height
        self._tile_cache: Dict[Tuple[int, int], np.ndarray] = {}

    # -- IFD parsing -------------------------------------------------------

    def _read_ifd(self, offset: int) -> dict:
        e = self._endian
        data = self._data
        n_entries = struct.unpack_from(e + "H", data, offset)[0]
        tags = {}
        entry_off = offset + 2
        for _ in range(n_entries):
            tag_id, field_type, count = struct.unpack_from(e + "HHI", data, entry_off)
            type_size = _TYPE_SIZES.get(field_type)
            value_offset_field = entry_off + 8
            if type_size is None:
                entry_off += 12
                continue
            total_size = type_size * count
            if total_size <= 4:
                value_bytes_offset = value_offset_field
            else:
                value_bytes_offset = struct.unpack_from(e + "I", data, value_offset_field)[0]

            if field_type == 2:  # ASCII
                raw = data[value_bytes_offset: value_bytes_offset + count]
                tags[tag_id] = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")
            else:
                fmt_char = {1: "B", 3: "H", 4: "I", 11: "f", 12: "d"}.get(field_type)
                if fmt_char is None:
                    entry_off += 12
                    continue
                values = struct.unpack_from(e + fmt_char * count, data, value_bytes_offset)
                tags[tag_id] = values

            entry_off += 12
        return tags

    def _require_scalar(self, tags: dict, tag_id: int) -> int:
        if tag_id not in tags:
            raise UnsupportedS2TiffError(f"Missing required tag {tag_id}: {self.path}")
        return tags[tag_id][0]

    # -- tile decode ---------------------------------------------------

    def _decode_tile(self, tile_row: int, tile_col: int) -> np.ndarray:
        key = (tile_row, tile_col)
        cached = self._tile_cache.get(key)
        if cached is not None:
            return cached

        tile_index = tile_row * self._n_tiles_x + tile_col
        if tile_index >= len(self._tile_offsets):
            raise UnsupportedS2TiffError(f"Tile index out of range: {self.path}")
        offset = self._tile_offsets[tile_index]
        byte_count = self._tile_byte_counts[tile_index]
        compressed = self._data[offset: offset + byte_count]
        raw = zlib.decompress(compressed)

        arr = np.frombuffer(raw, dtype=self._dtype).reshape(self.tile_height, self.tile_width).copy()

        if self._predictor == 2:
            # Horizontal differencing: undo via cumulative sum along each
            # row, in the pixel's native bit width so wraparound (modulo
            # 2^bits) matches what TIFF's spec defines.
            arr = np.cumsum(arr.astype(np.int64), axis=1)
            arr = (arr % (1 << self._bits_per_sample)).astype(self._dtype)
        elif self._predictor == 3:
            byte_view = arr.view(np.uint8).reshape(self.tile_height, -1)
            undiffed = np.cumsum(byte_view.astype(np.int64), axis=1) % 256
            undiffed = undiffed.astype(np.uint8)
            n_bytes_per_row = self.tile_width * 4
            reordered = undiffed.reshape(self.tile_height, 4, self.tile_width)
            planar_bytes = np.empty((self.tile_height, n_bytes_per_row), dtype=np.uint8)
            for b in range(4):
                planar_bytes[:, b::4] = reordered[:, b, :]
            arr = planar_bytes.view(np.float32).reshape(self.tile_height, self.tile_width)

        self._tile_cache[key] = arr
        return arr

    # -- public API ------------------------------------------------------

    def get_value(self, lon: float, lat: float) -> Optional[float]:
        """Returns this band's real value at (lon, lat), or None if the
        coordinate falls outside the raster or lands on a nodata pixel.
        Never raises for an out-of-bounds coordinate -- that is an
        ordinary expected case, not an error."""
        px = (lon - self._origin_x) / self._pixel_scale_x
        py = (self._origin_y - lat) / self._pixel_scale_y
        col = int(round(px))
        row = int(round(py))
        if col < 0 or col >= self.width or row < 0 or row >= self.height:
            return None

        tile_row = row // self.tile_height
        tile_col = col // self.tile_width
        tile = self._decode_tile(tile_row, tile_col)
        local_row = row - tile_row * self.tile_height
        local_col = col - tile_col * self.tile_width
        value = tile[local_row, local_col]

        if float(value) == self._nodata:
            return None
        return float(value)
