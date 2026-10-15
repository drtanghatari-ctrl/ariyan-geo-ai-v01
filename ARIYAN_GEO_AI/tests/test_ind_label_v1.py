"""ind-label-v1 (2026-10-15, user-approved): mapped industry within 300 m is
a LABEL and a Pass 2 ORDER only -- never a rejection, never hidden."""
import json

import grand_project_db as db
import grand_project_query_mobile as q
import grand_project_refinement as gpr
import grand_project_report as rpt
import industrial_label as il
import industrial_osm_data as data


def _inside_first_feature():
    _k, la0, lo0, la1, lo1 = data.FEATURES[0]
    return (la0 + la1) / 2.0, (lo0 + lo1) / 2.0


# ---------------------------------------------------------------- label

def test_label_inside_mapped_box():
    lat, lon = _inside_first_feature()
    n = il.nearest(lat, lon)
    assert n is not None and n["distance_m"] == 0.0
    t = il.label(lat, lon)
    assert "inside its mapped box" in t
    assert "OpenStreetMap 2026-10-06" in t
    assert "not a rejection" in t
    assert il.deferred(lat, lon) is True


def test_no_label_outside_coverage_or_bad_input():
    for lat, lon in [(0.0, 0.0), (None, None), ("x", 1), (51.5, -0.1)]:
        assert il.nearest(lat, lon) is None
        assert il.label(lat, lon) is None
        assert il.deferred(lat, lon) is False


def test_lookup_failure_is_silent(monkeypatch):
    import industrial_index as ii
    monkeypatch.setattr(ii, "features_within", lambda *a, **k: 1 / 0)
    lat, lon = _inside_first_feature()
    assert il.nearest(lat, lon) is None and il.label(lat, lon) is None


def test_detail_shape():
    lat, lon = _inside_first_feature()
    d = il.detail(lat, lon)
    assert d["method"] == "ind-label-v1" and d["deferred_in_pass2"] is True
    assert d["features"] and d["text"].startswith("mapped industry")
    assert il.detail(None, None)["text"] == "no coordinates"
    assert il.detail(0.0, 0.0)["deferred_in_pass2"] is False


# ------------------------------------------------------- Pass 2 ordering

def _setup(tmp_path):
    root = str(tmp_path)
    gp = db.create_grand_project(root, "t")
    centers = [{"tile_index": 0, "center_lat": 32.1, "center_lon": 48.3}]
    jid = db.create_wide_area_search_job(root, gp, "j", "MANUAL_BBOX", 32.1, 32.2, 48.3, 48.4, 1000, centers)
    t = db.list_tiles_for_job(root, jid)[0]
    inv = db.create_investigation(root, gp, "", "", {})
    db.mark_tile_done(root, t["id"], inv)
    hi_ind = db.create_candidate(root, gp, inv, 32.10, 48.30, score=9.0)   # strongest, near industry
    mid = db.create_candidate(root, gp, inv, 32.12, 48.32, score=-6.0)
    low = db.create_candidate(root, gp, inv, 32.14, 48.34, score=3.0)
    lo_ind = db.create_candidate(root, gp, inv, 32.16, 48.36, score=8.0)   # near industry
    return root, gp, jid, hi_ind, mid, low, lo_ind


def _fake_near(ids_by_lat):
    def nearest(lat, lon):
        return {"kind": "man_made=silo", "distance_m": 42.0} if round(float(lat), 2) in ids_by_lat else None
    return nearest


