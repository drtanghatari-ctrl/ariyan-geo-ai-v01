"""W1 tt-v1: one terrain tile on demand, through the phone's own downloader."""
import json
import os

import terrain_tile as tt


class _Resp:
    def __init__(self, code, body=b""):
        self.status_code, self._b = code, body

    def iter_content(self, chunk_size=1):
        yield self._b


class _Session:
    def __init__(self, code):
        self.code, self.urls = code, []

    def get(self, url, timeout=60, stream=True):
        self.urls.append(url)
        return _Resp(self.code, b"TIFFDATA")


def test_missing_tile_is_downloaded_once(tmp_path):
    root = str(tmp_path)
    st = tt.tile_status(root, 36.95323, 45.52454)
    assert st["covered"] and not st["present"] and st["tile"]
    s = _Session(200)
    r = tt.ensure_tile(root, 36.95323, 45.52454, s)
    assert r["status"] == "downloaded" and r["present"] and os.path.getsize(r["path"]) == 8
    assert len(s.urls) == 1 and "amazonaws.com" in s.urls[0]
    r = tt.ensure_tile(root, 36.95323, 45.52454, s)
    assert r["status"] == "already_present" and len(s.urls) == 1


def test_no_public_tile_and_outside_coverage(tmp_path):
    root = str(tmp_path)
    r = tt.ensure_tile(root, 36.95323, 45.52454, _Session(404))
    assert r["status"] == "not_available" and not r["present"]
    out = json.loads(tt.tile_status_json(root, -45.0, 170.0))
    assert out["covered"] is False


def test_study_area_tiles_cover_every_job(tmp_path):
    import grand_project_db as db
    root = str(tmp_path)
    gid = db.create_grand_project(root, "Default Grand Project", project_id="default")
    db.create_wide_area_search_job(root, gid, "U2 Solduz", "bbox", 36.9, 37.1, 45.3, 45.6, 1000.0,
                                   [{"tile_index": 0, "center_lat": 37.0, "center_lon": 45.45}])
    r = tt.study_area_tiles(root)
    assert r["jobs"] == 1
    assert [(t["lat"], t["lon"]) for t in r["tiles"]] == [(36, 45), (37, 45)]
    assert r["missing"] == 2 and all(t["tile"] and t["jobs"] == ["U2 Solduz"] for t in r["tiles"])
