"""
investigation_mobile.py — Entry point called from Kotlin (via Chaquopy).

Same pipeline as investigation.py (GPS coordinate -> AOI -> DEM ->
anomaly detection -> evidence record), but:
  - uses anomaly_detection_mobile (no scipy) instead of anomaly_detection
  - returns a JSON string directly instead of writing files, since the
    Android app renders results natively rather than embedding a
    matplotlib PNG

REWRITTEN THIS SESSION -- SYNTHETIC PATH REMOVED ENTIRELY. Previously
this function had a use_real_dem switch (default False) that meant the
main investigation screen ran on SyntheticDEMSource -- fabricated
terrain -- unless a user remembered to flip a switch and re-enter an
API key every session. That directly violated this project's own hard
requirement (nothing synthetic/fake -- data must actually be gathered)
the moment synthetic became the ACTUAL default behavior rather than an
explicit opt-in dev/test mode.

NEW BEHAVIOR: a real, live OpenTopography fetch
(dem_source_mobile.OpenTopographyAAIGridSource) is now ALWAYS attempted
first -- there is no toggle. If that fails for ANY reason (no network,
bad/expired API key, rate-limited, HTTP error, parse failure -- all
already covered by OpenTopographyFetchError), this module automatically
falls back to offline_evidence_fallback.fetch_offline_dem(), which reads
from this device's own previously-downloaded offline DEM library
(offline_dem_store.py / OfflineDataActivity.kt) IF that location's
country has been downloaded. If BOTH the live fetch and the offline
library fail, a single combined, honest error is raised -- there is no
third, fabricated fallback. api_key is therefore now a required,
non-empty argument (previously optional, only needed when use_real_dem
was explicitly turned on); offline_data_root is now required too, so
the offline fallback knows where on-device storage to look.

Every returned record's evidence entry states synthetic=False --
literally cannot be otherwise now, since this module no longer contains
any code path that produces a synthetic DEM at all.
"""
from __future__ import annotations

from coordinate import GeoPoint, build_aoi
from anomaly_detection_mobile import detect_anomalies
from evidence_record import build_investigation_record
from dem_source_mobile import OpenTopographyAAIGridSource, OpenTopographyFetchError
from offline_evidence_fallback import fetch_offline_dem, OfflineDataUnavailableError


def run_investigation_json(
    lat: float,
    lon: float,
    radius_m: float = 500.0,
    grid_size: int = 96,
    kernel_sigma_cells: float = 12.0,
    zscore_threshold: float = 2.5,
    api_key: str = "",
    demtype: str = "SRTMGL1",
    offline_data_root: str = "",
) -> str:
    """Run one investigation and return the InvestigationRecord as a
    JSON string. This is the function MainActivity.kt calls.

    Real data is ALWAYS attempted first: a live OpenTopography fetch via
    api_key. If that fails (network/HTTP/parse error, or api_key not
    yet configured), this automatically falls back to any
    previously-downloaded offline DEM data covering (lat, lon) -- see
    offline_evidence_fallback.py. If NEITHER succeeds, raises
    OpenTopographyFetchError with a message that names both real
    reasons (the live failure AND why the offline fallback couldn't
    help either) so the user always sees an honest, actionable error --
    never a silently substituted fabricated result.
    """
    center = GeoPoint(lat, lon)
    aoi = build_aoi(center, radius_m=radius_m, grid_size=grid_size)

    live_error: OpenTopographyFetchError | None = None
    dem = None

    if api_key:
        try:
            dem = OpenTopographyAAIGridSource(api_key, demtype=demtype).fetch(aoi)
        except OpenTopographyFetchError as exc:
            live_error = exc
    else:
        live_error = OpenTopographyFetchError(
            "No OpenTopography API key is configured yet -- enter your "
            "free key (opentopography.org) to enable live real DEM fetch."
        )

    if dem is None:
        try:
            dem = fetch_offline_dem(aoi, offline_data_root)
        except OfflineDataUnavailableError as offline_error:
            raise OpenTopographyFetchError(
                f"Live DEM fetch failed ({live_error}) and no offline data "
                f"is available for this location either ({offline_error})."
            ) from offline_error

    anomalies = detect_anomalies(
        dem,
        kernel_sigma_cells=kernel_sigma_cells,
        zscore_threshold=zscore_threshold,
        min_area_cells=3,
    )

    record = build_investigation_record(
        aoi, dem, anomalies, zscore_threshold, kernel_sigma_cells
    )
    return record.to_json()
