"""W2 bundle-v1 (2026-11-02): moving the project between phone and laptop safely."""
import json
import os
import zipfile

import grand_project_db as db
import project_bundle as pb


def _project(root, n=3):
    gid = db.create_grand_project(root, "Default Grand Project", project_id="default")
    inv = db.create_investigation(root, gid, objective="t")
    ids = [db.create_candidate(root, gid, inv, 36.9 + i * 0.01, 45.5, score=7.0 + i) for i in range(n)]
    lib = os.path.join(root, "sat_library", "NDVI")
    os.makedirs(lib, exist_ok=True)
    open(os.path.join(lib, "k1.json"), "w").write('{"a": 1}')
    json.dump({"k1": {"sha256": "x", "bytes": 8}}, open(os.path.join(lib, "index.json"), "w"))
    return gid, ids


def _count(root):
    conn = db.get_connection(root)
    try:
        return conn.execute("SELECT COUNT(*) FROM candidate").fetchone()[0]
    finally:
        conn.close()


def test_send_then_receive_on_an_empty_laptop(tmp_path):
    phone, laptop, drive = str(tmp_path / "phone"), str(tmp_path / "laptop"), str(tmp_path / "drive")
    os.makedirs(phone)
    _project(phone, 3)
    s = json.loads(pb.make_bundle_json(phone, drive, "phone"))
    assert "error" not in s, s
    assert s["name"].endswith(".ariyan") and s["manifest"]["project"]["candidates"] == 3
    assert pb.handoff(phone)["state"] == "SENT"
    r = json.loads(pb.receive_json(laptop, s["path"], "laptop"))
    assert r["received"] and r["safety_copy"] is None and not r["warnings"]
    assert _count(laptop) == 3
    assert os.path.exists(os.path.join(laptop, "sat_library", "NDVI", "k1.json"))
    assert pb.handoff(laptop)["state"] == "RECEIVED"
    g = json.load(open(os.path.join(laptop, db.GUARD_FILENAME)))
    assert g["last_seen_size"] == os.path.getsize(os.path.join(laptop, db.DB_FILENAME))


def test_round_trip_keeps_a_safety_copy_and_merges_libraries(tmp_path):
    phone, laptop, drive = str(tmp_path / "phone"), str(tmp_path / "laptop"), str(tmp_path / "drive")
    os.makedirs(phone)
    gid, ids = _project(phone, 2)
    b1 = pb.make_bundle(phone, drive, "phone")
    pb.receive(laptop, b1["path"], "laptop")
    inv = db.create_investigation(laptop, gid, objective="on the laptop")        # work on the laptop
    db.create_candidate(laptop, gid, inv, 37.0, 45.0, score=9.0)
    lib = os.path.join(laptop, "sat_library", "THERMAL")
    os.makedirs(lib)
    open(os.path.join(lib, "k2.json"), "w").write("{}")
    json.dump({"k2": {"sha256": "y"}}, open(os.path.join(lib, "index.json"), "w"))
    b2 = pb.make_bundle(laptop, drive, "laptop")
    r = pb.receive(phone, b2["path"], "phone")                                   # phone unchanged since sending
    assert r["received"] and not r["warnings"]
    assert _count(phone) == 3
    assert r["safety_copy"] and os.path.basename(r["safety_copy"]).startswith("grand_project_before_receive_")
    assert os.path.exists(os.path.join(phone, "sat_library", "THERMAL", "k2.json"))
    assert json.load(open(os.path.join(phone, "sat_library", "NDVI", "index.json")))["k1"]["bytes"] == 8


