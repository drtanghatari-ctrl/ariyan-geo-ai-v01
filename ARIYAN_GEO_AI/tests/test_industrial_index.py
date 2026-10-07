"""ind-v1: offline OpenStreetMap industrial check (cc-v1 step 6)."""
import industrial_index as ii
import industrial_osm_data as data


def test_source_is_pinned():
    assert data.SOURCE["md5"] == "3c7753276b34731017c5f1a6aef6ab79"
    assert data.SOURCE["features"] == len(data.FEATURES) == 24256
    assert len(data.COVERAGE) == 304


def test_coverage_is_iran_only():
    assert ii.check(32.1898, 48.2521)["status"] in (ii.STATUS_CLEAR, ii.STATUS_NEAR)   # Susa
    assert ii.check(33.094, 44.580)["status"] == ii.STATUS_OUTSIDE                      # Ctesiphon, Iraq


def test_inside_a_feature_is_near_and_distance_monotone():
    k, la0, lo0, la1, lo1 = data.FEATURES[5000]
    lat, lon = (la0 + la1) / 2, (lo0 + lo1) / 2
    c = ii.check(lat, lon)
    assert c["status"] == ii.STATUS_NEAR and c["features"][0]["distance_m"] == 0.0
    # 0.01 deg north of the box top is about 1.1 km: clear at 300 m for this
    # feature, found again at 2 km
    far = la1 + 0.01
    near_2k = [f for f in ii.features_within(far, lon, 2000)]
    assert any(abs(f["distance_m"] - (far - la1) * 110574.0) < 1.0 for f in near_2k)


def test_grid_matches_brute_force():
    import random
    random.seed(7)
    for _ in range(300):
        la, lo = random.uniform(29, 37), random.uniform(46, 60)
        a = sorted(f["distance_m"] for f in ii.features_within(la, lo, 3000))
        b = sorted(round(ii._dist_to_box_m(la, lo, *x[1:]), 1) for x in data.FEATURES
                   if ii._dist_to_box_m(la, lo, *x[1:]) <= 3000)
        assert a == b
