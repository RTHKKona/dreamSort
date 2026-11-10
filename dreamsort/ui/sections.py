# sections

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    # header toggles the body

    def __init__(self, title, collapsed=False, body=None, parent=None):
        super().__init__(parent)
        self.title_text = title
        self.collapsed = bool(collapsed)

        if body is None:
            body = QWidget(self)
            body_layout = QVBoxLayout(body)
            body_layout.setContentsMargins(0, 0, 0, 0)
            body_layout.setSpacing(4)
        else:
            body_layout = body.layout()
            if body_layout is None:
                body_layout = QVBoxLayout(body)
                body_layout.setContentsMargins(0, 0, 0, 0)
        self.body = body
        self.body_layout = body_layout

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.header = QToolButton(self)
        self.header.setObjectName("sectionHeader")
        self.header.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.header.setCheckable(False)
        self.header.setSizePolicy(self.header.sizePolicy().horizontalPolicy(),
                                  self.header.sizePolicy().verticalPolicy())
        self.header.clicked.connect(self.toggle)
        layout.addWidget(self.header, 0)

        layout.addWidget(self.body, 1)
        self.body.setVisible(not self.collapsed)
        self._refresh_header()

    def _refresh_header(self):
        arrow = "\u25b6" if self.collapsed else "\u25bc"   # arrow
        self.header.setText("%s %s" % (arrow, self.title_text))

    def set_title(self, title):
        self.title_text = title
        self._refresh_header()

    def toggle(self):
        self.collapsed = not self.collapsed
        self.body.setVisible(not self.collapsed)
        self._refresh_header()
