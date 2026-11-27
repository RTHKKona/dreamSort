# recomp analyzer

import hashlib
import os
import re
import shutil

from ..helpers.files import rename_prefixed_file
from ..install.commit import is_scratch_name
from ..rules.manifest import read_manifest
from ..storage.atomic import atomic_write_text

class RecompAnalyzer:
    # recomp layout
    MODS_FOLDER = "mods"
    LEGACY_DISABLED_FOLDER = "mods_disabled"
    CHEATS_FOLDER = "cheats"
    LOAD_ORDER_NAME = "load_order.txt"
    LOAD_ORDER_MARK = "# Written by the Mods tab"  # marker
    # port-side native code: engine_modules/<name>/<name>.dll (.so)
    MODULES_FOLDER = "engine_modules"
    MODULES_LIST_NAME = "enabled.txt"
    MODULE_EXTS = (".dll", ".so")

    EXE_NAMES = ("mhgurecomp.exe", "mhgurecomp", "mhgurecomp.app")

    def __init__(self):
        self.root_path = ""
        self.mods_path = ""
        self.disabled_mods_path = ""
        self.cheats_path = ""
        self.load_order_path = ""
        self.engine_modules_path = ""
        self.engine_modules_list_path = ""

        # mods
        self.mods = {}
        # cheat files
        self.cheats = {}
        # engine modules
        self.modules = {}
        self.module_order = []
        # patch list
        self.patches = []
        # plugin list
        self.plugins = []
        # conflicts
        self.conflicts = {}
        # arc conflicts
        self.conflict_entries = {}
        # notes
        self.conflict_examples = {}
        # merges
        self.mergeable_arcs = {}
        self._arc_cache = {}
        # digest cache
        self._arc_digest_cache = {}

    # config

    def set_root(self, path):
        if not path or not os.path.isdir(path):
            return False
        self.root_path = os.path.normpath(path)
        self.mods_path = os.path.join(self.root_path, self.MODS_FOLDER)
        self.disabled_mods_path = os.path.join(self.root_path,
                                               self.LEGACY_DISABLED_FOLDER)
        self.cheats_path = os.path.join(self.root_path, self.CHEATS_FOLDER)
        self.load_order_path = os.path.join(self.mods_path,
                                            self.LOAD_ORDER_NAME)
        self.engine_modules_path = os.path.join(self.root_path,
                                                self.MODULES_FOLDER)
        self.engine_modules_list_path = os.path.join(
            self.engine_modules_path, self.MODULES_LIST_NAME)
        return True

    def locate_recomp_exe(self):
        if not self.root_path:
            return None
        for name in self.EXE_NAMES:
            p = os.path.join(self.root_path, name)
            if os.path.exists(p):
                return p
        return None

    def structure_status(self, path=None):
        """Check the folder."""
        target = os.path.normpath(path) if path else self.root_path
        if not target:
            return True, "", None
        if not os.path.isdir(target):
            return (False,
                    "That folder does not exist. Select the MHGU Recomp root "
                    "(the folder containing mhgurecomp).",
                    None)

        # marker check
        for name in self.EXE_NAMES:
            if os.path.exists(os.path.join(target, name)):
                return True, "", None

        # or mods + cheats
        if (os.path.isdir(os.path.join(target, self.MODS_FOLDER))
                and os.path.isdir(os.path.join(target, self.CHEATS_FOLDER))):
            return True, "", None

        name = os.path.basename(target).lower()
        parent = os.path.dirname(target)
        if name == self.MODS_FOLDER:
            return (False,
                    "You selected the 'mods' folder. Pick its parent folder, "
                    "which contains mhgurecomp.",
                    parent)
        if name == self.CHEATS_FOLDER:
            return (False,
                    "You selected the 'cheats' folder. Pick the MHGU Recomp "
                    "root folder that contains mhgurecomp and mods/.",
                    parent)
        if name == self.LEGACY_DISABLED_FOLDER:
            return (False,
                    "You selected the legacy 'mods_disabled' folder. Pick "
                    "the MHGU Recomp root folder that contains mhgurecomp.",
                    parent)
        return (False,
                "Not an MHGU Recomp folder: mhgurecomp was not found here. "
                "Select the folder that contains mhgurecomp, mods/ and "
                "cheats/.", None)

    def clear_root(self):
        """Drop the scanned root."""
        self.root_path = ""
        self.mods_path = ""
        self.disabled_mods_path = ""
        self.cheats_path = ""
        self.load_order_path = ""
        self.engine_modules_path = ""
        self.engine_modules_list_path = ""
        self.mods.clear()
        self.cheats.clear()
        self.modules.clear()
        self.module_order = []
        self.patches.clear()
        self.plugins.clear()
        self.conflicts.clear()
        self.conflict_entries.clear()
        self.conflict_examples.clear()
        self.mergeable_arcs.clear()
        self._arc_cache.clear()
        self._arc_digest_cache.clear()

    # scanning

    @staticmethod
    def _strip_number_prefix(name):
        # ignore a __tmp__ prefix
        while name.startswith("__tmp__"):
            name = name[len("__tmp__"):]
        # underscore means off
        if name.startswith("_") and name != "_":
            name = name[1:]
        m = re.match(r"^(\d+)_(.*)$", name)
        return m.group(2) if m else name

    @staticmethod
    def _extract_prefix_number(name):
        m = re.match(r"^(\d+)_", name)
        return int(m.group(1)) if m else 10_000

    def scan(self):
        self.mods.clear()
        self.cheats.clear()
        self.modules.clear()
        self.module_order = []
        self.patches.clear()
        self.plugins.clear()
        self.conflicts.clear()
        self.conflict_entries.clear()
        self.conflict_examples.clear()
        self.mergeable_arcs.clear()
        self._arc_cache.clear()
        self._arc_digest_cache.clear()

        # mods folder
        raw_entries = []
        if os.path.isdir(self.mods_path):
            for raw in sorted(os.listdir(self.mods_path),
                              key=lambda n: n.lower()):
                full = os.path.join(self.mods_path, raw)
                if not os.path.isdir(full):
                    continue
                if raw.startswith("__tmp__") or is_scratch_name(raw):
                    continue
                raw_entries.append((raw, full, True))

        legacy_entries = []
        if os.path.isdir(self.disabled_mods_path):
            for raw in sorted(os.listdir(self.disabled_mods_path),
                              key=lambda n: n.lower()):
                full = os.path.join(self.disabled_mods_path, raw)
                if (os.path.isdir(full) and not raw.startswith("__tmp__")
                        and not is_scratch_name(raw)):
                    legacy_entries.append((raw, full, False))

        # load order
        ordered_raw, off_raw, has_list, ours = self._read_load_order(raw_entries)
        for raw, full, _on in raw_entries:
            clean = self._strip_number_prefix(raw)
            if clean in self.mods:
                continue  # duplicate name
            enabled = raw in ordered_raw
            if has_list and ours and raw not in ordered_raw \
                    and raw not in off_raw:
                enabled = True  # new mod
            if not has_list:
                enabled = not raw.startswith("_")
            order = (ordered_raw.index(raw) if raw in ordered_raw else 10_000)
            
            self.mods[clean] = {
                "enabled": enabled,
                "order": order,
                "path": full,
                "raw_name": raw,
            }
        for raw, full, _on in legacy_entries:
            clean = self._strip_number_prefix(raw)
            if clean in self.mods:
                continue
            self.mods[clean] = {
                "enabled": False,
                "order": 10_000,
                "path": full,
                "raw_name": raw,
                "legacy_disabled": True,
            }

        # cheats
        if os.path.isdir(self.cheats_path):
            for fname in sorted(os.listdir(self.cheats_path)):
                if not fname.lower().endswith(".txt"):
                    continue
                enabled = not fname.startswith("_")
                clean = fname if enabled else fname[1:]
                # the '_' switches a file off; '.txt' is not part of the name
                stem = clean[:-4] if clean.lower().endswith(".txt") else clean
                if stem in self.cheats:
                    continue
                self.cheats[stem] = {
                    "enabled": enabled,
                    "path": os.path.join(self.cheats_path, fname),
                    "raw_name": fname,
                }

        # find patches, plugins and conflicts
        for clean, mod in self.mods.items():
            self._scan_mod_contents(clean, mod)

        # port-side native code, kept out of mods/
        self._scan_engine_modules()

        # real conflicts only
        file_to_mods = {}
        for clean, mod in self.mods.items():
            for rel_lower, (rel_orig, abspath) in mod.get("files", {}).items():
                file_to_mods.setdefault(rel_lower, []).append(
                    (clean, rel_orig, abspath))

        for rel_lower, entries in file_to_mods.items():
            if len(entries) < 2:
                continue
            is_arc = rel_lower.endswith(".arc")
            for i in range(len(entries)):
                for j in range(i + 1, len(entries)):
                    kind, example, detail = self._pair_conflict(
                        entries[i], entries[j], rel_lower, is_arc)
                    if kind == "conflict":
                        a, b = entries[i][0], entries[j][0]
                        self.conflicts.setdefault(a, {}).setdefault(
                            rel_lower, []).append(b)
                        self.conflicts.setdefault(b, {}).setdefault(
                            rel_lower, []).append(a)
                        self.conflict_examples.setdefault(a, {})[rel_lower] = example
                        self.conflict_examples.setdefault(b, {})[rel_lower] = example
                        for key in detail:
                            self._add_entry_clash(a, b, rel_lower, key)
                            self._add_entry_clash(b, a, rel_lower, key)
                    elif kind == "merged":
                        a, b = entries[i][0], entries[j][0]
                        self.mergeable_arcs.setdefault(a, {}).setdefault(
                            rel_lower, []).append(b)
                        self.mergeable_arcs.setdefault(b, {}).setdefault(
                            rel_lower, []).append(a)

    # load order

    def _read_load_order(self, raw_entries):
        """Read mods/load_order.txt."""
        ordered, off = [], set()
        if not os.path.isfile(self.load_order_path):
            return ordered, off, False, False
        try:
            with open(self.load_order_path, "r", encoding="utf-8",
                      errors="ignore") as f:
                lines = f.readlines()
        except OSError:
            return ordered, off, False, False
        names = {raw for raw, _, _ in raw_entries}
        ours = False
        for ln, line in enumerate(lines):
            s = line.strip()
            if not ln and s.startswith(self.LOAD_ORDER_MARK):
                ours = True
            if ours and s.startswith("# off: "):
                off.add(s[7:].strip())
                continue
            if not s or s.startswith("#"):
                continue
            if s in names and s not in ordered:
                ordered.append(s)
        return ordered, off, True, ours

    def _write_load_order(self, enabled_raw, disabled_raw, progress_queue):
        """Write mods/load_order.txt."""
        try:
            lines = [
                self.LOAD_ORDER_MARK
                + " of the settings menu (also fine to edit by hand).",
                "# One mod folder per line, first to last: "
                "a file in a later mod wins.",
                "# A folder added later, that is neither listed nor marked "
                "off, loads after the listed ones.",
            ]
            lines += enabled_raw
            lines += [f"# off: {name}" for name in disabled_raw]
            atomic_write_text(self.load_order_path,
                              "\n".join(lines) + "\n", newline=None)
        except Exception as e:
            progress_queue.put({"type": "error",
                                "message": "Could not write mods/load_order.txt.\n\n"
                                           f"{e}"})
            return False
        progress_queue.put({"type": "status",
                            "text": f"load_order.txt: {len(enabled_raw)} on, "
                                    f"{len(disabled_raw)} off."})
        return True

    # engine modules

    @staticmethod
    def _module_name_ok(name):
        # the loader's rule: letters, digits, '-', '_', '.', no leading dot
        if not name or name.startswith("."):
            return False
        return all(c.isascii() and (c.isalnum() or c in "-_.")
                   for c in name)

    @staticmethod
    def _module_binary(folder, name):
        for ext in RecompAnalyzer.MODULE_EXTS:
            path = os.path.join(folder, name + ext)
            if os.path.isfile(path):
                return path
        return None

    def _read_engine_modules_list(self):
        # folder names enabled.txt lists, in file order
        try:
            with open(self.engine_modules_list_path, "r", encoding="utf-8",
                      errors="ignore") as f:
                lines = f.read().splitlines()
        except OSError:
            return []
        names = []
        seen = set()
        for line in lines:
            s = line.strip().lstrip("\ufeff").strip()
            if not s or s.startswith("#") or s in seen:
                continue
            seen.add(s)
            names.append(s)
        return names

    def _scan_engine_modules(self):
        # engine_modules/<name>/<name>.dll, loaded only when listed
        if not os.path.isdir(self.engine_modules_path):
            return
        try:
            entries = os.listdir(self.engine_modules_path)
        except OSError:
            return
        listed = self._read_engine_modules_list()
        self.module_order = list(listed)   # enabled.txt order is load order
        enabled = set(listed)
        for raw in sorted(entries, key=str.lower):
            full = os.path.join(self.engine_modules_path, raw)
            if not os.path.isdir(full) or not self._module_name_ok(raw):
                continue
            self.modules[raw] = {
                "enabled": raw in enabled,
                "path": full,
                "binary": self._module_binary(full, raw),
            }

    def _write_engine_modules_list(self, enabled):
        # write engine_modules/enabled.txt
        off = [name for name in sorted(self.modules, key=str.lower)
               if name not in enabled]
        lines = [
            self.LOAD_ORDER_MARK + " of dreamSort (also fine to edit by hand).",
            "# One engine module folder per line, first to last: the recomp "
            "loads the listed ones only.",
            "# Order is load order, so earlier modules load first.",
            "# An 'off:' line is installed but not loaded.",
        ]
        lines += list(enabled)
        lines += [f"# off: {name}" for name in off]
        atomic_write_text(self.engine_modules_list_path,
                          "\n".join(lines) + "\n", newline=None)

    def _apply_engine_modules(self, module_states, progress_queue):
        if not self.modules and not os.path.isfile(
                self.engine_modules_list_path):
            return True  # none installed and nothing listed: leave it alone
        progress_queue.put({"type": "status",
                            "text": "Phase 5: Writing engine_modules/enabled.txt..."})
        wanted = {name for name, on in module_states.items()
                  if on and name in self.modules}
        # keep the order that is already in the file, append new ones at the end
        enabled = [name for name in self.module_order if name in wanted]
        enabled += sorted((name for name in wanted
                           if name not in self.module_order), key=str.lower)
        try:
            os.makedirs(self.engine_modules_path, exist_ok=True)
            self._write_engine_modules_list(enabled)
        except Exception as e:
            progress_queue.put({
                "type": "error",
                "message": "Could not write "
                           f"engine_modules/enabled.txt.\n\n{e}"})
            return False
        progress_queue.put({"type": "status",
                            "text": f"engine_modules/enabled.txt: "
                                    f"{len(enabled)} on, "
                                    f"{len(self.modules) - len(enabled)} off."})
        return True

    # conflicts

    def _pair_conflict(self, a, b, rel_lower, is_arc):
        """Classify a shared file."""
        _ca, rel_orig_a, path_a = a
        _cb, rel_orig_b, path_b = b
        if not is_arc:
            if self._files_same(path_a, path_b):
                return "same", "", ()
            return "conflict", rel_orig_a, (None,)
        orig = self._game_arc_path(rel_lower)
        count, first, entries = self._arc_overlap(orig, path_a, path_b)
        if count is None:
            # not a parseable archive
            if self._files_same(path_a, path_b):
                return "same", "", ()
            return "conflict", f"{rel_orig_a} (archive not parseable)", (None,)
        if count == 0:
            return "merged", f"{rel_orig_a} (merged entry-by-entry)", ()
        note = (f"{first} in {rel_orig_a}" if first else rel_orig_a)
        return "conflict", note, tuple(sorted(set(entries)))

    def _add_entry_clash(self, mod, other, rel_lower, key):
        """Note a differing entry."""
        per_file = self.conflict_entries.setdefault(mod, {}) \
            .setdefault(rel_lower, {})
        rivals = per_file.setdefault(key, [])
        if other not in rivals:
            rivals.append(other)

    def conflict_view(self, is_enabled=None):
        """Conflict map for the ui."""
        if is_enabled is None:
            def is_enabled(_name):
                return True
        view = {}
        for mod, files in self.conflicts.items():
            entry_map = self.conflict_entries.get(mod, {})
            for rel, rivals in files.items():
                keep = [r for r in rivals if r != mod and is_enabled(r)]
                if not keep:
                    continue
                cell = view.setdefault(mod, {}).setdefault(rel, {})
                cell["rivals"] = keep
                cell["entries"] = {
                    key: [r for r in vals
                          if r != mod and is_enabled(r) and r in keep]
                    for key, vals in entry_map.get(rel, {}).items()
                }
        return view

    @staticmethod
    def latest_mod(mods, order_index):
        """Which mod wins a shared file."""
        return max(mods, key=lambda name: order_index.get(name, 10_000))

    @classmethod
    def win_state(cls, mod, view, order_index):
        """Winner or loser for one mod."""
        mine = order_index.get(mod, 10_000)
        loses = wins = False
        for _rel, cell in view.get(mod, {}).items():
            for other in cell.get("rivals", ()):
                if order_index.get(other, 10_000) > mine:
                    loses = True
                else:
                    wins = True
        if loses:
            return "loser"
        if wins:
            return "winner"
        return "none"

    def _game_arc_path(self, rel_lower):
        """The game's own copy of an archive."""
        for base in (os.path.join(self.root_path, "data", "romfs"),
                     os.path.join(self.root_path, "romfs")):
            if not os.path.isdir(base):
                continue
            cur = base
            ok = True
            for part in rel_lower.split("/"):
                if not part:
                    continue
                try:
                    names = os.listdir(cur)
                except OSError:
                    ok = False
                    break
                match = next((n for n in names if n.lower() == part), None)
                if match is None:
                    ok = False
                    break
                cur = os.path.join(cur, match)
            if ok and os.path.isfile(cur):
                return cur
        return None

    @staticmethod
    def _files_same(path_a, path_b):
        try:
            if os.path.getsize(path_a) != os.path.getsize(path_b):
                return False
        except OSError:
            return False
        try:
            with open(path_a, "rb") as fa, open(path_b, "rb") as fb:
                while True:
                    ca = fa.read(65536)
                    if ca != fb.read(65536):
                        return False
                    if not ca:
                        return True
        except OSError:
            return False

    def _arc_entries(self, path):
        # from arcmerg.c
        if path is None:
            return None
        cached = self._arc_cache.get(path)
        if cached is not None:
            return cached
        entries = None
        try:
            with open(path, "rb") as f:
                head = f.read(12)
                if len(head) < 12 or head[:4] != b"ARC\x00":
                    entries = None
                else:
                    f.seek(0, 2)
                    total = f.tell()
                    f.seek(12)
                    version = head[4] | head[5] << 8
                    n = head[6] | head[7] << 8
                    if 12 + n * 80 > total:
                        entries = None
                    else:
                        table = f.read(n * 80)
                        if len(table) != n * 80:
                            entries = None
                        else:
                            out = []
                            ok = True
                            for i in range(n):
                                e = table[i * 80:(i + 1) * 80]
                                name = e[:64].split(b"\x00", 1)[0] \
                                    .decode("latin-1")
                                typ = int.from_bytes(e[64:68], "little")
                                csize = int.from_bytes(e[68:72], "little")
                                sf = int.from_bytes(e[72:76], "little")
                                off = int.from_bytes(e[76:80], "little")
                                if off + csize > total:
                                    ok = False
                                    break
                                out.append((name, typ, csize, sf, off))
                            entries = (version, out) if ok else None
        except OSError:
            entries = None
        self._arc_cache[path] = entries
        return entries

    @staticmethod
    def _arc_blob(path, off, size):
        try:
            with open(path, "rb") as f:
                f.seek(off)
                return f.read(size)
        except OSError:
            return b""

    def _arc_digest(self, path, off, size):
        """Digest of one entry."""
        if path is None or size <= 0:
            return b""
        table = self._arc_digest_cache.setdefault(path, {})
        digest = table.get(off)
        if digest is None:
            digest = hashlib.blake2b(self._arc_blob(path, off, size),
                                     digest_size=16).digest()
            table[off] = digest
        return digest

    def _arc_same_entries(self, file_a, file_b, ea, eb):
        """Compare two entries."""
        if ea[1] != eb[1] or ea[2] != eb[2] or ea[3] != eb[3]:
            return False
        return (self._arc_digest(file_a, ea[4], ea[2]) ==
                self._arc_digest(file_b, eb[4], eb[2]))

    def _arc_overlap(self, orig, path_a, path_b):
        """Count entries both mods changed."""
        x = self._arc_entries(path_a)
        y = self._arc_entries(path_b)
        if x is None or y is None or x[0] != y[0]:
            return None, None, ()
        o = self._arc_entries(orig) if orig else None
        if o is not None and o[0] != x[0]:
            return None, None, ()
        ykey = {(ent[0], ent[1]): ent for ent in y[1]}
        okey = {(ent[0], ent[1]): ent for ent in o[1]} if o else {}
        count, first, entries = 0, None, []
        for ent in x[1]:
            other = ykey.get((ent[0], ent[1]))
            if other is None:
                continue  # other mod does not touch it
            base = okey.get((ent[0], ent[1]))
            if base is not None and (
                    self._arc_same_entries(path_a, orig, ent, base) or
                    self._arc_same_entries(path_b, orig, other, base)):
                continue  # one side left it alone
            if self._arc_same_entries(path_a, path_b, ent, other):
                continue  # both changed it the same
            if count == 0:
                first = ent[0]
            count += 1
            entries.append((ent[0], ent[1]))
        return count, first, entries

    def _scan_mod_contents(self, mod_name, mod):
        """Scan a mod."""
        mod_path = mod["path"]
        enabled = mod["enabled"]
        romfs_root = self._romfs_root(mod_path)

        patch_entries = []
        plugin_entries = []
        conflict_files = {}

        exefs_dir = self._find_dir(mod_path, "exefs", 3)
        plugins_dir = self._find_plugins_dir(romfs_root)

        def under_scan_dir(scan_dir, root_abs):
            """True for the scan dir or its disabled/."""
            if not scan_dir:
                return False
            scan_abs = os.path.normcase(os.path.abspath(scan_dir))
            if root_abs == scan_abs:
                return True
            disabled_abs = os.path.normcase(os.path.abspath(
                os.path.join(scan_dir, "disabled")))
            return root_abs == disabled_abs

        for root, _dirs, files in os.walk(mod_path):
            root_abs = os.path.normcase(os.path.abspath(root))
            for filename in files:
                lower_name = filename.lower()
                is_patch = lower_name.endswith((".pchtxt", ".ips"))
                is_plugin = lower_name.endswith(".nro")
                if not (is_patch or is_plugin):
                    continue
                if not enabled:
                    continue
                full_path = os.path.join(root, filename)
                scan_dir = exefs_dir if is_patch else plugins_dir
                ignored = not under_scan_dir(scan_dir, root_abs)
                in_disabled = os.path.basename(root).lower() == "disabled"
                is_file_enabled = not in_disabled
                clean_filename = (filename[1:]
                                  if filename.startswith("_")
                                  else filename)
                if ignored:
                    rel_dir = os.path.relpath(root, mod_path)
                    rel_path = (clean_filename if rel_dir == "."
                                else os.path.normpath(
                                    os.path.join(rel_dir, clean_filename)))
                else:
                    rel_path = clean_filename
                entry = {
                    "mod": mod_name,
                    "filename": clean_filename,
                    "path": full_path,
                    "enabled": is_file_enabled,
                    "rel_path": rel_path,
                    "ignored_by_recomp": ignored,
                    "scan_dir": scan_dir,
                }
                if is_patch:
                    patch_entries.append(entry)
                else:
                    entry["ini_files"] = self._find_nearby_ini(root)
                    entry["manifest"] = self._nearest_manifest(root, mod_path)
                    plugin_entries.append(entry)

        # romfs files
        has_arc = False
        non_plugin_romfs = False
        if romfs_root:
            plugins_abs = (os.path.normcase(os.path.abspath(plugins_dir))
                           if plugins_dir else None)
            for root, _dirs, files in os.walk(romfs_root):
                root_abs = os.path.normcase(os.path.abspath(root))
                in_plugins = (plugins_abs is not None
                              and (root_abs == plugins_abs
                                   or root_abs.startswith(plugins_abs + os.sep)))
                for filename in files:
                    if filename.startswith("."):
                        continue
                    full = os.path.join(root, filename)
                    if filename.lower().endswith(".arc"):
                        has_arc = True
                    if not in_plugins:
                        non_plugin_romfs = True
                    rel = os.path.relpath(full, romfs_root) \
                        .replace("\\", "/")
                    conflict_files[rel.lower()] = (rel, full)

        # has_nro
        has_nro = any(
            p["mod"] == mod_name
            and p["enabled"]
            and not p.get("ignored_by_recomp")
            for p in plugin_entries
        )

        mod.update({
            "has_romfs": non_plugin_romfs,
            "has_exefs": bool(exefs_dir),
            "has_plugins": bool(plugins_dir),
            "has_nro": has_nro,
            "is_pure_plugin": has_nro and not non_plugin_romfs,
            "has_arc": has_arc,
            "files": conflict_files,
        })
        self.patches.extend(patch_entries)
        self.plugins.extend(plugin_entries)

    @staticmethod
    def _find_dir(root, want, depth):
        """Shallowest folder named want."""
        from collections import deque
        queue = deque([(root, 0)])
        while queue:
            cur, level = queue.popleft()
            try:
                entries = os.listdir(cur)
            except OSError:
                continue
            for name in entries:
                p = os.path.join(cur, name)
                if not os.path.isdir(p):
                    continue
                if name.lower() == want:
                    return p
                if level < depth:
                    queue.append((p, level + 1))
        return None
    
    def _romfs_root(self, mod_path):
        romfs = self._find_dir(mod_path, "romfs", 3)
        if romfs:
            return romfs
        nativenx = self._find_dir(mod_path, "nativenx", 3)
        if nativenx:
            return os.path.dirname(nativenx)
        return None
    
    @staticmethod
    def _find_plugins_dir(romfs_root):
        """Plugin .nro files for a mod."""
        if not romfs_root:
            return None
        try:
            names = os.listdir(romfs_root)
        except OSError:
            return None
        nativenx = next((n for n in names
                         if n.lower() == "nativenx"
                         and os.path.isdir(os.path.join(romfs_root, n))),
                        None)
        if not nativenx:
            return None
        nativenx_path = os.path.join(romfs_root, nativenx)
        try:
            subnames = os.listdir(nativenx_path)
        except OSError:
            return None
        plugins = next((n for n in subnames
                        if n.lower() == "plugins"
                        and os.path.isdir(os.path.join(nativenx_path, n))),
                       None)
        return os.path.join(nativenx_path, plugins) if plugins else None

    @staticmethod
    def _nearest_manifest(start, stop):
        # manifests sit at or above the .nro, never beyond its mod folder;
        # one beside several plugins speaks for the folder, not for each file
        base = os.path.normcase(os.path.abspath(stop))
        node = os.path.abspath(start)
        first = True
        while True:
            shared = first and RecompAnalyzer._nro_count(node) > 1
            if not shared:
                data, _notes = read_manifest(node)
                if data is not None:
                    return data
            parent = os.path.dirname(node)
            if os.path.normcase(node) == base or parent == node:
                return None
            node = parent
            first = False

    @staticmethod
    def _nro_count(folder):
        try:
            return sum(1 for name in os.listdir(folder)
                       if name.lower().endswith(".nro"))
        except OSError:
            return 1

    @staticmethod
    def _find_nearby_ini(directory):
        try:
            return [
                os.path.join(directory, name)
                for name in os.listdir(directory)
                if name.lower().endswith(".ini")
            ]
        except OSError:
            return []

    # ordering

    def get_ordered_mods(self):
        # enabled first, then disabled
        enabled = sorted(
            [(n, d) for n, d in self.mods.items() if d["enabled"]],
            key=lambda x: x[1]["order"]
        )
        disabled = sorted(
            [(n, d) for n, d in self.mods.items() if not d["enabled"]],
            key=lambda x: x[0].lower()
        )
        return enabled + disabled

    def get_current_mod_path(self, clean_name):
        for base in (self.mods_path, self.disabled_mods_path):
            if not os.path.isdir(base):
                continue
            for raw in os.listdir(base):
                if self._strip_number_prefix(raw) == clean_name:
                    return os.path.join(base, raw)
        return None

    # apply

    def apply_changes_threaded(self, ordered_mod_names, mod_enabled_map,
                                cheat_states, patch_states, plugin_states,
                                progress_queue, module_states=None):
        module_states = module_states or {}
        if not self.root_path:
            progress_queue.put({"type": "error",
                                "message": "Recomp root not set."})
            return

        try:
            os.makedirs(self.mods_path, exist_ok=True)
        except Exception as e:
            progress_queue.put({"type": "error",
                                "message": f"Cannot create mod folders: {e}"})
            return

        # phase 1: mods_disabled
        progress_queue.put({"type": "status",
                            "text": "Phase 1: Migrating legacy mods_disabled/..."})
        if os.path.isdir(self.disabled_mods_path):
            try:
                existing = {raw.lower(): raw for raw in os.listdir(self.mods_path)}
                moved = 0
                for raw in sorted(os.listdir(self.disabled_mods_path)):
                    src = os.path.join(self.disabled_mods_path, raw)
                    if not os.path.isdir(src):
                        continue
                    if raw.lower() in existing:
                        progress_queue.put({
                            "type": "status",
                            "text": f"Kept '{raw}' in mods_disabled/ (name clash)."})
                        continue
                    shutil.move(src, os.path.join(self.mods_path, raw))
                    existing[raw.lower()] = raw
                    moved += 1
                try:
                    os.rmdir(self.disabled_mods_path)
                except OSError:
                    pass
                if moved:
                    progress_queue.put({"type": "status",
                                        "text": f"Migrated {moved} mod(s) back into mods/."})
            except Exception as e:
                progress_queue.put({"type": "error",
                                    "message": f"Failed to migrate mods_disabled/: {e}"})
                return

        # phase 2: load_order.txt
        progress_queue.put({"type": "status",
                            "text": "Phase 2: Writing mods/load_order.txt..."})
        try:
            raw_by_clean = {
                self._strip_number_prefix(d): d
                for d in os.listdir(self.mods_path)
                if os.path.isdir(os.path.join(self.mods_path, d))
            }
        except OSError as e:
            progress_queue.put({"type": "error",
                                "message": f"Cannot list mods/: {e}"})
            return

        enabled_raw, disabled_raw = [], []
        for raw_name in ordered_mod_names:
            clean = self._strip_number_prefix(raw_name)
            raw = raw_by_clean.get(clean, raw_name)
            on = mod_enabled_map.get(raw_name, mod_enabled_map.get(clean, True))
            (enabled_raw if on else disabled_raw).append(raw)
        # mods not in the list
        listed_cleans = {self._strip_number_prefix(e)
                         for e in enabled_raw + disabled_raw}
        for raw in sorted(raw_by_clean, key=str.lower):
            clean = self._strip_number_prefix(raw)
            if clean in listed_cleans:
                continue
            enabled_raw.append(raw)
        if not self._write_load_order(enabled_raw, disabled_raw, progress_queue):
            return

        # refresh state
        self.scan()

        # phase 3: cheats
        progress_queue.put({"type": "status",
                            "text": "Phase 3: Applying cheat selections..."})
        if not self._apply_cheats(cheat_states, progress_queue):
            return

        # phase 4: patches and plugins
        progress_queue.put({"type": "status",
                            "text": "Phase 4: Applying patch/plugin selections..."})
        if not self._apply_patches_plugins(patch_states, plugin_states,
                                          progress_queue):
            return

        # phase 5: engine modules
        if not self._apply_engine_modules(module_states, progress_queue):
            return

        progress_queue.put({"type": "progress", "value": 1.0, "text": "Done."})
        progress_queue.put({"type": "done"})

    def _apply_cheats(self, cheat_states, progress_queue):
        if not os.path.isdir(self.cheats_path):
            return True
        try:
            entries = os.listdir(self.cheats_path)
        except OSError as exc:
            progress_queue.put({"type": "error", "message": f"Cannot read cheats folder: {exc}"})
            return False

        current = {}
        for fname in entries:
            if not fname.lower().endswith(".txt"):
                continue
            clean = fname[1:] if fname.startswith("_") else fname
            stem = clean[:-4] if clean.lower().endswith(".txt") else clean
            current[stem] = (not fname.startswith("_"), fname)
        for clean, should_enable in cheat_states.items():
            if clean not in current:
                continue
            is_enabled, filename = current[clean]
            path = os.path.join(self.cheats_path, filename)
            if is_enabled != should_enable and not rename_prefixed_file(
                path, should_enable, "cheat", progress_queue, filename
            ):
                return False
        return True

    def _apply_patches_plugins(self, patch_states, plugin_states, progress_queue):
        """Toggle patches and plugins."""
        for entries, states, label in ((self.patches, patch_states, "patch"),
                                       (self.plugins, plugin_states, "plugin")):
            for entry in entries:
                key = (entry["mod"], entry["rel_path"])
                if key not in states:
                    continue
                want = states[key]
                if entry.get("ignored_by_recomp"):
                    continue  # nothing to toggle
                if entry["enabled"] == want:
                    continue
                scan_dir = entry.get("scan_dir")
                if not scan_dir or not os.path.isdir(scan_dir):
                    progress_queue.put({
                        "type": "error",
                        "message": f"Missing scan dir for {entry['filename']}."})
                    return False
                src = entry["path"]
                dst = (os.path.join(scan_dir, entry["filename"])
                       if want else
                       os.path.join(scan_dir, "disabled", entry["filename"]))
                try:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    if os.path.normcase(src) != os.path.normcase(dst):
                        if os.path.exists(dst):
                            os.remove(dst)
                        shutil.move(src, dst)
                except Exception as e:
                    progress_queue.put({
                        "type": "error",
                        "message": f"Could not {'enable' if want else 'disable'} "
                                   f"{label} '{entry['filename']}': {e}"})
                    return False
                progress_queue.put({"type": "status",
                                    "text": f"{label.title()} '{entry['filename']}' "
                                            f"{'enabled' if want else 'disabled'}."})
        return True

