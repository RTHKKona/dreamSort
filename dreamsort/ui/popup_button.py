# a tool button that opens its menu on click, Enter or Space

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton


class PopupButton(QToolButton):
    # InstantPopup opens on click and Space; Enter is added here so the
    # button works from the keyboard either way
    def __init__(self, text, menu, parent=None):
        super().__init__(parent)
        self.setObjectName("moreBtn")
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setPopupMode(QToolButton.InstantPopup)
        self.setMenu(menu)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.showMenu()
            return
        super().keyPressEvent(event)
