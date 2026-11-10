# main window

import json
import os
import re
import shutil
import tempfile
import traceback
import zipfile

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCursor, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from ..analyzers import eden_config
from ..analyzers import EdenAnalyzer, RecompAnalyzer, RyujinxAnalyzer
from ..constants import Colors, VERSION
from ..helpers.files import open_in_file_explorer
from ..launchers import launch_recomp, launch_ryujinx
from ..redact import expand_path, redact_path, unredact_path
from ..storage import atomic_write_text, config_path, read_config, write_config
from ..workers import InstallWorker, PY7ZR_SUPPORT, QueueBridge, run_in_thread, run_worker
from . import dialogs
from .details_panel import DetailsPanel, wrap_path_text
from .dnd import MOD_ROW_MIME
from .mod_list import ModListWidget, ModScrollArea
from .mod_row import CheckMark, FileRow, ModRow
from .sections import CollapsibleSection
from .tree_view import ConflictTree

FILE_TAG_PRIORITY = {"conflict": 0, "enable_conflict": 1, "override": 2, "safe": 3}


class DreamSortView(QWidget):
    # one mode's ui

    FOUNDATION_LIBS = {"katlib": "KatLib"}
    CONTENT_DIRS = {"romfs", "exefs", "cheats", "nativnx", "arc", "scenes"}

    def __init__(self, mode="ryujinx", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.emulator = (EdenAnalyzer() if mode == "eden" else RyujinxAnalyzer())
        self.recomp = RecompAnalyzer()

        # state
        self.pending_cheat_selections = {}
        self.cheat_files_model = []   # cheat files
        self._dir_stats_cache = {}    # sizes
        self.current_details_mod = None
        self._pending_details_cheat = None
        self.mod_rows = {}            # rows
        self._rows_by_id = {}         # rows
        self.mod_enabled = {}         # enabled
        self.cheat_rows = {}
        self.eden_cheat_rows = {}
        self.eden_cheat_states = {}
        self._eden_switch_noted = set()
        self.patch_rows = {}
        self.plugin_rows = {}
        self.file_rows = {}
        self.selected_files = set()
        self.selected_mods = set()
        self.recomp_mods_section = None
        self.view_mode = "list"
        self.current_state = "idle"
        self.display_path = ""
        self._last_real_path = ""
        self._scanning = False
        self._closing = False        # set after shutdown
        self._apply_reported = False
        self._install_staging = []
        self._install_dest_names = {}
        self._install_target_dir = ""
        self._legend_items = []

        # config
        self.ryujinx_exe_path = ""
        self.game_file_path = ""
        self.recomp_exe_path = ""
        self.profiles = {}
        self.remember_mode = False
        self._splitter_sizes = None
        self._splitter_user_set = False
        self._splitter_centered = False
        self.load_config()

        # widgets
        self._build_ui()
        self._apply_mode_initial()
        self._refresh_profile_menu()
        self._set_state("idle")

        # first scan once the window is up
        QTimer.singleShot(200, self.run_scan)

    # config
    def load_config(self):
        config = read_config()
        self.ryujinx_exe_path = config.get("ryujinx_exe_path", "")
        self.game_file_path = config.get("game_file_path", "")
        self.recomp_exe_path = config.get("recomp_exe_path", "")
        self.remember_mode = bool(config.get("remember_mode", False))
        self.profiles = config.get("profiles", {}) or {}
        self._saved_paths = {
            "ryujinx": expand_path(config.get("mods_path", "") or ""),
            "eden": expand_path(config.get("eden_path", "") or ""),
            "recomp": expand_path(config.get("recomp_root", "")
                                  or config.get("recomp_path", "") or ""),
        }
        # only restore a real drag
        sizes = config.get("splitter_sizes")
        if (isinstance(sizes, list) and len(sizes) == 2
                and config.get("splitter_user_set")):
            self._splitter_sizes = sizes
            self._splitter_user_set = True

    def save_config(self):
        config = {
            "ryujinx_exe_path": self.ryujinx_exe_path,
            "game_file_path": self.game_file_path,
            "recomp_exe_path": self.recomp_exe_path,
            "mode": self.mode,
            "remember_mode": self.remember_mode,
        }
        if self.emulator.mods_path and self.mode == "ryujinx":
            config["mods_path"] = redact_path(self.emulator.mods_path)
        elif self.emulator.mods_path and self.mode == "eden":
            config["eden_path"] = redact_path(self.emulator.mods_path)
        elif self.mode == "recomp" and self.display_path:
            config["recomp_root"] = self.display_path
        config["profiles"] = self.profiles
        if self.mode == "recomp":
            config["recomp_path"] = self.display_path
        try:
            if self.splitter is not None and self._splitter_user_set:
                config["splitter_sizes"] = list(self.splitter.sizes())
                config["splitter_user_set"] = True
        except Exception:
            pass
        write_config(config)

    # paths
    # path helpers
    def _update_path_display(self, path):
        if path:
            self._last_real_path = path
            self.display_path = redact_path(path)
            self.path_edit.setText(self.display_path)
        else:
            self._last_real_path = ""
            self.display_path = ""
            self.path_edit.setText("")
        self._refresh_structure_sign()

    def _get_current_path(self):
        entry = self.path_edit.text().strip()
        if entry != self.display_path:
            return os.path.expanduser(unredact_path(entry))
        return self._last_real_path

    def _current_display_path(self):
        return self.display_path

    def _scanned_path_matches_entry(self):
        entry = self._get_current_path()
        if not entry:
            return False
        if self.mode in ("ryujinx", "eden"):
            scanned = self.emulator.mods_path
        else:
            scanned = self.recomp.root_path
        if not scanned:
            return False
        try:
            return os.path.normcase(os.path.abspath(entry)) == os.path.normcase(
                os.path.abspath(scanned))
        except Exception:
            return False

    def _refresh_structure_sign(self):
        path = self._get_current_path()
        if not path:
            self.structure_warning.hide()
            return
        if self.mode == "recomp":
            ok, message, _suggested = self.recomp.structure_status(path)
        else:
            ok, message, _suggested = self.emulator.structure_status(path)
        if ok:
            self.structure_warning.hide()
        else:
            self.structure_warning.setText("\u26a0  " + message)
            self.structure_warning.show()

    def _on_path_edited(self):
        self._structure_timer.start(250)

    # ui
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.stack = QStackedWidget(self)
        root.addWidget(self.stack)

        self.main_page = QWidget(self.stack)
        page = QVBoxLayout(self.main_page)
        page.setContentsMargins(10, 8, 10, 8)
        page.setSpacing(6)

        page.addWidget(self._build_top_bar(), 0)

        self.splitter = QSplitter(Qt.Horizontal, self.main_page)
        self.splitter.setHandleWidth(6)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self._build_list_panel())
        self.splitter.addWidget(self._build_details_column())
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        page.addWidget(self.splitter, 1)

        page.addWidget(self._build_bottom_bar(), 0)

        self.overlay_page = self._build_overlay()
        self.stack.addWidget(self.main_page)
        self.stack.addWidget(self.overlay_page)
        self.stack.setCurrentWidget(self.main_page)

        self._structure_timer = QTimer(self)
        self._structure_timer.setSingleShot(True)
        self._structure_timer.timeout.connect(self._refresh_structure_sign)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_config)

    def _build_top_bar(self):
        bar = QWidget(self.main_page)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        path_row = QHBoxLayout()
        path_row.setSpacing(4)
        self.path_edit = QLineEdit(bar)
        self.path_edit.setPlaceholderText("Path to Mods folder")
        self.path_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.path_edit.textChanged.connect(self._on_path_edited)
        path_row.addWidget(self.path_edit, 1)

        self.browse_btn = QPushButton("\U0001f4c1", bar)
        self.browse_btn.setFixedWidth(44)
        self.browse_btn.setToolTip("Select mods folder")
        self.browse_btn.clicked.connect(self.select_folder)
        path_row.addWidget(self.browse_btn)

        self.scan_btn = QPushButton("Scan", bar)
        self.scan_btn.setFixedWidth(100)
        self.scan_btn.clicked.connect(self.run_scan)
        path_row.addWidget(self.scan_btn)

        self.open_btn = QPushButton("Open", bar)
        self.open_btn.setFixedWidth(100)
        self.open_btn.clicked.connect(self.open_mod_directory)
        path_row.addWidget(self.open_btn)

        self.find_btn = QPushButton("Auto-Find", bar)
        self.find_btn.setFixedWidth(92)
        self.find_btn.clicked.connect(self._auto_find_ryujinx_mods)
        path_row.addWidget(self.find_btn)

        self.launch_btn = QPushButton("Launch", bar)
        self.launch_btn.setObjectName("primaryBtn")
        self.launch_btn.setFixedWidth(130)
        self.launch_btn.clicked.connect(self.launch_game)
        path_row.addWidget(self.launch_btn)
        layout.addLayout(path_row)

        actions = QHBoxLayout()
        actions.setSpacing(4)

        self.cheat_buttons_widget = QWidget(bar)
        cheat_row = QHBoxLayout(self.cheat_buttons_widget)
        cheat_row.setContentsMargins(0, 0, 0, 0)
        cheat_row.setSpacing(4)
        self.preview_btn = QPushButton("Preview enabled.txt",
                                       self.cheat_buttons_widget)
        self.preview_btn.setFixedWidth(190)
        self.preview_btn.clicked.connect(self.preview_enabled_cheats_popup)
        cheat_row.addWidget(self.preview_btn)

        self.import_cheat_btn = QPushButton("\uff0b Import Cheat",
                                            self.cheat_buttons_widget)
        self.import_cheat_btn.setFixedWidth(148)
        self.import_cheat_btn.clicked.connect(self.import_cheat_popup)
        cheat_row.addWidget(self.import_cheat_btn)

        self.disable_cheats_btn = QPushButton("Disable Cheats",
                                              self.cheat_buttons_widget)
        self.disable_cheats_btn.setFixedWidth(145)
        self.disable_cheats_btn.clicked.connect(self.clear_all_cheats)
        cheat_row.addWidget(self.disable_cheats_btn)
        actions.addWidget(self.cheat_buttons_widget)

        # eden cheat switch
        self.eden_settings_btn = QPushButton("Eden Settings", bar)
        self.eden_settings_btn.setFixedWidth(140)
        self.eden_settings_btn.setToolTip(
            "Check Eden's own 'enable cheats by default' switch and turn it on")
        self.eden_settings_btn.clicked.connect(self.eden_settings_popup)
        self.eden_settings_btn.hide()
        actions.addWidget(self.eden_settings_btn)

        actions.addStretch(1)

        self.import_mods_btn = QPushButton("\uff0b Import Mods", bar)
        self.import_mods_btn.setFixedWidth(140)
        self.import_mods_btn.clicked.connect(self.import_mods_popup)
        actions.addWidget(self.import_mods_btn)

        self.disable_mods_btn = QPushButton("Disable Mods", bar)
        self.disable_mods_btn.setFixedWidth(140)
        self.disable_mods_btn.clicked.connect(self.clear_all_mods)
        actions.addWidget(self.disable_mods_btn)

        self.apply_btn = QPushButton("Apply New Order", bar)
        self.apply_btn.setObjectName("primaryBtn")
        self.apply_btn.setFixedWidth(160)
        self.apply_btn.clicked.connect(self.apply_changes)
        actions.addWidget(self.apply_btn)
        layout.addLayout(actions)

        self.structure_warning = QLabel("", bar)
        self.structure_warning.setObjectName("warningBanner")
        self.structure_warning.setWordWrap(True)
        self.structure_warning.hide()
        layout.addWidget(self.structure_warning)
        return bar

    def _legend_item(self, color, text, parent):
        holder = QWidget(parent)
        box = QHBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        swatch = QLabel(holder)
        swatch.setFixedSize(10, 10)
        swatch.setStyleSheet("background:%s; border:1px solid %s; border-radius:2px;"
                             % (color, color))
        box.addWidget(swatch)
        label = QLabel(text, holder)
        label.setStyleSheet("color: %s; background: transparent;" % Colors.TEXT_MUTED)
        box.addWidget(label)
        return holder

    def _build_list_panel(self):
        panel = QFrame(self.main_page)
        panel.setObjectName("listPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = QLabel("MOD LOAD ORDER  \u00b7  DRAG FILES HERE TO INSTALL", panel)
        header.setStyleSheet("color: %s; background: transparent;" % Colors.TEXT_MUTED)
        layout.addWidget(header, 0)

        view_row = QHBoxLayout()
        view_row.setSpacing(4)
        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.list_button = QPushButton("List View", panel)
        self.list_button.setObjectName("viewBtn")
        self.list_button.setCheckable(True)
        self.list_button.setChecked(True)
        self.list_button.setFixedWidth(90)
        self.tree_button = QPushButton("Tree View", panel)
        self.tree_button.setObjectName("viewBtn")
        self.tree_button.setCheckable(True)
        self.tree_button.setFixedWidth(90)
        self.view_group.addButton(self.list_button)
        self.view_group.addButton(self.tree_button)
        self.list_button.clicked.connect(lambda: self.switch_view("list"))
        self.tree_button.clicked.connect(lambda: self.switch_view("tree"))
        view_row.addWidget(self.list_button)
        view_row.addWidget(self.tree_button)
        view_row.addStretch(1)
        layout.addLayout(view_row, 0)

        legend = QHBoxLayout()
        legend.setSpacing(10)
        for color, text in ((Colors.RESOLVED_CONFLICT, "Overwrites"),
                            (Colors.CONFLICT, "Overwritten"),
                            (Colors.NO_CONFLICT_FILL, "Loaded"),
                            (Colors.DRAG_HIGHLIGHT, "Selected"),
                            (Colors.DISABLED, "Disabled")):
            item = self._legend_item(color, text, panel)
            self._legend_items.append(item)
            legend.addWidget(item)
        legend.addStretch(1)
        layout.addLayout(legend, 0)

        self.view_stack = QStackedWidget(panel)
        self.list_widget = ModListWidget(accept_drops=True)
        self.list_widget.dropPaths.connect(self._on_paths_dropped)
        self.list_widget.reorderRequested.connect(
            lambda mod_id, index: self._on_reorder_requested(mod_id, index,
                                                             self.list_widget))
        self.list_scroll = ModScrollArea(self.list_widget)
        self.tree = ConflictTree(panel)
        self.view_stack.addWidget(self.list_scroll)
        self.view_stack.addWidget(self.tree)
        layout.addWidget(self.view_stack, 1)

        self.selection_bar = QFrame(panel)
        self.selection_bar.setObjectName("selectionBar")
        bar_layout = QHBoxLayout(self.selection_bar)
        bar_layout.setContentsMargins(10, 4, 8, 4)
        bar_layout.setSpacing(8)
        self.selection_label = QLabel("", self.selection_bar)
        self.selection_label.setObjectName("selectionLabel")
        bar_layout.addWidget(self.selection_label, 1)
        self.selection_clear_btn = QPushButton("Clear selection", self.selection_bar)
        self.selection_clear_btn.setFixedWidth(130)
        self.selection_clear_btn.clicked.connect(self.clear_selection)
        bar_layout.addWidget(self.selection_clear_btn)
        self.selection_bar.hide()
        layout.addWidget(self.selection_bar, 0)
        return panel

    def _build_details_column(self):
        frame = QFrame(self.main_page)
        frame.setObjectName("detailsPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = QLabel("DETAILS / ACTIONS", frame)
        header.setStyleSheet("color: %s; background: transparent;" % Colors.TEXT_MUTED)
        layout.addWidget(header, 0)

        self.details = DetailsPanel(frame)
        self.details.placeholder()
        layout.addWidget(self.details, 1)
        return frame

    def _build_bottom_bar(self):
        bar = QWidget(self.main_page)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(2, 2, 2, 0)
        layout.setSpacing(6)

        self.status_label = QLabel("", bar)
        self.status_label.setObjectName("statusLabel")
        self.status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.status_label, 1)

        profile_label = QLabel("Profile:", bar)
        profile_label.setStyleSheet("color: %s; background: transparent;"
                                    % Colors.TEXT_MUTED)
        layout.addWidget(profile_label, 0)

        self.profile_combo = QComboBox(bar)
        self.profile_combo.setFixedWidth(180)
        self.profile_combo.activated.connect(self._on_profile_selected)
        layout.addWidget(self.profile_combo, 0)

        self.profile_btn = QPushButton("Profile \u25be", bar)
        self.profile_btn.setFixedWidth(96)
        self.profile_btn.clicked.connect(self._show_profile_menu)
        layout.addWidget(self.profile_btn, 0)
        return bar

    def _build_overlay(self):
        overlay = QFrame(self.main_page)
        overlay.setObjectName("progressOverlay")
        layout = QVBoxLayout(overlay)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(10)
        layout.addStretch(1)

        card = QFrame(overlay)
        card.setObjectName("progressCard")
        card.setMinimumWidth(460)
        card.setMaximumWidth(560)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(12)

        self.progress_header = QLabel("Applying Load Order...", card)
        header_font = self.progress_header.font()
        header_font.setPointSize(15)
        header_font.setBold(True)
        self.progress_header.setFont(header_font)
        self.progress_header.setWordWrap(True)
        card_layout.addWidget(self.progress_header)

        self.progress_bar = QProgressBar(card)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        card_layout.addWidget(self.progress_bar)

        self.progress_detail = QLabel("Initializing...", card)
        self.progress_detail.setWordWrap(True)
        self.progress_detail.setStyleSheet("color: %s; background: transparent;"
                                          % Colors.TEXT_MUTED)
        card_layout.addWidget(self.progress_detail)

        layout.addWidget(card, 0, Qt.AlignHCenter)
        layout.addStretch(1)
        return overlay

    # mode
    def _default_path_for_mode(self):
        saved = (self._saved_paths or {}).get(self.mode, "")
        if saved:
            return expand_path(saved)
        if self.mode == "recomp":
            if self.recomp_exe_path:
                return os.path.dirname(self.recomp_exe_path)
            return ""
        if self.mode == "eden":
            # only the installed profile
            appdata = os.environ.get("APPDATA", "")
            title = getattr(self.emulator, "TITLE_ID", "")
            if appdata and title:
                candidate = os.path.join(appdata, "eden", "load", title)
                if os.path.isdir(candidate):
                    return candidate
            return ""
        if self.ryujinx_exe_path:
            root = os.path.dirname(self.ryujinx_exe_path)
            candidate = os.path.join(root, "mods", "contents")
            if os.path.isdir(candidate):
                for child in sorted(os.listdir(candidate)):
                    sub = os.path.join(candidate, child)
                    if os.path.isdir(sub):
                        return sub
            return root
        return ""

    def _apply_mode_initial(self):
        self.eden_settings_btn.setVisible(self.mode == "eden")
        if self.mode == "recomp":
            self.path_edit.setPlaceholderText("Path to MHGU Recomp folder")
            self.cheat_buttons_widget.hide()
            self.find_btn.hide()
            self.details.placeholder(
                "Select a mod to see its details. Cheats live in the "
                "recomp's own cheats/ folder.")
        elif self.mode == "eden":
            self.path_edit.setPlaceholderText(
                "Path to Eden load %s folder" % getattr(self.emulator,
                                                       "TITLE_ID", ""))
            self.cheat_buttons_widget.show()
            self.find_btn.show()
            self.details.placeholder(
                "Select a mod or a cheat to view details. Disabled entries "
                "sit in disabled_mods / disabled_cheats.")
        else:
            self.path_edit.setPlaceholderText("Path to Ryujinx Mods folder")
            self.cheat_buttons_widget.show()
            self.find_btn.show()
            self.details.placeholder(
                "Select a mod to view details and manage cheats.")
        default_path = self._default_path_for_mode()
        if default_path:
            self._update_path_display(default_path)
        self._update_window_title()

    def _mode_label(self):
        return {"recomp": "MHGU Recomp", "eden": "Eden"}.get(
            self.mode, "Ryujinx")

    def _update_window_title(self):
        window = self.window()
        if window is not None:
            window.setWindowTitle("dreamSort \u2014 Mod Manager %s  [%s]"
                                  % (VERSION, self._mode_label()))

    # scanning
    def run_scan(self):
        if self._closing:
            return
        if self._scanning or self.current_state == "working":
            return
        if self.mode == "recomp":
            self._scan_recomp()
        else:
            self._scan_ryujinx()

    def _scan_ryujinx(self):
        path = self._get_current_path()
        if not path or not os.path.isdir(path):
            self.emulator.clear_mods_path()
            self._clear_scan_results()
            self._status("Error: Invalid folder path.")
            self._refresh_structure_sign()
            return
        ok, message, suggested = self.emulator.structure_status(path)
        if not ok:
            self.emulator.clear_mods_path()
            self._clear_scan_results()
            status = "Invalid mods folder: " + message
            if suggested:
                status += "  Try: " + suggested
            self._status(status)
            self._refresh_structure_sign()
            return
        if not self.emulator.set_mods_path(path):
            self.emulator.clear_mods_path()
            self._clear_scan_results()
            self._status("Error: Could not open the mods folder.")
            return

        self.current_details_mod = None
        self.details.placeholder("Select a mod to view details and manage cheats.")
        self._status("Scanning...")
        self._scanning = True
        run_in_thread(self, self._scan_emulator_job, path,
                      on_done=self._on_emulator_scanned,
                      on_error=self._on_scan_error)

    def _scan_emulator_job(self, _path):
        self._dir_stats_cache.clear()
        self.emulator.scan_and_analyze()
        self._initialize_pending_cheats()
        return dict(self.pending_cheat_selections)

    def _on_emulator_scanned(self, pending_cheats):
        self._scanning = False
        if self._closing:
            # window already closed
            return
        self.pending_cheat_selections = pending_cheats
        self.populate_mod_list()
        self.update_all_border_colors()
        if self.view_mode == "tree":
            self.populate_mod_tree()
        focus_cheat = self._pending_details_cheat
        self._pending_details_cheat = None
        if (focus_cheat and self.mode == "eden"
                and focus_cheat in self.emulator.cheat_states()):
            self._show_eden_cheat_details(focus_cheat)
        count = len(self.emulator.load_order)
        conflict_count = len(self._live_conflict_mod_ids())
        message = ("Loaded %d mods (%d conflicts)." % (count, conflict_count)
                   if conflict_count else
                   "Loaded %d mods. No conflicts detected." % count)
        if self.mode == "eden":
            states = self.emulator.cheat_states()
            on = sum(1 for value in states.values() if value)
            message = ("Loaded %d mods (%d conflicts), %d/%d cheats on.  "
                       "Eden: %s" % (count, conflict_count, on, len(states),
                                     self.emulator.variant_label()))
            self._note_eden_switch(on)
        elif self.emulator.mods_json_path:
            message += "  mods.json: " + redact_path(self.emulator.mods_json_path)
        else:
            message += "  (mods.json not found)"
        self._status(message)
        self._refresh_structure_sign()
        self.save_config()

    def _on_scan_error(self, error_text):
        self._scanning = False
        self._status("Scan failed: %s" % error_text.splitlines()[-1])
        dialogs.error(self, "Scan Failed", error_text)
        self.save_config()

    # eden switch
    def _eden_cheat_switch(self):
        # eden enables cheats in its ini
        if self.mode != "eden" or not self.emulator.mods_path:
            return None
        return eden_config.cheat_switch(self.emulator.config_dir,
                                        self.emulator.TITLE_ID)

    def _note_eden_switch(self, enabled_cheats=0):
        # warn once per folder
        if not enabled_cheats:
            return
        state = self._eden_cheat_switch()
        if state is None or state["enabled"]:
            return
        folder = self.emulator.mods_path
        if folder in self._eden_switch_noted:
            return
        self._eden_switch_noted.add(folder)
        # deferred
        QTimer.singleShot(0, lambda: self._offer_enable_eden_cheats(state))

    def eden_settings_popup(self):
        state = self._eden_cheat_switch()
        if state is None:
            dialogs.warn(self, "Eden settings",
                         "Load an Eden load folder first.")
            return
        if state["enabled"]:
            dialogs.info(self, "Eden settings",
                         "Eden starts games with cheats enabled.\n\n"
                         "Source: %s\nGlobal ini: %s"
                         % (state["source"], state["global_path"]))
            return
        self._offer_enable_eden_cheats(state)

    def _offer_enable_eden_cheats(self, state):
        places = [state["global_path"]]
        if state["per_game_present"] and not state["use_global"]:
            places.append(state["per_game_path"])
        answer = dialogs.confirm(
            self, "Eden has cheats switched off",
            "Eden ignores every cheat at startup while its own switch is off, "
            "however the folders are arranged.\n\n"
            "Read from:\n%s\n\n"
            "dreamSort can set enable_cheats_by_default=true there. Close Eden "
            "first, because it writes that file again when it exits.\n\n"
            "Write it now? A .dreamsort.bak copy stays beside the original."
            % "\n".join(places))
        if not answer:
            self._status("Eden's cheat switch was left as it is.")
            return
        ok, message = eden_config.set_enabled(self.emulator.config_dir,
                                              self.emulator.TITLE_ID, True)
        if ok:
            dialogs.info(self, "Eden settings", message)
            self._status("Eden cheats switched on in its own config.")
        else:
            dialogs.error(self, "Eden settings", message)

    def _scan_recomp(self):
        path = self._get_current_path()
        if not path or not os.path.isdir(path):
            self.recomp.clear_root()
            self._clear_scan_results()
            self._status("Error: Invalid folder path.")
            return
        ok, message, suggested = self.recomp.structure_status(path)
        if not ok:
            self.recomp.clear_root()
            self._clear_scan_results()
            status = "Invalid Recomp folder: " + message
            if suggested:
                status += "  Try: " + suggested
            self._status(status)
            self._refresh_structure_sign()
            return
        if not self.recomp.set_root(path):
            self.recomp.clear_root()
            self._clear_scan_results()
            self._status("Error: Could not open the Recomp folder.")
            return

        self.current_details_mod = None
        self.details.placeholder("Select a mod to see its details.")
        self._status("Scanning Recomp install...")
        self._scanning = True
        run_in_thread(self, self._scan_recomp_job,
                      on_done=self._on_recomp_scanned,
                      on_error=self._on_scan_error)

    def _scan_recomp_job(self):
        self.recomp.scan()
        return True

    def _on_recomp_scanned(self, _result):
        self._scanning = False
        self.populate_recomp_list()
        if self.view_mode == "tree":
            self.populate_recomp_tree()
        self._status("Loaded %d mods, %d cheats, %d plugins, %d patches."
                     % (len(self.recomp.mods), len(self.recomp.cheats),
                        len(self.recomp.plugins), len(self.recomp.patches)))
        self._refresh_structure_sign()
        self.save_config()

    def _clear_scan_results(self):
        self.list_widget.clear_items()
        self.recomp_mods_section = None
        self.mod_rows = {}
        self._rows_by_id = {}
        self.mod_enabled = {}
        self.cheat_rows = {}
        self.patch_rows = {}
        self.plugin_rows = {}
        self.file_rows = {}
        self.selected_files = set()
        self.pending_cheat_selections = {}
        self.tree.clear_items()
        self.selected_mods.clear()
        self._update_selection_bar()
        self.details.clear()
        self.details.placeholder("Select a mod to see its details.")

    # populate (ryujinx)
    def populate_mod_list(self):
        self.list_widget.clear_items()
        self.mod_rows = {}
        self._rows_by_id = {}
        self.mod_enabled = {}
        self.selected_mods.clear()
        self._update_selection_bar()

        analyzer = self.emulator
        all_mods = analyzer.load_order
        special = analyzer.special_cheats_folder_name
        romfs_mods = [m for m in all_mods
                      if m != special and m not in analyzer.cheat_only_mods]

        def mod_is_on(mod_name):
            # disabled prefix
            if self.mode == "eden":
                return analyzer.is_mod_enabled(mod_name)
            return not mod_name.startswith("~")

        for mod_name in romfs_mods:
            row = ModRow(mod_name, analyzer.strip_prefix(mod_name),
                         checkbox=True, draggable=True)
            row.set_mod_enabled(mod_is_on(mod_name))
            row.toggled.connect(self._on_row_toggled)
            row.activated.connect(self._on_row_activated)
            row.ctrlClicked.connect(self._on_row_ctrl_clicked)
            row.contextRequested.connect(self._on_row_context_menu)
            self.list_widget.add_row(row)
            self._register_row(row)
            self.mod_enabled[mod_name] = mod_is_on(mod_name)

        if special:
            self.list_widget.add_divider("--- Ryujinx Enabled Cheats ---")
            row = ModRow(special, analyzer.strip_prefix(special), checkbox=False,
                         variant="special", draggable=False)
            row.activated.connect(self._on_row_activated)
            row.contextRequested.connect(self._on_row_context_menu)
            self.list_widget.add_row(row)
            self._register_row(row)

        cheat_mods = [m for m in all_mods if m in analyzer.cheat_only_mods]
        if cheat_mods:
            self.list_widget.add_divider("--- Detected Cheats ---")
        for mod_name in cheat_mods:
            row = ModRow(mod_name, analyzer.strip_prefix(mod_name),
                         checkbox=False, variant="cheat", draggable=False)
            row.activated.connect(self._on_row_activated)
            row.contextRequested.connect(self._on_row_context_menu)
            self.list_widget.add_row(row)
            self._register_row(row)

        if self.mode == "eden":
            self._populate_eden_cheats(analyzer)

        self._renumber_mod_rows()

    def _populate_eden_cheats(self, analyzer):
        # one folder per cheat
        self.eden_cheat_rows = {}
        states = analyzer.cheat_states()
        self.eden_cheat_states = dict(states)
        section = CollapsibleSection(
            "Cheats (%d)" % len(states), body=ModListWidget())
        section.body.dropPaths.connect(self._on_paths_dropped)
        for name, enabled in states.items():
            row = FileRow(name, name, checked=enabled)
            if not enabled:
                row.set_note("(in disabled_cheats)")
            row.toggled.connect(
                lambda key, checked: self._on_eden_cheat_toggled(key, checked))
            row.activated.connect(
                lambda key: self._show_eden_cheat_details(key))
            section.body.add_item(row)
            self.eden_cheat_rows[name] = row
        if not states:
            section.body.add_item(self._empty_label("(no cheats installed)"))
        self.list_widget.add_item(section)

    def _on_eden_cheat_toggled(self, name, checked):
        self.eden_cheat_states[name] = bool(checked)
        self._status("Cheat '%s' %s. Click 'Apply New Order' to save."
                     % (name, "enabled" if checked else "disabled"))

    def _show_eden_cheat_details(self, name):
        self.current_details_mod = None
        self.details.clear()
        enabled = self.eden_cheat_states.get(name, True)
        self.details.heading("Cheat: %s" % name)
        folder = self.emulator.cheat_folder_path(name)
        code_path = self.emulator.cheat_code_path(name)
        rows = [
            ("State", "Enabled" if enabled else "Disabled (in disabled_cheats)"),
            ("Folder", redact_path(folder)),
            ("Cheat file", redact_path(code_path) if code_path else "(none)"),
        ]
        self.details.card(rows, open_path=folder)

        # one row per block
        files = self.emulator.cheat_code_files(name)
        entries = []
        raw_text = None
        for path in files:
            try:
                with open(path, "r", encoding="utf-8",
                          errors="replace") as handle:
                    text = handle.read()
            except Exception as exc:
                self.details.hint("Could not read %s: %s"
                                  % (os.path.basename(path),
                                     redact_path(str(exc))))
                continue
            if raw_text is None:
                raw_text = text
            for index, (title, block) in enumerate(
                    self.emulator.cheat_blocks(text)):
                entries.append((path, index, title, block))

        if not entries:
            if files:
                self.details.hint("No [Title] header in this cheat's .txt, so "
                                  "there is no entry to list or edit.")
            else:
                self.details.hint("No .txt inside this cheat's cheats/ folder.")
            return

        self.details.label("Cheat entries (%d)" % len(entries), bold=True)
        if len(files) > 1:
            self.details.hint("This folder holds %d .txt files; the code box "
                              "below shows %s." % (len(files),
                                                   os.path.basename(files[0])))
        for path, index, title, block in entries:
            holder, box = self.details.row()
            label = QLabel(title, holder)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            box.addWidget(label, 1)
            view_btn = QPushButton("View Code", holder)
            view_btn.setFixedWidth(100)
            view_btn.clicked.connect(
                lambda _checked=False, t=title, b=block:
                dialogs.CheatCodeDialog.view(self, t, b))
            box.addWidget(view_btn, 0)
            edit_btn = QPushButton("Edit", holder)
            edit_btn.setFixedWidth(70)
            edit_btn.clicked.connect(
                lambda _checked=False, n=name, p=path, i=index, t=title:
                self._edit_eden_cheat_block(n, p, i, t))
            box.addWidget(edit_btn, 0)
        self.details.hint("Eden has no per-entry switch: a cheat is enabled or "
                          "disabled as a folder (tick it in the list, then "
                          "Apply). Split a multi-block file to get separate "
                          "ticks.")

        if raw_text is not None:
            self.details.label("Cheat code", bold=True)
            self.details.code_area(raw_text, height=220)
            blocks = self.emulator.cheat_blocks(raw_text)
            if len(blocks) > 1:
                self.details.hint("This one file holds %d cheat blocks; Eden "
                                  "lists them as a single cheat entry."
                                  % len(blocks))
                holder, box = self.details.row()
                box.addStretch(1)
                split_btn = QPushButton(
                    "Split into %d separate cheats" % len(blocks), holder)
                split_btn.setToolTip(
                    "Create one cheat folder per [Title] block, then park the "
                    "original in disabled_cheats/ so the codes are not loaded "
                    "twice.")
                split_btn.clicked.connect(
                    lambda _checked=False, n=name, c=len(blocks):
                    self._split_eden_cheat(n, c))
                box.addWidget(split_btn, 0)

    def _edit_eden_cheat_block(self, cheat_name, path, index, title):
        try:
            with open(path, "r", encoding="utf-8",
                      errors="replace") as handle:
                text = handle.read()
        except Exception as exc:
            dialogs.error(self, "Read Failed", str(exc))
            return
        blocks = self.emulator.cheat_blocks(text)
        if not 0 <= index < len(blocks):
            dialogs.warn(self, "Not Found",
                         "That cheat entry no longer exists; reopen the cheat.")
            return
        current = blocks[index][1]
        edited = dialogs.CheatCodeDialog.edit(self, title, current)
        if edited is None or edited == current:
            return
        try:
            self.emulator.update_cheat_block(path, index, edited)
        except Exception as exc:
            dialogs.error(self, "Write Failed", str(exc))
            return
        self._status("Saved cheat entry '%s'." % title)
        self._show_eden_cheat_details(cheat_name)

    def _split_eden_cheat(self, name, count):
        enabled = self.eden_cheat_states.get(name, True)
        extra = ("" if enabled else
                 "\nThe original is disabled, so the new folders go into "
                 "disabled_cheats/ too; tick them and Apply to turn them on.")
        if not dialogs.confirm(
                self, "Split Cheat",
                "'%s' holds %d cheat blocks in one file.\n\n"
                "Split it into %d separate cheat folders, one per block, so "
                "each can be ticked on its own?\n\n"
                "The new folders are created next to the original, and the "
                "original is moved to disabled_cheats/ (still on disk, just "
                "not loaded) so the same codes are not applied twice.%s"
                % (name, count, count, extra)):
            return
        try:
            created = self.emulator.split_cheat_entry(name)
        except Exception as exc:
            dialogs.error(self, "Split Failed", str(exc))
            return
        self._status("Split '%s' into %d cheats: %s"
                     % (name, len(created), ", ".join(created)))
        self._pending_details_cheat = created[0] if created else None
        self.run_scan()

    def _register_row(self, row, primary=True):
        self._rows_by_id.setdefault(row.mod_id, []).append(row)
        if primary:
            self.mod_rows[row.mod_id] = row

    def _rows_for(self, mod_id):
        return list(self._rows_by_id.get(mod_id, []))

    def _order_ids(self):
        return self.list_widget.order_ids()

    def _orderable_ids(self):
        return [w.mod_id for w in self.list_widget.row_widgets()
                if w.checkbox is not None]

    def _load_numbers(self):
        # numbers only for loadable mods
        ids = self._recomp_order_ids() if self.mode == "recomp" else self._order_ids()
        numbers = {}
        for mod_id in ids:
            row = self.mod_rows.get(mod_id)
            if row is None or row.checkbox is None:
                continue
            if getattr(row, "variant", "") != "romfs":
                continue
            if not self.mod_enabled.get(mod_id, row.checkbox.isChecked()):
                continue
            numbers[mod_id] = len(numbers) + 1
        return numbers

    def _renumber_mod_rows(self):
        numbers = self._load_numbers()
        for mod_id, rows in list(self._rows_by_id.items()):
            value = numbers.get(mod_id)
            for row in rows:
                if not hasattr(row, "set_index"):
                    continue
                # gutter stays hidden
                mod_row = getattr(row, "variant", "") == "romfs"
                row.set_index(value, reserve=mod_row and row.checkbox is not None)

    # populate (recomp)
    def populate_recomp_list(self):
        self.list_widget.clear_items()
        self.recomp_mods_section = None
        self.mod_rows = {}
        self._rows_by_id = {}
        self.mod_enabled = {}
        self.cheat_rows = {}
        self.patch_rows = {}
        self.plugin_rows = {}
        self.file_rows = {}
        self.selected_files.clear()
        self.selected_mods.clear()
        self._update_selection_bar()

        analyzer = self.recomp
        ordered = analyzer.get_ordered_mods()

        # all mods
        all_section = CollapsibleSection(
            "All Mods (%d)" % len(ordered), collapsed=True, body=ModListWidget())
        all_section.body.dropPaths.connect(self._on_paths_dropped)
        self._build_recomp_mod_rows(all_section.body, ordered, analyzer,
                                    draggable=False, primary=False)
        self.list_widget.add_item(all_section)

        # romfs mods
        romfs_mods = [(n, d) for n, d in ordered if d.get("has_romfs")]
        romfs_section = CollapsibleSection(
            "romFS Mods (%d)" % len(romfs_mods), body=ModListWidget())
        romfs_section.body.dropPaths.connect(self._on_paths_dropped)
        romfs_section.body.reorderRequested.connect(
            lambda mod_id, index: self._on_reorder_requested(
                mod_id, index, romfs_section.body))
        self._build_recomp_mod_rows(romfs_section.body, romfs_mods, analyzer,
                                    draggable=True, primary=True)
        if not romfs_mods:
            romfs_section.body.add_item(
                self._empty_label("(no mods with romFS content)"))
        self.list_widget.add_item(romfs_section)
        self.recomp_mods_section = romfs_section

        # forge plugins
        plugins_section = CollapsibleSection(
            "Forge Plugins (%d)" % len(analyzer.plugins), body=ModListWidget())
        plugins_section.body.dropPaths.connect(self._on_paths_dropped)
        for entry in analyzer.plugins:
            key = (entry["mod"], entry["rel_path"])
            row = FileRow(key, "  \u2514 " + entry["filename"],
                          checked=entry["enabled"],
                          muted=entry.get("ignored_by_recomp"))
            row.setToolTip("Click the tick to enable or disable this file "
                           "(Apply moves it in or out of disabled/); click "
                           "the row for its details.")
            if entry.get("ignored_by_recomp"):
                row.set_note("(not loaded by the recomp)")
            row.activated.connect(
                lambda _k, own=key: self._on_file_activated(own))
            plugins_section.body.add_item(row)
            self.plugin_rows[key] = row
            self.file_rows[key] = row
        if not analyzer.plugins:
            plugins_section.body.add_item(
                self._empty_label("(no native plugins)"))
        self.list_widget.add_item(plugins_section)

        # exefs patches
        patches_section = CollapsibleSection(
            "Exefs Patches (%d)" % len(analyzer.patches), body=ModListWidget())
        patches_section.body.dropPaths.connect(self._on_paths_dropped)
        for entry in analyzer.patches:
            key = (entry["mod"], entry["rel_path"])
            row = FileRow(key, "  \u2514 " + entry["filename"],
                          checked=entry["enabled"],
                          muted=entry.get("ignored_by_recomp"))
            row.setToolTip("Click the tick to enable or disable this file "
                           "(Apply moves it in or out of disabled/); click "
                           "the row for its details.")
            if entry.get("ignored_by_recomp"):
                row.set_note("(not loaded by the recomp)")
            row.activated.connect(
                lambda _k, own=key: self._on_file_activated(own))
            patches_section.body.add_item(row)
            self.patch_rows[key] = row
            self.file_rows[key] = row
        if not analyzer.patches:
            patches_section.body.add_item(
                self._empty_label("(no exefs patches)"))
        self.list_widget.add_item(patches_section)

        # cheats
        cheats_section = CollapsibleSection(
            "Cheats (%d)" % len(analyzer.cheats), body=ModListWidget())
        cheats_section.body.dropPaths.connect(self._on_paths_dropped)
        for clean_name in sorted(analyzer.cheats, key=lambda n: n.lower()):
            data = analyzer.cheats[clean_name]
            row = FileRow(clean_name, "  \u2514 " + clean_name,
                          checked=data.get("enabled", True))
            row.activated.connect(
                lambda _k, own=clean_name: self._on_file_activated(own))
            cheats_section.body.add_item(row)
            self.cheat_rows[clean_name] = row
            self.file_rows[clean_name] = row
        if not analyzer.cheats:
            cheats_section.body.add_item(self._empty_label("(no cheat files)"))
        self.list_widget.add_item(cheats_section)

        self._recomp_recolor_all()
        self._renumber_mod_rows()

    def _empty_label(self, text):
        label = QLabel(text, self.list_widget)
        label.setStyleSheet("color: %s; background: transparent; padding: 2px 6px;"
                            % Colors.DISABLED)
        return label

    def _build_recomp_mod_rows(self, container, entries, analyzer, *,
                               draggable, primary):
        for clean_name, data in entries:
            chips = []
            if data.get("has_romfs"):
                chips.append(("romFS", "romfs", False))
            if data.get("has_exefs"):
                chips.append(("exefs", "exefs", False))
            if data.get("has_plugins"):
                chips.append(("forge", "forge", False))
            if data.get("has_arc"):
                chips.append(("arc", "arc", True))
            display = self._display_recomp_name(clean_name)
            row = ModRow(clean_name, display, checkbox=True, chips=chips,
                         bold=clean_name.lower() in self.FOUNDATION_LIBS,
                         draggable=draggable)
            row.set_mod_enabled(bool(data.get("enabled", True)))
            if primary:
                row.toggled.connect(self._recomp_mod_toggled)
                row.activated.connect(self._on_row_activated)
                row.ctrlClicked.connect(self._on_row_ctrl_clicked)
                row.contextRequested.connect(self._on_row_context_menu)
            else:
                row.toggled.connect(self._recomp_mod_toggled)
                row.activated.connect(self._on_row_activated)
            container.add_row(row)
            self._register_row(row, primary=primary)
            if primary:
                self.mod_enabled[clean_name] = bool(data.get("enabled", True))

    def _display_recomp_name(self, clean_name):
        mapped = self.FOUNDATION_LIBS.get(clean_name.lower())
        if mapped:
            return "%s  (%s)" % (clean_name, mapped)
        return clean_name

    def _recomp_mod_toggled(self, mod_id, checked):
        self.mod_enabled[mod_id] = checked
        for row in self._rows_for(mod_id):
            if row.checkbox is not None and row.checkbox.isChecked() != checked:
                row.checkbox.blockSignals(True)
                row.checkbox.setChecked(checked)
                row.checkbox.blockSignals(False)
        self._recomp_recolor_all()
        self._renumber_mod_rows()
        if self.view_mode == "tree":
            self.populate_recomp_tree()

    def _recomp_recolor_all(self):
        view = self._recomp_conflict_view()
        index_of = self._recomp_order_index()
        for mod_id, rows in list(self._rows_by_id.items()):
            enabled = self.mod_enabled.get(mod_id, True)
            if mod_id in self.selected_mods:
                state = "selected"
            elif not enabled:
                state = "disabled"
            elif mod_id not in view:
                state = "none"
            else:
                state = self._recomp_win_state(mod_id, view, index_of)
            for row in rows:
                row.set_conflict_state(state)

    def _recomp_order_ids(self):
        if self.recomp_mods_section is None:
            return []
        return self.recomp_mods_section.body.order_ids()

    def _recomp_enabled(self, mod_id):
        return bool(self.mod_enabled.get(mod_id, True))

    def _recomp_conflict_view(self):
        # parked rivals do not count
        return self.recomp.conflict_view(self._recomp_enabled)

    def _recomp_order_index(self):
        return {name: i for i, name in enumerate(self._recomp_order_ids())}

    def _recomp_latest(self, mods, index_of):
        # later mod wins
        return self.recomp.latest_mod(mods, index_of)

    def _recomp_win_state(self, mod_id, view, index_of):
        return self.recomp.win_state(mod_id, view, index_of)

    def _recomp_conflict_warning(self):
        # confirm what gets overridden
        view = self._recomp_conflict_view()
        if not view:
            return ""
        index_of = self._recomp_order_index()
        lines = []
        for mod in sorted(view):
            rel, cell = sorted(view[mod].items())[0]
            winner = self._recomp_latest([mod] + cell["rivals"], index_of)
            lines.append("  \u2022 %s: %s vs %s \u2014 %s"
                         % (mod, rel, ", ".join(cell["rivals"]),
                            "yours" if winner == mod else winner + "'s"))
        text = ("\n\n%d mod(s) share changed content with another enabled "
                "mod; the later one wins:\n%s"
                % (len(view), "\n".join(lines[:8])))
        if len(lines) > 8:
            text += "\n  ... and %d more mod(s)" % (len(lines) - 8)
        return text

    # colours and toggling
    def _conflict_later_wins(self):
        # who wins differs per runtime
        return self.mode != "ryujinx"

    def update_all_border_colors(self):
        order = self._order_ids()
        order_index = {name: i for i, name in enumerate(order)}
        later_wins = self._conflict_later_wins()
        conflicts = getattr(self.emulator, "conflicts", {}) or {}
        for mod_id, row in list(self.mod_rows.items()):
            if mod_id in self.selected_mods:
                row.set_selected(True)
                continue
            if row.checkbox is None:
                row.set_conflict_state("none")
                continue
            if not self.mod_enabled.get(mod_id, True):
                row.set_conflict_state("disabled")
                continue

            # one vote per contested path
            wins = 0
            losses = 0
            for rivals in conflicts.get(mod_id, {}).values():
                contenders = [
                    name for name in [mod_id] + list(rivals)
                    if name == mod_id or self.mod_enabled.get(name, True)
                ]
                contenders = [name for name in contenders
                              if name in order_index]
                if len(contenders) < 2:
                    continue
                pick = max if later_wins else min
                holder = pick(contenders, key=lambda name: order_index[name])
                if holder == mod_id:
                    wins += 1
                else:
                    losses += 1

            if losses and wins <= losses:
                row.set_conflict_state("loser")
            elif wins:
                row.set_conflict_state("winner")
            else:
                row.set_conflict_state("none")

    def _on_row_toggled(self, mod_id, checked):
        self.mod_enabled[mod_id] = checked
        for row in self._rows_for(mod_id):
            if row.checkbox is not None and row.checkbox.isChecked() != checked:
                row.checkbox.blockSignals(True)
                row.checkbox.setChecked(checked)
                row.checkbox.blockSignals(False)
        self.update_all_border_colors()
        self._renumber_mod_rows()
        if self.view_mode == "tree":
            self.populate_mod_tree()

    def _set_mod_enabled(self, mod_id, enabled, *, emit=True):
        self.mod_enabled[mod_id] = bool(enabled)
        for row in self._rows_for(mod_id):
            if row.checkbox is None:
                continue
            if row.checkbox.isChecked() == bool(enabled):
                continue
            if emit:
                row.checkbox.setChecked(bool(enabled))
            else:
                row.checkbox.blockSignals(True)
                row.checkbox.setChecked(bool(enabled))
                row.checkbox.blockSignals(False)

    def _is_mod_enabled(self, mod_id):
        row = self.mod_rows.get(mod_id)
        if row is None:
            return False
        if row.checkbox is None:
            return True
        if mod_id in self.mod_enabled:
            return bool(self.mod_enabled[mod_id])
        return row.checkbox.isChecked()

    def _live_conflicts(self, mod_id):
        # only enabled rivals
        conflicts = getattr(self.emulator, "conflicts", {}) or {}
        live = {}
        for rel_path, rivals in (conflicts.get(mod_id, {}) or {}).items():
            active = [name for name in rivals if self._is_mod_enabled(name)]
            if active:
                live[rel_path] = active
        return live

    def _live_conflict_mod_ids(self):
        return [mod_id for mod_id in self._order_ids()
                if self._is_mod_enabled(mod_id) and self._live_conflicts(mod_id)]

    def _on_reorder_requested(self, mod_id, index, container):
        if container is None:
            return
        if container.move_row(mod_id, index):
            self._after_order_change(
                "Order changed. Click 'Apply New Order' to save.")

    def _after_order_change(self, status_text=None):
        if self.mode == "recomp":
            self._recomp_recolor_all()
            self._renumber_mod_rows()
            if self.view_mode == "tree":
                self.populate_recomp_tree()
        else:
            self.update_all_border_colors()
            self._renumber_mod_rows()
            if self.view_mode == "tree":
                self.populate_mod_tree()
        if status_text:
            self._status(status_text)

    # selection
    def _on_row_activated(self, mod_id):
        if self.current_state == "working":
            return
        self._clear_file_selection()
        if len(self.selected_mods) == 1 and mod_id in self.selected_mods:
            self.clear_selection()
        else:
            self.clear_selection()
            self.selected_mods.add(mod_id)
            for row in self._rows_for(mod_id):
                row.set_selected(True)
            self._update_selection_bar()
        self.show_details(mod_id)

    def _on_row_ctrl_clicked(self, mod_id):
        self._clear_file_selection()
        if mod_id in self.selected_mods:
            self.selected_mods.discard(mod_id)
            for row in self._rows_for(mod_id):
                row.set_selected(False)
        else:
            self.selected_mods.add(mod_id)
            for row in self._rows_for(mod_id):
                row.set_selected(True)
        self._update_selection_bar()
        self._after_order_change()

    def _on_file_activated(self, key):
        # child row details
        if self.current_state == "working":
            return
        repeat = len(self.selected_files) == 1 and key in self.selected_files
        self._clear_file_selection()
        if not repeat:
            self.selected_files.add(key)
            if key in self.file_rows:
                self.file_rows[key].set_selected(True)
            self._drop_mod_selection()
        self.show_details(key)

    def _drop_mod_selection(self):
        # do not rebuild the clicked row
        if not self.selected_mods:
            return
        selected = list(self.selected_mods)
        self.selected_mods.clear()
        for mod_id in selected:
            for row in self._rows_for(mod_id):
                row.set_selected(False)
        self._update_selection_bar()

    def _clear_file_selection(self):
        if not self.selected_files:
            return
        self.selected_files.clear()
        for row in list(self.file_rows.values()):
            row.set_selected(False)

    def clear_selection(self):
        selected = list(self.selected_mods)
        self.selected_mods.clear()
        for mod_id in selected:
            for row in self._rows_for(mod_id):
                row.set_selected(False)
        self._update_selection_bar()
        self._after_order_change()

    def _update_selection_bar(self):
        count = len(self.selected_mods)
        if count:
            self.selection_label.setText("%d mod%s selected" %
                                         (count, "" if count == 1 else "s"))
            self.selection_bar.show()
        else:
            self.selection_bar.hide()

    def _bulk_enable(self, want):
        if not self.selected_mods:
            return
        count = 0
        for mod_id in list(self.selected_mods):
            if self.mode == "recomp":
                if mod_id not in self.mod_rows:
                    continue
                row = self.mod_rows[mod_id]
                if row.checkbox is None:
                    continue
                row.checkbox.setChecked(want)
            else:
                if mod_id in self.emulator.cheat_only_mods:
                    continue
                if self.emulator.special_cheats_folder_name == mod_id:
                    continue
                self._set_mod_enabled(mod_id, want)
            count += 1
        self._after_order_change("%s %d mod%s." %
                                 ("Enabled" if want else "Disabled", count,
                                  "" if count == 1 else "s"))

    def _bulk_delete(self):
        names = sorted(self.selected_mods)
        if not names:
            return
        if not dialogs.confirm(
                self, "Delete Selected",
                "Permanently delete %d selected mod%s?" %
                (len(names), "" if len(names) == 1 else "s")):
            return
        deleted = 0
        for mod_id in names:
            if self._delete_mod_path(mod_id, ask=False):
                deleted += 1
        self._after_order_change("Deleted %d mod%s." %
                                 (deleted, "" if deleted == 1 else "s"))

    def _delete_mod_path(self, mod_id, *, ask=True):
        path = self._mod_folder(mod_id)
        if not path or not os.path.isdir(path):
            dialogs.error(self, "Delete Failed", "Mod folder not found for '%s'."
                          % mod_id)
            return False
        if ask and not dialogs.confirm(self, "Delete Mod",
                                       "Delete '%s'?\n\n%s" % (mod_id, path)):
            return False
        try:
            shutil.rmtree(path)
        except Exception as exc:
            dialogs.error(self, "Delete Failed",
                          "Could not delete '%s':\n\n%s" % (mod_id, exc))
            return False
        self._remove_rows(mod_id)
        return True

    def _mod_folder(self, mod_id):
        if self.mode == "recomp":
            return self.recomp.get_current_mod_path(mod_id)
        if self.mode == "eden" and not self.emulator.is_mod_enabled(mod_id):
            # parked one level down
            return os.path.join(self.emulator.disabled_mods_path, mod_id)
        if not self.emulator.mods_path:
            return ""
        return os.path.join(self.emulator.mods_path, mod_id)

    def _remove_rows(self, mod_id):
        rows = self._rows_for(mod_id)
        for row in rows:
            container = row.parentWidget()
            while container is not None and not isinstance(container,
                                                          ModListWidget):
                container = container.parentWidget()
            if isinstance(container, ModListWidget):
                container.remove_row(row)
        self._rows_by_id.pop(mod_id, None)
        self.mod_rows.pop(mod_id, None)
        self.mod_enabled.pop(mod_id, None)
        self.selected_mods.discard(mod_id)
        self.cheat_rows.pop(mod_id, None)
        self._update_selection_bar()

    # context menus
    def _on_row_context_menu(self, mod_id, global_pos):
        menu = QMenu(self)
        multi = len(self.selected_mods) > 1 and mod_id in self.selected_mods
        if multi:
            menu.addAction("Enable Selected (%d)" % len(self.selected_mods),
                           lambda: self._bulk_enable(True))
            menu.addAction("Disable Selected (%d)" % len(self.selected_mods),
                           lambda: self._bulk_enable(False))
            menu.addSeparator()

        menu.addAction("Open mod folder",
                       lambda: self._open_mod_folder(mod_id))

        if self.mode == "ryujinx" and mod_id in self._orderable_ids():
            menu.addAction("Move to top", lambda: self._move_mod_to_edge(mod_id, "top"))
            menu.addAction("Move to bottom",
                           lambda: self._move_mod_to_edge(mod_id, "bottom"))
            menu.addSeparator()

        if multi:
            menu.addAction("Delete Selected (%d)" % len(self.selected_mods),
                           self._bulk_delete)
        else:
            menu.addAction("Delete mod", lambda: self._delete_mod(mod_id))
        menu.exec(global_pos)

    def _delete_mod(self, mod_id):
        if self._delete_mod_path(mod_id):
            self._after_order_change("Deleted '%s'." % mod_id)

    def _open_mod_folder(self, mod_id):
        path = self._mod_folder(mod_id)
        if path and os.path.isdir(path):
            open_in_file_explorer(path)
        else:
            dialogs.warn(self, "Not Found", "Folder not found:\n%s"
                         % redact_path(path))

    def _move_mod_to_edge(self, mod_id, side):
        container = self._reorder_container()
        if container is None:
            return
        ids = [i for i in container.order_ids() if i != mod_id]
        index = 0 if side == "top" else len(ids)
        if container.move_row(mod_id, index):
            self._after_order_change(
                "Order changed. Click 'Apply New Order' to save.")

    def _move_mod_above(self, mod_id, target_id):
        container = self._reorder_container()
        if container is None:
            return
        if target_id not in container.order_ids():
            self._status("Cannot reorder: '%s' is not in the load order." % target_id)
            return
        ids = [i for i in container.order_ids() if i != mod_id]
        index = ids.index(target_id)
        if container.move_row(mod_id, index):
            self._status("'%s' set to win over '%s'. Click 'Apply New Order'."
                         % (mod_id, target_id))
            self._after_order_change()

    def _move_mod_below(self, mod_id, target_id):
        # later mod wins
        container = self._reorder_container()
        if container is None:
            return
        if target_id not in container.order_ids():
            self._status("Cannot reorder: '%s' is not in the load order."
                         % target_id)
            return
        ids = [i for i in container.order_ids() if i != mod_id]
        index = ids.index(target_id) + 1
        if container.move_row(mod_id, index):
            self._status("'%s' now loads after '%s' (later wins). "
                         "Click 'Apply New Order'." % (mod_id, target_id))
            self._after_order_change()

    def _recomp_make_win(self, mod_id, rivals):
        container = self._reorder_container()
        if container is None:
            return
        index_of = {name: i for i, name in enumerate(container.order_ids())}
        live = [r for r in rivals if r != mod_id and r in index_of]
        if live:
            self._move_mod_below(mod_id, self._recomp_latest(live, index_of))

    def _reorder_container(self):
        if self.mode == "recomp":
            if self.recomp_mods_section is None:
                return None
            return self.recomp_mods_section.body
        return self.list_widget

    # details (ryujinx)
    def show_details(self, mod_id):
        if self.current_state == "working":
            return
        if self.mode == "recomp":
            self._show_recomp_details(mod_id)
            return
        self.current_details_mod = mod_id
        if mod_id == self.emulator.special_cheats_folder_name:
            self._show_enabled_cheats_preview()
        elif mod_id in self.emulator.cheat_only_mods:
            self._show_cheat_manager(mod_id)
        else:
            self._show_conflict_details(mod_id)

    def _show_conflict_details(self, mod_name):
        self.current_details_mod = mod_name
        self.details.clear()
        clean = self.emulator.strip_prefix(mod_name)
        self.details.heading("Mod: %s" % clean)

        path = os.path.join(self.emulator.mods_path, mod_name)
        stats = (getattr(self.emulator, "mod_stats", None) or {}).get(mod_name)
        if stats is None:
            stats = self._dir_stats(path)
        file_count, size = stats
        rows = [
            ("Name", clean),
            ("Location", redact_path(path)),
            ("Files", "%d files" % file_count),
            ("Size", self._format_size(size)),
            ("State", "Enabled" if self._is_mod_enabled(mod_name) else "Disabled"),
        ]
        self.details.card(rows, open_path=path)

        conflicts = self._live_conflicts(mod_name)
        if conflicts:
            self.details.label("%d conflicting file%s:" %
                               (len(conflicts), "" if len(conflicts) == 1 else "s"),
                               bold=True)
            for rel_path in sorted(conflicts)[:40]:
                rivals = conflicts[rel_path]
                holder, box = self.details.row()
                label = QLabel(rel_path, holder)
                label.setWordWrap(True)
                label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                box.addWidget(label, 1)
                note = QLabel("vs " + ", ".join(rivals)[:60], holder)
                note.setStyleSheet("color: %s; background: transparent;"
                                   % Colors.TEXT_MUTED)
                box.addWidget(note, 0)
                win_btn = QPushButton("Make mine win", holder)
                win_btn.setFixedWidth(120)
                # move above or below the rival
                move = (self._move_mod_below if self._conflict_later_wins()
                        else self._move_mod_above)
                win_btn.clicked.connect(
                    lambda _checked=False, t=rivals[0]: move(mod_name, t))
                box.addWidget(win_btn, 0)
            if len(conflicts) > 40:
                self.details.hint("(%d more not shown)" % (len(conflicts) - 40))
        else:
            shared = (getattr(self.emulator, "conflicts", {}) or {}).get(mod_name) or {}
            if shared:
                self.details.hint(
                    "No active conflicts. %d shared file%s overlap only with "
                    "mods that are switched off." % (
                        len(shared), "" if len(shared) == 1 else "s"))
            else:
                self.details.hint("No conflicts detected for this mod.")

        files = [entry for entry in self.cheat_files_model
                 if entry["owner"] == mod_name]
        if files:
            count = sum(len(entry["entries"]) for entry in files)
            self.details.label("Cheat entries (%d)" % count, bold=True)
            self._cheat_group_rows(files, show_file_label=len(files) > 1)
            self.details.hint("Ryujinx loads these from this mod's cheats/ "
                              "folder even when the mod itself is disabled.")

        state = "disabled" if not self._is_mod_enabled(mod_name) else "enabled"
        holder_rule = ("Larger load numbers win conflicts."
                       if self._conflict_later_wins()
                       else "Smaller load numbers win conflicts.")
        self.details.hint("This mod is %s. %s" % (state, holder_rule))

    def _show_enabled_cheats_preview(self):
        folder = self.emulator.special_cheats_folder_name
        self.details.clear()
        self.details.heading("Ryujinx Cheats: %s" % self.emulator.strip_prefix(folder))
        path = self.emulator.cheat_enabled_path()
        content = ""
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    content = handle.read()
            except Exception as exc:
                content = "Could not read enabled.txt:\n%s" % redact_path(str(exc))
        else:
            content = "(enabled.txt has not been written yet)"
        self.details.label("Applied cheat list", bold=True)
        self.details.code_area(content or "(empty)", height=260)
        files = [entry for entry in self.cheat_files_model
                 if entry["owner"] == ""]
        if files:
            self.details.label("Cheat entries in this folder (%d file%s)"
                               % (len(files), "" if len(files) == 1 else "s"),
                               bold=True)
            self._cheat_group_rows(files, show_file_label=len(files) > 1)
        self.details.hint("Location: %s" % wrap_path_text(redact_path(path)))

    def _show_cheat_manager(self, mod_name):
        self.current_details_mod = mod_name
        self.details.clear()
        clean = self.emulator.strip_prefix(mod_name)
        self.details.heading("Cheat Mod: %s" % clean)
        files = [entry for entry in self.cheat_files_model
                 if entry["owner"] == mod_name]
        if not files:
            self.details.hint("No cheat file (.txt named after a 16-digit "
                              "build id) inside this mod.")
            return
        self.details.label("Tick the cheat entries you want in enabled.txt:",
                           bold=True)
        self._cheat_group_rows(files)
        self.details.hint("Ryujinx switches cheats on per entry: enabled.txt "
                          "gets one \"<build id>-<name Cheat>\" line per ticked "
                          "entry.")

    def _cheat_group_rows(self, files, *, show_file_label=True):
        # one group per cheat file
        for entry in files:
            if show_file_label:
                self.details.label(entry["rel"], bold=True, mono=True)
            for item in entry["entries"]:
                holder, box = self.details.row()
                check = CheckMark(holder, size=16)
                states = self.pending_cheat_selections.get(entry["path"], {})
                check.setChecked(bool(states.get(item["key"], False)))
                check.toggled.connect(
                    lambda checked, p=entry["path"], k=item["key"]:
                    self._on_cheat_toggled(p, k, checked))
                box.addWidget(check, 0)
                label = QLabel(item["title"], holder)
                label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                box.addWidget(label, 1)
                view_btn = QPushButton("View Code", holder)
                view_btn.setFixedWidth(100)
                view_btn.clicked.connect(
                    lambda _checked=False, p=entry["path"], i=item["index"]:
                    self._show_cheat_code(p, i))
                box.addWidget(view_btn, 0)
                edit_btn = QPushButton("Edit", holder)
                edit_btn.setFixedWidth(70)
                edit_btn.clicked.connect(
                    lambda _checked=False, p=entry["path"], i=item["index"]:
                    self._edit_cheat_code(p, i))
                box.addWidget(edit_btn, 0)

    def _on_cheat_toggled(self, path, key, checked):
        # keep both panels in step
        for stored, states in self.pending_cheat_selections.items():
            if key in states:
                states[key] = bool(checked)
        self.pending_cheat_selections.setdefault(path, {})[key] = bool(checked)
        name = key.split("-", 1)[-1]
        self._status("%s %s. Click 'Apply New Order' to save."
                     % (name, "enabled" if checked else "disabled"))

    def _cheat_section(self, path, index):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except Exception as exc:
            dialogs.error(self, "Read Failed", str(exc))
            return None
        sections = self.emulator.cheat_sections(text)
        if not 0 <= index < len(sections):
            dialogs.warn(self, "Not Found",
                         "That cheat entry no longer exists; rescan the mods "
                         "folder.")
            return None
        title, start, end = sections[index][0], sections[index][1], sections[index][2]
        return title, text[start:end].rstrip() + "\n"

    def _show_cheat_code(self, path, index):
        section = self._cheat_section(path, index)
        if section is None:
            return
        dialogs.CheatCodeDialog.view(self, section[0], section[1])

    def _edit_cheat_code(self, path, index):
        section = self._cheat_section(path, index)
        if section is None:
            return
        title, body = section
        edited = dialogs.CheatCodeDialog.edit(self, title, body)
        if edited is None or edited == body:
            return
        try:
            self.emulator.update_cheat_section(path, index, edited)
        except Exception as exc:
            dialogs.error(self, "Write Failed", str(exc))
            return
        # re-read after a rename
        self._load_cheat_model(keep_states=True)
        self.show_details(self.current_details_mod)
        self._status("Saved cheat entry '%s'. Entries re-read from disk." % title)

    # details (recomp)
    def _show_recomp_details(self, mod_id):
        self.current_details_mod = mod_id
        if mod_id in self.recomp.mods:
            self._show_recomp_mod_details(mod_id)
        elif mod_id in self.recomp.cheats:
            self._show_recomp_cheat_details(mod_id)
        else:
            self._show_recomp_file_details(mod_id)

    def _show_recomp_mod_details(self, clean_name):
        self.details.clear()
        data = self.recomp.mods.get(clean_name, {})
        path = self.recomp.get_current_mod_path(clean_name) or ""
        self.details.heading("Mod: %s" % clean_name)

        contents = []
        if data.get("has_romfs"):
            contents.append("romFS")
        if data.get("has_exefs"):
            contents.append("exefs")
        if data.get("has_plugins"):
            contents.append("forge plugin")
        if data.get("has_arc"):
            contents.append(".arc archive")
        rows = [
            ("Name", clean_name),
            ("Location", redact_path(path)),
            ("Contents", ", ".join(contents) or "unknown"),
            ("State", "Enabled" if self.mod_enabled.get(clean_name, True)
             else "Disabled"),
        ]
        self.details.card(rows, open_path=path)

        view = self._recomp_conflict_view()
        conflicts = view.get(clean_name, {})
        index_of = self._recomp_order_index()
        if conflicts:
            self.details.label("%d conflicting file%s:" %
                               (len(conflicts), "" if len(conflicts) == 1
                                else "s"), bold=True)
            self.details.hint("Recomp merges a shared .arc entry by entry; "
                              "a later mod wins an entry it changes "
                              "differently. Per-entry clashes are in grey.")
            for rel_path in sorted(conflicts)[:40]:
                cell = conflicts[rel_path]
                rivals = cell["rivals"]
                winner = self._recomp_latest([clean_name] + rivals, index_of)
                holder, box = self.details.row()
                label = QLabel(rel_path, holder)
                label.setWordWrap(True)
                label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                box.addWidget(label, 1)
                note = QLabel("vs " + ", ".join(rivals)[:60], holder)
                note.setStyleSheet("color: %s; background: transparent;"
                                   % Colors.TEXT_MUTED)
                box.addWidget(note, 0)
                state = QLabel("yours is used" if winner == clean_name
                               else "%s is used" % winner, holder)
                state.setStyleSheet("color: %s; background: transparent;"
                                    % (Colors.RESOLVED_CONFLICT
                                       if winner == clean_name
                                       else Colors.CONFLICT))
                box.addWidget(state, 0)
                win_btn = QPushButton("Make mine win", holder)
                win_btn.setFixedWidth(120)
                win_btn.clicked.connect(
                    lambda _checked=False, m=clean_name, r=list(rivals):
                    self._recomp_make_win(m, r))
                box.addWidget(win_btn, 0)
                for key, key_rivals in list(cell["entries"].items())[:8]:
                    if key is None or not key_rivals:
                        continue
                    key_winner = self._recomp_latest(
                        [clean_name] + key_rivals, index_of)
                    self.details.hint(
                        "    %s  vs %s  \u2192 %s"
                        % (self._entry_label(key), ", ".join(key_rivals),
                           "yours" if key_winner == clean_name
                           else key_winner + "'s"))
            if len(conflicts) > 40:
                self.details.hint("(%d more not shown)" % (len(conflicts) - 40))
        else:
            self.details.hint("No conflicts detected for this mod.")

        mergeable = self.recomp.mergeable_arcs.get(clean_name, {})
        mergeable = {rel: [r for r in rivals if self._recomp_enabled(r)]
                     for rel, rivals in mergeable.items()}
        mergeable = {rel: rivals for rel, rivals in mergeable.items() if rivals}
        if mergeable:
            self.details.label("%d mergeable .arc file%s (no manual merge needed)"
                               % (len(mergeable), "" if len(mergeable) == 1 else "s"),
                               color=Colors.RESOLVED_CONFLICT)
            for rel_path in sorted(mergeable)[:12]:
                self.details.hint("  %s  \u2194  %s" % (rel_path,
                                                       ", ".join(mergeable[rel_path])))

    @staticmethod
    def _entry_label(key):
        if not key:
            return "(whole file)"
        return "%s [type %d]" % (key[0], key[1])

    def _show_recomp_cheat_details(self, clean_name):
        self.details.clear()
        data = self.recomp.cheats.get(clean_name, {})
        self.details.heading("Cheat: %s" % clean_name)
        rows = [
            ("Name", clean_name),
            ("Folder", redact_path(self.recomp.cheats_path)),
            ("File", data.get("raw_name", clean_name)),
            ("State", "Enabled" if data.get("enabled", True) else "Disabled"),
        ]
        self.details.card(rows, open_path=self.recomp.cheats_path)
        self.details.hint("Cheats are toggled in the Cheats section; "
                          "the recomp shows them in its settings menu.")

    def _show_recomp_file_details(self, key):
        self.details.clear()
        entry = None
        for candidate in self.recomp.patches + self.recomp.plugins:
            if (candidate["mod"], candidate["rel_path"]) == key:
                entry = candidate
                break
        if entry is None:
            self.details.heading("Details unavailable")
            self.details.hint("Re-scan the folder to refresh this entry.")
            return
        self.details.heading("File: %s" % entry["filename"])
        rows = [
            ("Mod", entry["mod"]),
            ("Relative path", entry["rel_path"]),
            ("Location", redact_path(entry["path"])),
            ("State", "Enabled" if entry["enabled"] else "Disabled"),
        ]
        if entry.get("ignored_by_recomp"):
            rows.append(("Note", "Not loaded by the recomp"))
        self.details.card(rows, open_path=os.path.dirname(entry["path"]))

    # tree
    def switch_view(self, mode):
        self.view_mode = mode
        self.list_button.setChecked(mode == "list")
        self.tree_button.setChecked(mode == "tree")
        if mode == "list":
            self.view_stack.setCurrentWidget(self.list_scroll)
        else:
            self.view_stack.setCurrentWidget(self.tree)
            if self.mode == "recomp":
                self.populate_recomp_tree()
            else:
                self.populate_mod_tree()

    def _build_emulator_tree_data(self):
        conflicts = self.emulator.conflicts
        mod_files = self.emulator.mod_files
        current_ids = self._order_ids()
        order_index = {name: i for i, name in enumerate(current_ids)}
        all_mod_ids = set(current_ids)

        file_status = {}
        for mod_id in current_ids:
            enabled = self._is_mod_enabled(mod_id)
            for rel_path in (mod_files.get(mod_id, set()) or set()):
                if rel_path not in file_status:
                    file_status[rel_path] = {
                        "mods": [], "enabled_mods": [], "disabled_mods": [],
                        "conflict": False, "enable_conflict": False,
                    }
                info = file_status[rel_path]
                info["mods"].append(mod_id)
                if enabled:
                    info["enabled_mods"].append(mod_id)
                else:
                    info["disabled_mods"].append(mod_id)
                # rivals for this path
                rivals = (conflicts.get(mod_id) or {}).get(rel_path) or ()
                if enabled and any(name in all_mod_ids and self._is_mod_enabled(name)
                                   for name in rivals):
                    info["conflict"] = True
                    info["enable_conflict"] = True

        enabled_ids = [m for m in current_ids if self._is_mod_enabled(m)]
        entries = []
        for rel_path, info in file_status.items():
            active = info["enabled_mods"]
            if not active:
                tag = "disabled"
                status = "Disabled (mod off)"
                winner = info["disabled_mods"][0] if info["disabled_mods"] else None
            elif info["enable_conflict"]:
                tag = "conflict"
                winner = min(active, key=lambda m: order_index.get(m, 10_000))
                status = "Load Order Conflict"
            else:
                tag = "safe"
                winner = active[0]
                status = "No conflict"
            entries.append({
                "file": rel_path,
                "tag": tag,
                "status": status,
                "winner": winner,
                "order": order_index.get(winner, 10_000),
            })
        entries.sort(key=lambda item: (FILE_TAG_PRIORITY.get(item["tag"], 9),
                                       item["file"].lower()))

        grouped = {}
        for entry in entries:
            grouped.setdefault(entry["tag"], []).append(entry)

        # one node per mod
        root_entries = []
        for mod_id in enabled_ids:
            children = [item for tag in ("conflict", "safe")
                        for item in grouped.get(tag, ()) if item["winner"] == mod_id]
            if not children:
                continue
            conflicts_n = sum(1 for item in children if item["tag"] == "conflict")
            files_n = len(children)
            status = "%d file%s" % (files_n, "" if files_n == 1 else "s")
            if conflicts_n:
                status = "%d files (%d conflicting)" % (files_n, conflicts_n)
            root_entries.append({
                "name": self.emulator.strip_prefix(mod_id),
                "mod": mod_id,
                "tag": "loaded",
                "status": status,
                "children": children,
            })
        orphans = [item for tag in ("conflict", "safe")
                   for item in grouped.get(tag, ()) if item["winner"] not in enabled_ids]
        for item in orphans:
            root_entries.append({
                "name": item["file"],
                "tag": item["tag"],
                "status": item["status"],
                "winner": item["winner"],
                "children": [],
            })

        disabled = grouped.get("disabled") or []
        if disabled:
            root_entries.append({
                "name": "Disabled Mods",
                "tag": "disabled",
                "status": "%d file%s" % (len(disabled),
                                         "" if len(disabled) == 1 else "s"),
                "children": disabled,
            })

        if self.mode == "eden":
            cheat_entries = [{
                "name": name if on else name + " (disabled)",
                "tag": "cheat" if on else "disabled",
                "status": "Cheat",
                "special": True,
                "children": [],
            } for name, on in self.emulator.cheat_states().items()]
        else:
            cheat_entries = [{
                "name": "%s (Ryujinx Enabled Cheats)" %
                        self.emulator.strip_prefix(
                            self.emulator.special_cheats_folder_name),
                "tag": "loaded",
                "status": "Special cheats",
                "children": [],
            }] if self.emulator.special_cheats_folder_name else []

            for mod_id in self.emulator.cheat_only_mods:
                if mod_id in current_ids:
                    cheat_entries.append({
                        "name": "%s (Cheat Only)" % self.emulator.strip_prefix(
                            mod_id),
                        "tag": "cheat",
                        "status": self.emulator.strip_prefix(mod_id),
                        "special": True,
                        "children": [],
                    })
        return root_entries + cheat_entries

    def populate_mod_tree(self):
        self.tree.clear_items()
        try:
            data = self._build_emulator_tree_data()
        except Exception:
            traceback.print_exc()
            return
        enabled_children = [d for d in data if not d.get("special")]
        numbers = self._load_numbers()
        for entry in data:
            special = entry.get("special")
            name = entry["name"]
            number = numbers.get(entry.get("mod"))
            if number is not None:
                name = "%d  %s" % (number, name)
            top = self.tree.add_item(None, name,
                                     "" if special else entry["status"],
                                     entry["tag"])
            for child in entry.get("children", []):
                self.tree.add_item(top, child["file"], child["status"],
                                   child["tag"])
            if entry["tag"] == "loaded" and entry["children"]:
                top.setExpanded(True)
            elif entry["tag"] == "disabled":
                top.setExpanded(False)
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.childCount() == 0:
                item.setExpanded(False)

    def populate_recomp_tree(self):
        self.tree.clear_items()
        analyzer = self.recomp
        view = self._recomp_conflict_view()
        index_of = self._recomp_order_index()

        numbers = self._load_numbers()
        for clean_name, data in analyzer.get_ordered_mods():
            if not data.get("has_romfs"):
                continue
            enabled = self.mod_enabled.get(clean_name, True)
            conflicts = view.get(clean_name, {})
            overridden = False
            overridden_by = False
            for rel_path, cell in conflicts.items():
                for other in cell["rivals"]:
                    if (index_of.get(other, 10_000)
                            > index_of.get(clean_name, 10_000)):
                        overridden = True
                    else:
                        overridden_by = True
            if not enabled:
                tag, status = "disabled", "Disabled"
            elif overridden:
                tag, status = "loser", "Overridden (a later mod wins)"
            elif overridden_by:
                tag, status = "winner", "Wins conflicts"
            else:
                tag, status = "loaded", "Loaded"
            name = clean_name
            if numbers.get(clean_name):
                name = "%d  %s" % (numbers[clean_name], name)
            top = self.tree.add_item(None, name, status, tag)
            for rel_path in sorted(conflicts)[:50]:
                cell = conflicts[rel_path]
                winner = self._recomp_latest(
                    [clean_name] + cell["rivals"], index_of)
                rel_item = self.tree.add_item(
                    top, rel_path, "vs " + ", ".join(cell["rivals"])[:40],
                    "winner" if winner == clean_name else "loser")
                for key, key_rivals in list(cell["entries"].items())[:6]:
                    if key is None or not key_rivals:
                        continue
                    key_winner = self._recomp_latest(
                        [clean_name] + key_rivals, index_of)
                    self.tree.add_item(
                        rel_item, "  " + self._entry_label(key),
                        ("you: " if key_winner == clean_name
                         else "%s: " % key_winner) + ", ".join(key_rivals)[:30],
                        "winner" if key_winner == clean_name else "loser")
            top.setExpanded(bool(conflicts))

        for entry in analyzer.plugins:
            tag = "loaded" if entry["enabled"] else "disabled"
            self.tree.add_item(None, "plugin: " + entry["filename"],
                               entry["mod"], tag)
        for entry in analyzer.patches:
            tag = "loaded" if entry["enabled"] else "disabled"
            self.tree.add_item(None, "patch: " + entry["filename"],
                               entry["mod"], tag)
        for clean_name in sorted(analyzer.cheats):
            enabled = analyzer.cheats[clean_name].get("enabled", True)
            self.tree.add_item(None, "cheat: " + clean_name,
                               "Enabled" if enabled else "Disabled",
                               "cheat" if enabled else "disabled")

    # importing
    def _on_paths_dropped(self, paths):
        if self.current_state == "working" or not paths:
            return
        self._install_mod_items(list(paths))

    def _install_mod_items(self, items):
        if not items:
            return
        if self.mode == "recomp":
            if not self.recomp.root_path:
                dialogs.error(self, "Install", "Select a Recomp folder first.")
                return
            root = self._get_current_path()
            ok, message, _suggested = self.recomp.structure_status(root)
            if not ok:
                dialogs.error(self, "Install", message)
                return
            target_dir = self.recomp.mods_path
        else:
            if not self.emulator.mods_path:
                dialogs.error(self, "Install", "Select a Mods folder first.")
                return
            target_dir = self.emulator.mods_path
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as exc:
            dialogs.error(self, "Install", "Cannot create mods folder:\n%s"
                          % redact_path(str(exc)))
            return

        jobs = []
        for item in items:
            item = item.strip().strip('"')
            if not os.path.exists(item):
                dialogs.error(self, "Install", "Path not found:\n%s"
                              % redact_path(item))
                continue
            base = os.path.basename(item.rstrip("\\/"))
            lower = base.lower()
            if os.path.isfile(item) and lower.endswith(".txt"):
                if self.mode == "recomp":
                    self._install_recomp_cheat_txt(item)
                elif self.mode == "eden":
                    self._install_eden_cheat_txt(item)
                else:
                    self.import_cheat_file(item)
                continue
            extension = os.path.splitext(base)[1].lower()
            if extension in (".zip", ".7z") and not PY7ZR_SUPPORT and \
                    extension == ".7z":
                dialogs.error(self, "Install",
                              "Install 'py7zr' to open .7z archives.")
                continue
            dest_name = base if os.path.isdir(item) else os.path.splitext(base)[0]
            if self.mode == "recomp":
                dest_name = re.sub(r"^\d+_", "", dest_name).strip()
                if not dest_name:
                    continue
                destination = os.path.join(target_dir, dest_name)
                replace = False
                if os.path.exists(destination):
                    if not dialogs.confirm(
                            self, "Mod Already Exists",
                            "'%s' already exists in mods/.\n\nOverwrite it?"
                            % dest_name):
                        continue
                    replace = True
                kind = ("zip" if extension == ".zip" else
                        "7z" if extension == ".7z" else "copy_tree")
                jobs.append({"kind": kind, "src": item, "dest": destination,
                             "label": dest_name, "replace": replace})
            else:
                staging = tempfile.mkdtemp(prefix="ds_drop_", dir=target_dir)
                self._install_staging.append(staging)
                kind = ("zip" if extension == ".zip" else
                        "7z" if extension == ".7z" else "copy_tree")
                jobs.append({"kind": kind, "src": item, "dest": staging,
                             "label": dest_name, "dest_name": dest_name,
                             "staging": staging})

        if not jobs:
            return
        self._install_target_dir = target_dir
        self._set_state("working")
        self.progress_header.setText("Installing Mods...")
        self.progress_detail.setText("Preparing...")
        self.progress_bar.setValue(0)
        worker = InstallWorker(jobs)
        run_worker(self, worker,
                   on_done=self._on_install_finished,
                   on_error=self._on_install_error,
                   on_progress=self._on_install_progress)

    def _on_install_progress(self, message):
        total = max(message.get("total", 1), 1)
        index = message.get("index", 1)
        self.progress_bar.setValue(int(index / total * 100))
        self.progress_detail.setText("Extracting %s (%d/%d)"
                                     % (message.get("text", ""), index, total))

    def _on_install_finished(self, payload):
        installed = 0
        for job in payload.get("done", []):
            staging = job.get("staging")
            if not staging:
                installed += 1
                continue
            if self._finalize_ryujinx_drop(staging, self._install_target_dir,
                                           job.get("dest_name", "")):
                installed += 1
        for staging in self._install_staging:
            shutil.rmtree(staging, ignore_errors=True)
        self._install_staging = []
        self._set_state("idle")
        errors = payload.get("errors") or []
        if errors:
            dialogs.error(self, "Install Failed", "\n\n".join(errors))
        if installed:
            self._status("Installed %d mod%s. Refreshing..."
                         % (installed, "" if installed == 1 else "s"))
            self.run_scan()
        elif not errors:
            self._status("Nothing was installed.")

    def _on_install_error(self, error_text):
        for staging in self._install_staging:
            shutil.rmtree(staging, ignore_errors=True)
        self._install_staging = []
        self._set_state("idle")
        dialogs.error(self, "Install Failed", error_text)

    def _finalize_ryujinx_drop(self, staging, target_dir, dest_name):
        # one folder per mod
        if not dest_name:
            dest_name = "Imported Mod"
        try:
            entries = [e for e in os.listdir(staging) if not e.startswith(".")]
        except OSError as exc:
            dialogs.error(self, "Install Failed", str(exc))
            return False
        source = staging
        if len(entries) == 1:
            candidate = os.path.join(staging, entries[0])
            if os.path.isdir(candidate) and \
                    entries[0].lower() not in self.CONTENT_DIRS:
                source = candidate
                dest_name = entries[0]
        destination = os.path.join(target_dir, dest_name)
        if os.path.exists(destination):
            if not dialogs.confirm(self, "Mod Already Exists",
                                   "'%s' already exists.\n\nOverwrite it?"
                                   % dest_name):
                return False
            try:
                if os.path.isdir(destination):
                    shutil.rmtree(destination)
                else:
                    os.remove(destination)
            except Exception as exc:
                dialogs.error(self, "Install Failed", str(exc))
                return False
        try:
            shutil.move(source, destination)
        except Exception as exc:
            dialogs.error(self, "Install Failed",
                          "Could not move the extracted mod into place:\n%s" % exc)
            return False
        return True

    def import_mods_popup(self):
        kind, items = dialogs.ImportModsDialog.ask(self)
        if kind is None or not items:
            return
        self._install_mod_items(items)

    # cheats
    def _parse_cheat_blocks(self, text):
        blocks = {}
        current = None
        buffer = []
        for line in str(text).splitlines():
            match = re.match(r"^\[([^\]]+)\]", line.strip())
            if match:
                if current is not None:
                    blocks[current] = "\n".join(buffer).strip()
                current = match.group(1).strip()
                buffer = [line]
            elif current is not None:
                buffer.append(line)
        if current is not None:
            blocks[current] = "\n".join(buffer).strip()
        return blocks

    def _merge_cheat_blocks(self, text, source_label, raw_mod_name, build_id=None):
        if not self.emulator.mods_path:
            dialogs.error(self, "Cheats", "Select a mods folder first.")
            return
        blocks = self._parse_cheat_blocks(text)
        if not blocks:
            dialogs.error(self, "Cheats",
                          "No '[Cheat Name]' blocks found in %s." % source_label)
            return
        if self.mode == "eden":
            self._write_eden_cheat_folders(blocks, source_label)
            return
        # ryujinx wants one build-id file
        target_dir = os.path.join(self.emulator.mods_path, "cheats")
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as exc:
            dialogs.error(self, "Cheats",
                          "Cannot create the cheats folder:\n%s" % exc)
            return

        build_id = build_id or self.emulator.preferred_cheat_build_id()
        path = os.path.join(target_dir, build_id + ".txt")
        text = ""
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    text = handle.read()
            except Exception as exc:
                dialogs.error(self, "Cheats", "Could not read %s:\n%s"
                              % (redact_path(path), redact_path(str(exc))))
                return

        written = 0
        for name, code in blocks.items():
            body = (code if code.lstrip().startswith("[")
                    else "[%s]\n%s" % (name, code)).strip("\r\n") + "\n"
            sections = self.emulator.cheat_sections(text)
            match = next((section for section in sections
                          if section[0] == name), None)
            if match:
                tail = text[match[2]:]
                text = (text[:match[1]] + body
                        + ("\n" if tail and not tail.startswith("\n") else "")
                        + tail)
            else:
                if text and not text.endswith("\n\n"):
                    text += "\n" if text.endswith("\n") else "\n\n"
                text += body
            written += 1
        try:
            atomic_write_text(path, text)
        except Exception as exc:
            dialogs.error(self, "Cheats", "Could not write %s:\n%s"
                          % (redact_path(path), redact_path(str(exc))))
            return
        self._status("Merged %d cheat entr%s into %s."
                     % (written, "y" if written == 1 else "ies",
                        os.path.join("cheats", build_id + ".txt")))
        self.run_scan()

    def import_cheat_popup(self):
        if self.mode == "recomp":
            dialogs.info(self, "Cheats",
                         "Recomp cheats are .txt files in the cheats/ folder. "
                         "Drop one onto the list to add it.")
            return
        if not self.emulator.mods_path:
            dialogs.error(self, "Cheats", "Select a mods folder first.")
            return
        name, body = dialogs.ImportCheatDialog.ask(self)
        if body is None:
            return
        if name and not re.match(r"^\[", body):
            body = "[%s]\n%s" % (name, body)
        folder = self.emulator.special_cheats_folder_name or "cheats"
        self._merge_cheat_blocks(body, "the paste box", folder)

    def import_cheat_file(self, path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                body = handle.read()
        except Exception as exc:
            dialogs.error(self, "Cheats", "Could not read %s:\n%s"
                          % (redact_path(path), redact_path(str(exc))))
            return
        folder = self.emulator.special_cheats_folder_name or "cheats"
        stem = os.path.splitext(os.path.basename(path))[0].upper()
        known = stem if self.emulator.CHEAT_ID_RE.match(stem) else None
        self._merge_cheat_blocks(body, os.path.basename(path), folder, known)

    def _install_eden_cheat_txt(self, path):
        # eden wants one folder per cheat
        if not self.emulator.mods_path:
            dialogs.error(self, "Cheats", "Select an Eden load folder first.")
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                body = handle.read()
        except Exception as exc:
            dialogs.error(self, "Cheats", "Could not read %s:\n%s"
                          % (redact_path(path), redact_path(str(exc))))
            return
        blocks = self._parse_cheat_blocks(body)
        if not blocks:
            dialogs.error(self, "Cheats",
                          "No '[Cheat Name]' blocks found in %s."
                          % os.path.basename(path))
            return
        self._write_eden_cheat_folders(blocks, os.path.basename(path),
                                      self._eden_build_id_from_name(
                                          os.path.basename(path)))

    @staticmethod
    def _eden_build_id_from_name(filename):
        # keep a build-id pack name
        stem = os.path.splitext(filename)[0]
        if re.fullmatch(r"[0-9A-Fa-f]{16}", stem):
            return stem.upper()
        if re.fullmatch(r"[0-9A-Fa-f]{32}", stem):
            return stem[:16].upper()
        return ""

    def _write_eden_cheat_folders(self, blocks, source_label, build_id=""):
        build_id = build_id or self.emulator.CHEAT_BUILD_ID
        written = 0
        for name, code in blocks.items():
            safe = re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "Cheat"
            folder = os.path.join(self.emulator.mods_path, safe,
                                  self.emulator.CHEATS_FOLDER)
            path = os.path.join(folder, build_id + ".txt")
            if os.path.exists(path):
                if not dialogs.confirm(
                        self, "Cheat Exists",
                        "Cheat '%s' already exists.\n\nOverwrite it?" % safe):
                    continue
            try:
                os.makedirs(folder, exist_ok=True)
                atomic_write_text(path, code + "\n")
                written += 1
            except Exception as exc:
                dialogs.error(self, "Cheats", "Could not write '%s':\n%s"
                              % (safe, redact_path(str(exc))))
                return
        self._status("Imported %d cheat%s from %s into Eden cheat folders."
                     % (written, "" if written == 1 else "s", source_label))
        self.run_scan()

    def _install_recomp_cheat_txt(self, path):
        if not self.recomp.root_path:
            dialogs.error(self, "Cheats", "Select a Recomp folder first.")
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                content = handle.read()
        except Exception as exc:
            dialogs.error(self, "Cheats", "Could not read %s:\n%s"
                          % (redact_path(path), redact_path(str(exc))))
            return
        name = os.path.basename(path)
        if name.startswith("_"):
            name = name[1:]
        target = os.path.join(self.recomp.cheats_path, name)
        if os.path.exists(target) and not dialogs.confirm(
                self, "Cheat Exists", "'%s' already exists.\n\nOverwrite it?" % name):
            return
        try:
            os.makedirs(self.recomp.cheats_path, exist_ok=True)
            atomic_write_text(target, content)
        except Exception as exc:
            dialogs.error(self, "Cheats", "Could not write '%s':\n%s"
                          % (name, redact_path(str(exc))))
            return
        self._status("Cheat '%s' installed. Refreshing..." % name)
        self.run_scan()

    def clear_all_cheats(self):
        if self.mode == "eden":
            if not self.eden_cheat_rows:
                self._status("No cheats loaded.")
                return
            if not dialogs.confirm(self, "Disable All",
                                   "Disable every cheat?\n\n"
                                   "Click 'Apply New Order' to save."):
                return
            for row in self.eden_cheat_rows.values():
                row.checkbox.setChecked(False)
            self._status("All cheats disabled. Click 'Apply New Order' to save.")
            return
        if self.mode == "recomp":
            if not self.recomp.cheats:
                self._status("No cheats loaded.")
                return
            if not dialogs.confirm(self, "Disable All",
                                   "Disable every cheat?\n\n"
                                   "Click 'Apply New Order' to save."):
                return
            for row in self.cheat_rows.values():
                row.checkbox.setChecked(False)
            self._status("All cheats disabled. Click 'Apply New Order' to save.")
            return
        if not self.cheat_files_model:
            self._status("No cheat files loaded.")
            return
        if not dialogs.confirm(self, "Disable All",
                               "Disable all cheat entries?\n\nClears pending "
                               "selections. You must click 'Apply New Order' "
                               "to save."):
            return
        self._load_cheat_model()
        for states in self.pending_cheat_selections.values():
            for key in states:
                states[key] = False
        if self.current_details_mod in self.emulator.cheat_only_mods:
            self.show_details(self.current_details_mod)
        self._status("All cheats cleared. Click 'Apply New Order' to save.")

    def _load_cheat_model(self, keep_states=False):
        # re-read the model, ticks beside it
        self.cheat_files_model = self.emulator.discover_cheat_files()
        enabled = self.emulator.cheat_enabled_keys()
        self._enabled_cheat_names = enabled
        old = self.pending_cheat_selections if keep_states else {}
        pending = {}
        for entry in self.cheat_files_model:
            previous = old.get(entry["path"], {})
            states = {}
            for item in entry["entries"]:
                states[item["key"]] = previous.get(item["key"],
                                                   item["key"] in enabled)
            if states:
                pending[entry["path"]] = states
        self.pending_cheat_selections = pending

    def _initialize_pending_cheats(self):
        if self.mode == "eden":
            # eden: the scan is the truth
            self.pending_cheat_selections = {}
            self._enabled_cheat_names = set()
            self.eden_cheat_states = self.emulator.cheat_states()
            return
        self._load_cheat_model()

    def preview_enabled_cheats_popup(self):
        if self.mode == "eden":
            states = self.eden_cheat_states or self.emulator.cheat_states()
            if not states:
                dialogs.info(self, "No Cheats", "No cheats installed.")
                return
            lines = ["%s  %s" % ("on " if on else "off", name)
                     for name, on in sorted(states.items())]
            dialogs.CheatCodeDialog.view(
                self, "Eden cheats",
                "\n".join(lines) + "\n\nBits are moved into disabled_cheats/"
                " as you untick them, then applied.")
            return
        if not self.emulator.mods_path:
            dialogs.info(self, "No Cheats", "No mods folder selected.")
            return
        path = self.emulator.cheat_enabled_path()
        if not os.path.isfile(path):
            dialogs.info(self, "No enabled.txt",
                         "enabled.txt has not been written yet.\n\n"
                         "Tick cheats, then click Apply New Order.")
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                content = handle.read()
        except Exception as exc:
            dialogs.error(self, "Read Failed", str(exc))
            return
        dialogs.CheatCodeDialog.view(self, "enabled.txt", content or "(empty)")

    def clear_all_mods(self):
        if not self.mod_rows:
            self._status("No mods loaded.")
            return
        if not dialogs.confirm(self, "Disable All",
                               "Disable all mods except the cheats folder?\n\n"
                               "You must click 'Apply New Order' to save."):
            return
        count = 0
        for mod_id, row in self.mod_rows.items():
            if row.checkbox is None:
                continue
            if self.mode == "ryujinx" and mod_id in self.emulator.cheat_only_mods:
                continue
            self._set_mod_enabled(mod_id, False)
            count += 1
        self._after_order_change("Disabled %d mod%s. Click 'Apply New Order'."
                                 % (count, "" if count == 1 else "s"))

    # apply
    def apply_changes(self):
        if self.current_state == "working" or self._scanning:
            return
        if self.mode == "recomp":
            self._apply_changes_recomp()
        else:
            self._apply_changes_emulator()

    def _apply_changes_emulator(self):
        if not self.emulator.mods_path:
            dialogs.error(self, "Error", "No mods folder selected.")
            return
        if not self._scanned_path_matches_entry():
            dialogs.error(self, "Folder Changed",
                          "The folder in the path box is not the one that was "
                          "scanned.\n\nClick Scan to load it before applying "
                          "changes.")
            return
        ok, message, _suggested = self.emulator.structure_status()
        if not ok:
            dialogs.error(self, "Invalid Folder", message)
            return

        config = {}
        for mod_id in self._order_ids():
            config[mod_id] = self._is_mod_enabled(mod_id)

        cheat_states = self.pending_cheat_selections
        if self.mode == "eden":
            # one reserved key
            cheat_states = {
                self.emulator.CHEAT_STATE_KEY: dict(self.eden_cheat_states)
            }

        live_conflicts = self._live_conflict_mod_ids()
        if live_conflicts:
            sample = "\n".join("  \u2022 " + name for name in
                               sorted(live_conflicts)[:10])
            rule = ("Later mods win." if self._conflict_later_wins()
                    else "Earlier mods win.")
            if not dialogs.confirm(
                    self, "Confirm Apply",
                    "Some mods share files. %s\n\n%s\n\n"
                    "Apply the new load order now?" % (rule, sample)):
                return

        self.progress_header.setText("Applying Load Order...")
        self._set_state("working")
        self.progress_bar.setValue(0)
        self.progress_detail.setText("Initializing...")
        self._apply_reported = False
        bridge = QueueBridge(self)
        bridge.message.connect(self._on_apply_message)
        self._apply_bridge = bridge
        run_in_thread(self, self.emulator.apply_new_order_threaded,
                      config, cheat_states, bridge,
                      on_done=self._on_apply_thread_done,
                      on_error=self._on_apply_thread_error)

    def _apply_changes_recomp(self):
        if not self.recomp.root_path:
            dialogs.error(self, "Error", "No recomp root selected.")
            return
        if not self._scanned_path_matches_entry():
            dialogs.error(self, "Folder Changed",
                          "The folder in the path box is not the one that was "
                          "scanned.\n\nClick Scan to load it before applying "
                          "changes.")
            return
        ok, message, _suggested = self.recomp.structure_status()
        if not ok:
            dialogs.error(self, "Invalid Folder", message)
            return

        ordered_mods = list(self._recomp_order_ids())
        mod_enabled = {name: self._is_mod_enabled(name) for name in ordered_mods}
        cheat_states = {name: row.checkbox.isChecked()
                        for name, row in self.cheat_rows.items()
                        if row.checkbox is not None}
        patch_states = {key: row.checkbox.isChecked()
                        for key, row in self.patch_rows.items()
                        if row.checkbox is not None}
        plugin_states = {key: row.checkbox.isChecked()
                         for key, row in self.plugin_rows.items()
                         if row.checkbox is not None}

        enabled_mods = sum(1 for value in mod_enabled.values() if value)
        disabled_mods = len(mod_enabled) - enabled_mods
        enabled_cheats = sum(1 for value in cheat_states.values() if value)
        enabled_patches = sum(1 for value in patch_states.values() if value)
        enabled_plugins = sum(1 for value in plugin_states.values() if value)

        if not dialogs.confirm(
                self, "Confirm Apply",
                ("Apply changes to MHGU Recomp?\n\n"
                 "Enabled mods: %d (disabled: %d)\n"
                 "Enabled cheats: %d\n"
                 "Enabled patches: %d\n"
                 "Enabled plugins: %d\n\n"
                 "This will:\n"
                 "  \u2022 write mods/load_order.txt (native settings-menu format)\n"
                 "  \u2022 rename cheat .txt files with '_' to match their state\n"
                 "  \u2022 move patches/plugins into/out of a 'disabled/' subfolder\n"
                 "  \u2022 migrate any old mods_disabled/ folder back into mods/\n\n"
                 "No mod folder is renamed. Restart MHGU Recomp to apply."
                 % (enabled_mods, disabled_mods, enabled_cheats,
                    enabled_patches, enabled_plugins))
                + self._recomp_conflict_warning()):
            return

        self.progress_header.setText("Applying Recomp Changes...")
        self._set_state("working")
        self.progress_bar.setValue(0)
        self.progress_detail.setText("Initializing...")
        self._apply_reported = False
        bridge = QueueBridge(self)
        bridge.message.connect(self._on_apply_message)
        self._apply_bridge = bridge
        run_in_thread(self, self.recomp.apply_changes_threaded,
                      ordered_mods, mod_enabled, cheat_states, patch_states,
                      plugin_states, bridge,
                      on_done=self._on_apply_thread_done,
                      on_error=self._on_apply_thread_error)

    def _on_apply_message(self, message):
        if not isinstance(message, dict):
            return
        kind = message.get("type")
        if kind == "progress":
            value = float(message.get("value", 0) or 0)
            percent = value * 100 if value <= 1.0 else value
            self.progress_bar.setValue(int(max(0, min(100, percent))))
            text = message.get("text")
            if text:
                self.progress_detail.setText(text)
        elif kind == "status":
            text = message.get("text", "")
            if text:
                self.progress_detail.setText(text)
        elif kind == "error":
            self._apply_reported = True
            self._set_state("idle")
            dialogs.error(self, "Apply Failed", message.get("message", ""))
            self._status("Apply failed. Rescanning...")
            QTimer.singleShot(300, self.run_scan)
        elif kind == "done":
            self._apply_reported = True
            self._set_state("idle")
            dialogs.info(self, "Apply Complete",
                         message.get("message") or "Changes applied.")
            self._status("Changes applied. Rescanning...")
            QTimer.singleShot(300, self.run_scan)

    def _on_apply_thread_done(self, _result):
        if self._apply_reported:
            return
        self._apply_reported = True
        self._set_state("idle")
        dialogs.error(self, "Apply Failed",
                      "The apply operation stopped without reporting completion.\n\n"
                      "The load order may be partially applied. Rescan and try again.")
        QTimer.singleShot(300, self.run_scan)

    def _on_apply_thread_error(self, error_text):
        self._apply_reported = True
        self._set_state("idle")
        dialogs.error(self, "Apply Failed",
                      "Unexpected error while applying changes:\n\n%s" % error_text)
        QTimer.singleShot(300, self.run_scan)

    # launching
    def launch_game(self):
        if self.mode == "eden":
            dialogs.info(self, "Launch",
                         "dreamSort does not start Eden for you. Open Eden "
                         "yourself, then launch the game from its menu.")
            return
        if self.mode == "recomp":
            self._launch_recomp()
        else:
            self._launch_ryujinx()

    def _launch_recomp(self):
        exe = self.recomp_exe_path
        if not exe or not os.path.exists(exe):
            start_dir = self.recomp.root_path or (
                self._get_current_path() if self._get_current_path() else "")
            exe = dialogs.pick_open_file(
                self, "Select MHGU Recomp executable", "*.exe *.app")
            if not exe:
                return
            if not os.path.isabs(exe):
                exe = os.path.join(start_dir, exe)
            self.recomp_exe_path = exe
            self.save_config()
        try:
            launch_recomp(exe)
        except Exception as exc:
            dialogs.error(self, "Launch Failed", str(exc))
            return
        if not self._scanned_path_matches_entry():
            self.run_scan()

    def _launch_ryujinx(self):
        exe = self.ryujinx_exe_path
        game = self.game_file_path
        need_exe = not exe or not os.path.exists(exe)
        need_game = not game or not os.path.exists(game)
        if need_exe:
            exe = dialogs.pick_open_file(self, "Select Ryujinx executable",
                                         "*.exe *.app")
            if not exe:
                return
            self.ryujinx_exe_path = exe
        if need_game:
            game = dialogs.pick_open_file(
                self, "Select game file", "NSP (*.nsp);;XCI (*.xci);;All (*.*)")
            if not game:
                return
            self.game_file_path = game
        self.save_config()
        try:
            launch_ryujinx(exe, game)
        except Exception as exc:
            dialogs.error(self, "Launch Failed", str(exc))

    # searching
    def select_folder(self):
        title = ("Select MHGU Recomp folder" if self.mode == "recomp"
                 else "Select Ryujinx Mods folder")
        current = self._get_current_path() or ""
        start = current if os.path.isdir(current) else ""
        folder = dialogs.pick_directory(self, title, start)
        if not folder:
            return
        self._update_path_display(folder)
        self.run_scan()

    def open_mod_directory(self):
        folder = (self.recomp.root_path if self.mode == "recomp"
                  else self.emulator.mods_path)
        if folder and os.path.isdir(folder):
            open_in_file_explorer(folder)
        else:
            dialogs.warn(self, "Not Found", "No folder loaded yet.")

    def _auto_find_ryujinx_mods(self):
        if self.mode == "eden":
            self._auto_find_eden_mods()
            return
        title_ids = [getattr(self.emulator, "TITLE_ID", ""), "0100C8B019756000"]

        def collect(roots):
            found = []
            for root in roots:
                if not root or not os.path.isdir(root):
                    continue
                candidates = [
                    os.path.join(root, "mods", "contents", tid)
                    for tid in title_ids if tid
                ]
                candidates.append(os.path.join(root, "mods", "contents"))
                for candidate in candidates:
                    if not os.path.isdir(candidate):
                        continue
                    if candidate.lower().endswith("contents"):
                        try:
                            for child in os.listdir(candidate):
                                sub = os.path.join(candidate, child)
                                if os.path.isdir(sub):
                                    found.append(sub)
                        except OSError:
                            continue
                    else:
                        found.append(candidate)
            return found

        if self.ryujinx_exe_path:
            roots = [os.path.dirname(self.ryujinx_exe_path)]
            if os.path.basename(self.ryujinx_exe_path).lower() == "ryujinx.app":
                roots.append(os.path.dirname(os.path.dirname(self.ryujinx_exe_path)))
            found = collect(roots)
            if found:
                self._update_path_display(found[0])
                self.run_scan()
                return

        launched_dir = ""
        found = collect([launched_dir]) if launched_dir else []

        home = os.path.expanduser("~")
        roots = [
            os.path.join(home, "AppData", "Roaming", "Ryujinx"),
            os.path.join(home, ".config", "Ryujinx"),
            os.path.join(home, "Library", "Application Support", "Ryujinx"),
            os.environ.get("RYUJINX_DATA_DIR", ""),
        ]
        found = collect(roots)
        if not found:
            self._status("Auto-find failed: set Ryujinx path manually.")
            dialogs.warn(self, "Not Found",
                         "Could not find a Ryujinx mods folder.\n\n"
                         "Select it manually with the folder button.")
            return
        unique = []
        for path in found:
            if path not in unique:
                unique.append(path)
        if len(unique) == 1:
            self._update_path_display(unique[0])
            self.run_scan()
            return
        chosen = dialogs.FolderPickerDialog.ask(self, unique)
        if chosen:
            self._update_path_display(chosen)
            self.run_scan()

    def _auto_find_eden_mods(self):
        # portable copy is picked by hand
        title = getattr(self.emulator, "TITLE_ID", "")
        home = os.path.expanduser("~")
        roots = [
            os.path.join(home, "AppData", "Roaming", "eden"),
            os.path.join(home, ".local", "share", "eden"),
            os.path.join(home, "Library", "Application Support", "eden"),
        ]
        found = []
        for root in roots:
            for candidate in (os.path.join(root, "load", title),
                              os.path.join(root, "user", "load", title)):
                if os.path.isdir(candidate) and candidate not in found:
                    found.append(candidate)
            load_dir = os.path.join(root, "load")
            if os.path.isdir(load_dir):
                for child in sorted(os.listdir(load_dir)):
                    sub = os.path.join(load_dir, child)
                    if os.path.isdir(sub) and sub not in found:
                        found.append(sub)
        if not found:
            self._status("Auto-find failed: set the Eden load folder manually.")
            dialogs.warn(self, "Not Found",
                         "Could not find an Eden load folder.\n\n"
                         "The installed copy is searched in AppData; a portable "
                         "copy sits in <eden folder>\\user\\load\\. Select that "
                         "one manually with the folder button.")
            return
        if len(found) == 1:
            self._update_path_display(found[0])
            self.run_scan()
            return
        chosen = dialogs.FolderPickerDialog.ask(self, found)
        if chosen:
            self._update_path_display(chosen)
            self.run_scan()

    # profiles
    def _refresh_profile_menu(self):
        names = sorted(self.profiles.keys(), key=lambda n: n.lower())
        current = self.profile_combo.currentText()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("(no profile)")
        for name in names:
            self.profile_combo.addItem(name)
        index = self.profile_combo.findText(current)
        self.profile_combo.setCurrentIndex(index if index >= 0 else 0)
        self.profile_combo.blockSignals(False)

    def _show_profile_menu(self):
        menu = QMenu(self)
        menu.addAction("Save current layout...", self.save_profile)
        current = self.profile_combo.currentText()
        if current and current != "(no profile)":
            menu.addAction("Load '%s'" % current, lambda: self.load_profile(current))
            menu.addAction("Delete '%s'" % current,
                           lambda: self.delete_profile(current))
        menu.addSeparator()
        menu.addAction("Export profiles...", self.export_profiles)
        menu.addAction("Import profiles...", self.import_profiles)
        menu.exec(self.profile_btn.mapToGlobal(
            self.profile_btn.rect().bottomLeft()))

    def _on_profile_selected(self, _index):
        name = self.profile_combo.currentText()
        if name and name != "(no profile)" and name in self.profiles:
            self.load_profile(name, refresh_combo=False)

    def _layout_snapshot(self):
        container = self._reorder_container()
        if container is None:
            return {}
        return {mod_id: self._is_mod_enabled(mod_id)
                for mod_id in container.order_ids()}

    def save_profile(self):
        if self._reorder_container() is None:
            self._status("Scan a folder before saving a profile.")
            return
        default = (self.profile_combo.currentText()
                   if self.profile_combo.currentText() != "(no profile)" else "My profile")
        name = dialogs.ask_text(self, "Save Profile", "Profile name:", default)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        self.profiles[name] = self._layout_snapshot()
        self.save_config()
        self._refresh_profile_menu()
        self.profile_combo.setCurrentText(name)
        self._status("Profile '%s' saved." % name)

    def load_profile(self, name, refresh_combo=True):
        profile = self.profiles.get(name)
        if not profile:
            self._status("Profile '%s' not found." % name)
            return
        container = self._reorder_container()
        if container is None:
            self._status("Scan a folder before loading a profile.")
            return
        known = set(container.order_ids())
        order = [mod_id for mod_id in profile.keys() if mod_id in known]
        if order:
            container.reorder_to(order)
        for mod_id, enabled in profile.items():
            if mod_id in known:
                self._set_mod_enabled(mod_id, bool(enabled), emit=False)
        self._after_order_change("Profile '%s' loaded. Click 'Apply New Order' "
                                 "to save." % name)
        if refresh_combo:
            index = self.profile_combo.findText(name)
            if index >= 0:
                self.profile_combo.blockSignals(True)
                self.profile_combo.setCurrentIndex(index)
                self.profile_combo.blockSignals(False)

    def delete_profile(self, name):
        if name not in self.profiles:
            return
        if not dialogs.confirm(self, "Delete Profile",
                               "Delete profile '%s'?" % name):
            return
        self.profiles.pop(name, None)
        self.save_config()
        self._refresh_profile_menu()
        self._status("Profile '%s' deleted." % name)

    def export_profiles(self):
        if not self.profiles:
            self._status("No profiles to export.")
            return
        path = dialogs.pick_save_file(self, "Export Profiles",
                                      "dreamsort_profiles.json",
                                      "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"profiles": self.profiles}, handle, indent=2)
        except Exception as exc:
            dialogs.error(self, "Export Failed", str(exc))
            return
        self._status("Profiles exported to %s" % redact_path(path))

    def import_profiles(self):
        path = dialogs.pick_open_file(self, "Import Profiles", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            dialogs.error(self, "Import Failed", str(exc))
            return
        profiles = payload.get("profiles") if isinstance(payload, dict) else None
        if not isinstance(profiles, dict):
            dialogs.error(self, "Import Failed",
                          "That file does not contain dreamSort profiles.")
            return
        self.profiles.update({str(k): dict(v) for k, v in profiles.items()
                              if isinstance(v, dict)})
        self.save_config()
        self._refresh_profile_menu()
        self._status("Imported %d profile(s)." % len(profiles))

    # chrome
    def _status(self, text):
        self.status_label.setText(text)

    def _set_state(self, state):
        # idle or working
        self.current_state = state
        if state == "working":
            self.stack.setCurrentWidget(self.overlay_page)
        else:
            self.stack.setCurrentWidget(self.main_page)
            self.progress_bar.setValue(0)

    def set_ui_state(self, state):
        self._set_state(state)

    def _on_splitter_moved(self, _pos, _index):
        # only a real drag counts
        self._splitter_user_set = True
        self._save_timer.start(500)

    def apply_splitter_layout(self):
        # middle, or a saved ratio
        width = self.splitter.width()
        if width <= 0:
            return
        usable = width - self.splitter.handleWidth()
        if self._splitter_user_set and self._splitter_sizes:
            total = sum(self._splitter_sizes) or 1
            left = int(round(usable * self._splitter_sizes[0] / total))
            self.splitter.setSizes([left, usable - left])
        else:
            self.splitter.setSizes([usable // 2, usable - usable // 2])

    def showEvent(self, event):
        super().showEvent(event)
        if not self._splitter_centered:
            self._splitter_centered = True
            # wait for the layout pass
            QTimer.singleShot(0, self.apply_splitter_layout)

    def shutdown(self, timeout_ms=5000):
        # join threads before teardown
        self._closing = True
        self._scanning = False
        remaining = []
        for thread, worker in list(getattr(self, "_active_threads", [])):
            try:
                thread.quit()
                finished = thread.wait(timeout_ms)
            except RuntimeError:
                finished = True
            if not finished:
                remaining.append((thread, worker))
        self._active_threads = remaining
        return not remaining

    def closeEvent(self, event):
        # scan may still be running
        if not self.shutdown():
            self._status("A background job is still finishing. Try closing again.")
            event.ignore()
            return
        try:
            self.save_config()
        except Exception:
            pass
        super().closeEvent(event)

    # utilities
    @staticmethod
    def _format_size(num_bytes):
        size = float(num_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return "%.1f %s" % (size, unit)
            size /= 1024
        return "%.1f GB" % size

    def _dir_stats(self, path):
        # fallback sizes, cached
        cached = self._dir_stats_cache.get(path)
        if cached is not None:
            return cached
        total = 0
        count = 0
        for root, _dirs, files in os.walk(path):
            for filename in files:
                try:
                    total += os.path.getsize(os.path.join(root, filename))
                    count += 1
                except OSError:
                    continue
        self._dir_stats_cache[path] = (count, total)
        return count, total

    @staticmethod
    def _read_mod_metadata(path):
        # read mod metadata
        for name in ("info.ini", "Info.ini", "mod.ini", "README.txt"):
            candidate = os.path.join(path, name)
            if not os.path.isfile(candidate):
                continue
            try:
                with open(candidate, "r", encoding="utf-8", errors="replace") as handle:
                    return handle.read()
            except Exception:
                return ""
        return ""


class MainWindow(QMainWindow):
    # window shell

    def __init__(self):
        super().__init__()
        self.setWindowTitle("dreamSort \u2014 Mod Manager %s" % VERSION)
        self._apply_icon()
        self._startup_centered = False
        self._startup_area = None

        self.container = QWidget(self)
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(0)
        self.setCentralWidget(self.container)

        config = read_config()
        mode = config.get("mode", "ryujinx")
        if not config.get("remember_mode") or mode not in ("ryujinx", "recomp"):
            mode = "ryujinx"
        self._orphaned_views = []
        self.view = None
        self._build_view(mode)

        self._apply_startup_geometry()

        self._build_menus()

        # startup prompts
        self._startup_timer = QTimer(self)
        self._startup_timer.setSingleShot(True)
        self._startup_timer.timeout.connect(self._maybe_prompt_startup)
        self._startup_timer.start(250)

    # window frame
    def _startup_screen(self):
        # screen under the cursor
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        return screen

    def _apply_startup_geometry(self):
        """Open on the screen under the cursor."""
        screen = self._startup_screen()
        area = screen.availableGeometry() if screen else None
        if area is None or not area.isValid():
            self.resize(1280, 800)
            return
        self._startup_area = area
        width = min(1600, max(900, int(area.width() * 0.8)),
                    area.width() - 40)
        height = min(900, max(600, int(area.height() * 0.8)),
                     area.height() - 40)
        self.resize(width, height)
        self.setMinimumSize(min(1000, width), min(640, height))
        self._center_on_area(area)

    def _center_on_area(self, area):
        frame = self.frameGeometry()
        frame.moveCenter(area.center())
        # clamp to the usable desktop
        frame.moveLeft(max(area.left(),
                           min(frame.left(), area.right() - frame.width() + 1)))
        frame.moveTop(max(area.top(),
                          min(frame.top(), area.bottom() - frame.height() + 1)))
        self.move(frame.topLeft())

    def showEvent(self, event):
        super().showEvent(event)
        # redo it once the margins are known
        if not self._startup_centered and self._startup_area is not None:
            self._startup_centered = True
            self._center_on_area(self._startup_area)

    # chrome
    def _apply_icon(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        for candidate in (os.path.join(here, "icon.ico"),
                          os.path.join(here, "icon.png")):
            if os.path.exists(candidate):
                self.setWindowIcon(QIcon(candidate))
                return

    def _build_menus(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("File")
        switch = QAction("Switch Mode...", self)
        switch.triggered.connect(self.prompt_mode_switch)
        file_menu.addAction(switch)

        save = QAction("Save Config", self)
        save.triggered.connect(self._save_app_config)
        file_menu.addAction(save)

        file_menu.addSeparator()
        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = menu_bar.addMenu("Help")
        about = QAction("About dreamSort", self)
        about.triggered.connect(lambda: dialogs.show_about(self))
        help_menu.addAction(about)

    def _build_view(self, mode):
        old = self.view
        if old is not None:
            old.setParent(None)
            old.hide()
            if old.shutdown(5000):
                old.deleteLater()
            else:
                # keep the object alive
                # TODO: never pruned
                self._orphaned_views.append(old)
        self.view = DreamSortView(mode, self.container)
        self.container_layout.addWidget(self.view)

    def _save_app_config(self):
        if self.view is not None:
            self.view.save_config()
        dialogs.info(self, "Saved", "Settings written to:\n%s"
                     % redact_path(config_path()))

    def _maybe_prompt_startup(self):
        if not self.isVisible():
            return
        from ..storage.config import CONFIG_NOTICES
        if CONFIG_NOTICES:
            dialogs.show_config_notices(self, list(CONFIG_NOTICES))
            CONFIG_NOTICES.clear()
        config = read_config()
        if config.get("remember_mode"):
            return
        self.prompt_mode_switch()

    def prompt_mode_switch(self):
        if self.view is None:
            return
        config = read_config()
        remember = bool(config.get("remember_mode", False))
        mode, remember_now = dialogs.ModeSelectorDialog.ask(
            self, self.view.mode, remember)
        if mode is None:
            return
        self.view.remember_mode = remember_now
        config = read_config()
        config["mode"] = mode
        config["remember_mode"] = remember_now
        write_config(config)
        if mode != self.view.mode:
            self._build_view(mode)

    def closeEvent(self, event):
        timer = getattr(self, "_startup_timer", None)
        if timer is not None:
            timer.stop()
        if self.view is not None:
            try:
                self.view.save_config()
            except Exception:
                pass
            try:
                self.view.shutdown(30000)
            except Exception:
                pass
        for view in getattr(self, "_orphaned_views", []):
            try:
                view.shutdown(30000)
            except Exception:
                pass
        super().closeEvent(event)
