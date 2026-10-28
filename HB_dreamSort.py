## DREAMSORT MOD MANAGER
# 2026/10/28
VERSION = "v7.0.1"

import os
import re
import sys
import shutil
import zipfile
import json
import platform
import subprocess
import threading
import traceback
from queue import Queue

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinterdnd2 import DND_FILES, TkinterDnD

try:
    import py7zr
    PY7ZR_SUPPORT = True
except ImportError:
    PY7ZR_SUPPORT = False

# DPI for 2k+ monitors
def enable_high_dpi_awareness():
    # Enable per-monitor v2 DPI awareness on Windows so Tk renders at
    # the physical pixel resolution (fixes blurry text on 2K+ displays).
    if sys.platform != "win32":
        return
    # Prevent CustomTkinter's own awareness setup from racing/conflicting.
    try:
        ctk.deactivate_automatic_dpi_awareness()
    except Exception:
        pass
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor v2
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    except Exception as e:
        print(f"DPI awareness setup failed: {e}")

def get_dpi_scale():
    # Return the effective DPI scale factor (1.0 == 96 DPI == 100%).
    if sys.platform == "win32":
        try:
            import ctypes
            dpi = ctypes.windll.user32.GetDpiForSystem()
            return max(1.0, min(dpi / 96.0, 2.5))
        except Exception:
            return 1.0
    # macOS and Linux: CustomTkinter's defaults are good. Steam Deck = 1.0.
    return 1.0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def config_path():
    # config.json lives next to the script (or next to the frozen exe), not in
    # whatever directory the user happened to launch from, so settings are
    # consistent across platforms and launch methods.
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "config.json")

def is_process_running(process_name):
    system = platform.system()
    try:
        if system == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            command = ["tasklist", "/FI", f"IMAGENAME eq {process_name}.exe"]
            output = subprocess.check_output(
                command, startupinfo=startupinfo, stderr=subprocess.STDOUT
            )
            return process_name.lower() in output.decode(errors="ignore").lower()
        command = ["pgrep", "-f", process_name]
        output = subprocess.check_output(command, stderr=subprocess.STDOUT)
        return output.strip() != b""
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def open_in_file_explorer(path):
    if not path or not os.path.isdir(path):
        return False
    try:
        if sys.platform == "win32":
            os.startfile(os.path.normpath(path))
        elif sys.platform == "darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])
        return True
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

class Colors:
    BG = "#2b2b2b"
    TEXT = "#ffebcd"
    WIDGET_BG = "#3c3c3c"
    FRAME_BG = "#2b2b2b"
    BUTTON_BG = "#4c4c4c"
    BUTTON_HOVER = "#636363"
    BUTTON_BORDER = "#ffebcd"
    HEADER_BG = "#ffebcd"
    HEADER_TEXT = "#000000"
    HIGHLIGHT_BG = "#636363"
    TREE_HEADING_BG = "#4c4c4c"
    CONFLICT = "#FF7D7D"
    RESOLVED_CONFLICT = "#3EFF65"
    NO_CONFLICT = "#d5d0ff"
    CHEAT_MOD = "#FFA500"
    DISABLED = "#808080"
    DRAG_HIGHLIGHT = "#FFD700"
    # Dark-gold blend of WIDGET_BG and DRAG_HIGHLIGHT: the face color of a
    # selected row, so ctrl-click selection changes the whole row, not just
    # its edge.
    SELECTED_FACE = "#5a5233"
    SELECTED_BAR_TEXT = "#1a1a1a"
    PROGRESS_OVERLAY = ("#000000", "#000000")
    SECTION_HEADER = "#505050"
    RECOMP_ACCENT = "#4fc3f7"
    RYUJINX_ACCENT = "#e57373"

class RyujinxAnalyzer:
    CHEAT_BUILD_ID_PREFIX = "FB08F1D20FD1204F-"

    def __init__(self):
        self.mods_path = ""
        self.mods_json_path = None
        self.mod_files = {}
        self.conflicts = {}
        self.load_order = []
        self.cheat_only_mods = set()
        self.special_cheats_folder_name = None

    def set_mods_path(self, path):
        if not os.path.isdir(path):
            return False
        self.mods_path = os.path.normpath(path)
        self.mods_json_path = None
        try:
            norm_path = os.path.normpath(self.mods_path)
            parts = norm_path.split(os.sep)
            if (len(parts) >= 3
                    and parts[-2].lower() == "contents"
                    and parts[-3].lower() == "mods"):
                game_id = parts[-1]
                ryujinx_root_path = os.sep.join(parts[:-3])
                self.mods_json_path = os.path.join(
                    ryujinx_root_path, "games", game_id, "mods.json"
                )
                print(f"Found Ryujinx structure. mods.json: {self.mods_json_path}")
            else:
                print("Warning: path not a standard Ryujinx structure.")
        except Exception as e:
            print(f"Could not determine mods.json path: {e}")
            self.mods_json_path = None
        return True

    def get_current_load_order(self):
        if not self.mods_path:
            return []
        try:
            dirs = [d for d in os.listdir(self.mods_path)
                    if os.path.isdir(os.path.join(self.mods_path, d))]
            dirs.sort(key=lambda x: [
                int(c) if c.isdigit() else c
                for c in re.split("([0-9]+)", x)
            ])
            return dirs
        except FileNotFoundError:
            return []

    @staticmethod
    def strip_prefix(name):
        match = re.match(r"^(?:\d+_)|(?:[.!~]+_?)", name)
        return name[match.end():] if match else name
    
    def scan_and_analyze(self):
        if not self.mods_path:
            return
        self.load_order = self.get_current_load_order()
        file_to_mods_map = {}
        self.mod_files = {}
        self.cheat_only_mods.clear()
        self.special_cheats_folder_name = None

        for mod_name in self.load_order:
            if self.strip_prefix(mod_name).lower() == "cheats":
                self.special_cheats_folder_name = mod_name
                break

        for mod_name in self.load_order:
            if mod_name == self.special_cheats_folder_name:
                continue
            mod_path = os.path.join(self.mods_path, mod_name)
            self.mod_files[mod_name] = set()
            try:
                top = [d.lower() for d in os.listdir(mod_path)]
                if "cheats" in top and "romfs" not in top:
                    self.cheat_only_mods.add(mod_name)
            except OSError:
                continue
            for root, dirs, files in os.walk(mod_path):
                dirs[:] = [d for d in dirs if d.lower() != "cheats"]
                for file in files:
                    rel = os.path.relpath(os.path.join(root, file),
                                          mod_path).replace("\\", "/")
                    self.mod_files[mod_name].add(rel)
                    file_to_mods_map.setdefault(rel, []).append(mod_name)

        self.conflicts = {}
        for file_path, mods in file_to_mods_map.items():
            if len(mods) > 1:
                for mod_name in mods:
                    if mod_name in self.cheat_only_mods:
                        continue
                    self.conflicts.setdefault(mod_name, {})[file_path] = [
                        m for m in mods if m != mod_name
                    ]

    def _update_ryujinx_mods_json(self, final_mod_list, progress_queue):
        if not self.mods_json_path:
            progress_queue.put({"type": "status",
                                "text": "Skipping mods.json (path not found)."})
            return
        progress_queue.put({"type": "status",
                            "text": "Phase 3: Updating Ryujinx mods.json..."})
        entries = []
        for cfg in final_mod_list:
            entries.append({
                "name": cfg["name"],
                "path": os.path.abspath(os.path.join(self.mods_path, cfg["name"])),
                "enabled": cfg["enabled"],
            })
        try:
            os.makedirs(os.path.dirname(self.mods_json_path), exist_ok=True)
            with open(self.mods_json_path, "w", encoding="utf-8") as f:
                json.dump({"mods": entries}, f, indent=2)
        except Exception as e:
            progress_queue.put({
                "type": "error",
                "message": f"Could not write to mods.json.\n\n{self.mods_json_path}\n{e}"
            })

    def _apply_cheat_selections_threaded(self, pending_cheats, progress_queue):
        folder = self.special_cheats_folder_name or "cheats"
        enabled_path = os.path.join(self.mods_path, folder, "enabled.txt")
        try:
            os.makedirs(os.path.dirname(enabled_path), exist_ok=True)
            if not pending_cheats:
                open(enabled_path, "w").close()
                progress_queue.put({"type": "status",
                                    "text": "No cheats selected, cleared enabled.txt."})
                return
            progress_queue.put({"type": "status",
                                "text": "Phase 4: Applying Cheat Selections..."})
            all_enabled = set()
            for mod_name, states in pending_cheats.items():
                all_enabled.update(n for n, s in states.items() if s)
            sorted_cheats = sorted(all_enabled)
            with open(enabled_path, "w", encoding="utf-8") as f:
                for c in sorted_cheats:
                    f.write(f"{self.CHEAT_BUILD_ID_PREFIX}<{c} Cheat>\n")
            progress_queue.put({
                "type": "status",
                "text": f"Written {len(sorted_cheats)} cheats to enabled.txt"
            })
        except Exception as e:
            progress_queue.put({
                "type": "error",
                "message": f"Could not write enabled.txt.\n\n{enabled_path}\n{e}"
            })

    def apply_new_order_threaded(self, ordered_mods_config, pending_cheats,
                                  progress_queue):
        if not self.mods_path:
            progress_queue.put({"type": "error", "message": "Mods path not set."})
            return
        temp_map = {}
        final_mod_list = []
        try:
            current_mods = [d for d in os.listdir(self.mods_path)
                            if os.path.isdir(os.path.join(self.mods_path, d))]
        except Exception as e:
            progress_queue.put({"type": "error",
                                "message": f"Failed to list mod directories: {e}"})
            return
        total_ops = len(current_mods) + len(ordered_mods_config)
        ops_done = 0

        progress_queue.put({"type": "status",
                            "text": "Phase 1: Backing up current mods..."})
        for mod_name in current_mods:
            try:
                clean = self.strip_prefix(mod_name)
                temp_name = f"{clean}__temp_rename__"
                progress_queue.put({
                    "type": "progress",
                    "value": ops_done / max(total_ops, 1),
                    "text": f"Backing up: '{mod_name}'",
                })
                shutil.move(os.path.join(self.mods_path, mod_name),
                            os.path.join(self.mods_path, temp_name))
                temp_map[clean] = temp_name
                ops_done += 1
            except PermissionError:
                progress_queue.put({
                    "type": "error",
                    "message": f"Permission denied renaming '{mod_name}'. Close Ryujinx and retry."
                })
                return
            except Exception as e:
                progress_queue.put({
                    "type": "error",
                    "message": f"Could not rename '{mod_name}'.\n\n{e}"
                })
                return

        try:
            progress_queue.put({"type": "status",
                                "text": "Phase 2: Applying new load order..."})
            if self.special_cheats_folder_name:
                clean = self.strip_prefix(self.special_cheats_folder_name)
                temp = temp_map.pop(clean, None)
                if temp:
                    shutil.move(os.path.join(self.mods_path, temp),
                                os.path.join(self.mods_path,
                                             self.special_cheats_folder_name))

            idx = 0
            for mod_name, is_enabled in ordered_mods_config.items():
                if mod_name == self.special_cheats_folder_name:
                    continue
                clean = self.strip_prefix(mod_name)
                temp = temp_map.get(clean)
                if not temp:
                    continue
                if mod_name in self.cheat_only_mods or not is_enabled:
                    final_name = f"~{clean}"
                    enabled_status = False
                else:
                    idx += 1
                    final_name = f"{idx:02d}_{clean}"
                    enabled_status = True
                progress_queue.put({
                    "type": "progress",
                    "value": ops_done / max(total_ops, 1),
                    "text": f"Writing: '{final_name}'",
                })
                shutil.move(os.path.join(self.mods_path, temp),
                            os.path.join(self.mods_path, final_name))
                final_mod_list.append({"name": final_name,
                                       "enabled": enabled_status})
                ops_done += 1
        except PermissionError as e:
            progress_queue.put({
                "type": "error",
                "message": ("Permission denied. Mods may be in a temporary state "
                            "(__temp_rename__). Close Ryujinx and retry.\n\n"
                            f"{e}")
            })
            return
        except Exception as e:
            progress_queue.put({
                "type": "error",
                "message": f"Could not apply new order.\n\n{e}"
            })
            return

        self._update_ryujinx_mods_json(final_mod_list, progress_queue)
        self._apply_cheat_selections_threaded(pending_cheats, progress_queue)
        progress_queue.put({"type": "done"})

