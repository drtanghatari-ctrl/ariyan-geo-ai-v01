"""
land_cover_flags.py

WIDE-AREA SEARCH: LAND-COVER FLAGS ("is this candidate really just trees,
buildings or water?").

WHY THIS EXISTS: the Pass 1 detector scores DEM bumps. The public
Copernicus DEM (GLO-30) is a SURFACE model, so palm groves and buildings
show up as bumps exactly like a real mound does. In the first clean
196-tile Ctesiphon sweep (job ef20fd, 1963 candidates) 13 of the 20
highest-scoring candidates turned out to be palm groves or standing
buildings when checked against satellite imagery, while the one real
tell in the top 20 ranked only 7th. Refining the raw top N in Pass 2
would spend the daily API budget mostly on palms.

WHAT THIS DOES: for each candidate it reads the ESA WorldCover 2021 v200
10 m land-cover map (a public Cloud-Optimized GeoTIFF on AWS Open Data),
measures what share of the ground within about 60 m is tree cover,
built-up or open water, and stores those shares in its OWN table. A
candidate is FLAGGED when:
  - tree cover + built-up >= TREE_BUILT_THRESHOLD (0.20) of that window, or
  - the candidate's own pixel is open water, or
  - open water >= WATER_FRACTION_THRESHOLD (0.20) of that window (added
    2026-09-22 -- see CHANGELOG below).
FLAG, NOT DELETE: nothing is removed. Candidate rows, scores and
evidence are never touched. The flag only lets Pass 2 skip these
candidates (grand_project_refinement.select_refinement_candidates,
skip_flagged=True by default), and the user can choose to include them.
The raw shares are stored, not just the yes/no, so either threshold can
be changed later without downloading anything again.

WHAT IT CANNOT DO (honest limits):
- A real buried feature under an orchard or a field WILL be flagged too,
  because from above it is indistinguishable from an orchard or a field.
  That is the reason for "flag, not delete" and for the include option.
- WorldCover is a 2021 satellite classification at 10 m. New buildings,
  construction sites and small palm stands can be missed (a construction
  site was missed in the Ctesiphon check) and palms are sometimes labelled
  crop rather than tree.
- The threshold was tuned by looking at only about 5 spots. It is a
  starting rule, not a proven one.

NO EXISTING DETECTION CODE IS CHANGED. This file only READS candidates
(the same query grand_project_refinement uses) and writes ONLY to its own
table candidate_land_cover, created here with CREATE TABLE IF NOT EXISTS.
It deliberately has NO foreign key, so it can never block a delete in the
existing tables, and it does not use evidence_link, so the Steward and the
evidence views never see a new evidence type.

WHY A NEW HTTP READER: geotiff_cog_reader.py and sentinel2_cog_reader.py
read LOCAL files. WorldCover is ~99 MB per 3 x 3 degree tile, far too big
to download whole, so this file reads only the internal 1024 x 1024
blocks it needs, using HTTP Range requests (standard library only:
urllib, struct, zlib, plus numpy -- the same set already proven under
Chaquopy). It is scoped to exactly the WorldCover file shape (classic
TIFF, single-band uint8, tiled, DEFLATE, no predictor) and raises
UnsupportedLandCoverTiffError on anything else rather than guessing
(the Predictor=3 bug in geotiff_cog_reader.py is the reason for that
rule: a decoder must never assume).

VERIFICATION STATUS: written 2026-09-21. In a sandbox, against the REAL
N33E042 WorldCover tile over the network: decoded windows were compared
with rasterio, and the stored shares for all 1963 ef20fd candidates were
compared with an independent rasterio calculation. The reader and the
ORIGINAL flag_reason() (center-pixel water, tree+built window fraction)
were run on real hardware as part of job ef20fd's 2026-09-21 Pass 2
selection (1228 of 1963 candidates flagged).

CHANGELOG:
- 2026-09-22: added the window-based water rule (frac_water >=
  WATER_FRACTION_THRESHOLD) to flag_reason(), and added l.frac_water to
  the SELECT in job_flags() (it was being stored but not read back,
  which would have made the new rule crash on the first real row).
  Trigger: two candidates from job ef20fd's Pass 2 output (NEW #1 at
  33.057946,44.627758 and candidate 'E' at 33.10143,44.61275) sat on the
  narrow berm between aquaculture ponds -- non-water center pixel, but a
  60 m window that was mostly open water -- so the original center-pixel
  -only water rule missed both, and they were only caught by manual
  satellite review after already consuming Pass 2 DEM budget. No reader
  code, table schema, or existing stored row is touched by this change;
  frac_water was already being sampled and written for every candidate,
  just never read back for the flag decision. Sandbox-checked (ast.parse,
  manual logic trace) only -- NOT yet run on real hardware against this
  candidate or any other. Treat the water-fraction path specifically as
  unverified on-device until it has been.
"""

