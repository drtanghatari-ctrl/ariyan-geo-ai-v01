"""Run core calls off the screen thread; results come back to the screen thread as signals."""
from __future__ import annotations

from typing import Any, Callable

from PySide6 import QtCore

_keep = set()


class _Signals(QtCore.QObject):
    done = QtCore.Signal(object)


class _Worker(QtCore.QRunnable):
    def __init__(self, fn: Callable[..., Any], *args):
        super().__init__()
        self.fn, self.args = fn, args
        self.signals = _Signals()
        self.setAutoDelete(False)

    def run(self):
        try:
            r = self.fn(*self.args)
        except Exception as e:                   # shown, never hidden
            r = {"error": "%s: %s" % (type(e).__name__, e)}
        self.signals.done.emit(r)


def run_async(fn: Callable[..., Any], callback: Callable[[Any], None], *args) -> None:
    w = _Worker(fn, *args)
    _keep.add(w)

    def finish(r, w=w):
        _keep.discard(w)
        callback(r)

    w.signals.done.connect(finish)
    QtCore.QThreadPool.globalInstance().start(w)


def wait_all(ms: int = 60000) -> None:
    QtCore.QThreadPool.globalInstance().waitForDone(ms)
