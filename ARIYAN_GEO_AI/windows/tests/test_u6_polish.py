"""u6: every page has its title strip and icon, Visualization opens each Final Image view,
the Steward still finds pages through their frames, and the toolbar is grouped."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ariyan_win import core_path  # noqa: E402

core_path.install()

import grand_project_db as db  # noqa: E402


def test_pages_framed_and_navigation_still_works(tmp_path, monkeypatch):
    from PySide6 import QtWidgets
    from ariyan_win import app, qtwork, ui
    root = str(tmp_path)
    db.create_grand_project(root, "Default Grand Project", project_id="default")
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    w = app.build_window(root)
    for _ in range(3):
        qtwork.wait_all(30000)
        qa.processEvents()
    names = [w.tabs.tabText(i).replace("&&", "&") for i in range(w.tabs.count())]
    assert names[0] == "MISSION CONTROL" and len(names) == 9
    for i in range(1, w.tabs.count()):
        assert isinstance(w.tabs.widget(i), ui.PageFrame)
        assert not w.tabs.tabIcon(i).isNull()
    assert w._goto("INVESTIGATION", "Wide-area jobs") is w.inv_tabs
    assert w.inv_tabs.currentWidget() is w.jobs
    assert w._goto("REPORT & ARCHIVE") is w.report
    opened = []
    monkeypatch.setattr(w.mission, "open_final_image", lambda cid, start_tab=0: opened.append((cid, start_tab)))
    w.mission.selected = "abc12345"
    w.visual._open(4)
    assert opened == [("abc12345", 4)]
    assert w.findChildren(QtWidgets.QPushButton, "danger")
    w.close()


def test_window_fits_a_1366x768_laptop_on_every_page(tmp_path):
    """Nothing on any page may force the window larger than a 1366 x 768 screen."""
    from PySide6 import QtWidgets
    from ariyan_win import app, qtwork
    root = str(tmp_path)
    gid = db.create_grand_project(root, "Default Grand Project", project_id="default")
    db.create_wide_area_search_job(root, gid, "A rather long job title for the Steward to show", "MANUAL_BBOX",
                                   36.94, 36.96, 45.51, 45.53, 2000.0,
                                   [{"tile_index": 0, "center_lat": 36.95, "center_lon": 45.52}])
    qa = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])
    old = qa.styleSheet()
    qa.setStyleSheet(app.STYLE)                       # as the program runs
    w = app.build_window(root)
    for _ in range(3):
        qtwork.wait_all(30000)
        qa.processEvents()
    for i in range(w.tabs.count()):
        w.tabs.setCurrentIndex(i)
        for _ in range(2):
            qtwork.wait_all(30000)
            qa.processEvents()
        m = w.minimumSizeHint()
        lay = w.centralWidget().layout()
        parts = [(type(lay.itemAt(k).widget() or lay.itemAt(k).layout()).__name__, lay.itemAt(k).minimumSize().width(),
                  lay.itemAt(k).minimumSize().height()) for k in range(lay.count())]
        assert m.width() <= 1300 and m.height() <= 640, (w.tabs.tabText(i), m, parts)
    w.inv_tabs.setCurrentWidget(w.jobs)
    w.steward_bar.path.setChecked(True)
    qa.processEvents()
    m = w.minimumSizeHint()
    assert m.width() <= 1300 and m.height() <= 640, m
    # the tab row's natural width depends on the machine's fonts (CI runners have no real screen);
    # what must hold everywhere: it scrolls instead of widening the window
    assert w.tabs.usesScrollButtons() and w.tabs.tabBar().usesScrollButtons()
    assert w.tabs.minimumSizeHint().width() <= 1300 or w.tabs.sizePolicy().horizontalPolicy() == \
        QtWidgets.QSizePolicy.Ignored
    w.close()
    qa.setStyleSheet(old)
