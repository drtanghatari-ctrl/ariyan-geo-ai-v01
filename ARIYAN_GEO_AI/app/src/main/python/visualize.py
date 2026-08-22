"""visualize.py — render DEM, hillshade, and anomaly map to a PNG figure."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from dem_source import DEM
from terrain_derivatives import compute_hillshade, compute_slope_deg
from anomaly_detection import AnomalyCandidate, compute_residual_relief


def render_investigation(
    dem: DEM,
    anomalies: list[AnomalyCandidate],
    kernel_sigma_cells: float,
    out_path: str,
):
    hillshade = compute_hillshade(dem)
    slope = compute_slope_deg(dem)
    residual = compute_residual_relief(dem, kernel_sigma_cells)

    fig, axes = plt.subplots(1, 4, figsize=(20, 5))

    im0 = axes[0].imshow(dem.elevation_m, cmap="terrain", origin="lower")
    axes[0].set_title(f"Elevation (m)\nsource={dem.source}")
    plt.colorbar(im0, ax=axes[0], fraction=0.046)

    axes[1].imshow(hillshade.values, cmap="gray", origin="lower", vmin=0, vmax=255)
    axes[1].set_title("Hillshade\n(az=315°, alt=45°)")

    im2 = axes[2].imshow(slope.values, cmap="magma", origin="lower")
    axes[2].set_title("Slope (degrees)")
    plt.colorbar(im2, ax=axes[2], fraction=0.046)

    im3 = axes[3].imshow(residual, cmap="RdBu_r", origin="lower",
                          vmin=-np.abs(residual).max(), vmax=np.abs(residual).max())
    axes[3].set_title(f"Local relief residual (m)\n{len(anomalies)} candidate(s) flagged")
    plt.colorbar(im3, ax=axes[3], fraction=0.046)
    for a in anomalies:
        color = "lime" if a.polarity == "positive" else "cyan"
        axes[3].plot(a.col, a.row, "o", markersize=10, markerfacecolor="none",
                     markeredgecolor=color, markeredgewidth=2)
        axes[3].annotate(f"z={a.peak_zscore:.1f}", (a.col, a.row),
                          color=color, fontsize=8, xytext=(4, 4), textcoords="offset points")

    label = "SYNTHETIC (offline test data)" if dem.synthetic else dem.source
    fig.suptitle(
        f"ARIYAN core investigation — {dem.aoi.center.lat:.5f}, {dem.aoi.center.lon:.5f} "
        f"(radius {dem.aoi.radius_m:.0f}m) — DEM: {label}",
        fontsize=12,
    )
    plt.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
