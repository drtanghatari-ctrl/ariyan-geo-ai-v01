"""dbr-v1.1 (2026-10-31): the Anthropogenic perspective gives the real-NDVI
bonus and says "NDVI corroboration" only when NDVI itself corroborated the
candidate."""
import debate_engine as de


def _anthro(sources, ndvi_synth):
    cand = {"id": "#1", "z_score": 3.37, "elevation_delta_m": -3.71, "correlation_status": "CORROBORATED",
            "sources": sources, "ndvi_synthetic": ndvi_synth}
    pos = [p for p in de.run_debate(cand)["positions"] if p["perspective"].startswith("Anthropogenic")][0]
    return pos


def test_no_ndvi_bonus_or_claim_when_ndvi_did_not_corroborate():
    p = _anthro(["DEM", "THERMAL", "SAR"], False)
    assert not any("NDVI" in r for r in p["reasoning"])
    q = _anthro(["DEM", "THERMAL", "SAR", "NDVI"], False)
    assert any("vegetation (NDVI) corroboration is real" in r for r in q["reasoning"])
    assert abs((q["confidence_score"] - p["confidence_score"]) - 0.15) < 1e-9


def test_synthetic_note_only_when_ndvi_corroborated():
    assert not any("SYNTHETIC" in r for r in _anthro(["DEM", "THERMAL"], True)["reasoning"])
    assert any("SYNTHETIC" in r for r in _anthro(["DEM", "NDVI"], True)["reasoning"])
