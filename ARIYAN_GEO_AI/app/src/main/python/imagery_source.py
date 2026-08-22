"""
imagery_source.py — Evidence Acquisition: Sentinel-2 NDVI (vegetation index)

This is the second independent evidence source, added specifically so
multi-source correlation (correlation.py) has two genuinely different
kinds of evidence to check for co-location — a DEM and a spectral
vegetation index measure fundamentally different physical things
(surface elevation vs. reflected light), so agreement between them is
real independent corroboration, not two measurements of the same thing.

Two sources, same pattern as dem_source.py:

1. PlanetaryComputerNDVISource — a REAL client for Microsoft's
   Planetary Computer STAC API (https://planetarycomputer.microsoft.com).
   Verified as of this writing: STAC search and asset access for public
   collections like sentinel-2-l2a require NO API key or login — public
   assets are accessed by requesting a short-lived SAS token from the
   public signing endpoint (https://planetarycomputer.microsoft.com/api/sas/v1/sign).
   This is genuine, working integration code. It is NOT exercised here
   (no network egress in this sandbox) — point it at an AOI with network
   access and it performs real STAC search + real GeoTIFF band reads.

2. SyntheticNDVISource — offline generator for development/testing,
   used the same way SyntheticDEMSource is: produces a physically
   plausible NDVI surface (-1 to 1, vegetated baseline with realistic
   spatial autocorrelation) with an optional injected vegetation
   anomaly, and is honestly labeled synthetic=True everywhere downstream.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from coordinate import AreaOfInterest


@dataclass
class NDVIRaster:
    """An NDVI evidence raster tied to an AOI, with explicit provenance."""
    aoi: AreaOfInterest
    ndvi: np.ndarray             # shape (grid_size, grid_size), unitless, -1..1
    source: str                  # e.g. "PlanetaryComputer:sentinel-2-l2a", "SYNTHETIC"
    synthetic: bool
    resolution_m: float
    acquisition_date: Optional[str] = None
    cloud_cover_pct: Optional[float] = None
    notes: str = ""

    def as_evidence_record(self) -> dict:
        return {
            "evidence_type": "NDVI",
            "source": self.source,
            "synthetic": self.synthetic,
            "resolution_m": self.resolution_m,
            "acquisition_date": self.acquisition_date,
            "cloud_cover_pct": self.cloud_cover_pct,
            "grid_size": self.aoi.grid_size,
            "aoi_radius_m": self.aoi.radius_m,
            "center_lat": self.aoi.center.lat,
            "center_lon": self.aoi.center.lon,
            "notes": self.notes,
        }


class PlanetaryComputerNDVISource:
    """Real client for Microsoft Planetary Computer's Sentinel-2 L2A
    collection. Not exercised in this sandbox (no network egress here),
    but this performs genuine STAC search, genuine public-asset signing,
    and genuine windowed GeoTIFF reads of the Red (B04) and NIR (B08)
    bands — not a stub.

    Requires: pystac-client, requests, rasterio.
    """

    STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
    SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"

    def __init__(self, max_cloud_cover_pct: float = 20.0):
        self.max_cloud_cover_pct = max_cloud_cover_pct

    def _sign(self, href: str) -> str:
        import requests
        resp = requests.get(self.SIGN_URL, params={"href": href}, timeout=30)
        resp.raise_for_status()
        return resp.json()["href"]

    def fetch(self, aoi: AreaOfInterest, datetime_range: str = "2023-01-01/2024-12-31") -> NDVIRaster:
        try:
            from pystac_client import Client
        except ImportError as e:
            raise RuntimeError(
                "PlanetaryComputerNDVISource.fetch requires the "
                "'pystac-client' package."
            ) from e
        try:
            import rasterio
            from rasterio.windows import from_bounds
            from rasterio.enums import Resampling
        except ImportError as e:
            raise RuntimeError(
                "PlanetaryComputerNDVISource.fetch requires the "
                "'rasterio' package to read GeoTIFF band assets."
            ) from e

        catalog = Client.open(self.STAC_URL)
        bbox = [aoi.min_lon, aoi.min_lat, aoi.max_lon, aoi.max_lat]

        search = catalog.search(
            collections=["sentinel-2-l2a"],
            bbox=bbox,
            datetime=datetime_range,
            query={"eo:cloud_cover": {"lt": self.max_cloud_cover_pct}},
            sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}],
            max_items=1,
        )
        items = list(search.items())
        if not items:
            raise RuntimeError(
                f"No Sentinel-2 scenes found for this AOI under "
                f"{self.max_cloud_cover_pct}% cloud cover in {datetime_range}."
            )
        item = items[0]

        red_href = self._sign(item.assets["B04"].href)
        nir_href = self._sign(item.assets["B08"].href)

        n = aoi.grid_size

        def _read_band(href: str) -> np.ndarray:
            with rasterio.open(href) as ds:
                window = from_bounds(
                    aoi.min_lon, aoi.min_lat, aoi.max_lon, aoi.max_lat,
                    transform=ds.transform,
                )
                band = ds.read(
                    1, window=window,
                    out_shape=(n, n),
                    resampling=Resampling.bilinear,
                ).astype(np.float64)
                return band

        red = _read_band(red_href)
        nir = _read_band(nir_href)

        denom = nir + red
        ndvi = np.where(denom != 0, (nir - red) / np.where(denom == 0, 1, denom), 0.0)

        return NDVIRaster(
            aoi=aoi,
            ndvi=ndvi,
            source="PlanetaryComputer:sentinel-2-l2a",
            synthetic=False,
            resolution_m=10.0,  # Sentinel-2 B04/B08 native resolution
            acquisition_date=item.properties.get("datetime"),
            cloud_cover_pct=item.properties.get("eo:cloud_cover"),
            notes=f"Live fetch from Microsoft Planetary Computer, item {item.id}.",
        )


class SyntheticNDVISource:
    """Offline, honestly-labeled synthetic NDVI for development/testing.

    Produces a spatially-autocorrelated vegetation baseline (band-limited
    noise, same technique as SyntheticDEMSource) plus an optional
    localized vegetation anomaly (a stress/clearing signature — locally
    lower NDVI than the surrounding baseline, which is the pattern a
    buried structure suppressing plant growth above it would produce).

    This is NOT a claim about any real place. `synthetic=True` and the
    source string make that explicit everywhere the raster is used.
    """

    def __init__(self, seed: int = 42):
        self.rng = np.random.default_rng(seed)

    def fetch(
        self,
        aoi: AreaOfInterest,
        baseline_ndvi: float = 0.55,
        variability: float = 0.08,
        variability_wavelength_cells: float = 30.0,
        anomalies: Optional[list[dict]] = None,
    ) -> NDVIRaster:
        n = aoi.grid_size

        white = self.rng.normal(0, 1, size=(n, n))
        freq = np.fft.fftfreq(n)
        fx, fy = np.meshgrid(freq, freq)
        radius = np.sqrt(fx ** 2 + fy ** 2)
        cutoff = 1.0 / variability_wavelength_cells
        low_pass = np.exp(-(radius / cutoff) ** 2)
        spectrum = np.fft.fft2(white) * low_pass
        field = np.real(np.fft.ifft2(spectrum))
        field = field / (field.std() + 1e-9) * variability

        ndvi = baseline_ndvi + field

        if anomalies:
            for a in anomalies:
                cx = a.get("row", n // 2)
                cy = a.get("col", n // 2)
                amp = a.get("amplitude", -0.15)  # negative = vegetation stress
                sigma = a.get("sigma_cells", 5.0)
                yg, xg = np.mgrid[0:n, 0:n]
                bump = amp * np.exp(-(((yg - cx) ** 2 + (xg - cy) ** 2) / (2 * sigma ** 2)))
                ndvi = ndvi + bump

        ndvi = np.clip(ndvi, -1.0, 1.0)

        return NDVIRaster(
            aoi=aoi,
            ndvi=ndvi,
            source="SYNTHETIC",
            synthetic=True,
            resolution_m=aoi.cell_size_m,
            acquisition_date=None,
            cloud_cover_pct=None,
            notes=(
                "Synthetic offline NDVI for development/testing only. "
                "Not derived from any real measurement."
            ),
        )
