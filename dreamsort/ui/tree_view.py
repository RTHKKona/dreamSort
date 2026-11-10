# conflict tree

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QTreeWidget, QTreeWidgetItem,
)

from ..constants import Colors

# tag -> colour
TAG_COLORS = {
    "winner": Colors.RESOLVED_CONFLICT,
    "loser": Colors.CONFLICT,
    "loaded": Colors.NO_CONFLICT_TEXT,
    "noconflict": Colors.TEXT,
    "cheat": Colors.CHEAT_MOD,
    "disabled": Colors.DISABLED,
}


class ConflictTree(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderLabels(["Mod / File", "Status"])
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(False)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)

    def clear_items(self):
        self.clear()

    def add_item(self, parent_item, text, status="", tag="noconflict"):
        if parent_item is None:
            item = QTreeWidgetItem(self)
        else:
            item = QTreeWidgetItem(parent_item)
        item.setText(0, text)
        item.setText(1, status)
        color = TAG_COLORS.get(tag)
        if color:
            brush = QBrush(QColor(color))
            item.setForeground(0, brush)
            item.setForeground(1, brush)
        return item