class RecompAnalyzer:
    # Analyzes an MHGU Recomp installation root:
    #   <root>/mhgurecomp.exe
    #   <root>/mods/            - enabled mod folders (numbered prefixes)
    #   <root>/mods_disabled/   - disabled mod folders
    #   <root>/cheats/          - .txt cheat files ('_' prefix = disabled)
    MODS_FOLDER = "mods"
    DISABLED_FOLDER = "mods_disabled"
    CHEATS_FOLDER = "cheats"

    EXE_NAMES = ("mhgurecomp.exe", "mhgurecomp", "mhgurecomp.app")

    def __init__(self):
        self.root_path = ""
        self.mods_path = ""
        self.disabled_mods_path = ""
        self.cheats_path = ""

        # name -> {enabled, order, path, raw_name, has_romfs, has_exefs, has_plugins}
        self.mods = {}
        # clean filename -> {enabled, path, raw_name}
        self.cheats = {}
        # list of {mod, filename, path, enabled, rel_path}
        self.patches = []
        # list of {mod, filename, path, enabled, rel_path, ini_files}
        self.plugins = []

    # -- configuration ------------------------------------------------------

    def set_root(self, path):
        if not path or not os.path.isdir(path):
            return False
        self.root_path = os.path.normpath(path)
        self.mods_path = os.path.join(self.root_path, self.MODS_FOLDER)
        self.disabled_mods_path = os.path.join(self.root_path, self.DISABLED_FOLDER)
        self.cheats_path = os.path.join(self.root_path, self.CHEATS_FOLDER)
        return True

    def locate_recomp_exe(self):
        if not self.root_path:
            return None
        for name in self.EXE_NAMES:
            p = os.path.join(self.root_path, name)
            if os.path.exists(p):
                return p
        return None

    # -- scanning -----------------------------------------------------------

    @staticmethod
    def _strip_number_prefix(name):
        # Ignore any leftover __tmp__ prefix from an interrupted apply
        while name.startswith("__tmp__"):
            name = name[len("__tmp__"):]
        m = re.match(r"^(\d+)_(.*)$", name)
        return m.group(2) if m else name

    @staticmethod
    def _extract_prefix_number(name):
        m = re.match(r"^(\d+)_", name)
        return int(m.group(1)) if m else 10_000

    def scan(self):
        self.mods.clear()
        self.cheats.clear()
        self.patches.clear()
        self.plugins.clear()

        if os.path.isdir(self.mods_path):
            for raw in sorted(os.listdir(self.mods_path)):
                full = os.path.join(self.mods_path, raw)
                if not os.path.isdir(full):
                    continue
                clean = self._strip_number_prefix(raw)
                self.mods[clean] = {
                    "enabled": True,
                    "order": self._extract_prefix_number(raw),
                    "path": full,
                    "raw_name": raw,
                    **self._detect_mod_types(full),
                }

        if os.path.isdir(self.disabled_mods_path):
            for raw in sorted(os.listdir(self.disabled_mods_path)):
                full = os.path.join(self.disabled_mods_path, raw)
                if not os.path.isdir(full):
                    continue
                clean = self._strip_number_prefix(raw)
                if clean in self.mods:
                    continue  # enabled wins
                self.mods[clean] = {
                    "enabled": False,
                    "order": 10_000,
                    "path": full,
                    "raw_name": raw,
                    **self._detect_mod_types(full),
                }

        if os.path.isdir(self.cheats_path):
            for fname in sorted(os.listdir(self.cheats_path)):
                if not fname.lower().endswith(".txt"):
                    continue
                enabled = not fname.startswith("_")
                clean = fname if enabled else fname[1:]
                self.cheats[clean] = {
                    "enabled": enabled,
                    "path": os.path.join(self.cheats_path, fname),
                    "raw_name": fname,
                }

        for clean, mod in self.mods.items():
            if mod["enabled"]:
                self._scan_patches_plugins(clean, mod["path"])

        # --- File conflict detection: which enabled romfs mods share files ---
        self.conflicts = {}
        file_to_mods = {}
        for clean, mod in self.mods.items():
            mod["files"] = set()
            if not mod["enabled"] or not mod.get("has_romfs"):
                continue
            romfs_dir = os.path.join(mod["path"], "romfs")
            walk_root = romfs_dir if os.path.isdir(romfs_dir) else mod["path"]
            try:
                for root, _d, files in os.walk(walk_root):
                    for f in files:
                        rel = os.path.relpath(
                            os.path.join(root, f), walk_root
                        ).replace("\\", "/")
                        mod["files"].add(rel)
                        file_to_mods.setdefault(rel, []).append(clean)
            except OSError:
                continue
        for rel, mods in file_to_mods.items():
            if len(mods) > 1:
                for m in mods:
                    self.conflicts.setdefault(m, {})[rel] = [
                        o for o in mods if o != m]

    def _detect_mod_types(self, path):
        has_romfs = has_exefs = has_plugins = has_nro = False
        for root, dirs, files in os.walk(path):
            for d in dirs:
                dl = d.lower()
                if dl == "romfs":
                    # Only count as a romfs mod if the romfs/ directory
                    # actually contains files (a stray empty folder should
                    # not promote a pure-plugin mod into "Mods").
                    rdir = os.path.join(root, d)
                    if any(f for _r, _d, f in os.walk(rdir)):
                        has_romfs = True
                elif dl == "exefs":
                    has_exefs = True
                elif dl == "plugins":
                    has_plugins = True
            for f in files:
                fl = f.lower()
                if fl.endswith(".pchtxt") or fl.endswith(".ips"):
                    has_exefs = True
                elif fl.endswith(".nro"):
                    has_plugins = True
                    has_nro = True
        return {"has_romfs": has_romfs, "has_exefs": has_exefs,
                "has_plugins": has_plugins, "has_nro": has_nro}

    def _scan_patches_plugins(self, mod_name, mod_path):
        for root, dirs, files in os.walk(mod_path):
            for f in files:
                fl = f.lower()
                is_patch = fl.endswith(".pchtxt") or fl.endswith(".ips")
                is_plugin = fl.endswith(".nro")
                if not (is_patch or is_plugin):
                    continue
                enabled = not f.startswith("_")
                clean_f = f if enabled else f[1:]
                rel_dir = os.path.relpath(root, mod_path)
                if rel_dir == ".":
                    rel_path = clean_f
                else:
                    rel_path = os.path.normpath(os.path.join(rel_dir, clean_f))
                entry = {
                    "mod": mod_name,
                    "filename": clean_f,
                    "path": os.path.join(root, f),
                    "enabled": enabled,
                    "rel_path": rel_path,
                }
                if is_patch:
                    self.patches.append(entry)
                else:
                    entry["ini_files"] = self._find_nearby_ini(root)
                    self.plugins.append(entry)

    @staticmethod
    def _find_nearby_ini(directory):
        out = []
        try:
            for name in os.listdir(directory):
                if name.lower().endswith(".ini"):
                    out.append(os.path.join(directory, name))
        except OSError:
            pass
        return out

    # -- ordering helpers ---------------------------------------------------

    def get_ordered_mods(self):
        # Return list of (clean_name, data) — enabled by order, then disabled.
        enabled = sorted(
            [(n, d) for n, d in self.mods.items() if d["enabled"]],
            key=lambda x: x[1]["order"]
        )
        disabled = sorted(
            [(n, d) for n, d in self.mods.items() if not d["enabled"]],
            key=lambda x: x[0].lower()
        )
        return enabled + disabled

    def get_clean_name_for_widget(self, mod_name):
        return self._strip_number_prefix(mod_name)

    def get_current_mod_path(self, clean_name):
        for base in (self.mods_path, self.disabled_mods_path):
            if not os.path.isdir(base):
                continue
            for raw in os.listdir(base):
                if self._strip_number_prefix(raw) == clean_name:
                    return os.path.join(base, raw)
        return None

    # -- apply --------------------------------------------------------------

    def apply_changes_threaded(self, ordered_mod_names, mod_enabled_map,
                                cheat_states, patch_states, plugin_states,
                                progress_queue):
        if not self.root_path:
            progress_queue.put({"type": "error",
                                "message": "Recomp root not set."})
            return

        try:
            os.makedirs(self.mods_path, exist_ok=True)
            os.makedirs(self.disabled_mods_path, exist_ok=True)
        except Exception as e:
            progress_queue.put({"type": "error",
                                "message": f"Cannot create mod folders: {e}"})
            return

        ordered_clean_set = {self._strip_number_prefix(n)
                             for n in ordered_mod_names}

        # ---- PHASE 1: move all existing top-level mods to a neutral name
        progress_queue.put({"type": "status",
                            "text": "Phase 1: Preparing mods..."})
        try:
            existing_locations = {}
            for base in (self.mods_path, self.disabled_mods_path):
                if not os.path.isdir(base):
                    continue
                for raw in os.listdir(base):
                    full = os.path.join(base, raw)
                    if not os.path.isdir(full):
                        continue
                    clean = self._strip_number_prefix(raw)
                    # Recover any folder a previous (buggy) run left behind.
                    if raw.startswith("__tmp__"):
                        target = os.path.join(base, clean)
                        if (os.path.normcase(full) != os.path.normcase(target)
                                and not os.path.exists(target)):
                            try:
                                shutil.move(full, target)
                                full = target
                            except Exception:
                                pass
                    # Only park folders the ordering system will place back.
                    # Plugin-only folders keep their name — their enable/
                    # disable is handled by per-file renames later.
                    if clean not in ordered_clean_set:
                        continue
                    existing_locations.setdefault(clean, full)
        except Exception as e:
            progress_queue.put({"type": "error",
                                "message": f"Failed to list mod folders: {e}"})
            return

        temp_paths = {}
        total_phase1 = max(len(existing_locations), 1)
        for i, (clean, src) in enumerate(existing_locations.items()):
            dst = os.path.join(os.path.dirname(src), f"__tmp__{clean}")
            try:
                if os.path.normcase(src) != os.path.normcase(dst):
                    shutil.move(src, dst)
                temp_paths[clean] = dst
            except Exception as e:
                progress_queue.put({
                    "type": "error",
                    "message": f"Failed to prepare '{clean}': {e}"
                })
                return
            progress_queue.put({
                "type": "progress",
                "value": (i + 1) / total_phase1 * 0.4,
                "text": f"Prepared: {clean}",
            })

        # ---- PHASE 2: place each mod in the right folder with the right name
        progress_queue.put({"type": "status",
                            "text": "Phase 2: Writing mod order..."})
        enabled_index = 0
        total_phase2 = max(len(ordered_mod_names), 1)
        for i, raw_name in enumerate(ordered_mod_names):
            clean = self._strip_number_prefix(raw_name)
            if clean not in temp_paths:
                continue
            is_enabled = mod_enabled_map.get(raw_name,
                                            mod_enabled_map.get(clean, True))
            if is_enabled:
                enabled_index += 1
                final_name = f"{enabled_index:02d}_{clean}"
                final_dir = self.mods_path
            else:
                final_name = clean
                final_dir = self.disabled_mods_path
            final_path = os.path.join(final_dir, final_name)
            try:
                shutil.move(temp_paths[clean], final_path)
            except Exception as e:
                progress_queue.put({
                    "type": "error",
                    "message": f"Failed to place '{clean}': {e}"
                })
                return
            progress_queue.put({
                "type": "progress",
                "value": 0.4 + ((i + 1) / total_phase2) * 0.4,
                "text": f"Placed: {final_name}",
            })

        # Update internal state so patch/plugin lookup uses fresh paths
        self.scan()

        # ---- PHASE 3: cheats
        progress_queue.put({"type": "status",
                            "text": "Phase 3: Applying cheat selections..."})
        self._apply_cheats(cheat_states, progress_queue)

        # ---- PHASE 4: patches and plugins
        progress_queue.put({"type": "status",
                            "text": "Phase 4: Applying patch/plugin selections..."})
        self._apply_patches_plugins(patch_states, plugin_states, progress_queue)

        progress_queue.put({"type": "progress", "value": 1.0, "text": "Done."})
        progress_queue.put({"type": "done"})

    def _apply_cheats(self, cheat_states, progress_queue):
        if not os.path.isdir(self.cheats_path):
            return
        try:
            entries = os.listdir(self.cheats_path)
        except OSError as e:
            progress_queue.put({"type": "error",
                                "message": f"Cannot read cheats folder: {e}"})
            return
        # index current state
        current = {}  # clean -> (enabled, raw_name)
        for fname in entries:
            if not fname.lower().endswith(".txt"):
                continue
            enabled = not fname.startswith("_")
            clean = fname if enabled else fname[1:]
            current[clean] = (enabled, fname)
        for clean, should_enable in cheat_states.items():
            if clean not in current:
                continue
            is_enabled, fname = current[clean]
            if is_enabled == should_enable:
                continue
            src = os.path.join(self.cheats_path, fname)
            if should_enable:
                dst = os.path.join(self.cheats_path, fname[1:])
            else:
                dst = os.path.join(self.cheats_path, "_" + fname)
            try:
                shutil.move(src, dst)
            except Exception as e:
                progress_queue.put({
                    "type": "error",
                    "message": f"Failed to rename cheat '{fname}': {e}"
                })
                return
    
    def _apply_patches_plugins(self, patch_states, plugin_states,
                                progress_queue):
        for entries, states, label in (
            (self.patches, patch_states, "patch"),
            (self.plugins, plugin_states, "plugin"),
        ):
            for entry in entries:
                key = (entry["mod"], entry["rel_path"])
                if key not in states:
                    continue
                should_enable = states[key]
                if entry["enabled"] == should_enable:
                    continue
                src = entry["path"]
                dir_name = os.path.dirname(src)
                new_name = (entry["filename"] if should_enable
                            else "_" + entry["filename"])
                dst = os.path.join(dir_name, new_name)
                try:
                    shutil.move(src, dst)
                except Exception as e:
                    progress_queue.put({
                        "type": "error",
                        "message": (f"Failed to rename {label} "
                                    f"'{entry['filename']}': {e}")
                    })
                    return

class CollapsibleSection(ctk.CTkFrame):
    def __init__(self, master, title, start_collapsed=False, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.title_text = title
        self.collapsed = start_collapsed
        self.header = ctk.CTkButton(
            self, text=f"{'▶' if start_collapsed else '▼'} {title}",
            anchor="w",
            fg_color=Colors.SECTION_HEADER,
            hover_color=Colors.BUTTON_HOVER,
            text_color=Colors.TEXT,
            command=self.toggle,
            height=26, corner_radius=4,
        )
        self.header.pack(fill="x", pady=(6, 2))
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        if not start_collapsed:
            # Collapsed sections keep content hidden until toggled.
            self.content.pack(fill="x")

    def toggle(self):
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.content.pack_forget()
            self.header.configure(text=f"▶ {self.title_text}")
        else:
            self.content.pack(fill="x")
            self.header.configure(text=f"▼ {self.title_text}")

    def set_title(self, text):
        self.title_text = text
        prefix = "▶" if self.collapsed else "▼"
        self.header.configure(text=f"{prefix} {text}")

class StartupModeDialog(ctk.CTkToplevel):
    def __init__(self, master, current_mode, remember, callback):
        super().__init__(master)
        self.callback = callback
        self.mode_var = ctk.StringVar(value=current_mode)
        self.remember_var = ctk.BooleanVar(value=remember)

        self.title("dreamSort — Select Mode")
        self.geometry("440x320")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        ctk.CTkLabel(
            self, text="Which setup are you managing?",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(20, 12))

        radio_frame = ctk.CTkFrame(self, fg_color="transparent")
        radio_frame.pack(pady=4, fill="x", padx=40)
        ctk.CTkRadioButton(
            radio_frame, text="Ryujinx (Switch emulator)",
            variable=self.mode_var, value="ryujinx",
        ).pack(anchor="w", pady=6)
        ctk.CTkRadioButton(
            radio_frame, text="Morerokk's MHGU Recomp (native PC port)",
            variable=self.mode_var, value="recomp",
        ).pack(anchor="w", pady=6)

        ctk.CTkCheckBox(
            self, text="Remember this choice on next launch",
            variable=self.remember_var,
        ).pack(pady=20)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=(0, 10))
        ctk.CTkButton(
            btn_frame, text="Continue", command=self._on_continue,
            fg_color=Colors.RESOLVED_CONFLICT, text_color="#000000",
            width=120,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            btn_frame, text="Cancel", command=self._on_cancel,
            fg_color=Colors.BUTTON_BG, width=120,
        ).pack(side="left", padx=6)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.after(150, self._center)

    def _center(self):
        try:
            self.update_idletasks()
            x = self.master.winfo_rootx() + (self.master.winfo_width() - self.winfo_width()) // 2
            y = self.master.winfo_rooty() + (self.master.winfo_height() - self.winfo_height()) // 2
            self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _on_continue(self):
        self.callback(self.mode_var.get(), self.remember_var.get())
        self.destroy()

    def _on_cancel(self):
        self.callback(None, self.remember_var.get())
        self.destroy()

