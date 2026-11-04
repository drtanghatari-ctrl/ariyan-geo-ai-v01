"""u3c: a layer fetched in a Final Image reaches Mission Control at once, and saved layers
are read with the Settings login (check only, never fetch)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ariyan_win import core_path  # noqa: E402

core_path.install()


def test_thumbs_pass_keys_and_never_fetch(monkeypatch):
    import sat_image_mobile as sim
    from ariyan_win import keys, workstation
    seen = []

    def fake(root, sid, p, cid, sec, fetch):
        seen.append((p, cid, sec, fetch))
        if p == "TRUE_COLOR":
            return json.dumps({"allowed": True, "scene_date": "2026-09-27", "clear_fraction_window": 1.0,
                               "grid": {"width": 4, "height": 4}})
        return json.dumps({"needs_fetch": True})
    monkeypatch.setattr(sim, "open_layer_json", fake)
    monkeypatch.setattr(keys, "copernicus", lambda: ("id1", "sec1"))
    th = workstation._thumbs_with_keys("/nowhere", "s")
    states = {l["product"]: l["state"] for l in th["layers"]}
    assert states["TRUE_COLOR"] == "SAVED" and states["NDVI"] == "NOT_SAVED"
    assert all(x[1] == "id1" and x[3] is False for x in seen)


def test_final_image_fetch_tells_mission_control(tmp_path, monkeypatch):
    from PySide6 import QtWidgets
    from ariyan_win import mission, workstation
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    w = mission.Workstation(str(tmp_path))
    w.selected = "abc"
    calls = []
    monkeypatch.setattr(mission.qtwork, "run_async", lambda fn, cb, *a: calls.append((fn, a)))
    w._layers_changed("abc")
    assert calls and calls[0][0] is workstation.terrain and calls[0][1][1] == "abc"
    from ariyan_win.finalimage import FinalImageWindow
    assert hasattr(FinalImageWindow, "layers_changed")
