# dialogs

import os
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QVBoxLayout,
    QWidget,
)

from ..constants import Colors, VERSION


# helpers
def info(parent, title, text):
    QMessageBox.information(parent, title, text)


def warn(parent, title, text):
    QMessageBox.warning(parent, title, text)


def error(parent, title, text):
    QMessageBox.critical(parent, title, text)


def confirm(parent, title, text):
    answer = QMessageBox.question(
        parent, title, text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No)
    return answer == QMessageBox.StandardButton.Yes


def ask_text(parent, title, label, default=""):
    text, ok = QInputDialog.getText(parent, title, label, text=default)
    return text if ok else None


def pick_directory(parent, title, start=""):
    return QFileDialog.getExistingDirectory(parent, title, start)


def pick_open_files(parent, title, filetypes):
    files, _selected = QFileDialog.getOpenFileNames(parent, title, "", filetypes)
    return list(files)


def pick_open_file(parent, title, filetypes):
    path, _selected = QFileDialog.getOpenFileName(parent, title, "", filetypes)
    return path or ""


def pick_save_file(parent, title, default_name, filetypes):
    path, _selected = QFileDialog.getSaveFileName(parent, title, default_name,
                                                  filetypes)
    return path or ""


def show_about(parent):
    info(parent, "About dreamSort",
         "dreamSort Mod Manager %s\n\n"
         "A mod manager for MHGU on Ryujinx, Eden and Morerokk Recomp.\n\n"
         "Supports Windows, Linux (Steam Deck) and macOS." % VERSION)


def show_config_notices(parent, notes):
    if notes:
        warn(parent, "Settings Recovered", "\n\n".join(notes))


# mode selector
class ModeSelectorDialog(QDialog):
    # startup / mode dialog

    def __init__(self, current_mode="ryujinx", remember=False, parent=None):
        super().__init__(parent)
        self.mode = None
        self.remember = bool(remember)

        self.setWindowTitle("dreamSort \u2014 Select Mode")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(10)

        title = QLabel("Which setup are you managing?", self)
        font = title.font()
        font.setPointSize(13)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        self.ryujinx_radio = QRadioButton("Ryujinx (Switch emulator)", self)
        self.eden_radio = QRadioButton(
            "Eden (Switch emulator — installed or portable)", self)
        self.recomp_radio = QRadioButton(
            "Morerokk's MHGU Recomp (native PC port)", self)
        current = {"recomp": self.recomp_radio,
                   "eden": self.eden_radio}.get(current_mode, self.ryujinx_radio)
        current.setChecked(True)
        layout.addWidget(self.ryujinx_radio)
        layout.addWidget(self.eden_radio)
        layout.addWidget(self.recomp_radio)

        self.remember_box = QCheckBox("Remember this choice on next launch",
                                      self)
        self.remember_box.setChecked(bool(remember))
        layout.addSpacing(6)
        layout.addWidget(self.remember_box)
        layout.addSpacing(8)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.continue_btn = QPushButton("Continue", self)
        self.continue_btn.setMinimumWidth(120)
        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setMinimumWidth(120)
        self.continue_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.continue_btn)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)

        self.continue_btn.setDefault(True)

    def accept(self):
        if self.recomp_radio.isChecked():
            self.mode = "recomp"
        elif self.eden_radio.isChecked():
            self.mode = "eden"
        else:
            self.mode = "ryujinx"
        self.remember = self.remember_box.isChecked()
        super().accept()

    @classmethod
    def ask(cls, parent, current_mode="ryujinx", remember=False):
        dialog = cls(current_mode, remember, parent)
        if parent is not None:
            dialog.adjustSize()
        accepted = dialog.exec() == QDialog.Accepted
        return (dialog.mode if accepted else None), dialog.remember


StartupModeDialog = ModeSelectorDialog


