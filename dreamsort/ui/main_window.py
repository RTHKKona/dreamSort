# main window

import json
import os
import re
import shutil
import sys
import tempfile
import threading
import traceback
import webbrowser

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFrame, QGraphicsDropShadowEffect,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget, QApplication,
)
from .. import app_logging
from .. import packs
from ..analyzers import eden_config
from ..analyzers import game_version
from ..analyzers import recomp_log
from ..analyzers import trimmed as trimmed_arcs
from ..analyzers import EdenAnalyzer, RecompAnalyzer, RyujinxAnalyzer
from ..constants import Colors, VERSION
from ..gamebanana.client import GameBananaClient
from ..gamebanana.links import build_record, read_record, write_record
from ..gamebanana import profiles as gb_profiles
from ..gamebanana.service import GameBananaService
from ..gamebanana.policy import mode_for_profile
from ..gamebanana.updater import Updater
from ..gamebanana.updates import known_ids_for, pick_installable_file
from ..gamebanana.urls import page_url, parse_link
from ..github import records as github_records
from ..github.client import GitHubClient, GitHubError
from ..github.service import GitHubUpdates
from ..github.updates import pick_asset as pick_github_asset
from ..github.urls import parse_repo
from ..rules import manifest as rules_manifest
from ..rules import resolver as rules_resolver
from ..rules import store as rules_store
from ..rules.model import ModRules, clean_folder
from ..rules.versions import satisfies
from ..helpers.files import is_process_running, open_in_file_explorer
from ..install.commit import STAGING_PREFIX, recover_interrupted, sweep_dir
from ..launchers import launch_eden, launch_recomp, launch_ryujinx
from ..launchers import exit_codes
from ..launchers.process_watcher import ProcessWatcher
from ..redact import expand_path, redact_path, unredact_path
from ..workers import autofind as autofind_job
from .ini_editor import IniEditorDialog, plugin_ini_names, save_dir as plugin_save_dir
from .progress_dialog import AutoFindProgressDialog

# dependency names arrive as manifest ids, folder names, or plugin file names
_DEP_SUFFIXES = (".nro", ".arc", ".nsp", ".xci", ".kip", ".elf", ".nso", ".pchtxt")
_DEP_VERSION = re.compile(r"[-_\s]?[\[(]\s*v?\d[\w.\- ]*[\])]\s*$|v\d+(?:\.\d+)?$"
                          r"|[-_\s]\d+(?:\.\d+)+$", re.I)


def dep_key(text):
    # author/name, folder or file name -> one comparison key
    value = str(text or "").strip().lower().replace("\\", "/").rsplit("/", 1)[-1]
    for suffix in _DEP_SUFFIXES:
        if value.endswith(suffix):
            value = value[:-len(suffix)]
            break
    value = clean_folder(value)
    value = _DEP_VERSION.sub("", value)
    return re.sub(r"[^a-z0-9]", "", value)
from ..security import scan_paths
from ..storage import atomic_write_text, config_path, read_config, write_config
from ..workers import InstallWorker, PY7ZR_SUPPORT, QueueBridge, run_in_thread, run_worker
from . import dialogs
from .details_panel import (
    ACTION, ChipCell, ClickLabel, DetailsPanel, LocationRow, SheetRow,
    middle_ellipsis, page_link, wrap_path_text,
)
from .download_panel import DownloadsDialog, DownloadQueuePanel
from .dnd import MOD_ROW_MIME
from .icons import action_icon, set_icon
from .mod_list import ModListWidget, ModScrollArea
from .mod_row import CheckMark, ChildRow, FileRow, ModRow
from .popup_button import PopupButton
from .profile_dialog import ModProfilesDialog
from .sections import CollapsibleSection
from .theme import apply_theme, high_contrast
from .tree_view import ConflictTree

FILE_TAG_PRIORITY = {"conflict": 0, "enable_conflict": 1, "override": 2, "safe": 3}

# a dependency chip's mark follows its status colour
DEP_MARKS = {Colors.CONFLICT: "\u2715", Colors.DRAG_HIGHLIGHT: "\u26a0"}


def dep_note(text):
    # "0.33.0 \u2713" -> "0.33.0 installed"; plain states stay as they are
    body = re.sub(r"\s*[\u2713\u2715\u26a0]", "", text).strip()
    head, _sep, rest = body.partition(" ")
    if not head[:1].isdigit():
        return body
    note = head + " installed"
    if rest and not rest.startswith("needs"):
        rest = "satisfies " + rest
    return note + (" \u00b7 " + rest if rest else "")