def test_industry_adjacent_go_last_but_are_kept(tmp_path, monkeypatch):
    root, gp, jid, hi_ind, mid, low, lo_ind = _setup(tmp_path)
    monkeypatch.setattr(il, "nearest", _fake_near({32.10, 32.16}))
    r = gpr.select_refinement_candidates(root, jid, 10, min_separation_m=0, skip_flagged=False)
    assert [c["id"] for c in r["selected"]] == [mid, low, hi_ind, lo_ind]
    assert r["industrial_deferred"] == 2 and r["industrial_deferred_selected"] == 2
    assert r["industrial_order"] == "ind-label-v1"
    # n smaller than the open-ground group: industry ones fall out of THIS run only
    r2 = gpr.select_refinement_candidates(root, jid, 2, min_separation_m=0, skip_flagged=False)
    assert [c["id"] for c in r2["selected"]] == [mid, low]
    assert r2["industrial_deferred"] == 2 and r2["industrial_deferred_selected"] == 0


def test_requested_count_not_clobbered(tmp_path, monkeypatch):
    # regression: the lookup loop must not overwrite the requested count n
    root, gp, jid, *_ = _setup(tmp_path)
    monkeypatch.setattr(il, "nearest", _fake_near({32.10, 32.16}))
    r = gpr.select_refinement_candidates(root, jid, 1, min_separation_m=0, skip_flagged=False)
    assert len(r["selected"]) == 1


def test_lookup_failure_means_plain_score_order(tmp_path, monkeypatch):
    root, gp, jid, hi_ind, mid, low, lo_ind = _setup(tmp_path)
    monkeypatch.setattr(il, "nearest", lambda *a: 1 / 0)
    r = gpr.select_refinement_candidates(root, jid, 10, min_separation_m=0, skip_flagged=False)
    assert [c["id"] for c in r["selected"]] == [hi_ind, lo_ind, mid, low]
    assert r["industrial_deferred"] == 0


def test_previews_carry_industrial_text(tmp_path, monkeypatch):
    root, gp, jid, hi_ind, mid, low, lo_ind = _setup(tmp_path)
    monkeypatch.setattr(il, "nearest", _fake_near({32.10, 32.16}))
    sel = json.loads(gpr.preview_refinement_selection_json(root, jid, 10, min_separation_m=0, skip_flagged=False))
    by = {c["candidate_id"]: c["industrial_text"] for c in sel["selected"]}
    assert by[mid] is None and "42 m (man_made=silo" in by[hi_ind]
    assert sel["industrial_deferred"] == 2
    man = json.loads(gpr.preview_selected_refinement_json(root, jid, " ".join([lo_ind, mid])))
    # a hand-picked order is kept as given
    assert [c["candidate_id"] for c in man["selected"]] == [lo_ind, mid]
    assert man["selected"][0]["industrial_text"] and man["selected"][1]["industrial_text"] is None


# ------------------------------------------------- never changes status

def test_rows_and_detail_label_only(tmp_path, monkeypatch):
    root, gp, jid, hi_ind, mid, low, lo_ind = _setup(tmp_path)
    monkeypatch.setattr(il, "nearest", _fake_near({32.10, 32.16}))
    rows = {r["id"]: r for r in json.loads(q.list_candidates_json(root, gp))}
    assert "man_made=silo" in rows[hi_ind]["ind_label_text"]
    assert rows[mid]["ind_label_text"] is None
    assert rows[hi_ind]["status"] == rows[mid]["status"]  # same status either way
    assert rows[hi_ind]["status"] != "REJECTED"
    d = json.loads(q.get_candidate_detail_json(root, hi_ind))
    assert "industry" in d


# --------------------------------------------------------------- report

def test_report_industry_text_exact_and_rounded():
    lat, lon = _inside_first_feature()
    ex = rpt._industry(lat, lon, True)
    assert "inside its mapped box" in ex["text_en"] and "فقط زمینه" in ex["text_fa"]
    ro = rpt._industry(lat, lon, False)
    assert "within 1 km" in ro["text_en"] and "distance withheld" in ro["text_en"]
    assert rpt._industry(0.0, 0.0, True) == {"text_en": "", "text_fa": ""}
    assert rpt._industry(None, None, False) == {"text_en": "", "text_fa": ""}
    assert "industry_context" in rpt._CSV_COLUMNS
    assert rpt.REPORT_VERSION == "rp-v1.2"