# folder picker
class FolderPickerDialog(QDialog):
    # pick a mods folder

    def __init__(self, candidates, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose Ryujinx Mods Folder")
        self.setModal(True)
        self.resize(620, 320)
        self.selected = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)

        caption = QLabel("Multiple Ryujinx mods folders found. Pick one:", self)
        font = caption.font()
        font.setBold(True)
        caption.setFont(font)
        layout.addWidget(caption)

        self.list = QListWidget(self)
        for path in candidates:
            QListWidgetItem(path, self.list)
        if candidates:
            self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        use_btn = QPushButton("Use This Folder", self)
        use_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(use_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def accept(self):
        item = self.list.currentItem()
        if item is not None:
            self.selected = item.text()
        super().accept()

    @classmethod
    def ask(cls, parent, candidates):
        dialog = cls(candidates, parent)
        if dialog.exec() == QDialog.Accepted:
            return dialog.selected
        return None


# import mods
class ImportModsDialog(QDialog):
    # archives or a folder

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Mods")
        self.setModal(True)
        self.result_kind = None
        self.result_items = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        title = QLabel("Import mods from:", self)
        font = title.font()
        font.setPointSize(10)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        row = QHBoxLayout()
        archives_btn = QPushButton("Archive (zip / 7z)", self)
        archives_btn.setFixedWidth(160)
        archives_btn.clicked.connect(self._pick_archives)
        folder_btn = QPushButton("Folder", self)
        folder_btn.setFixedWidth(160)
        folder_btn.clicked.connect(self._pick_folder)
        row.addWidget(archives_btn)
        row.addWidget(folder_btn)
        row.addStretch(1)
        layout.addLayout(row)

        tip = QLabel("Tip: you can also drag & drop archives or folders "
                     "onto the mod list.", self)
        tip.setStyleSheet("color: %s;" % Colors.TEXT_MUTED)
        layout.addWidget(tip)

    def _pick_archives(self):
        files = pick_open_files(
            self, "Select mod archives (zip / 7z)",
            [("Mod archives", "*.zip *.7z"), ("All files", "*.*")])
        if files:
            self.result_kind = "archives"
            self.result_items = files
            self.accept()

    def _pick_folder(self):
        folder = pick_directory(self, "Select a mod folder")
        if folder:
            self.result_kind = "folder"
            self.result_items = [folder]
            self.accept()

    @classmethod
    def ask(cls, parent):
        dialog = cls(parent)
        if dialog.exec() == QDialog.Accepted:
            return dialog.result_kind, dialog.result_items
        return None, []


# import cheat
class ImportCheatDialog(QDialog):
    # paste a cheat and name it

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Cheat")
        self.setModal(True)
        self.resize(640, 480)
        self.result_name = ""
        self.result_body = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Cheat name:", self), 0)
        self.name_edit = QLineEdit(self)
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        layout.addWidget(QLabel(
            "Paste cheat code below (a [Name] header is optional):", self))

        self.editor = QPlainTextEdit(self)
        self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.editor.textChanged.connect(self._autofill_name)
        layout.addWidget(self.editor, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        import_btn = QPushButton("Import", self)
        import_btn.clicked.connect(self._on_import)
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(import_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def _autofill_name(self):
        if self.name_edit.text().strip():
            return
        match = re.match(r"^\s*\[([^\]]+)\]", self.editor.toPlainText())
        if match:
            self.name_edit.setText(match.group(1).strip())

    def _on_import(self):
        body = self.editor.toPlainText().strip()
        if not body:
            warn(self, "Empty", "Paste some cheat code first.")
            return
        self.result_name = self.name_edit.text().strip()
        self.result_body = body
        self.accept()

    @classmethod
    def ask(cls, parent):
        dialog = cls(parent)
        if dialog.exec() == QDialog.Accepted:
            return dialog.result_name, dialog.result_body
        return None, None


# cheat code box
class CheatCodeDialog(QDialog):
    # view or edit one block

    def __init__(self, title, content, editable=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(700, 500 if editable else 400)
        self.edited_content = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.editor = QPlainTextEdit(self)
        self.editor.setPlainText(content)
        self.editor.setReadOnly(not editable)
        layout.addWidget(self.editor, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        if editable:
            save_btn = QPushButton("Save", self)
            save_btn.clicked.connect(self._on_save)
            buttons.addWidget(save_btn)
        close_btn = QPushButton("Close" if not editable else "Cancel", self)
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _on_save(self):
        self.edited_content = self.editor.toPlainText()
        self.accept()

    @classmethod
    def view(cls, parent, title, content):
        dialog = cls(title, content, editable=False, parent=parent)
        dialog.exec()

    @classmethod
    def edit(cls, parent, title, content):
        dialog = cls(title, content, editable=True, parent=parent)
        if dialog.exec() == QDialog.Accepted:
            return dialog.edited_content
        return None