from __future__ import annotations

import json
import math
import struct
import time
import urllib.error
import urllib.request
import zlib
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

import grand_project_db as db

# ============================ CONSTANTS ============================

WORLDCOVER_SOURCE = "ESA_WorldCover_v200_2021"
WORLDCOVER_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
)

# The window is a square of (2 * WINDOW_HALF_PX + 1) pixels a side: 13 x 13
# pixels, about 120 m across at 10 m pixels, i.e. about 60 m each way.
WINDOW_HALF_PX = 6

# Flag rule (see the module docstring). Fractions are stored, so changing
# these needs no new download.
TREE_BUILT_THRESHOLD = 0.20
WATER_FRACTION_THRESHOLD = 0.20
WATER_CLASS = 80

REASON_TREE_OR_BUILT = "tree_or_built"
REASON_WATER = "water"

# ESA WorldCover class codes -> the share column each one counts toward.
# 10 tree cover, 95 mangroves (tree-like), 20 shrubland, 30 grassland,
# 40 cropland, 50 built-up, 60 bare / sparse vegetation, 80 open water.
# Anything else (70 snow/ice, 90 herbaceous wetland, 100 moss/lichen)
# is counted as "other". Class 0 is no-data and is not counted at all.
_CLASS_TO_COLUMN = {
    10: "frac_tree", 95: "frac_tree",
    20: "frac_shrub",
    30: "frac_grass",
    40: "frac_crop",
    50: "frac_built",
    60: "frac_bare",
    80: "frac_water",
}
_FRAC_COLUMNS = [
    "frac_tree", "frac_shrub", "frac_grass", "frac_crop",
    "frac_built", "frac_bare", "frac_water", "frac_other",
]

_HEAD_BYTES = 262144        # first 256 KB: TIFF header + IFD + tag arrays
_BLOCK_CACHE_SIZE = 6       # decoded 1024 x 1024 blocks kept in memory
_HTTP_TIMEOUT_S = 60
_HTTP_RETRIES = 3

_TAG_IMAGE_WIDTH = 256
_TAG_IMAGE_LENGTH = 257
_TAG_BITS_PER_SAMPLE = 258
_TAG_COMPRESSION = 259
_TAG_SAMPLES_PER_PIXEL = 277
_TAG_PREDICTOR = 317
_TAG_TILE_WIDTH = 322
_TAG_TILE_LENGTH = 323
_TAG_TILE_OFFSETS = 324
_TAG_TILE_BYTE_COUNTS = 325
_TAG_SAMPLE_FORMAT = 339
_TAG_MODEL_PIXEL_SCALE = 33550
_TAG_MODEL_TIEPOINT = 33922

