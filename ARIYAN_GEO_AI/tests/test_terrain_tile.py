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
