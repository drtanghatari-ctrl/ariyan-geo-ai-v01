"""
geotiff_cog_reader.py

Part of ARIYAN GEO AI's OFFLINE MODE extension.

A minimal, hand-written reader for the specific kind of GeoTIFF file the
offline DEM path actually needs to read: Copernicus DEM GLO-30/90 Cloud-
Optimized GeoTIFFs (COGs) as distributed on the public AWS Open Data
bucket. It is NOT a general-purpose GeoTIFF library.

WHY THIS EXISTS INSTEAD OF A LIBRARY: the standard way to read GeoTIFFs
(GDAL/rasterio) cannot be compiled for Chaquopy Android builds (the same
reason dem_source_mobile.py avoids them for the live pipeline). The
obvious pure-Python alternative, tifffile, turned out to depend on the
imagecodecs package to actually decode DEFLATE-compressed data -- and a
real GitHub Actions test (see project history) confirmed imagecodecs
fails to build under Chaquopy too, the same category of failure as
GDAL/scipy/rasterio.

Copernicus's own documentation confirms exactly what this file needs to
handle, and nothing more: classic (non-Big) TIFF, single-band float32
samples, tiled layout, DEFLATE (zlib) compression, floating-point
horizontal-differencing predictor (TIFF Predictor=3), WGS84 lat/lon
georeferencing via ModelPixelScaleTag + ModelTiepointTag. Everything
below is scoped to exactly that, using only Python's built-in `struct`
and `zlib` modules plus numpy (both already proven to work under
Chaquopy in this project) -- no new dependency, no native-compile risk.

PER-IMAGE-TILE CACHING FIX (this session, found via real on-device
testing): offline_dem_store.py's earlier fix (this same session) cached
the CopernicusDemTile OBJECT itself, avoiding re-parsing this file's
TIFF header/IFD on every call -- but that header parse was always cheap
(a few KB). The real cost was one level deeper, in THIS file:
get_elevation() called _read_tile() completely fresh on EVERY call --
reopening the file, seeking, zlib-decompressing the tile's compressed
bytes, then undoing the floating-point predictor via a per-row Python
loop (_undo_floatingpoint_predictor). Copernicus DEM COGs are internally
subdivided into image tiles (commonly 512x512 pixels at this
resolution -- roughly 15km x 15km on the ground), while a typical
investigation AOI (hundreds of meters) is tiny by comparison -- meaning
virtually every one of up to 9,216 AOI grid-point lookups was landing in
the SAME single internal image tile, yet fully re-decompressing and
re-decoding it from scratch every single time. This was the actual
multi-minute bottleneck previously (wrongly) suspected to be a live-
network hang, then a redundant-file-open issue -- neither of those
fixes touched this cost, which is why the wait time barely changed
after either of them.

Fixed by caching each DECODED image tile's numpy array on the
CopernicusDemTile instance itself, keyed by that tile's index within the
file. Since the object itself is now already cached per file path
(offline_dem_store.py's fix), this cache naturally persists for the
lifetime of one investigation too -- so a given internal image tile is
now decompressed and predictor-undone at most ONCE per app process, no
matter how many of the AOI's grid points fall inside it.

TESTED SO FAR: the floating-point predictor undo logic was verified with
an exact bitwise round-trip against synthetic data. The full parsing
pipeline (TIFF header, IFD tags, tile lookup, decompression, predictor,
georeferencing) was verified end-to-end in a local sandbox test against
a hand-constructed synthetic COG-like file -- all pixel lookups (tile
corners, interior points, both tiles, out-of-bounds) matched exactly.
Two real bugs were found and fixed by that testing: (1) reading a tag's
externally-stored value moved the file pointer, so the NEXT tag was read
from the wrong position -- fixed by seeking to each IFD entry's absolute
computed position instead of relying on sequential reads; (2) float
division landing a hair below an intended integer pixel index (e.g.
2.999999999 instead of 3.0) was truncated by int() to the WRONG
neighboring pixel -- fixed by using round() instead. This session's own
per-tile caching addition has been reasoned through but not yet re-run
against that same sandbox fixture -- an honest gap to close alongside
the on-device retest this fix is going out for. Still NOT yet tested
against a real Copernicus-produced file (only a self-built synthetic
one) -- that remains the next honest step before this is fully trusted
on-device.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np


_FIELD_SIZE = {
    1: 1,   # BYTE
    2: 1,   # ASCII
    3: 2,   # SHORT
    4: 4,   # LONG
    5: 8,   # RATIONAL
    11: 4,  # FLOAT
    12: 8,  # DOUBLE
}

_TAG_IMAGE_WIDTH = 256
_TAG_IMAGE_LENGTH = 257
_TAG_BITS_PER_SAMPLE = 258
_TAG_COMPRESSION = 259
_TAG_PREDICTOR = 317
_TAG_TILE_WIDTH = 322
_TAG_TILE_LENGTH = 323
_TAG_TILE_OFFSETS = 324
_TAG_TILE_BYTE_COUNTS = 325
_TAG_SAMPLE_FORMAT = 339
_TAG_MODEL_PIXEL_SCALE = 33550
_TAG_MODEL_TIEPOINT = 33922

_COMPRESSION_DEFLATE = 8
_COMPRESSION_DEFLATE_OLD = 32946
_PREDICTOR_FLOATINGPOINT = 3
_SAMPLEFORMAT_IEEEFP = 3


class UnsupportedTiffError(Exception):
    """Raised when the file doesn't match the narrow shape this reader
    supports (see module docstring). Deliberately never silently guesses
    or falls back to a default -- an unsupported file is a real error,
    not something to paper over."""


@dataclass
class _TiffLayout:
    byte_order: str
    width: int
    height: int
    tile_width: int
    tile_length: int
    tile_offsets: Tuple[int, ...]
    tile_byte_counts: Tuple[int, ...]
    predictor: int
    compression: int
    pixel_scale_x: float
    pixel_scale_y: float
    tiepoint_pixel: Tuple[float, float]
    tiepoint_geo: Tuple[float, float]


def _read_ifd_entry_value(f, byte_order, field_type, count, raw4):
    size = _FIELD_SIZE.get(field_type)
    if size is None:
        raise UnsupportedTiffError(f"Unhandled TIFF field type {field_type}")
    total = size * count
    fmt_char = {1: 'B', 3: 'H', 4: 'I', 11: 'f', 12: 'd'}.get(field_type)
    if fmt_char is None:
        raise UnsupportedTiffError(f"Unhandled TIFF field type {field_type}")
    if total <= 4:
        data = raw4[:total]
    else:
        offset = struct.unpack(byte_order + 'I', raw4)[0]
        f.seek(offset)
        data = f.read(total)
    return struct.unpack(byte_order + fmt_char * count, data)


def _read_ifd(f, byte_order, ifd_offset):
    # Each entry is fixed-size (12 bytes) at a known position -- but
    # reading an entry's value can itself seek elsewhere in the file (for
    # values too large to fit inline, e.g. TileOffsets). So the position
    # of the NEXT entry must be computed from ifd_offset, never assumed
    # to follow on from wherever the previous entry's value-read left the
    # file pointer.
    f.seek(ifd_offset)
    (entry_count,) = struct.unpack(byte_order + 'H', f.read(2))
    tags = {}
    for i in range(entry_count):
        entry_pos = ifd_offset + 2 + i * 12
        f.seek(entry_pos)
        entry = f.read(12)
        tag_id, field_type, count = struct.unpack(byte_order + 'HHI', entry[:8])
        raw4 = entry[8:12]
        try:
            tags[tag_id] = _read_ifd_entry_value(f, byte_order, field_type, count, raw4)
        except UnsupportedTiffError:
            continue
    return tags


def _parse_layout(f) -> _TiffLayout:
    f.seek(0)
    header = f.read(8)
    if header[:2] == b'II':
        byte_order = '<'
    elif header[:2] == b'MM':
        byte_order = '>'
    else:
        raise UnsupportedTiffError(f"Not a TIFF file (bad byte-order marker {header[:2]!r})")
    magic = struct.unpack(byte_order + 'H', header[2:4])[0]
    if magic == 43:
        raise UnsupportedTiffError("BigTIFF is not supported by this reader")
    if magic != 42:
        raise UnsupportedTiffError(f"Unexpected TIFF magic number {magic}")
    (ifd_offset,) = struct.unpack(byte_order + 'I', header[4:8])

    tags = _read_ifd(f, byte_order, ifd_offset)

    def require(tag_id, name):
        if tag_id not in tags:
            raise UnsupportedTiffError(f"Missing required tag {name} ({tag_id})")
        return tags[tag_id]

    width = require(_TAG_IMAGE_WIDTH, "ImageWidth")[0]
    height = require(_TAG_IMAGE_LENGTH, "ImageLength")[0]
    tile_width = require(_TAG_TILE_WIDTH, "TileWidth")[0]
    tile_length = require(_TAG_TILE_LENGTH, "TileLength")[0]
    tile_offsets = require(_TAG_TILE_OFFSETS, "TileOffsets")
    tile_byte_counts = require(_TAG_TILE_BYTE_COUNTS, "TileByteCounts")
    compression = require(_TAG_COMPRESSION, "Compression")[0]
    predictor = tags.get(_TAG_PREDICTOR, (1,))[0]
    sample_format = tags.get(_TAG_SAMPLE_FORMAT, (1,))[0]
    bits_per_sample = tags.get(_TAG_BITS_PER_SAMPLE, (32,))[0]

    if compression not in (_COMPRESSION_DEFLATE, _COMPRESSION_DEFLATE_OLD):
        raise UnsupportedTiffError(f"Unsupported compression {compression}")
    if sample_format != _SAMPLEFORMAT_IEEEFP or bits_per_sample != 32:
        raise UnsupportedTiffError(f"Unsupported sample format/depth ({sample_format}, {bits_per_sample})")
    if predictor != _PREDICTOR_FLOATINGPOINT:
        raise UnsupportedTiffError(f"Unsupported predictor {predictor}")

    scale = tags.get(_TAG_MODEL_PIXEL_SCALE)
    tiepoint = tags.get(_TAG_MODEL_TIEPOINT)
    if scale is None or tiepoint is None:
        raise UnsupportedTiffError("Missing georeferencing tags")

    return _TiffLayout(
        byte_order=byte_order, width=width, height=height,
        tile_width=tile_width, tile_length=tile_length,
        tile_offsets=tile_offsets, tile_byte_counts=tile_byte_counts,
        predictor=predictor, compression=compression,
        pixel_scale_x=scale[0], pixel_scale_y=scale[1],
        tiepoint_pixel=(tiepoint[0], tiepoint[1]),
        tiepoint_geo=(tiepoint[3], tiepoint[4]),
    )


def _undo_floatingpoint_predictor(tile: np.ndarray) -> np.ndarray:
    tile_height, row_bytes = tile.shape
    tile_width = row_bytes // 4
    out = np.empty((tile_height, tile_width), dtype='>f4')
    for row in range(tile_height):
        planes = tile[row].reshape(4, tile_width)
        undone = np.cumsum(planes.astype(np.uint16), axis=1).astype(np.uint8)
        buf = undone.T.copy()
        out[row] = np.frombuffer(buf.tobytes(), dtype='>f4')
    return out.astype(np.float32)


def _read_tile(f, layout: _TiffLayout, tile_index: int) -> np.ndarray:
    offset = layout.tile_offsets[tile_index]
    byte_count = layout.tile_byte_counts[tile_index]
    f.seek(offset)
    compressed = f.read(byte_count)
    raw = zlib.decompress(compressed)
    expected = layout.tile_length * layout.tile_width * 4
    if len(raw) != expected:
        raise UnsupportedTiffError(f"Decompressed tile size {len(raw)} != expected {expected}")
    packed = np.frombuffer(raw, dtype=np.uint8).reshape(layout.tile_length, layout.tile_width * 4)
    return _undo_floatingpoint_predictor(packed)


class CopernicusDemTile:
    """Opens one downloaded Copernicus DEM COG file and answers elevation
    lookups for coordinates inside it. One instance per downloaded tile
    file -- offline_dem_store.py is responsible for picking the right
    tile file for a given coordinate and constructing (or, since this
    session's caching fix there, reusing a cached) instance of this."""

    def __init__(self, file_path: str):
        self._file_path = file_path
        with open(file_path, 'rb') as f:
            self._layout = _parse_layout(f)
        self._tiles_across = -(-self._layout.width // self._layout.tile_width)
        # THIS SESSION'S FIX: caches each DECODED internal image tile's
        # numpy array, keyed by tile_index. A typical investigation AOI
        # is far smaller than one internal image tile (see module
        # docstring's PER-IMAGE-TILE CACHING FIX note) -- without this,
        # get_elevation() re-decompressed and re-predictor-undid the
        # SAME tile bytes on every single one of up to ~9,216 AOI grid
        # points. Persists for the lifetime of this object, which
        # offline_dem_store.py now also caches per file path -- so in
        # practice a given image tile is decoded at most once per app
        # process, not once per elevation lookup.
        self._decoded_tile_cache: Dict[int, np.ndarray] = {}

    def _pixel_for_lonlat(self, lon: float, lat: float):
        # round(), not int(): floating-point division can land a hair
        # below the intended integer pixel index (e.g. 2.999999999
        # instead of 3.0), and int() truncates toward zero -- silently
        # returning the WRONG neighboring pixel instead of the intended
        # one. round() is the correct nearest-pixel behaviour here.
        tp_i, tp_j = self._layout.tiepoint_pixel
        tp_x, tp_y = self._layout.tiepoint_geo
        col = tp_i + (lon - tp_x) / self._layout.pixel_scale_x
        row = tp_j + (tp_y - lat) / self._layout.pixel_scale_y
        return round(row), round(col)

    def _get_decoded_tile(self, tile_index: int) -> np.ndarray:
        """Returns the decoded pixel array for this internal image tile,
        decoding (and caching) it on first request only -- see
        __init__'s _decoded_tile_cache and this class's own docstring."""
        cached = self._decoded_tile_cache.get(tile_index)
        if cached is not None:
            return cached
        with open(self._file_path, 'rb') as f:
            decoded = _read_tile(f, self._layout, tile_index)
        self._decoded_tile_cache[tile_index] = decoded
        return decoded

    def get_elevation(self, lon: float, lat: float) -> Optional[float]:
        """Nearest-pixel elevation lookup (no interpolation -- matches
        this reader's minimal scope; offline_dem_store.py can add
        bilinear interpolation across tile lookups later if needed, the
        same way np_ops.resample_bilinear already does for the live
        pipeline's rasters). Returns None if the coordinate falls outside
        this tile file's coverage.

        THIS SESSION'S FIX: fetches the decoded image tile via
        _get_decoded_tile() (cached per tile_index) instead of calling
        _read_tile() directly on every lookup -- see class docstring."""
        row, col = self._pixel_for_lonlat(lon, lat)
        if not (0 <= row < self._layout.height and 0 <= col < self._layout.width):
            return None
        tile_row = row // self._layout.tile_length
        tile_col = col // self._layout.tile_width
        tile_index = tile_row * self._tiles_across + tile_col
        tile = self._get_decoded_tile(tile_index)
        local_row = row % self._layout.tile_length
        local_col = col % self._layout.tile_width
        return float(tile[local_row, local_col])