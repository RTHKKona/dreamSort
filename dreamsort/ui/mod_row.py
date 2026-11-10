# mod row

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget,
)

from ..constants import Colors
from .dnd import MOD_ROW_MIME


class CheckMark(QAbstractButton):
    # boxed tick
    def __init__(self, parent=None, size=16):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        box = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        on = self.isChecked()
        live = self.isEnabled()
        if on:
            fill = QColor(Colors.PRIMARY if live else Colors.DISABLED)
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(box, 3.0, 3.0)
            pen = QPen(QColor(Colors.PRIMARY_TEXT if live else Colors.BG))
            pen.setWidthF(1.6)
            painter.setPen(pen)
            width, height = float(self.width()), float(self.height())
            painter.drawLine(QPointF(width * 0.28, height * 0.52),
                             QPointF(width * 0.45, height * 0.68))
            painter.drawLine(QPointF(width * 0.45, height * 0.68),
                             QPointF(width * 0.74, height * 0.34))
            return
        border = QColor(Colors.TEXT_MUTED if self.underMouse() else
                        (Colors.DISABLED if live else Colors.BORDER))
        painter.setBrush(Qt.NoBrush)
        pen = QPen(border)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawRoundedRect(box, 3.0, 3.0)


class ModRow(QFrame):
    # one mod row

    toggled = Signal(str, bool)          # mod_id, enabled
    activated = Signal(str)              # left click
    ctrlClicked = Signal(str)            # ctrl click
    contextRequested = Signal(str, object)  # mod_id, global pos

    def __init__(self, mod_id, name, *, checkbox=True, chips=(),
                 variant="romfs", bold=False, draggable=True, index=None,
                 parent=None):
        super().__init__(parent)
        self.mod_id = mod_id
        self.display_name = name
        self.variant = variant
        self.draggable = draggable
        self._index = None

        self.setObjectName("modRow")
        # needed for the qss background
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFrameShape(QFrame.NoFrame)
        self.setProperty("conflictState", "none")
        self.setProperty("variant", variant)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 4, 8, 4)
        self._layout.setSpacing(8)

        # order gutter
        self.index_label = QLabel("", self)
        self.index_label.setObjectName("modIndex")
        self.index_label.setFixedWidth(18)
        self.index_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.index_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.index_label.hide()
        self._layout.addWidget(self.index_label, 0)
        if index is not None:
            self.set_index(index)

        self.checkbox = None
        if checkbox:
            self.checkbox = CheckMark(self, size=18)
            self.checkbox.toggled.connect(self._on_toggled)
            self._layout.addWidget(self.checkbox, 0)

        self.name_label = QLabel(name, self)
        self.name_label.setObjectName("modName")
        self.name_label.setSizePolicy(QSizePolicy.Expanding,
                                      QSizePolicy.Preferred)
        self.name_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        if bold:
            font = self.name_label.font()
            font.setBold(True)
            self.name_label.setFont(font)
        self._layout.addWidget(self.name_label, 1)

        self.handle = None
        self.chip_labels = []
        for spec in chips:
            self._add_chip(spec)

        if checkbox:
            self.handle = QLabel("\u2261", self)   # drag handle
            self.handle.setObjectName("dragHandle")
            self.handle.setFixedWidth(18)
            self.handle.setAlignment(Qt.AlignCenter)
            self.handle.setCursor(Qt.SizeAllCursor)
            self.handle.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._layout.addWidget(self.handle, 0)

    # chips
    def _add_chip(self, spec):
        if isinstance(spec, str):
            text, kind, is_bold = spec, "none", False
        else:
            text, kind, is_bold = (list(spec) + [None, None, None])[:3]
            kind = kind or "none"
            is_bold = bool(is_bold)
        chip = QLabel(text, self)
        chip.setObjectName("chip")
        chip.setProperty("kind", kind)
        chip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        chip.setAlignment(Qt.AlignCenter)
        if is_bold:
            font = chip.font()
            font.setBold(True)
            chip.setFont(font)
        self._layout.insertWidget(self._layout.count() - (1 if self.handle
                                                          else 0), chip)
        self.chip_labels.append(chip)

    # setters
    def _repolish(self):
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    def set_name(self, name):
        self.display_name = name
        self.name_label.setText(name)

    def set_index(self, index, reserve=False):
        # position, reserve = no number
        self._index = index
        self.index_label.setText("" if index is None else str(index))
        self.index_label.setVisible(index is not None or reserve)

    def set_mod_enabled(self, enabled):
        # enabled flag
        if self.checkbox is not None and self.checkbox.isChecked() != bool(enabled):
            self.checkbox.blockSignals(True)
            self.checkbox.setChecked(bool(enabled))
            self.checkbox.blockSignals(False)
        self.set_conflict_state("none" if enabled else "disabled")

    def set_conflict_state(self, state):
        # state
        if self.property("conflictState") == state:
            return
        self.setProperty("conflictState", state)
        self._repolish()

    def set_selected(self, selected):
        state = "selected" if selected else (
            "none" if self.is_enabled_state() else "disabled")
        self.setProperty("selected", bool(selected))
        self.set_conflict_state(state)

    def is_enabled_state(self):
        if self.checkbox is None:
            return True
        return self.checkbox.isChecked()

    def _on_toggled(self, checked):
        self.set_conflict_state("none" if checked else "disabled")
        self.toggled.emit(self.mod_id, checked)

    # events
    def _on_handle(self, pos) -> bool:
        if self.handle is None:
            return False
        return self.handle.geometry().contains(pos)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.contextRequested.emit(self.mod_id,
                                       event.globalPosition().toPoint())
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            if self.draggable and self._on_handle(pos):
                self._start_drag()
                event.accept()
                return
            if event.modifiers() & Qt.ControlModifier:
                self.ctrlClicked.emit(self.mod_id)
            else:
                self.activated.emit(self.mod_id)
            event.accept()
            return
        super().mousePressEvent(event)

    def _start_drag(self):
        # start a drag
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MOD_ROW_MIME, str(self.mod_id).encode("utf-8"))
        mime.setText(self.display_name)
        drag.setMimeData(mime)
        pixmap = self.grab()
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        drag.exec(Qt.MoveAction)


