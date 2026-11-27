# plugin ini editor
#
# plugin inis live beside the save, not next to the .nro.

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)

from ..constants import Colors
from ..helpers.files import open_in_file_explorer
from ..redact import redact_path
from ..storage.atomic import atomic_write_text


def default_save_dir():
    # %APPDATA%/MHGURecomp/save/save_0
    appdata = os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(appdata, "MHGURecomp", "save", "save_0")


def _save_location_ini(recomp_root=""):
    # mhgurecomp.ini may redirect [Application] SaveLocation
    names = ("mhgurecomp.ini",)
    folders = [recomp_root,
               os.path.join(os.environ.get("APPDATA", ""), "MHGURecomp")]
    for folder in folders:
        if not folder:
            continue
        for name in names:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                return path
    return ""


def _redirected_root(recomp_root=""):
    path = _save_location_ini(recomp_root)
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            section = False
            for line in handle:
                line = line.strip()
                if line.startswith("["):
                    section = line.lower() == "[application]"
                    continue
                if section and "=" in line:
                    key, value = line.split("=", 1)
                    if key.strip().lower() == "savelocation":
                        return value.strip().strip('"')
    except OSError:
        return ""
    return ""


def save_dir(recomp_root=""):
    redirected = _redirected_root(recomp_root)
    if redirected:
        nested = os.path.join(redirected, "save_0")
        if os.path.isdir(nested):
            return nested
        return redirected
    return default_save_dir()


def plugin_ini_names(folder, plugin_filename):
    # prefix match on the plugin file stem; fallback lists every ini
    stem = os.path.splitext(plugin_filename)[0].lower()
    try:
        names = sorted(name for name in os.listdir(folder)
                       if name.lower().endswith(".ini"))
    except OSError:
        return []
    matched = [name for name in names if name.lower().startswith(stem)]
    return matched, names


class IniEditorDialog(QDialog):
    # edit one plugin ini

    def __init__(self, ini_path, parent=None):
        super().__init__(parent)
        self.ini_path = ini_path
        self.setWindowTitle("Edit %s" % os.path.basename(ini_path))
        self.setModal(True)
        self.resize(660, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        path = QLabel(redact_path(ini_path))
        path.setWordWrap(True)
        path.setStyleSheet(
            "color: %s; background: transparent;" % Colors.TEXT_MUTED)
        layout.addWidget(path)

        self.editor = QPlainTextEdit(self)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
        self.editor.setFont(font)
        self.editor.setPlainText(self._read())
        layout.addWidget(self.editor, 1)

        row = QHBoxLayout()
        open_btn = QPushButton("Open save folder", self)
        open_btn.clicked.connect(
            lambda _checked=False: open_in_file_explorer(
                os.path.dirname(ini_path)))
        row.addWidget(open_btn)
        row.addStretch(1)
        save_btn = QPushButton("Save", self)
        save_btn.setObjectName("primaryBtn")
        save_btn.setFixedWidth(110)
        save_btn.clicked.connect(self._save)
        row.addWidget(save_btn)
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.setFixedWidth(110)
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(cancel_btn)
        layout.addLayout(row)

    def _read(self):
        try:
            with open(self.ini_path, "r", encoding="utf-8",
                      errors="replace") as handle:
                return handle.read()
        except OSError:
            return ""

    def _save(self):
        try:
            atomic_write_text(self.ini_path, self.editor.toPlainText())
        except OSError as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))
            return
        self.accept()
