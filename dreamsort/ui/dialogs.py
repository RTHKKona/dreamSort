# dialogs

import os
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QVBoxLayout,
    QWidget,
)

from ..constants import Colors, VERSION
from ..helpers.files import open_in_file_explorer
from ..redact import redact_path


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

    def __init__(self, candidates, parent=None,
                 title="Choose Ryujinx Mods Folder",
                 caption="Multiple Ryujinx mods folders found. Pick one:"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(620, 320)
        self.selected = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)

        label = QLabel(caption, self)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        layout.addWidget(label)

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
    def ask(cls, parent, candidates, title=None, caption=None):
        kwargs = {}
        if title:
            kwargs["title"] = title
        if caption:
            kwargs["caption"] = caption
        dialog = cls(candidates, parent, **kwargs)
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


# updates
ORDER = {"update_available": 0, "needs_choice": 1, "no_asset": 2,
         "installed_gone": 3, "unknown": 4, "up_to_date": 5, "unlinked": 6}
SOURCE_LABELS = {"gamebanana": "GB", "github": "GH"}


class UpdatesDialog(QDialog):
    # what both sources found, and the buttons that act on it

    def __init__(self, parent, updater, check=None, github=None):
        super().__init__(parent)
        self.updater = updater
        self.github = github
        self._check = check
        self._rows = []
        self._shown = []
        self._closed = False
        self.request = None          # (source, folder_id, file_id)
        self.setWindowTitle("Mod Updates")
        self.setModal(True)
        self.resize(680, 440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        self.head = QLabel("", self)
        self.head.setWordWrap(True)
        layout.addWidget(self.head)

        self.list = QListWidget(self)
        self.list.itemSelectionChanged.connect(self._on_selection)
        self.list.itemDoubleClicked.connect(
            lambda _row: self._on_update_clicked())
        layout.addWidget(self.list, 1)

        self.launch_box = QCheckBox("Check for updates 24h after the last check",
                                    self)
        self.launch_box.setChecked(bool(updater.on_launch()))
        self.launch_box.toggled.connect(self._on_launch_toggled)
        layout.addWidget(self.launch_box)

        buttons = QHBoxLayout()
        self.check_btn = QPushButton("Check now", self)
        self.check_btn.setFixedWidth(120)
        self.check_btn.clicked.connect(self._on_check)
        buttons.addWidget(self.check_btn)
        self.update_btn = QPushButton("Update", self)
        self.update_btn.setFixedWidth(140)
        self.update_btn.setEnabled(False)
        self.update_btn.clicked.connect(self._on_update_clicked)
        buttons.addWidget(self.update_btn)
        self.ignore_btn = QPushButton("Ignore this version", self)
        self.ignore_btn.setFixedWidth(170)
        self.ignore_btn.setEnabled(False)
        self.ignore_btn.clicked.connect(self._on_ignore)
        buttons.addWidget(self.ignore_btn)
        buttons.addStretch(1)
        close_btn = QPushButton("Close", self)
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        # a check finishing while the window is open should show up here
        for service in (updater, github):
            if service is not None:
                service.statuses_ready.connect(self.refresh)
        self.refresh()

    def refresh(self, *_args):
        # rebuild from both services, they own the state
        if self._closed:
            return
        self._rows = [self._gb_row(item)
                      for item in (self.updater.items or {}).values()]
        if self.github is not None:
            self._rows.extend(self._gh_row(item)
                              for item in (self.github.items or {}).values())
        self._shown = sorted(self._rows,
                             key=lambda row: (ORDER.get(row["status"], 9),
                                              (row["name"] or "").lower()))
        self.list.clear()
        for index, row in enumerate(self._shown):
            entry = QListWidgetItem(_row_line(row), self.list)
            entry.setData(Qt.UserRole, index)
        self.head.setText(self._head_text())
        self.check_btn.setEnabled(bool(self._check))
        self._on_selection()

    def _head_text(self):
        gb = (self.updater.summary if self.updater is not None else {}) or {}
        gh = (self.github.summary if self.github is not None else {}) or {}
        updates = gb.get("updates", 0) + gh.get("updates", 0)
        choices = gb.get("choices", 0)
        linked = gb.get("linked", 0) + gh.get("linked", 0)
        if updates or choices:
            head = ("%d update%s available, %d to choose from."
                    % (updates, "" if updates == 1 else "s", choices))
        elif linked:
            head = "Nothing to update: %d linked mod%s checked." % (
                linked, "" if linked == 1 else "s")
        else:
            head = ("No mods are linked to a GameBanana page or GitHub "
                    "release yet.")
        errors = [text for text in (getattr(self.updater, "error", ""),
                                    getattr(self.github, "error", "")) if text]
        return head + ("  (%s)" % "; ".join(errors) if errors else "")

    @staticmethod
    def _gb_row(item):
        status = item.get("status") or ""
        file = item.get("file") or {}
        options = item.get("options") or []
        actionable = bool(options) or (
            status in ("update_available", "installed_gone")
            and bool(file.get("id")))
        return {"source": "gamebanana", "folder_id": item.get("folder_id"),
                "status": status, "name": item.get("name") or
                item.get("folder_id") or "", "detail": _gb_detail(item),
                "file_id": "" if options else str(file.get("id") or ""),
                "options": options, "actionable": actionable}

    @staticmethod
    def _gh_row(item):
        status = item.get("status") or ""
        asset = item.get("asset") or {}
        return {"source": "github", "folder_id": item.get("folder_id"),
                "status": status, "name": item.get("name") or
                item.get("repo") or item.get("folder_id") or "",
                "detail": _gh_detail(item), "file_id": "", "options": [],
                "actionable": status == "update_available"
                              and bool(asset.get("url"))}

    def _selected(self):
        entry = self.list.currentItem()
        if entry is None:
            return None
        index = entry.data(Qt.UserRole)
        if not isinstance(index, int) or not 0 <= index < len(self._shown):
            return None
        return self._shown[index]

    def _on_selection(self):
        row = self._selected() or {}
        self.update_btn.setEnabled(bool(row.get("actionable")))
        self.update_btn.setText("Choose file\u2026" if row.get("options")
                                else "Update")
        self.ignore_btn.setEnabled(
            row.get("source") == "gamebanana"
            and row.get("status") == "update_available"
            and bool(row.get("file_id")))

    def _on_check(self):
        if self._check is not None:
            self._check()
            self.refresh()

    def _on_update_clicked(self):
        row = self._selected()
        if not row or not row.get("actionable"):
            return
        file_id = row.get("file_id") or ""
        options = row.get("options") or []
        if options:
            labels = [_option_label(option) for option in options]
            choice, accepted = QInputDialog.getItem(
                self, "Pick a file",
                "Which file should replace the installed one?",
                labels, 0, False)
            if not accepted or choice not in labels:
                return
            file_id = str(options[labels.index(choice)].get("id") or "")
        self.request = (row["source"], row["folder_id"], file_id)
        self.accept()

    def _on_ignore(self):
        row = self._selected()
        if row and self.updater.ignore(row.get("folder_id")):
            self.refresh()

    def _on_launch_toggled(self, on):
        self.updater.set_on_launch(bool(on))
        if self.github is not None:
            self.github.set_on_launch(bool(on))

    def done(self, result):
        self._closed = True
        super().done(result)


def _row_line(row):
    # one line per mod, source tagged
    return "%s  \u00b7  [%s] %s" % (row.get("name") or "",
                                   SOURCE_LABELS.get(row.get("source"), "?"),
                                   row.get("detail") or "")


def _gb_detail(item):
    status = item.get("status")
    file = item.get("file") or {}
    if status == "update_available":
        return "new file: %s" % (file.get("name") or "?")
    if status == "needs_choice":
        return "pick one of %d files" % len(item.get("options") or [])
    if status == "installed_gone":
        return "the installed file is gone; newest is %s" % (
            file.get("name") or "?")
    if status == "unknown" and item.get("knowledge") == "failed":
        return "last check failed"
    if status == "up_to_date":
        return "up to date"
    return "not linked"


def _gh_detail(item):
    status = item.get("status")
    if status == "update_available":
        return "release %s, was %s" % (item.get("tag") or "?",
                                       item.get("installed_tag") or "?")
    if status == "no_asset":
        return "release %s has no installable archive" % (
            item.get("tag") or "?")
    if status == "unknown":
        return item.get("error") or "last check failed"
    if status == "up_to_date":
        return "up to date"
    return "not linked"


def _option_label(option):
    # the id keeps two uploads of the same name apart
    return "%s  (id %s)" % (option.get("name") or "?",
                            option.get("id") or "?")


# unusual mod install
class ScriptRiskDialog(QDialog):
    # a mod that ships scripts gets one more question

    def __init__(self, findings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unusual Mod Installation")
        self.setModal(True)
        self.resize(660, 470)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        count = len(findings)
        self.head = QLabel("This mod ships %d script file%s."
                           % (count, "" if count == 1 else "s"), self)
        font = self.head.font()
        font.setPointSize(11)
        font.setBold(True)
        self.head.setFont(font)
        layout.addWidget(self.head)

        body = QLabel(
            "Normal mods are game files only. A .bat, .cmd or .ps1 runs code "
            "on your PC instead: it can delete files, change Windows settings "
            "or pull more code off the internet, and dreamSort cannot undo "
            "what it did. Only continue if you trust where this mod came from.",
            self)
        body.setWordWrap(True)
        body.setStyleSheet("color: %s;" % Colors.TEXT_MUTED)
        layout.addWidget(body)

        self.list = QListWidget(self)
        for entry in findings:
            row = QListWidgetItem(_risk_line(entry), self.list)
            row.setToolTip(redact_path(entry.get("where")
                                       or entry.get("name") or ""))
        layout.addWidget(self.list, 1)

        self.confirm_box = QCheckBox(
            "I understand this mod can run code on my PC", self)
        self.confirm_box.toggled.connect(self._on_toggled)
        layout.addWidget(self.confirm_box)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.install_btn = QPushButton("Install Anyway", self)
        self.install_btn.setObjectName("primaryBtn")
        self.install_btn.setMinimumWidth(160)
        self.install_btn.setEnabled(False)
        self.install_btn.clicked.connect(self.accept)
        buttons.addWidget(self.install_btn)
        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setMinimumWidth(120)
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)

        self.cancel_btn.setDefault(True)
        self.cancel_btn.setFocus()

    def _on_toggled(self, on):
        self.install_btn.setEnabled(bool(on))

    @classmethod
    def ask(cls, parent, findings):
        if not findings:
            return True
        dialog = cls(findings, parent)
        return dialog.exec() == QDialog.Accepted


def _risk_line(entry):
    # file, then what was found inside it
    risks = entry.get("risks") or []
    if risks:
        detail = "; ".join(risks)
    elif entry.get("inspected"):
        detail = "no risky command found, but it still runs on your PC"
    else:
        detail = "contents could not be read before install"
    return "%s  \u00b7  %s" % (entry.get("name") or "?", detail)


class TrimmedArcDialog(QDialog):
    # a mod cut down with arcBarber only loads where partial arcs merge

    def __init__(self, findings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Trimmed Arc Mod")
        self.setModal(True)
        self.resize(660, 440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        count = len(findings)
        self.head = QLabel("This mod ships %d trimmed archive%s."
                           % (count, "" if count == 1 else "s"), self)
        font = self.head.font()
        font.setPointSize(11)
        font.setBold(True)
        self.head.setFont(font)
        layout.addWidget(self.head)

        body = QLabel(
            "A trimmed .arc holds only the files the mod changed and not the "
            "rest of the original archive. As of 2026-11-19 only Morerokk's "
            "Recomp can load those (partial arc loading); Ryujinx and Eden "
            "replace the whole archive, so everything that was cut reads as "
            "missing and the game usually breaks. Regrow the archives with "
            "arcBarber first, or install this where the recomp runs it.",
            self)
        body.setWordWrap(True)
        body.setStyleSheet("color: %s;" % Colors.TEXT_MUTED)
        layout.addWidget(body)

        self.list = QListWidget(self)
        for entry in findings:
            row = QListWidgetItem(_trimmed_line(entry), self.list)
            row.setToolTip(redact_path(entry.get("where") or ""))
        layout.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.install_btn = QPushButton("Install Anyway", self)
        self.install_btn.setObjectName("primaryBtn")
        self.install_btn.setMinimumWidth(160)
        self.install_btn.clicked.connect(self.accept)
        buttons.addWidget(self.install_btn)
        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setMinimumWidth(120)
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)

        self.cancel_btn.setDefault(True)
        self.cancel_btn.setFocus()

    @classmethod
    def ask(cls, parent, findings):
        if not findings:
            return True
        dialog = cls(findings, parent)
        return dialog.exec() == QDialog.Accepted


class PackWarningDialog(QDialog):
    # a known repack, flagged by its packaging rather than its mods

    def __init__(self, findings, parent=None, install=False, action="Install"):
        super().__init__(parent)
        self.mute_box = None
        self.setWindowTitle("Known Modpack" if install else "Known Modpack")
        self.setModal(True)
        self.resize(680, 470)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        name = findings[0]["name"] if findings else "a known pack"
        self.head = QLabel("This looks like %s." % name, self)
        font = self.head.font()
        font.setPointSize(11)
        font.setBold(True)
        self.head.setFont(font)
        layout.addWidget(self.head)

        note = findings[0].get("note") if findings else ""
        body = QLabel(
            (note + "\n\n" if note else "") +
            "dreamSort matches the pack's own naming and files, not what is "
            "inside the mods: a component kept under the pack's name is "
            "flagged, a copy repacked under a different name is not. Nothing "
            "here is proof of who made each part, so check the original pages "
            "before relying on this bundle.", self)
        body.setWordWrap(True)
        body.setStyleSheet("color: %s;" % Colors.TEXT_MUTED)
        layout.addWidget(body)

        self.list = QListWidget(self)
        for finding in findings:
            row = QListWidgetItem(redact_path(finding.get("where") or "?"))
            row.setToolTip("\n".join(finding.get("signals") or []))
            self.list.addItem(row)
            for signal in finding.get("signals") or []:
                line = QListWidgetItem("    " + signal)
                line.setForeground(QColor(Colors.TEXT_MUTED))
                self.list.addItem(line)
        layout.addWidget(self.list, 1)

        if install:
            buttons = QHBoxLayout()
            buttons.addStretch(1)
            self.install_btn = QPushButton("%s Anyway" % (action or "Install"),
                                           self)
            self.install_btn.setObjectName("primaryBtn")
            self.install_btn.setMinimumWidth(160)
            self.install_btn.clicked.connect(self.accept)
            buttons.addWidget(self.install_btn)
            self.cancel_btn = QPushButton("Cancel", self)
            self.cancel_btn.setMinimumWidth(120)
            self.cancel_btn.clicked.connect(self.reject)
            buttons.addWidget(self.cancel_btn)
            layout.addLayout(buttons)
            self.cancel_btn.setDefault(True)
            self.cancel_btn.setFocus()
        else:
            self.mute_box = QCheckBox(
                "Don't warn again for this folder", self)
            layout.addWidget(self.mute_box)
            buttons = QHBoxLayout()
            buttons.addStretch(1)
            self.close_btn = QPushButton("Close", self)
            self.close_btn.setObjectName("primaryBtn")
            self.close_btn.setMinimumWidth(120)
            self.close_btn.clicked.connect(self.accept)
            buttons.addWidget(self.close_btn)
            layout.addLayout(buttons)

    @classmethod
    def ask(cls, parent, findings):
        if not findings:
            return True
        dialog = cls(findings, parent, install=True, action="Install")
        return dialog.exec() == QDialog.Accepted

    @classmethod
    def proceed(cls, parent, finding, action):
        # apply / launch gate; the folder can be muted from the banner
        if not finding:
            return True
        dialog = cls([finding], parent, install=True, action=action)
        return dialog.exec() == QDialog.Accepted

    @classmethod
    def details(cls, parent, findings):
        # returns True when the user opted out for this folder
        if not findings:
            return False
        dialog = cls(findings, parent, install=False)
        dialog.exec()
        return bool(dialog.mute_box and dialog.mute_box.isChecked())


def _trimmed_line(entry):
    # archive, then how much of it is left
    entries = entry.get("entries") or 0
    if entry.get("compared"):
        detail = "%d entr%s, a partial of the game's archive" % (
            entries, "y" if entries == 1 else "ies")
    else:
        detail = ("%d entr%s, no original archive to compare against"
                  % (entries, "y" if entries == 1 else "ies"))
    return "%s  \u00b7  %s" % (redact_path(entry.get("where") or "?"), detail)


class ExitCodeDialog(QDialog):
    # what dreamSort says when the recomp closes with a nonzero code

    def __init__(self, code, title, colour, meaning, log_excerpt,
                 on_open_folder, on_analyze, parent=None):
        super().__init__(parent)
        from ..launchers import exit_codes
        self.setWindowTitle(
            "MHGU Recomp closed - %s" % exit_codes.label(code))
        self.setModal(True)
        self.resize(620, 330)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        head = QLabel(title)
        font = head.font()
        font.setBold(True)
        font.setPointSize(12)
        head.setFont(font)
        head.setStyleSheet(
            "color: %s; background: transparent;" % colour)
        layout.addWidget(head)

        line = QLabel("Exit code %s" % exit_codes.label(code))
        line.setStyleSheet(
            "color: %s; background: transparent;" % Colors.TEXT_MUTED)
        layout.addWidget(line)

        body = QLabel(meaning)
        body.setWordWrap(True)
        layout.addWidget(body)
        layout.addSpacing(6)

        tail = QLabel("log.txt ends with:")
        tail.setStyleSheet(
            "color: %s; background: transparent;" % Colors.TEXT_MUTED)
        layout.addWidget(tail)
        excerpt = QPlainTextEdit(self)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
        excerpt.setFont(font)
        excerpt.setPlainText(log_excerpt)
        excerpt.setFixedHeight(72)
        excerpt.setReadOnly(True)
        layout.addWidget(excerpt)
        layout.addStretch(1)

        row = QHBoxLayout()
        folder_btn = QPushButton("Open log folder", self)
        folder_btn.clicked.connect(lambda _checked=False: on_open_folder())
        row.addWidget(folder_btn)
        analyze_btn = QPushButton("Analyze log.txt", self)
        analyze_btn.clicked.connect(lambda _checked=False: on_analyze())
        row.addWidget(analyze_btn)
        row.addStretch(1)
        close_btn = QPushButton("Close", self)
        close_btn.setObjectName("primaryBtn")
        close_btn.setFixedWidth(110)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        layout.addLayout(row)


class RecompLogDialog(QDialog):
    # recomp log findings with suggested fixes

    def __init__(self, report, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recomp log.txt")
        self.setModal(True)
        self.resize(720, 560)
        self.report = report

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        self.summary = QLabel(report.get("summary", ""), self)
        self.summary.setWordWrap(True)
        font = self.summary.font()
        font.setBold(True)
        self.summary.setFont(font)
        layout.addWidget(self.summary)

        if report.get("path"):
            where = QLabel(redact_path(report["path"]), self)
            where.setWordWrap(True)
            where.setStyleSheet("color: %s;" % Colors.TEXT_MUTED)
            layout.addWidget(where)

        self.list = QListWidget(self)
        for finding in report.get("findings", []):
            head = QListWidgetItem("%s   (%s)" % (finding["title"],
                                                  finding["severity"]))
            head_font = head.font()
            head_font.setBold(True)
            head.setFont(head_font)
            self.list.addItem(head)
            if finding.get("line"):
                raw = QListWidgetItem("    " + finding["line"])
                raw.setForeground(QColor(Colors.TEXT_MUTED))
                self.list.addItem(raw)
            self.list.addItem(QListWidgetItem(
                "    -> " + finding["suggestion"]))
        layout.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        self.open_btn = QPushButton("Open log folder", self)
        self.open_btn.clicked.connect(self._open_folder)
        buttons.addWidget(self.open_btn)
        buttons.addStretch(1)
        self.close_btn = QPushButton("Close", self)
        self.close_btn.setObjectName("primaryBtn")
        self.close_btn.setMinimumWidth(120)
        self.close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

    def _open_folder(self):
        folder = os.path.dirname(self.report.get("path", "") or "")
        if folder:
            open_in_file_explorer(folder)

    @classmethod
    def show_report(cls, parent, report):
        cls(report, parent).exec()