# Actual App Starts
class DreamSortApp(ctk.CTkFrame):
    def __init__(self, master, mode="ryujinx", dpi_scale=1.0):
        super().__init__(master)

        self.mode = mode
        self.dpi_scale = dpi_scale

        self.ryujinx = RyujinxAnalyzer()
        self.recomp = RecompAnalyzer()

        # Ryujinx-specific state
        self.pending_cheat_selections = {}
        self.current_details_mod = None

        # Shared state
        self.mod_item_widgets = {}       # name -> widget (mods only)
        self.cheat_widgets = {}          # clean_name -> widget
        self.patch_widgets = {}          # (mod, rel_path) -> widget
        self.plugin_widgets = {}         # (mod, rel_path) -> widget
        self.drag_data = {"item": None, "y": 0}
        self.selected_mods = set()       # mod_name(s) toggled via Ctrl+click
        self.apply_thread = None
        self.progress_queue = Queue()
        self.current_state = "idle"
        self.real_mods_path = ""
        self.ryujinx_exe_path = ""
        self.game_file_path = ""
        self.recomp_exe_path = ""
        self.remember_mode = False
        self._after_id = None
        self._sash_dragging = False
        self._sash_target = None
        self._sash_after = None
        self.profiles = {}   # name -> {mode, order:[clean], enabled:{clean:bool}}

        # Recomp section refs (set during populate)
        self.recomp_mods_section = None

        self.load_config()

        self.configure(fg_color=Colors.BG)
        ctk.set_appearance_mode("Dark")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.main_content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_content_frame.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self.main_content_frame.grid_columnconfigure(0, weight=1)
        self.main_content_frame.grid_rowconfigure(1, weight=1)

        self._build_top_bar()
        self._build_paned_area()
        self._build_bottom_bar()
        self._build_progress_overlay()

        self.set_ui_state("idle")
        self.after(100, self.set_initial_sash_pos)
        self.bind("<Configure>", self.on_resize)

        self.apply_mode(mode, initial=True)
        self._refresh_profile_menu()

    # ------------------------------------------------------------------ UI
    def _build_top_bar(self):
        self.top_frame = ctk.CTkFrame(self.main_content_frame, fg_color="transparent")
        self.top_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        self.top_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.top_frame, text="Folder:",
                     text_color=Colors.TEXT).grid(row=0, column=0, padx=(0, 5))
        self.path_entry = ctk.CTkEntry(
            self.top_frame,
            placeholder_text="Select your game's mod directory...",
            text_color=Colors.TEXT,
            fg_color=Colors.WIDGET_BG,
        )
        self.path_entry.grid(row=0, column=1, sticky="ew")

        self.browse_btn = self._mk_btn(self.top_frame, "...",
                                       self.select_folder, width=40)
        self.browse_btn.grid(row=0, column=2, padx=5)

        self.scan_btn = self._mk_btn(self.top_frame, "Scan/Refresh",
                                     self.run_scan)
        self.scan_btn.grid(row=0, column=3, padx=5)

        self.open_dir_btn = self._mk_btn(self.top_frame, "Open Directory",
                                         self.open_mod_directory)
        self.open_dir_btn.grid(row=0, column=4, padx=5)

        self.preview_cheats_btn = self._mk_btn(self.top_frame,
                                               "Preview enabled.txt",
                                               self.preview_enabled_cheats_popup)
        self.preview_cheats_btn.grid(row=0, column=5, padx=5)

        self.clear_mods_btn = self._mk_btn(self.top_frame, "Disable All Mods",
                                           self.clear_all_mods)
        self.clear_mods_btn.grid(row=0, column=6, padx=5)

        self.clear_cheats_btn = self._mk_btn(self.top_frame, "Disable All Cheats",
                                             self.clear_all_cheats)
        self.clear_cheats_btn.grid(row=0, column=7, padx=5)

        self.launch_game_btn = ctk.CTkButton(
            self.top_frame, text="Launch MHGU",
            command=self.launch_game,
            fg_color="#00ffdd", hover_color="#3acdc3",
            text_color="#000000",
            border_color=Colors.BUTTON_BORDER, border_width=1,
        )
        self.launch_game_btn.grid(row=0, column=8, padx=5)

    def _mk_btn(self, parent, text, command, width=None):
        kwargs = dict(
            text=text, command=command,
            fg_color=Colors.BUTTON_BG, hover_color=Colors.BUTTON_HOVER,
            text_color=Colors.TEXT,
            border_color=Colors.BUTTON_BORDER, border_width=1,
        )
        if width:
            kwargs["width"] = width
        return ctk.CTkButton(parent, **kwargs)

    def _build_paned_area(self):
        style = ttk.Style()
        style.configure("TPanedwindow", background=Colors.BG)
        style.configure(
            "TPanedwindow.Sash",
            background=Colors.BUTTON_BG,
            bordercolor=Colors.BG,
            relief="flat",
            sashthickness=6,
        )
        style.map("TPanedwindow.Sash",
                  background=[("active", Colors.BUTTON_HOVER)])

        self.paned_window = ttk.PanedWindow(self.main_content_frame,
                                            orient="horizontal")
        self.paned_window.grid(row=1, column=0, sticky="nsew",
                               padx=10, pady=(0, 5))

        # ----- Left panel -----
        self.list_panel = ctk.CTkFrame(self.paned_window, fg_color=Colors.FRAME_BG)
        self.list_panel.grid_rowconfigure(3, weight=1)
        self.list_panel.grid_columnconfigure(0, weight=1)
        self.paned_window.add(self.list_panel, weight=1)

        self.list_panel.drop_target_register(DND_FILES)
        self.list_panel.dnd_bind("<<Drop>>", self.on_drop)

        self.list_header_label = ctk.CTkLabel(
            self.list_panel, text="Mod Load Order (Drag files here to install)",
            text_color=Colors.HEADER_TEXT, fg_color=Colors.HEADER_BG,
            corner_radius=5,
        )
        self.list_header_label.grid(row=0, column=0, sticky="ew", padx=2, pady=2)

        self.view_switcher = ctk.CTkSegmentedButton(
            self.list_panel,
            values=["List View", "Tree View"],
            command=self.switch_view,
            fg_color=Colors.WIDGET_BG,
            selected_color=Colors.BUTTON_BG,
            selected_hover_color=Colors.BUTTON_HOVER,
            unselected_color=Colors.WIDGET_BG,
            unselected_hover_color=Colors.BUTTON_HOVER,
            text_color=Colors.TEXT,
        )
        self.view_switcher.set("List View")
        self.view_switcher.grid(row=1, column=0, sticky="ew", padx=5, pady=5)

        self.legend_frame = ctk.CTkFrame(self.list_panel, fg_color="transparent")
        self.legend_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=(0, 5))
        self.legend_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        def legend_item(color, text):
            f = ctk.CTkFrame(self.legend_frame, fg_color="transparent")
            ctk.CTkFrame(f, fg_color=color, width=15, height=15,
                         corner_radius=4, border_width=1,
                         border_color=Colors.TEXT).pack(side="left", padx=(0, 5))
            ctk.CTkLabel(f, text=text, text_color=Colors.TEXT,
                         font=ctk.CTkFont(size=11)).pack(side="left", anchor="w")
            return f

        for i, (color, text) in enumerate([
            (Colors.RESOLVED_CONFLICT, "Overrides other mods"),
            (Colors.CONFLICT, "Is overridden by others"),
            (Colors.NO_CONFLICT, "No conflicts"),
            (Colors.DISABLED, "Disabled"),
            (Colors.DRAG_HIGHLIGHT, "Selected (Ctrl+Click)"),
        ]):
            legend_item(color, text).grid(row=0, column=i, sticky="w", padx=5)

        self.view_container = ctk.CTkFrame(self.list_panel, fg_color="transparent")
        self.view_container.grid(row=3, column=0, sticky="nsew")
        self.view_container.grid_rowconfigure(0, weight=1)
        self.view_container.grid_columnconfigure(0, weight=1)

        self.mod_list_frame = ctk.CTkScrollableFrame(
            self.view_container, label_text="", fg_color="transparent")
        self.tree_frame = ctk.CTkFrame(self.view_container, fg_color="transparent")
        self.setup_treeview(style)
        self.mod_list_frame.grid(row=0, column=0, sticky="nsew")

        # ----- Selection bar (row 4): visible whenever mods are selected.
        # Makes ctrl-click selection unmistakable: it announces how many rows
        # are selected and what the selection is for.
        self.selection_bar = ctk.CTkFrame(
            self.list_panel, fg_color=Colors.DRAG_HIGHLIGHT, corner_radius=6)
        self.selection_bar.grid(row=4, column=0, sticky="ew", padx=5,
                                pady=(0, 5))
        self.selection_bar.grid_remove()  # hidden until something is selected
        self.selection_label = ctk.CTkLabel(
            self.selection_bar, text="", anchor="w", justify="left",
            text_color=Colors.SELECTED_BAR_TEXT,
            font=ctk.CTkFont(size=12, weight="bold"))
        self.selection_label.pack(fill="x", padx=10, pady=3)

        # ----- Right panel -----
        self.details_frame = ctk.CTkFrame(self.paned_window, fg_color=Colors.FRAME_BG)
        self.details_frame.grid_rowconfigure(1, weight=1)
        self.details_frame.grid_columnconfigure(0, weight=1)
        self.paned_window.add(self.details_frame, weight=1)

        # Smooth sash dragging: hide the expensive scrollable list while the
        # divider is held, exactly like the window-resize suppression below.
        # Button events on the sash are delivered to the ttk.PanedWindow itself
        # (child frames cover every other pixel), so binding here only fires
        # when the user actually grabs the divider.
        self.paned_window.bind("<ButtonPress-1>", self._on_sash_press)
        self.paned_window.bind("<B1-Motion>", self._on_sash_motion)
        self.paned_window.bind("<ButtonRelease-1>", self._on_sash_release,
                               add="+")

        ctk.CTkLabel(
            self.details_frame, text="Details / Actions",
            text_color=Colors.HEADER_TEXT, fg_color=Colors.HEADER_BG,
            corner_radius=5,
        ).grid(row=0, column=0, sticky="ew", padx=2, pady=2)

        self.details_content_frame = ctk.CTkFrame(
            self.details_frame, fg_color="transparent")
        self.details_content_frame.grid(row=1, column=0, sticky="nsew",
                                        padx=2, pady=2)
        self.details_content_frame.grid_rowconfigure(0, weight=1)
        self.details_content_frame.grid_columnconfigure(0, weight=1)

    def _build_bottom_bar(self):
        bottom = ctk.CTkFrame(self.main_content_frame, fg_color="transparent")
        bottom.grid(row=2, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

        self.apply_btn = self._mk_btn(bottom, "Apply New Order",
                                      self.apply_changes)
        self.apply_btn.pack(side="right")

        # --- Profiles: save / restore / import / export a load-out ---
        prof_frame = ctk.CTkFrame(bottom, fg_color="transparent")
        prof_frame.pack(side="right", padx=(0, 10))
        ctk.CTkLabel(prof_frame, text="Profile:",
                     text_color=Colors.TEXT).pack(side="left", padx=(0, 4))
        self.profile_var = ctk.StringVar(value="(none)")
        self.profile_menu = ctk.CTkOptionMenu(
            prof_frame, variable=self.profile_var,
            values=["(none)"], width=140,
            fg_color=Colors.WIDGET_BG, button_color=Colors.BUTTON_BG,
            button_hover_color=Colors.BUTTON_HOVER, text_color=Colors.TEXT,
        )
        self.profile_menu.pack(side="left", padx=2)
        self._mk_btn(prof_frame, "Save", self._ui_save_profile,
                     width=60).pack(side="left", padx=2)
        self._mk_btn(prof_frame, "Load", self._ui_load_profile,
                     width=60).pack(side="left", padx=2)
        self._mk_btn(prof_frame, "Del", self._ui_delete_profile,
                     width=50).pack(side="left", padx=2)
        self._mk_btn(prof_frame, "Export", self._ui_export_profiles,
                     width=60).pack(side="left", padx=2)
        self._mk_btn(prof_frame, "Import", self._ui_import_profiles,
                     width=60).pack(side="left", padx=2)

        self.status_label = ctk.CTkLabel(
            bottom, text="Ready. Select a folder and click Scan.",
            text_color=Colors.TEXT, anchor="w",
        )
        self.status_label.pack(side="left", fill="x", expand=True, padx=5)

    def _build_progress_overlay(self):
        self.progress_overlay = ctk.CTkFrame(
            self, fg_color=Colors.PROGRESS_OVERLAY, corner_radius=0)
        self.progress_overlay.grid_columnconfigure(0, weight=1)
        self.progress_overlay.grid_rowconfigure(1, weight=1)

        content = ctk.CTkFrame(self.progress_overlay, fg_color=Colors.FRAME_BG)
        content.grid(row=1, column=0, padx=50, pady=200, sticky="ew")
        content.grid_columnconfigure(0, weight=1)

        self.progress_header_label = ctk.CTkLabel(
            content, text="Applying New Mod Order...",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=Colors.TEXT,
        )
        self.progress_header_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.progress_bar = ctk.CTkProgressBar(
            content, fg_color=Colors.WIDGET_BG,
            progress_color=Colors.RESOLVED_CONFLICT,
        )
        self.progress_bar.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        self.progress_bar.set(0)

        self.progress_detail_label = ctk.CTkLabel(
            content, text="Initializing...",
            text_color=Colors.TEXT, anchor="w",
        )
        self.progress_detail_label.grid(row=2, column=0, padx=20, pady=(0, 20),
                                        sticky="ew")

    # ------------------------------------------------------------ mode setup

    def apply_mode(self, mode, initial=False):
        self.mode = mode
        self.current_details_mod = None
        self.mod_item_widgets.clear()
        self.cheat_widgets.clear()
        self.patch_widgets.clear()
        self.plugin_widgets.clear()

        for widget in self.details_content_frame.winfo_children():
            widget.destroy()

        # Title (handled by parent window)
        try:
            self.winfo_toplevel().title(
                f"dreamSort — Mod Manager {VERSION} [{self.mode_label()}]"
            )
        except Exception:
            pass

        # Placeholder + default path
        if mode == "recomp":
            self.path_entry.configure(
                placeholder_text="Select your MHGU Recomp root folder "
                                 "(contains mhgurecomp.exe, mods/, cheats/)..."
            )
            self.preview_cheats_btn.grid_remove()
            self.view_switcher.configure(values=["List View", "Tree View"])
            self.view_switcher.set("List View")
            # Switch to list view
            self.tree_frame.grid_remove()
            self.mod_list_frame.grid(row=0, column=0, sticky="nsew")
            default_path = self.recomp.root_path or ""
            if not default_path:
                default_path = self._default_recomp_path()
            self._update_path_display(default_path)
        else:
            self.path_entry.configure(
                placeholder_text="Select your game's mod directory..."
            )
            self.preview_cheats_btn.grid()
            self.view_switcher.configure(values=["List View", "Tree View"])
            default_path = self.ryujinx.mods_path or ""
            if not default_path:
                default_path = self._default_ryujinx_path()
            self._update_path_display(default_path)

        # Switch to list view on mode change
        self.view_switcher.set("List View")
        self.tree_frame.grid_remove()
        self.mod_list_frame.grid(row=0, column=0, sticky="nsew")

        if initial:
            self.after(200, self.run_scan)

    def mode_label(self):
        return "Recomp" if self.mode == "recomp" else "Ryujinx"

    def _default_ryujinx_path(self):
        try:
            if os.name == "nt":
                p = "~/AppData/Roaming/Ryujinx/mods/contents/0100770008dd8000/"
            elif sys.platform == "darwin":
                p = "~/Library/Application Support/Ryujinx/mods/contents/0100770008dd8000/"
            else:
                p = "~/.config/Ryujinx/mods/contents/0100770008dd8000/"
            return os.path.expanduser(p)
        except Exception:
            return ""

    def _default_recomp_path(self):
        # Try to find an mhgurecomp next to the current working directory
        try:
            cwd = os.getcwd()
            for name in RecompAnalyzer.EXE_NAMES:
                if os.path.exists(os.path.join(cwd, name)):
                    return cwd
        except Exception:
            pass
        return ""

    # -------------------------------------------------------------- config

    def load_config(self):
        try:
            with open(config_path(), "r") as f:
                cfg = json.load(f)
            self.ryujinx_exe_path = cfg.get("ryujinx_exe_path", "")
            self.game_file_path = cfg.get("game_file_path", "")
            self.recomp_exe_path = cfg.get("recomp_exe_path", "")
            self.remember_mode = cfg.get("remember_mode", False)
            saved_mode = cfg.get("mode", "ryujinx")
            ryujinx_path = cfg.get("ryujinx_path", "")
            recomp_root = cfg.get("recomp_root", "")
            if ryujinx_path:
                self.ryujinx.set_mods_path(ryujinx_path)
            if recomp_root:
                self.recomp.set_root(recomp_root)
            if self.remember_mode and saved_mode in ("ryujinx", "recomp"):
                self._preferred_mode = saved_mode
            else:
                self._preferred_mode = None
            self.profiles = cfg.get("profiles", {}) or {}
        except (FileNotFoundError, json.JSONDecodeError):
            self.ryujinx_exe_path = ""
            self.game_file_path = ""
            self.recomp_exe_path = ""
            self.remember_mode = False
            self._preferred_mode = None
            self.profiles = {}

    def save_config(self):
        try:
            data = {
                "ryujinx_exe_path": self.ryujinx_exe_path,
                "game_file_path": self.game_file_path,
                "recomp_exe_path": self.recomp_exe_path,
                "mode": self.mode,
                "remember_mode": self.remember_mode,
                "ryujinx_path": self.ryujinx.mods_path or "",
                "recomp_root": self.recomp.root_path or "",
                "profiles": self.profiles,
            }
            with open(config_path(), "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            messagebox.showerror("Config Error",
                                 f"Could not save settings:\n{e}")

    # ------------------------------------------------------------- path ops

    def _redact_path(self, path):
        if not path:
            return ""
        try:
            home = os.path.expanduser("~")
            if os.path.normcase(path).startswith(os.path.normcase(home)):
                return os.path.normpath(
                    os.path.join(os.path.dirname(home), "[REDACTED]")
                    + path[len(home):]
                )
        except Exception:
            pass
        return path

    def _unredact_path(self, path):
        if not path or "[REDACTED]" not in path:
            return path
        try:
            home = os.path.expanduser("~")
            prefix = os.path.normpath(
                os.path.join(os.path.dirname(home), "[REDACTED]"))
            if os.path.normcase(path).startswith(os.path.normcase(prefix)):
                return os.path.normpath(home + path[len(prefix):])
        except Exception:
            pass
        return path

    def _update_path_display(self, path):
        self.real_mods_path = os.path.normpath(path) if path else ""
        redacted = self._redact_path(self.real_mods_path)
        self.path_entry.delete(0, "end")
        self.path_entry.insert(0, redacted)

    def _get_current_path(self):
        entry = self.path_entry.get()
        expected = self._redact_path(self.real_mods_path)
        if entry == expected:
            return self.real_mods_path
        new = self._unredact_path(entry)
        self._update_path_display(new)
        return new

    # ----------------------------------------------------------- UI state

    def set_initial_sash_pos(self):
        try:
            if self.paned_window.winfo_viewable():
                total = self.paned_window.winfo_width()
                self.paned_window.sashpos(0, total // 2)
        except Exception:
            pass

    def set_ui_state(self, state):
        self.current_state = state
        if state == "working":
            self.main_content_frame.grid_remove()
            self.progress_overlay.grid(row=0, column=0, rowspan=3,
                                       sticky="nsew")
            self.progress_overlay.tkraise()
        else:
            self.progress_overlay.grid_remove()
            self.main_content_frame.grid()
            self.main_content_frame.tkraise()

    def _on_sash_press(self, event):
        # Take over the divider drag ourselves. ttk's default sash runs a
        # sashpos + full relayout on EVERY mouse motion event, and a high-poll
        # mouse (1000Hz) floods Tk faster than it can redraw -> the divider
        # lags the cursor and feels choppy. Instead we just record the target
        # x and pump it at a steady ~60fps cadence in _pump_sash.
        try:
            on_sash = self.paned_window.identify(event.x, event.y) != ""
        except Exception:
            on_sash = True
        if on_sash:
            self._sash_dragging = True
            self._sash_target = event.x
            self._sash_after = None
            self._pump_sash()
            return "break"   # stop ttk's own per-pixel sash drag

    def _on_sash_motion(self, event):
        if self._sash_dragging:
            self._sash_target = event.x
            return "break"

    def _pump_sash(self):
        if not self._sash_dragging:
            return
        try:
            self.paned_window.sashpos(0, self._sash_target)
        except Exception:
            pass
        self._sash_after = self.after(16, self._pump_sash)

    def _on_sash_release(self, event=None):
        if self._sash_dragging:
            self._sash_dragging = False
            if self._sash_after:
                self.after_cancel(self._sash_after)
                self._sash_after = None
            try:
                self.paned_window.sashpos(0, self._sash_target)
            except Exception:
                pass

    def on_resize(self, event=None):
        # Debounce only. Rows use fill="x" and reflow natively, so there is
        # nothing expensive to suppress while the window resizes.
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(250, self.on_resize_end)

    def on_resize_end(self):
        self.set_initial_sash_pos()
        self._after_id = None

    # ---------------------------------------------------------- tree view

    def setup_treeview(self, style):
        style.theme_use("default")
        base_font = max(10, int(11 * self.dpi_scale))
        row_height = max(22, int(24 * self.dpi_scale))
        style.configure(
            "Treeview",
            background=Colors.WIDGET_BG,
            foreground=Colors.TEXT,
            fieldbackground=Colors.WIDGET_BG,
            borderwidth=0,
            font=("", base_font),
            rowheight=row_height,
        )
        style.map("Treeview", background=[("selected", Colors.HIGHLIGHT_BG)])
        style.configure(
            "Treeview.Heading",
            background=Colors.TREE_HEADING_BG,
            foreground=Colors.TEXT,
            relief="flat",
            font=("", base_font, "bold"),
        )
        style.map("Treeview.Heading",
                  background=[("active", Colors.BUTTON_HOVER)])
        self.tree = ttk.Treeview(
            self.tree_frame, columns=("status",), show="tree headings")
        self.tree.heading("#0", text="Mod / File")
        self.tree.heading("status", text="Status")
        self.tree.column("#0", stretch=True, width=450)
        self.tree.column("status", stretch=True, width=200)
        self.tree.tag_configure("winner", foreground=Colors.RESOLVED_CONFLICT)
        self.tree.tag_configure("loser", foreground=Colors.CONFLICT)
        self.tree.tag_configure("loaded", foreground=Colors.NO_CONFLICT)
        self.tree.tag_configure("noconflict", foreground=Colors.TEXT)
        self.tree.tag_configure("cheat", foreground=Colors.CHEAT_MOD)
        self.tree.tag_configure("disabled", foreground=Colors.DISABLED)
        self.tree.pack(expand=True, fill="both")

    def switch_view(self, view_name):
        if self.current_state == "working":
            return
        if self.mode == "recomp":
            if view_name == "List View":
                self.tree_frame.grid_remove()
                self.mod_list_frame.grid(row=0, column=0, sticky="nsew")
            else:
                self.populate_recomp_tree()
                self.mod_list_frame.grid_remove()
                self.tree_frame.grid(row=0, column=0, sticky="nsew")
            return
        if view_name == "List View":
            self.tree_frame.grid_remove()
            self.mod_list_frame.grid(row=0, column=0, sticky="nsew")
        else:
            self.populate_mod_tree()
            self.mod_list_frame.grid_remove()
            self.tree_frame.grid(row=0, column=0, sticky="nsew")

    # ------------------------------------------------------------ scanning

    def select_folder(self):
        if self.current_state == "working":
            return
        title = ("Select MHGU Recomp root folder"
                 if self.mode == "recomp"
                 else "Select Game Mod Folder")
        path = filedialog.askdirectory(title=title)
        if path:
            self._update_path_display(path)
            self.run_scan()

    def run_scan(self):
        if self.mode == "recomp":
            self.run_scan_recomp()
        else:
            self.run_scan_ryujinx()

    def run_scan_ryujinx(self):
        path = self._get_current_path()
        if not self.ryujinx.set_mods_path(path):
            self.status_label.configure(text="Error: Invalid folder path.")
            return
        self.current_details_mod = None
        for w in self.details_content_frame.winfo_children():
            w.destroy()
        self.status_label.configure(text="Scanning...")
        self.update_idletasks()
        self.ryujinx.scan_and_analyze()
        self._initialize_pending_cheats()
        self.populate_mod_list()
        self.update_all_border_colors()
        if self.view_switcher.get() == "Tree View":
            self.populate_mod_tree()
        conflict_count = len(
            [m for m in self.ryujinx.conflicts if self._is_mod_enabled(m)])
        msg = f"Scan complete. {conflict_count} mods with enabled conflicts."
        if self.ryujinx.mods_json_path:
            msg += " (Ryujinx mods.json path found)"
        else:
            msg += " (Ryujinx mods.json path not found)"
        self.status_label.configure(text=msg)
        self.save_config()

    def run_scan_recomp(self):
        path = self._get_current_path()
        if not path or not os.path.isdir(path):
            self.status_label.configure(text="Error: Invalid folder path.")
            return
        if not self.recomp.set_root(path):
            self.status_label.configure(text="Error: Invalid recomp root.")
            return
        self.current_details_mod = None
        for w in self.details_content_frame.winfo_children():
            w.destroy()
        self.status_label.configure(text="Scanning recomp installation...")
        self.update_idletasks()
        self.recomp.scan()
        self.populate_recomp_list()
        if self.view_switcher.get() == "Tree View":
            self.populate_recomp_tree()
        enabled_mods = sum(1 for m in self.recomp.mods.values() if m["enabled"])
        msg = (f"Recomp scan complete. {enabled_mods} enabled mods, "
               f"{len(self.recomp.patches)} patches, "
               f"{len(self.recomp.plugins)} plugins, "
               f"{len(self.recomp.cheats)} cheat files.")
        if self.recomp.locate_recomp_exe() or self.recomp_exe_path:
            msg += " (mhgurecomp found)"
        else:
            msg += " (mhgurecomp.exe not found in root)"
        self.status_label.configure(text=msg)
        self.save_config()

    # ----------------------------------------------------- Ryujinx populate

    def _initialize_pending_cheats(self):
        self.pending_cheat_selections.clear()
        globally_enabled = set()
        folder = self.ryujinx.special_cheats_folder_name or "cheats"
        enabled_txt = os.path.join(self.ryujinx.mods_path, folder, "enabled.txt")
        if os.path.exists(enabled_txt):
            try:
                with open(enabled_txt, "r", encoding="utf-8",
                          errors="ignore") as f:
                    for line in f:
                        m = re.search(r"<(.*?) Cheat>", line)
                        if m:
                            globally_enabled.add(m.group(1).strip())
            except Exception as e:
                print(f"Warning: Could not read enabled.txt: {e}")
        for mod_name in self.ryujinx.cheat_only_mods:
            self.pending_cheat_selections[mod_name] = {}
            cheat_path = os.path.join(self.ryujinx.mods_path, mod_name, "cheats")
            if not os.path.isdir(cheat_path):
                continue
            try:
                for filename in os.listdir(cheat_path):
                    if not filename.endswith(".txt") or filename.lower() == "enabled.txt":
                        continue
                    with open(os.path.join(cheat_path, filename), "r",
                              encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    for name_with_brackets, code in re.findall(
                            r"(\[.*?\])\s*([\s\S]*?)(?=\n\s*\[|$)", content):
                        cheat_name = name_with_brackets.strip()[1:-1]
                        if cheat_name and code.strip():
                            self.pending_cheat_selections[mod_name][cheat_name] = \
                                cheat_name in globally_enabled
            except Exception as e:
                print(f"Warning: Could not parse cheats for '{mod_name}': {e}")

    def populate_mod_list(self):
        # Ryujinx version
        for w in self.mod_list_frame.winfo_children():
            w.destroy()
        self.mod_item_widgets.clear()
        self.selected_mods.clear()
        self._update_selection_bar()
        self.recomp_mods_section = None
        special = self.ryujinx.special_cheats_folder_name
        romfs_mods = [m for m in self.ryujinx.load_order
                      if m not in self.ryujinx.cheat_only_mods and m != special]
        cheat_mods = [m for m in self.ryujinx.load_order
                      if m in self.ryujinx.cheat_only_mods]
        for name in romfs_mods:
            self.create_mod_item(name, "romfs")
        if special:
            self.create_mod_item(special, "special_cheats")
        if cheat_mods:
            ctk.CTkLabel(self.mod_list_frame,
                         text="--- Detected Cheats ---",
                         text_color=Colors.CHEAT_MOD).pack(fill="x", padx=5,
                                                            pady=(10, 2))
        for name in cheat_mods:
            self.create_mod_item(name, "cheat_only")

    def create_mod_item(self, mod_name, mod_type):
        clean = self.ryujinx.strip_prefix(mod_name)
        border = ctk.CTkFrame(self.mod_list_frame, corner_radius=8,
                              fg_color=Colors.DISABLED)
        border.pack(fill="x", padx=5, pady=2)
        content = ctk.CTkFrame(border, fg_color=Colors.WIDGET_BG,
                               corner_radius=7)
        content.pack(expand=True, fill="both", padx=1, pady=1)
        border.original_name = mod_name
        content.grid_columnconfigure(1, weight=1)
        label = ctk.CTkLabel(content, text=clean, text_color=Colors.TEXT,
                             anchor="w", fg_color="transparent")
        if mod_type == "romfs":
            is_enabled = not mod_name.startswith("~")
            checkbox = ctk.CTkCheckBox(content, text="", width=20,
                                       onvalue=True, offvalue=False,
                                       command=self.on_checkbox_toggle)
            checkbox.grid(row=0, column=0, padx=(5, 0), pady=4)
            if is_enabled:
                checkbox.select()
            border.checkbox = checkbox
            handle = ctk.CTkLabel(content, text="≡", text_color=Colors.TEXT,
                                  fg_color="transparent", width=20)
            handle.grid(row=0, column=2, padx=(0, 5), pady=2)
            self.setup_drag_drop(border, handle)
            self._attach_select_ring(content, border, corner_radius=7)
        elif mod_type == "special_cheats":
            border.configure(fg_color=Colors.BG)
        else:
            label.configure(text=f"~ {clean}")
        label.grid(row=0, column=1, sticky="ew", padx=10)
        self.mod_item_widgets[mod_name] = border
        clickable = content if mod_type == "special_cheats" else label
        clickable.bind("<Button-1>",
                       lambda e, m=mod_name: self._row_primary_click(m))
        if mod_type == "special_cheats":
            label.bind("<Button-1>",
                       lambda e, m=mod_name: self.show_details(m))
        all_w = [border, content, label]
        if mod_type == "romfs":
            all_w.extend([border.checkbox, handle])
        for w in all_w:
            w.bind("<Button-3>",
                   lambda e, m=mod_name: self.show_context_menu(e, m))
            w.bind("<Button-2>",
                   lambda e, m=mod_name: self.show_context_menu(e, m))
            if mod_type == "romfs":
                w.bind("<Control-Button-1>",
                       lambda e, m=mod_name: self._toggle_mod_selection(m))

    def _row_primary_click(self, mod_name):
        # Plain left-click: focus a single row (ring it) and show its details.
        # Ctrl+left-click is handled separately as a multi-select toggle.
        widget = self.mod_item_widgets.get(mod_name)
        if widget is not None and hasattr(widget, "_ring_face"):
            if mod_name not in self.selected_mods or len(self.selected_mods) > 1:
                self._clear_selection()
                self.selected_mods.add(mod_name)
                self._set_row_ring(widget, True)
                self._update_selection_bar()
        self.show_details(mod_name)

    def on_checkbox_toggle(self):
        self.update_all_border_colors()
        if self.view_switcher.get() == "Tree View":
            self.populate_mod_tree()

    def _reorderable_widgets(self):
        # Widgets in the mod list that carry an original_name (drag/reorder).
        if self.mode == "recomp":
            if self.recomp_mods_section:
                return [w for w in self.recomp_mods_section.content.pack_slaves()
                        if hasattr(w, "original_name")]
            return []
        return [w for w in self.mod_list_frame.pack_slaves()
                if hasattr(w, "original_name")]

    def update_all_border_colors(self):
        if self.mode == "recomp":
            return  # recomp doesn't use conflict colouring
        ordered = self.mod_list_frame.pack_slaves()
        current_names = [w.original_name for w in ordered
                        if hasattr(w, "original_name")]
        for widget in ordered:
            if not hasattr(widget, "original_name"):
                continue
            mod_name = widget.original_name
            if (mod_name in self.selected_mods
                    or widget is self.drag_data.get("item")):
                continue  # keep the selection / drag ring intact
            if not hasattr(widget, "checkbox"):
                if mod_name == self.ryujinx.special_cheats_folder_name:
                    widget.configure(fg_color=Colors.BG)
                elif mod_name in self.ryujinx.cheat_only_mods:
                    widget.configure(fg_color=Colors.CHEAT_MOD)
                continue
            if not widget.checkbox.get():
                widget.configure(fg_color=Colors.DISABLED)
                continue
            overridden = False
            overriding = False
            if mod_name in self.ryujinx.conflicts:
                my_idx = current_names.index(mod_name)
                for file, others in self.ryujinx.conflicts[mod_name].items():
                    for other in others:
                        if self._is_mod_enabled(other):
                            try:
                                oi = current_names.index(other)
                                if oi < my_idx:
                                    overridden = True
                                else:
                                    overriding = True
                            except ValueError:
                                continue
            if overridden:
                widget.configure(fg_color=Colors.CONFLICT)
            elif overriding:
                widget.configure(fg_color=Colors.RESOLVED_CONFLICT)
            else:
                widget.configure(fg_color=Colors.NO_CONFLICT)

    def _is_mod_enabled(self, mod_name):
        w = self.mod_item_widgets.get(mod_name)
        if not w:
            return False
        if hasattr(w, "checkbox"):
            return w.checkbox.get()
        return True

    def populate_mod_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        ordered = self._reorderable_widgets()
        current_names = [w.original_name for w in ordered]
        tree_data = []
        try:
            for mod_name in current_names:
                info = {"name": mod_name, "status": "", "tag": "noconflict",
                        "files": []}
                widget = self.mod_item_widgets.get(mod_name)
                is_romfs = widget and hasattr(widget, "checkbox")
                if not is_romfs:
                    info["status"] = ("Cheat Only"
                                      if mod_name in self.ryujinx.cheat_only_mods
                                      else "Ryujinx Enabled Cheats File")
                    info["tag"] = "cheat"
                elif not widget.checkbox.get():
                    info["status"] = "Disabled"
                    info["tag"] = "disabled"
                else:
                    conflicts = 0
                    overrides = 0
                    is_overridden = False
                    if mod_name in self.ryujinx.conflicts:
                        for file_path, other_mods in self.ryujinx.conflicts[mod_name].items():
                            involved = [mod_name] + [m for m in other_mods
                                                     if self._is_mod_enabled(m)]
                            if len(involved) > 1:
                                winner = min(involved, key=lambda m:
                                             current_names.index(m)
                                             if m in current_names else float("inf"))
                                if mod_name == winner:
                                    overrides += 1
                                else:
                                    conflicts += 1
                                    is_overridden = True
                    if is_overridden:
                        info["status"] = f"Conflicts ({conflicts})"
                        info["tag"] = "loser"
                    elif overrides > 0:
                        info["status"] = f"Overrides ({overrides})"
                        info["tag"] = "winner"
                    else:
                        info["status"] = "No Conflicts"
                        info["tag"] = "noconflict"
                if mod_name in self.ryujinx.mod_files and is_romfs:
                    for file_path in sorted(list(self.ryujinx.mod_files[mod_name])):
                        fi = {"path": file_path, "status": "", "tag": "noconflict"}
                        if widget.checkbox.get():
                            potential = (mod_name in self.ryujinx.conflicts
                                         and file_path in self.ryujinx.conflicts[mod_name])
                            if not potential:
                                fi["status"] = "Loaded"
                                fi["tag"] = "loaded"
                            else:
                                involved = self.ryujinx.conflicts[mod_name][file_path] + [mod_name]
                                enabled_inv = [m for m in involved
                                               if self._is_mod_enabled(m)]
                                if len(enabled_inv) < 2:
                                    fi["status"] = "Loaded"
                                    fi["tag"] = "loaded"
                                else:
                                    winner = min(enabled_inv, key=lambda m:
                                                 current_names.index(m)
                                                 if m in current_names else float("inf"))
                                    if mod_name == winner:
                                        losers = [self.ryujinx.strip_prefix(m)
                                                  for m in enabled_inv if m != mod_name]
                                        fi["status"] = f"Overrides: {', '.join(losers)}"
                                        fi["tag"] = "winner"
                                    else:
                                        fi["status"] = (f"Conflicts (by "
                                                        f"{self.ryujinx.strip_prefix(winner)})")
                                        fi["tag"] = "loser"
                        info["files"].append(fi)
                tree_data.append(info)
        except Exception:
            traceback.print_exc()
        for md in tree_data:
            clean = self.ryujinx.strip_prefix(md["name"])
            mod_id = self.tree.insert("", "end", text=clean,
                                      values=(md["status"],),
                                      tags=(md["tag"],))
            pm = {"winner": 0, "loser": 0, "loaded": 1, "noconflict": 2}
            for fi in sorted(md["files"],
                             key=lambda f: (pm.get(f["tag"], 99), f["path"])):
                self.tree.insert(mod_id, "end", text=fi["path"],
                                 values=(fi["status"],),
                                 tags=(fi["tag"],))

    def populate_recomp_tree(self):
        # Recomp tree view: each romFS mod as a parent node, its romfs/
        # files as children.
        for i in self.tree.get_children():
            self.tree.delete(i)
        for clean, data in self.recomp.get_ordered_mods():
            has_nro = data.get("has_nro")
            if not data.get("has_romfs"):
                continue
            if has_nro and clean.lower() not in self.FOUNDATION_LIBS:
                continue
            status = "Enabled" if data.get("enabled") else "Disabled"
            tag = "noconflict" if data.get("enabled") else "disabled"
            mod_id = self.tree.insert("", "end",
                                      text=self._display_mod_name(clean),
                                      values=(status,), tags=(tag,))
            root = data.get("path", "")
            romfs_dir = os.path.join(root, "romfs")
            if os.path.isdir(romfs_dir):
                for dirpath, _dirs, files in os.walk(romfs_dir):
                    for f in sorted(files):
                        full = os.path.join(dirpath, f)
                        rel = os.path.relpath(full, romfs_dir).replace("\\", "/")
                        self.tree.insert(mod_id, "end", text=rel,
                                         values=("",), tags=("loaded",))

    # ------------------------------------------------------ Recomp populate

    def populate_recomp_list(self):
        for w in self.mod_list_frame.winfo_children():
            w.destroy()
        self.mod_item_widgets.clear()
        self.cheat_widgets.clear()
        self.patch_widgets.clear()
        self.plugin_widgets.clear()
        self.selected_mods.clear()
        self._update_selection_bar()

        # --- Mods section: ONLY romFS mods. A package that ships an .nro is
        # a plugin, not a mod (foundational libraries are excepted). Pure
        # exefs/plugin packages appear under their own sections below.
        def _is_mod_row(clean, d):
            if not d.get("has_romfs"):
                return False
            if d.get("has_nro") and clean.lower() not in self.FOUNDATION_LIBS:
                return False
            return True

        romfs_mods = [(n, d) for n, d in self.recomp.get_ordered_mods()
                      if _is_mod_row(n, d)]

        # --- "All" section: every mod folder in one flat list, collapsed by
        # default so nothing is hidden in the categorized sections below.
        all_mods = list(self.recomp.get_ordered_mods())
        all_section = CollapsibleSection(
            self.mod_list_frame,
            f"All ({len(all_mods)})",
            start_collapsed=True,
        )
        all_section.pack(fill="x", padx=5, pady=2)
        for clean_name, data in all_mods:
            self._create_recomp_mod_row(all_section.content, clean_name, data)

        mods_section = CollapsibleSection(
            self.mod_list_frame,
            f"Mods ({len(romfs_mods)})",
        )
        mods_section.pack(fill="x", padx=5, pady=2)
        self.recomp_mods_section = mods_section

        for clean_name, data in romfs_mods:
            self._create_recomp_mod_row(mods_section.content, clean_name, data)

        # --- Patches section ---
        patch_section = CollapsibleSection(
            self.mod_list_frame,
            f"Exefs Patches ({len(self.recomp.patches)})",
        )
        patch_section.pack(fill="x", padx=5, pady=2)
        if not self.recomp.patches:
            ctk.CTkLabel(patch_section.content,
                         text="  (no .pchtxt or .ips files found)",
                         text_color=Colors.DISABLED,
                         anchor="w").pack(fill="x", padx=10, pady=2)
        for entry in self.recomp.patches:
            self._create_recomp_file_row(
                patch_section.content, entry, "patch")

        # --- Plugins section ---
        plugin_section = CollapsibleSection(
            self.mod_list_frame,
            f"Plugins ({len(self.recomp.plugins)})",
        )
        plugin_section.pack(fill="x", padx=5, pady=2)
        if not self.recomp.plugins:
            ctk.CTkLabel(plugin_section.content,
                         text="  (no .nro plugins found)",
                         text_color=Colors.DISABLED,
                         anchor="w").pack(fill="x", padx=10, pady=2)
        for entry in self.recomp.plugins:
            self._create_recomp_file_row(
                plugin_section.content, entry, "plugin")

        # --- Cheats section ---
        cheats_section = CollapsibleSection(
            self.mod_list_frame,
            f"Cheats ({len(self.recomp.cheats)})",
        )
        cheats_section.pack(fill="x", padx=5, pady=2)
        if not self.recomp.cheats:
            ctk.CTkLabel(cheats_section.content,
                         text="  (no .txt cheat files in /cheats/)",
                         text_color=Colors.DISABLED,
                         anchor="w").pack(fill="x", padx=10, pady=2)
        for clean_name in sorted(self.recomp.cheats.keys()):
            self._create_recomp_cheat_row(
                cheats_section.content, clean_name,
                self.recomp.cheats[clean_name])

        # Apply live conflict coloring to the mod rows now that they exist.
        self._recomp_recolor_all()

    # Mod folders that are foundational libraries: shown bold and
    # properly capitalized so they stand out in the list.
    FOUNDATION_LIBS = {"katlib": "KatLib", "forge": "Forge"}

    def _display_mod_name(self, clean_name):
        return self.FOUNDATION_LIBS.get(clean_name.lower(), clean_name)

    def _create_recomp_mod_row(self, parent, clean_name, data):
        # Single frame with a rounded border (not two nested frames) so the
        # colored outline follows the rounded corners exactly — no slim
        # rectangular line poking out at the corners.
        row = ctk.CTkFrame(
            parent, corner_radius=10,
            fg_color=Colors.WIDGET_BG,
            border_color=Colors.NO_CONFLICT if data["enabled"]
            else Colors.DISABLED,
            border_width=2,
        )
        row.pack(fill="x", padx=4, pady=3)
        row.original_name = clean_name
        row.grid_columnconfigure(1, weight=1)

        checkbox = ctk.CTkCheckBox(row, text="", width=20,
                                  onvalue=True, offvalue=False,
                                  command=self._on_recomp_mod_toggle)
        checkbox.grid(row=0, column=0, padx=(8, 0), pady=4)
        if data["enabled"]:
            checkbox.select()
        row.checkbox = checkbox
        row._on_color = Colors.NO_CONFLICT
        row._off_color = Colors.DISABLED

        # Badges
        badges = []
        if data["has_romfs"]:
            badges.append("romfs")
        if data["has_exefs"]:
            badges.append("exefs")
        if data["has_plugins"]:
            badges.append("plugins")
        badge_text = f"  [{' | '.join(badges)}]" if badges else ""

        display = self._display_mod_name(clean_name)
        is_lib = clean_name.lower() in self.FOUNDATION_LIBS
        name_font = ctk.CTkFont(size=13, weight="bold") if is_lib else None
        label = ctk.CTkLabel(
            row, text=f"{display}{badge_text}",
            text_color=Colors.TEXT, anchor="w", fg_color="transparent",
            font=name_font,
        )
        label.grid(row=0, column=1, sticky="ew", padx=10)

        handle = ctk.CTkLabel(row, text="≡", text_color=Colors.TEXT,
                              fg_color="transparent", width=20)
        handle.grid(row=0, column=2, padx=(0, 6), pady=2)

        self.setup_drag_drop(row, handle)
        self._attach_select_ring(row, row, corner_radius=10)
        self.mod_item_widgets[clean_name] = row

        for w in [row, label, handle, checkbox]:
            w.bind("<Button-3>",
                   lambda e, m=clean_name: self._recomp_context_menu(e, m))
            w.bind("<Button-2>",
                   lambda e, m=clean_name: self._recomp_context_menu(e, m))
            w.bind("<Control-Button-1>",
                   lambda e, m=clean_name: self._toggle_mod_selection(m))
        label.bind("<Button-1>",
                   lambda e, m=clean_name: self._row_primary_click(m))

    def _recomp_row_color(self, clean_name):
        # Border color for a recomp mod row based on enabled state and file
        # conflicts (mod higher in the list wins, same convention as Ryujinx).
        widget = self.mod_item_widgets.get(clean_name)
        if widget is None or not widget.checkbox.get():
            return Colors.DISABLED
        if clean_name not in getattr(self.recomp, "conflicts", {}):
            return Colors.NO_CONFLICT
        ordered = [w.original_name for w in self._reorderable_widgets()]
        if clean_name not in ordered:
            return Colors.NO_CONFLICT
        my_idx = ordered.index(clean_name)
        overridden = False
        for _rel, others in self.recomp.conflicts[clean_name].items():
            for o in others:
                ow = self.mod_item_widgets.get(o)
                if ow is None or not ow.checkbox.get():
                    continue
                if o in ordered and ordered.index(o) < my_idx:
                    overridden = True
        return Colors.CONFLICT if overridden else Colors.RESOLVED_CONFLICT

    def _recomp_recolor_all(self):
        for clean_name, widget in self.mod_item_widgets.items():
            if hasattr(widget, "checkbox"):
                if (clean_name in self.selected_mods
                        or widget is self.drag_data.get("item")):
                    continue  # keep the selection / drag ring intact
                widget.configure(border_color=self._recomp_row_color(clean_name))

    def _on_recomp_mod_toggle(self):
        # Recolor rows to reflect enabled state + conflict status.
        self._recomp_recolor_all()

    def _create_recomp_file_row(self, parent, entry, kind):
        # Create a row for a patch or plugin file.
        is_patch = (kind == "patch")
        prefix = "  └ "
        border = ctk.CTkFrame(
            parent, corner_radius=6,
            fg_color=Colors.NO_CONFLICT if entry["enabled"] else Colors.DISABLED,
        )
        border.pack(fill="x", padx=20, pady=1)
        content = ctk.CTkFrame(border, fg_color=Colors.WIDGET_BG,
                               corner_radius=5)
        content.pack(expand=True, fill="both", padx=1, pady=1)
        content.grid_columnconfigure(1, weight=1)

        checkbox = ctk.CTkCheckBox(content, text="", width=18,
                                   onvalue=True, offvalue=False,
                                   command=lambda: self._on_recomp_file_toggle(border))
        checkbox.grid(row=0, column=0, padx=(5, 0), pady=3)
        if entry["enabled"]:
            checkbox.select()
        border.checkbox = checkbox
        border.original_name = None  # not draggable

        display = f"{prefix}{entry['mod']} › {entry['filename']}"
        label = ctk.CTkLabel(content, text=display, text_color=Colors.TEXT,
                             anchor="w", fg_color="transparent")
        label.grid(row=0, column=1, sticky="ew", padx=8)

        key = (entry["mod"], entry["rel_path"])
        if is_patch:
            self.patch_widgets[key] = border
            border.patch_key = key
        else:
            self.plugin_widgets[key] = border
            border.plugin_key = key

        label.bind("<Button-1>",
                   lambda e, ent=entry, k=kind:
                   self._show_recomp_file_details(ent, k))

    def _on_recomp_file_toggle(self, widget):
        widget.configure(
            fg_color=Colors.NO_CONFLICT if widget.checkbox.get()
            else Colors.DISABLED
        )

    def _create_recomp_cheat_row(self, parent, clean_name, data):
        border = ctk.CTkFrame(
            parent, corner_radius=6,
            fg_color=Colors.NO_CONFLICT if data["enabled"] else Colors.DISABLED,
        )
        border.pack(fill="x", padx=20, pady=1)
        content = ctk.CTkFrame(border, fg_color=Colors.WIDGET_BG,
                               corner_radius=5)
        content.pack(expand=True, fill="both", padx=1, pady=1)
        content.grid_columnconfigure(1, weight=1)

        checkbox = ctk.CTkCheckBox(content, text="", width=18,
                                   onvalue=True, offvalue=False,
                                   command=lambda: self._on_recomp_file_toggle(border))
        checkbox.grid(row=0, column=0, padx=(5, 0), pady=3)
        if data["enabled"]:
            checkbox.select()
        border.checkbox = checkbox
        border.original_name = None
        border.cheat_name = clean_name
        border.cheat_path = data["path"]

        label = ctk.CTkLabel(content, text=f"  └ {clean_name}",
                             text_color=Colors.TEXT, anchor="w",
                             fg_color="transparent")
        label.grid(row=0, column=1, sticky="ew", padx=8)

        self.cheat_widgets[clean_name] = border

        label.bind("<Button-1>",
                   lambda e, n=clean_name:
                   self._show_recomp_cheat_details(n))

    # -------------------------------------------------- Recomp actions

    def _recomp_context_menu(self, event, clean_name):
        menu = tk.Menu(self, tearoff=0,
                       bg=Colors.WIDGET_BG, fg=Colors.TEXT,
                       activebackground=Colors.BUTTON_HOVER,
                       activeforeground=Colors.TEXT,
                       relief="flat", borderwidth=1)
        multi = (len(self.selected_mods) > 1
                 and clean_name in self.selected_mods)
        if multi:
            n = len(self.selected_mods)
            menu.add_command(label=f"Enable Selected ({n})",
                             command=lambda: self._bulk_enable(True))
            menu.add_command(label=f"Disable Selected ({n})",
                             command=lambda: self._bulk_enable(False))
            menu.add_separator()
            menu.add_command(label=f"Delete Selected ({n})",
                             command=self._bulk_delete)
        else:
            menu.add_command(
                label="Delete",
                command=lambda: self._recomp_delete_mod(clean_name))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _recomp_delete_mod(self, clean_name):
        mod_path = self.recomp.get_current_mod_path(clean_name)
        if not mod_path:
            messagebox.showerror("Error", "Mod path not found.")
            return
        if not messagebox.askyesno(
            "Confirm Deletion",
            f"Permanently delete the mod '{clean_name}'?\n\n"
            f"Path: {mod_path}\n\nThis action cannot be undone.",
        ):
            return
        try:
            shutil.rmtree(mod_path)
            self.status_label.configure(
                text=f"Deleted '{clean_name}'. Refreshing list...")
            self.run_scan()
        except PermissionError:
            messagebox.showerror(
                "Deletion Failed",
                f"Permission denied. Close MHGU Recomp and retry, "
                "or run dreamSort as administrator.",
            )
        except Exception as e:
            messagebox.showerror("Deletion Failed", str(e))

    @staticmethod
    def _read_mod_metadata(mod_path):
        # Best-effort extract of (mod_name, version, author) from metadata a
        # mod ships next to its romfs/ folder. Looks for, in order:
        #   - manifest.txt  (flat key=value: mod_name=, version=, author(s)=)
        #   - mod.json / info.json / plugin.json
        # Missing values come back as 'Unknown'.
        name = version = author = "Unknown"
        if not mod_path or not os.path.isdir(mod_path):
            return name, version, author

        # 1) Simple flat key=value text file — easiest for devs.
        for fname in ("manifest.txt", "mod.txt", "info.txt"):
            fp = os.path.join(mod_path, fname)
            if not os.path.isfile(fp):
                continue
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        # Support both "key=value" and "key: value".
                        if "=" in line:
                            key, _, val = line.partition("=")
                        elif ":" in line:
                            key, _, val = line.partition(":")
                        else:
                            continue
                        key = key.strip().lower().rstrip(":")
                        val = val.strip()
                        # Strip surrounding quotes if a dev wrote them.
                        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("\"", "'"):
                            val = val[1:-1]
                        if key in ("mod_name", "name"):
                            name = val or name
                        elif key == "version":
                            version = val or version
                        elif key in ("author", "authors", "author(s)"):
                            author = val or author
                if name != "Unknown" or version != "Unknown" or \
                        author != "Unknown":
                    return name, version, author
            except Exception:
                pass

        # 2) JSON manifests, if a dev already ships one.
        for fname in ("mod.json", "info.json", "plugin.json"):
            fp = os.path.join(mod_path, fname)
            if os.path.isfile(fp):
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                        j = json.load(f)
                    name = str(j.get("name", name))
                    version = str(j.get("version", version))
                    author = str(j.get("author",
                                       j.get("authors", author)))
                    if name != "Unknown" or version != "Unknown" \
                            or author != "Unknown":
                        return name, version, author
                except Exception:
                    pass
        return name, version, author

    def _build_details_card(self, display_name, version, author, enabled,
                            location, type_str, open_path):
        for w in self.details_content_frame.winfo_children():
            w.destroy()
        card = ctk.CTkFrame(self.details_content_frame,
                            fg_color=Colors.WIDGET_BG, corner_radius=8)
        card.pack(fill="x", padx=8, pady=8)
        card.grid_columnconfigure(1, weight=1)
        rows = [
            ("Mod Name:", display_name),
            ("Version Number:", version),
            ("Author:", author),
            ("Status:", "Enabled" if enabled else "Disabled"),
            ("Location:", self._redact_path(location) or "Unknown"),
            ("Type:", type_str),
        ]
        for i, (label, value) in enumerate(rows):
            ctk.CTkLabel(card, text=label, text_color=Colors.DISABLED,
                         anchor="w").grid(row=i, column=0, sticky="w",
                                          padx=(12, 8), pady=6)
            val_lbl = ctk.CTkLabel(card, text=str(value),
                                   text_color=Colors.TEXT,
                                   anchor="w", justify="left")
            val_lbl.grid(row=i, column=1, sticky="ew", padx=(0, 12),
                         pady=6)
            # Wrap a little before the pane edge so long paths don't get
            # clipped mid-word at the boundary.
            val_lbl.bind(
                "<Configure>",
                lambda e, v=val_lbl: v.configure(
                    wraplength=max(50, e.width - 14)))
        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.grid(row=len(rows), column=0, columnspan=2, sticky="w",
                     padx=12, pady=(4, 10))
        ctk.CTkButton(btn_row, text="Open mod folder", width=130,
                      fg_color=Colors.BUTTON_BG, hover_color=Colors.BUTTON_HOVER,
                      command=lambda: open_in_file_explorer(open_path)
                      ).pack(side="left")

    def _show_recomp_mod_details(self, clean_name):
        if self.current_state == "working":
            return
        self.current_details_mod = clean_name
        data = self.recomp.mods.get(clean_name, {})
        mod_path = data.get("path", "")
        meta_name, version, author = self._read_mod_metadata(mod_path)
        display_name = (meta_name if meta_name != "Unknown"
                        else self._display_mod_name(clean_name))
        self._build_details_card(display_name, version, author,
                                 data.get("enabled"), mod_path,
                                 "romFS Mod", mod_path)

    def _show_recomp_file_details(self, entry, kind):
        # Plugins and patches get the same structured details card as mods,
        # including manifest metadata resolved from their parent mod folder.
        parent = self.recomp.mods.get(entry.get("mod", ""), {})
        parent_path = parent.get("path", "")
        meta_name, version, author = self._read_mod_metadata(parent_path)
        display_name = entry.get("filename", "plugin")
        title = "EXEFS Patch" if kind == "patch" else "Plugin"
        type_str = f"{title} (.nro)" if kind == "plugin" else f"{title} (.pchtxt/.ips)"
        open_path = parent_path or entry.get("path", "")
        self._build_details_card(
            display_name, version, author, entry.get("enabled"),
            parent_path or entry.get("path", ""), type_str, open_path)

    def _show_recomp_cheat_details(self, clean_name):
        data = self.recomp.cheats.get(clean_name)
        if not data:
            return
        for w in self.details_content_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.details_content_frame,
            text=f"Cheat file: {clean_name}",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=Colors.TEXT, anchor="w",
        ).pack(pady=(5, 2), padx=5, fill="x")
        text = ctk.CTkTextbox(self.details_content_frame,
                              text_color=Colors.TEXT,
                              fg_color=Colors.WIDGET_BG,
                              wrap="word",
                              font=ctk.CTkFont(family="Consolas", size=12))
        text.pack(expand=True, fill="both", padx=5, pady=5)
        content = ""
        try:
            with open(data["path"], "r", encoding="utf-8",
                      errors="ignore") as f:
                content = f.read()
            if not content:
                content = "(empty cheat file)"
        except Exception as e:
            content = f"Error reading file:\n{e}"
        text.insert("1.0", content)
        text.configure(state="disabled")

    # ----------------------------------------------------------- details

    def show_details(self, mod_name):
        if self.current_state == "working":
            return
        if self.mode == "recomp":
            self._show_recomp_mod_details(mod_name)
            return
        self.current_details_mod = mod_name
        for w in self.details_content_frame.winfo_children():
            w.destroy()
        if mod_name == self.ryujinx.special_cheats_folder_name:
            self.display_enabled_cheats_preview()
        elif mod_name in self.ryujinx.cheat_only_mods:
            self.display_cheat_manager(mod_name)
        else:
            self.display_conflict_details(mod_name)

    def display_enabled_cheats_preview(self):
        ctk.CTkLabel(
            self.details_content_frame,
            text="Preview: enabled.txt",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=Colors.TEXT,
        ).pack(pady=5, anchor="w", padx=5)
        textbox = ctk.CTkTextbox(self.details_content_frame,
                                 text_color=Colors.TEXT,
                                 fg_color=Colors.WIDGET_BG, wrap="word",
                                 font=ctk.CTkFont(family="Consolas", size=12))
        textbox.pack(expand=True, fill="both", padx=5, pady=5)
        folder = (self.ryujinx.special_cheats_folder_name or "cheats")
        path = os.path.join(self.ryujinx.mods_path, folder, "enabled.txt")
        content = ""
        if not os.path.exists(path):
            content = f"File not found:\n{path}\n\nWill be created on Apply."
        else:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                if not content:
                    content = "(enabled.txt is empty)"
            except Exception as e:
                content = f"Error: {e}"
        textbox.insert("1.0", content)
        textbox.configure(state="disabled")

    def display_conflict_details(self, mod_name):
        for w in self.details_content_frame.winfo_children():
            w.destroy()
        clean = self.ryujinx.strip_prefix(mod_name)
        ctk.CTkLabel(self.details_content_frame, text=f"Mod: {clean}",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=Colors.TEXT).pack(anchor="w", padx=5, pady=(5, 0))

        self._mod_info_row(self.details_content_frame, mod_name)

        scroll = ctk.CTkScrollableFrame(self.details_content_frame,
                                        label_text="Conflicts",
                                        fg_color="transparent")
        scroll.pack(expand=True, fill="both", padx=2, pady=(0, 5))

        if mod_name not in self.ryujinx.conflicts:
            ctk.CTkLabel(scroll, text="No conflicts detected with other mods.",
                         text_color=Colors.NO_CONFLICT).pack(anchor="w", padx=8,
                                                              pady=8)
            return

        current = [w.original_name for w in self._orderable_widgets()]

        def _idx(nm):
            try:
                return current.index(nm)
            except ValueError:
                return None

        for file, others in self.ryujinx.conflicts[mod_name].items():
            header = ctk.CTkFrame(scroll, fg_color="transparent")
            header.pack(fill="x", padx=6, pady=(8, 0))
            ctk.CTkLabel(header, text=file, text_color=Colors.TEXT,
                         anchor="w", font=ctk.CTkFont(weight="bold")
                         ).pack(fill="x")
            for other in others:
                if not self._is_mod_enabled(other):
                    continue
                row = ctk.CTkFrame(scroll, fg_color=Colors.WIDGET_BG,
                                   corner_radius=4)
                row.pack(fill="x", padx=12, pady=2)
                row.grid_columnconfigure(0, weight=1)
                mi, oi = _idx(mod_name), _idx(other)
                other_clean = self.ryujinx.strip_prefix(other)
                if mi is None or oi is None:
                    who = "unknown order"
                    i_win = False
                else:
                    i_win = mi < oi  # higher in list wins
                    who = (f"You win (above {other_clean})" if i_win
                           else f"'{other_clean}' wins (above you)")
                ctk.CTkLabel(row, text=f"overlaps: {other_clean}\n{who}",
                             text_color=(Colors.RESOLVED_CONFLICT if i_win
                                         else Colors.CONFLICT),
                             anchor="w", justify="left"
                             ).grid(row=0, column=0, sticky="ew", padx=8, pady=6)
                ctk.CTkButton(
                    row, text="Make mine win", width=120,
                    fg_color=Colors.BUTTON_BG, hover_color=Colors.BUTTON_HOVER,
                    command=lambda mv=mod_name, tg=other:
                        self._resolve_conflict_by_move(mv, tg, clean, other_clean)
                ).grid(row=0, column=1, padx=6, pady=6)

        ctk.CTkLabel(scroll,
                     text="Note: the mod HIGHER in the list wins each shared "
                          "file. 'Make mine win' reorders this mod above the "
                          "other one — remember to Apply.",
                     text_color=Colors.DISABLED, wraplength=380,
                     justify="left").pack(anchor="w", padx=8, pady=(8, 4))

    def _resolve_conflict_by_move(self, moving_raw, target_raw,
                                  moving_clean, target_clean):
        self._move_mod_above(moving_raw, target_raw)
        # Refresh the details pane to show the new winner.
        self.show_details(self.current_details_mod or moving_raw)



    def _update_pending_cheats(self, mod_name, cheat_name, var):
        self.pending_cheat_selections.setdefault(mod_name, {})[cheat_name] = var.get()
        self.status_label.configure(
            text="Unsaved cheat selections. Click 'Apply New Order' to save.")

    def display_cheat_manager(self, mod_name):
        clean = self.ryujinx.strip_prefix(mod_name)
        for w in self.details_content_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.details_content_frame,
                     text=f"Cheat Manager: {clean}",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=Colors.TEXT).pack(pady=5, anchor="w", padx=5)
        cheat_path = os.path.join(self.ryujinx.mods_path, mod_name, "cheats")
        if not os.path.isdir(cheat_path):
            ctk.CTkLabel(self.details_content_frame,
                         text="No 'cheats' subfolder found.",
                         text_color=Colors.TEXT).pack(pady=10)
            return
        current = self.pending_cheat_selections.get(mod_name, {})
        scroll = ctk.CTkScrollableFrame(self.details_content_frame,
                                        label_text="Available Cheats",
                                        fg_color="transparent")
        scroll.pack(expand=True, fill="both", padx=5, pady=5)
        if not current:
            ctk.CTkLabel(scroll, text="No valid cheats found.",
                         text_color=Colors.TEXT).pack()
            return
        for cheat_name in sorted(current.keys()):
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", expand=True, pady=2)
            row.grid_columnconfigure(1, weight=1)
            var = ctk.BooleanVar(value=current.get(cheat_name, False))
            var.trace_add(
                "write",
                lambda n, i, mo, v=var, m=mod_name, c=cheat_name:
                self._update_pending_cheats(m, c, v),
            )
            cb = ctk.CTkCheckBox(row, text="", variable=var)
            cb.grid(row=0, column=0, padx=(5, 0))
            lbl = ctk.CTkLabel(row, text=cheat_name, text_color=Colors.TEXT,
                               anchor="w", cursor="hand2")
            lbl.grid(row=0, column=1, sticky="ew", padx=(5, 10))
            lbl.bind("<Button-1>", lambda e, c=cb: c.toggle())
            ctk.CTkButton(
                row, text="View Code", width=80,
                fg_color=Colors.BUTTON_BG, hover_color=Colors.BUTTON_HOVER,
                command=lambda m=mod_name, c=cheat_name:
                self.show_cheat_code_popup(m, c),
            ).grid(row=0, column=2, padx=5)
            ctk.CTkButton(
                row, text="Edit", width=60,
                fg_color=Colors.BUTTON_BG, hover_color=Colors.BUTTON_HOVER,
                command=lambda m=mod_name, c=cheat_name:
                self.edit_cheat_code_popup(m, c),
            ).grid(row=0, column=3, padx=5)

    def show_cheat_code_popup(self, mod_name, cheat_name):
        code = "Could not find cheat code."
        base = os.path.join(self.ryujinx.mods_path, mod_name)
        try:
            for item in os.listdir(base):
                if item.lower() == "cheats" and \
                        os.path.isdir(os.path.join(base, item)):
                    cdir = os.path.join(base, item)
                    for fn in os.listdir(cdir):
                        if not fn.endswith(".txt") or fn.lower() == "enabled.txt":
                            continue
                        with open(os.path.join(cdir, fn), "r",
                                  encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        m = re.search(
                            r"\[" + re.escape(cheat_name) + r"\]\s*([\s\S]*?)(?=\n\s*\[|$)",
                            content)
                        if m:
                            code = m.group(1).strip()
                            raise StopIteration
        except StopIteration:
            pass
        except Exception as e:
            print(f"Error: {e}")
        popup = ctk.CTkToplevel(self)
        popup.title(f"Code: {cheat_name}")
        popup.geometry("600x400")
        popup.transient(self.master)
        popup.grab_set()
        popup.grid_rowconfigure(0, weight=1)
        popup.grid_columnconfigure(0, weight=1)
        tb = ctk.CTkTextbox(popup, text_color=Colors.TEXT,
                            fg_color=Colors.WIDGET_BG, wrap="word",
                            font=ctk.CTkFont(family="Consolas", size=12))
        tb.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        tb.insert("1.0", code)
        tb.configure(state="disabled")

    def edit_cheat_code_popup(self, mod_name, cheat_name):
        file_path, error = self._find_cheat_file_path(mod_name, cheat_name)
        if error:
            messagebox.showerror("Error", error)
            return
        code = ""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            m = re.search(
                r"\[\s*" + re.escape(cheat_name) + r"\s*\]\s*([\s\S]*?)(?=\n\s*\[|$)",
                content)
            if m:
                code = m.group(1).strip()
            else:
                messagebox.showerror("Error", f"Cheat '{cheat_name}' not found.")
                return
        except Exception as e:
            messagebox.showerror("Read Error", str(e))
            return
        popup = ctk.CTkToplevel(self)
        popup.title(f"Edit: {cheat_name}")
        popup.geometry("700x500")
        popup.transient(self.master)
        popup.grab_set()
        popup.grid_rowconfigure(0, weight=1)
        popup.grid_columnconfigure(0, weight=1)
        tb = ctk.CTkTextbox(popup, text_color=Colors.TEXT,
                            fg_color=Colors.WIDGET_BG, wrap="word",
                            font=ctk.CTkFont(family="Consolas", size=12))
        tb.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))
        tb.insert("1.0", code)

        def save():
            new_code = tb.get("1.0", "end-1c")
            try:
                with open(file_path, "r", encoding="utf-8",
                          errors="ignore") as f:
                    full = f.read()
                pattern = re.compile(
                    r"(\[" + re.escape(cheat_name) + r"\]\s*)([\s\S]*?)((?=\n\s*\[)|$)",
                    re.IGNORECASE)
                if not pattern.search(full):
                    raise ValueError("Cheat block not found.")
                new_full = pattern.sub(r"\1" + new_code.strip() + r"\3",
                                       full, count=1)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(new_full)
                messagebox.showinfo("Saved", f"'{cheat_name}' updated.",
                                    parent=popup)
                popup.destroy()
            except Exception as e:
                messagebox.showerror("Save Error", str(e), parent=popup)

        btn_row = ctk.CTkFrame(popup, fg_color="transparent")
        btn_row.grid(row=1, column=0, pady=10)
        ctk.CTkButton(btn_row, text="Save", command=save,
                      fg_color=Colors.BUTTON_BG,
                      hover_color=Colors.BUTTON_HOVER).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text="Cancel", command=popup.destroy,
                      fg_color=Colors.BUTTON_BG,
                      hover_color=Colors.BUTTON_HOVER).pack(side="left", padx=5)

    def _find_cheat_file_path(self, mod_name, cheat_name):
        base = os.path.join(self.ryujinx.mods_path, mod_name)
        try:
            for item in os.listdir(base):
                if item.lower() == "cheats" and \
                        os.path.isdir(os.path.join(base, item)):
                    cdir = os.path.join(base, item)
                    for fn in os.listdir(cdir):
                        if not fn.endswith(".txt") or fn.lower() == "enabled.txt":
                            continue
                        fp = os.path.join(cdir, fn)
                        with open(fp, "r", encoding="utf-8",
                                  errors="ignore") as f:
                            if re.search(r"\[" + re.escape(cheat_name) + r"\]",
                                         f.read(), re.IGNORECASE):
                                return fp, None
        except Exception as e:
            return None, str(e)
        return None, "Cheat file not found."

    # ------------------------------------------------------------ context

    def show_context_menu(self, event, mod_name):
        menu = tk.Menu(self, tearoff=0,
                       bg=Colors.WIDGET_BG, fg=Colors.TEXT,
                       activebackground=Colors.BUTTON_HOVER,
                       activeforeground=Colors.TEXT,
                       relief="flat", borderwidth=1)
        multi = (len(self.selected_mods) > 1
                 and mod_name in self.selected_mods)
        if multi:
            n = len(self.selected_mods)
            menu.add_command(label=f"Enable Selected ({n})",
                             command=lambda: self._bulk_enable(True))
            menu.add_command(label=f"Disable Selected ({n})",
                             command=lambda: self._bulk_enable(False))
            menu.add_separator()
        menu.add_command(label="Open mod folder",
                         command=lambda: self._open_mod_folder(mod_name))
        if self.mode == "ryujinx":
            menu.add_command(label="Move to top (highest priority)",
                             command=lambda: self._move_mod_to_edge(mod_name, "top"))
            menu.add_command(label="Move to bottom (lowest priority)",
                             command=lambda: self._move_mod_to_edge(mod_name, "bottom"))
            menu.add_separator()
        if multi:
            menu.add_command(label=f"Delete Selected ({n})",
                             command=self._bulk_delete)
        else:
            menu.add_command(label="Delete",
                             command=lambda: self.delete_mod(mod_name))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _open_mod_folder(self, mod_name):
        if self.mode == "recomp":
            path = self.recomp.get_current_mod_path(mod_name)
        else:
            path = os.path.join(self.ryujinx.mods_path, mod_name)
        if path and os.path.isdir(path):
            open_in_file_explorer(path)
        else:
            self.status_label.configure(text="Mod folder not found.")

    def delete_mod(self, mod_name):
        clean = self.ryujinx.strip_prefix(mod_name)
        if not messagebox.askyesno(
                "Confirm Deletion",
                f"Permanently delete '{clean}'?\n\nCannot be undone."):
            return
        path = os.path.join(self.ryujinx.mods_path, mod_name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            elif os.path.exists(path):
                os.remove(path)
            if self.current_details_mod == mod_name:
                self.current_details_mod = None
                for w in self.details_content_frame.winfo_children():
                    w.destroy()
            self.status_label.configure(text=f"Deleted '{clean}'. Refreshing...")
            self.run_scan()
        except PermissionError:
            messagebox.showerror(
                "Deletion Failed",
                "Permission denied. Close Ryujinx and retry, or run as admin.")
        except Exception as e:
            messagebox.showerror("Deletion Failed", str(e))

    # --------------------------------------------- selection + inner ring

    # Ring thickness in px. Thinner than every child widget's inset, so no
    # child canvas can ever reach over it and punch rectangular bites out of
    # it (the cause of the old "broken ring" artifact at high DPI).
    RING_WIDTH = 1

    def _attach_select_ring(self, face, row, corner_radius):
        # Selection indicator: swap the row's own border to a thin gold ring
        # and tint the row face. An overlay frame can't work on Windows —
        # raised above children it paints over the checkbox/text; below
        # children the label clips the top/bottom edges. The row's own border
        # is drawn beneath every child and, at RING_WIDTH, stays out of every
        # child's reach — a complete, reliable, uninterrupted indicator.
        row._ring_face = face   # frame whose face gets tinted (row itself for recomp)
        row._ring_on = False

    @staticmethod
    def _safe_child_bg(child, color):
        # Re-paint the canvas backdrop of fake-transparent children (labels,
        # checkbox) so they blend into the tinted face instead of showing
        # stale rectangles over it.
        try:
            child.configure(bg_color=color)
        except (ValueError, tk.TclError):
            pass

    def _set_row_ring(self, row, on):
        if row is None:
            return
        face = getattr(row, "_ring_face", row)
        frames = [row] if face is row else [row, face]
        if on:
            if getattr(row, "_ring_on", False):
                return  # already ringed (e.g. a selected row grabbed for drag)
            # Capture the exact pre-selection look so deselect can restore it
            # even if conflict recoloring ran in between.
            row._pre_ring = [(f.cget("border_color"), f.cget("border_width"),
                              f.cget("fg_color")) for f in frames]
            for f in frames:
                f.configure(fg_color=Colors.SELECTED_FACE)
            row.configure(border_color=Colors.DRAG_HIGHLIGHT,
                          border_width=self.RING_WIDTH)
            for child in face.winfo_children():
                self._safe_child_bg(child, Colors.SELECTED_FACE)
            row._ring_on = True
        else:
            if not getattr(row, "_ring_on", False):
                return
            pre = getattr(row, "_pre_ring", None)
            if pre is None:
                pre = [(row.cget("border_color"), row.cget("border_width"),
                        Colors.WIDGET_BG)]
            for f, (bc, bw, fg) in zip(frames, pre):
                f.configure(fg_color=fg)
                if f is row:
                    f.configure(border_width=bw)
                    if bc is not None:
                        f.configure(border_color=bc)
            # Restore children AFTER the face, so auto-detected backgrounds
            # (bg_color was None) re-detect the restored face color.
            face_color = face.cget("fg_color")
            for child in face.winfo_children():
                self._safe_child_bg(child, face_color)
            row._ring_on = False

    def _update_selection_bar(self):
        n = len(self.selected_mods)
        if n > 0:
            noun = "mod" if n == 1 else "mods"
            self.selection_label.configure(
                text=(f"Selected: {n} {noun}   |   Ctrl+Click adds/removes"
                      f"   |   Right-click a selected row to enable, disable"
                      f" or delete all {n}"))
            self.selection_bar.grid()
        else:
            self.selection_bar.grid_remove()

    def _clear_selection(self):
        for name in list(self.selected_mods):
            self._set_row_ring(self.mod_item_widgets.get(name), False)
        self.selected_mods.clear()
        self._update_selection_bar()

    def _toggle_mod_selection(self, mod_name):
        widget = self.mod_item_widgets.get(mod_name)
        if widget is None:
            return
        if mod_name in self.selected_mods:
            self.selected_mods.discard(mod_name)
            self._set_row_ring(widget, False)
        else:
            self.selected_mods.add(mod_name)
            self._set_row_ring(widget, True)
        self._update_selection_bar()

    def _bulk_enable(self, want):
        for name in list(self.selected_mods):
            w = self.mod_item_widgets.get(name)
            if w and hasattr(w, "checkbox") and bool(w.checkbox.get()) != want:
                w.checkbox.toggle()
        if self.mode == "recomp":
            self._on_recomp_mod_toggle()
        else:
            self.on_checkbox_toggle()

    def _bulk_delete(self):
        names = sorted(self.selected_mods)
        if not names:
            return
        if not messagebox.askyesno(
                "Confirm Deletion",
                f"Permanently delete {len(names)} selected mod(s)?\n\n"
                + "\n".join(f"  \u2022 {n}" for n in names)
                + "\n\nThis cannot be undone."):
            return
        for name in names:
            if self.mode == "recomp":
                self._recomp_delete_mod(name)
            else:
                self.delete_mod(name)
        self.selected_mods.clear()
        self._update_selection_bar()
        self.run_scan()

    def setup_drag_drop(self, row, drag_handle):
        def on_start(event):
            if self.current_state == "working":
                return
            self.drag_data["item"] = row
            self._set_row_ring(row, True)

        def on_motion(event):
            if self.drag_data["item"] is None:
                return
            container = self._drag_container()
            if container is None:
                return
            for widget in container.pack_slaves():
                if widget == self.drag_data["item"] or not hasattr(widget,
                                                                   "original_name"):
                    continue
                wy = widget.winfo_rooty()
                wh = widget.winfo_height()
                if wy <= event.y_root <= wy + wh:
                    rel = event.y_root - wy
                    if rel < wh / 2:
                        self.drag_data["item"].pack_configure(before=widget)
                    else:
                        self.drag_data["item"].pack_configure(after=widget)
                    # Recolor conflict states live while dragging.
                    if self.mode == "ryujinx":
                        self.update_all_border_colors()
                    else:
                        self._recomp_recolor_all()
                    break

        def on_end(event):
            item = self.drag_data["item"]
            if item:
                # Ring returns to the row's selection state.
                name = getattr(item, "original_name", None)
                self._set_row_ring(item, name in self.selected_mods)
                if self.mode == "ryujinx":
                    self.update_all_border_colors()
                    if self.view_switcher.get() == "Tree View":
                        self.populate_mod_tree()
                else:
                    self._on_recomp_mod_toggle()
                self.drag_data["item"] = None

        for w in [drag_handle, row, row.winfo_children()[0]]:
            w.bind("<Button-1>", on_start)
            w.bind("<B1-Motion>", on_motion)
            w.bind("<ButtonRelease-1>", on_end)

    def _drag_container(self):
        if self.mode == "recomp":
            if self.recomp_mods_section:
                return self.recomp_mods_section.content
            return None
        return self.mod_list_frame

    # --------------------------------------------------------- drag-drop install

    def on_drop(self, event):
        if self.current_state == "working":
            return
        path = self._get_current_path()
        if not path or not os.path.isdir(path):
            messagebox.showerror("Error",
                                 "Please select a valid folder first.")
            return
        if self.mode == "recomp":
            target_dir = self.recomp.mods_path
            os.makedirs(target_dir, exist_ok=True)
        else:
            target_dir = path
        dropped = self.master.tk.splitlist(event.data)
        for item_path in dropped:
            base_name = os.path.basename(item_path)
            is_archive = item_path.lower().endswith((".zip", ".7z"))
            dest_name = os.path.splitext(base_name)[0] if is_archive else base_name
            if self.mode == "recomp":
                dest_name = re.sub(r"^\d+_", "", dest_name)
            destination = os.path.join(target_dir, dest_name)
            if os.path.exists(destination):
                if not messagebox.askyesno(
                        "Overwrite Confirmation",
                        f"A mod named '{dest_name}' already exists. Overwrite?"):
                    continue
                try:
                    if os.path.isdir(destination):
                        shutil.rmtree(destination)
                    else:
                        os.remove(destination)
                except Exception as e:
                    messagebox.showerror("Error",
                                         f"Failed to remove '{dest_name}': {e}")
                    continue
            try:
                self.status_label.configure(text=f"Installing {base_name}...")
                self.update_idletasks()
                if item_path.lower().endswith(".zip"):
                    with zipfile.ZipFile(item_path, "r") as z:
                        z.extractall(destination)
                elif item_path.lower().endswith(".7z"):
                    if not PY7ZR_SUPPORT:
                        messagebox.showerror(
                            "Missing Library",
                            "Install 'py7zr' to extract .7z files.")
                        continue
                    with py7zr.SevenZipFile(item_path, mode="r") as z:
                        z.extractall(path=destination)
                elif os.path.isdir(item_path):
                    shutil.copytree(item_path, destination)
            except Exception as e:
                messagebox.showerror("Installation Failed",
                                     f"Could not install '{base_name}':\n{e}")
        self.status_label.configure(text="Installation complete. Refreshing...")
        self.run_scan()

    # ----------------------------------------------------------- launching

    def launch_game(self):
        if self.mode == "recomp":
            self._launch_recomp()
            return
        self._launch_ryujinx()

    def _launch_recomp(self):
        exe = self.recomp_exe_path or self.recomp.locate_recomp_exe()
        if not exe or not os.path.exists(exe):
            messagebox.showinfo(
                "MHGU Recomp Executable",
                "Please select the mhgurecomp executable (mhgurecomp.exe).")
            filetypes = [("Executable", "*.exe"),
                         ("All files", "*.*")]
            if sys.platform == "darwin":
                filetypes = [("Application", "*.app"), ("All files", "*.*")]
            chosen = filedialog.askopenfilename(
                title="Select mhgurecomp", filetypes=filetypes)
            if not chosen:
                self.status_label.configure(text="Launch cancelled.")
                return
            self.recomp_exe_path = chosen
            self.save_config()
        try:
            self.status_label.configure(text="Launching MHGU Recomp...")
            cmd = [self.recomp_exe_path]
            if sys.platform == "darwin" and self.recomp_exe_path.endswith(".app"):
                # FIX: point at the actual binary inside the .app bundle
                cmd = [os.path.join(self.recomp_exe_path, "Contents",
                                    "MacOS", "mhgurecomp")]
            subprocess.Popen(cmd, cwd=os.path.dirname(self.recomp_exe_path))
            self.status_label.configure(text="Launch command sent.")
            messagebox.showinfo(
                "MHGU Recomp Launched",
                "Launch command sent.\n\n"
                "dreamSort will wait. Press OK when you have closed the game.")
        except Exception as e:
            messagebox.showerror("Launch Error", str(e))

    def _launch_ryujinx(self):
        if not self.ryujinx_exe_path or not os.path.exists(self.ryujinx_exe_path):
            messagebox.showinfo(
                "Ryujinx Location Needed",
                "Please select your Ryujinx executable.")
            filetypes = [("Executable files", "*.exe"), ("All files", "*.*")]
            if sys.platform == "darwin":
                filetypes = [("Application", "*.app"), ("All files", "*.*")]
            elif sys.platform != "win32":
                filetypes = [("All files", "*.*")]
            chosen = filedialog.askopenfilename(
                title="Select Ryujinx Executable", filetypes=filetypes)
            if not chosen:
                self.status_label.configure(text="Launch cancelled.")
                return
            self.ryujinx_exe_path = chosen
            self.save_config()
        if not self.game_file_path or not os.path.exists(self.game_file_path):
            messagebox.showinfo(
                "Game File Needed",
                "Please select your MHGU game file (.nsp/.xci/.nca).")
            chosen = filedialog.askopenfilename(
                title="Select MHGU game file",
                filetypes=(("Switch Game Files", "*.nsp *.xci *.nca"),
                           ("All files", "*.*")))
            if not chosen:
                self.status_label.configure(text="Launch cancelled.")
                return
            self.game_file_path = chosen
            self.save_config()
        try:
            self.status_label.configure(text="Launching MHGU...")
            cmd = [self.ryujinx_exe_path, self.game_file_path]
            if sys.platform == "darwin" and self.ryujinx_exe_path.endswith(".app"):
                cmd[0] = os.path.join(self.ryujinx_exe_path, "Contents",
                                      "MacOS", "Ryujinx")
            subprocess.Popen(cmd)
            self.status_label.configure(text="Launch command sent to Ryujinx.")
            messagebox.showinfo(
                "Ryujinx Launched",
                "Launch command sent.\n\nPress OK when you have closed the game.")
        except Exception as e:
            messagebox.showerror("Launch Error", str(e))

    # --------------------------------------------------------- open/preview

    def open_mod_directory(self):
        if self.mode == "recomp":
            if not open_in_file_explorer(self.recomp.root_path):
                messagebox.showwarning("Warning", "Invalid recomp root.")
            return
        path = self._get_current_path()
        if not open_in_file_explorer(path):
            messagebox.showwarning("Warning", "Invalid directory.")

    def preview_enabled_cheats_popup(self):
        if self.mode == "recomp":
            # Only relevant to Ryujinx; hide silently.
            return
        path = self._get_current_path()
        if not path or not os.path.isdir(path):
            messagebox.showwarning("Warning", "Invalid mod directory.")
            return
        folder = self.ryujinx.special_cheats_folder_name or "cheats"
        enabled_path = os.path.join(path, folder, "enabled.txt")
        content = ""
        if not os.path.exists(enabled_path):
            content = (f"Not found:\n{enabled_path}\n\n"
                       "Will be created on Apply.")
        else:
            try:
                with open(enabled_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if not content:
                    content = "(empty)"
            except Exception as e:
                messagebox.showerror("Error", str(e))
                return
        popup = ctk.CTkToplevel(self)
        popup.title("Preview: enabled.txt")
        popup.geometry("600x400")
        popup.transient(self.master)
        popup.grab_set()
        popup.grid_rowconfigure(0, weight=1)
        popup.grid_columnconfigure(0, weight=1)
        tb = ctk.CTkTextbox(popup, text_color=Colors.TEXT,
                            fg_color=Colors.WIDGET_BG, wrap="word",
                            font=ctk.CTkFont(family="Consolas", size=12))
        tb.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        tb.insert("1.0", content)
        tb.configure(state="disabled")

    # ------------------------------------------------------------- disable-all

    def clear_all_mods(self):
        if self.current_state == "working":
            return
        if self.mode == "recomp":
            if not self.recomp.root_path:
                messagebox.showwarning("No Folder", "Select a recomp root first.")
                return
            if not messagebox.askyesno(
                    "Confirm Disable All",
                    "Disable all mods?\n\n"
                    "This moves every mod in mods/ to mods_disabled/. "
                    "Click 'Apply New Order' to save."):
                return
            for widget in self.mod_item_widgets.values():
                if hasattr(widget, "checkbox"):
                    widget.checkbox.deselect()
            self._on_recomp_mod_toggle()
            self.status_label.configure(
                text="All mods unchecked. Click 'Apply New Order' to save.")
            return
        # Ryujinx
        if not self.ryujinx.mods_path:
            messagebox.showwarning("No Folder", "Select a mod folder first.")
            return
        if not messagebox.askyesno(
                "Confirm Disable All",
                "Disable all mods?\n\nUnchecks all mods. "
                "You must click 'Apply New Order' to save."):
            return
        for widget in self.mod_item_widgets.values():
            if hasattr(widget, "checkbox"):
                widget.checkbox.deselect()
        self.update_all_border_colors()
        if self.view_switcher.get() == "Tree View":
            self.populate_mod_tree()
        self.status_label.configure(
            text="All mods disabled. Click 'Apply New Order' to save.")

    def clear_all_cheats(self):
        if self.current_state == "working":
            return
        if self.mode == "recomp":
            if not self.recomp.root_path:
                messagebox.showwarning("No Folder", "Select a recomp root first.")
                return
            if not messagebox.askyesno(
                    "Confirm Disable All",
                    "Disable all cheats?\n\n"
                    "All cheat .txt files will be prefixed with '_'. "
                    "Click 'Apply New Order' to save."):
                return
            for widget in self.cheat_widgets.values():
                if hasattr(widget, "checkbox"):
                    widget.checkbox.deselect()
                    widget.configure(fg_color=Colors.DISABLED)
            self.status_label.configure(
                text="All cheats unchecked. Click 'Apply New Order' to save.")
            return
        # Ryujinx
        if not self.ryujinx.mods_path:
            messagebox.showwarning("No Folder", "Select a mod folder first.")
            return
        if not messagebox.askyesno(
                "Confirm Disable All",
                "Disable all cheats?\n\nClears pending selections. "
                "You must click 'Apply New Order' to save."):
            return
        self.pending_cheat_selections.clear()
        self._initialize_pending_cheats()
        if self.current_details_mod and \
                self.current_details_mod in self.ryujinx.cheat_only_mods:
            self.show_details(self.current_details_mod)
        self.status_label.configure(
            text="All cheats cleared. Click 'Apply New Order' to save.")

    # ------------------------------------------------------------ apply

    def apply_changes(self):
        if self.current_state == "working":
            return
        if self.mode == "recomp":
            self._apply_changes_recomp()
        else:
            self._apply_changes_ryujinx()

    def _apply_changes_recomp(self):
        if not self.recomp.root_path:
            messagebox.showerror("Error", "No recomp root selected.")
            return
        if is_process_running("mhgurecomp"):
            messagebox.showerror(
                "Process Running",
                "MHGU Recomp is running.\n\n"
                "Please close the game before applying changes.")
            return

        # Gather current states from UI
        ordered_mods = []
        mod_enabled = {}
        for widget in self._reorderable_widgets():
            name = widget.original_name
            ordered_mods.append(name)
            mod_enabled[name] = (widget.checkbox.get()
                                 if hasattr(widget, "checkbox") else True)

        cheat_states = {}
        for clean_name, widget in self.cheat_widgets.items():
            if hasattr(widget, "checkbox"):
                cheat_states[clean_name] = widget.checkbox.get()

        patch_states = {}
        for key, widget in self.patch_widgets.items():
            if hasattr(widget, "checkbox"):
                patch_states[key] = widget.checkbox.get()

        plugin_states = {}
        for key, widget in self.plugin_widgets.items():
            if hasattr(widget, "checkbox"):
                plugin_states[key] = widget.checkbox.get()

        # Summary prompt
        enabled_mods = sum(1 for v in mod_enabled.values() if v)
        disabled_mods = len(mod_enabled) - enabled_mods
        enabled_cheats = sum(1 for v in cheat_states.values() if v)
        enabled_patches = sum(1 for v in patch_states.values() if v)
        enabled_plugins = sum(1 for v in plugin_states.values() if v)
        if not messagebox.askyesno(
                "Confirm Apply",
                f"Apply changes to MHGU Recomp?\n\n"
                f"Enabled mods: {enabled_mods} (disabled: {disabled_mods})\n"
                f"Enabled cheats: {enabled_cheats}\n"
                f"Enabled patches: {enabled_patches}\n"
                f"Enabled plugins: {enabled_plugins}\n\n"
                f"Mods will be renamed with numbered prefixes and moved "
                f"between mods/ and mods_disabled/. Cheats and "
                f"patches/plugins will be renamed with the '_' prefix.",
        ):
            return

        self.start_recomp_apply_worker(
            ordered_mods, mod_enabled, cheat_states, patch_states, plugin_states)

    def start_recomp_apply_worker(self, ordered_mods, mod_enabled, cheat_states,
                                   patch_states, plugin_states):
        self.set_ui_state("working")
        self.progress_bar.set(0)
        self.progress_detail_label.configure(text="Initializing...")
        self.apply_thread = threading.Thread(
            target=self.recomp.apply_changes_threaded,
            args=(ordered_mods, mod_enabled, cheat_states,
                  patch_states, plugin_states, self.progress_queue),
            daemon=True,
        )
        self.apply_thread.start()
        self.after(100, self.check_apply_progress)

    def _apply_changes_ryujinx(self):
        if not self.ryujinx.mods_path:
            messagebox.showerror("Error", "No mod folder selected.")
            return
        if is_process_running("Ryujinx"):
            messagebox.showerror(
                "Process Running",
                "Ryujinx is running.\n\nPlease close Ryujinx first.")
            return
        config = self.get_ordered_mods_config()
        # Conflict pre-flight prompt
        current_names = [w.original_name for w in self._reorderable_widgets()]
        conflict_details = []
        for widget in self._reorderable_widgets():
            mod_name = widget.original_name
            if hasattr(widget, "checkbox") and not widget.checkbox.get():
                continue
            if mod_name in self.ryujinx.conflicts:
                my_idx = current_names.index(mod_name)
                for file, others in self.ryujinx.conflicts[mod_name].items():
                    for other in others:
                        if self._is_mod_enabled(other):
                            try:
                                oi = current_names.index(other)
                                if oi > my_idx:
                                    conflict_details.append(
                                        f"• '{self.ryujinx.strip_prefix(mod_name)}' "
                                        f"overrides '{self.ryujinx.strip_prefix(other)}' "
                                        f"for {file}"
                                    )
                            except ValueError:
                                continue
        if conflict_details:
            unique = list(set(conflict_details))[:10]
            text = ("The following overrides will occur:\n\n"
                    + "\n\n".join(unique))
            if len(conflict_details) > 10:
                text += f"\n\n... and {len(conflict_details) - 10} more."
            text += "\n\nProceed?"
            if not messagebox.askyesno("Confirm Load Order", text):
                self.status_label.configure(text="Apply cancelled.")
                return
        self.start_apply_worker(config)

    def get_ordered_mods_config(self):
        ordered = self._reorderable_widgets()
        config = {}
        for w in ordered:
            name = w.original_name
            config[name] = (w.checkbox.get() if hasattr(w, "checkbox") else True)
        return config

    # ---------------------------------------------------------- reorder helpers
    # In this app the mod HIGHER in the list wins conflicts (see
    # update_all_border_colors / the apply pre-flight), so "make X win" means
    # packing X above its competitors.

    def _clean_of_widget(self, w):
        if self.mode == "recomp":
            return getattr(w, "original_name", None)
        return self.ryujinx.strip_prefix(getattr(w, "original_name", ""))

    def _orderable_widgets(self):
        # The widgets the user can actually reorder: real mod rows with an
        # enable checkbox (excludes the special-cheats folder and cheat-only
        # entries, which also carry original_name but are not reorderable).
        return [w for w in self._reorderable_widgets()
                if hasattr(w, "checkbox")]

    def _widget_by_clean(self):
        return {self._clean_of_widget(w): w
                for w in self._orderable_widgets()}

    def _orderable_container_anchor(self):
        # First slave in the mod container that is NOT an orderable widget —
        # i.e. the top of the non-mod block (cheats section). Orderable widgets
        # are kept packed above this anchor.
        container = self._drag_container()
        if container is None:
            return None
        ids = {id(w) for w in self._orderable_widgets()}
        for s in container.pack_slaves():
            if id(s) not in ids:
                return s
        return None

    def _after_order_change(self):
        if self.mode == "ryujinx":
            self.update_all_border_colors()
            if self.view_switcher.get() == "Tree View":
                self.populate_mod_tree()
        else:
            self._on_recomp_mod_toggle()

    def _move_mod_above(self, moving_raw, target_raw):
        # Reorder the widget for moving_raw to sit directly above target_raw.
        by_raw = {w.original_name: w for w in self._orderable_widgets()}
        mv, tg = by_raw.get(moving_raw), by_raw.get(target_raw)
        if mv is not None and tg is not None and mv is not tg:
            try:
                mv.pack_configure(before=tg)
            except Exception as e:
                print(f"reorder failed: {e}")
                return
            self._after_order_change()
            self.status_label.configure(
                text=f"Order changed. Click 'Apply New Order' to save.")

    def _move_mod_to_edge(self, moving_raw, side):
        by_raw = {w.original_name: w for w in self._orderable_widgets()}
        w = by_raw.get(moving_raw)
        if w is None:
            return
        if side == "top":
            anchor = self._orderable_container_anchor()
            if anchor is not None:
                w.pack_configure(before=anchor)
            else:
                w.pack_configure()
        else:
            w.pack_configure()  # no-arg pack moves it to the end of its side
        self._after_order_change()
        self.status_label.configure(
            text=f"Order changed. Click 'Apply New Order' to save.")

    # ---------------------------------------------------------------- profiles

    def _refresh_profile_menu(self):
        names = sorted(self.profiles.keys())
        self.profile_menu.configure(values=["(none)"] + names)
        if self.profile_var.get() not in ["(none)"] + names:
            self.profile_var.set("(none)")

    def _collect_profile(self):
        order, enabled = [], {}
        for w in self._orderable_widgets():
            clean = self._clean_of_widget(w)
            if not clean:
                continue
            order.append(clean)
            enabled[clean] = (w.checkbox.get()
                              if hasattr(w, "checkbox") else True)
        return {"mode": self.mode, "order": order, "enabled": enabled}

    def _ui_save_profile(self):
        from tkinter.simpledialog import askstring
        name = askstring("Save Profile", "Profile name:", parent=self)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        self.profiles[name] = self._collect_profile()
        self.save_config()
        self._refresh_profile_menu()
        self.profile_var.set(name)
        self.status_label.configure(text=f"Profile '{name}' saved.")

    def _ui_load_profile(self):
        name = self.profile_var.get()
        prof = self.profiles.get(name)
        if not prof:
            return
        if prof.get("mode") and prof["mode"] != self.mode:
            if not messagebox.askyesno(
                    "Wrong mode",
                    f"Profile '{name}' was saved in "
                    f"'{prof['mode']}' mode, current is '{self.mode}'.\n"
                    "Apply order/enabled states anyway?"):
                return
        order = prof.get("order", [])
        enabled = prof.get("enabled", {})
        w_by_clean = self._widget_by_clean()
        anchor = self._orderable_container_anchor()
        for clean in order:
            w = w_by_clean.get(clean)
            if w is None:
                continue
            if anchor is not None:
                w.pack_configure(before=anchor)
            else:
                w.pack_configure()
        for clean, w in w_by_clean.items():
            if clean in enabled and hasattr(w, "checkbox"):
                want = bool(enabled[clean])
                if bool(w.checkbox.get()) != want:
                    w.checkbox.toggle()
        self._after_order_change()
        self.status_label.configure(
            text=f"Profile '{name}' applied. Click 'Apply New Order' to "
                 "write it to disk.")

    def _ui_delete_profile(self):
        name = self.profile_var.get()
        if name not in self.profiles:
            return
        if not messagebox.askyesno("Delete Profile",
                                   f"Delete profile '{name}'?"):
            return
        del self.profiles[name]
        self.save_config()
        self._refresh_profile_menu()
        self.status_label.configure(text=f"Profile '{name}' deleted.")

    def _ui_export_profiles(self):
        if not self.profiles:
            messagebox.showinfo("Export", "No profiles to export.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile="dreamsort_profiles.json",
            filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.profiles, f, indent=2)
            self.status_label.configure(text=f"Profiles exported to {path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def _ui_import_profiles(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Not a profiles object")
        except Exception as e:
            messagebox.showerror("Import failed", str(e))
            return
        merged = 0
        for k, v in data.items():
            if isinstance(v, dict) and "order" in v:
                self.profiles[k] = v
                merged += 1
        self.save_config()
        self._refresh_profile_menu()
        self.status_label.configure(
            text=f"Imported {merged} profile(s) from {path}")

    # ------------------------------------------------------- per-mod file info

    @staticmethod
    def _dir_size(path):
        total = 0
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total

    def _format_size(self, n):
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
            n /= 1024.0
        return f"{n:.1f} GB"

    def _mod_info_row(self, parent, mod_name):
        path = os.path.join(self.ryujinx.mods_path, mod_name)
        clean = self.ryujinx.strip_prefix(mod_name)
        try:
            nfiles = sum(len(fs) for _r, _d, fs in os.walk(path))
            size = self._format_size(self._dir_size(path))
        except OSError:
            nfiles, size = "?", "?"
        enabled = self._is_mod_enabled(mod_name)
        info = (f"Name: {clean}\n"
                f"Path: {path}\n"
                f"Files: {nfiles}   Size: {size}\n"
                f"State: {'ENABLED' if enabled else 'DISABLED'}")
        box = ctk.CTkFrame(parent, fg_color=Colors.WIDGET_BG, corner_radius=6)
        box.pack(fill="x", padx=5, pady=(5, 5))
        ctk.CTkLabel(box, text=info, text_color=Colors.TEXT,
                     justify="left", anchor="w").pack(fill="x", padx=8, pady=6)
        ctk.CTkButton(box, text="Open mod folder", width=130,
                      fg_color=Colors.BUTTON_BG,
                      hover_color=Colors.BUTTON_HOVER,
                      command=lambda p=path: open_in_file_explorer(p)
                      ).pack(anchor="w", padx=8, pady=(0, 6))

    def start_apply_worker(self, config):
        self.set_ui_state("working")
        self.progress_bar.set(0)
        self.progress_detail_label.configure(text="Initializing...")
        self.apply_thread = threading.Thread(
            target=self.ryujinx.apply_new_order_threaded,
            args=(config, self.pending_cheat_selections,
                  self.progress_queue),
            daemon=True,
        )
        self.apply_thread.start()
        self.after(100, self.check_apply_progress)

    def check_apply_progress(self):
        try:
            while not self.progress_queue.empty():
                msg = self.progress_queue.get_nowait()
                t = msg.get("type")
                if t == "progress":
                    self.progress_bar.set(msg.get("value", 0))
                    self.progress_detail_label.configure(text=msg.get("text", ""))
                elif t == "status":
                    self.progress_header_label.configure(text=msg.get("text", "..."))
                elif t == "done":
                    self.set_ui_state("idle")
                    messagebox.showinfo("Success", "Changes applied successfully!")
                    self.run_scan()
                    return
                elif t == "error":
                    self.set_ui_state("idle")
                    messagebox.showerror("Saving Error", msg.get("message"))
                    self.run_scan()
                    return
            if self.apply_thread and self.apply_thread.is_alive():
                self.after(100, self.check_apply_progress)
        except Exception as e:
            self.set_ui_state("idle")
            traceback.print_exc()
            messagebox.showerror("UI Error", str(e))

class DreamSortMainWindow(TkinterDnD.Tk):
    def __init__(self, dpi_scale=1.0):
        super().__init__()
        self.dpi_scale = dpi_scale
        self.title(f"dreamSort — Mod Manager {VERSION}")
        try:
            self.iconbitmap(resource_path("yoohyeon.ico"))
        except Exception:
            print("Warning: yoohyeon.ico not found.")
        self.geometry("1600x900")
        self.minsize(900, 650)
        self.configure(bg=Colors.BG)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Menu bar
        self.menu_bar = tk.Menu(self)
        self.config(menu=self.menu_bar)

        file_menu = tk.Menu(self.menu_bar, tearoff=0)
        file_menu.add_command(label="Switch Mode...",
                              command=self.prompt_mode_switch)
        file_menu.add_separator()
        file_menu.add_command(label="Save Config", command=self._save_app_config)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        self.menu_bar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(self.menu_bar, tearoff=0)
        help_menu.add_command(label="About", command=self._show_about)
        self.menu_bar.add_cascade(label="Help", menu=help_menu)

        # Build app
        self.app = None
        initial_mode = "ryujinx"
        try:
            with open(config_path(), "r") as f:
                cfg = json.load(f)
            if cfg.get("remember_mode") and cfg.get("mode") in ("ryujinx", "recomp"):
                initial_mode = cfg["mode"]
            else:
                initial_mode = "ryujinx"
        except Exception:
            initial_mode = "ryujinx"

        self.app = DreamSortApp(self, mode=initial_mode, dpi_scale=dpi_scale)
        self.app.grid(row=0, column=0, sticky="nsew")

        # Show startup dialog if not remembered
        self.after(300, self._maybe_prompt_startup)

    def _maybe_prompt_startup(self):
        try:
            with open(config_path(), "r") as f:
                cfg = json.load(f)
            if cfg.get("remember_mode"):
                return
        except Exception:
            pass
        self.prompt_mode_switch(first_run=True)

    def prompt_mode_switch(self, first_run=False):
        current = self.app.mode if self.app else "ryujinx"
        remembered = False
        try:
            with open(config_path(), "r") as f:
                cfg = json.load(f)
            remembered = cfg.get("remember_mode", False)
        except Exception:
            pass

        def on_result(mode, remember):
            if mode is None:
                return
            if remember:
                self.app.remember_mode = True
                try:
                    with open(config_path(), "r") as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}
                cfg["mode"] = mode
                cfg["remember_mode"] = True
                try:
                    with open(config_path(), "w") as f:
                        json.dump(cfg, f, indent=2)
                except Exception:
                    pass
            else:
                # keep remember_mode as-is (probably False)
                self.app.remember_mode = False

            if self.app and self.app.mode != mode:
                # Recreate the app frame
                try:
                    geo = self.geometry()
                    self.app.destroy()
                    self.app = DreamSortApp(self, mode=mode,
                                            dpi_scale=self.dpi_scale)
                    self.app.grid(row=0, column=0, sticky="nsew")
                    self.geometry(geo)
                except Exception as e:
                    messagebox.showerror("Mode Switch Error", str(e))

        StartupModeDialog(self, current, remembered, on_result)

    def _save_app_config(self):
        if self.app:
            self.app.save_config()
            messagebox.showinfo("Saved", "Configuration saved.")

    def _show_about(self):
        messagebox.showinfo(
            "About dreamSort",
            f"dreamSort Mod Manager {VERSION}\n\n"
            "A mod manager for MHGU on Ryujinx and Morerokk Recomp.\n\n"
            "Supports Windows, Linux (Steam Deck) and macOS.",
        )

## init
if __name__ == "__main__":
    enable_high_dpi_awareness()
    scale = get_dpi_scale()
    try:
        ctk.set_widget_scaling(scale)
        ctk.set_window_scaling(scale)
    except Exception as e:
        print(f"Scaling setup failed: {e}")

    app = DreamSortMainWindow(dpi_scale=scale)
    app.mainloop()