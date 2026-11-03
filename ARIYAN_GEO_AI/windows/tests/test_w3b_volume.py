"""win-w3b: the Final Image window's Evidence Volume, hypotheses and exports run the
phone's own modules. Fixture DEM tile and fixture GPR survey from the core tests
(test data only)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ariyan_win import core_path  # noqa: E402

core_path.install()

import field_data as fd  # noqa: E402
import project_bundle  # noqa: E402
from test_ef_v4a import _survey  # noqa: E402
from test_fi_v1 import _bridge_env  # noqa: E402


def _pump(qa, n=6):
    from ariyan_win import qtwork
    for _ in range(n):
        qtwork.wait_all(30000)
        qa.processEvents()


def test_volume_hypotheses_gpr_and_exports(tmp_path):
    from PySide6 import QtWidgets
    from ariyan_win import finalimage as F
    root, cid, _near, _far = _bridge_env(tmp_path)
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    w = F.FinalImageWindow(root, cid)
    _pump(qa)
    assert w.sid, w.layer_note.text()
    # a real GPR survey (fixture) for this candidate
    g = w.data["meta"]
    import final_image_mobile as fim
    s = fim._SESSIONS[w.sid]
    lon, lat = s["result"]["grid"].pixel_to_lonlat(g["width"] / 2.0, g["height"] / 2.0)
    name = _survey(root, lat, lon)
    assert json.loads(fd.import_json(root, w.sid, name, "UTM", "test GPR", "amplitude"))["ok"]
    before = project_bundle.content_fingerprint(os.path.join(root, "grand_project.db"))
    # footprint hypothesis drawn on the map
    import evidence_volume as ev
    cx, cy = g["width"] / 2.0, g["height"] / 2.0
    r = json.loads(ev.add_footprint_json(root, w.sid, json.dumps([[cx - 3, cy - 3], [cx + 3, cy - 3], [cx + 3, cy + 3],
                                                                  [cx - 3, cy + 3]]), "wall?", 0.5, 2.0, ""))
    assert r["ok"] and r["cells"] > 0
    w._build_volume()
    _pump(qa)
    v = w._vol
    assert v and len(v["slices"]) == len(v["summary"]["slices"]) and v["summary"]["hypotheses"]
    assert w.fp_list.count() == 1 and w.gpr_combo.count() == 2
    w.gpr_combo.setCurrentIndex(1)
    w.depth.setValue(2)                       # 1.0-1.5 m: the fixture wall's depth
    _pump(qa)
    assert w.vol_canvas.gpr is not None
    # section hypothesis on the profile line
    w._preset("EW")
    _pump(qa)
    pr = w._prof
    import section_hypothesis as sh
    sh.add(root, cid, pr["a"]["lat"], pr["a"]["lon"], pr["b"]["lat"], pr["b"]["lon"], pr["length_m"], "ditch?",
           10.0, 40.0, 0.0, 1.5, "")
    w._refresh_sections()
    _pump(qa)
    assert "ditch?" in w.sec_list.item(0).text()
    # exports land in offline_data/exports
    import profile_section_mobile as psm
    out = json.loads(psm.export_profile_json(root, w.sid, pr["a"]["x"], pr["a"]["y"], pr["b"]["x"], pr["b"]["y"], ""))
    assert out["ok"] and all(os.path.exists(p) for p in out["paths"].values() if isinstance(p, str))
    out = json.loads(fim.export_final_image_json(root, w.sid, json.dumps({"device": "windows"})))
    assert out["ok"]
    # hypotheses and exports added rows of their own, but no candidate, review or confidence changed
    import grand_project_db as db
    conn = db.get_connection(root)
    try:
        cand = conn.execute("SELECT status, confidence_band, confidence_numeric FROM candidate WHERE id=?", (cid,)).fetchone()
    finally:
        conn.close()
    assert tuple(cand) == ("GENERATED", None, None)
    assert project_bundle.content_fingerprint(os.path.join(root, "grand_project.db")) != before   # hypotheses stored
    w.close()