def test_changes_after_sending_need_confirmation(tmp_path):
    phone, laptop, drive = str(tmp_path / "phone"), str(tmp_path / "laptop"), str(tmp_path / "drive")
    os.makedirs(phone)
    gid, ids = _project(phone, 2)
    b1 = pb.make_bundle(phone, drive, "phone")
    pb.receive(laptop, b1["path"], "laptop")
    b2 = pb.make_bundle(laptop, drive, "laptop")
    inv = db.create_investigation(phone, gid, objective="phone kept working")    # breaks one-device rule
    db.create_candidate(phone, gid, inv, 37.0, 45.0, score=9.0)
    r = pb.receive(phone, b2["path"], "phone")
    assert not r["received"] and r["needs_confirm"] and "AFTER sending" in r["warnings"][0]
    assert _count(phone) == 3                                                     # nothing replaced
    r = pb.receive(phone, b2["path"], "phone", confirm=True)
    assert r["received"] and _count(phone) == 2
    safety = r["safety_copy"]
    import sqlite3
    c = sqlite3.connect(safety)
    assert c.execute("SELECT COUNT(*) FROM candidate").fetchone()[0] == 3          # the phone's work is kept
    c.close()


def test_damaged_or_foreign_bundles_are_refused(tmp_path):
    phone, laptop, drive = str(tmp_path / "phone"), str(tmp_path / "laptop"), str(tmp_path / "drive")
    os.makedirs(phone)
    _project(phone, 1)
    b = pb.make_bundle(phone, drive, "phone")
    not_zip = str(tmp_path / "x.ariyan")
    open(not_zip, "w").write("hello")
    assert "not a zip" in json.loads(pb.receive_json(laptop, not_zip, "laptop"))["error"]
    bad = str(tmp_path / "bad.ariyan")
    with zipfile.ZipFile(b["path"]) as zin, zipfile.ZipFile(bad, "w") as zout:
        for n in zin.namelist():
            data = zin.read(n)
            if n == "grand_project.db":
                data = data[:-10] + b"0123456789"
            zout.writestr(n, data)
    assert "fingerprint" in json.loads(pb.receive_json(laptop, bad, "laptop"))["error"]
    evil = str(tmp_path / "evil.ariyan")
    with zipfile.ZipFile(b["path"]) as zin, zipfile.ZipFile(evil, "w") as zout:
        for n in zin.namelist():
            zout.writestr(n, zin.read(n))
        zout.writestr("files/../../outside.txt", "x")
    assert "unsafe path" in json.loads(pb.receive_json(laptop, evil, "laptop"))["error"]
    assert not os.path.exists(os.path.join(laptop, db.DB_FILENAME))


def test_nothing_to_send_is_reported(tmp_path):
    assert "no grand_project.db" in json.loads(pb.make_bundle_json(str(tmp_path), str(tmp_path / "o"), "phone"))["error"]


def test_reading_after_sending_is_not_a_change(tmp_path):
    import mission_control as mc
    phone, laptop, drive = str(tmp_path / "phone"), str(tmp_path / "laptop"), str(tmp_path / "drive")
    os.makedirs(phone)
    _project(phone, 2)
    b1 = pb.make_bundle(phone, drive, "phone")
    pb.receive(laptop, b1["path"], "laptop")
    mc.mission_json(phone)                                  # the user just looks at Mission Control
    mc.debates_json(phone)
    b2 = pb.make_bundle(laptop, drive, "laptop")            # laptop sends back (only its receive record is new)
    c = pb.check_receive(phone, b2["path"])
    assert c["warnings"] == [] and not c["needs_confirm"]
    b3 = pb.make_bundle(phone, drive, "phone")              # receiving the same bundle twice is harmless
    pb.receive(laptop, b3["path"], "laptop", confirm=True)
    assert pb.check_receive(laptop, b3["path"])["warnings"] == []


def test_work_after_receiving_needs_confirmation(tmp_path):
    phone, laptop, drive = str(tmp_path / "phone"), str(tmp_path / "laptop"), str(tmp_path / "drive")
    os.makedirs(phone)
    gid, _ = _project(phone, 2)
    b1 = pb.make_bundle(phone, drive, "phone")
    pb.receive(laptop, b1["path"], "laptop")
    inv = db.create_investigation(laptop, gid, objective="laptop work, never sent back")
    db.create_candidate(laptop, gid, inv, 37.0, 45.0, score=9.0)
    b_again = pb.make_bundle(phone, drive, "phone")         # phone sends again by mistake
    r = pb.receive(laptop, b_again["path"], "laptop")
    assert not r["received"] and "after receiving" in r["warnings"][0]
