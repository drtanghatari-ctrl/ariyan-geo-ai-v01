"""win-w4a: keys encrypted on Windows (DPAPI), never stored in clear on other systems;
the Final Image passes the saved Copernicus login only when fetching; study-area tiles."""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ariyan_win import core_path  # noqa: E402

core_path.install()

from ariyan_win import keys  # noqa: E402


def test_keys_roundtrip_and_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    allow = not keys.protected()                 # outside Windows only the explicit test store works
    assert keys.status(allow) == {"opentopography": False, "copernicus": False}
    keys.save({"OPENTOPOGRAPHY_API_KEY": "ot-123", "COPERNICUS_CLIENT_ID": "cid", "COPERNICUS_CLIENT_SECRET": "sec"},
              allow_unprotected=allow)
    assert keys.status(allow) == {"opentopography": True, "copernicus": True}
    assert keys.copernicus(allow) == ("cid", "sec")
    raw = open(os.path.join(str(tmp_path), "ARIYAN_GEO_AI", "keys.dat"), "rb").read()
    if keys.protected():
        assert b"ot-123" not in raw and b"sec" not in raw          # DPAPI ciphertext, not the values
    keys.save({"OPENTOPOGRAPHY_API_KEY": ""}, allow_unprotected=allow)
    assert keys.status(allow)["opentopography"] is False and keys.status(allow)["copernicus"] is True


@pytest.mark.skipif(keys.protected(), reason="Windows saves with DPAPI")
def test_no_clear_text_store_outside_windows(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    with pytest.raises(OSError):
        keys.save({"OPENTOPOGRAPHY_API_KEY": "x"})
    keys.save({"OPENTOPOGRAPHY_API_KEY": "x"}, allow_unprotected=True)
    assert keys.load() == {}                     # the app itself never reads a test store


def test_fetch_passes_the_saved_login_only_when_asked(monkeypatch):
    import sat_image_mobile as sim
    from ariyan_win import finalimage as F
    calls = []
    monkeypatch.setattr(sim, "open_layer_json", lambda *a: calls.append(a) or json.dumps({"needs_fetch": True,
                                                                                        "label": "NDVI"}))
    monkeypatch.setattr(keys, "copernicus", lambda *a: ("cid", "sec"))
    F._layer("/tmp/x", "sid", "NDVI")
    F._layer("/tmp/x", "sid", "NDVI", True)
    assert calls[0][3:] == ("cid", "sec", False) and calls[1][3:] == ("cid", "sec", True)


def test_window_has_the_w4a_actions():
    from ariyan_win.finalimage import FinalImageWindow
    for name in ("_fetch_layer", "_import_gpr", "_import_ert", "_pick_into_inbox"):
        assert callable(getattr(FinalImageWindow, name))
