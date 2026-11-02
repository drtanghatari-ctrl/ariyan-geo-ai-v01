"""win-w0: the Windows shell starts headless, imports every core module (optional
desktop extras aside), builds the main window and reads Mission Control."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ariyan_win import app, config, core_path  # noqa: E402


def test_selftest_passes():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    assert app.selftest() == 0
    with open(os.path.join(tempfile.gettempdir(), "ariyan_selftest.txt"), encoding="utf-8") as f:
        text = f.read()
    assert "SELFTEST PASS" in text and "failed: 0" in text


def test_core_is_the_phone_core():
    d = core_path.core_dir()
    assert os.path.normpath(d).endswith(os.path.join("app", "src", "main", "python"))
    assert "mission_control" in core_path.core_modules()


def test_data_root_setting_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert config.data_root().endswith(os.path.join("ARIYAN_GEO_AI", "offline_data"))
    config.set_data_root(str(tmp_path / "elsewhere"))
    assert config.data_root() == str(tmp_path / "elsewhere")
    assert json.load(open(tmp_path / "ARIYAN_GEO_AI" / "settings.json"))["data_root"] == str(tmp_path / "elsewhere")
