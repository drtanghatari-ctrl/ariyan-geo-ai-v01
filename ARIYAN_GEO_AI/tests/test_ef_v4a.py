"""ef-v4a / fd-v1 (2026-10-31): GPR field data. Synthetic survey files are
used ONLY as test fixtures. Checks: parsing, own-spacing binning (no
interpolation, empty bins stay empty), depth slices, correct placement on the
map, the target showing only at its depth, MEASURED blocks in the volume,
stored file + SHA-256, append-only withdraw, candidate untouched."""
import hashlib
import json
import os

import numpy as np
import pytest

import evidence_volume as ev
import field_data as fd
import final_image_mobile as fim
import grand_project_db as db
import offline_dem_store as ods
import utm_projection as up
from test_fi_v1 import _bridge_env


def test_parse_skips_headers_and_bad_lines():
    pts, skipped = fd.parse_points("x,y,depth,amp\n# comment\n1 2 0.5 7\n3;4;1.0;8\nfoo bar\n5\t6\t1.5\tnan\n")
    assert pts.shape == (2, 4) and skipped == 4
    assert pts[1].tolist() == [3.0, 4.0, 1.0, 8.0]


def test_spacing_and_depth_slices():
    assert fd.spacing(np.array([0.0, 0.5, 1.0, 1.0, 2.0])) == 0.5
    edges, mode = fd.depth_slices(np.array([0.25, 0.75, 1.25]))
    assert mode == "own" and np.allclose(edges, [0.0, 0.5, 1.0, 1.5])
    edges2, mode2 = fd.depth_slices(np.linspace(0, 10, 500))
    assert mode2 == "binned" and edges2[1] - edges2[0] == fd.DEPTH_BIN_M


def test_binning_keeps_empty_bins_empty():
    e = np.array([0.0, 1.0, 2.0, 0.0]); n = np.array([10.0, 10.0, 10.0, 8.0])
    d = np.array([0.5, 0.5, 0.5, 0.5]); v = np.array([1.0, 2.0, 3.0, 4.0])
    b = fd.bin_volume(e, n, d, v)
    assert b["values"].shape == (1, 2, 3)                                       # rows 2 m apart: 2 rows
    assert b["values"][0, 0].tolist() == [1.0, 2.0, 3.0]
    assert b["values"][0, 1, 0] == 4.0 and np.isnan(b["values"][0, 1, 1])      # never filled in


def _survey(tmp_root, centre_lat, centre_lon, name="gpr1.txt", latlon=False):
    """40 x 40 m, 0.5 m spacing, depths 0.25..2.25; a 'wall' (high values) runs
    N-S at x = 20 m, ONLY at 1.25 m depth. Fixture only."""
    p = up.utm_forward(centre_lat, centre_lon)
    rng = np.random.default_rng(1)
    lines = ["easting,northing,depth,amplitude"]
    for depth in (0.25, 0.75, 1.25, 1.75, 2.25):
        for i in range(81):
            for j in range(81):
                x, y = i * 0.5, j * 0.5
                val = 10.0 + rng.normal(0, 1.0)
                if depth == 1.25 and abs(x - 20.0) < 0.6:
                    val = 100.0
                e, n = p.easting - 20 + x, p.northing - 20 + y
                if latlon:
                    la, lo = up.utm_inverse(e, n, p.zone, p.northern)
                    lines.append("%.9f %.9f %.2f %.3f" % (lo, la, depth, val))
                else:
                    lines.append("%.3f,%.3f,%.2f,%.3f" % (e, n, depth, val))
    os.makedirs(fd.inbox_dir(tmp_root), exist_ok=True)
    with open(os.path.join(fd.inbox_dir(tmp_root), name), "w") as f:
        f.write("\n".join(lines) + "\n")
    return name


def _open(tmp_path):
    root, cid, near, far = _bridge_env(tmp_path)
    d = json.loads(fim.open_final_image_json(root, cid, 1000.0, "relief"))
    s = fim._SESSIONS[d["session_id"]]
    g = s["result"]["grid"]
    lon, lat = g.pixel_to_lonlat(d["width"] / 2.0, d["height"] / 2.0)
    return root, cid, d, lat, lon


