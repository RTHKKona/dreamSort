# ryujinx analyzer

import json
import os
import re
import shutil

from ..helpers.files import is_process_running
from ..storage.atomic import atomic_write_json, atomic_write_text

class RyujinxAnalyzer:
    CHEAT_BUILD_ID_PREFIX = "FB08F1D20FD1204F-"
    TITLE_ID = "0100770008DD8000"

    def __init__(self):
        self.mods_path = ""
        self.mods_json_path = None
        self.mod_files = {}
        self.mod_stats = {}
        self.conflicts = {}
        self.load_order = []
        self.cheat_only_mods = set()
        self.special_cheats_folder_name = None
        self.structure_ok = True
        self.structure_message = ""
        self.structure_suggested = None

    def structure_status(self, path=None):
        """Check the folder."""
        target = os.path.normpath(path) if path else self.mods_path
        if not target:
            return True, "", None
        name = os.path.basename(target).lower()
        parent = os.path.basename(os.path.dirname(target)).lower()
        grand = os.path.basename(os.path.dirname(os.path.dirname(target))).lower()
        title = self.TITLE_ID.lower()
        if name == title:
            if parent == "contents" and grand == "mods":
                return True, "", None
            return (False,
                    "This is the title-id folder, but it is not under "
                    "…\\mods\\contents, so Ryujinx's mod load order may not "
                    "apply.",
                    None)
        if name == "contents":
            return (False,
                    "You selected the 'contents' folder. The mods live in "
                    f"the '{self.TITLE_ID}' folder inside it.",
                    os.path.join(target, self.TITLE_ID))
        if name == "mods":
            return (False,
                    "You selected the Ryujinx 'mods' root. The mods live in "
                    "mods\\contents\\" + self.TITLE_ID + ".",
                    os.path.join(target, "contents", self.TITLE_ID))
        return (False,
                "Not a standard Ryujinx mods folder. Expected "
                "…\\mods\\contents\\" + self.TITLE_ID + ".",
                None)

    def set_mods_path(self, path):
        if not os.path.isdir(path):
            return False
        self.mods_path = os.path.normpath(path)
        self.mods_json_path = None
        self.structure_ok, self.structure_message, \
            self.structure_suggested = self.structure_status()
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
        except Exception:
            self.mods_json_path = None
        return True
    
    def clear_mods_path(self):
        """Drop the scanned folder."""
        self.mods_path = ""
        self.mods_json_path = None
        self.mod_files = {}
        self.mod_stats = {}
        self.conflicts = {}
        self.load_order = []
        self.cheat_only_mods.clear()
        self.special_cheats_folder_name = None
        self.structure_ok = True
        self.structure_message = ""
        self.structure_suggested = None

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
        self.mod_stats = {}
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
            # one pass per mod
            file_count = 0
            total_size = 0
            stack = [(mod_path, "")]
            while stack:
                directory, prefix = stack.pop()
                try:
                    entries = list(os.scandir(directory))
                except OSError:
                    continue
                for entry in entries:
                    rel = prefix + entry.name
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name.lower() != "cheats":
                                stack.append((entry.path, rel + "/"))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        file_count += 1
                        total_size += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
                    self.mod_files[mod_name].add(rel)
                    file_to_mods_map.setdefault(rel, []).append(mod_name)
            self.mod_stats[mod_name] = (file_count, total_size)

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
        # warnings, or None on failure
        if not self.mods_json_path:
            progress_queue.put({"type": "status",
                                "text": "Skipping mods.json (path not found)."})
            return [
                "Ryujinx reads the on/off state from mods.json, and this folder "
                "is not …\\mods\\contents\\" + self.TITLE_ID + ", so nothing was "
                "written there. Mods switched off here still load in Ryujinx; "
                "point the mods folder at …\\mods\\contents\\" + self.TITLE_ID
                + " to have them respected."
            ]

        progress_queue.put({"type": "status",
                            "text": "Phase 3: Updating Ryujinx mods.json..."})
        entries = []
        known = set()
        for cfg in final_mod_list:
            path = self._actual_case_path(
                os.path.abspath(os.path.join(self.mods_path, cfg["name"])))
            entries.append({
                "name": cfg["name"],
                "path": path,
                "enabled": cfg["enabled"],
            })
            known.add(os.path.normcase(path))

        # keep entries we did not write
        preserved = []
        try:
            with open(self.mods_json_path, "r", encoding="utf-8") as handle:
                existing = json.load(handle)
        except (OSError, ValueError):
            existing = None
        if isinstance(existing, dict):
            for item in existing.get("mods") or []:
                if not isinstance(item, dict):
                    continue
                path = item.get("path")
                if isinstance(path, str) and os.path.normcase(path) not in known:
                    preserved.append(item)

        try:
            os.makedirs(os.path.dirname(self.mods_json_path), exist_ok=True)
            atomic_write_json(self.mods_json_path, {"mods": entries + preserved})
        except Exception as e:
            progress_queue.put({
                "type": "error",
                "message": f"Could not write to mods.json.\n\n{self.mods_json_path}\n{e}"
            })
            return None
        if preserved:
            progress_queue.put({
                "type": "status",
                "text": f"Kept {len(preserved)} mods.json entr%s dreamSort did "
                        "not scan." % ("y" if len(preserved) == 1 else "ies"),
            })
        return []

    def _apply_cheat_selections_threaded(self, pending_cheats, progress_queue):
        # enabled.txt is per entry
        enabled_path = self.cheat_enabled_path()
        try:
            os.makedirs(os.path.dirname(enabled_path), exist_ok=True)
            managed = set()
            wanted = set()
            for states in (pending_cheats or {}).values():
                for key, is_enabled in states.items():
                    managed.add(key)
                    if is_enabled:
                        wanted.add(key)

            if not managed:
                progress_queue.put({"type": "status",
                                    "text": "No cheats found, left enabled.txt alone."})
                return True

            # keep lines we cannot place
            preserved = []
            if os.path.isfile(enabled_path):
                try:
                    with open(enabled_path, "r", encoding="utf-8",
                              errors="replace") as handle:
                        for line in handle:
                            entry = line.strip()
                            if entry and not entry.startswith("#") \
                                    and entry not in managed:
                                preserved.append(entry)
                except OSError:
                    preserved = []

            progress_queue.put({"type": "status",
                                "text": "Phase 4: Applying Cheat Selections..."})
            lines = preserved + sorted(wanted)
            atomic_write_text(enabled_path, "".join(line + "\n" for line in lines))
            progress_queue.put({
                "type": "status",
                "text": f"Written {len(wanted)} cheat entries to enabled.txt"
            })
            return True
        except Exception as e:
            progress_queue.put({
                "type": "error",
                "message": f"Could not write enabled.txt.\n\n{enabled_path}\n{e}"
            })
            return False

    # cheat model

    CHEAT_DIR = "cheats"
    CHEAT_ID_SIZE = 16
    CHEAT_ID_RE = re.compile(r"^[0-9A-Fa-f]{16}$")
    # only mods/cheats levels
    CHEAT_WALK_SKIP = ("romfs", "romfslite", "romfs_ext", "exefs",
                       "exefs_patches", "exefs_patches_disabled")

    def cheat_enabled_path(self):
        # the folder is always 'cheats'
        return os.path.join(self.mods_path, self.CHEAT_DIR, "enabled.txt")

    @staticmethod
    def cheat_display_name(title):
        # '<name> Cheat' key
        return "<%s Cheat>" % title

    @classmethod
    def cheat_sections(cls, text):
        """Cheat blocks in one file."""
        sections = []
        title = "<default>"
        start = 0
        count = 0
        offset = 0
        for raw in text.splitlines(True):
            line = raw.strip()
            length = len(raw)
            if line.startswith("["):
                if not line.endswith("]") or len(line) < 3:
                    return []
                if count:
                    sections.append((title, start, offset, count))
                title = line[1:-1]
                start = offset
                count = 0
            elif line:
                count += 1
            offset += length
        if count:
            sections.append((title, start, offset, count))
        return sections

    def discover_cheat_files(self):
        """Every cheat file ryujinx would install."""
        found = []
        if not self.mods_path:
            return found
        root = os.path.abspath(self.mods_path)
        for dirpath, dirnames, filenames in os.walk(root):
            if os.path.basename(dirpath).lower() == self.CHEAT_DIR:
                owner = ""
                parent = os.path.dirname(dirpath)
                if os.path.abspath(parent) != root:
                    owner = os.path.basename(parent)
                for filename in filenames:
                    if not filename.lower().endswith(".txt"):
                        continue
                    build_id = os.path.splitext(filename)[0]
                    if not self.CHEAT_ID_RE.match(build_id):
                        # 16-digit build id only
                        continue
                    path = os.path.join(dirpath, filename)
                    try:
                        with open(path, "r", encoding="utf-8",
                                  errors="replace") as handle:
                            text = handle.read()
                    except OSError:
                        continue
                    sections = self.cheat_sections(text)
                    entries = []
                    for index, section in enumerate(sections):
                        name = self.cheat_display_name(section[0])
                        entries.append({
                            "title": section[0],
                            "name": name,
                            "index": index,
                            "key": "%s-%s" % (build_id.upper(), name),
                        })
                    if entries:
                        found.append({
                            "path": path,
                            "rel": os.path.relpath(path, root).replace("\\", "/"),
                            "build_id": build_id.upper(),
                            "owner": owner,
                            "entries": entries,
                        })
                dirnames[:] = []
                continue
            rel_parts = os.path.relpath(dirpath, root).split(os.sep)
            if len(rel_parts) > 4:
                dirnames[:] = []
                continue
            dirnames[:] = [name for name in dirnames
                           if name.lower() not in self.CHEAT_WALK_SKIP]
        found.sort(key=lambda item: item["rel"].lower())
        return found

    def cheat_enabled_keys(self):
        keys = set()
        try:
            with open(self.cheat_enabled_path(), "r", encoding="utf-8",
                      errors="replace") as handle:
                for line in handle:
                    entry = line.strip()
                    if entry and not entry.startswith("#"):
                        keys.add(entry)
        except OSError:
            pass
        return keys

    def update_cheat_section(self, path, index, new_text):
        """Swap one block in a cheat file."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError as exc:
            raise ValueError("Could not read %s: %s"
                             % (os.path.basename(path), exc))
        sections = self.cheat_sections(text)
        if not 0 <= index < len(sections):
            raise ValueError("Cheat entry %d no longer exists in %s."
                             % (index + 1, os.path.basename(path)))
        body = new_text.replace("\r\n", "\n").strip("\n")
        if not body.strip():
            raise ValueError("Refusing to save an empty cheat entry.")
        if not self.cheat_sections(body):
            raise ValueError("Ryujinx ignores a block with no instruction "
                             "lines, so that edit would delete the cheat.")
        start = sections[index][1]
        end = sections[index][2]
        tail = text[end:]
        replacement = body + "\n" + ("\n" if tail and not tail.startswith("\n")
                                     else "")
        atomic_write_text(path, text[:start] + replacement + tail)

    def preferred_cheat_build_id(self):
        """Build id for a new cheat file."""
        counts = {}
        for entry in self.discover_cheat_files():
            counts[entry["build_id"]] = counts.get(entry["build_id"], 0) + 1
        default = self.CHEAT_BUILD_ID_PREFIX.rstrip("-")
        if default in counts:
            return default
        if counts:
            return max(counts, key=counts.get)
        return default

    # folder moves
    STAGE_PREFIX = "__dreamsort_stage__"
    STAGE_RE = re.compile(r"^__dreamsort_stage__\d+__(.+)$", re.DOTALL)
    LEGACY_TEMP_SUFFIX = "__temp_rename__"

    def _unique_folder(self, desired, taken):
        # numeric suffix keeps them apart
        if desired not in taken and not os.path.exists(
                os.path.join(self.mods_path, desired)):
            taken.add(desired)
            return desired
        index = 2
        while True:
            candidate = "%s (%d)" % (desired, index)
            if candidate not in taken and not os.path.exists(
                    os.path.join(self.mods_path, candidate)):
                taken.add(candidate)
                return candidate
            index += 1

    def _actual_case_path(self, path):
        # spell the path like windows does
        drive, rest = os.path.splitdrive(path)
        parts = [part for part in re.split(r"[\\/]+", rest) if part]
        if drive.startswith("\\\\"):
            current = drive + os.sep
        elif drive:
            current = drive[:2].upper() + os.sep
        else:
            current = ""
        for part in parts:
            try:
                siblings = os.listdir(current or os.sep)
            except OSError:
                return path
            match = next((name for name in siblings
                          if name.lower() == part.lower()), None)
            current = os.path.join(current, match or part) if current \
                else (match or part)
        return current or path

    def _unstage(self, staged):
        # back to the old names
        blocked = []
        for entry in staged:
            source = os.path.join(self.mods_path, entry["temp"])
            target = os.path.join(self.mods_path, entry["original"])
            try:
                if not os.path.isdir(source):
                    continue
                if os.path.exists(target):
                    blocked.append(entry["original"])
                    continue
                shutil.move(source, target)
            except OSError:
                blocked.append(entry["original"])
        return blocked

    def _recover_staged_folders(self, progress_queue):
        # undo old staging names
        recovered = []
        try:
            names = sorted(os.listdir(self.mods_path))
        except OSError:
            return recovered
        for name in names:
            full = os.path.join(self.mods_path, name)
            if not os.path.isdir(full):
                continue
            match = self.STAGE_RE.match(name)
            if match:
                original = match.group(1)
            elif name.endswith(self.LEGACY_TEMP_SUFFIX) and \
                    name != self.LEGACY_TEMP_SUFFIX:
                # old build used the clean name
                original = name[:-len(self.LEGACY_TEMP_SUFFIX)]
            else:
                continue
            target = os.path.join(self.mods_path, original)
            if os.path.exists(target):
                continue
            try:
                shutil.move(full, target)
            except OSError:
                continue
            recovered.append(original)
        if recovered:
            shown = ", ".join(recovered[:3]) + ("…" if len(recovered) > 3 else "")
            progress_queue.put({
                "type": "status",
                "text": "Recovered %d folder(s) from an interrupted apply: %s"
                        % (len(recovered), shown),
            })
        return recovered

    def _restore_report(self, blocked):
        if not blocked:
            return "Every staged folder was put back."
        return ("Could not put back: %s\n\nThey are named %s<n>__<name>; "
                "the next Apply restores them."
                % (", ".join(blocked[:5]), self.STAGE_PREFIX))

    def apply_new_order_threaded(self, ordered_mods_config, pending_cheats,
                                  progress_queue):
        if not self.mods_path:
            progress_queue.put({"type": "error", "message": "Mods path not set."})
            return

        warnings = []
        self._recover_staged_folders(progress_queue)

        try:
            current_mods = [d for d in os.listdir(self.mods_path)
                            if os.path.isdir(os.path.join(self.mods_path, d))]
        except Exception as e:
            progress_queue.put({"type": "error",
                                "message": f"Failed to list mod directories: {e}"})
            return
        current_mods.sort()
        total_ops = len(current_mods) + len(ordered_mods_config) + 1
        ops_done = 0

        progress_queue.put({"type": "status",
                            "text": "Phase 1: Staging current mods..."})
        staged = []
        for index, mod_name in enumerate(current_mods):
            temp_name = "%s%d__%s" % (self.STAGE_PREFIX, index, mod_name)
            progress_queue.put({
                "type": "progress",
                "value": ops_done / max(total_ops, 1),
                "text": f"Staging: '{mod_name}'",
            })
            try:
                shutil.move(os.path.join(self.mods_path, mod_name),
                            os.path.join(self.mods_path, temp_name))
            except PermissionError as e:
                blocked = self._unstage(staged)
                progress_queue.put({
                    "type": "error",
                    "message": (f"Permission denied renaming '{mod_name}'. "
                                "Close Ryujinx and retry.\n\n"
                                + self._restore_report(blocked) + f"\n\n{e}"),
                })
                return
            except Exception as e:
                blocked = self._unstage(staged)
                progress_queue.put({
                    "type": "error",
                    "message": (f"Could not rename '{mod_name}'.\n\n"
                                + self._restore_report(blocked) + f"\n\n{e}"),
                })
                return
            staged.append({"original": mod_name,
                           "temp": temp_name,
                           "clean": self.strip_prefix(mod_name)})
            ops_done += 1

        progress_queue.put({"type": "status",
                            "text": "Phase 2: Writing final names..."})
        by_original = {entry["original"]: entry for entry in staged}
        by_clean = {}
        for entry in staged:
            by_clean.setdefault(entry["clean"], entry)

        final_mod_list = []
        taken = set()
        consumed = set()
        idx = 0

        def place(entry, final_name):
            shutil.move(os.path.join(self.mods_path, entry["temp"]),
                        os.path.join(self.mods_path, final_name))

        try:
            if self.special_cheats_folder_name:
                entry = by_original.get(self.special_cheats_folder_name)
                if entry:
                    place(entry, self.special_cheats_folder_name)
                    consumed.add(entry["original"])
                    ops_done += 1

            for mod_name, is_enabled in ordered_mods_config.items():
                if mod_name == self.special_cheats_folder_name:
                    continue
                entry = by_original.get(mod_name)
                if entry is None:
                    # fallback for the clean name
                    entry = by_clean.get(self.strip_prefix(mod_name))
                if entry is None or entry["original"] in consumed:
                    continue
                clean = entry["clean"]
                if mod_name in self.cheat_only_mods or not is_enabled:
                    final_name = self._unique_folder("~" + clean, taken)
                    enabled_status = False
                else:
                    idx += 1
                    final_name = self._unique_folder("%02d_%s" % (idx, clean),
                                                     taken)
                    enabled_status = True
                progress_queue.put({
                    "type": "progress",
                    "value": ops_done / max(total_ops, 1),
                    "text": f"Writing: '{final_name}'",
                })
                place(entry, final_name)
                consumed.add(entry["original"])
                final_mod_list.append({"name": final_name,
                                       "enabled": enabled_status})
                ops_done += 1

            # folder added after the scan
            for entry in staged:
                if entry["original"] in consumed:
                    continue
                final_name = self._unique_folder(entry["original"], taken)
                place(entry, final_name)
                consumed.add(entry["original"])
                final_mod_list.append({
                    "name": final_name,
                    "enabled": not final_name.startswith("~"),
                })
                ops_done += 1
        except PermissionError as e:
            remaining = [entry for entry in staged
                         if entry["original"] not in consumed]
            blocked = self._unstage(remaining)
            progress_queue.put({
                "type": "error",
                "message": ("Permission denied. Close Ryujinx and retry.\n\n"
                            + self._restore_report(blocked) + f"\n\n{e}"),
            })
            return
        except Exception as e:
            remaining = [entry for entry in staged
                         if entry["original"] not in consumed]
            blocked = self._unstage(remaining)
            progress_queue.put({
                "type": "error",
                "message": (f"Could not apply new order.\n\n"
                            + self._restore_report(blocked) + f"\n\n{e}"),
            })
            return

        mods_json_warnings = self._update_ryujinx_mods_json(final_mod_list,
                                                           progress_queue)
        if mods_json_warnings is None:
            return
        warnings.extend(mods_json_warnings)
        if not self._apply_cheat_selections_threaded(pending_cheats, progress_queue):
            return
        message = "Changes applied."
        if warnings:
            message = "Changes applied.\n\n" + "\n\n".join(warnings)
        progress_queue.put({"type": "done", "message": message})

