# details pane

import html
import math
import urllib.parse
import webbrowser

from PySide6.QtCore import (
    QPoint, QPointF, QRect, QRectF, QSize, Qt, QEvent, QTimer, Signal,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF,
)
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ..constants import Colors
from ..helpers.files import open_in_file_explorer
from .theme import token

LINE = 18      # legacy one text line
GAP = 7        # legacy line gap
CHIP = 20      # legacy status pill
ACTION = 24    # details control height


def blend(fore, back, alpha):
    # fore over back at alpha, as a hex colour
    def channels(value):
        value = value.lstrip("#")
        return [int(value[index:index + 2], 16) for index in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(
        round(alpha * first + (1 - alpha) * second)
        for first, second in zip(channels(fore), channels(back)))


PLACEHOLDER = blend(Colors.TEXT, Colors.WIDGET_BG, 0.62)


def tint(colour):
    # a status colour washed over the sheet
    return blend(colour, Colors.WIDGET_BG, 0.14)


def wrap_path_text(path):
    # add zero-width breaks
    if not path:
        return path
    out = []
    for char in str(path):
        out.append(char)
        if char in ("/", "\\"):
            out.append("\u200b")
    return "".join(out)


def link_href(url):
    # only http(s) leaves this app
    text = str(url or "").strip()
    if not text:
        return ""
    if "://" in text:
        scheme = text.split("://", 1)[0].lower()
        if scheme not in ("http", "https"):
            return ""
        return text
    if text.lower().startswith(("mailto:", "file:", "javascript:")):
        return ""
    return "https://" + text.lstrip("/")


def link_text(url):
    # short label for the address
    href = link_href(url)
    if not href:
        return ""
    try:
        host = urllib.parse.urlsplit(href).netloc or ""
        host = host.lower()
    except ValueError:
        host = ""
    if "gamebanana.com" in host:
        return "GameBanana \u2197"
    if host:
        return host + " \u2197"
    return href


def page_link(url, fallback="View on page"):
    # (label, address) for a sheet byline, or None when it is not a web page
    href = link_href(url)
    if not href:
        return None
    try:
        host = urllib.parse.urlsplit(href).netloc.lower()
    except ValueError:
        host = ""
    if "gamebanana.com" in host:
        label = "GameBanana \u2197"
    else:
        label = "%s %s \u2197" % (fallback, host) if host else fallback + " \u2197"
    return label, href


def middle_ellipsis(text, limit=56):
    # keep both ends of a long path
    value = str(text or "")
    if len(value) <= limit:
        return value
    head = limit // 2 - 2
    tail = limit - head - 2
    return value[:head] + "\u2026" + value[-tail:]


class ClickLabel(QLabel):
    # a label that acts like a link

    def __init__(self, text, callback, parent=None, color=None,
                 underline=True):
        super().__init__(text, parent)
        self._callback = callback
        self.setTextFormat(Qt.PlainText)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "color: %s; background: transparent;%s"
            % (color or Colors.NO_CONFLICT_TEXT,
               " text-decoration: underline;" if underline else ""))

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._callback()
        super().mouseReleaseEvent(event)


