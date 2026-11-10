# details pane

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ..constants import Colors
from ..helpers.files import open_in_file_explorer


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


class DetailsPanel(QFrame):
    # details column

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
        self._body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(8, 6, 8, 8)
        self._layout.setSpacing(6)
        self._layout.addStretch(1)

        self._scroll.setWidget(self._body)
        outer.addWidget(self._scroll)

    # basics
    def clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._layout.addStretch(1)

    def add_widget(self, widget):
        self._layout.insertWidget(self._layout.count() - 1, widget)
        return widget

    def placeholder(self, text="Select a mod to see its details."):
        self.clear()
        label = QLabel(text, self._body)
        label.setStyleSheet("color: %s;" % Colors.TEXT_MUTED)
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
            font.setPointSize(9)
            label.setFont(font)
        if bold:
            font = label.font()
            font.setBold(True)
            label.setFont(font)
        self.add_widget(label)
        return label

    def hint(self, text, color=Colors.DISABLED):
        return self.label(text, color=color, wrap=True)

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

        for index, (name, value) in enumerate(rows):
            key = QLabel(str(name), card)
            key.setObjectName("fieldLabel")
            key.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            grid.addWidget(key, index, 0)

            is_path = str(name).rstrip(":").lower() == "location"
            text = wrap_path_text(value) if is_path else str(value)
            val = QLabel(text, card)
            val.setObjectName("fieldValue")
            val.setWordWrap(True)
            val.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            # indent with a margin, not padding
            val.setContentsMargins(6, 0, 0, 0)
            grid.addWidget(val, index, 1)

        if open_path:
            button = QPushButton(open_label, card)
            button.setFixedWidth(140)
            button.clicked.connect(
                lambda _checked=False, p=open_path: open_in_file_explorer(p))
            grid.addWidget(button, len(rows), 0, 1, 2, Qt.AlignLeft)

        self.add_widget(card)
        return card

    def code_area(self, content, *, editable=False, height=None):
        editor = QPlainTextEdit(self._body)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
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
