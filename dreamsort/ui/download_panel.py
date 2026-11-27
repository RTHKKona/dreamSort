# download queue panel

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from ..constants import Colors

STATE_TEXT = {
    "queued": "Queued",
    "downloading": "Downloading",
    "ready": "Downloaded",
    "installed": "Installed",
    "error": "Failed",
    "canceled": "Canceled",
}


def _format_size(num_bytes):
    size = float(num_bytes or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return "%.1f %s" % (size, unit)
        size /= 1024
    return "%.1f GB" % size


class DownloadQueuePanel(QWidget):
    # shared by the bottom strip and the dialog

    open_folder_requested = Signal()

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = QHBoxLayout()
        self.title = QLabel("DOWNLOADS", self)
        self.title.setStyleSheet("color: %s; background: transparent;"
                                 % Colors.TEXT_MUTED)
        header.addWidget(self.title)
        header.addStretch(1)
        self.clear_btn = QPushButton("Clear finished", self)
        self.clear_btn.setFixedWidth(120)
        self.clear_btn.clicked.connect(self.service.clear_finished)
        header.addWidget(self.clear_btn)
        layout.addLayout(header)

        self.list = QListWidget(self)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        layout.addWidget(self.list, 1)

        service.queue_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for entry in self.service.entries():
            self._add_row(entry)
        active = self.service.active_count()
        suffix = " (%d active)" % active if active else ""
        self.title.setText("DOWNLOADS%s" % suffix)

    def _add_row(self, entry):
        item = QListWidgetItem(self.list)
        row = QWidget(self.list)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(6, 3, 6, 3)
        row_layout.setSpacing(8)

        name = QLabel(entry.get("label", ""), row)
        status = QLabel(STATE_TEXT.get(entry["status"], entry["status"]), row)
        status.setFixedWidth(92)
        bar = QProgressBar(row)
        total = entry.get("total") or 0
        received = entry.get("received") or 0
        if entry["status"] == "downloading" and not total:
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 100)
            bar.setValue(int(received / total * 100) if total else 0)
        size = QLabel(_format_size(received), row)
        size.setFixedWidth(90)

        row_layout.addWidget(name, 1)
        row_layout.addWidget(status, 0)
        row_layout.addWidget(bar, 1)
        row_layout.addWidget(size, 0)
        item.setSizeHint(row.sizeHint())
        self.list.addItem(item)
        self.list.setItemWidget(item, row)

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        entries = self.service.entries()
        row = self.list.row(item)
        if row < 0 or row >= len(entries):
            return
        entry = entries[row]
        menu = QMenu(self)
        if entry["status"] in ("queued", "downloading"):
            menu.addAction("Cancel",
                           lambda: self.service.cancel_download(entry["id"]))
        menu.addAction("Open downloads folder", self.open_folder_requested.emit)
        menu.exec(self.list.viewport().mapToGlobal(pos))


class DownloadsDialog(QDialog):
    # standalone window over the same queue

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.setWindowTitle("dreamSort \u2014 Downloads")
        self.resize(580, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.panel = DownloadQueuePanel(service, self)
        layout.addWidget(self.panel)