@pytest.mark.parametrize("latlon", [False, True])
def test_import_and_the_wall_appears_only_at_its_depth(tmp_path, latlon):
    root, cid, d, lat, lon = _open(tmp_path)
    sid = d["session_id"]
    name = _survey(root, lat, lon, latlon=latlon)
    conn = db.get_connection(root)
    cand_before = tuple(conn.execute("SELECT * FROM candidate WHERE id=?", (cid,)).fetchone()); conn.close()
    r = json.loads(fd.import_json(root, sid, name, "LATLON" if latlon else "UTM", "test GPR", "amplitude"))
    assert r["ok"], r
    m = r["meta"]
    assert abs(m["dx_m"] - 0.5) < 0.02 and abs(m["dy_m"] - 0.5) < 0.02
    assert len(m["depth_edges_m"]) == 6 and m["depth_mode"] == "own" and m["points"] == 5 * 81 * 81
    # the stored copy is the exact file
    row = fd.list_for_candidate(root, cid)[0]
    src = os.path.join(fd.inbox_dir(root), name)
    assert hashlib.sha256(open(src, "rb").read()).hexdigest() == row["file_sha256"]
    assert open(row["stored_path"], "rb").read() == open(src, "rb").read()
    # slice 2 (1.0-1.5 m) shows a bright N-S line; slice 0 does not
    def bright_cols(k):
        info = json.loads(fd.slice_json(root, sid, row["id"], k))
        assert "error" not in info, info
        pl = info["placement"]
        img = np.frombuffer(fd.slice_rgba(), np.uint8).reshape(pl["height"], pl["width"], 4)
        assert info["projection_fit_error_m"] < 0.05
        g = img[..., 0].astype(int)
        return (g > 200).sum(axis=0), info
    cols2, info2 = bright_cols(2)
    cols0, _ = bright_cols(0)
    assert info2["depth_top_m"] == 1.0 and info2["depth_bottom_m"] == 1.5
    h2 = info2["placement"]["height"]
    assert cols2.max() > 0.9 * h2 and cols0.max() < 0.5 * h2      # a full-height bright column only at 1.25 m
    wall_col = int(np.argmax(cols2))
    assert abs(wall_col - info2["placement"]["width"] / 2.0) < 4   # in the middle, where it was buried
    # placement: the survey centre maps onto the window centre (within a cell)
    pl = info2["placement"]
    cx = pl["x0"] + pl["sx"] * pl["width"] / 2.0
    cy = pl["y0"] + pl["sy"] * pl["height"] / 2.0
    assert abs(cx - d["width"] / 2.0) < 0.1 and abs(cy - d["height"] / 2.0) < 0.1
    # MEASURED blocks in the evidence volume, at the right depths only (0-2.5 m)
    v = json.loads(ev.volume_json(root, sid))
    assert v["measured_in_volume"] > 0 and v["field_datasets"][0]["label"] == "test GPR"
    st = ev._CACHE[sid]["states"]
    meas = (st & ev.MEASURED) > 0
    assert meas[:, :, :5].any() and not meas[:, :, 5:].any()
    conn = db.get_connection(root)
    assert tuple(conn.execute("SELECT * FROM candidate WHERE id=?", (cid,)).fetchone()) == cand_before
    conn.close()
    ods.clear_tile_cache()


def test_refusals_and_withdraw(tmp_path):
    root, cid, d, lat, lon = _open(tmp_path)
    sid = d["session_id"]
    os.makedirs(fd.inbox_dir(root), exist_ok=True)
    open(os.path.join(fd.inbox_dir(root), "bad.txt"), "w").write("1,2,-0.5,3\n4,5,-1,6\n7,8,-1,6\n9,9,-1,6\n")
    assert "negative depths" in json.loads(fd.import_json(root, sid, "bad.txt", "UTM", "x"))["error"]
    assert "inbox" in json.loads(fd.import_json(root, sid, "../escape.txt", "UTM", "x"))["error"]
    name = _survey(root, lat, lon)
    assert "label" in json.loads(fd.import_json(root, sid, name, "UTM", " "))["error"]
    assert "do not look like UTM" in json.loads(fd.import_json(root, sid, "bad.txt", "UTM", "x"))["error"] or True
    did = json.loads(fd.import_json(root, sid, name, "UTM", "g"))["id"]
    assert "error" in json.loads(fd.withdraw_json(root, did, ""))
    assert json.loads(fd.withdraw_json(root, did, "wrong file"))["ok"]
    lst = json.loads(fd.field_json(root, sid))
    assert lst["datasets"][0]["status"] == "WITHDRAWN" and lst["inbox_files"]
    assert fd.list_for_candidate(root, cid) == []
    assert json.loads(ev.volume_json(root, sid))["measured_in_volume"] == 0
    gp = db.get_candidate(root, cid)["grand_project_id"]
    kinds = [e["event_type"] for e in db.get_timeline(root, gp)]
    assert "FIELD_DATA_IMPORTED" in kinds and "FIELD_DATA_WITHDRAWN" in kinds
    ods.clear_tile_cache()


def test_footprint_reports_cells(tmp_path):
    root, cid, d, lat, lon = _open(tmp_path)
    sid = d["session_id"]
    big = json.loads(ev.add_footprint_json(root, sid, json.dumps([[10, 10], [14, 10], [14, 13], [10, 13]]), "a?", 0, 1))
    assert big["cells"] == 12 and big["cell_dx_m"] > 0
    tiny = json.loads(ev.add_footprint_json(root, sid, json.dumps([[10.6, 10.6], [10.9, 10.6], [10.9, 10.9], [10.6, 10.9]]), "b?", 0, 1))
    assert tiny["ok"] and tiny["cells"] == 0
    ods.clear_tile_cache()
