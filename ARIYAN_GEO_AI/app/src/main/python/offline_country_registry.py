"""
offline_country_registry.py

Part of ARIYAN GEO AI's OFFLINE MODE extension.

This module is intentionally the very first piece of the offline system,
and it does nothing but hold configuration data -- no network calls, no
file I/O, no Android/Chaquopy interaction. That is deliberate: every other
offline module (offline_dem_store.py, offline_ndvi_store.py,
offline_data_manager.py) will import CountryConfig / get_country() from
here rather than hard-coding Iran's numbers, so adding a second country
later means adding one new entry below, not touching any downloader code.

THIS MODULE IS PART OF THE SEPARATE OFFLINE EXTENSION. It is never
imported by any existing live-pipeline file (dem_source_mobile.py,
ndvi_source_mobile.py, investigation_multi_mobile.py, evidence_record.py)
and does not change how the live/online investigation flow behaves.

ADDED THIS SESSION -- get_country_for_point(): the real-data-first /
offline-fallback design (offline_evidence_fallback.py) needs to find
which country's offline package (if any) covers a given investigation
coordinate, WITHOUT the user having to manually pick a country on the
main investigation screen -- they already picked it once, implicitly,
when they entered coordinates or used their GPS location. This is a
simple linear scan over _COUNTRIES' bounding boxes; fine at this
registry's current and realistically-expected size (a handful of
countries, not thousands).
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class CountryConfig:
    """
    Static configuration describing one country's offline data package.

    Nothing in this class is measured or fetched -- it is the *plan* for
    what offline_data_manager.py should go download, not a record of what
    has actually been downloaded (that lives in a separate per-country
    manifest.json written to device storage once a real download
    actually completes -- see offline_data_manager.py, not yet written).
    """

    name: str
    iso_code: str  # ISO 3166-1 alpha-2, used for the on-device folder name

    # Bounding box in WGS84 decimal degrees. Deliberately a simple
    # rectangle around the country, not its precise border polygon --
    # matches the architecture discussion: a rectangle is very slightly
    # wasteful in storage (some ocean/neighboring-country tiles get
    # pulled in along the edges) in exchange for real simplicity (no
    # polygon-clipping, no partial-tile logic). Padded a few tenths of a
    # degree beyond the country's actual extent on every side so a
    # coordinate near the border is never just outside the cached area.
    #
    # Visually confirmed by the user against real maps (Chabahar just
    # inside the south edge, the Aras River/Azerbaijan border just inside
    # the north edge, Tehran/Mashhad/Isfahan all well inside).
    south: float
    north: float
    west: float
    east: float

    # --- DEM ---
    # Matches the resolution decision from planning: 30m (COP30), the
    # same effective resolution the LIVE pipeline already fetches via
    # OpenTopography, so offline results stay scientifically consistent
    # with online ones instead of quietly being coarser.
    dem_resolution_m: int
    # Native AWS Open Data bucket + dataset folder prefix. Public bucket,
    # no AWS account, no API key -- see offline_data_manager.py (not yet
    # written) for the actual fetch logic. Deliberately NOT going through
    # OpenTopography's API here, to avoid its per-day call-count limits
    # (50/day for non-academic accounts, confirmed during planning).
    #
    # IMPORTANT, confirmed against the bucket's own documentation
    # (copernicus-dem-30m.s3.amazonaws.com/readme.html): the resolution
    # code embedded in the tile prefix is in ARC-SECONDS, not meters, and
    # counter-intuitively "10" means the 30m dataset (GLO-30) and "30"
    # means the 90m dataset (GLO-90). dem_dataset_prefix below was
    # originally written as "Copernicus_DSM_COG_30" by assumption and has
    # been corrected to "Copernicus_DSM_COG_10" after actually checking.
    dem_s3_bucket: str
    dem_dataset_prefix: str

    # --- NDVI ---
    # Sentinel-2 L2A source imagery, pulled from the public (non
    # Requester-Pays) COG bucket. IMPORTANT, confirmed during planning:
    # this must stay 'sentinel-cogs' (Element84/Earth Search, public) and
    # never get swapped for the older 'sentinel-s2-l2a' bucket (Sinergise,
    # Requester-Pays -- that one bills whoever downloads from it).
    ndvi_s3_bucket: str
    # How many most-recent days of Sentinel-2 scenes to pull for the
    # median composite. 30 days matches the planning decision: "as fresh
    # as possible, but an averaged/composite value is fine, not
    # day-by-day."
    ndvi_composite_window_days: int

    @property
    def storage_folder(self) -> str:
        """On-device folder name for this country's offline package,
        under the shared offline_data root (exact path decided in
        offline_dem_store.py / offline_ndvi_store.py, not yet written)."""
        return self.iso_code.lower()

    def contains(self, lat: float, lon: float) -> bool:
        """True if (lat, lon) falls inside this country's configured
        bounding box (the padded rectangle above, not its real border)."""
        return self.south <= lat <= self.north and self.west <= lon <= self.east


# --- Registry -------------------------------------------------------------
#
# Add a new country by adding one entry here. Nothing else in the offline
# module needs to change -- offline_data_manager.py reads whichever
# CountryConfig it's given.

_COUNTRIES: Dict[str, CountryConfig] = {
    "IR": CountryConfig(
        name="Iran",
        iso_code="IR",
        south=24.8,
        north=40.0,
        west=43.9,
        east=63.5,
        dem_resolution_m=30,
        dem_s3_bucket="copernicus-dem-30m",
        dem_dataset_prefix="Copernicus_DSM_COG_10",
        ndvi_s3_bucket="sentinel-cogs",
        ndvi_composite_window_days=30,
    ),
}


def get_country(iso_code: str) -> CountryConfig:
    """
    Look up a country's offline config by ISO 3166-1 alpha-2 code
    (case-insensitive). Raises KeyError with an honest message if the
    country hasn't been added yet -- never silently falls back to a
    default or guesses at values, matching this project's hard rule
    against fabricated/placeholder data.
    """
    key = iso_code.upper()
    if key not in _COUNTRIES:
        raise KeyError(
            f"No offline CountryConfig registered for '{iso_code}'. "
            f"Currently registered: {', '.join(_COUNTRIES.keys())}. "
            f"Add a new CountryConfig entry to _COUNTRIES to support it."
        )
    return _COUNTRIES[key]


def list_countries() -> Dict[str, str]:
    """Returns {iso_code: display_name} for every registered country."""
    return {code: cfg.name for code, cfg in _COUNTRIES.items()}


def get_country_for_point(lat: float, lon: float) -> Optional[CountryConfig]:
    """Returns the registered CountryConfig whose bounding box covers
    (lat, lon), or None if no registered country's offline package
    covers this coordinate (either because it's genuinely outside every
    registered country, or because that country simply hasn't been added
    to _COUNTRIES yet). Never raises -- 'no offline coverage here' is an
    ordinary, expected outcome for the live-fetch-fails fallback path in
    offline_evidence_fallback.py to handle honestly, not an error.

    If bounding boxes of two registered countries ever overlap (padded
    rectangles near a shared border, once a second country is added),
    this returns whichever is found first in _COUNTRIES -- acceptable
    for now since there is currently only one entry; revisit if that
    ever becomes a real ambiguity worth resolving properly."""
    for country in _COUNTRIES.values():
        if country.contains(lat, lon):
            return country
    return None
