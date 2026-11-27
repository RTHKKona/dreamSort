# line icons drawn with the painter, so they tint from the theme tokens

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import QApplication, QAbstractButton

from . import theme

SIZE = 18        # logical box
STROKE = 1.8     # in the 24 unit drawing box

_cache = {}


def _rounded(points, radius):
    # an open polyline with softened corners
    path = QPainterPath(QPointF(*points[0]))
    for index in range(1, len(points) - 1):
        prev, corner, nxt = points[index - 1], points[index], points[index + 1]
        def toward(frm, to):
            dx, dy = to[0] - frm[0], to[1] - frm[1]
            length = math.hypot(dx, dy) or 1.0
            return dx / length * radius, dy / length * radius
        ax, ay = toward(corner, prev)
        bx, by = toward(corner, nxt)
        path.lineTo(QPointF(corner[0] - ax, corner[1] - ay))
        path.quadTo(QPointF(*corner), QPointF(corner[0] + bx, corner[1] + by))
    path.lineTo(QPointF(*points[-1]))
    return path


def _draw(painter, name, colour):
    # 24 unit box, stroke icons
    pen = QPen(QColor(colour))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setWidthF(STROKE)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    poly = lambda pts: painter.drawPath(
        _rounded(pts, 1.6)) if len(pts) > 2 else painter.drawPolyline(
            [QPointF(*pt) for pt in pts])
    line = lambda a, b: painter.drawLine(QPointF(*a), QPointF(*b))
    ring = lambda box: painter.drawEllipse(QRectF(*box))

    if name == "play":
        painter.setBrush(pen.color())
        painter.drawPolygon(QPolygonF([QPointF(7.5, 4.5), QPointF(19.5, 12),
                                       QPointF(7.5, 19.5)]))
    elif name == "refresh":
        painter.drawArc(QRectF(3, 3, 18, 18), 0, -270 * 16)
        poly([(12, 3), (18.7, 5.7), (21, 8)])
        poly([(21, 3), (21, 8), (16, 8)])
    elif name == "more":
        painter.setBrush(pen.color())
        pen.setWidthF(2.8)
        painter.setPen(pen)
        for x in (5, 12, 19):
            painter.drawPoint(QPointF(x, 12))
    elif name == "check":
        poly([(5, 12.5), (10, 17.5), (19, 7)])
    elif name == "download":
        poly([(7, 10), (12, 15), (17, 10)])
        line((12, 3.5), (12, 15))
        tray = QPainterPath(QPointF(4, 17))
        tray.lineTo(4, 19)
        tray.arcTo(QRectF(4, 17, 4, 4), 180, 90)
        tray.lineTo(18, 21)
        tray.arcTo(QRectF(14, 17, 4, 4), 270, 90)
        tray.lineTo(20, 17)
        painter.drawPath(tray)
    elif name == "folder":
        path = QPainterPath(QPointF(3, 20))
        path.lineTo(19, 20)
        path.arcTo(QRectF(17, 16, 4, 4), 270, 90)
        path.lineTo(21, 8)
        path.arcTo(QRectF(17, 4, 4, 4), 0, 90)
        path.lineTo(12, 6)
        path.lineTo(10.2, 3.6)
        path.lineTo(4, 3.6)
        path.arcTo(QRectF(2, 3.6, 4, 4), 90, 90)
        path.lineTo(2, 18)
        path.arcTo(QRectF(2, 16, 4, 4), 180, 90)
        painter.drawPath(path)
    elif name == "find":
        line((4, 20), (13, 11))
        line((17, 3.5), (17, 8.5))
        line((14.5, 6), (19.5, 6))
        line((9, 3.5), (9, 6.5))
        line((7.5, 5), (10.5, 5))
        line((20, 11.5), (20, 14.5))
        line((18.5, 13), (21.5, 13))
    elif name == "ban":
        ring((3, 3, 18, 18))
        line((5.6, 5.6), (18.4, 18.4))
    elif name == "scan":
        ring((4.5, 4.5, 12, 12))
        line((13.5, 13.5), (19.5, 19.5))


def pixmap(name, colour, ratio=1.0):
    # a tinted icon, crisp on the given screen
    ratio = max(1.0, float(ratio or 1.0))
    key = (name, colour, ratio)
    if key not in _cache:
        image = QPixmap(math.ceil(SIZE * ratio), math.ceil(SIZE * ratio))
        image.fill(Qt.transparent)
        image.setDevicePixelRatio(ratio)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.scale(SIZE / 24.0, SIZE / 24.0)
        _draw(painter, name, colour)
        painter.end()
        _cache[key] = image
    return _cache[key]


def icon(name, colour, disabled=None, ratio=1.0):
    # normal and disabled looks, so a greyed button keeps a greyed icon
    made = QIcon()
    dim = disabled or colour
    for mode, tint in ((QIcon.Normal, colour), (QIcon.Active, colour),
                       (QIcon.Disabled, dim)):
        made.addPixmap(pixmap(name, tint, ratio), mode)
    return made


def action_icon(name):
    # an icon in the theme's text colour, for a menu action
    values = theme.tokens()
    return icon(name, values["text"], values["textDisabled"])


def set_icon(widget, name):
    # the widget keeps its icon name, so a theme change can tint it again
    widget.setProperty("iconName", name)
    _apply(widget, name)


def _apply(widget, name):
    values = theme.tokens()
    on_primary = widget.objectName() == "primaryBtn"
    colour = values["primaryText"] if on_primary else values["text"]
    dim = values["primaryText"] if on_primary else values["textDisabled"]
    widget.setIcon(icon(name, colour, dim, widget.devicePixelRatioF()))
    widget.setIconSize(QSize(SIZE, SIZE))


def refresh_icons():
    # after a theme change; gone widgets are skipped
    for widget in QApplication.allWidgets():
        try:
            name = widget.property("iconName")
        except RuntimeError:
            continue
        if name and isinstance(widget, QAbstractButton):
            _apply(widget, name)
