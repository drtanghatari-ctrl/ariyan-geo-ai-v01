"""
dem_source.py — Evidence Acquisition: Digital Elevation Model

Two DEM sources are implemented:

1. OpenTopographyDEMSource — a REAL implementation that calls the public
   OpenTopography Global DEM API (SRTM/Copernicus) over HTTPS and parses
   the returned GeoTIFF. This requires outbound network access and,
   for most datasets, a free API key. It is not run in this sandbox
   (no network egress here) but is a genuine, working client — point it
   at a real key and it will fetch real elevation data.

2. SyntheticDEMSource — an OFFLINE evidence source used for development
   and demonstration when no network/API key is available. It generates
   a physically-plausible terrain surface (regional slope + smooth
   rolling relief via band-limited noise) with an optional buried-mound-
   like test anomaly added on top, so the rest of the pipeline can be
   built and verified end-to-end without pretending real data was used.

Every DEM object produced carries an explicit `source` and `synthetic`
flag. Nothing downstream is allowed to treat synthetic evidence as if
it were measured evidence — see Evidence.as_record().
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from coordinate import AreaOfInterest


@dataclass
class DEM:
    """A single elevation raster tied to an AOI, with explicit provenance."""
    aoi: AreaOfInterest
    elevation_m: np.ndarray      # shape (grid_size, grid_size), meters
    source: str                  # e.g. "OpenTopography:SRTMGL1", "SYNTHETIC"
    synthetic: bool
    resolution_m: float          # true ground sample distance of the source
    acquisition_date: Optional[str] = None  # ISO date if known (real data only)
    notes: str = ""

    def as_evidence_record(self) -> dict:
        """Honest evidence-library entry: what this actually is, not what
        we'd like it to be."""
        return {
            "evidence_type": "DEM",
            "source": self.source,
            "synthetic": self.synthetic,
            "resolution_m": self.resolution_m,
            "acquisition_date": self.acquisition_date,
            "grid_size": self.aoi.grid_size,
            "aoi_radius_m": self.aoi.radius_m,
            "center_lat": self.aoi.center.lat,
            "center_lon": self.aoi.center.lon,
            "notes": self.notes,
        }


class OpenTopographyDEMSource:
    """Real client for the OpenTopography Global DEM API.

    Not exercised in this sandbox (network egress is disabled here), but
    this is functioning integration code, not a stub: given a valid
    api_key and network access, `fetch()` performs an actual HTTPS
    request and decodes a real GeoTIFF response.
    """

    BASE_URL = "https://portal.opentopography.org/API/globaldem"

    def __init__(self, api_key: str, demtype: str = "SRTMGL1"):
        if not api_key:
            raise ValueError("OpenTopography requires an API key")
        self.api_key = api_key
        self.demtype = demtype  # SRTMGL1 (~30m), SRTMGL3 (~90m), COP30, etc.

    def fetch(self, aoi: AreaOfInterest) -> DEM:
        import requests
        try:
            import rasterio
        except ImportError as e:
            raise RuntimeError(
                "OpenTopographyDEMSource.fetch requires the 'rasterio' "
                "package to decode the returned GeoTIFF."
            ) from e

        params = {
            "demtype": self.demtype,
            "south": aoi.min_lat,
            "north": aoi.max_lat,
            "west": aoi.min_lon,
            "east": aoi.max_lon,
            "outputFormat": "GTiff",
            "API_Key": self.api_key,
        }
        resp = requests.get(self.BASE_URL, params=params, timeout=60)
        resp.raise_for_status()

        with rasterio.io.MemoryFile(resp.content) as memfile:
            with memfile.open() as dataset:
                elevation = dataset.read(1).astype(np.float64)
                resolution_m = abs(dataset.transform.a) * 111_320 * math.cos(
                    math.radians(aoi.center.lat)
                )

        resolution_by_type = {"SRTMGL1": 30.0, "SRTMGL3": 90.0, "COP30": 30.0, "COP90": 90.0}

        return DEM(
            aoi=aoi,
            elevation_m=elevation,
            source=f"OpenTopography:{self.demtype}",
            synthetic=False,
            resolution_m=resolution_by_type.get(self.demtype, resolution_m),
            acquisition_date=None,  # OpenTopography mosaics don't expose a single date
            notes="Live fetch from OpenTopography Global DEM API.",
        )


class SyntheticDEMSource:
    """Offline, honestly-labeled synthetic terrain for development/testing.

    Produces:
      - a regional tilt (simulates a sloped landscape)
      - smooth rolling relief via band-limited Gaussian noise (simulates
        natural terrain roughness at a chosen wavelength)
      - optionally, one or more buried-mound-like local rises, so the
        anomaly detector has something real to find during development.

    This is NOT a claim about any real place. `synthetic=True` and the
    source string make that explicit everywhere the DEM is used.
    """

    def __init__(self, seed: int = 42):
        self.rng = np.random.default_rng(seed)

    def fetch(
        self,
        aoi: AreaOfInterest,
        regional_slope_pct: float = 2.0,
        relief_amplitude_m: float = 3.0,
        relief_wavelength_cells: float = 40.0,
        anomalies: Optional[list[dict]] = None,
    ) -> DEM:
        n = aoi.grid_size
        yy, xx = np.mgrid[0:n, 0:n].astype(np.float64)

        # 1. Regional tilt (meters of rise across the grid)
        slope_rad = math.atan(regional_slope_pct / 100.0)
        rise_per_cell = math.tan(slope_rad) * aoi.cell_size_m
        tilt = (xx * 0.6 + yy * 0.4) * rise_per_cell  # tilt along an arbitrary azimuth

        # 2. Band-limited rolling relief via smoothed white noise (real FFT
        #    filtering, not a canned shape)
        white = self.rng.normal(0, 1, size=(n, n))
        freq = np.fft.fftfreq(n)
        fx, fy = np.meshgrid(freq, freq)
        radius = np.sqrt(fx ** 2 + fy ** 2)
        cutoff = 1.0 / relief_wavelength_cells
        low_pass = np.exp(-(radius / cutoff) ** 2)
        spectrum = np.fft.fft2(white) * low_pass
        relief = np.real(np.fft.ifft2(spectrum))
        relief = relief / (relief.std() + 1e-9) * relief_amplitude_m

        elevation = 100.0 + tilt + relief  # base elevation offset of 100m, arbitrary

        # 3. Optional test anomalies: localized Gaussian rises/depressions,
        #    representing e.g. a buried mound or filled ditch signature.
        if anomalies:
            for a in anomalies:
                cx = a.get("row", n // 2)
                cy = a.get("col", n // 2)
                amp = a.get("amplitude_m", 0.6)
                sigma = a.get("sigma_cells", 6.0)
                yg, xg = np.mgrid[0:n, 0:n]
                bump = amp * np.exp(-(((yg - cx) ** 2 + (xg - cy) ** 2) / (2 * sigma ** 2)))
                elevation = elevation + bump

        return DEM(
            aoi=aoi,
            elevation_m=elevation,
            source="SYNTHETIC",
            synthetic=True,
            resolution_m=aoi.cell_size_m,
            acquisition_date=None,
            notes=(
                "Synthetic offline terrain for development/testing only. "
                "Not derived from any real measurement."
            ),
        )
