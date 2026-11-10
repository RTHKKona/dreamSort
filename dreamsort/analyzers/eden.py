# eden analyzer

import os
import re
import shutil

from ..storage import atomic_write_text
from . import eden_config
from .ryujinx import RyujinxAnalyzer


class EdenAnalyzer(RyujinxAnalyzer):
    TITLE_ID = "0100770008DD8000"
    # build id for the cheat file
    CHEAT_BUILD_ID = "FB08F1D20FD1204F"

    DISABLED_MODS = "disabled_mods"
    DISABLED_CHEATS = "disabled_cheats"
    CHEATS_FOLDER = "cheats"

    # cheat ticks live under one key
    CHEAT_STATE_KEY = "__eden_cheats__"

    def __init__(self):
        super().__init__()
        self.variant = ""
        self.mod_enabled = {}
        self.cheat_enabled = {}

    # structure
    def structure_status(self, path=None):
        # load folder
        target = os.path.normpath(path) if path else self.mods_path
        if not target:
            return True, "", None
        name = os.path.basename(target).lower()
        parent = os.path.basename(os.path.dirname(target)).lower()

        if name == self.TITLE_ID.lower():
            if parent == "load":
                return True, "", None
            return (False,
                    "This is the title-id folder, but it is not under a 'load' "
                    "folder, so Eden will not load anything from it.",
                    None)
        if name == "load":
            return (False,
                    "You selected the Eden 'load' folder. The mods live in the "
                    "'%s' folder inside it." % self.TITLE_ID,
                    os.path.join(target, self.TITLE_ID))
        if name in ("eden", "user", "contents"):
            return (False,
                    "You selected an Eden root folder. The mods live in "
                    "load\\%s inside it." % self.TITLE_ID,
                    os.path.join(target, "load", self.TITLE_ID))
        return (False,
                "Not a standard Eden mods folder. Expected "
                "…\\eden\\load\\%s (installed) or "
                "…\\eden\\user\\load\\%s (portable)."
                % (self.TITLE_ID, self.TITLE_ID),
                None)

    def set_mods_path(self, path):
        if not os.path.isdir(path):
            return False
        self.mods_path = os.path.normpath(path)
        # no mods.json
        self.mods_json_path = None
        parts = self.mods_path.split(os.sep)
        parent = parts[-2].lower() if len(parts) >= 2 else ""
        grand = parts[-3].lower() if len(parts) >= 3 else ""
        if parent != "load":
            self.variant = ""
        elif grand == "user":
            self.variant = "portable"
        else:
            self.variant = "installed"
        self.structure_ok, self.structure_message, \
            self.structure_suggested = self.structure_status()
        return True

    def clear_mods_path(self):
        super().clear_mods_path()
        self.variant = ""
        self.mod_enabled = {}
        self.cheat_enabled = {}

    @property
    def eden_root(self):
        # data folder
        if not self.mods_path:
            return ""
        return os.path.dirname(os.path.dirname(self.mods_path))

    @property
    def config_dir(self):
        # ini files
        return eden_config.config_dir_for(self.eden_root)

    @property
    def disabled_mods_path(self):
        return os.path.join(self.mods_path, self.DISABLED_MODS)

    @property
    def disabled_cheats_path(self):
        return os.path.join(self.mods_path, self.DISABLED_CHEATS)

    def variant_label(self):
        return {"portable": "portable", "installed": "installed"}.get(
            self.variant, "unrecognised")

    # scan
    # game file names
    CONTENT_FOLDERS = ("romfs", "romfslite", "romfs_ext", "exefs",
                       "manual_html")

    @staticmethod
    def _is_cheat_folder(path):
        # cheat-only folder
        try:
            top = [name.lower() for name in os.listdir(path)]
        except OSError:
            return False
        if "cheats" not in top:
            return False
        return not any(name in top for name in EdenAnalyzer.CONTENT_FOLDERS)

    def _folder_names(self, directory):
        try:
            names = os.listdir(directory)
        except OSError:
            return []
        return [name for name in names
                if os.path.isdir(os.path.join(directory, name))]

    @staticmethod
    def _sort_key(name):
        return [int(part) if part.isdigit() else part.lower()
                for part in re.split("([0-9]+)", name)]

    def scan_and_analyze(self):
        if not self.mods_path:
            return
        self.mod_files = {}
        self.mod_stats = {}
        self.conflicts = {}
        self.load_order = []
        self.cheat_only_mods.clear()
        self.special_cheats_folder_name = None
        self.mod_enabled = {}
        self.cheat_enabled = {}

        enabled_mods = []
        disabled_mods = []
        enabled_cheats = []
        disabled_cheats = []

        for name in self._folder_names(self.mods_path):
            if name.lower() in (self.DISABLED_MODS, self.DISABLED_CHEATS):
                continue
            path = os.path.join(self.mods_path, name)
            if self._is_cheat_folder(path):
                enabled_cheats.append(name)
            else:
                enabled_mods.append(name)

        for name in self._folder_names(self.disabled_mods_path):
            disabled_mods.append(name)
        for name in self._folder_names(self.disabled_cheats_path):
            disabled_cheats.append(name)

        enabled_mods.sort(key=self._sort_key)
        disabled_mods.sort(key=self._sort_key)
        enabled_cheats.sort(key=self._sort_key)
        disabled_cheats.sort(key=self._sort_key)

        for name in enabled_mods:
            self.mod_enabled[name] = True
        for name in disabled_mods:
            self.mod_enabled[name] = False
        for name in enabled_cheats:
            self.cheat_enabled[name] = True
        for name in disabled_cheats:
            self.cheat_enabled[name] = False

        self.load_order = enabled_mods + disabled_mods

        # parked mods cannot conflict
        file_to_mods = {}
        for mod_name in enabled_mods:
            mod_path = os.path.join(self.mods_path, mod_name)
            self.mod_files[mod_name] = set()
            # file list and sizes
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
                            if entry.name.lower() != self.CHEATS_FOLDER:
                                stack.append((entry.path, rel + "/"))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        file_count += 1
                        total_size += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
                    self.mod_files[mod_name].add(rel)
                    file_to_mods.setdefault(rel, []).append(mod_name)
            self.mod_stats[mod_name] = (file_count, total_size)

        for rel_path, mods in file_to_mods.items():
            if len(mods) > 1:
                for mod_name in mods:
                    self.conflicts.setdefault(mod_name, {})[rel_path] = [
                        other for other in mods if other != mod_name
                    ]

    def is_mod_enabled(self, mod_name):
        return bool(self.mod_enabled.get(mod_name, True))

    def cheat_states(self):
        return dict(self.cheat_enabled)

    def cheat_folder_path(self, name):
        # current folder
        if os.path.isdir(os.path.join(self.disabled_cheats_path, name)):
            return os.path.join(self.disabled_cheats_path, name)
        return os.path.join(self.mods_path, name)

    def cheat_code_path(self, name):
        folder = os.path.join(self.cheat_folder_path(name), self.CHEATS_FOLDER)
        try:
            files = [filename for filename in os.listdir(folder)
                     if filename.lower().endswith(".txt")]
        except OSError:
            return ""
        if not files:
            return ""
        return os.path.join(folder, sorted(files)[0])

    # cheat split
    CHEAT_HEADER_RE = re.compile(r"(?m)^[ \t]*\[([^\[\]\r\n]+)\][ \t]*$")

    def cheat_code_files(self, name):
        """The cheat .txt files in a cheat folder."""
        folder = os.path.join(self.cheat_folder_path(name), self.CHEATS_FOLDER)
        try:
            names = sorted(filename for filename in os.listdir(folder)
                           if filename.lower().endswith(".txt"))
        except OSError:
            return []
        return [os.path.join(folder, filename) for filename in names]

    @classmethod
    def cheat_block_spans(cls, text):
        """Offsets of each block in text."""
        matches = list(cls.CHEAT_HEADER_RE.finditer(text))
        spans = []
        for index, match in enumerate(matches):
            end = (matches[index + 1].start()
                   if index + 1 < len(matches) else len(text))
            spans.append((match.group(1).strip(), match.start(), end))
        return spans

    @classmethod
    def cheat_blocks(cls, text):
        """Split a cheat file into blocks."""
        return [(title, text[start:end].rstrip() + "\n")
                for title, start, end in cls.cheat_block_spans(text)]

    def update_cheat_block(self, path, index, new_text):
        """Swap one block in a cheat file."""
        try:
            with open(path, "r", encoding="utf-8",
                      errors="replace") as handle:
                text = handle.read()
        except OSError as exc:
            raise ValueError("Could not read %s: %s"
                             % (os.path.basename(path), exc))
        spans = self.cheat_block_spans(text)
        if not 0 <= index < len(spans):
            raise ValueError("Cheat entry %d no longer exists in %s."
                             % (index + 1, os.path.basename(path)))
        _title, start, end = spans[index]
        body = new_text.replace("\r\n", "\n").strip("\n")
        if not body.strip():
            raise ValueError("Refusing to save an empty cheat entry.")
        tail = text[end:]
        replacement = body + "\n" + ("\n" if tail and not tail.startswith("\n")
                                     else "")
        atomic_write_text(path, text[:start] + replacement + tail)

    @staticmethod
    def _unique_folder(desired, taken):
        # case-insensitive names
        name, index = desired, 2
        while name.lower() in taken:
            name = "%s (%d)" % (desired, index)
            index += 1
        taken.add(name.lower())
        return name

    def split_cheat_entry(self, name):
        """Split a cheat entry into one folder per block."""
        sources = self.cheat_code_files(name)
        if not sources:
            raise ValueError("No .txt inside '%s/%s'."
                             % (name, self.CHEATS_FOLDER))
        blocks = []
        for path in sources:
            try:
                with open(path, "r", encoding="utf-8",
                          errors="replace") as handle:
                    text = handle.read()
            except OSError as exc:
                raise ValueError("Could not read %s: %s"
                                 % (os.path.basename(path), exc))
            blocks.extend(self.cheat_blocks(text))
        if not blocks:
            raise ValueError("No [Title] header in this cheat file, so there "
                             "is nothing to split.")
        if len(blocks) < 2:
            raise ValueError("This cheat holds a single [Title] block, "
                             "so there is nothing to split.")

        enabled = bool(self.cheat_enabled.get(name, True))
        target_root = self.mods_path if enabled else self.disabled_cheats_path
        os.makedirs(target_root, exist_ok=True)
        taken = set()
        for folder in (self._folder_names(self.mods_path)
                       + self._folder_names(self.disabled_cheats_path)):
            taken.add(folder.lower())

        created = []
        for title, block in blocks:
            # trailing dots and spaces
            clean = self._safe_name(title).rstrip(" .")
            base = clean or self._safe_name(name)
            folder_name = self._unique_folder(base, taken)
            folder = os.path.join(target_root, folder_name)
            cheat_dir = os.path.join(folder, self.CHEATS_FOLDER)
            os.makedirs(cheat_dir)
            atomic_write_text(os.path.join(cheat_dir,
                                           (clean or "cheat") + ".txt"), block)
            created.append(folder_name)

        if enabled and os.path.isdir(os.path.join(self.mods_path, name)):
            os.makedirs(self.disabled_cheats_path, exist_ok=True)
            parked = os.path.join(self.disabled_cheats_path, name)
            if not os.path.exists(parked):
                shutil.move(os.path.join(self.mods_path, name), parked)
        return created

    # applying
    @staticmethod
    def _safe_name(name):
        return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "entry"

    def _unique(self, desired, taken):
        if desired not in taken:
            taken.add(desired)
            return desired
        index = 2
        while "%s (%d)" % (desired, index) in taken:
            index += 1
        final = "%s (%d)" % (desired, index)
        taken.add(final)
        return final

    EDEN_TEMP_SUFFIX = "__eden_tmp__"

    def _recover_staged_folders(self, progress_queue):
        # clean up temp names
        recovered = []
        for directory in (self.mods_path, self.disabled_mods_path):
            for name in self._folder_names(directory):
                if self.EDEN_TEMP_SUFFIX not in name:
                    continue
                base = re.sub(r" \(\d+\)$", "",
                              name.split(self.EDEN_TEMP_SUFFIX)[0]).strip()
                if not base:
                    continue
                target = os.path.join(directory, base)
                if os.path.exists(target):
                    continue
                try:
                    shutil.move(os.path.join(directory, name), target)
                except OSError:
                    continue
                recovered.append(base)
        if recovered:
            progress_queue.put({
                "type": "status",
                "text": "Recovered %d folder(s) from an interrupted apply: %s"
                        % (len(recovered),
                           ", ".join(recovered[:3])
                           + ("…" if len(recovered) > 3 else "")),
            })
        return recovered

    def _unstage(self, staged):
        blocked = []
        for entry in staged:
            source = os.path.join(self.mods_path, entry["temp"])
            target = os.path.join(entry["origin"], entry["original"])
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

    def _restore_report(self, blocked, exc):
        if not blocked:
            return "Every staged folder was put back.\n\n%s" % exc
        return ("Could not put back: %s\n\nThey are named <name>%s; the next "
                "Apply restores them.\n\n%s"
                % (", ".join(blocked[:5]), self.EDEN_TEMP_SUFFIX, exc))

    def apply_new_order_threaded(self, ordered_mods_config, pending_cheats,
                                 progress_queue):
        if not self.mods_path:
            progress_queue.put({"type": "error", "message": "Mods path not set."})
            return

        cheat_states = dict((pending_cheats or {}).get(self.CHEAT_STATE_KEY, {}))
        self._recover_staged_folders(progress_queue)

        # key by the folder name
        sources = []
        for name in self._folder_names(self.mods_path):
            if name.lower() in (self.DISABLED_MODS, self.DISABLED_CHEATS):
                continue
            path = os.path.join(self.mods_path, name)
            if self._is_cheat_folder(path):
                continue
            sources.append({"original": name, "origin": self.mods_path,
                            "clean": self.strip_prefix(name)})
        for name in self._folder_names(self.disabled_mods_path):
            sources.append({"original": name,
                            "origin": self.disabled_mods_path,
                            "clean": self.strip_prefix(name)})

        total = max(len(sources) + len(cheat_states) + 1, 1)
        done = 0

        progress_queue.put({"type": "status",
                           "text": "Phase 1: Staging mods..."})
        staged = []
        taken_temps = set()
        for entry in sources:
            temp_name = self._unique(
                "%s%s" % (self._safe_name(entry["original"]),
                          self.EDEN_TEMP_SUFFIX), taken_temps)
            progress_queue.put({
                "type": "progress",
                "value": done / total,
                "text": "Staging: '%s'" % entry["original"],
            })
            try:
                shutil.move(os.path.join(entry["origin"], entry["original"]),
                            os.path.join(self.mods_path, temp_name))
            except PermissionError as exc:
                blocked = self._unstage(staged)
                progress_queue.put({
                    "type": "error",
                    "message": ("Permission denied moving '%s'. Close Eden and "
                                "retry.\n\n%s"
                                % (entry["original"],
                                   self._restore_report(blocked, exc))),
                })
                return
            except Exception as exc:
                blocked = self._unstage(staged)
                progress_queue.put({
                    "type": "error",
                    "message": "Could not stage '%s'.\n\n%s"
                               % (entry["original"],
                                  self._restore_report(blocked, exc)),
                })
                return
            staged.append({"original": entry["original"],
                           "clean": entry["clean"],
                           "origin": entry["origin"],
                           "temp": temp_name})
            done += 1

        progress_queue.put({"type": "status",
                            "text": "Phase 2: Writing mod folders..."})
        by_original = {entry["original"]: entry for entry in staged}
        by_clean = {}
        for entry in staged:
            by_clean.setdefault(entry["clean"], entry)

        taken_names = set()
        index = 0
        consumed = set()
        try:
            for mod_id, enabled in ordered_mods_config.items():
                entry = by_original.get(mod_id)
                if entry is None:
                    # fallback for the clean name
                    entry = by_clean.get(self.strip_prefix(mod_id))
                if entry is None or entry["original"] in consumed:
                    continue
                clean = entry["clean"]
                if enabled:
                    index += 1
                    final = self._unique(
                        "%02d_%s" % (index, self._safe_name(clean)),
                        taken_names)
                    dest = os.path.join(self.mods_path, final)
                else:
                    os.makedirs(self.disabled_mods_path, exist_ok=True)
                    final = self._unique(self._safe_name(clean), taken_names)
                    dest = os.path.join(self.disabled_mods_path, final)
                progress_queue.put({
                    "type": "progress",
                    "value": done / total,
                    "text": "Writing: '%s'" % final,
                })
                shutil.move(os.path.join(self.mods_path, entry["temp"]), dest)
                consumed.add(entry["original"])
                done += 1

            # put stray folders back
            for entry in staged:
                if entry["original"] in consumed:
                    continue
                final = self._unique(entry["original"], taken_names)
                shutil.move(os.path.join(self.mods_path, entry["temp"]),
                            os.path.join(entry["origin"], final))
                consumed.add(entry["original"])
                done += 1
        except PermissionError as exc:
            remaining = [entry for entry in staged
                         if entry["original"] not in consumed]
            blocked = self._unstage(remaining)
            progress_queue.put({
                "type": "error",
                "message": ("Permission denied. Close Eden and retry.\n\n%s"
                            % self._restore_report(blocked, exc)),
            })
            return
        except Exception as exc:
            remaining = [entry for entry in staged
                         if entry["original"] not in consumed]
            blocked = self._unstage(remaining)
            progress_queue.put({
                "type": "error",
                "message": ("Could not write mod folders.\n\n%s"
                            % self._restore_report(blocked, exc)),
            })
            return

        progress_queue.put({"type": "status",
                            "text": "Phase 3: Moving cheats..."})
        os.makedirs(self.disabled_cheats_path, exist_ok=True)
        for name, wanted in cheat_states.items():
            enabled_path = os.path.join(self.mods_path, name)
            disabled_path = os.path.join(self.disabled_cheats_path, name)
            done += 1
            try:
                if wanted and os.path.isdir(disabled_path) and \
                        not os.path.isdir(enabled_path):
                    shutil.move(disabled_path, enabled_path)
                elif not wanted and os.path.isdir(enabled_path) and \
                        not os.path.isdir(disabled_path):
                    shutil.move(enabled_path, disabled_path)
            except PermissionError:
                progress_queue.put({
                    "type": "error",
                    "message": ("Permission denied moving cheat '%s'. Close "
                                "Eden and retry." % name),
                })
                return
            except Exception as exc:
                progress_queue.put({
                    "type": "error",
                    "message": "Could not move cheat '%s'.\n\n%s" % (name, exc),
                })
                return
            progress_queue.put({
                "type": "progress",
                "value": done / total,
                "text": "Cheat: '%s' %s" % (name, "on" if wanted else "off"),
            })

        progress_queue.put({"type": "done"})
