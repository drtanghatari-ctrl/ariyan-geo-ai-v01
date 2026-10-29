"""sp-v1 tests: a single-point investigation becomes a one-tile COMPLETE job
whose candidates every job feature (refinement first of all) can see,
without copying or changing any investigation, candidate or evidence."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "app", "src", "main", "python"))

import grand_project_db as db  # noqa: E402
import grand_project_sync as sync  # noqa: E402
import grand_project_refinement as refine  # noqa: E402
import single_point_jobs as spj  # noqa: E402

LAT, LON, R = 32.67958, 47.30584, 500.0


def _aoi(lat=LAT, lon=LON, r=R):
    """The shape the app REALLY stores (evidence_record.py record_kwargs["aoi"])."""
    return {"center_lat": lat, "center_lon": lon, "radius_m": r,
            "grid_size": 96, "cell_size_m": 2 * r / 96}


def _full_aoi(lat=LAT, lon=LON, r=R):
    dlat, dlon = r / 110900.0, r / 93500.0
    return {"center": {"lat": lat, "lon": lon}, "radius_m": r,
            "min_lat": lat - dlat, "max_lat": lat + dlat,
            "min_lon": lon - dlon, "max_lon": lon + dlon,
            "grid_size": 96, "cell_size_m": 2 * r / 96}


class SpV1(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.gp = sync.get_or_create_default_grand_project(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def _single(self, n_cand=2, objective="", aoi=None):
        inv = db.create_investigation(self.root, self.gp, objective=objective,
                                      workflow_reference=spj.WORKFLOW,
                                      parameters=_aoi() if aoi is None else aoi)
        cands = [db.create_candidate(self.root, self.gp, inv, lat=LAT + i * 1e-4, lon=LON, score=3.0 + i)
                 for i in range(n_cand)]
        return inv, cands

    def _q(self, sql, args=()):
        conn = db.get_connection(self.root)
        try:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]
        finally:
            conn.close()

    def test_convert_makes_complete_one_tile_job(self):
        inv, cands = self._single()
        job_id = spj.make_single_point_job(self.root, inv)
        job = db.get_wide_area_search_job(self.root, job_id)
        self.assertEqual(job["input_kind"], "SINGLE_POINT")
        self.assertEqual(job["status"], "COMPLETE")
        self.assertEqual(job["n_tiles"], 1)
        self.assertAlmostEqual(job["tile_size_m"], 2 * R)
        tiles = db.list_tiles_for_job(self.root, job_id)
        self.assertEqual(len(tiles), 1)
        self.assertEqual(tiles[0]["status"], "DONE")
        self.assertEqual(tiles[0]["investigation_id"], inv)
        self.assertEqual(db.get_wide_area_search_job_progress(self.root, job_id)["pending"], 0)

    def test_refinement_sees_the_original_candidates(self):
        inv, cands = self._single()
        job_id = spj.make_single_point_job(self.root, inv)
        got = sorted(c["id"] for c in refine._job_candidates(self.root, job_id))
        self.assertEqual(got, sorted(cands))

    def test_nothing_is_copied_or_changed(self):
        inv, cands = self._single()
        before = self._q("SELECT * FROM candidate ORDER BY id")
        spj.make_single_point_job(self.root, inv)
        self.assertEqual(self._q("SELECT * FROM candidate ORDER BY id"), before)
        self.assertEqual(len(self._q("SELECT id FROM investigation")), 1)

    def test_twice_is_refused_never_a_twin(self):
        inv, _ = self._single()
        spj.make_single_point_job(self.root, inv)
        with self.assertRaises(spj.SinglePointJobError):
            spj.make_single_point_job(self.root, inv)
        self.assertEqual(len(self._q("SELECT id FROM wide_area_search_job")), 1)

    def test_tile_run_in_flight_is_never_claimed(self):
        inv, _ = self._single(objective="Wide-area search 'x' -- tile 3/4 (analysis radius 750 m)")
        self.assertEqual(spj.list_single_points(self.root), [])
        with self.assertRaises(spj.SinglePointJobError):
            spj.make_single_point_job(self.root, inv)

    def test_no_candidates_no_job(self):
        inv, _ = self._single(n_cand=0)
        self.assertEqual(spj.list_single_points(self.root), [])
        self.assertIsNone(spj.register_after_run(self.root, inv))
        self.assertEqual(self._q("SELECT id FROM wide_area_search_job"), [])

    def test_bad_aoi_refused_with_reason(self):
        inv, _ = self._single(aoi={"center_lat": LAT})
        with self.assertRaises(spj.SinglePointJobError) as cm:
            spj.make_single_point_job(self.root, inv)
        self.assertIn("analysis window", str(cm.exception))

    def test_list_and_json_batch(self):
        a, _ = self._single()
        b, _ = self._single(n_cand=1)
        items = spj.list_single_points(self.root)
        self.assertEqual({i["investigation_id"] for i in items}, {a, b})
        out = json.loads(spj.make_single_point_jobs_json(self.root, json.dumps([a, b, "nope"])))
        self.assertEqual(len(out["created"]), 2)
        self.assertEqual(len(out["skipped"]), 1)
        self.assertEqual(spj.list_single_points(self.root), [])

    def test_wide_area_tile_investigations_are_not_listed(self):
        inv, _ = self._single()
        job = db.create_wide_area_search_job(
            self.root, self.gp, "t", "MANUAL_BBOX", LAT - .01, LAT + .01, LON - .01, LON + .01,
            1000.0, [{"tile_index": 0, "center_lat": LAT, "center_lon": LON}])
        tile = db.list_tiles_for_job(self.root, job)[0]
        db.mark_tile_done(self.root, tile["id"], inv)
        self.assertEqual(spj.list_single_points(self.root), [])

    def test_timeline_event_logged(self):
        inv, _ = self._single()
        job_id = spj.make_single_point_job(self.root, inv)
        ev = self._q("SELECT * FROM timeline_event WHERE event_type = 'SINGLE_POINT_JOB_CREATED'")
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["related_entity_id"], job_id)

    def _investigation_json(self):
        return json.dumps({"aoi": _aoi(), "anomalies": [
            {"lat": LAT, "lon": LON, "peak_zscore": 3.4, "evidence_type": "DEM"}]})

    def test_sync_flag_registers_new_run(self):
        res = sync.record_investigation_results(
            self.root, self.gp, self._investigation_json(), register_single_point_job=True)
        self.assertIn("single_point_job_id", res)
        job = db.get_wide_area_search_job(self.root, res["single_point_job_id"])
        self.assertEqual(job["input_kind"], "SINGLE_POINT")

    def test_sync_default_registers_nothing(self):
        res = sync.record_investigation_results(self.root, self.gp, self._investigation_json())
        self.assertNotIn("single_point_job_id", res)
        self.assertEqual(self._q("SELECT id FROM wide_area_search_job"), [])
        self.assertEqual(len(spj.list_single_points(self.root)), 1)

    def test_real_stored_shape_gives_right_box(self):
        inv, _ = self._single()
        job = db.get_wide_area_search_job(self.root, spj.make_single_point_job(self.root, inv))
        from coordinate import meters_per_degree
        m_lat, m_lon = meters_per_degree(LAT)
        self.assertAlmostEqual((job["max_lat"] - job["min_lat"]) * m_lat, 2 * R, delta=0.5)
        self.assertAlmostEqual((job["max_lon"] - job["min_lon"]) * m_lon, 2 * R, delta=0.5)
        self.assertAlmostEqual((job["min_lat"] + job["max_lat"]) / 2, LAT, places=9)

    def test_full_aoi_shape_also_accepted(self):
        inv, _ = self._single(aoi=_full_aoi())
        self.assertTrue(spj.make_single_point_job(self.root, inv))

    def test_real_evidence_record_aoi_round_trip(self):
        """Guards the sp-v1 mistake: the AOI comes from evidence_record.py itself."""
        import inspect
        import evidence_record
        src = inspect.getsource(evidence_record)
        for key in ("center_lat", "center_lon", "radius_m"):
            self.assertIn('"%s"' % key, src)

    def test_left_out_runs_are_reported_with_reason(self):
        self._single(aoi={"center_lat": LAT})
        self._single(objective="Wide-area search 'x' -- tile 1/4")
        out = json.loads(spj.list_single_points_json(self.root))
        self.assertEqual(out["items"], [])
        self.assertEqual(len(out["not_eligible"]), 2)
        self.assertIn("analysis window", out["not_eligible_summary"])
        self.assertIn("wide-area job", out["not_eligible_summary"])


if __name__ == "__main__":
    unittest.main()