class SheetTitle(QLabel):
    # a long title elides instead of widening the panel
    def __init__(self, text, parent=None):
        super().__init__(str(text), parent)
        self._full = str(text)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self):
        # rounded up, so Qt never elides a title that does fit
        return QSize(math.ceil(QFontMetricsF(self.font()).horizontalAdvance(
            self._full)), super().sizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        shown = self.fontMetrics().elidedText(self._full, Qt.ElideRight, self.width())
        if shown != self.text():
            self.setText(shown)


def draw_icon(painter, kind, colour):
    # 14px line icons in a 16 unit box: check, cross, copy, folder
    pen = QPen(colour)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setWidthF(1.4)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    if kind in ("check", "cross"):
        painter.drawEllipse(QPointF(8.0, 8.0), 6.25, 6.25)
        if kind == "check":
            painter.drawPolyline(QPolygonF([QPointF(5.2, 8.2), QPointF(7.1, 10.1),
                                            QPointF(10.8, 5.9)]))
        else:
            painter.drawPolyline(QPolygonF([QPointF(5.8, 5.8), QPointF(10.2, 10.2)]))
            painter.drawPolyline(QPolygonF([QPointF(10.2, 5.8), QPointF(5.8, 10.2)]))
    elif kind == "copy":
        painter.drawRoundedRect(QRectF(5.5, 5.5, 7.5, 7.5), 1.5, 1.5)
        path = QPainterPath()
        path.moveTo(3.0, 10.5)
        path.lineTo(3.0, 4.5)
        path.arcTo(QRectF(3.0, 3.0, 3.0, 3.0), 180, -90)
        path.lineTo(10.5, 3.0)
        painter.drawPath(path)
    elif kind == "folder":
        path = QPainterPath()
        path.moveTo(2.0, 12.5)
        path.lineTo(2.0, 4.0)
        path.arcTo(QRectF(2.0, 2.5, 3.0, 3.0), 180, -90)
        path.lineTo(6.1, 2.5)
        path.lineTo(7.5, 4.3)
        path.lineTo(12.0, 4.3)
        path.arcTo(QRectF(10.5, 4.3, 3.0, 3.0), 90, -90)
        path.lineTo(13.5, 11.0)
        path.arcTo(QRectF(10.5, 9.5, 3.0, 3.0), 0, -90)
        path.lineTo(3.5, 12.5)
        path.arcTo(QRectF(2.0, 9.5, 3.0, 3.0), 270, -90)
        painter.drawPath(path)


class SheetIcon(QWidget):
    # a line icon, centred in a 14px box
    def __init__(self, kind, colour, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._colour = QColor(colour)
        self.setObjectName("sheetIcon")
        self.setFixedSize(14, 14)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.translate(-1.0, -1.0)
        draw_icon(painter, self._kind, self._colour)


class IconButton(QPushButton):
    # square button that draws one line icon
    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setObjectName("sheetIconButton")
        self.setFixedSize(26, ACTION)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("padding: 0;")

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.translate((self.width() - 16) / 2, (self.height() - 16) / 2)
        draw_icon(painter, self._kind, QColor(Colors.TEXT))


class Chip(QWidget):
    # rounded status pill: a tinted background with coloured text
    def __init__(self, text, colour, background, *, icon=None, radius=12,
                 pad=9, mono=False, height=CHIP, parent=None):
        super().__init__(parent)
        self.setObjectName("sheetChip")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("#sheetChip { background: %s; border-radius: %dpx; }"
                           % (background, radius))
        box = QHBoxLayout(self)
        box.setContentsMargins(pad, 0, pad, 0)
        box.setSpacing(6)
        if icon:
            box.addWidget(SheetIcon(icon, colour, self), 0, Qt.AlignVCenter)
        label = QLabel(text, self)
        label.setObjectName("sheetLabel")
        label.setStyleSheet("color: %s; background: transparent;" % colour)
        label.setFont(QFont("Consolas", 10) if mono else label.font())
        box.addWidget(label, 0, Qt.AlignVCenter)
        self.setFixedHeight(height)


class Hairline(QWidget):
    # 1 device pixel line with transparent overlay room
    def __init__(self, color, parent=None, bright=False):
        super().__init__(parent)
        self._color = QColor(color)
        self.setObjectName("sectionRule" if bright else "detailRule")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def place(self, x, boundary_y, width):
        self.setGeometry(x, boundary_y - 1, width, 3)

    def paintEvent(self, event):
        painter = QPainter(self)
        dpr = self.devicePixelRatioF() or 1
        origin_device = self.mapTo(self.window(), QPoint()).y() * dpr
        boundary_device = origin_device + dpr
        target_device = round(boundary_device)
        y = (target_device - origin_device) / dpr
        painter.fillRect(QRectF(0, y, self.width(), 1 / dpr), self._color)


class FieldCell(QWidget):
    # top-aligned text with optional first-line controls
    CONTROL_GAP = 8

    def __init__(self, text, *, mono=False, color=None, wrap=False,
                 elide=False, tooltip="", controls=(), lead=None, parent=None):
        super().__init__(parent)
        self.setObjectName("sheetHost")
        self._plain = str(text)
        self._elide = elide
        self.label = QLabel(self)
        self.label.setObjectName("sheetLabel")
        if mono:
            font = QFont("Consolas")
            font.setStyleHint(QFont.Monospace)
            font.setPointSize(10)
            self.label.setFont(font)
        self.label.setTextFormat(Qt.PlainText)
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.label.setWordWrap(wrap and not elide)
        if mono:
            self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if color:
            self.label.setStyleSheet(
                "color: %s; background: transparent;" % color)
        if tooltip:
            self.label.setToolTip(tooltip)
        self._label_top = round(
            (ACTION - self.label.fontMetrics().lineSpacing()) / 2)
        self.label.setContentsMargins(0, self._label_top, 0, 0)
        self.path = self.label
        self._controls = list(controls)
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(self.CONTROL_GAP)
        if lead is not None:
            box.addWidget(lead, 0, Qt.AlignTop)
        box.addWidget(self.label, 1, Qt.AlignTop)
        for control in self._controls:
            self._prepare(control)
            box.addWidget(control, 0, Qt.AlignTop)
        self.setMinimumHeight(ACTION)
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    @staticmethod
    def _prepare(control):
        if isinstance(control, QLabel):
            control.setMinimumHeight(ACTION)
            control.setAlignment(control.alignment() | Qt.AlignVCenter)
        elif isinstance(control, QPushButton):
            if control.height() != ACTION:
                control.setFixedHeight(ACTION)

    def _lead_width(self):
        layout = self.layout()
        if not layout.count():
            return 0
        item = layout.itemAt(0)
        if item.widget() is self.label:
            return 0
        return item.widget().sizeHint().width() + self.CONTROL_GAP

    def _controls_width(self):
        if not self._controls:
            return 0
        width = sum(control.sizeHint().width() for control in self._controls)
        return width + self.CONTROL_GAP * len(self._controls)

    def _label_width(self, width):
        return max(0, width - self._lead_width() - self._controls_width())

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        label_w = self._label_width(width)
        if self.label.wordWrap():
            return max(ACTION, self.label.heightForWidth(label_w))
        return max(ACTION, self.label.sizeHint().height())

    def sizeHint(self):
        return QSize(240, ACTION)

    def minimumSizeHint(self):
        return QSize(0, ACTION)

    def resizeEvent(self, event):
        if self._elide:
            label_w = self._label_width(self.width())
            self.label.setText(self.label.fontMetrics().elidedText(
                self._plain, Qt.ElideMiddle, label_w))
        super().resizeEvent(event)


class LocationRow(FieldCell):
    # elided path using the common field cell
    def __init__(self, text, *, tooltip="", on_copy=None, on_open=None,
                 parent=None):
        controls = []
        if on_copy:
            button = IconButton("copy")
            button.setToolTip("Copy path")
            button.clicked.connect(lambda _checked=False: on_copy())
            controls.append(button)
        if on_open:
            button = IconButton("folder")
            button.setToolTip("Open folder")
            button.clicked.connect(lambda _checked=False: on_open())
            controls.append(button)
        super().__init__(text, mono=True, elide=True, tooltip=tooltip,
                         controls=controls, parent=parent)


class SheetRow(FieldCell):
    # wrapping sheet line using the common field cell
    def __init__(self, text, *, mono=False, color=None, lead=None,
                 controls=(), parent=None):
        super().__init__(text, mono=mono, color=color, wrap=True,
                         controls=controls, lead=lead, parent=parent)
        self.text = self.label


class ChipCell:
    # chips with an optional note
    def __init__(self, chips, note=""):
        self.chips = chips
        self.note = note


class RowGroup(QWidget):
    # zero-spacing rows with overlaid boundary separators
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sheetHost")
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.rows = []
        self.rules = []

    def add_row(self, row, last):
        self.layout().addWidget(row)
        self.rows.append(row)
        if not last:
            self.rules.append(Hairline(token("rowRule"), self.parent()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        card = self.parent()
        for index, rule in enumerate(self.rules):
            row = self.rows[index]
            y = self.y() + row.y() + row.height()
            rule.place(self.x(), y, card.width() - self.x())
            rule.raise_()


class SectionHeader(QWidget):
    # bold title with an overlaid boundary underline
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("detailSection")
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        label = QLabel(title, self)
        label.setObjectName("sheetLabel")
        label.setProperty("role", "section")
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        box.addWidget(label)
        self.title = label
        self.rule = Hairline(token("sectionRule"), parent, bright=True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        y = self.y() + self.title.y() + self.title.height()
        self.rule.place(0, y, self.parent().width())
        self.rule.raise_()


class FieldRow(QWidget):
    # shared key/value row with metric-derived equal padding
    SPACING = 10

    def __init__(self, key, cell, parent=None, key_width=0):
        super().__init__(parent)
        self.setObjectName("detailRow")
        self._key_width = key_width
        self._key = key
        self._cell = cell
        key.setParent(self)
        cell.setParent(self)
        key.setFixedWidth(key_width)
        key.setFixedHeight(key.fontMetrics().height())
        key.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def is_valid(self):
        if isinstance(self._cell, QLabel):
            return bool(self._cell.text().strip())
        plain = getattr(self._cell, "_plain", None)
        if plain is not None:
            return bool(str(plain).strip())
        return True

    def _pad(self):
        return math.ceil(self.fontMetrics().lineSpacing() / 3)

    def _cell_width(self, width):
        return max(0, width - self._key_width - self.SPACING)

    def _cell_height(self, cell_w):
        if self._cell.hasHeightForWidth():
            return self._cell.heightForWidth(cell_w)
        return self._cell.sizeHint().height()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        cell_w = self._cell_width(width)
        cell_h = self._cell_height(cell_w)
        pad = self._pad()
        return 2 * pad + max(ACTION, cell_h)

    def sizeHint(self):
        return QSize(240, 2 * self._pad() + ACTION)

    def minimumSizeHint(self):
        return QSize(0, 2 * self._pad() + ACTION)

    def resizeEvent(self, event):
        pad = self._pad()
        cell_w = self._cell_width(self.width())
        cell_h = self._cell_height(cell_w)
        key_y = round(
            pad + (ACTION - self._key.fontMetrics().lineSpacing()) / 2)
        self._key.setGeometry(0, key_y, self._key_width, self._key.height())
        self._cell.setGeometry(
            self._key_width + self.SPACING, pad, cell_w, cell_h)
        super().resizeEvent(event)


class DetailsPanel(QFrame):
    # details column

    overflow = Signal(int)      # fresh content taller than the viewport

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("detailsPanel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.viewport().setAutoFillBackground(False)

        self._body = QWidget(self._scroll)
        # its height comes from _fit, not from the width-blind size hint
        self._body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(8, 6, 8, 8)
        self._layout.setSpacing(6)
        self._layout.addStretch(1)
        self._box = None      # layout of the open sheet
        self._overhang = 0    # how far the sheet's last row drops past its line
        self._fresh = False   # a render is waiting for its fit
        self._fit_tries = 0
        self.quiet = False    # a redraw must not grow the window
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._fit)
        self._body.installEventFilter(self)

        self._scroll.setWidget(self._body)
        outer.addWidget(self._scroll)

    def eventFilter(self, watched, event):
        if watched is self._body and event.type() in (QEvent.Resize,
                                                      QEvent.LayoutRequest):
            self._fit()
        return super().eventFilter(watched, event)

    def _fit(self):
        # the body is exactly as tall as its content wraps at its current width
        body = self._body
        if not body.isVisible():
            return
        height = body.heightForWidth(body.width())
        if height < 0:
            if self._fresh and self._fit_tries < 3:
                # rows just added are still hidden, so nothing wraps yet
                self._fit_tries += 1
                self._fit_timer.start(0)
                return
            height = body.sizeHint().height()
        if height != body.minimumHeight():
            body.setMinimumHeight(height)
        if not self._fresh:
            return
        # only a render asks for room: a manual resize must be left alone
        self._fresh = False
        short = height - self._scroll.viewport().height()
        if short > 0 and not self.quiet:
            self.overflow.emit(short)

    # basics
    def clear(self):
        self._box = None
        self._overhang = 0
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._layout.addStretch(1)

    def add_widget(self, widget):
        if self._box is not None:
            self._box.addWidget(widget)
        else:
            self._layout.insertWidget(self._layout.count() - 1, widget)
        self._refresh_row_rules()
        self._fresh = True
        self._fit_tries = 0
        self._fit_timer.start(0)
        return widget

    def _refresh_row_rules(self):
        # RowGroup owns boundary separators
        return

    @staticmethod
    def _is_block_row(widget):
        layout = widget.layout()
        if layout is None or not layout.count():
            return False
        return isinstance(layout.itemAt(0).widget(), SheetRow)

    @staticmethod
    def _row_valid(row):
        return row.is_valid() if isinstance(row, FieldRow) else True

    def placeholder(self, text="Select a mod to see its details."):
        self.clear()
        label = QLabel(text, self._body)
        label.setStyleSheet("color: %s;" % token("textMuted"))
        label.setWordWrap(True)
        self.add_widget(label)

    def heading(self, text, size=13):
        label = QLabel(text, self._body)
        font = label.font()
        font.setPointSize(size)
        font.setBold(True)
        label.setFont(font)
        label.setWordWrap(True)
        self.add_widget(label)
        return label

    def label(self, text, *, color=None, wrap=True, mono=False, bold=False,
              selectable=False):
        label = QLabel(str(text), self._body)
        label.setWordWrap(wrap)
        label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        label.setTextInteractionFlags(
            Qt.TextSelectableByMouse if selectable or mono else Qt.NoTextInteraction)
        if color:
            label.setStyleSheet("color: %s; background: transparent;" % color)
        if mono:
            font = QFont("Consolas")
            font.setStyleHint(QFont.Monospace)
            font.setPointSize(10)
            label.setFont(font)
        if bold:
            font = label.font()
            font.setBold(True)
            label.setFont(font)
        self.add_widget(label)
        return label

    def hint(self, text, color=None):
        return self.label(text, color=color or token("textMuted"), wrap=True)

    def header(self, name, badge="", subtitle=""):
        # name with an optional version pill, id underneath
        holder = QWidget(self._body)
        box = QHBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        title = QLabel(name, holder)
        title.setTextFormat(Qt.PlainText)
        font = title.font()
        font.setPointSize(13)
        font.setBold(True)
        title.setFont(font)
        title.setWordWrap(True)
        box.addWidget(title, 0)
        if badge:
            pill = QLabel(badge, holder)
            pill.setStyleSheet(
                "color: %s; background: %s; border-radius: 8px; "
                "padding: 2px 8px;" % (token("textMuted"), token("chipBg")))
            box.addWidget(pill, 0)
        box.addStretch(1)
        self.add_widget(holder)
        if subtitle:
            self.label(subtitle, color=token("textMuted"))
        return holder

    def summary(self, text):
        return self.hint(text, color=Colors.TEXT_MUTED)

    def section(self, title):
        # a little air above each bold header
        spacer = QWidget(self._body)
        spacer.setFixedHeight(4)
        self.add_widget(spacer)
        return self.label(title, bold=True)

    def description(self, text):
        # long text folds behind a toggle
        full = str(text or "")
        label = self.label(full)
        label.setTextFormat(Qt.PlainText)
        if len(full) < 220:
            return label
        short = full[:210].rsplit(" ", 1)[0].rstrip(" ,.;:") + "\u2026"
        label.setText(short)
        toggle = QPushButton("Show more", self._body)
        toggle.setCursor(Qt.PointingHandCursor)
        toggle.setFlat(True)
        toggle.setFixedWidth(96)
        toggle.setStyleSheet(
            "color: %s; background: transparent; border: none; "
            "text-align: left; padding: 0;" % Colors.NO_CONFLICT_TEXT)

        def _toggle(_checked=False):
            if label.text() == short:
                label.setText(full)
                toggle.setText("Show less")
            else:
                label.setText(short)
                toggle.setText("Show more")

        toggle.clicked.connect(_toggle)
        self.add_widget(toggle)
        return label

    # cards
    def card(self, rows, *, open_path=None, open_label="Open mod folder"):
        # rows: (label, value) pairs
        card = QFrame(self._body)
        card.setObjectName("detailsCard")
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        for index, row in enumerate(rows):
            name, value = row[0], row[1]
            opts = row[2] if len(row) > 2 and isinstance(row[2], dict) else {}
            key = QLabel(str(name), card)
            key.setObjectName("fieldLabel")
            key.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            grid.addWidget(key, index, 0)

            if isinstance(value, QWidget):
                grid.addWidget(value, index, 1)
                continue
            is_path = str(name).rstrip(":").lower() in (
                "location", "folder", "file", "path")
            display = str(value)
            text = wrap_path_text(display) if is_path else display
            if opts.get("click"):
                val = ClickLabel(text, opts["click"], card,
                                 color=opts.get("color"),
                                 underline=opts.get("underline", True))
                val.setWordWrap(True)
                val.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            else:
                val = QLabel(text, card)
                val.setObjectName("fieldValue")
                val.setTextFormat(Qt.PlainText)
                val.setWordWrap(True)
                val.setAlignment(Qt.AlignLeft | Qt.AlignTop)
                val.setTextInteractionFlags(Qt.TextSelectableByMouse)
                if opts.get("color"):
                    val.setStyleSheet("color: %s; background: transparent;"
                                      % opts["color"])
            if opts.get("tooltip"):
                val.setToolTip(opts["tooltip"])
            # indent with a margin, not padding
            val.setContentsMargins(6, 0, 0, 0)
            grid.addWidget(val, index, 1)

        if open_path:
            button = QPushButton(open_label, card)
            button.setFixedWidth(140)
            button.clicked.connect(
                lambda _checked=False, p=open_path: open_in_file_explorer(p))
            grid.addWidget(button, len(rows), 0, 1, 2, Qt.AlignRight)

        self.add_widget(card)
        return card

    def link(self, url, text=None):
        # clickable url, handed to the system browser
        href = link_href(url)
        if not href:
            return None
        label = QLabel(self._body)
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        label.setText('<a href="%s" style="color: %s;">%s</a>'
                      % (html.escape(href, quote=True), Colors.NO_CONFLICT_TEXT,
                         html.escape(text or link_text(url) or str(url).strip())))
        label.setOpenExternalLinks(True)
        label.setCursor(Qt.PointingHandCursor)
        label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        label.setToolTip(str(url))
        label.setContentsMargins(0, 0, 0, 0)
        self.add_widget(label)
        return label

    def list_card(self, title, rows):
        # grouped rows: name (+ id), status on the right
        card = QFrame(self._body)
        card.setObjectName("detailsCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(6)
        head = None
        if title:
            head = QLabel(str(title), card)
            font = head.font()
            font.setBold(True)
            head.setFont(font)
            box.addWidget(head)

        for row in rows:
            left, right = row[0], row[1]
            color = row[2] if len(row) > 2 else None
            secondary = row[3] if len(row) > 3 else ""
            holder = QWidget(card)
            line = QHBoxLayout(holder)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            name = QLabel(holder)
            name.setTextFormat(Qt.RichText)
            name.setWordWrap(True)
            name_text = html.escape(str(left))
            if secondary:
                name_text += (' <span style="color: %s; font-size: 8pt;">%s</span>'
                              % (Colors.TEXT_MUTED, html.escape(str(secondary)))
                              )
            name.setText(name_text)
            line.addWidget(name, 1)
            note = QLabel(str(right), holder)
            note.setStyleSheet("color: %s; background: transparent;"
                               % (color or Colors.TEXT))
            note.setAlignment(Qt.AlignRight | Qt.AlignTop)
            line.addWidget(note, 0)
            box.addWidget(holder)
        self.add_widget(card)
        return card

    def action_row(self, buttons):
        # one row of buttons under the cards
        holder, box = self.row(margins=(0, 4, 0, 0), spacing=6)
        box.addStretch(1)
        for entry in buttons:
            text, callback = entry[0], entry[1]
            width = entry[2] if len(entry) > 2 else 110
            button = QPushButton(text, holder)
            button.setFixedWidth(width)
            button.clicked.connect(lambda _checked=False, cb=callback: cb())
            box.addWidget(button)
        return holder

    def code_area(self, content, *, editable=False, height=None):
        editor = QPlainTextEdit(self._body)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        editor.setFont(font)
        editor.setPlainText(content)
        editor.setReadOnly(not editable)
        editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        if height:
            editor.setFixedHeight(height)
        editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.add_widget(editor)
        return editor

    def row(self, *, margins=(0, 0, 0, 0), spacing=8):
        # one-line row
        widget = QWidget(self._body)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        box = QHBoxLayout(widget)
        box.setContentsMargins(*margins)
        box.setSpacing(spacing)
        self.add_widget(widget)
        return widget, box

    def action(self, text, callback, width=120, parent=None):
        button = QPushButton(text, parent or self._body)
        button.setFixedWidth(width)
        button.clicked.connect(lambda _checked=False: callback())
        return button

    # sheet
    def _host(self, parent=None, *, top=0, left=0, horizontal=False):
        # a clear holder whose layout starts at the given offsets
        widget = QWidget(parent or self._body)
        widget.setObjectName("sheetHost")
        box = (QHBoxLayout if horizontal else QVBoxLayout)(widget)
        box.setContentsMargins(left, top, 0, 0)
        box.setSpacing(0)
        return widget

    def _line(self, text, parent, *, colour=None, height=LINE,
              mono=False, bold=False, size=0, italic=False, wrap=False,
              cls=QLabel, role=None):
        # one text line, centred in its box; a role leaves its colour to
        # the theme
        label = cls(str(text), parent)
        label.setObjectName("sheetLabel")
        label.setTextFormat(Qt.PlainText)
        if role:
            label.setProperty("role", role)
        font = QFont("Consolas") if mono else label.font()
        if mono:
            font.setStyleHint(QFont.Monospace)
            # match the default line height so mono rows are not squished
            font.setPointSize(10)
        if bold:
            font.setBold(True)
        if italic:
            font.setItalic(True)
        if size:
            font.setPointSize(size)
        label.setFont(font)
        label.setWordWrap(wrap)
        label.setAlignment(Qt.AlignLeft | (Qt.AlignTop if wrap else Qt.AlignVCenter))
        # the app stylesheet sizes every font, so the size must live here too
        look = ["background: transparent"]
        if colour and not role:
            look.insert(0, "color: %s" % colour)
        if size:
            look.append("font-size: %dpt" % size)
        if bold:
            look.append("font-weight: bold")
        if italic:
            look.append("font-style: italic")
        label.setStyleSheet("; ".join(look) + ";")
        if wrap:
            label.setMinimumHeight(height)
        else:
            label.setFixedHeight(height)
        return label

    def sheet(self):
        # one rounded card; everything added after this lands inside it
        card = QFrame(self._body)
        card.setObjectName("detailsSheet")
        box = QVBoxLayout(card)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(0)
        self.add_widget(card)
        self._box = box
        return card

    def sheet_header(self, name, *, version="", enabled=None, on_toggle=None,
                     menu=()):
        # title, version and state pills, then the switch and an overflow menu
        holder = self._host(horizontal=True)
        box = holder.layout()
        box.setSpacing(8)
        title = self._line(name, holder, height=ACTION, bold=True, size=13,
                           cls=SheetTitle)
        title.setToolTip(str(name))
        box.addWidget(title, 0)
        if version:
            box.addWidget(Chip(version, token("textMuted"), token("chipBg"),
                               parent=holder), 0, Qt.AlignVCenter)
        if enabled is not None:
            on = bool(enabled)
            colour = Colors.RESOLVED_CONFLICT if on else Colors.TEXT_MUTED
            box.addWidget(Chip("Enabled" if on else "Disabled", colour,
                               tint(colour), icon="check" if on else "cross",
                               parent=holder), 0, Qt.AlignVCenter)
        box.addStretch(1)
        if on_toggle:
            button = QPushButton("Disable" if enabled else "Enable", holder)
            button.setFixedHeight(ACTION)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False: on_toggle())
            box.addWidget(button, 0, Qt.AlignVCenter)
        if menu:
            button = QPushButton("\u00b7\u00b7\u00b7", holder)
            button.setFixedSize(30, ACTION)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet("padding: 5px 0; font-weight: bold;")
            button.clicked.connect(lambda _checked=False: self._popup(button, menu))
            box.addWidget(button, 0, Qt.AlignVCenter)
        self.add_widget(holder)
        return holder

    def _popup(self, button, entries):
        # entries are (text, callback), or None for a separator
        menu = QMenu(self)
        for entry in entries:
            if entry is None:
                menu.addSeparator()
                continue
            menu.addAction(entry[0], entry[1])
        menu.exec(button.mapToGlobal(QPoint(0, button.height() + 4)))

    def sheet_byline(self, parts, *, top=3):
        # plain text and links on one line: "by A" and a page link
        if not parts:
            return None
        holder = self._host(top=top, horizontal=True)
        box = holder.layout()
        box.setSpacing(4)
        for index, part in enumerate(parts):
            if index:
                box.addWidget(self._line("\u00b7", holder), 0, Qt.AlignVCenter)
            if isinstance(part, (tuple, list)):
                text, url = part
                link = ClickLabel(
                    text, lambda _checked=False, target=url: webbrowser.open(target),
                    holder, color=Colors.NO_CONFLICT_TEXT, underline=False)
                link.setMinimumHeight(LINE)
                link.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                link.setToolTip(str(url))
                link.setWordWrap(True)
                box.addWidget(link, 0, Qt.AlignVCenter)
            else:
                box.addWidget(self._line(part, holder), 0, Qt.AlignVCenter)
        box.addStretch(1)
        self.add_widget(holder)
        return holder

    def sheet_text(self, text, *, top=0, left=0, **look):
        # one text line, or a paragraph when wrap is on
        holder = self._host(top=top, left=left)
        holder.layout().addWidget(self._line(text, holder, **look))
        self.add_widget(holder)
        return holder

    def section_gap(self):
        return math.ceil(self.fontMetrics().lineSpacing() * 0.8)

    def sheet_banner(self, text, *, top=8):
        # full-width warning inside the card, styled by the warningBanner rule
        holder = self._host(top=top)
        label = QLabel(text, holder)
        label.setObjectName("warningBanner")
        label.setWordWrap(True)
        holder.layout().addWidget(label)
        self.add_widget(holder)
        return holder

    def sheet_group(self, title):
        if self._box.count():
            gap = QWidget(self._box.parentWidget())
            gap.setObjectName("sectionGap")
            gap.setFixedHeight(self.section_gap())
            self._box.addWidget(gap)
        section = SectionHeader(title, self._box.parentWidget())
        self._box.addWidget(section)

    def sheet_block(self, widget, *, top=GAP):
        holder = self._host(top=top)
        widget.setParent(holder)
        holder.layout().addWidget(widget)
        self.add_widget(holder)
        return holder

    def sheet_tag(self, text, colour=Colors.TEXT_MUTED):
        return self._line(text, None, colour=colour)

    def key_width(self):
        return self.fontMetrics().horizontalAdvance("Load order") + 12

    def sheet_fields(self, rows):
        group = RowGroup(self._box.parentWidget())
        for index, row in enumerate(rows):
            key, value = row[0], row[1]
            opts = row[2] if len(row) > 2 and isinstance(row[2], dict) else {}
            cell, _height, _overhang = self._cell(value, opts, group)
            label = self._line(key, group, role="key")
            field = FieldRow(label, cell, group, key_width=self.key_width())
            group.add_row(field, index == len(rows) - 1)
        self.add_widget(group)
        return group

    def _cell(self, value, opts, parent):
        if isinstance(value, (LocationRow, SheetRow, FieldCell)):
            return value, ACTION, 0
        if isinstance(value, ChipCell):
            chip_host = QWidget(parent)
            chip_host.setObjectName("chipHost")
            chip_box = QHBoxLayout(chip_host)
            chip_box.setContentsMargins(0, 0, 0, 0)
            chip_box.setSpacing(10)
            for text, colour in value.chips:
                chip_box.addWidget(Chip(
                    text, colour, tint(colour), radius=6, pad=8, mono=True,
                    height=ACTION, parent=chip_host), 0, Qt.AlignTop)
            cell = FieldCell(
                value.note, wrap=bool(value.note), lead=chip_host,
                parent=parent)
            return cell, ACTION, 0
        if isinstance(value, QWidget):
            return value, LINE, 0
        cell = FieldCell(
            value, mono=opts.get("mono", False), color=opts.get("color"),
            wrap=True, tooltip=opts.get("tooltip", ""), parent=parent)
        if opts.get("placeholder"):
            cell.label.setStyleSheet(
                "color: %s; background: transparent;" % PLACEHOLDER)
        elif not opts.get("color"):
            cell.label.setProperty("role", "value")
        return cell, ACTION, 0

