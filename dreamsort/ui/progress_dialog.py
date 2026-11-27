# small modal progress windows

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
)

from ..constants import Colors
from ..workers.autofind import FOLDER_BUDGET


class AutoFindProgressDialog(QDialog):
    # the main window stays visible behind this; no black overlay
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auto-Find")
        self.setModal(True)
        self.resize(470, 190)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(9)

        head = QLabel("Searching this PC for the mods folder…")
        font = head.font()
        font.setBold(True)
        head.setFont(font)
        layout.addWidget(head)

        self.bar = QProgressBar(self)
        self.bar.setRange(0, FOLDER_BUDGET)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)

        self.count_label = QLabel("0 folders scanned…")
        layout.addWidget(self.count_label)

        self.path_label = QLabel("")
        self.path_label.setStyleSheet(
            "color: %s; background: transparent;" % Colors.TEXT_MUTED)
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel", self)
        cancel.setFixedWidth(100)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        layout.addLayout(row)

    def update_progress(self, info):
        scanned = int(info.get("scanned", 0))
        self.bar.setValue(min(scanned, FOLDER_BUDGET))
        self.count_label.setText(
            "%s folders scanned…" % format(scanned, ","))
        self.path_label.setText(info.get("path", ""))