class FileRow(QFrame):
    # small row

    toggled = Signal(object, bool)   # key
    activated = Signal(object)       # key

    def __init__(self, key, text, *, checked=True, enabled=True, muted=False,
                 parent=None):
        super().__init__(parent)
        self.key = key

        self.setObjectName("fileRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFrameShape(QFrame.NoFrame)
        self.setProperty("active", bool(checked))
        self.setProperty("missing", False)
        self.setProperty("selected", False)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)

        self.checkbox = CheckMark(self, size=16)
        self.checkbox.setChecked(bool(checked) and enabled)
        self.checkbox.setEnabled(enabled)
        self.checkbox.toggled.connect(self._on_toggled)
        layout.addWidget(self.checkbox, 0)

        self.label = QLabel(text, self)
        self.label.setObjectName("fileName")
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        if muted:
            self.label.setStyleSheet("color: #6e6e6e;")
        layout.addWidget(self.label, 1)

        self.note = QLabel("", self)
        self.note.setStyleSheet("color: #6e6e6e;")
        self.note.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.note.hide()
        layout.addWidget(self.note, 0)

    def _repolish(self):
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    def set_active(self, active):
        self.setProperty("active", bool(active))
        self._repolish()

    def set_selected(self, selected):
        if bool(self.property("selected")) == bool(selected):
            return
        self.setProperty("selected", bool(selected))
        # repolish the label too
        for widget in (self, self.label):
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)
        self.update()

    def set_note(self, text):
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def _on_toggled(self, checked):
        self.set_active(checked)
        self.toggled.emit(self.key, checked)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # press selects, the tick is separate
            self.activated.emit(self.key)
            event.accept()
            return
        super().mousePressEvent(event)