_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8}
_TYPE_FMT = {1: "B", 3: "H", 4: "I", 11: "f", 12: "d"}

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS candidate_land_cover (
    candidate_id  TEXT PRIMARY KEY,
    computed_at   TEXT NOT NULL,
    source        TEXT NOT NULL,
    window_px     INTEGER NOT NULL,
    valid_px      INTEGER NOT NULL,
    center_class  INTEGER,
    frac_tree     REAL,
    frac_shrub    REAL,
    frac_grass    REAL,
    frac_crop     REAL,
    frac_built    REAL,
    frac_bare     REAL,
    frac_water    REAL,
    frac_other    REAL
)
"""


class LandCoverError(Exception):
    """A genuine caller error (for example an unknown job id)."""


class LandCoverDataUnavailable(LandCoverError):
    """The land-cover tile could not be read (no network, or no tile
    exists for that area, for example open ocean)."""


class UnsupportedLandCoverTiffError(LandCoverError):
    """The file is outside the narrow shape this reader supports. Never
    silently guessed around."""


# ============================ HTTP ============================

def _http_range(url: str, start: int, end: int) -> bytes:
    """Reads bytes [start, end] (inclusive) of `url` with an HTTP Range
    request. Requires a 206 answer: a server that ignores Range and would
    send the whole ~99 MB file is refused, not downloaded."""
    last_exc: Optional[BaseException] = None
    for attempt in range(_HTTP_RETRIES):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Range": f"bytes={start}-{end}",
                    "User-Agent": "ARIYAN-GEO-AI/land-cover",
                },
            )
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                if status != 206:
                    raise LandCoverDataUnavailable(
                        f"Server answered HTTP {status} instead of 206 to a "
                        f"Range request for {url}; refusing to download the whole file.")
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                # No such tile (open ocean) -- retrying will not help.
                raise LandCoverDataUnavailable(
                    f"No land-cover tile at {url} (HTTP {exc.code}).") from exc
            last_exc = exc
        except LandCoverDataUnavailable:
            raise
        except Exception as exc:  # network trouble: retry
            last_exc = exc
        if attempt < _HTTP_RETRIES - 1:
            time.sleep(1.5 * (attempt + 1))
    raise LandCoverDataUnavailable(
        f"Could not read land cover from {url}: {type(last_exc).__name__}: {last_exc}")


def worldcover_tile_name(lat: float, lon: float) -> str:
    """WorldCover 2021 tiles are 3 x 3 degrees, named by their SOUTH-WEST
    corner, for example N33E042 covers latitude 33..36, longitude 42..45."""
    lat0 = int(math.floor(lat / 3.0)) * 3
    lon0 = int(math.floor(lon / 3.0)) * 3
    ns = "N" if lat0 >= 0 else "S"
    ew = "E" if lon0 >= 0 else "W"
    return f"{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}"


# ============================ READER ============================

class WorldCoverHttpTile:
    """One WorldCover COG, read lazily: the header up front, image blocks
    only when a window needs them. `http_get(url, start, end)` can be
    replaced (tests read a local file through it)."""

    def __init__(self, url: str,
                 http_get: Optional[Callable[[str, int, int], bytes]] = None,
                 block_cache_size: int = _BLOCK_CACHE_SIZE):
        self.url = url
        self._get = http_get or _http_range
        self._cache: "OrderedDict[Tuple[int, int], np.ndarray]" = OrderedDict()
        self._cache_size = max(1, int(block_cache_size))
        self._head = self._get(url, 0, _HEAD_BYTES - 1)
        self._parse()

    # ---- low-level reads ----

    def _read(self, offset: int, length: int) -> bytes:
        if length <= 0:
            return b""
        if offset + length <= len(self._head):
            return self._head[offset:offset + length]
        data = self._get(self.url, offset, offset + length - 1)
        if len(data) != length:
            raise LandCoverDataUnavailable(
                f"Short read at offset {offset}: wanted {length} bytes, got {len(data)}.")
        return data

    def _values(self, tag: int) -> Tuple[Any, ...]:
        typ, cnt, value_field = self._tags[tag]
        if typ not in _TYPE_FMT:
            raise UnsupportedLandCoverTiffError(f"TIFF tag {tag} has unsupported type {typ}.")
        size = _TYPE_SIZE[typ] * cnt
        if size <= 4:
            data = value_field[:size]
        else:
            offset = struct.unpack(self._e + "I", value_field)[0]
            data = self._read(offset, size)
        return struct.unpack(f"{self._e}{cnt}{_TYPE_FMT[typ]}", data)

    def _scalar(self, tag: int, default: Optional[int] = None) -> int:
        if tag not in self._tags:
            if default is None:
                raise UnsupportedLandCoverTiffError(f"Required TIFF tag {tag} is missing.")
            return default
        return int(self._values(tag)[0])

    # ---- header ----

    def _parse(self) -> None:
        h = self._head
        if len(h) < 16:
            raise UnsupportedLandCoverTiffError("File is too short to be a TIFF.")
        if h[:2] == b"II":
            self._e = "<"
        elif h[:2] == b"MM":
            self._e = ">"
        else:
            raise UnsupportedLandCoverTiffError("Not a TIFF file (bad byte-order mark).")
        magic = struct.unpack(self._e + "H", h[2:4])[0]
        if magic != 42:
            raise UnsupportedLandCoverTiffError(
                f"TIFF magic {magic} is not classic TIFF (42); BigTIFF is not supported.")
        ifd_off = struct.unpack(self._e + "I", h[4:8])[0]
        n_entries = struct.unpack(self._e + "H", self._read(ifd_off, 2))[0]
        raw = self._read(ifd_off + 2, n_entries * 12)
        self._tags: Dict[int, Tuple[int, int, bytes]] = {}
        for i in range(n_entries):
            entry = raw[i * 12:(i + 1) * 12]
            tag, typ, cnt = struct.unpack(self._e + "HHI", entry[:8])
            self._tags[tag] = (typ, cnt, entry[8:12])

        self.width = self._scalar(_TAG_IMAGE_WIDTH)
        self.height = self._scalar(_TAG_IMAGE_LENGTH)
        self.tile_w = self._scalar(_TAG_TILE_WIDTH)
        self.tile_h = self._scalar(_TAG_TILE_LENGTH)
        self._compression = self._scalar(_TAG_COMPRESSION)
        if self._compression not in (1, 8, 32946):
            raise UnsupportedLandCoverTiffError(
                f"Compression {self._compression} is not supported (need none or DEFLATE).")
        if self._scalar(_TAG_BITS_PER_SAMPLE, 8) != 8:
            raise UnsupportedLandCoverTiffError("Only 8-bit samples are supported.")
        if self._scalar(_TAG_SAMPLES_PER_PIXEL, 1) != 1:
            raise UnsupportedLandCoverTiffError("Only single-band files are supported.")
        if self._scalar(_TAG_SAMPLE_FORMAT, 1) != 1:
            raise UnsupportedLandCoverTiffError("Only unsigned-integer samples are supported.")
        if self._scalar(_TAG_PREDICTOR, 1) != 1:
            raise UnsupportedLandCoverTiffError(
                "A predictor is set on this file; this reader supports none.")

        self._offsets = self._values(_TAG_TILE_OFFSETS)
        self._counts = self._values(_TAG_TILE_BYTE_COUNTS)
        self._tiles_across = (self.width + self.tile_w - 1) // self.tile_w
        self._tiles_down = (self.height + self.tile_h - 1) // self.tile_h
        if len(self._offsets) < self._tiles_across * self._tiles_down:
            raise UnsupportedLandCoverTiffError("Tile offset table is shorter than the tile grid.")

        scale = self._values(_TAG_MODEL_PIXEL_SCALE)
        tie = self._values(_TAG_MODEL_TIEPOINT)
        if len(scale) < 2 or len(tie) < 6:
            raise UnsupportedLandCoverTiffError("Georeferencing tags are incomplete.")
        self._sx = float(scale[0])
        self._sy = float(scale[1])
        self._x0 = float(tie[3]) - float(tie[0]) * self._sx   # west edge, degrees
        self._y0 = float(tie[4]) + float(tie[1]) * self._sy   # north edge, degrees

    # ---- georeferencing ----

    def pixel_of(self, lon: float, lat: float) -> Tuple[float, float]:
        """(column, row) as continuous pixel coordinates, pixel EDGE
        convention: int(floor()) gives the pixel that contains the point."""
        return (lon - self._x0) / self._sx, (self._y0 - lat) / self._sy

    # ---- decoding ----

    def _block(self, bi: int, bj: int) -> np.ndarray:
        key = (bi, bj)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        idx = bi * self._tiles_across + bj
        offset = int(self._offsets[idx])
        count = int(self._counts[idx])
        if count == 0:
            arr = np.zeros((self.tile_h, self.tile_w), dtype=np.uint8)   # empty block = no data
        else:
            data = self._read(offset, count)
            if self._compression in (8, 32946):
                data = zlib.decompress(data)
            expected = self.tile_h * self.tile_w
            if len(data) != expected:
                raise UnsupportedLandCoverTiffError(
                    f"Block ({bi},{bj}) decoded to {len(data)} bytes, expected {expected}.")
            arr = np.frombuffer(data, dtype=np.uint8).reshape(self.tile_h, self.tile_w)
        self._cache[key] = arr
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return arr

    def read_window(self, r0: int, r1: int, c0: int, c1: int) -> np.ndarray:
        """Pixels rows [r0, r1) x columns [c0, c1), clipped to the image.
        Assembles from as many internal blocks as the window touches."""
        r0 = max(0, int(r0)); c0 = max(0, int(c0))
        r1 = min(self.height, int(r1)); c1 = min(self.width, int(c1))
        if r1 <= r0 or c1 <= c0:
            return np.zeros((0, 0), dtype=np.uint8)
        out = np.zeros((r1 - r0, c1 - c0), dtype=np.uint8)
        for bi in range(r0 // self.tile_h, (r1 - 1) // self.tile_h + 1):
            for bj in range(c0 // self.tile_w, (c1 - 1) // self.tile_w + 1):
                blk = self._block(bi, bj)
                br0, bc0 = bi * self.tile_h, bj * self.tile_w
                rr0, rr1 = max(r0, br0), min(r1, br0 + self.tile_h)
                cc0, cc1 = max(c0, bc0), min(c1, bc0 + self.tile_w)
                out[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0] = blk[rr0 - br0:rr1 - br0, cc0 - bc0:cc1 - bc0]
        return out


# ============================ SAMPLING + RULE ============================

def sample_fractions(reader: WorldCoverHttpTile, lat: float, lon: float,
                     half_px: int = WINDOW_HALF_PX) -> Optional[Dict[str, Any]]:
    """Land-cover shares in the square window around (lat, lon). Returns
    None when the point is outside the tile or the window has no valid
    pixel (an honest gap; no row is written)."""
    col_f, row_f = reader.pixel_of(lon, lat)
    r = int(math.floor(row_f))
    c = int(math.floor(col_f))
    if r < 0 or c < 0 or r >= reader.height or c >= reader.width:
        return None
    window = reader.read_window(r - half_px, r + half_px + 1, c - half_px, c + half_px + 1)
    valid = window != 0
    n_valid = int(valid.sum())
    if n_valid == 0:
        return None
    counts = np.bincount(window[valid].ravel(), minlength=256)
    result: Dict[str, Any] = {col: 0.0 for col in _FRAC_COLUMNS}
    other = n_valid
    for cls, col in _CLASS_TO_COLUMN.items():
        n = int(counts[cls])
        result[col] += n / n_valid
        other -= n
    result["frac_other"] = max(0, other) / n_valid
    center = int(reader.read_window(r, r + 1, c, c + 1)[0, 0])
    result["center_class"] = center if center != 0 else None
    result["valid_px"] = n_valid
    result["window_px"] = 2 * half_px + 1
    return result


def flag_reason(row: Any) -> Optional[str]:
    """The flag rule, applied to one stored row (a dict or sqlite3.Row,
    must include frac_water -- see job_flags()'s SELECT). Returns
    REASON_WATER, REASON_TREE_OR_BUILT or None (not flagged)."""
    if row["center_class"] == WATER_CLASS:
        return REASON_WATER
    water = row["frac_water"] or 0.0
    if water >= WATER_FRACTION_THRESHOLD:
        # Added 2026-09-22: catches a candidate sitting on the berm
        # between ponds -- its own pixel need not be water for its 60 m
        # surroundings to be mostly water. See module CHANGELOG.
        return REASON_WATER
    tree = row["frac_tree"] or 0.0
    built = row["frac_built"] or 0.0
    if tree + built >= TREE_BUILT_THRESHOLD:
        return REASON_TREE_OR_BUILT
    return None


# ============================ DATABASE ============================

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_table(conn) -> None:
    db.initialize_schema(conn)
    with conn:
        conn.execute(_TABLE_SQL)


def _job_candidate_rows(conn, job_id: str, only_unchecked: bool) -> List[Any]:
    sql = """
        SELECT c.id AS id, c.lat AS lat, c.lon AS lon
        FROM candidate c
        WHERE c.investigation_id IN (
            SELECT investigation_id FROM wide_area_search_tile
            WHERE job_id = ? AND investigation_id IS NOT NULL
        )
    """
    if only_unchecked:
        sql += " AND c.id NOT IN (SELECT candidate_id FROM candidate_land_cover)"
    return conn.execute(sql, (job_id,)).fetchall()


def job_flags(db_root: str, job_id: str) -> Dict[str, Any]:
    """Read-only: {"candidates": N, "checked": N, "flagged": {candidate_id:
    reason}, "by_reason": {reason: count}} for a job. Never touches the
    network. Candidates that were never checked simply are not in
    "flagged" (they are treated as not flagged)."""
    conn = db.get_connection(db_root)
    try:
        _ensure_table(conn)
        n_candidates = len(_job_candidate_rows(conn, job_id, only_unchecked=False))
        rows = conn.execute(
            """
            SELECT l.candidate_id, l.center_class, l.frac_tree, l.frac_built,
                   l.frac_water
            FROM candidate_land_cover l
            JOIN candidate c ON c.id = l.candidate_id
            WHERE c.investigation_id IN (
                SELECT investigation_id FROM wide_area_search_tile
                WHERE job_id = ? AND investigation_id IS NOT NULL
            )
            """,
            (job_id,),
        ).fetchall()
        flagged: Dict[str, str] = {}
        by_reason: Dict[str, int] = {}
        for row in rows:
            reason = flag_reason(row)
            if reason:
                flagged[row["candidate_id"]] = reason
                by_reason[reason] = by_reason.get(reason, 0) + 1
        return {
            "candidates": n_candidates,
            "checked": len(rows),
            "flagged": flagged,
            "by_reason": by_reason,
        }
    finally:
        conn.close()


def ensure_job_land_cover(
    db_root: str, job_id: str,
    http_get: Optional[Callable[[str, int, int], bytes]] = None,
) -> Dict[str, Any]:
    """Makes sure every candidate of the job has a land-cover row, reading
    WorldCover for those that do not. Candidates already checked are not
    read again, so calling this repeatedly is cheap. A network or tile
    problem is REPORTED in the result ("problem"), never raised: the
    caller carries on without a filter for the unchecked candidates. Only
    an unknown job id raises LandCoverError."""
    started = time.time()
    if db.get_wide_area_search_job(db_root, job_id) is None:
        raise LandCoverError(f"No wide-area search job with id {job_id!r} was found.")

    conn = db.get_connection(db_root)
    problems: List[str] = []
    newly = 0
    no_data = 0
    unavailable = 0
    try:
        _ensure_table(conn)
        todo = _job_candidate_rows(conn, job_id, only_unchecked=True)
        already = len(_job_candidate_rows(conn, job_id, only_unchecked=False)) - len(todo)

        groups: Dict[str, List[Any]] = {}
        for row in todo:
            if row["lat"] is None or row["lon"] is None:
                no_data += 1
                continue
            groups.setdefault(worldcover_tile_name(row["lat"], row["lon"]), []).append(row)

        for tile_name, rows in groups.items():
            try:
                reader = WorldCoverHttpTile(WORLDCOVER_URL.format(tile=tile_name), http_get=http_get)
            except LandCoverError as exc:
                problems.append(f"{tile_name}: {exc}")
                unavailable += len(rows)
                continue
            except Exception as exc:
                problems.append(f"{tile_name}: {type(exc).__name__}: {exc}")
                unavailable += len(rows)
                continue

            inserts = []
            for k, row in enumerate(rows):
                try:
                    s = sample_fractions(reader, row["lat"], row["lon"])
                except LandCoverError as exc:
                    # A block failed mid-way (network): stop this tile, keep
                    # what was read, report the rest as unavailable.
                    problems.append(f"{tile_name}: {exc}")
                    unavailable += len(rows) - k
                    break
                except Exception as exc:
                    problems.append(f"{tile_name}: {type(exc).__name__}: {exc}")
                    unavailable += len(rows) - k
                    break
                if s is None:
                    no_data += 1
                    continue
                inserts.append((
                    row["id"], _now_iso(), WORLDCOVER_SOURCE, s["window_px"], s["valid_px"],
                    s["center_class"], s["frac_tree"], s["frac_shrub"], s["frac_grass"],
                    s["frac_crop"], s["frac_built"], s["frac_bare"], s["frac_water"],
                    s["frac_other"],
                ))
            if inserts:
                with conn:
                    conn.executemany(
                        """
                        INSERT OR REPLACE INTO candidate_land_cover
                            (candidate_id, computed_at, source, window_px, valid_px,
                             center_class, frac_tree, frac_shrub, frac_grass, frac_crop,
                             frac_built, frac_bare, frac_water, frac_other)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        inserts,
                    )
                newly += len(inserts)
    finally:
        conn.close()

    flags = job_flags(db_root, job_id)
    result: Dict[str, Any] = {
        "job_id": job_id,
        "source": WORLDCOVER_SOURCE,
        "candidates": flags["candidates"],
        "already_checked": already,
        "newly_checked": newly,
        "no_land_cover_data": no_data,
        "could_not_read": unavailable,
        "flagged_total": len(flags["flagged"]),
        "flagged_by_reason": flags["by_reason"],
        "seconds": round(time.time() - started, 1),
    }
    if problems:
        # The key is ABSENT (not null) when there is no problem, because
        # org.json's optString() does not apply its fallback to a present
        # JSON null.
        result["problem"] = "; ".join(problems)[:600]
    return result


def ensure_job_land_cover_json(db_root: str, job_id: str) -> str:
    """Chaquopy-facing wrapper: JSON string of ensure_job_land_cover()."""
    return json.dumps(ensure_job_land_cover(db_root, job_id), default=str)


def job_land_cover_summary_json(db_root: str, job_id: str) -> str:
    """Read-only, no network: how many of the job's candidates are checked
    and flagged (without the per-candidate map)."""
    flags = job_flags(db_root, job_id)
    return json.dumps({
        "job_id": job_id,
        "candidates": flags["candidates"],
        "checked": flags["checked"],
        "flagged_total": len(flags["flagged"]),
        "flagged_by_reason": flags["by_reason"],
        "threshold_tree_plus_built": TREE_BUILT_THRESHOLD,
        "threshold_water_fraction": WATER_FRACTION_THRESHOLD,
    })
