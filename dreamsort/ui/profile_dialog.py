# mod profile dialog

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from . import dialogs


def _entry_label(entry):
    return (entry.get("filename") or entry.get("page_url")
            or entry.get("gb_mod_id") or "untitled")


def _installed_label(item):
    record = item.get("record") or {}
    return record.get("filename") or item.get("mod_id") or "untitled"


class ModProfilesDialog(QDialog):
    # snapshots of the linked mod set, matched by file identity

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("dreamSort \u2014 Mod Sets")
        self.resize(720, 460)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        left = QVBoxLayout()
        self.list = QListWidget(self)
        self.list.currentItemChanged.connect(self._on_select)
        left.addWidget(self.list, 1)

        buttons = QVBoxLayout()
        for text, slot in (("New from current", self._new),
                           ("Copy", self._copy),
                           ("Rename", self._rename),
                           ("Delete", self._delete),
                           ("Apply", self._apply),
                           ("Export...", self._export),
                           ("Import...", self._import)):
            button = QPushButton(text, self)
            button.setFixedWidth(130)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        close_btn = QPushButton("Close", self)
        close_btn.setFixedWidth(130)
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)

        right = QVBoxLayout()
        self.summary = QLabel("", self)
        self.report = QPlainTextEdit(self)
        self.report.setReadOnly(True)
        right.addWidget(self.summary)
        right.addWidget(self.report, 1)

        layout.addLayout(left, 1)
        layout.addLayout(buttons, 0)
        layout.addLayout(right, 2)
        self._refresh_list()

    # list handling

    def _refresh_list(self):
        current = self.list.currentItem()
        current_name = current.text() if current else ""
        self.list.clear()
        for name in self.controller.mod_profile_names():
            QListWidgetItem(name, self.list)
        if current_name:
            index = self.list.findText(current_name)
            if index >= 0:
                self.list.setCurrentRow(index)
        if self.list.count() and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)

    def _current_name(self):
        item = self.list.currentItem()
        return item.text() if item else None

    def _on_select(self, current, _previous):
        if current is not None:
            self._show_report(current.text())

    # actions

    def _new(self):
        name = dialogs.ask_text(self, "New Mod Set", "Set name:")
        if not name or not name.strip():
            return
        self.controller.save_mod_profile(name.strip())
        self._refresh_list()
        self._select(name.strip())

    def _copy(self):
        source = self._current_name()
        if not source:
            return
        name = dialogs.ask_text(self, "Copy Mod Set", "New set name:", source)
        if not name or not name.strip():
            return
        self.controller.copy_mod_profile(source, name.strip())
        self._refresh_list()
        self._select(name.strip())

    def _rename(self):
        old = self._current_name()
        if not old:
            return
        name = dialogs.ask_text(self, "Rename Mod Set", "New name:", old)
        if not name or not name.strip():
            return
        self.controller.rename_mod_profile(old, name.strip())
        self._refresh_list()
        self._select(name.strip())

    def _delete(self):
        name = self._current_name()
        if not name:
            return
        self.controller.delete_mod_profile(name)
        self._refresh_list()

    def _apply(self):
        name = self._current_name()
        if not name:
            return
        message = self.controller.apply_mod_profile(name)
        dialogs.info(self, "Mod Set", message)
        self._show_report(name)

    def _export(self):
        self.controller.export_mod_profiles()

    def _import(self):
        self.controller.import_mod_profiles()
        self._refresh_list()

    def _select(self, name):
        index = self.list.findText(name)
        if index >= 0:
            self.list.setCurrentRow(index)

    # report

    def _show_report(self, name):
        report = self.controller.compare_mod_profile(name)
        if report is None:
            self.summary.setText("")
            self.report.setPlainText("")
            return
        matched = report["matched"]
        missing = report["missing"]
        mismatched = report["mismatched"]
        extra = report["extra"]
        self.summary.setText(
            "Matched %d  \u00b7  Missing %d  \u00b7  Mismatched %d  \u00b7  Extra %d"
            % (len(matched), len(missing), len(mismatched), len(extra)))
        lines = []
        lines.append("Matched:")
        lines += ["  \u2713 " + _installed_label(x["installed"]) for x in matched]
        lines.append("")
        lines.append("Missing (not installed):")
        lines += ["  \u2013 " + _entry_label(x) for x in missing]
        lines.append("")
        lines.append("Mismatched (same mod, different file):")
        lines += ["  ! " + _entry_label(x["entry"]) for x in mismatched]
        lines.append("")
        lines.append("Extra (installed but not in this set):")
        lines += ["  + " + _installed_label(x) for x in extra]
        self.report.setPlainText("\n".join(lines))
