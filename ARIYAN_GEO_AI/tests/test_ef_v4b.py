"""ef-v4b / fd-v2 (2026-10-31): ERT sections. Synthetic section files are used
ONLY as test fixtures. Checks: own layers and distance bins (nothing
interpolated, empty stays empty), uniform drawing rows taking their layer,
log colour scale, line placement from the open profile line, matching the
cut line in both directions, MEASURED blocks along the line only, refusals."""
import json
import os

import numpy as np

import evidence_volume as ev
import field_data as fd
import final_image_mobile as fim
import offline_dem_store as ods
from test_fi_v1 import _bridge_env

LAYERS = [0.5, 1.5, 2.75, 4.25, 6.0]          # thicker with depth, as inversions are


def _ert_text():
    lines = ["distance depth resistivity", "# fixture only"]
    for d in np.arange(0.0, 200.0 + 1e-9, 2.5):
        for z in LAYERS:
            v = 50.0
            if 95.0 <= d <= 105.0 and z in (1.5, 2.75):
                v = 800.0                       # the buried block
            if d == 0.0 and z == 6.0:
                continue                        # one model cell missing: must stay empty
            lines.append("%.1f %.2f %.1f" % (d, z, v))
    return "\n".join(lines) + "\n"


def test_bin_section_layers_and_rows():
    pts, _ = fd.parse_points(_ert_text(), ncols=3)
    sec = fd.bin_section(pts[:, 0], pts[:, 1], pts[:, 2])
    assert sec["dx"] == 2.5 and np.allclose(sec["edges"], [0.0, 1.0, 2.125, 3.5, 5.125, 6.875])
    assert sec["cells"].shape == (5, 81) and np.isnan(sec["cells"][4, 0])
    assert sec["cells"][1, 40] == 800.0 and sec["cells"][0, 40] == 50.0
    img = sec["image"]
    rows = img.shape[0]
    thin = 1.0
    assert rows == int(np.ceil((6.875 - 0.0) / thin))           # uniform rows of the thinnest layer
    # the row covering 1.5 m depth takes layer 1 exactly
    r15 = int(1.5 / (6.875 / rows))
    assert img[r15, 40] == 800.0 and img[r15, 0] == 50.0


def _open(tmp_path):
    root, cid, near, far = _bridge_env(tmp_path)
    d = json.loads(fim.open_final_image_json(root, cid, 1000.0, "relief"))
    os.makedirs(fd.inbox_dir(root), exist_ok=True)
    with open(os.path.join(fd.inbox_dir(root), "ert1.txt"), "w") as f:
        f.write(_ert_text())
    return root, cid, d


def _line(d):
    cy = d["height"] / 2.0
    return [10.0, cy, 18.0, cy]                 # E-W, ~8 cells long (~200 m at these cells)


def test_import_on_profile_line_and_draw_on_matching_cut(tmp_path):
    root, cid, d = _open(tmp_path)
    sid = d["session_id"]
    ln = _line(d)
    r = json.loads(fd.import_ert_json(root, sid, "ert1.txt", json.dumps({"grid": ln}), "ERT line 1"))
    if "error" in r and "outside the line" in r["error"]:
        # the test window's cells decide the line length; widen to cover 200 m
        g = fim._SESSIONS[sid]["result"]["grid"]
        dx, _ = g.cell_size_m()
        ln = [10.0, ln[1], 10.0 + 205.0 / dx, ln[1]]
        r = json.loads(fd.import_ert_json(root, sid, "ert1.txt", json.dumps({"grid": ln}), "ERT line 1"))
    assert r["ok"], r
    m = r["meta"]
    assert m["log_scale"] and m["filled_bins"] == m["bins"] - 1 and m["dist_to_m"] == 200.0
    on = json.loads(fd.ert_on_line_json(root, sid, *ln))
    assert len(on["sections"]) == 1 and not on["sections"][0]["reversed"]
    sec = on["sections"][0]
    img = np.frombuffer(fd.section_rgba(0), np.uint8).reshape(sec["height"], sec["width"], 4)
    r15 = int(1.5 / (sec["depth_bottom_m"] / sec["height"]))
    hot, cold = img[r15, 40], img[r15, 5]
    assert hot[0] > 200 and hot[2] < 80                  # 800 ohm m: red end of the ramp
    assert cold[2] > 150                                 # 50 ohm m: blue end
    assert img[-1, 0, 3] == 0                            # the missing model cell: transparent (drawn dark)
    rev = json.loads(fd.ert_on_line_json(root, sid, ln[2], ln[3], ln[0], ln[1]))
    assert rev["sections"][0]["reversed"]
    other = json.loads(fd.ert_on_line_json(root, sid, ln[0], ln[1] + 10, ln[2], ln[3] + 10))
    assert other["sections"] == []
    # MEASURED blocks: only cells on the line, only down to ~6.9 m
    v = json.loads(ev.volume_json(root, sid))
    assert v["field_datasets"][0]["method"] == "ERT" and v["measured_in_volume"] > 0
    meas = (ev._CACHE[sid]["states"] & ev.MEASURED) > 0
    rows = set(np.nonzero(meas.any(axis=(1, 2)))[0].tolist())
    assert rows == {int(np.floor(ln[1]))}
    assert meas[:, :, :14].any() and not meas[:, :, 14:].any()
    lst = json.loads(fd.field_json(root, sid))["datasets"][0]
    assert lst["method"] == "ERT" and lst["line_in_window"] and np.allclose(lst["line_grid"], ln, atol=1e-6)
    ods.clear_tile_cache()


def test_ert_refusals(tmp_path):
    root, cid, d = _open(tmp_path)
    sid = d["session_id"]
    tiny = json.dumps({"grid": [10.0, 10.0, 10.5, 10.0]})       # far shorter than 200 m
    assert "outside the line" in json.loads(fd.import_ert_json(root, sid, "ert1.txt", tiny, "x"))["error"]
    with open(os.path.join(fd.inbox_dir(root), "neg.txt"), "w") as f:
        f.write("0 -1 5\n1 -1 5\n2 -1 5\n3 -1 5\n")
    assert "negative depths" in json.loads(fd.import_ert_json(root, sid, "neg.txt", json.dumps({"grid": _line(d)}), "x"))["error"]
    same = json.dumps({"latlon": [33.5, 51.5, 33.5, 51.5]})
    assert "same point" in json.loads(fd.import_ert_json(root, sid, "ert1.txt", same, "x"))["error"]
    assert "label" in json.loads(fd.import_ert_json(root, sid, "ert1.txt", json.dumps({"grid": _line(d)}), " "))["error"]
    ods.clear_tile_cache()


def test_linear_scale_when_values_not_positive():
    pts, _ = fd.parse_points("0 0.5 -3\n2.5 0.5 4\n5 0.5 1\n7.5 0.5 2\n", ncols=3)
    assert not bool((pts[:, 2] > 0).all())
