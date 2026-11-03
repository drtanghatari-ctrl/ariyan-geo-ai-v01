"""
Drawing widgets for the Mission Control workstation (win-w1). They draw exactly
the numbers they are given -- no data is made up here.

TerrainView is a software 3D view (no graphics driver needed, works on any
laptop and headless): the real DEM window as a shaded surface, draped with the
relief image or a saved satellite layer, with the candidate pins. Drag to
rotate, wheel to zoom, double-click to reset.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

ACCENT = QtGui.QColor("#3FB68B")
TEXT = QtGui.QColor("#E6EDF3")
MUTED = QtGui.QColor("#8B9BB0")
LINE = QtGui.QColor("#22324A")
BAND_COLOURS = {"SUBSTANTIAL": "#2E7D32", "HIGH": "#3FB68B", "MODERATE": "#D9A62B", "LOW": "#D9822B",
                "NO_DATA": "#6E7681", "NOT_RATED": "#3A414A"}
# the same pin colours as the phone's Final Image (FinalImageView.styleColour)
PIN_COLOURS = {"high": "#E5484D", "moderate": "#D9822B", "low": "#F0C83C", "rejected": "#A0A0A0", "unrated": "#5AA0E6"}


def image_from_rgba(data: bytes, w: int, h: int) -> QtGui.QImage:
    img = QtGui.QImage(data, w, h, 4 * w, QtGui.QImage.Format_RGBA8888_Premultiplied)
    return img.copy()                                   # own the pixels


def pin_colour(style: str) -> QtGui.QColor:
    return QtGui.QColor(PIN_COLOURS.get((style or "").lower(), PIN_COLOURS["unrated"]))


class Gauge(QtWidgets.QWidget):
    """Semicircle on the Steward's 0-1 scale; the needle sits on a STORED value."""
    SEGS = [(0.0, 0.35, "LOW"), (0.35, 0.55, "MODERATE"), (0.55, 0.75, "HIGH"), (0.75, 0.90, "SUBSTANTIAL"),
            (0.90, 1.0, "")]
    ORDER = ["LOW", "MODERATE", "HIGH", "SUBSTANTIAL"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value: Optional[float] = None
        self.band: Optional[str] = None
        self.setMinimumHeight(170)

    def set(self, value: Optional[float], band: Optional[str]):
        self.value, self.band = value, band
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        stroke = max(10.0, min(w, h) * 0.08)
        rad = min(w / 2 - stroke - 24, h - stroke - 54)
        cx, cy = w / 2, 22 + stroke / 2 + rad
        box = QtCore.QRectF(cx - rad, cy - rad, 2 * rad, 2 * rad)
        reached = self.ORDER.index(self.band) if self.band in self.ORDER else -1
        for a, b, name in self.SEGS:
            col = QtGui.QColor(BAND_COLOURS.get(name, "#2A3038"))
            if name and self.ORDER.index(name) > reached:
                col.setAlpha(60)
            pen = QtGui.QPen(col, stroke)
            pen.setCapStyle(QtCore.Qt.FlatCap)
            p.setPen(pen)
            p.drawArc(box, int((180 - a * 180) * 16) - 10, -int((b - a) * 180 * 16) + 20)
        p.setPen(MUTED)
        f = p.font(); f.setPointSize(8); p.setFont(f)
        for t in (0.0, 0.35, 0.55, 0.75, 0.90):
            ang = math.pi + t * math.pi
            rx = cx + (rad + stroke / 2 + 12) * math.cos(ang)
            ry = cy + (rad + stroke / 2 + 12) * math.sin(ang)
            p.drawText(QtCore.QRectF(rx - 20, ry - 8, 40, 16), QtCore.Qt.AlignCenter, "0" if t == 0 else "%.2f" % t)
        if self.value is not None:
            ang = math.pi + max(0.0, min(1.0, self.value)) * math.pi
            pen = QtGui.QPen(TEXT, 3)
            pen.setCapStyle(QtCore.Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(QtCore.QPointF(cx, cy), QtCore.QPointF(cx + (rad - stroke * 0.3) * math.cos(ang),
                                                              cy + (rad - stroke * 0.3) * math.sin(ang)))
            p.setBrush(TEXT)
            p.drawEllipse(QtCore.QPointF(cx, cy), 6, 6)
        f.setPointSize(22); f.setBold(True); p.setFont(f)
        p.setPen(QtGui.QColor(BAND_COLOURS.get(self.band or "", "#E6EDF3")))
        p.drawText(QtCore.QRectF(0, cy + 8, w, 34), QtCore.Qt.AlignCenter,
                   "%.2f" % self.value if self.value is not None else "\u2014")
        f.setPointSize(9); f.setBold(False); p.setFont(f)
        p.setPen(MUTED)
        p.drawText(QtCore.QRectF(0, cy + 40, w, 18), QtCore.Qt.AlignCenter, self.band or "not rated")
        p.end()


class TerrainView(QtWidgets.QWidget):
    """Software 3D surface of a real DEM window (painter's algorithm, one quad per DEM cell)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 300)
        self.heights: Optional[np.ndarray] = None
        self.drape: Optional[np.ndarray] = None          # (h, w, 3) uint8, sampled at DEM cells
        self.pins: List[Dict] = []
        self.dx = self.dy = 30.0
        self.ve = 1.0
        self.message = "Loading\u2026"
        self.reset_view()
        self.setMouseTracking(False)
        self._last: Optional[QtCore.QPointF] = None

    def reset_view(self):
        self.yaw, self.pitch, self.zoom = -35.0, 38.0, 1.0
        self.update()

    def set_message(self, text: str):
        self.heights, self.message = None, text
        self.update()

    def set_surface(self, heights: np.ndarray, dx: float, dy: float, ve: float, pins: List[Dict]):
        self.heights = heights.astype(np.float64)
        self.dx, self.dy, self.ve, self.pins = float(dx), float(dy), float(ve), pins
        self.message = ""
        self.update()

    def set_drape(self, img: QtGui.QImage):
        """Sample the drape image at each DEM cell centre (nearest; no smoothing)."""
        if self.heights is None or img.isNull():
            return
        h, w = self.heights.shape
        small = img.convertToFormat(QtGui.QImage.Format_RGB888).scaled(w, h, QtCore.Qt.IgnoreAspectRatio,
                                                                        QtCore.Qt.FastTransformation)
        ptr = small.constBits()
        arr = np.frombuffer(ptr, dtype=np.uint8, count=small.bytesPerLine() * h).reshape(h, small.bytesPerLine())
        self.drape = arr[:, : w * 3].reshape(h, w, 3).copy()
        self.update()

    def set_drape_array(self, arr: np.ndarray):
        """arr: (h, w, 3) uint8 on the DEM's own lattice (see workstation.drape_on_dem)."""
        if self.heights is not None and arr.shape[:2] == self.heights.shape:
            self.drape = arr
            self.update()

    # -- interaction
    def mousePressEvent(self, e):
        self._last = e.position()

    def mouseMoveEvent(self, e):
        if self._last is not None:
            d = e.position() - self._last
            self.yaw += d.x() * 0.5
            self.pitch = max(8.0, min(88.0, self.pitch + d.y() * 0.4))
            self._last = e.position()
            self.update()

    def mouseReleaseEvent(self, _e):
        self._last = None

    def wheelEvent(self, e):
        self.zoom = max(0.4, min(4.0, self.zoom * (1.0012 ** e.angleDelta().y())))
        self.update()

    def mouseDoubleClickEvent(self, _e):
        self.reset_view()

    # -- drawing
    def _project(self):
        z = self.heights
        h, w = z.shape
        finite = np.isfinite(z)
        zmed = np.nanmedian(z) if finite.any() else 0.0
        zz = np.where(finite, z, zmed)
        xs = (np.arange(w) - (w - 1) / 2) * self.dx
        ys = (np.arange(h) - (h - 1) / 2) * self.dy
        X, Y = np.meshgrid(xs, ys)
        Z = (zz - zmed) * self.ve
        a, b = math.radians(self.yaw), math.radians(self.pitch)
        x1 = X * math.cos(a) - Y * math.sin(a)
        y1 = X * math.sin(a) + Y * math.cos(a)
        sx = x1
        sy = y1 * math.sin(b) - Z * math.cos(b)
        depth = y1 * math.cos(b) + Z * math.sin(b)
        span = max(w * self.dx, h * self.dy)
        scale = min(self.width(), self.height()) / span * 0.95 * self.zoom
        px = self.width() / 2 + sx * scale
        py = self.height() / 2 + sy * scale
        return px, py, depth, finite, zz, scale

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#0B0E13"))
        if self.heights is None:
            p.setPen(MUTED)
            p.drawText(self.rect().adjusted(20, 20, -20, -20), QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap,
                       self.message)
            p.end()
            return
        px, py, depth, finite, zz, scale = self._project()
        h, w = zz.shape
        # light from the north-west, from the real slope (normals of the scaled surface)
        gy, gx = np.gradient(zz * self.ve, self.dy, self.dx)
        nz = 1.0 / np.sqrt(1 + gx * gx + gy * gy)
        light = np.clip(((-gx * -0.5) + (-gy * 0.5) + 0.7) * nz, 0.25, 1.15)
        cells = []
        for r in range(h - 1):
            for c in range(w - 1):
                if not (finite[r, c] and finite[r + 1, c] and finite[r, c + 1] and finite[r + 1, c + 1]):
                    continue
                cells.append((depth[r, c] + depth[r + 1, c + 1], r, c))
        cells.sort(reverse=True)                        # far first
        p.setPen(QtCore.Qt.NoPen)
        for _d, r, c in cells:
            if self.drape is not None:
                rgb = self.drape[r, c].astype(float)
            else:
                rgb = np.array([120.0, 150.0, 120.0])
            k = light[r, c]
            col = QtGui.QColor(int(min(255, rgb[0] * k)), int(min(255, rgb[1] * k)), int(min(255, rgb[2] * k)))
            p.setBrush(col)
            poly = QtGui.QPolygonF([QtCore.QPointF(px[r, c], py[r, c]), QtCore.QPointF(px[r, c + 1], py[r, c + 1]),
                                    QtCore.QPointF(px[r + 1, c + 1], py[r + 1, c + 1]),
                                    QtCore.QPointF(px[r + 1, c], py[r + 1, c])])
            p.drawPolygon(poly)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        for pin in self.pins:
            x, y = pin.get("x"), pin.get("y")
            if x is None or y is None:
                continue
            c, r = int(round(x)), int(round(y))
            if not (0 <= r < h and 0 <= c < w):
                continue
            base = QtCore.QPointF(px[r, c], py[r, c])
            hgt = 60 if pin.get("focus") else 30
            top = QtCore.QPointF(base.x(), base.y() - hgt)
            col = QtGui.QColor("#FFFFFF") if pin.get("focus") else pin_colour(pin.get("style", ""))
            p.setPen(QtGui.QPen(col, 2))
            p.drawLine(base, top)
            p.setBrush(col)
            s = 7 if pin.get("focus") else 4
            p.drawRect(QtCore.QRectF(top.x() - s, top.y() - s, 2 * s, 2 * s))
        p.setPen(MUTED)
        p.drawText(QtCore.QRectF(8, self.height() - 22, self.width() - 16, 18), QtCore.Qt.AlignCenter,
                   "Drag to rotate \u00b7 wheel to zoom \u00b7 double-click to reset")
        p.end()


class ProfileView(QtWidgets.QWidget):
    """Real heights along one line (A to A'), with the candidate marked."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.d: Optional[np.ndarray] = None
        self.z: Optional[np.ndarray] = None
        self.mark: Optional[float] = None

    def set(self, dist_m: np.ndarray, z: np.ndarray, mark_m: Optional[float]):
        self.d, self.z, self.mark = dist_m, z, mark_m
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = self.rect().adjusted(62, 10, -10, -24)
        p.setPen(LINE)
        p.drawRect(r)
        if self.z is None or not np.isfinite(self.z).any():
            p.setPen(MUTED)
            p.drawText(self.rect(), QtCore.Qt.AlignCenter, "No terrain yet")
            p.end()
            return
        z = self.z
        lo, hi = float(np.nanmin(z)), float(np.nanmax(z))
        if hi - lo < 0.5:
            hi = lo + 0.5
        dmax = float(self.d[-1]) or 1.0
        path = QtGui.QPainterPath()
        first = True
        for di, zi in zip(self.d, z):
            if not np.isfinite(zi):
                first = True
                continue
            pt = QtCore.QPointF(r.left() + di / dmax * r.width(), r.bottom() - (zi - lo) / (hi - lo) * r.height())
            if first:
                path.moveTo(pt); first = False
            else:
                path.lineTo(pt)
        p.setPen(QtGui.QPen(ACCENT, 2))
        p.drawPath(path)
        if self.mark is not None:
            x = r.left() + self.mark / dmax * r.width()
            p.setPen(QtGui.QPen(QtGui.QColor("#F2C14E"), 1, QtCore.Qt.DashLine))
            p.drawLine(QtCore.QPointF(x, r.top()), QtCore.QPointF(x, r.bottom()))
        p.setPen(MUTED)
        f = p.font(); f.setPointSize(8); p.setFont(f)
        p.drawText(QtCore.QRectF(0, r.top() - 6, 58, 14), QtCore.Qt.AlignRight, "%.1f m" % hi)
        p.drawText(QtCore.QRectF(0, r.bottom() - 8, 58, 14), QtCore.Qt.AlignRight, "%.1f m" % lo)
        p.drawText(QtCore.QRectF(r.left(), r.bottom() + 4, 30, 14), QtCore.Qt.AlignLeft, "A")
        p.drawText(QtCore.QRectF(r.right() - 120, r.bottom() + 4, 120, 14), QtCore.Qt.AlignRight,
                   "A\u2032  (%.0f m, west \u2192 east)" % dmax)
        p.end()


class MapView(QtWidgets.QWidget):
    """Top-down image of the window (relief or a saved layer) with the candidate pins."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.img: Optional[QtGui.QImage] = None
        self.pins: List[Dict] = []
        self.size_px: Tuple[int, int] = (1, 1)

    def set(self, img: QtGui.QImage, pins: List[Dict], grid_w: int, grid_h: int):
        self.img, self.pins, self.size_px = img, pins, (grid_w, grid_h)
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#0B0E13"))
        if self.img is None or self.img.isNull():
            p.setPen(MUTED)
            p.drawText(self.rect(), QtCore.Qt.AlignCenter, "No terrain yet")
            p.end()
            return
        side = min(self.width(), self.height())
        target = QtCore.QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        p.drawImage(target, self.img)                    # nearest: exact cells
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        gw, gh = self.size_px
        for pin in self.pins:
            x, y = pin.get("x"), pin.get("y")
            if x is None or y is None:
                continue
            pt = QtCore.QPointF(target.left() + (x + 0.5) / gw * side, target.top() + (y + 0.5) / gh * side)
            col = QtGui.QColor("#FFFFFF") if pin.get("focus") else pin_colour(pin.get("style", ""))
            p.setPen(QtGui.QPen(QtGui.QColor("#000000"), 1))
            p.setBrush(col)
            p.drawEllipse(pt, 6 if pin.get("focus") else 4, 6 if pin.get("focus") else 4)
        p.end()


class Bars(QtWidgets.QWidget):
    """Horizontal bars of real numbers (label, value 0-1, colour)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: List[Tuple[str, float, str]] = []

    def set(self, rows: Sequence[Tuple[str, float, str]]):
        self.rows = list(rows)
        self.setMinimumHeight(22 * max(1, len(self.rows)))
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        y = 2
        for label, v, col in self.rows:
            p.setPen(TEXT)
            p.drawText(QtCore.QRectF(0, y, self.width() * 0.5, 18), QtCore.Qt.AlignVCenter, label)
            bx = self.width() * 0.52
            bw = self.width() * 0.36
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(LINE)
            p.drawRoundedRect(QtCore.QRectF(bx, y + 5, bw, 8), 4, 4)
            p.setBrush(QtGui.QColor(col))
            p.drawRoundedRect(QtCore.QRectF(bx, y + 5, bw * max(0.0, min(1.0, v)), 8), 4, 4)
            p.setPen(MUTED)
            p.drawText(QtCore.QRectF(bx + bw + 4, y, self.width() - bx - bw - 4, 18), QtCore.Qt.AlignVCenter,
                       "%.2f" % v)
            y += 22
        p.end()