class DreamSortView(QWidget):
    # one mode's ui

    def __init__(self, mode="ryujinx", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.emulator = (EdenAnalyzer() if mode == "eden" else RyujinxAnalyzer())
        self.recomp = RecompAnalyzer()

        # state
        self.pending_cheat_selections = {}
        self.cheat_files_model = []   # cheat files
        self._dir_stats_cache = {}    # sizes
        self._rules_cache = {}        # mod_id -> ModRules
        self._manifest_cache = {}     # mod_id -> raw manifest dict
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
        self.module_rows = {}
        self.module_enabled = {}
        self.file_rows = {}
        self.selected_files = set()
        self.selected_mods = set()
        self.recomp_mods_section = None
        self.mod_section = None
        self.view_mode = "list"
        self.current_state = "idle"
        self._unapplied = False      # disk differs from the rows
        self.display_path = ""
        self._last_real_path = ""
        self._scanning = False
        self._closing = False        # set after shutdown
        self._apply_reported = False
        self._install_staging = []
        self._install_context = None
        self._legend_items = []
        self.game_info = None
        self._pack_finding = None
        self.pack_muted = set()

        # config
        self.ryujinx_exe_path = ""
        self.game_file_path = ""
        self.recomp_exe_path = ""
        self.eden_exe_path = ""
        self.profiles = {}
        self.mod_profiles = {}
        self.remember_mode = False
        self._splitter_sizes = None
        self._splitter_user_set = False
        self._splitter_centered = False
        self._download_strip_height = None
        self._download_strip_user_set = False
        self._wide_actions = None     # action row at full width
        self._actions_wide = True
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
        self.eden_exe_path = config.get("eden_exe_path", "")
        self.remember_mode = bool(config.get("remember_mode", False))
        self.logging_enabled = bool(config.get("logging_enabled", True))
        self.high_contrast = bool(config.get("high_contrast", False))
        self.profiles = config.get("profiles", {}) or {}
        self.mod_profiles = config.get("mod_profiles", {}) or {}
        self.rules_overrides = config.get("rules", {}) or {}
        self.pack_muted = set(config.get("pack_muted", []) or [])
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
        height = config.get("download_strip_height")
        if isinstance(height, int) and config.get("download_strip_user_set"):
            self._download_strip_height = height
            self._download_strip_user_set = True

    def save_config(self):
        config = {
            "ryujinx_exe_path": self.ryujinx_exe_path,
            "game_file_path": self.game_file_path,
            "recomp_exe_path": self.recomp_exe_path,
            "eden_exe_path": self.eden_exe_path,
            "mode": self.mode,
            "remember_mode": self.remember_mode,
            "logging_enabled": self.logging_enabled,
            "high_contrast": self.high_contrast,
        }
        if self.emulator.mods_path and self.mode == "ryujinx":
            config["mods_path"] = redact_path(self.emulator.mods_path)
        elif self.emulator.mods_path and self.mode == "eden":
            config["eden_path"] = redact_path(self.emulator.mods_path)
        elif self.mode == "recomp" and self.display_path:
            config["recomp_root"] = self.display_path
        config["profiles"] = self.profiles
        config["mod_profiles"] = self.mod_profiles
        config["rules"] = self.rules_overrides
        # other views share the file, so keep their mutes too
        muted = set(read_config().get("pack_muted", []) or [])
        config["pack_muted"] = sorted(muted | self.pack_muted)
        updater = getattr(self.window(), "updater", None)
        if updater is not None:
            config["update_prefs"] = updater.prefs
        github = getattr(self.window(), "github", None)
        if github is not None and github.token:
            config["github_token"] = github.token
        if self.mode == "recomp":
            config["recomp_path"] = self.display_path
        # kept in every mode: the recomp dump is the reference the trimmed
        # arc check in the emulator modes compares mods against
        recomp_root = (getattr(self, "paths", {}) or {}).get("recomp") or ""
        if recomp_root:
            config["recomp_root"] = redact_path(recomp_root)
        try:
            if self.splitter is not None and self._splitter_user_set:
                config["splitter_sizes"] = list(self.splitter.sizes())
                config["splitter_user_set"] = True
        except Exception:
            pass
        try:
            if (self._download_strip_height and self._download_strip_user_set
                    and getattr(self, "download_strip", None) is not None):
                config["download_strip_height"] = int(self._download_strip_height)
                config["download_strip_user_set"] = True
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

    def _arc_reference_root(self):
        # the recomp's dumped game files are the only local copy of the
        # original arcs the emulators make us compare a mod's against
        root = (getattr(self, "paths", {}) or {}).get("recomp") or ""
        if not root:
            return None
        for candidate in (root, os.path.join(root, "data", "romfs"),
                          os.path.join(root, "romfs"),
                          os.path.join(root, "data")):
            if candidate and os.path.isdir(candidate):
                return candidate
        return None

    def _refresh_structure_sign(self):
        path = self._get_current_path()
        if not path:
            self.structure_warning.hide()
        elif self.mode == "recomp":
            ok, message, _suggested = self.recomp.structure_status(path)
            self._set_structure_sign(ok, message)
        else:
            ok, message, _suggested = self.emulator.structure_status(path)
            self._set_structure_sign(ok, message)
        self._refresh_game_sign()

    def _set_structure_sign(self, ok, message):
        if ok:
            self.structure_warning.hide()
        else:
            self.structure_warning.setText("\u26a0  " + message)
            self.structure_warning.show()

    def _refresh_game_sign(self):
        # the game the emulator loads, not the emulator build: mods and
        # cheats here are written for MHGU 1.4.0
        if self.mode == "recomp":
            self.game_info = None
            self.game_warning.hide()
            return None
        info = game_version.report(self.mode, self.emulator.mods_path)
        self.game_info = info
        message = info.message()
        if message:
            self.game_warning.setText("\u26a0  " + message)
            self.game_warning.setToolTip(info.tooltip())
            self.game_warning.show()
        else:
            self.game_warning.hide()
        return info

    # known packs
    def _pack_root(self):
        if self.mode == "recomp":
            return self.recomp.mods_path
        return self.emulator.mods_path

    def _check_pack(self):
        # packaging fingerprint, runs beside the scan
        root = self._pack_root()
        if not root or packs.folder_key(root) in self.pack_muted:
            self._pack_finding = None
            self._refresh_pack_sign()
            return
        if (self._pack_finding and packs.folder_key(
                self._pack_finding["where"]) != packs.folder_key(root)):
            self._pack_finding = None
            self._refresh_pack_sign()
        run_in_thread(self, packs.scan_root, root,
                      on_done=self._on_pack_scanned,
                      on_error=lambda _error: None)

    def _on_pack_scanned(self, finding):
        if self._closing:
            return
        root = self._pack_root() or ""
        if finding and packs.folder_key(finding["where"]) != packs.folder_key(root):
            return
        self._pack_finding = finding
        self._refresh_pack_sign()

    def _refresh_pack_sign(self):
        finding = self._pack_finding
        if not finding or packs.folder_key(finding["where"]) in self.pack_muted:
            self.pack_warning.hide()
            return
        self.pack_warning.setText(
            "\u26a0  Looks like <b>%s</b> \u2014 a repack of other authors' "
            "mods.  <a href=\"details\" style=\"color:%s;\">details</a>"
            % (finding["name"], Colors.CHEAT_MOD))
        self.pack_warning.setToolTip(finding["note"])
        self.pack_warning.show()

    def _pack_gate(self, action):
        # the banner is easy to miss, so apply and launch ask once more;
        # rescan here rather than trust the finding from the last scan
        root = self._pack_root()
        if not root or packs.folder_key(root) in self.pack_muted:
            return True
        finding = packs.scan_root(root)
        self._pack_finding = finding
        self._refresh_pack_sign()
        if not finding:
            return True
        return dialogs.PackWarningDialog.proceed(self, finding, action)

    def _show_pack_details(self, _link=None):
        finding = self._pack_finding
        if not finding:
            return
        if dialogs.PackWarningDialog.details(self, [finding]):
            self.pack_muted.add(packs.folder_key(finding["where"]))
            self._refresh_pack_sign()
            self.save_config()

    def show_game_version_report(self):
        # explicit check, the banner only speaks up when something is off
        if self.mode == "recomp":
            dialogs.info(self, "MHGU Version",
                         "This check reads the game the emulators load. "
                         "Recomp mode runs its own copy of the game.")
            return
        if not self.emulator.mods_path:
            dialogs.info(self, "MHGU Version", "Set the mods folder first.")
            return
        info = game_version.report(self.mode, self.emulator.mods_path)
        expected = game_version.EXPECTED
        lines = []
        if info.verdict == "ok":
            lines.append("MHGU %s is installed." % info.version)
            lines.append("Mods and cheats expect %s, so this matches." % expected)
        elif info.verdict == "old":
            if info.version:
                lines.append("MHGU %s is installed, but mods and cheats here "
                             "expect %s." % (info.version, expected))
            else:
                lines.append("The MHGU program on this install is not the "
                             "%s build." % expected)
            lines.append("")
            lines.append("Install the %s update in %s, then rescan. "
                         "Cheats key off the build id, so an older game "
                         "will not load them." % (expected, info.name))
        elif info.verdict == "unverified":
            lines.append("An MHGU update is installed, but dreamSort cannot "
                         "read its version from %s's files." % info.name)
            lines.append("Check the game's update in %s: it should be %s."
                         % (info.name, expected))
        else:
            lines.append("The game files were not found next to the mods "
                         "folder, so the version is unknown.")
            lines.append("Ryujinx keeps them in games\\%s, Eden under "
                         "nand\\user\\Contents\\registered."
                         % game_version.TITLE_ID)
        detail = info.tooltip()
        if detail:
            lines.append("")
            lines.append(detail)
        dialogs.info(self, "MHGU Version", "\n".join(lines))


    def _on_path_edited(self):
        self._pack_finding = None
        self._refresh_pack_sign()
        self._structure_timer.start(250)

    def refresh_details(self):
        # the open sheet fixes its colours when it is drawn, so draw it
        # again after a theme change, without asking the window for room
        if not self.current_details_mod or self.current_state == "working":
            return
        self.details.quiet = True
        try:
            self.show_details(self.current_details_mod)
        finally:
            QTimer.singleShot(200, lambda: setattr(self.details, "quiet", False))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # the page still has its old width here, so look again once laid out
        QTimer.singleShot(0, self._fit_action_row)

    def _fit_action_row(self):
        # a narrow window keeps the left buttons as icons; tooltips stay
        bar = getattr(self, "top_bar", None)
        if bar is None or not bar.isVisible():
            return
        if self._wide_actions is None:
            self._wide_actions = self.action_row.sizeHint().width()
        edges = bar.layout().contentsMargins()
        room = bar.width() - edges.left() - edges.right()
        # strict: the wide row cannot shrink below its own width, so that
        # is already too narrow
        wide = self._wide_actions < room
        if wide == self._actions_wide:
            return
        self._actions_wide = wide
        for button, text in ((self.import_mods_btn, "Import Mods"),
                             (self.refresh_btn, "Refresh"),
                             (self.more_btn, "More")):
            button.setText(text if wide else "")

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
        self.download_strip = self._build_download_strip()

        # list area over the strip, so the strip's edge can be dragged
        self.content_splitter = QSplitter(Qt.Vertical, self.main_page)
        self.content_splitter.setHandleWidth(6)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.addWidget(self.splitter)
        self.content_splitter.addWidget(self.download_strip)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)
        self.content_splitter.splitterMoved.connect(self._on_content_splitter_moved)
        page.addWidget(self.content_splitter, 1)

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
        self.top_bar = bar
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
        layout.addLayout(path_row)

        # one row: the four buttons in use, the rest under More
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.action_row = actions

        self.import_mods_btn = QPushButton("Import Mods", bar)
        set_icon(self.import_mods_btn, "download")
        self.import_mods_btn.setToolTip(
            "Install mods from files, folders or archives")
        self.import_mods_btn.clicked.connect(self.import_mods_popup)
        actions.addWidget(self.import_mods_btn)

        self.refresh_btn = QPushButton("Refresh", bar)
        set_icon(self.refresh_btn, "refresh")
        self.refresh_btn.setToolTip("Re-read this mode's mods and cheats")
        self.refresh_btn.clicked.connect(self.refresh_mods)
        actions.addWidget(self.refresh_btn)

        # one Cheats dropdown where the three fixed buttons were
        self.cheat_menu = QMenu(bar)
        self.cheat_menu.setToolTipsVisible(True)
        self.cheat_menu.aboutToShow.connect(self._fill_cheat_menu)
        self.cheat_btn = PopupButton("Cheats", self.cheat_menu, bar)
        self.cheat_btn.setText("Cheats  \u25be")
        self.cheat_btn.setFixedHeight(
            self.import_mods_btn.sizeHint().height())
        self.cheat_btn.setToolTip(
            "Preview, import or disable cheats")
        actions.addWidget(self.cheat_btn)

        # eden cheat switch
        self.eden_settings_btn = QPushButton("Eden Settings", bar)
        self.eden_settings_btn.setFixedWidth(140)
        self.eden_settings_btn.setToolTip(
            "Check Eden's own 'enable cheats by default' switch and turn it on")
        self.eden_settings_btn.clicked.connect(self.eden_settings_popup)
        self.eden_settings_btn.hide()
        actions.addWidget(self.eden_settings_btn)

        # the overflow button sits at the end of the left group
        self.more_menu = QMenu(bar)
        self.more_menu.setToolTipsVisible(True)
        self.more_menu.aboutToShow.connect(self._fill_more_menu)
        self.more_btn = PopupButton("More", self.more_menu, bar)
        set_icon(self.more_btn, "more")
        # the tool button's own layout adds a few px; match the row's
        self.more_btn.setFixedHeight(self.import_mods_btn.sizeHint().height())
        self.more_btn.setToolTip(
            "Scan, open the mods folder, Auto-Find, Disable Mods")
        actions.addWidget(self.more_btn)

        actions.addStretch(1)

        self.apply_btn = QPushButton("Apply Changes", bar)
        self.apply_btn.setObjectName("applyBtn")
        set_icon(self.apply_btn, "check")
        self.apply_btn.setToolTip("Write the pending changes to disk")
        self.apply_btn.clicked.connect(self.apply_changes)
        actions.addWidget(self.apply_btn)

        self.launch_btn = QPushButton("Launch", bar)
        self.launch_btn.setObjectName("primaryBtn")
        set_icon(self.launch_btn, "play")
        self.launch_btn.setToolTip("Start the game with these mods")
        self.launch_btn.clicked.connect(self.launch_game)
        actions.addWidget(self.launch_btn)
        layout.addLayout(actions)

        self.structure_warning = QLabel("", bar)
        self.structure_warning.setObjectName("warningBanner")
        self.structure_warning.setWordWrap(True)
        self.structure_warning.hide()
        layout.addWidget(self.structure_warning)

        self.game_warning = QLabel("", bar)
        self.game_warning.setObjectName("versionBanner")
        self.game_warning.setWordWrap(True)
        self.game_warning.hide()
        layout.addWidget(self.game_warning)

        self.pack_warning = QLabel("", bar)
        self.pack_warning.setObjectName("packBanner")
        self.pack_warning.setWordWrap(True)
        self.pack_warning.setTextFormat(Qt.RichText)
        self.pack_warning.linkActivated.connect(self._show_pack_details)
        self.pack_warning.hide()
        layout.addWidget(self.pack_warning)
        return bar

    def _fill_cheat_menu(self):
        # filled on each open, so the items follow the mode in use
        menu = self.cheat_menu
        menu.clear()
        if self.mode == "ryujinx":
            menu.addAction(action_icon("check"), "Preview enabled.txt",
                           self.preview_enabled_cheats_popup)
            menu.addSeparator()
        elif self.mode == "eden":
            menu.addAction(action_icon("check"), "Preview Cheats",
                           self.preview_enabled_cheats_popup)
            menu.addSeparator()
        menu.addAction(action_icon("download"), "Import Cheat…",
                       self.import_cheat_popup)
        menu.addAction(action_icon("ban"), "Disable All Cheats",
                       self.clear_all_cheats)

    def _fill_more_menu(self):
        # filled on each open, so the icons follow the theme in use
        menu = self.more_menu
        menu.clear()
        for text, icon, tip, slot in (
                ("Scan", "scan", "Re-read the folder in the path box",
                 self.run_scan),
                ("Open mods folder", "folder",
                 "Open the loaded mods folder in File Explorer",
                 self.open_mod_directory),
                ("Auto-Find", "find",
                 "Search this PC for the mods folder of the current mode",
                 self._auto_find_mods)):
            menu.addAction(action_icon(icon), text, slot).setToolTip(tip)
        menu.addSeparator()
        menu.addAction(action_icon("ban"), "Disable Mods",
                       self.clear_all_mods).setToolTip(
            "Switch every mod off, then Apply Changes to save")

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

        header = QLabel("Mod load order  \u00b7  Drag files here to install", panel)
        header.setObjectName("panelHeader")
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
        for color, text in ((Colors.RESOLVED_CONFLICT, "Wins conflict"),
                            (Colors.CONFLICT, "Loses conflict"),
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

        header = QLabel("Details", frame)
        header.setObjectName("panelHeader")
        layout.addWidget(header, 0)

        self.download_summary = QLabel("", frame)
        self.download_summary.setStyleSheet("color: %s; background: transparent;"
                                             % Colors.TEXT_MUTED)
        layout.addWidget(self.download_summary, 0)

        self.details = DetailsPanel(frame)
        self.details.overflow.connect(self._grow_for_details)
        self.details.placeholder()
        layout.addWidget(self.details, 1)
        return frame

    def _grow_for_details(self, deficit):
        # the sheet's last row must not sit on the window border
        window = self.window()
        if window is None or window.isMaximized() or window.isFullScreen():
            return
        screen = window.screen()
        if screen is None:
            return
        room = screen.availableGeometry().bottom() - window.frameGeometry().bottom()
        grow = min(deficit, room)
        if grow > 0:
            window.resize(window.width(), window.height() + grow)

    def _build_download_strip(self):
        # holder reserves only the top margin the shadow bleeds into
        holder = QWidget(self.main_page)
        holder.setObjectName("downloadStripHolder")
        holder.setMinimumHeight(122)
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 18, 0, 0)
        box.setSpacing(0)

        frame = QFrame(holder)
        frame.setObjectName("listPanel")
        service = getattr(self.window(), "gb_service", None)
        self.download_panel = None
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 4, 4, 4)
        if service is not None:
            self.download_panel = DownloadQueuePanel(service, frame)
            self.download_panel.open_folder_requested.connect(
                self._open_downloads_folder)
            service.queue_changed.connect(self._refresh_download_summary)
            layout.addWidget(self.download_panel)

        # lifts the strip off the window background, top edge only
        shadow = QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, -6)
        shadow.setColor(QColor(0, 0, 0, 250))
        frame.setGraphicsEffect(shadow)

        box.addWidget(frame)
        holder.hide()
        return holder

    def _refresh_download_summary(self):
        service = getattr(self.window(), "gb_service", None)
        if service is None:
            return
        active = service.active_count()
        ready = sum(1 for e in service.entries() if e["status"] == "ready")
        if active:
            self.download_summary.setText("Downloads: %d active" % active)
        elif ready:
            self.download_summary.setText("Downloads: %d ready to install" % ready)
        else:
            self.download_summary.setText("")

    def _toggle_download_strip(self):
        strip = self.download_strip
        if strip.isVisible():
            strip.setVisible(False)
        else:
            strip.setVisible(True)
            self._apply_download_strip_height()

    def _on_content_splitter_moved(self, _pos, _index):
        # a real drag is worth remembering
        self._download_strip_height = self.download_strip.height()
        self._download_strip_user_set = True
        self._save_timer.start(500)

    def _apply_download_strip_height(self):
        # reopen at the last dragged height, leaving room for the list
        strip = self.download_strip
        total = self.content_splitter.height()
        height = self._download_strip_height or 200
        if total > 0:
            height = min(height, total - 120)
        height = max(height, strip.minimumHeight())
        self.content_splitter.setSizes([max(1, total - height), height])
        self._download_strip_height = height

    def _open_downloads_dialog(self):
        service = getattr(self.window(), "gb_service", None)
        if service is None:
            return
        self._downloads_dialog = DownloadsDialog(service, self)
        self._downloads_dialog.panel.open_folder_requested.connect(
            self._open_downloads_folder)
        self._downloads_dialog.open()

    def _open_downloads_folder(self):
        directory = os.path.join(os.path.dirname(config_path()), "downloads")
        os.makedirs(directory, exist_ok=True)
        open_in_file_explorer(directory)

    def _build_bottom_bar(self):
        bar = QWidget(self.main_page)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(2, 2, 2, 0)
        layout.setSpacing(6)

        self.status_label = QLabel("", bar)
        self.status_label.setObjectName("statusLabel")
        self.status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.status_label, 1)

        self.updates_btn = QPushButton("Updates", bar)
        self.updates_btn.setFixedWidth(120)
        self.updates_btn.setToolTip(
            "GameBanana updates for the linked mods in this folder")
        self.updates_btn.clicked.connect(self.show_updates)
        layout.addWidget(self.updates_btn, 0)

        self.downloads_btn = QPushButton("Downloads \u25be", bar)
        self.downloads_btn.setFixedWidth(110)
        self.downloads_btn.clicked.connect(self._toggle_download_strip)
        layout.addWidget(self.downloads_btn, 0)

        profile_label = QLabel("Layout:", bar)
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
            self.details.placeholder(
                "Select a mod or a cheat to view details. Cheats are .txt "
                "files in cheats/; a leading '_' switches one off.")
        elif self.mode == "eden":
            self.path_edit.setPlaceholderText(
                "Path to Eden load %s folder" % getattr(self.emulator,
                                                       "TITLE_ID", ""))
            self.details.placeholder(
                "Select a mod or a cheat to view details. Disabled entries "
                "sit in disabled_mods / disabled_cheats.")
        else:
            self.path_edit.setPlaceholderText("Path to Ryujinx Mods folder")
            self.details.placeholder(
                "Select a mod to view details and manage cheats.")
        default_path = self._default_path_for_mode()
        if default_path:
            self._update_path_display(default_path)
        else:
            self._refresh_game_sign()
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
    def refresh_mods(self):
        # same as Scan, but reads the disk again first
        if self._closing or self._scanning or self.current_state == "working":
            return
        self._rules_cache.clear()
        self._manifest_cache.clear()
        self._dir_stats_cache.clear()
        self._pack_finding = None
        self._refresh_pack_sign()
        self.run_scan()

    def run_scan(self):
        if self._closing:
            return
        if self._scanning or self.current_state == "working":
            return
        self._rules_cache = {}
        self._manifest_cache = {}
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
        self._sweep_staging()
        self.emulator.scan_and_analyze()
        self._initialize_pending_cheats()
        return dict(self.pending_cheat_selections)

    def _on_emulator_scanned(self, pending_cheats):
        self._scanning = False
        if self._closing:
            # window already closed
            return
        self._clear_unapplied()
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
        self._refresh_structure_sign()
        self._check_pack()
        if self.game_info is not None and self.game_info.version:
            message += "  MHGU " + self.game_info.version
        self._status(message)
        self.save_config()
        self._maybe_check_updates()

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
        self._sweep_staging()
        self.recomp.scan()
        return True

    def _on_recomp_scanned(self, _result):
        self._scanning = False
        self._clear_unapplied()
        self.populate_recomp_list()
        if self.view_mode == "tree":
            self.populate_recomp_tree()
        self._status("Loaded %d mods, %d cheats, %d plugins, %d patches, "
                     "%d engine modules."
                     % (len(self.recomp.mods), len(self.recomp.cheats),
                        len(self.recomp.plugins), len(self.recomp.patches),
                        len(self.recomp.modules)))
        self._refresh_structure_sign()
        self._check_pack()
        self.save_config()
        self._maybe_check_updates()

    def _clear_scan_results(self):
        self.list_widget.clear_items()
        self.recomp_mods_section = None
        self.mod_section = None
        self.mod_rows = {}
        self._rows_by_id = {}
        self.mod_enabled = {}
        self.cheat_rows = {}
        self.patch_rows = {}
        self.plugin_rows = {}
        self.module_rows = {}
        self.module_enabled = {}
        self.file_rows = {}
        self.selected_files = set()
        self.pending_cheat_selections = {}
        self.tree.clear_items()
        self.selected_mods.clear()
        self._update_selection_bar()
        self.details.clear()
        self.details.placeholder("Select a mod to see its details.")
        self._pack_finding = None
        self._refresh_pack_sign()

    # populate (ryujinx)
    def populate_mod_list(self):
        self.list_widget.clear_items()
        self.mod_section = None
        self.mod_rows = {}
        self._rows_by_id = {}
        self.mod_enabled = {}
        self.eden_cheat_rows = {}
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

        # orderable stack, in the order the loader reads
        mods_section = CollapsibleSection(
            "Mods (%d)" % len(romfs_mods), body=ModListWidget())
        mods_section.body.dropPaths.connect(self._on_paths_dropped)
        mods_section.body.reorderRequested.connect(
            lambda mod_id, index: self._on_reorder_requested(
                mod_id, index, mods_section.body))
        self.list_widget.add_item(mods_section)
        self.mod_section = mods_section

        labels = getattr(analyzer, "mod_labels", {})
        for mod_name in romfs_mods:
            marks = labels.get(mod_name) or {}
            chips = []
            if marks.get("romfs"):
                chips.append(("romFS", "romfs", False))
            if marks.get("exefs"):
                chips.append(("exefs", "exefs", False))
            if marks.get("forge"):
                chips.append(("forge", "forge", False))
            if marks.get("arc"):
                chips.append(("arc", "arc", True))
            row = ModRow(mod_name, analyzer.strip_prefix(mod_name),
                         checkbox=True, draggable=True, chips=chips)
            row.set_mod_enabled(mod_is_on(mod_name))
            row.toggled.connect(self._on_row_toggled)
            row.activated.connect(self._on_row_activated)
            row.ctrlClicked.connect(self._on_row_ctrl_clicked)
            row.contextRequested.connect(self._on_row_context_menu)
            mods_section.body.add_row(row)
            self._register_row(row)
            self.mod_enabled[mod_name] = mod_is_on(mod_name)
        if not romfs_mods:
            mods_section.body.add_item(self._empty_label("(no mods installed)"))

        if special:
            # the header and the folder it points at are one row
            title = ("Ryujinx Enabled Cheats" if self.mode == "ryujinx"
                     else "Enabled Cheats")
            row = ModRow(special, title, checkbox=False,
                         chips=[(analyzer.strip_prefix(special), "muted",
                                 False)],
                         variant="section", bold=True, draggable=False)
            row.activated.connect(self._on_row_activated)
            row.contextRequested.connect(self._on_row_context_menu)
            self.list_widget.add_row(row)
            self._register_row(row)

        # cheats: the recomp's plugin row look, one indent per cheat
        cheat_mods = [m for m in all_mods if m in analyzer.cheat_only_mods]
        if cheat_mods or self.mode == "ryujinx":
            cheats_section = CollapsibleSection(
                "Cheats (%d)" % len(cheat_mods), body=ModListWidget())
            cheats_section.body.dropPaths.connect(self._on_paths_dropped)
            for mod_name in cheat_mods:
                row = ChildRow(mod_name, analyzer.strip_prefix(mod_name))
                row.activated.connect(self._on_row_activated)
                row.contextRequested.connect(self._on_row_context_menu)
                cheats_section.body.add_row(row)
                self._register_row(row)
            if not cheat_mods:
                cheats_section.body.add_item(self._empty_label("(no cheats)"))
            self.list_widget.add_item(cheats_section)

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
            row = FileRow(name, "  \u2514 " + name, checked=enabled)
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
        self._status("Cheat '%s' %s. Click 'Apply Changes' to save."
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

    def _list_rows(self, container=None):
        # rows in a stack, sections walked in place
        rows = []
        for widget in (container or self.list_widget).items():
            if isinstance(widget, ModRow):
                rows.append(widget)
                continue
            body = getattr(widget, "body", None)
            if isinstance(body, ModListWidget):
                rows.extend(self._list_rows(body))
        return rows

    def _row_stack(self, mod_id):
        # stack that owns a row
        for widget in self.list_widget.items():
            body = getattr(widget, "body", None)
            if isinstance(body, ModListWidget) and mod_id in body.rows:
                return body
        return None

    def _order_ids(self):
        return [row.mod_id for row in self._list_rows()]

    def _orderable_ids(self):
        return [row.mod_id for row in self._list_rows()
                if row.checkbox is not None]

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
        self.refresh_update_badges()

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
        self.module_rows = {}
        self.module_enabled = {}
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
            row.set_note(self._plugin_note(entry))
            row.toggled.connect(self._file_toggled)
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
            row.toggled.connect(self._file_toggled)
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

        # engine modules: native code for the port, never a Forge plugin
        modules_section = CollapsibleSection(
            "Engine Modules (%d)" % len(analyzer.modules),
            body=ModListWidget())
        modules_section.body.dropPaths.connect(self._module_drop_hint)
        for name in sorted(analyzer.modules, key=str.lower):
            data = analyzer.modules[name]
            chips = [("module", "module", True)]
            if not data.get("binary"):
                chips.append(("no binary", "muted", False))
            row = ModRow(name, name, checkbox=True, chips=chips,
                         variant="module", draggable=False)
            row.set_mod_enabled(bool(data.get("enabled")))
            row.toggled.connect(self._module_toggled)
            row.activated.connect(self._on_row_activated)
            row.setToolTip("Native code the recomp loads into its own process. "
                           "Not a Forge plugin; never installed on Eden or "
                           "Ryujinx. Apply writes engine_modules/enabled.txt.")
            modules_section.body.add_row(row)
            self._register_row(row, primary=False)
            self.module_rows[name] = row
            self.module_enabled[name] = bool(data.get("enabled"))
        if not analyzer.modules:
            modules_section.body.add_item(self._empty_label(
                "(no engine modules)" if os.path.isdir(analyzer.engine_modules_path)
                else "(none: no engine_modules/ folder in this install)"))
        self.list_widget.add_item(modules_section)

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
                         bold=clean_folder(clean_name) in rules_store.SEED_RULES,
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
        seed = rules_store.SEED_RULES.get(clean_folder(clean_name))
        if seed and seed.name:
            return "%s  (%s)" % (clean_name, seed.name)
        return clean_name

    @staticmethod
    def _version_pill(version):
        # the header pill form of a manifest version
        text = str(version or "").strip()
        if not text:
            return ""
        return text if text.lower().startswith("v") else "v" + text

    @staticmethod
    def _plugin_name(entry):
        # manifest name when the release ships one, else the file stem
        raw = entry.get("manifest") or {}
        return ((raw.get("name") or "").strip()
                or os.path.splitext(str(entry.get("filename") or ""))[0])

    def _plugin_note(self, entry):
        # manifest version and author, shown beside the file name
        raw = entry.get("manifest") or {}
        authors = ", ".join(str(a) for a in (raw.get("authors") or []))
        parts = [self._version_pill(raw.get("version")), authors]
        if entry.get("ignored_by_recomp"):
            parts.append("(not loaded by the recomp)")
        return " \u00b7 ".join(part for part in parts if part)

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
        self._mark_unapplied("'%s' %s. Click 'Apply Changes' to save."
                             % (mod_id, "enabled" if checked else "disabled"))

    def _module_drop_hint(self, _paths):
        # a module is a native library, not something mods/ can hold
        dialogs.info(self, "Engine modules",
                     "A module is not a mod: put its folder in engine_modules/ "
                     "beside mods/, so each <name>/ holds <name>.dll, then Scan "
                     "again.\n\nThe recomp loads it only while "
                     "engine_modules/enabled.txt lists that folder.")

    def _module_toggled(self, name, checked):
        # modules are not load-order items, they only go in or out of enabled.txt
        self.module_enabled[name] = checked
        self._mark_unapplied("Module '%s' %s. Click 'Apply Changes' to save."
                             % (name, "enabled" if checked else "disabled"))
        if self.view_mode == "tree":
            self.populate_recomp_tree()

    def _recomp_recolor_all(self):
        view = self._recomp_conflict_view()
        index_of = self._recomp_order_index()
        for mod_id, rows in list(self._rows_by_id.items()):
            if mod_id in self.module_rows:
                continue  # module rows carry their own accent
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
        self._after_order_change("'%s' %s. Click 'Apply Changes' to save."
                                 % (mod_id, "enabled" if checked else "disabled"))

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
        if mod_id in self.mod_enabled:
            return bool(self.mod_enabled[mod_id])
        row = self.mod_rows.get(mod_id)
        if row is not None:
            if row.checkbox is None:
                return True
            return row.checkbox.isChecked()
        # a plugin-only mod has no row in the romFS section, only in All Mods
        data = self.recomp.mods.get(mod_id) if self.mode == "recomp" else None
        return bool((data or {}).get("enabled", False))

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
        if index is not None and index < 0:
            # dropped beside a stack: end of the row's own stack
            container = self._row_stack(mod_id) or container
            index = len(container.order_ids())
        if container.move_row(mod_id, index):
            self._after_order_change(
                "Order changed. Click 'Apply Changes' to save.")

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
        self._mark_unapplied(status_text)

    def _mark_unapplied(self, status_text=None):
        # nothing is on disk yet, so flag the commit button
        self._unapplied = True
        self.apply_btn.setProperty("unapplied", True)
        self.apply_btn.style().unpolish(self.apply_btn)
        self.apply_btn.style().polish(self.apply_btn)
        self._status(status_text
                     or "Unapplied changes. Click 'Apply Changes' to save.")

    def _clear_unapplied(self):
        self._unapplied = False
        self.apply_btn.setProperty("unapplied", False)
        self.apply_btn.style().unpolish(self.apply_btn)
        self.apply_btn.style().polish(self.apply_btn)

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

    def _file_toggled(self, key, checked):
        # a tick on a plugin or patch row is a pending change for Apply
        self._mark_unapplied("'%s' %s. Click 'Apply Changes' to save."
                             % (os.path.basename(str(key[1])),
                                "enabled" if checked else "disabled"))
        if self.current_details_mod == key:
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
        path = self._module_folder(mod_id) if self.mode == "recomp" else None
        if path is None:
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

    def _module_folder(self, mod_id):
        # engine modules live outside mods/, never a load-order entry
        data = self.recomp.modules.get(mod_id)
        return data.get("path") if data else None

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
        self.module_rows.pop(mod_id, None)
        self.module_enabled.pop(mod_id, None)
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

        record = self._mod_record(mod_id)
        if record and record.get("gb_mod_id"):
            menu.addAction("Update…", lambda: self._update_mod(mod_id))
        if record and record.get("page_url"):
            menu.addAction("Open mod page",
                           lambda: self._open_gb_page(mod_id))
        menu.addAction("Link to GameBanana…", lambda: self._link_gb(mod_id))
        menu.addAction("Check for update", lambda: self._check_update(mod_id))

        gh_source = github_records.source(record)
        if gh_source:
            service = getattr(self.window(), "github", None)
            state = service.item(mod_id) if service is not None else None
            if state and state.get("status") == "update_available":
                menu.addAction("Update from GitHub…",
                               lambda: self._update_from_github(mod_id))
                if state.get("page_url"):
                    menu.addAction("Open GitHub release",
                                   lambda: webbrowser.open(state["page_url"]))
            menu.addAction("Check GitHub update",
                           lambda: self._check_github_update(mod_id))
            menu.addAction("Remove GitHub link",
                           lambda: self._unlink_github(mod_id))
        else:
            menu.addAction("Link to GitHub…",
                           lambda: self._link_github(mod_id))

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
            shown = getattr(self, "current_details_mod", None)
            # a plugin or patch shows as (mod, rel_path)
            if shown == mod_id or (isinstance(shown, tuple)
                                   and shown[:1] == (mod_id,)):
                self.current_details_mod = None
                self.details.clear()
                self.details.hint("Select a mod to see its details.")
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
                "Order changed. Click 'Apply Changes' to save.")

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
            self._status("'%s' set to win over '%s'. Click 'Apply Changes'."
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
                         "Click 'Apply Changes'." % (mod_id, target_id))
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
        if self.mod_section is None:
            return None
        return self.mod_section.body

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

    def _display_name(self, mod_id, fallback):
        # manifest name wins, folder name is the fallback
        raw = self._load_manifest_raw(mod_id) or {}
        return (raw.get("name") or "").strip() or fallback

    def _show_conflict_details(self, mod_name):
        self.current_details_mod = mod_name
        self.details.clear()
        clean = self.emulator.strip_prefix(mod_name)
        display = self._display_name(mod_name, clean)
        raw = self._load_manifest_raw(mod_name) or {}
        rule = self._load_mod_rules(mod_name)
        version = (raw.get("version") or "") if raw else (
            rule.version if rule is not None else "")
        version = str(version or "").strip()
        badge = self._version_pill(version)
        mod_id = rule.mod_id if rule is not None else ""
        path = self._mod_folder(mod_name)
        if not path:
            path = os.path.join(self.emulator.mods_path, mod_name)
        page = (raw.get("page_url") or "") if raw else ""
        if rule is not None:
            page = page or rule.page_url
        record = read_record(path) if path else None
        page = page or ((record or {}).get("page_url") or "")
        description = (raw.get("description") or "") if raw else ""
        if rule is not None:
            description = description or rule.description

        self.details.sheet()
        self.details.sheet_header(
            display, version=badge, enabled=self._is_mod_enabled(mod_name),
            on_toggle=lambda: self._details_toggle_mod(mod_name),
            menu=[("Check update", lambda: self._check_update(mod_name)),
                  ("Copy path", lambda: self._copy_mod_path(path)),
                  None,
                  ("Uninstall", lambda: self._delete_mod(mod_name))])
        link = page_link(page) if page else None
        self.details.sheet_byline([link] if link else [])
        if mod_id:
            self.details.sheet_text(mod_id, mono=True, colour=Colors.TEXT_MUTED)
        if description:
            self.details.sheet_text(description, top=8, wrap=True)

        requires_rows, conflict_rows, _counts = self._rule_status_rows(rule)
        self.details.sheet_group("Dependencies")
        self.details.sheet_fields(
            self._order_fields(mod_name, rule)
            + self._dep_fields("Requires", requires_rows, "None")
            + self._dep_fields("Conflicts", conflict_rows, "None declared"))

        stats = (getattr(self.emulator, "mod_stats", None) or {}).get(mod_name)
        if stats is None:
            stats = self._dir_stats(path)
        file_count, size = stats
        full_path = redact_path(path)
        self.details.sheet_group("Installed")
        self.details.sheet_fields([
            ("Location", LocationRow(
                middle_ellipsis(full_path, 44), tooltip=full_path,
                on_copy=lambda: self._copy_mod_path(path),
                on_open=lambda: open_in_file_explorer(path)), {}),
            ("Files", SheetRow("%d file%s" % (
                file_count, "" if file_count == 1 else "s"), controls=[
                    ClickLabel("View list",
                              lambda: self._show_mod_files(mod_name, display),
                              None, color=Colors.NO_CONFLICT_TEXT,
                              underline=False)]), {}),
            ("Size", self._format_size(size), {}),
        ])

        conflicts = self._live_conflicts(mod_name)
        if conflicts:
            self.details.sheet_group("%d conflicting file%s" % (
                len(conflicts), "" if len(conflicts) == 1 else "s"))
            for rel_path in sorted(conflicts)[:40]:
                rivals = conflicts[rel_path]
                win_btn = QPushButton("Make mine win")
                win_btn.setFixedHeight(ACTION)
                # move above or below the rival
                move = (self._move_mod_below if self._conflict_later_wins()
                        else self._move_mod_above)
                win_btn.clicked.connect(
                    lambda _checked=False, t=rivals[0]: move(mod_name, t))
                self.details.sheet_block(SheetRow(
                    rel_path, mono=True, controls=[
                        self.details.sheet_tag("vs " + ", ".join(rivals)[:60]),
                        win_btn]))
            if len(conflicts) > 40:
                self.details.sheet_text("(%d more not shown)" % (
                    len(conflicts) - 40), colour=Colors.TEXT_MUTED)
        else:
            self.details.sheet_group("Conflicting Files")
            shared = (getattr(self.emulator, "conflicts", {}) or {}).get(
                mod_name) or {}
            self.details.sheet_text(
                ("%d shared file%s overlap%s only with mods that are "
                 "switched off." % (len(shared), "" if len(shared) == 1 else "s",
                                    "s" if len(shared) == 1 else ""))
                if shared else "None detected.",
                colour=Colors.TEXT_MUTED, wrap=True)

        files = [entry for entry in self.cheat_files_model
                 if entry["owner"] == mod_name]
        if files:
            count = sum(len(entry["entries"]) for entry in files)
            self.details.sheet_group("Cheat entries (%d)" % count)
            self._cheat_group_rows(files, show_file_label=len(files) > 1,
                                   sheet=True)
            self.details.sheet_text(
                "Ryujinx loads these from this mod's cheats/ folder even "
                "when the mod itself is disabled.",
                top=2, colour=Colors.TEXT_MUTED, wrap=True)

    def _order_fields(self, mod_name, rule):
        # the gutter number, then the rule's own ordering
        rows = []
        position = self._load_numbers().get(mod_name)
        if position:
            rows.append(("Position", "#%d of %d" % (
                position, len(self._load_numbers())), {"tooltip": (
                    "Larger load numbers win conflicts."
                    if self._conflict_later_wins()
                    else "Smaller load numbers win conflicts.")}))
        rows.append(("Load order", self._load_order_text(rule), {}))
        return rows

    def _details_toggle_mod(self, mod_name):
        enabled = self._is_mod_enabled(mod_name)
        if self._rows_for(mod_name):
            self._set_mod_enabled(mod_name, not enabled)
        else:
            self.mod_enabled[mod_name] = not enabled
            self._after_order_change("'%s' %s." % (
                mod_name, "enabled" if not enabled else "disabled"))
        self._show_conflict_details(mod_name)

    def _copy_mod_path(self, path):
        QGuiApplication.clipboard().setText(str(path))
        self._status("Copied the mod path.")

    def _show_mod_files(self, mod_name, display):
        files = sorted(getattr(self.emulator, "mod_files", {}).get(
            mod_name, set()) or set())
        if not files:
            dialogs.info(self, "Files",
                         "No game files were found for this mod.")
            return
        shown = files[:400]
        body = "\n".join(shown)
        if len(files) > len(shown):
            body += "\n... %d more" % (len(files) - len(shown))
        dialogs.CheatCodeDialog.view(
            self, "Files in %s (%d)" % (display, len(files)), body)

    def _friendly_name(self, rule, fallback):
        return (rule.name if rule is not None and rule.name else "") or fallback

    @staticmethod
    def _extra_constraint(constraint, have):
        # a satisfied constraint is only worth showing when it says something
        # the installed version does not already
        body = str(constraint or "").strip()
        for op in (">=", "<=", "==", "!=", ">", "<"):
            if body.startswith(op):
                body = body[len(op):].strip()
                break
        if body in ("", "*") or body == str(have):
            return ""
        return str(constraint).strip()

    def _rule_status_rows(self, rule):
        counts = {"requires": 0, "issues": 0, "conflicts": 0, "active": 0}
        if rule is None:
            return [], [], counts
        _installed, enabled, rules, aliases, folders = self._rules_snapshot()
        requires_rows, conflict_rows = [], []
        for ref, constraint in (rule.requires or {}).items():
            canonical = aliases.get(ref, ref)
            dep = rules.get(canonical)
            folder = folders.get(canonical)
            name = self._friendly_name(dep, canonical)
            counts["requires"] += 1
            need = "any version" if constraint in ("", "*") else constraint
            if folder is None:
                counts["issues"] += 1
                requires_rows.append((name, "not installed \u2715",
                                      Colors.CONFLICT, canonical))
            elif canonical not in enabled:
                counts["issues"] += 1
                requires_rows.append((name, "installed, disabled \u26a0",
                                      Colors.DRAG_HIGHLIGHT, canonical))
            else:
                ok, warn = satisfies(dep.version if dep else None,
                                     constraint)
                have = (dep.version if dep else "") or "unknown"
                if ok:
                    shown = self._extra_constraint(constraint, have)
                    requires_rows.append(
                        (name, "%s \u2713%s" % (have, " " + shown if shown else ""),
                         Colors.RESOLVED_CONFLICT, canonical))
                else:
                    counts["issues"] += 1
                    requires_rows.append(
                        (name, "%s %s needs %s"
                         % (have, "\u26a0" if warn else "\u2715", need),
                         Colors.DRAG_HIGHLIGHT if warn else Colors.CONFLICT,
                         canonical))
        for ref, constraint in (rule.conflicts or {}).items():
            canonical = aliases.get(ref, ref)
            if canonical == rule.mod_id:
                continue
            dep = rules.get(canonical)
            folder = folders.get(canonical)
            name = self._friendly_name(dep, canonical)
            counts["conflicts"] += 1
            if folder is None:
                conflict_rows.append((name, "not installed \u2713",
                                      Colors.RESOLVED_CONFLICT, canonical))
                continue
            if canonical not in enabled:
                conflict_rows.append((name, "disabled \u2713",
                                      Colors.RESOLVED_CONFLICT, canonical))
                continue
            match, _warn = satisfies(dep.version if dep else None, constraint)
            if match:
                counts["active"] += 1
                conflict_rows.append((name, "active \u2715",
                                      Colors.CONFLICT, canonical))
            else:
                have = dep.version if dep else ""
                note = ("%s \u2713 outside range" % have if have
                        else "outside range \u2713")
                conflict_rows.append((name, note,
                                      Colors.RESOLVED_CONFLICT, canonical))

        def _dedupe(rows):
            # only show the id when it differs from the display name
            return [(name, text, color, "" if name == ident else ident)
                    for name, text, color, ident in rows]

        return _dedupe(requires_rows), _dedupe(conflict_rows), counts

    def _rule_names(self, refs, rules, aliases, enabled, folders):
        names = []
        for ref in refs:
            canonical = aliases.get(ref, ref)
            name = self._friendly_name(rules.get(canonical), canonical)
            if canonical in folders and canonical not in enabled:
                name += " (disabled)"
            names.append(name)
        return ", ".join(names) or "any"

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

    def _cheat_group_rows(self, files, *, show_file_label=True, sheet=False):
        # one group per cheat file; the sheet form uses SheetRow lines
        for entry in files:
            if show_file_label:
                if sheet:
                    self.details.sheet_text(entry["rel"], top=4, mono=True,
                                            colour=Colors.TEXT_MUTED)
                else:
                    self.details.label(entry["rel"], bold=True, mono=True)
            for item in entry["entries"]:
                check = CheckMark(None, size=16)
                states = self.pending_cheat_selections.get(entry["path"], {})
                check.setChecked(bool(states.get(item["key"], False)))
                check.toggled.connect(
                    lambda checked, p=entry["path"], k=item["key"]:
                    self._on_cheat_toggled(p, k, checked))
                view_btn = QPushButton("View Code")
                view_btn.clicked.connect(
                    lambda _checked=False, p=entry["path"], i=item["index"]:
                    self._show_cheat_code(p, i))
                edit_btn = QPushButton("Edit")
                edit_btn.clicked.connect(
                    lambda _checked=False, p=entry["path"], i=item["index"]:
                    self._edit_cheat_code(p, i))
                if sheet:
                    view_btn.setFixedHeight(ACTION)
                    edit_btn.setFixedHeight(ACTION)
                    self.details.sheet_block(SheetRow(
                        item["title"], lead=check,
                        controls=[view_btn, edit_btn]), top=4)
                    continue
                holder, box = self.details.row()
                box.addWidget(check, 0)
                label = QLabel(item["title"], holder)
                label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                box.addWidget(label, 1)
                view_btn.setFixedWidth(100)
                box.addWidget(view_btn, 0)
                edit_btn.setFixedWidth(70)
                box.addWidget(edit_btn, 0)

    def _on_cheat_toggled(self, path, key, checked):
        # keep both panels in step
        for stored, states in self.pending_cheat_selections.items():
            if key in states:
                states[key] = bool(checked)
        self.pending_cheat_selections.setdefault(path, {})[key] = bool(checked)
        name = key.split("-", 1)[-1]
        self._mark_unapplied("%s %s. Click 'Apply Changes' to save."
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
        elif mod_id in self.recomp.modules:
            self._show_recomp_module_details(mod_id)
        else:
            self._show_recomp_file_details(mod_id)

    def _show_recomp_module_details(self, name):
        self.details.clear()
        data = self.recomp.modules.get(name, {})
        binary = data.get("binary")
        folder = data.get("path") or ""
        full_path = redact_path(folder)

        self.details.sheet()
        self.details.sheet_header(
            name, enabled=self.module_enabled.get(name, data.get("enabled")),
            on_toggle=lambda: self._toggle_module(name),
            menu=[("Copy path", lambda: self._copy_mod_path(folder))])
        self.details.sheet_text("Native code that extends the recomp itself, "
                                "not the game.", colour=Colors.TEXT_MUTED,
                                wrap=True)
        self.details.sheet_group("Installed")
        self.details.sheet_fields([
            ("Folder", LocationRow(
                middle_ellipsis(full_path, 44), tooltip=full_path,
                on_copy=lambda: self._copy_mod_path(folder),
                on_open=(lambda: open_in_file_explorer(folder))
                if folder else None), {}),
            ("Binary", os.path.basename(binary) if binary
             else "missing (%s.dll)" % name,
             {"mono": bool(binary), "color": None if binary else Colors.CONFLICT}),
        ])
        if not binary:
            self.details.sheet_banner(
                "No binary in that folder, so the port logs it as missing "
                "and loads nothing.")

    def _toggle_module(self, name):
        # the row's tick carries the state; its signal marks Apply
        row = self.module_rows.get(name)
        if row is None or row.checkbox is None:
            return
        row.checkbox.setChecked(not row.checkbox.isChecked())
        self.show_details(name)

    def _show_recomp_mod_details(self, clean_name):
        self.details.clear()
        data = self.recomp.mods.get(clean_name, {})
        path = self.recomp.get_current_mod_path(clean_name) or ""
        display = self._display_name(clean_name, clean_name)
        raw = self._load_manifest_raw(clean_name)
        rule = self._load_mod_rules(clean_name)
        record = read_record(path) if path else None
        version = str((raw or {}).get("version")
                      or (rule.version if rule is not None else "")
                      or (record or {}).get("version") or "").strip()
        page = str((raw or {}).get("page_url")
                   or (rule.page_url if rule is not None else "")
                   or (record or {}).get("page_url") or "").strip()
        description = str((raw or {}).get("description")
                          or (rule.description if rule is not None else "")
                          or "").strip()
        enabled = self.mod_enabled.get(clean_name, True)

        # the page a mod came from, gamebanana or a github release
        byline = []
        authors = ", ".join(str(a) for a in ((raw or {}).get("authors") or ()))
        if rule is not None:
            authors = authors or ", ".join(rule.authors)
        if authors:
            byline.append("by " + authors)
        link = page_link(page) if page else None
        if link:
            byline.append(link)
        source = github_records.source(record)
        if source:
            repo = "%s/%s" % (source["owner"], source["repo"])
            byline.append(("GitHub: " + repo, "https://github.com/" + repo))
            if source.get("tag"):
                byline.append("Release: " + source["tag"])

        self.details.sheet()
        self.details.sheet_header(
            display, version=self._version_pill(version), enabled=enabled,
            on_toggle=lambda: self._toggle_recomp_mod(clean_name),
            menu=[("Check update", lambda: self._check_update(clean_name)),
                  ("Copy path", lambda: self._copy_mod_path(path)),
                  None,
                  ("Uninstall", lambda: self._delete_mod(clean_name))])
        self.details.sheet_byline(byline)
        if description:
            self.details.sheet_text(description, top=8, wrap=True)

        requires_rows, conflict_rows, _counts = self._rule_status_rows(rule)
        index_of = self._recomp_order_index()
        order = []
        if clean_name in index_of:
            order.append(("Order", "#%d of %d" % (
                index_of[clean_name] + 1, len(index_of)),
                {"tooltip": "Later mods win a shared .arc entry they "
                            "change differently."}))
        self.details.sheet_group("Dependencies")
        self.details.sheet_fields(
            self._dep_fields("Requires", requires_rows, "None")
            + self._dep_fields("Conflicts", conflict_rows, "None declared")
            + order + [("Load order", self._load_order_text(rule), {})])

        contents = []
        if data.get("has_romfs"):
            contents.append("romFS")
        if data.get("has_exefs"):
            contents.append("exefs")
        if data.get("has_plugins"):
            contents.append("forge plugin")
        if data.get("has_arc"):
            contents.append(".arc archive")
        self.details.sheet_group("Installed")
        self.details.sheet_fields([
            ("Location", LocationRow(
                middle_ellipsis(redact_path(path), 44), tooltip=redact_path(path),
                on_copy=lambda: self._copy_mod_path(path),
                on_open=lambda: open_in_file_explorer(path)), {}),
            ("Contents", ", ".join(contents) or "unknown", {}),
        ])

        view = self._recomp_conflict_view()
        conflicts = view.get(clean_name, {})
        if conflicts:
            self.details.sheet_group("%d conflicting file%s" % (
                len(conflicts), "" if len(conflicts) == 1 else "s"))
            self.details.sheet_text(
                "Recomp merges a shared .arc entry by entry; a later mod "
                "wins an entry it changes differently. Per-entry clashes "
                "are in grey.", colour=Colors.TEXT_MUTED, wrap=True)
            for rel_path in sorted(conflicts)[:40]:
                cell = conflicts[rel_path]
                rivals = cell["rivals"]
                winner = self._recomp_latest([clean_name] + rivals, index_of)
                state = ("yours is used" if winner == clean_name
                         else "%s is used" % winner)
                win_btn = QPushButton("Make mine win")
                win_btn.setFixedHeight(ACTION)
                win_btn.clicked.connect(
                    lambda _checked=False, m=clean_name, r=list(rivals):
                    self._recomp_make_win(m, r))
                self.details.sheet_block(SheetRow(
                    rel_path, mono=True, controls=[
                        self.details.sheet_tag("vs " + ", ".join(rivals)[:60]),
                        self.details.sheet_tag(
                            state, Colors.RESOLVED_CONFLICT
                            if winner == clean_name else Colors.CONFLICT),
                        win_btn]))
                for key, key_rivals in list(cell["entries"].items())[:8]:
                    if key is None or not key_rivals:
                        continue
                    key_winner = self._recomp_latest(
                        [clean_name] + key_rivals, index_of)
                    self.details.sheet_text(
                        "%s  vs %s  \u2192 %s"
                        % (self._entry_label(key), ", ".join(key_rivals),
                           "yours" if key_winner == clean_name
                           else key_winner + "'s"),
                        mono=True, colour=Colors.TEXT_MUTED)
            if len(conflicts) > 40:
                self.details.sheet_text("(%d more not shown)" % (
                    len(conflicts) - 40), colour=Colors.TEXT_MUTED)
        else:
            self.details.sheet_group("Conflicting Files")
            self.details.sheet_text("No conflicts detected for this mod.",
                                    colour=Colors.TEXT_MUTED)

        mergeable = self.recomp.mergeable_arcs.get(clean_name, {})
        mergeable = {rel: [r for r in rivals if self._recomp_enabled(r)]
                     for rel, rivals in mergeable.items()}
        mergeable = {rel: rivals for rel, rivals in mergeable.items() if rivals}
        if mergeable:
            self.details.sheet_group(
                "%d mergeable .arc file%s (no manual merge needed)"
                % (len(mergeable), "" if len(mergeable) == 1 else "s"))
            for rel_path in sorted(mergeable)[:12]:
                self.details.sheet_block(SheetRow(
                    rel_path, mono=True, controls=[self.details.sheet_tag(
                        "merges with " + ", ".join(mergeable[rel_path]))]))

    def _toggle_recomp_mod(self, mod_id):
        self._recomp_mod_toggled(mod_id, not self.mod_enabled.get(mod_id, True))
        self.show_details(mod_id)

    @staticmethod
    def _entry_label(key):
        if not key:
            return "(whole file)"
        return "%s [type %d]" % (key[0], key[1])

    def _show_recomp_cheat_details(self, clean_name):
        self.details.clear()
        data = self.recomp.cheats.get(clean_name, {})
        raw_name = data.get("raw_name") or clean_name + ".txt"
        path = data.get("path") or os.path.join(
            self.recomp.cheats_path, raw_name)
        enabled = bool(data.get("enabled", True))
        self.details.heading("Cheat: %s" % clean_name)
        rows = [
            ("Folder", redact_path(self.recomp.cheats_path)),
            ("File", raw_name),
            ("State", "Enabled" if enabled
             else "Disabled (file name starts with '_')"),
        ]
        self.details.card(rows, open_path=self.recomp.cheats_path,
                          open_label="Open cheats folder")

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except Exception as exc:
            self.details.hint("Could not read this cheat: %s"
                              % redact_path(str(exc)))
            return

        entries = [(title, text[start:end])
                   for title, start, end in self._cheat_block_spans(text)]
        if not entries:
            self.details.hint("No [Title] header in this file, so there is no "
                              "entry to list or edit. The recomp reads the hex "
                              "code lines as they are.")
        else:
            self.details.label("Cheat entries (%d)" % len(entries), bold=True)
            for title, block in entries:
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
                    lambda _checked=False, n=clean_name, t=title:
                    self._edit_recomp_cheat_block(n, t))
                box.addWidget(edit_btn, 0)
            self.details.hint("The recomp has no per-entry switch: the whole "
                              "file is on or off, and off means a '_' in front "
                              "of the file name. Tick it in the Cheats section, "
                              "then Apply.")

        self.details.label("Cheat code", bold=True)
        self.details.code_area(text, height=220)
        if enabled:
            self.details.hint("A {Master} block in this file runs before the "
                              "other cheats and stays on in the recomp's own "
                              "settings menu.")

    def _cheat_block_spans(self, text):
        # [Title] starts a block; spans keep the file layout intact
        spans = []
        title = None
        start = 0
        offset = 0
        for line in str(text).splitlines(keepends=True):
            match = re.match(r"^\s*\[([^\]]+)\]", line)
            if match:
                if title is not None:
                    spans.append((title, start, offset))
                title = match.group(1).strip()
                start = offset
            offset += len(line)
        if title is not None:
            spans.append((title, start, len(text)))
        return spans

    def _edit_recomp_cheat_block(self, clean_name, title):
        data = self.recomp.cheats.get(clean_name, {})
        path = data.get("path") or ""
        if not path or not os.path.isfile(path):
            dialogs.warn(self, "Not Found",
                         "That cheat file is gone; scan the folder again.")
            return
        try:
            with open(path, "r", encoding="utf-8",
                      errors="replace") as handle:
                text = handle.read()
        except Exception as exc:
            dialogs.error(self, "Read Failed", redact_path(str(exc)))
            return
        target = None
        for span in self._cheat_block_spans(text):
            if span[0] == title:
                target = span
                break
        if target is None:
            dialogs.warn(self, "Not Found",
                         "That cheat entry no longer exists; reopen the cheat.")
            return
        block = text[target[1]:target[2]]
        edited = dialogs.CheatCodeDialog.edit(self, title, block.rstrip("\r\n"))
        if edited is None or edited.strip() == block.strip():
            return
        if not re.match(r"^\s*\[", edited):
            edited = "[%s]\n%s" % (title, edited)
        problems = self._recomp_cheat_problems(edited)
        if problems:
            dialogs.error(self, "Cheats",
                          "That edit is not a cheat the recomp can read:\n\n%s"
                          % "\n".join(problems))
            return
        merged = text[:target[1]] + edited.rstrip("\r\n") + "\n"
        rest = text[target[2]:]
        merged += ("\n" + rest.lstrip("\r\n")) if rest.strip() else ""
        try:
            atomic_write_text(path, merged)
        except Exception as exc:
            dialogs.error(self, "Write Failed", redact_path(str(exc)))
            return
        self._status("Saved cheat entry '%s'." % title)
        self._show_recomp_cheat_details(clean_name)

    def _show_recomp_file_details(self, key):
        plugin = next((item for item in self.recomp.plugins
                       if (item["mod"], item["rel_path"]) == key), None)
        if plugin is not None:
            self._show_recomp_plugin_details(plugin)
            return
        self.details.clear()
        entry = next((item for item in self.recomp.patches
                      if (item["mod"], item["rel_path"]) == key), None)
        if entry is None:
            self.details.heading("Details unavailable")
            self.details.hint("Re-scan the folder to refresh this entry.")
            return
        self.details.heading("File: %s" % entry["filename"])
        row = self.patch_rows.get(key)
        enabled = (row.checkbox.isChecked()
                   if row is not None and row.checkbox is not None
                   else bool(entry["enabled"]))
        rows = [
            ("Mod", entry["mod"]),
            ("Relative path", entry["rel_path"]),
            ("Location", redact_path(entry["path"])),
            ("State", "Enabled" if enabled else "Disabled"),
        ]
        if entry.get("ignored_by_recomp"):
            rows.append(("Note", "Not loaded by the recomp"))
        self.details.card(rows, open_path=os.path.dirname(entry["path"]))

    def _show_recomp_plugin_details(self, entry):
        # a plugin presents the manifest of the release it came from
        self.details.clear()
        raw = entry.get("manifest") or {}
        name = self._plugin_name(entry)
        enabled = self._plugin_enabled((entry["mod"], entry["rel_path"]), entry)
        location = os.path.dirname(entry["path"])
        full_path = redact_path(location)
        rule = rules_store.rules_from_manifest(raw)
        requires_rows, conflict_rows, _counts = self._rule_status_rows(rule)

        mod_folder = self.recomp.get_current_mod_path(entry["mod"]) or ""
        record = read_record(mod_folder) if mod_folder else None
        page = str(raw.get("page_url") or "").strip()
        record_page = str((record or {}).get("page_url") or "")
        byline = []
        authors = ", ".join(str(a) for a in (raw.get("authors") or []))
        if authors:
            byline.append("by " + authors)
        # the install record's page only matters when it differs
        for url in (page, record_page if record_page != page else ""):
            link = page_link(url) if url else None
            if link:
                byline.append(link)

        self.details.sheet()
        self.details.sheet_header(
            name, version=self._version_pill(str(raw.get("version") or "")),
            enabled=enabled, on_toggle=lambda: self._toggle_plugin(entry),
            menu=[("Check update", lambda: self._check_update(entry["mod"])),
                  ("Copy path", lambda: self._copy_mod_path(location)),
                  ("Edit Plugin INI", lambda: self._open_plugin_ini(entry)),
                  None,
                  ("Uninstall", lambda: self._delete_mod(entry["mod"]))])
        self.details.sheet_byline(byline)
        ident = str(raw.get("id") or "").strip()
        if ident:
            self.details.sheet_text(ident, mono=True, colour=Colors.TEXT_MUTED)
        description = str(raw.get("description") or "").strip()
        if description:
            self.details.sheet_text(description, top=8, wrap=True)

        self.details.sheet_group("Dependencies")
        self.details.sheet_fields(
            self._dep_fields("Requires", requires_rows, "None")
            + self._dep_fields("Conflicts", conflict_rows, "None declared")
            + [("Load order", self._load_order_text(rule), {})])

        self.details.sheet_group("Installed")
        self.details.sheet_fields([
            ("Type", "Forge plugin (.nro)", {}),
            ("File", entry["filename"], {"mono": True}),
            ("Location", LocationRow(
                middle_ellipsis(full_path, 44), tooltip=full_path,
                on_copy=lambda: self._copy_mod_path(location),
                on_open=lambda: open_in_file_explorer(location)), {}),
        ])
        if entry.get("ignored_by_recomp"):
            self.details.sheet_banner(
                "Not loaded: the recomp reads .nro files only from "
                "romfs/nativeNX/plugins/")

        # plugin inis live beside the save, not next to the .nro
        ini_folder = plugin_save_dir(self.recomp.root_path)
        matched, _all_names = plugin_ini_names(
            ini_folder, entry["filename"])
        self.details.sheet_group("Plugin config")
        self.details.sheet_fields([
            ("INI file", matched[0] if matched else "(no INI yet)",
             {"mono": bool(matched), "placeholder": not matched}),
            ("Folder", LocationRow(
                middle_ellipsis(redact_path(ini_folder), 44),
                tooltip=redact_path(ini_folder),
                on_copy=lambda: QApplication.clipboard().setText(ini_folder),
                on_open=lambda: open_in_file_explorer(ini_folder)), {}),
        ])

    def _open_plugin_ini(self, entry):
        folder = plugin_save_dir(self.recomp.root_path)
        matched, all_names = plugin_ini_names(folder, entry["filename"])
        names = matched or all_names
        if not names:
            dialogs.warn(
                self, "No INI",
                "No .ini files were found in the save folder:\n\n%s"
                % redact_path(folder))
            return
        name = names[0]
        if len(names) > 1:
            chosen, ok = QInputDialog.getItem(
                self, "Choose plugin INI",
                "Which INI do you want to edit?", names, 0, False)
            if not ok:
                return
            name = chosen
        IniEditorDialog(os.path.join(folder, name), self).exec()

    def _plugin_enabled(self, key, entry):
        # the tick is the live state; the scan value is the fallback
        row = self.plugin_rows.get(key)
        if row is not None and row.checkbox is not None:
            return row.checkbox.isChecked()
        return bool(entry.get("enabled"))

    def _toggle_plugin(self, entry):
        # the tick carries the state; its signal marks Apply and redraws
        row = self.plugin_rows.get((entry["mod"], entry["rel_path"]))
        if row is not None and row.checkbox is not None:
            row.checkbox.setChecked(not row.checkbox.isChecked())

    @staticmethod
    def _dep_fields(title, status_rows, empty):
        # rule rows -> one chip line per reference
        if not status_rows:
            return [(title, empty, {"placeholder": True})]
        fields = []
        for index, row in enumerate(status_rows):
            name, text, colour, ident = row
            mark = DEP_MARKS.get(colour, "\u2713")
            fields.append((title if index == 0 else "",
                           ChipCell([("%s %s" % (mark, ident or name), colour)],
                                    dep_note(text)), {}))
        return fields

    def _load_order_text(self, rule):
        if rule is None or not (rule.load_after or rule.load_before):
            return "No rules"
        _installed, enabled, rules, aliases, folders = self._rules_snapshot()
        parts = []
        if rule.load_after:
            parts.append("loads after " + self._rule_names(
                rule.load_after, rules, aliases, enabled, folders))
        if rule.load_before:
            parts.append("loads before " + self._rule_names(
                rule.load_before, rules, aliases, enabled, folders))
        return "; ".join(parts)

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
            self.tree.add_item(None, "plugin: " + self._plugin_name(entry),
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
        for name in sorted(analyzer.modules, key=str.lower):
            enabled = self.module_enabled.get(
                name, analyzer.modules[name].get("enabled"))
            self.tree.add_item(None, "module: " + name,
                               "Enabled" if enabled else "Disabled",
                               "module" if enabled else "disabled")

    # importing
    def _on_paths_dropped(self, paths):
        if self.current_state == "working" or not paths:
            return
        self._install_mod_items(list(paths))

    def _install_mod_items(self, items, gb_meta=None):
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

        # the checks walk the whole drop, so they run off the UI thread
        self._install_context = {"items": list(items),
                                 "gb_meta": gb_meta or {},
                                 "target_dir": target_dir}
        self.progress_header.setText("Checking Mods...")
        self.progress_detail.setText(
            "Reading archives, scripts and pack markers...")
        self.progress_bar.setRange(0, 0)
        self._set_state("working")
        run_in_thread(self, self._check_install_items,
                      self._install_context["items"],
                      self._arc_reference_root(), self.mode != "recomp",
                      on_done=self._on_install_checked,
                      on_error=self._on_install_check_error)

    @staticmethod
    def _check_install_items(items, reference_root, check_trimmed):
        # full trees and every .arc header, the slow part of a drop
        pack_hits = packs.scan_inputs(items)
        result = {"scripts": scan_paths(items),
                  "packs": pack_hits,
                  "pack_errors": [packs.pixelpack_error(h)
                                  for h in pack_hits],
                  "trimmed": []}
        if check_trimmed:
            result["trimmed"] = trimmed_arcs.scan_paths(items, reference_root)
        return result

    def _on_install_checked(self, result):
        if self._closing:
            return
        context = self._install_context
        if not context:
            self._set_state("idle")
            return
        if result.get("scripts") and not dialogs.ScriptRiskDialog.ask(
                self, result["scripts"]):
            self._cancel_install(
                "Install cancelled: the mod ships script files.")
            return
        if result.get("trimmed") and not dialogs.TrimmedArcDialog.ask(
                self, result["trimmed"]):
            self._cancel_install(
                "Install cancelled: the mod ships trimmed .arc files.")
            return
        if result.get("packs") and not dialogs.PackWarningDialog.ask(
                self, result["packs"]):
            # the 1337 line is shown in the status bar
            self._cancel_install(str(result["pack_errors"][0]))
            return
        self._install_context = None
        context["allow_scripts"] = bool(result.get("scripts"))
        try:
            self._build_install_jobs(context)
        except Exception as exc:
            self._cancel_install("")
            dialogs.error(self, "Install", str(exc))

    def _on_install_check_error(self, message):
        self._install_context = None
        self._cancel_install("")
        dialogs.error(self, "Install", message)

    def _cancel_install(self, status=""):
        self._install_context = None
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self._set_state("idle")
        if status:
            self._status(status)

    def _build_install_jobs(self, context):
        items = context["items"]
        gb_meta = context["gb_meta"]
        target_dir = context["target_dir"]
        record = gb_meta.get("record")
        profile = gb_meta.get("profile") or {}
        update_dir = gb_meta.get("update_dir")
        # gamebanana archives have to carry a manifest, a github release
        # is whatever the author attached
        require_manifest = bool(record and record.get("gb_mod_id"))
        jobs = []
        handled = False
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
                handled = True
                continue
            extension = os.path.splitext(base)[1].lower()
            if self.mode == "recomp":
                pack = self._recomp_cheat_archive_pack(item)
                if pack:
                    if not dialogs.confirm(
                            self, "Cheat Pack",
                            "%s holds %d cheat .txt file%s.\n\nInstall them "
                            "into cheats/ instead of mods/?"
                            % (base, len(pack), "" if len(pack) == 1 else "s")):
                        continue
                    for member, text in sorted(pack.items()):
                        self._save_recomp_cheat_pack(
                            member, text, member, refresh=False)
                    handled = True
                    continue
            if extension == ".7z" and not PY7ZR_SUPPORT:
                dialogs.error(self, "Install",
                              "Install 'py7zr' to open .7z archives.")
                continue
            stem = os.path.splitext(base)[0]
            kind = ("zip" if extension == ".zip" else
                    "7z" if extension == ".7z" else
                    "rar" if extension == ".rar" else "copy_tree")
            if self.mode == "recomp":
                dest_name = re.sub(r"^\d+_", "", stem).strip()
                if not dest_name:
                    continue
            else:
                dest_name = stem
            if update_dir and os.path.isdir(update_dir):
                commit_target = os.path.dirname(update_dir)
                commit_name = os.path.basename(update_dir)
            else:
                commit_target = target_dir
                commit_name = dest_name
                destination = os.path.join(target_dir, dest_name)
                if os.path.exists(destination):
                    if not dialogs.confirm(
                            self, "Mod Already Exists",
                            "'%s' already exists.\n\nOverwrite it?" % dest_name):
                        continue
            staging = tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=target_dir)
            self._install_staging.append(staging)
            jobs.append({"kind": kind, "src": item, "dest": staging,
                         "label": commit_name,
                         "entry_id": gb_meta.get("entry_id"),
                         "require_manifest": require_manifest,
                         "allow_scripts": bool(context.get("allow_scripts")),
                         "commit": {"target_dir": commit_target,
                                    "dest_name": commit_name, "record": record,
                                    "display_name": "" if update_dir else
                                    profile.get("name", "")}})

        if not jobs:
            if handled:
                # cheats landed directly; read them once the overlay is gone
                self._cancel_install("")
                self.run_scan()
            else:
                self._cancel_install("Nothing to install.")
            return
        self.progress_header.setText("Installing Mods...")
        self.progress_detail.setText("Preparing...")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        worker = InstallWorker(jobs)
        run_worker(self, worker,
                   on_done=self._on_install_finished,
                   on_error=self._on_install_error,
                   on_progress=self._on_install_progress)

    def _on_install_progress(self, message):
        total = max(message.get("total", 1), 1)
        index = message.get("index", 1)
        fraction = message.get("fraction")
        if fraction is None:
            fraction = index / total
        self.progress_bar.setValue(int(min(max(fraction, 0.0), 1.0) * 100))
        self.progress_detail.setText("Installing %s (%d/%d)"
                                     % (message.get("text", ""), index, total))

    def _on_install_finished(self, payload):
        installed = len(payload.get("done", []))
        mismatched = []
        for job in payload.get("done", []):
            kind = job.get("layout_kind")
            if self.mode == "recomp" and kind == "emulator":
                mismatched.append(job.get("label", ""))
            elif self.mode != "recomp" and kind == "recomp":
                mismatched.append(job.get("label", ""))
        self._install_staging = []
        self._set_state("idle")
        errors = payload.get("errors") or []
        service = getattr(self.window(), "gb_service", None)
        for job in payload.get("done", []):
            entry_id = job.get("entry_id")
            if entry_id is not None and service is not None:
                service.mark_installed(entry_id)
        if errors:
            dialogs.error(self, "Install Failed", "\n\n".join(errors))
            self.run_scan()
        if mismatched:
            dialogs.warn(self, "Mode Mismatch",
                         "These look like they belong to a different setup:\n%s"
                         % ", ".join(m for m in mismatched if m))
        if installed:
            self._status("Installed %d mod%s. Refreshing..."
                         % (installed, "" if installed == 1 else "s"))
            self.run_scan()
        elif not errors:
            self._status("Nothing was installed.")

    def _on_install_error(self, error_text):
        # the next scan sweeps whatever is left in staging
        self._install_staging = []
        self._set_state("idle")
        dialogs.error(self, "Install Failed", error_text)
        self.run_scan()

    def _install_downloaded(self, archive, meta):
        # archive handed over by the gb service
        if self._emulator_running():
            dialogs.warn(self, "Emulator Running",
                         "Close the emulator before installing this mod.")
            return
        if not archive or not os.path.exists(archive):
            dialogs.error(self, "Install", "Downloaded archive was not found.")
            return
        self._install_mod_items([archive], gb_meta=meta)

    # gamebanana hooks
    def _mod_record(self, mod_id):
        path = self._mod_folder(mod_id)
        if not path or not os.path.isdir(path):
            return None
        return read_record(path)

    def _open_gb_page(self, mod_id):
        record = self._mod_record(mod_id)
        if record and record.get("page_url"):
            webbrowser.open(record["page_url"])

    def _link_gb(self, mod_id):
        path = self._mod_folder(mod_id)
        if not path or not os.path.isdir(path):
            return
        url = dialogs.ask_text(self, "Link to GameBanana",
                               "Paste the mod's GameBanana page link:")
        if not url:
            return
        parsed = parse_link(url)
        if not parsed:
            dialogs.error(self, "Link Failed",
                          "That does not look like a GameBanana link.")
            return
        client = GameBananaClient()

        def fetch():
            return client.fetch_profile(parsed["mod_id"])

        def done(profile):
            file = pick_installable_file(profile, None)
            record = build_record(
                parsed["mod_id"], file["id"] if file else "",
                file["name"] if file else "",
                file.get("md5", "") if file else "",
                file.get("date", "") if file else "",
                profile.get("version", ""), known_ids_for(profile))
            write_record(path, record)
            self._status("Linked to '%s'." % profile.get("name", mod_id))
            self.run_scan()

        run_in_thread(self, fetch, on_done=done,
                      on_error=lambda exc: dialogs.error(
                          self, "Link Failed", str(exc)))

    def _check_update(self, mod_id):
        record = self._mod_record(mod_id)
        has_gb = bool(record and record.get("gb_mod_id"))
        has_gh = bool(github_records.source(record))
        if not has_gb and not has_gh:
            dialogs.info(self, "Updates",
                         "This mod has no GameBanana page or GitHub release "
                         "linked yet.")
            return
        if has_gb:
            self.check_updates(force=True, only=record.get("gb_mod_id"))
        if has_gh:
            source = github_records.source(record)
            self.check_github_updates(
                force=True,
                only=("%s/%s" % (source["owner"], source["repo"])).lower())

    def _update_mod(self, mod_id, file_id=None):
        record = self._mod_record(mod_id)
        if not record or not record.get("gb_mod_id"):
            dialogs.info(self, "GameBanana",
                         "This mod is not linked to a GameBanana page yet.")
            return
        if self._emulator_running():
            dialogs.warn(self, "Emulator Running",
                         "Close the emulator before updating this mod.")
            return
        existing = self._mod_folder(mod_id)
        if not existing or not os.path.isdir(existing):
            dialogs.error(self, "Update", "Mod folder was not found.")
            return
        service = getattr(self.window(), "gb_service", None)
        if service is None:
            return
        self._status("Updating '%s'..." % mod_id)
        service.install_from_url(
            record.get("page_url") or page_url(record["gb_mod_id"]),
            context={"update_mod_id": mod_id,
                     "want_file_id": str(file_id or "")})

    def _link_github(self, mod_id):
        # a repo or a release link, the tag we install is the one recorded
        path = self._mod_folder(mod_id)
        if not path or not os.path.isdir(path):
            return
        text = dialogs.ask_text(
            self, "Link to GitHub",
            "Paste the repository link (github.com/owner/repo):")
        if not text:
            return
        parsed = parse_repo(text)
        if not parsed:
            dialogs.error(self, "Link Failed",
                          "That does not look like a GitHub repository link.")
            return
        github = getattr(self.window(), "github", None)
        client = GitHubClient(getattr(github, "token", ""))

        def fetch():
            # failures come back as text, the thread wrapper reports tracebacks
            try:
                release, _meta = client.latest_release(
                    parsed["owner"], parsed["repo"], force=True)
            except GitHubError as exc:
                return {"error": str(exc)}
            return {"release": release}

        def done(result):
            if result.get("error"):
                dialogs.error(self, "Link Failed", result["error"])
                return
            release = result["release"]
            asset = pick_github_asset(release, "")
            if asset is None:
                dialogs.error(
                    self, "Link Failed",
                    "The newest release has no installable archive "
                    "(zip, 7z or rar).")
                return
            github_records.link(path, parsed["owner"], parsed["repo"],
                                release.get("tag", ""),
                                asset["name"])
            self._status("Linked to %s/%s at %s."
                         % (parsed["owner"], parsed["repo"],
                            release.get("tag", "") or "the newest release"))
            self.run_scan()

        run_in_thread(self, fetch, on_done=done,
                      on_error=lambda _exc: dialogs.error(
                          self, "Link Failed",
                          "Could not reach GitHub for that repository."))

    def _unlink_github(self, mod_id):
        path = self._mod_folder(mod_id)
        if path and github_records.unlink(path):
            self._status("Removed the GitHub link for '%s'." % mod_id)
            self.run_scan()

    def _check_github_update(self, mod_id):
        source = github_records.source(self._mod_record(mod_id))
        if not source:
            dialogs.info(self, "GitHub",
                         "This mod has no GitHub release linked yet.")
            return
        self.check_github_updates(
            force=True,
            only=("%s/%s" % (source["owner"], source["repo"])).lower())

    def _update_from_github(self, mod_id):
        # same download + install path as gamebanana, different record
        github = getattr(self.window(), "github", None)
        if github is None:
            return
        if self._emulator_running():
            dialogs.warn(self, "Emulator Running",
                         "Close the emulator before updating this mod.")
            return
        existing = self._mod_folder(mod_id)
        if not existing or not os.path.isdir(existing):
            dialogs.error(self, "Update", "Mod folder was not found.")
            return
        plan = github.prepare_install(mod_id)
        if not plan:
            dialogs.info(self, "GitHub",
                         "No GitHub release is pending for this mod.")
            return
        plan["record"] = github_records.keep_gamebanana(existing,
                                                        plan["record"])
        service = getattr(self.window(), "gb_service", None)
        if service is None:
            return
        self._status("Updating '%s' from GitHub..." % mod_id)
        service.install_archive(**plan)

    def _update_from_list(self, source, folder_id, file_id=""):
        # the updates dialog reports the row it acted on
        if source == "github":
            self._update_from_github(folder_id)
        else:
            self._update_mod(folder_id, file_id)

    def check_updates(self, force=True, only=None):
        # refresh the badges, force ignores the 24h gate
        updater = getattr(self.window(), "updater", None)
        root = self._updates_root()
        if updater is None or not root:
            if force:
                self._status("Select a mods folder first.")
            return
        if updater.busy():
            if force:
                self._status("An update check is already running.")
            return
        started = updater.check(self.mode, root, self._update_records(),
                                force=force, only=only)
        if force and not started:
            self._status("Nothing to check on GameBanana right now.")
        elif force:
            self._status("Checking GameBanana for updates...")

    def _maybe_check_updates(self):
        # after a scan, at most once per day
        self.check_updates(force=False)
        self.check_github_updates(force=False)

    def check_github_updates(self, force=True, only=None):
        # the release side, only for mods with a repo in their sidecar
        github = getattr(self.window(), "github", None)
        root = self._updates_root()
        if github is None or not root:
            if force:
                self._status("Select a mods folder first.")
            return
        if github.busy():
            if force:
                self._status("A GitHub check is already running.")
            return
        started = github.check(self.mode, root, self._github_records(),
                               force=force, only=only)
        if force and not started:
            self._status("Nothing to check on GitHub right now.")
        elif force:
            self._status("Checking GitHub for updates...")

    def _update_records(self):
        # the rows on screen, whatever container they sit in
        records = {}
        for mod_id in list(self.mod_rows):
            folder = self._mod_folder(mod_id)
            record = read_record(folder) if folder else None
            if record and record.get("gb_mod_id"):
                records[mod_id] = record
        return records

    def _github_records(self):
        # rows that carry a github release source
        records = {}
        for mod_id in list(self.mod_rows):
            folder = self._mod_folder(mod_id)
            record = read_record(folder) if folder else None
            if github_records.source(record):
                records[mod_id] = record
        return records

    def _updates_root(self):
        if self.mode == "recomp":
            return self.recomp.mods_path or ""
        return self.emulator.mods_path or ""

    def refresh_update_badges(self):
        # every mode shows the same badges, gamebanana wins when both know
        updater = getattr(self.window(), "updater", None)
        github = getattr(self.window(), "github", None)
        states = dict(updater.badges()) if updater is not None else {}
        if github is not None:
            for mod_id, state in github.badges().items():
                if not states.get(mod_id, ("", "none"))[0]:
                    states[mod_id] = state
        for mod_id, row in self.mod_rows.items():
            text, kind = states.get(mod_id, ("", "none"))
            if hasattr(row, "set_badge"):
                row.set_badge(text, kind)
        self._refresh_updates_btn()

    def _refresh_updates_btn(self):
        # the button opens the list, so both sources count here
        updater = getattr(self.window(), "updater", None)
        github = getattr(self.window(), "github", None)
        summary = (updater.summary if updater is not None else {}) or {}
        gh = (github.summary if github is not None else {}) or {}
        pending = (summary.get("updates", 0) + summary.get("choices", 0)
                   + gh.get("updates", 0))
        self.updates_btn.setText(
            "%d update%s" % (pending, "" if pending == 1 else "s")
            if pending else "Updates")
        linked = summary.get("linked", 0) + gh.get("linked", 0)
        self.updates_btn.setToolTip(
            "%d linked mod%s" % (linked, "" if linked == 1 else "s"))

    def show_updates(self):
        updater = getattr(self.window(), "updater", None)
        if updater is None:
            return
        github = getattr(self.window(), "github", None)
        dialog = dialogs.UpdatesDialog(
            self, updater,
            check=lambda: (self.check_updates(True),
                           self.check_github_updates(True)),
            github=github)
        dialog.exec()
        request = dialog.request
        dialog.deleteLater()
        if request:
            self._update_from_list(*request)
        self.refresh_update_badges()

    def _sweep_staging(self):
        # clean leftovers before the next scan; deletion runs in the
        # background so a 2 GB staging tree cannot stall the scan
        if self.mode == "recomp":
            dirs = [self.recomp.mods_path] if self.recomp.mods_path else []
        else:
            dirs = [self.emulator.mods_path] if self.emulator.mods_path else []
        for directory in dirs:
            recover_interrupted(directory)
            threading.Thread(target=sweep_dir, args=(directory,),
                             daemon=True).start()

    def _emulator_running(self):
        if self.mode == "recomp":
            return any(is_process_running(n) for n in self.recomp.EXE_NAMES)
        names = ("ryujinx",) if self.mode == "ryujinx" else ("eden",)
        return any(is_process_running(n) for n in names)

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
            if not self.recomp.root_path:
                dialogs.error(self, "Cheats", "Select a Recomp folder first.")
                return
            name, body = dialogs.ImportCheatDialog.ask(self)
            if body is None:
                return
            self._save_recomp_cheat_pack(
                name or "Imported Cheat", body, "the paste box")
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
        if name.lower() == "_off.txt":
            dialogs.info(self, "Cheats",
                         "'_off.txt' is the recomp's own per-cheat off list, "
                         "not a cheat pack.\n\nTick the cheats here and Apply "
                         "to add or drop a file's '_' prefix.")
            return
        if name.startswith("_"):
            name = name[1:]
        self._save_recomp_cheat_pack(name, content, name)

    def _recomp_cheat_problems(self, text):
        # what the recomp loader actually accepts
        problems = []
        blocks = self._parse_cheat_blocks(text)
        if not blocks:
            return ["No '[Cheat Name]' block found."]
        for title, body in blocks.items():
            codes = [line.strip() for line in body.splitlines()[1:]
                     if line.strip() and not line.strip().startswith(("#", "//"))]
            if not any(re.match(r"^[0-9A-Fa-f]{8}\s+[0-9A-Fa-f]{8}", line)
                       for line in codes):
                problems.append("'%s' has no 8-hex code words." % title)
        return problems[:3]

    def _save_recomp_cheat_pack(self, name, text, source, refresh=True):
        # one .txt per pack, enabled (no '_' prefix)
        if not self.recomp.root_path:
            dialogs.error(self, "Cheats", "Select a Recomp folder first.")
            return
        problems = self._recomp_cheat_problems(text)
        if problems:
            dialogs.error(self, "Cheats",
                          "%s is not a cheat the recomp can read:\n\n%s\n\n"
                          "Cheats use [Cheat Name] headers and 8-hex code "
                          "words, one per line." % (source, "\n".join(problems)))
            return
        stem = os.path.splitext(str(name or "").strip())[0].lstrip("_")
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", stem).strip(" .")
        filename = (stem or "Imported Cheat") + ".txt"
        target = os.path.join(self.recomp.cheats_path, filename)
        if os.path.exists(target) and not dialogs.confirm(
                self, "Cheat Exists",
                "'%s' already exists.\n\nOverwrite it?" % filename):
            return
        try:
            os.makedirs(self.recomp.cheats_path, exist_ok=True)
            atomic_write_text(target, text.rstrip("\r\n") + "\n")
        except Exception as exc:
            dialogs.error(self, "Cheats", "Could not write '%s':\n%s"
                          % (filename, redact_path(str(exc))))
            return
        self._status("Cheat '%s' installed. Refreshing..." % filename)
        if refresh:
            self.run_scan()

    def _recomp_cheat_archive_pack(self, path):
        # a zip/7z that holds only .txt cheats at its top level
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".zip", ".7z"):
            return None
        try:
            if ext == ".zip":
                import zipfile
                with zipfile.ZipFile(path) as archive:
                    names = [n for n in archive.namelist() if not n.endswith("/")]
                if not self._looks_like_cheat_names(names):
                    return None
                with zipfile.ZipFile(path) as archive:
                    texts = {n: archive.read(n).decode("utf-8", "replace")
                             for n in names}
            else:
                if not PY7ZR_SUPPORT:
                    return None
                import py7zr
                import shutil
                import tempfile
                with py7zr.SevenZipFile(path) as archive:
                    names = [n for n in archive.getnames() if not n.endswith("/")]
                if not self._looks_like_cheat_names(names):
                    return None
                # py7zr 1.x has no in-memory read, so unpack somewhere safe
                work = tempfile.mkdtemp(prefix="dreamsort-cheats-")
                try:
                    with py7zr.SevenZipFile(path) as archive:
                        archive.extractall(path=work)
                    texts = {}
                    for name in names:
                        target = os.path.join(work, name)
                        if not os.path.isfile(target):
                            continue
                        with open(target, "r", encoding="utf-8",
                                  errors="replace") as handle:
                            texts[name] = handle.read()
                finally:
                    shutil.rmtree(work, ignore_errors=True)
        except Exception:
            return None
        if not texts:
            return None
        if not any(self._parse_cheat_blocks(text) for text in texts.values()):
            return None
        return texts

    def _looks_like_cheat_names(self, names):
        # flat .txt only, and no name that could escape the temp folder
        if not names:
            return False
        for name in names:
            if not name or name in (".", ".."):
                return False
            if any(char in name for char in '\\/:*?"<>|'):
                return False
            if not name.lower().endswith(".txt"):
                return False
        return True

    def clear_all_cheats(self):
        if self.mode == "eden":
            if not self.eden_cheat_rows:
                self._status("No cheats loaded.")
                return
            if not dialogs.confirm(self, "Disable All",
                                   "Disable every cheat?\n\n"
                                   "Click 'Apply Changes' to save."):
                return
            for row in self.eden_cheat_rows.values():
                row.checkbox.setChecked(False)
            self._status("All cheats disabled. Click 'Apply Changes' to save.")
            return
        if self.mode == "recomp":
            if not self.recomp.cheats:
                self._status("No cheats loaded.")
                return
            if not dialogs.confirm(self, "Disable All",
                                   "Disable every cheat?\n\n"
                                   "Click 'Apply Changes' to save."):
                return
            for row in self.cheat_rows.values():
                row.checkbox.setChecked(False)
            self._status("All cheats disabled. Click 'Apply Changes' to save.")
            return
        if not self.cheat_files_model:
            self._status("No cheat files loaded.")
            return
        if not dialogs.confirm(self, "Disable All",
                               "Disable all cheat entries?\n\nClears pending "
                               "selections. You must click 'Apply Changes' "
                               "to save."):
            return
        self._load_cheat_model()
        for states in self.pending_cheat_selections.values():
            for key in states:
                states[key] = False
        if self.current_details_mod in self.emulator.cheat_only_mods:
            self.show_details(self.current_details_mod)
        self._status("All cheats cleared. Click 'Apply Changes' to save.")

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
                         "Tick cheats, then click Apply Changes.")
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
                               "You must click 'Apply Changes' to save."):
            return
        count = 0
        for mod_id, row in self.mod_rows.items():
            if row.checkbox is None:
                continue
            if self.mode == "ryujinx" and mod_id in self.emulator.cheat_only_mods:
                continue
            self._set_mod_enabled(mod_id, False)
            count += 1
        self._after_order_change("Disabled %d mod%s. Click 'Apply Changes'."
                                 % (count, "" if count == 1 else "s"))

    # apply
    def apply_changes(self):
        if self.current_state == "working" or self._scanning:
            return
        if not self._pack_gate("Apply"):
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

        rule_notes = self._rule_gate()
        if rule_notes is None:
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
        if live_conflicts or rule_notes:
            sample = "\n".join("  \u2022 " + name for name in
                               sorted(live_conflicts)[:10])
            rule = ("Later mods win." if self._conflict_later_wins()
                    else "Earlier mods win.")
            text = ""
            if live_conflicts:
                text += ("Some mods share files. %s\n\n%s\n\n"
                         % (rule, sample))
            if rule_notes:
                text += rule_notes + "\n\n"
            text += "Apply the new load order now?"
            if not dialogs.confirm(self, "Confirm Apply", text):
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

        rule_notes = self._rule_gate()
        if rule_notes is None:
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
        module_states = {name: row.checkbox.isChecked()
                         for name, row in self.module_rows.items()
                         if row.checkbox is not None}

        enabled_mods = sum(1 for value in mod_enabled.values() if value)
        disabled_mods = len(mod_enabled) - enabled_mods
        enabled_cheats = sum(1 for value in cheat_states.values() if value)
        enabled_patches = sum(1 for value in patch_states.values() if value)
        enabled_plugins = sum(1 for value in plugin_states.values() if value)
        enabled_modules = sum(1 for value in module_states.values() if value)

        if not dialogs.confirm(
                self, "Confirm Apply",
                ("Apply changes to MHGU Recomp?\n\n"
                 "Enabled mods: %d (disabled: %d)\n"
                 "Enabled cheats: %d\n"
                 "Enabled patches: %d\n"
                 "Enabled plugins: %d\n"
                 "Enabled engine modules: %d\n\n"
                 "This will:\n"
                 "  \u2022 write mods/load_order.txt (native settings-menu format)\n"
                 "  \u2022 write engine_modules/enabled.txt (module load list)\n"
                 "  \u2022 rename cheat .txt files with '_' to match their state\n"
                 "  \u2022 move patches/plugins into/out of a 'disabled/' subfolder\n"
                 "  \u2022 migrate any old mods_disabled/ folder back into mods/\n\n"
                 "No mod folder is renamed. Restart MHGU Recomp to apply."
                 % (enabled_mods, disabled_mods, enabled_cheats,
                    enabled_patches, enabled_plugins, enabled_modules))
                + self._recomp_conflict_warning()
                + ("\n\n" + rule_notes if rule_notes else "")):
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
                      plugin_states, bridge, module_states=module_states,
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
            self._clear_unapplied()
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
        if not self._pack_gate("Launch"):
            return
        if self.mode == "eden":
            self._launch_eden()
            return
        if self.mode == "recomp":
            self._launch_recomp()
        else:
            self._launch_ryujinx()

    def _launch_eden(self):
        exe = self.eden_exe_path
        if not exe or not os.path.exists(exe):
            exe = self._guess_eden_exe()
        if not exe:
            exe = dialogs.pick_open_file(self, "Select Eden executable",
                                         "*.exe *.app")
            if not exe:
                return
        if exe != self.eden_exe_path:
            self.eden_exe_path = exe
            self.save_config()
        self._refresh_game_sign()
        try:
            launch_eden(exe)
        except Exception as exc:
            dialogs.error(self, "Launch Failed", str(exc))
            return
        if not self._scanned_path_matches_entry():
            self.run_scan()

    def _guess_eden_exe(self):
        # portable layouts keep the exe a few levels above the load folder
        base = self.emulator.mods_path or self._get_current_path() or ""
        for _level in range(4):
            if not base:
                break
            for name in ("eden.exe", "eden"):
                candidate = os.path.join(base, name)
                if os.path.isfile(candidate):
                    return candidate
            parent = os.path.dirname(base.rstrip("\\/"))
            if parent == base:
                break
            base = parent
        return ""

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
            process, _command = launch_recomp(exe)
        except Exception as exc:
            dialogs.error(self, "Launch Failed", str(exc))
            return
        # watch for the new exit-code handling
        watcher = ProcessWatcher(self)
        watcher.process_exited.connect(self._on_recomp_process_exited)
        watcher.watch(process)
        self._recomp_watcher = watcher
        if not self._scanned_path_matches_entry():
            self.run_scan()

    def _on_recomp_process_exited(self, code):
        if exit_codes.is_quiet(code):
            if code == 31:
                self._status("The recomp closed to restart.")
            return
        root = self.recomp.root_path or self._saved_paths.get("recomp", "")
        title, colour, meaning = exit_codes.describe(code)
        excerpt = self._recomp_log_tail(root, code, title)
        dialog = dialogs.ExitCodeDialog(
            code, title, colour, meaning, excerpt,
            on_open_folder=lambda: open_in_file_explorer(root) if root else None,
            on_analyze=self._analyze_current_log, parent=self)
        app_logging.info("Recomp exited with code %s (%s)" % (code, title))
        dialog.exec()

    def _recomp_log_tail(self, root, code, title):
        if root:
            path = os.path.join(root, "log.txt")
            try:
                with open(path, "rb") as handle:
                    handle.seek(0, os.SEEK_END)
                    size = handle.tell()
                    handle.seek(max(0, size - 4096))
                    text = handle.read().decode("utf-8", errors="replace")
                lines = [line.strip() for line in text.splitlines()
                         if line.strip()]
                for line in reversed(lines):
                    if "[exit]" in line:
                        return line
                if lines:
                    return lines[-1]
            except OSError:
                pass
        return "[exit] code %s (%s)" % (exit_codes.label(code), title.lower())

    def _analyze_current_log(self):
        root = self.recomp.root_path or self._saved_paths.get("recomp", "")
        if not root:
            dialogs.info(
                self, "Recomp log.txt",
                "Set the MHGU Recomp folder first so dreamSort knows where "
                "log.txt lives.")
            return
        report = recomp_log.analyze(root)
        if not report["found"]:
            dialogs.info(
                self, "Recomp log.txt",
                report["summary"] + "\n\nExpected at:\n"
                + redact_path(report["path"]))
            return
        dialogs.RecompLogDialog.show_report(self, report)

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
        self._refresh_game_sign()
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

    def _auto_find_mods(self):
        if self.mode == "recomp":
            self._auto_find_recomp_root()
        else:
            self._auto_find_ryujinx_mods()

    def _auto_find_recomp_root(self):
        # the port keeps mhgurecomp next to mods/ and cheats/
        home = os.path.expanduser("~")
        user_roots = []
        program_roots = []

        if self.recomp_exe_path:
            user_roots.append(os.path.dirname(self.recomp_exe_path))
        current = self._get_current_path()
        if current:
            user_roots.append(current)
        try:
            user_roots.append(os.path.dirname(os.path.abspath(sys.argv[0])))
        except Exception:
            pass
        for folder in ("Desktop", "Downloads", "Download", "Documents", "Games"):
            user_roots.append(os.path.join(home, folder))
        for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(env, "")
            if base:
                program_roots.append(base)

        # the walk runs on a worker thread so the GUI keeps painting
        self._autofind_cancel = threading.Event()
        dialog = AutoFindProgressDialog(self)
        self._autofind_dialog = dialog
        run_in_thread(
            self, autofind_job.search_recomp_roots,
            user_roots, program_roots, RecompAnalyzer.EXE_NAMES,
            self._autofind_cancel,
            on_done=self._on_autofind_done,
            on_error=self._on_autofind_error,
            on_progress=dialog.update_progress)
        dialog.exec()

    def _on_autofind_done(self, result):
        dialog = getattr(self, "_autofind_dialog", None)
        if dialog is not None:
            dialog.accept()
        if result.get("cancelled"):
            return
        # structure validation stays on the GUI thread
        valid = []
        for path in result.get("found", []):
            ok, _message, _suggested = self.recomp.structure_status(path)
            if ok and path not in valid:
                valid.append(path)
        self._finish_autofind(valid)

    def _on_autofind_error(self, error_text):
        dialog = getattr(self, "_autofind_dialog", None)
        if dialog is not None:
            dialog.accept()
        self._status("Auto-find failed.")
        dialogs.error(self, "Auto-Find Failed", error_text)

    def _finish_autofind(self, found):
        if not found:
            self._status("Auto-find failed: set the MHGU Recomp folder manually.")
            dialogs.warn(self, "Not Found",
                         "Could not find mhgurecomp.\n\n"
                         "Use the folder button to select the MHGU Recomp root: "
                         "the folder that holds mhgurecomp, mods/ and cheats/.")
            return
        if len(found) == 1:
            self._update_path_display(found[0])
            self.run_scan()
            return
        chosen = dialogs.FolderPickerDialog.ask(
            self, found, title="Choose MHGU Recomp Folder",
            caption="Multiple MHGU Recomp folders found. Pick one:")
        if chosen:
            self._update_path_display(chosen)
            self.run_scan()

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
        menu.addAction("Save layout profile...", self.save_profile)
        current = self.profile_combo.currentText()
        if current and current != "(no profile)":
            menu.addAction("Load layout '%s'" % current,
                           lambda: self.load_profile(current))
            menu.addAction("Delete layout '%s'" % current,
                           lambda: self.delete_profile(current))
        menu.addSeparator()
        menu.addAction("Export layout profiles...", self.export_profiles)
        menu.addAction("Import layout profiles...", self.import_profiles)
        menu.addSeparator()
        menu.addAction("Mod sets (matched by md5)...", self._open_mod_profiles)
        menu.addAction("Downloads...", self._open_downloads_dialog)
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
            self._status("Scan a folder before saving a layout profile.")
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
        self._status("Layout profile '%s' saved." % name)

    def load_profile(self, name, refresh_combo=True):
        profile = self.profiles.get(name)
        if not profile:
            self._status("Layout profile '%s' not found." % name)
            return
        container = self._reorder_container()
        if container is None:
            self._status("Scan a folder before loading a layout profile.")
            return
        known = set(container.order_ids())
        order = [mod_id for mod_id in profile.keys() if mod_id in known]
        if order:
            container.reorder_to(order)
        for mod_id, enabled in profile.items():
            if mod_id in known:
                self._set_mod_enabled(mod_id, bool(enabled), emit=False)
        self._after_order_change("Layout profile '%s' loaded. Click 'Apply "
                                 "Changes' to save." % name)
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
        self._status("Layout profile '%s' deleted." % name)

    def export_profiles(self):
        if not self.profiles:
            self._status("No layout profiles to export.")
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
        self._status("Layout profiles exported to %s" % redact_path(path))

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
        self._status("Imported %d layout profile(s)." % len(profiles))

    # rules: manifests, overrides and validation

    def _load_manifest_raw(self, mod_id):
        if mod_id in self._manifest_cache:
            return self._manifest_cache[mod_id]
        folder = self._mod_folder(mod_id)
        data = None
        if folder:
            data, _warnings = rules_manifest.read_manifest(folder)
        self._manifest_cache[mod_id] = data
        return data

    def _load_mod_rules(self, mod_id):
        if mod_id in self._rules_cache:
            return self._rules_cache[mod_id]
        raw = self._load_manifest_raw(mod_id)
        rules = rules_store.rules_from_manifest(raw) if raw else None
        self._rules_cache[mod_id] = rules
        return rules

    def _rules_snapshot(self):
        # identities, not folder names: a manifest id usually differs from
        # the folder it sits in, and a dependency can be a forge plugin
        installed, enabled = set(), set()
        rules = dict(rules_store.SEED_RULES)
        aliases = {}
        folders = {}
        for mod_id in self._order_ids():
            on = self._is_mod_enabled(mod_id)
            mod_rules = self._load_mod_rules(mod_id)
            canonical = mod_rules.mod_id if mod_rules is not None else mod_id
            if mod_rules is not None:
                rules[canonical] = mod_rules
            folder = self._mod_folder(mod_id)
            folders.setdefault(canonical, folder)
            folders.setdefault(mod_id, folder)
            for identity in (mod_id, canonical, clean_folder(mod_id),
                             clean_folder(canonical)):
                if not identity:
                    continue
                installed.add(identity)
                if on:
                    enabled.add(identity)
                aliases.setdefault(identity, canonical)
            aliases[canonical] = canonical
            record = read_record(folder) if folder else None
            if record and record.get("gb_mod_id"):
                aliases[str(record["gb_mod_id"])] = canonical
        for entry in self._forge_plugin_identities():
            identity, path, on, plugin_raw = entry
            rules.setdefault(identity, ModRules(
                mod_id=identity,
                version=str(plugin_raw.get("version") or "").strip() or None,
                name=str(plugin_raw.get("name") or "").strip()
                or os.path.basename(path)))
            folders.setdefault(identity, path)
            installed.add(identity)
            if on:
                enabled.add(identity)
            aliases.setdefault(identity, identity)
            aliases.setdefault(clean_folder(identity), identity)
        rules = rules_store.merge_overrides(rules, self.rules_overrides)
        # resolve leftover refs by their name tail: manifests may name the
        # dependency by its page id while the folder or plugin differs
        for rule in list(rules.values()):
            for ref in list(rule.requires or ()) + list(rule.conflicts or ()):
                if ref in aliases:
                    continue
                match = self._match_identity(ref, folders)
                if match:
                    aliases[ref] = match
        return installed, enabled, rules, aliases, folders

    def _forge_plugin_identities(self):
        # a forge plugin can satisfy a dependency that ships as a .nro
        if self.mode != "recomp":
            return []
        out = []
        for entry in getattr(self.recomp, "plugins", ()):
            name = os.path.basename(str(entry.get("filename") or ""))
            key = dep_key(name)
            if not key:
                continue
            identity = "forge/" + re.sub(r"[^a-z0-9._-]+", "-", key)
            on = bool(entry.get("enabled")) and not entry.get("ignored_by_recomp")
            out.append((identity, entry.get("path") or name, on,
                        entry.get("manifest") or {}))
        return out

    def _match_identity(self, ref, folders):
        # unique match on the normalised name, otherwise stay undecided
        key = dep_key(ref)
        if not key:
            return None
        hits = [identity for identity in folders if dep_key(identity) == key]
        targets = {folders[identity] for identity in hits}
        if len(targets) != 1:
            # a plugin file nested inside its folder mod is the same target
            loose = set()
            for path in targets:
                here = os.path.normcase(os.path.abspath(path))
                if any(here.startswith(os.path.normcase(os.path.abspath(t))
                                       + os.sep)
                       for t in targets if t != path):
                    loose.add(path)
            if len(targets - loose) != 1:
                return None
            # the mod owns the release, its plugin file does not
            hits = [identity for identity in hits
                    if folders[identity] not in loose]
        preferred = [identity for identity in hits if "/" in identity]
        return sorted(preferred or hits)[0]

    def _rule_violations(self):
        installed, enabled, rules, aliases, _folders = self._rules_snapshot()
        # one node per mod, or every folder alias reports the same error
        installed = {aliases.get(identity, identity) for identity in installed}
        enabled = {aliases.get(identity, identity) for identity in enabled}
        return rules_resolver.validate(installed, enabled, rules, aliases,
                                       self._order_ids())

    def _rule_gate(self):
        # None blocks apply; empty string means clean; otherwise notes text
        violations = self._rule_violations()
        errors = [v for v in violations if v.severity == "error"]
        if errors:
            dialogs.error(
                self, "Rule Conflicts",
                "Cannot apply:\n" + "\n".join(
                    "  \u2022 %s: %s" % (v.mod, v.message) for v in errors))
            return None
        warnings = [v for v in violations if v.severity == "warning"]
        if not warnings:
            return ""
        return "Rule warnings:\n" + "\n".join(
            "  \u2022 %s" % v.message for v in warnings[:10])

    # mod profiles, matched by uploaded file identity

    def _current_installed(self):
        container = self._reorder_container()
        ids = container.order_ids() if container is not None else self._order_ids()
        installed = []
        for order, mod_id in enumerate(ids):
            folder = self._mod_folder(mod_id)
            record = read_record(folder) if folder else None
            installed.append({"mod_id": mod_id, "record": record,
                              "enabled": self._is_mod_enabled(mod_id),
                              "order": order})
        return installed

    def mod_profile_names(self):
        return sorted(self.mod_profiles.keys())

    def save_mod_profile(self, name):
        entries = [gb_profiles.entry_from_record(item["record"], item["enabled"],
                                                 item["order"])
                   for item in self._current_installed() if item["record"]]
        self.mod_profiles[name] = gb_profiles.build_profile(entries, self.mode)
        self.save_config()
        self._status("Mod set '%s' saved." % name)

    def compare_mod_profile(self, name):
        data = gb_profiles.normalize_profile(self.mod_profiles.get(name))
        if data is None:
            return None
        return gb_profiles.compare(data["entries"], self._current_installed())

    def apply_mod_profile(self, name):
        report = self.compare_mod_profile(name)
        if report is None:
            return "Mod set not found."
        container = self._reorder_container()
        order_map = {}
        for item in report["matched"]:
            entry, inst = item["entry"], item["installed"]
            self._set_mod_enabled(inst["mod_id"],
                                  bool(entry.get("enabled", True)), emit=False)
            order_map[inst["mod_id"]] = entry.get("order", 0)
        if container is not None and order_map:
            order = sorted(container.order_ids(),
                           key=lambda mid: order_map.get(mid, 1 << 30))
            container.reorder_to(order)
        service = getattr(self.window(), "gb_service", None)
        queued = 0
        for entry in report["missing"]:
            if not entry.get("gb_mod_id"):
                continue
            url = entry.get("page_url") or page_url(entry["gb_mod_id"])
            if service is not None:
                service.install_from_url(url, context={"auto_confirm": True,
                                                       "profile": name})
                queued += 1
        self._after_order_change(
            "Mod set '%s' applied: %d matched, %d missing queued, "
            "%d mismatched, %d extra." % (
                name, len(report["matched"]), queued,
                len(report["mismatched"]), len(report["extra"])))
        return ("%d matched, %d missing queued for download, %d mismatched, "
                "%d extra." % (len(report["matched"]), queued,
                               len(report["mismatched"]), len(report["extra"])))

    def delete_mod_profile(self, name):
        if name not in self.mod_profiles:
            return
        if not dialogs.confirm(self, "Delete Mod Set",
                                "Delete mod set '%s'?" % name):
            return
        self.mod_profiles.pop(name, None)
        self.save_config()

    def rename_mod_profile(self, old, new):
        if old not in self.mod_profiles:
            return
        if new != old and new in self.mod_profiles:
            dialogs.warn(self, "Rename",
                         "A mod set named '%s' already exists." % new)
            return
        self.mod_profiles[new] = self.mod_profiles.pop(old)
        self.save_config()

    def copy_mod_profile(self, source, dest):
        if source not in self.mod_profiles:
            return
        data = gb_profiles.normalize_profile(self.mod_profiles[source])
        if data is None:
            return
        self.mod_profiles[dest] = gb_profiles.build_profile(
            [dict(entry) for entry in data["entries"]], data["mode"])
        self.save_config()

    def export_mod_profiles(self):
        if not self.mod_profiles:
            self._status("No mod sets to export.")
            return
        path = dialogs.pick_save_file(self, "Export Mod Sets",
                                      "dreamsort_mod_profiles.json",
                                      "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"mod_profiles": self.mod_profiles}, handle, indent=2)
        except Exception as exc:
            dialogs.error(self, "Export Failed", str(exc))
            return
        self._status("Mod sets exported to %s" % redact_path(path))

    def import_mod_profiles(self):
        path = dialogs.pick_open_file(self, "Import Mod Sets",
                                      "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            dialogs.error(self, "Import Failed", str(exc))
            return
        incoming = payload.get("mod_profiles") if isinstance(payload, dict) else None
        if not isinstance(incoming, dict):
            dialogs.error(self, "Import Failed",
                          "That file does not contain dreamSort mod profiles.")
            return
        count = 0
        for key, value in incoming.items():
            data = gb_profiles.normalize_profile(value)
            if data is not None:
                self.mod_profiles[str(key)] = data
                count += 1
        self.save_config()
        self._status("Imported %d mod set(s)." % count)

    def _open_mod_profiles(self):
        self._mod_profiles_dialog = ModProfilesDialog(self, self)
        self._mod_profiles_dialog.open()

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
        if not config.get("remember_mode") or mode not in (
                "ryujinx", "eden", "recomp"):
            mode = "ryujinx"
        self._orphaned_views = []
        self.view = None
        self._pending_urls = []
        self._pending_archives = []
        self._protocol_sockets = []
        self.gb_service = GameBananaService(self)
        self.gb_service.profile_ready.connect(self._on_gb_profile)
        self.gb_service.archive_ready.connect(self._on_gb_archive)
        self.gb_service.failed.connect(self._on_gb_failed)
        self.gb_service.progress.connect(self._on_gb_progress)
        self.update_prefs = config.get("update_prefs") or {}
        self.updater = Updater(self.gb_service.client, self.update_prefs,
                               self._save_update_prefs, self)
        self.updater.statuses_ready.connect(self._on_updater_statuses)
        self.updater.busy_changed.connect(self._on_updater_busy)
        self.github = GitHubUpdates(config.get("github_token", ""),
                                    self.update_prefs,
                                    self._save_update_prefs, self)
        self.github.statuses_ready.connect(self._on_updater_statuses)
        self.github.busy_changed.connect(self._on_updater_busy)
        self.github.failed.connect(self._on_github_failed)
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

        gb_action = QAction("Install from GameBanana link…", self)
        gb_action.triggered.connect(self._install_from_gb)
        file_menu.addAction(gb_action)

        token_action = QAction("GitHub token…", self)
        token_action.triggered.connect(self._set_github_token)
        file_menu.addAction(token_action)

        save = QAction("Save Config", self)
        save.triggered.connect(self._save_app_config)
        file_menu.addAction(save)

        self.log_toggle = QAction("Enable File Logging", self)
        self.log_toggle.setCheckable(True)
        self.log_toggle.setChecked(app_logging.is_enabled())
        self.log_toggle.triggered.connect(self._toggle_file_logging)
        file_menu.addAction(self.log_toggle)

        file_menu.addSeparator()
        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = menu_bar.addMenu("View")
        self.contrast_toggle = QAction("High contrast mode", self)
        self.contrast_toggle.setCheckable(True)
        self.contrast_toggle.setChecked(high_contrast())
        self.contrast_toggle.toggled.connect(self._toggle_high_contrast)
        view_menu.addAction(self.contrast_toggle)

        help_menu = menu_bar.addMenu("Help")
        checker = QAction("Check MHGU Version", self)
        checker.triggered.connect(self._check_game_version)
        help_menu.addAction(checker)

        recomp_log_action = QAction("Analyze Recomp log.txt…", self)
        recomp_log_action.triggered.connect(self._analyze_recomp_log)
        help_menu.addAction(recomp_log_action)

        about = QAction("About dreamSort", self)
        about.triggered.connect(lambda: dialogs.show_about(self))
        help_menu.addAction(about)

    def _toggle_file_logging(self, checked):
        app_logging.set_enabled(checked)
        if self.view is not None:
            self.view.logging_enabled = app_logging.is_enabled()
            self.view.save_config()

    def _toggle_high_contrast(self, checked):
        # live: no restart, and the choice is kept with the other settings
        apply_theme(QApplication.instance(), checked)
        if self.view is not None:
            self.view.high_contrast = bool(checked)
            self.view.save_config()
            self.view.refresh_details()

    def _recomp_analysis_root(self):
        # live recomp view first, then the path saved in config
        if self.view is not None and self.view.recomp.root_path:
            return self.view.recomp.root_path
        if self.view is not None:
            return self.view._saved_paths.get("recomp", "")
        return ""

    def _analyze_recomp_log(self):
        root = self._recomp_analysis_root()
        if not root:
            dialogs.info(
                self, "Recomp log.txt",
                "Set the MHGU Recomp folder first so dreamSort knows where "
                "mhgurecomp.exe and log.txt live.")
            return
        report = recomp_log.analyze(root)
        if not report["found"]:
            dialogs.info(
                self, "Recomp log.txt",
                report["summary"] + "\n\nExpected at:\n"
                + redact_path(report["path"]))
            return
        dialogs.RecompLogDialog.show_report(self, report)

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
        self._flush_pending_urls()
        self._flush_pending_archives()

    # gamebanana / protocol
    def _install_from_gb(self):
        url = dialogs.ask_text(self, "GameBanana Link",
                               "Paste a GameBanana mod link:")
        if url:
            self.gb_service.install_from_url(url)

    def _on_gb_profile(self, payload):
        profile = payload["profile"]
        file = payload["file"]
        want_mode = mode_for_profile(profile)
        if (want_mode and self.view is not None
                and self.view.mode != want_mode):
            # this section is only read by the recomp; do not install elsewhere
            if not dialogs.confirm(
                    self, "Wrong Mode",
                    "'%s' is in %s, which only MHGU Recomp loads.\n\n"
                    "dreamSort is in %s mode right now. Switch to MHGU Recomp "
                    "and install it there?\n\n"
                    "No cancels this install; nothing is downloaded."
                    % (profile.get("name") or file.get("name") or "That mod",
                       profile.get("category") or "a Recomp section",
                       self.view._mode_label())):
                self.gb_service.cancel_pending()
                return
            self._build_view(want_mode)
            self.view.save_config()
        size = (self.view._format_size(file.get("size") or 0)
                if self.view is not None else "?")
        text = ("Name: %s\nAuthor: %s\nFile: %s\nSize: %s"
                % (profile.get("name", ""), profile.get("author", ""),
                   file.get("name", ""), size))
        if dialogs.confirm(self, "Install from GameBanana", text):
            self.gb_service.proceed_download()
        else:
            self.gb_service.cancel_pending()

    def _on_gb_archive(self, payload):
        ctx = payload.get("context") or {}
        update_mod_id = ctx.get("update_mod_id")
        if update_mod_id and self.view is not None:
            payload["update_dir"] = self.view._mod_folder(update_mod_id)
        if self.view is not None:
            self.view._install_downloaded(payload["archive"], payload)
        else:
            self._pending_archives.append(payload)

    def _on_gb_failed(self, message):
        dialogs.warn(self, "GameBanana", message)

    def _on_updater_statuses(self, payload):
        if self.view is not None:
            self.view.refresh_update_badges()
        if payload.get("error"):
            self.view and self.view._status(
                "Update check failed: %s" % payload["error"])

    def _on_updater_busy(self, busy):
        if self.view is None:
            return
        github = getattr(self, "github", None)
        busy_now = self.updater.busy() or (github is not None
                                           and github.busy())
        self.view.updates_btn.setEnabled(not busy_now)

    def _on_github_failed(self, message):
        dialogs.warn(self, "GitHub", message)

    def _save_update_prefs(self):
        # cheap, and the next start reads it back
        if self.view is not None:
            self.view.save_config()

    def _on_gb_progress(self, message):
        if self.view is not None:
            self.view._status("Downloading %s..." % message.get("text", ""))

    def enqueue_protocol_url(self, url):
        self._pending_urls.append(url)
        self._flush_pending_urls()

    def attach_protocol_connection(self, socket):
        self._protocol_sockets.append(socket)
        socket.readyRead.connect(lambda: self._read_protocol_socket(socket))

    def _read_protocol_socket(self, socket):
        data = bytes(socket.readAll()).decode("utf-8", errors="replace")
        if data.strip():
            self.enqueue_protocol_url(data.strip())

    def _flush_pending_urls(self):
        if self.view is None:
            return
        while self._pending_urls:
            url = self._pending_urls.pop(0)
            self.gb_service.install_from_url(url)

    def _flush_pending_archives(self):
        if self.view is None:
            return
        while self._pending_archives:
            payload = self._pending_archives.pop(0)
            self.view._install_downloaded(payload["archive"], payload)

    def _save_app_config(self):
        if self.view is not None:
            self.view.save_config()
        dialogs.info(self, "Saved", "Settings written to:\n%s"
                     % redact_path(config_path()))

    def _set_github_token(self):
        # read-only token lifts the unauthenticated hourly quota
        github = getattr(self, "github", None)
        if github is None:
            return
        token = dialogs.ask_text(
            self, "GitHub Token",
            "A read-only token raises the 60 requests/hour limit.\n"
            "Leave empty to send none:", github.token)
        if token is None:
            return
        github.token = token.strip()
        self._save_update_prefs()
        if self.view is not None:
            self.view._status("GitHub token saved." if github.token
                              else "GitHub token cleared.")

    def _check_game_version(self):
        if self.view is not None:
            self.view.show_game_version_report()

    def _maybe_prompt_startup(self):
        if not self.isVisible():
            return
        from ..storage.config import CONFIG_NOTICES
        if CONFIG_NOTICES:
            dialogs.show_config_notices(self, list(CONFIG_NOTICES))
            CONFIG_NOTICES.clear()
        config = read_config()
        if not config.get("remember_mode"):
            self.prompt_mode_switch()
        self._flush_pending_urls()
        self._flush_pending_archives()

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
        try:
            self.gb_service.shutdown(30000)
        except Exception:
            pass
        try:
            self.github.shutdown()
        except Exception:
            pass
        super().closeEvent(event)
