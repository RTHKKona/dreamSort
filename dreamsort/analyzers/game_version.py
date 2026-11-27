# mhgu title version, read off the install the emulator loads

import os
import re
import struct

TITLE_ID = "0100770008DD8000"
TITLE_PREFIX = "0100770008DD"
EXPECTED = "1.4.0"
# first 8 bytes of the 1.4.0 main build id, the same value cheats are keyed by
EXPECTED_BUILD_ID = "FB08F1D20FD1204F"
# 1.4.0 as a packed switch title version
EXPECTED_TITLE_VERSION = 0x10400

NAMES = {"ryujinx": "Ryujinx", "eden": "Eden"}

# container names carry the title version as [v65536]
_V_TAG = re.compile(r"\[v(\d{4,9})\]", re.I)
_TID_IN_NAME = re.compile(r"(0100770008dd[0-9a-f]{4})", re.I)
_CONTAINER_EXTS = (".nsp", ".xci")
# nso0 header, build id sits right after the flags block
_BUILD_AT = 0x40
_BUILD_LEN = 8
# cnmt: title id, title version, type
_CNMT_SIZE = 0x20
_CNMT_FMT = "<QI B"
# eden keeps its title records under both nand trees
_NAND = ("user", "system")


class GameReport:
    # what was read, where from, and whether it matches 1.4.0

    def __init__(self, kind, version, source, verdict, build_id=""):
        self.kind = kind
        self.name = NAMES.get(kind, "Emulator")
        self.version = version
        self.source = source
        self.verdict = verdict
        self.build_id = build_id

    def line(self):
        # status bar summary
        if not self.version:
            return "MHGU version unknown"
        return "MHGU %s" % self.version

    def message(self):
        # banner text, empty when there is nothing to warn about
        if self.verdict != "old":
            return ""
        if self.version:
            head = "MHGU %s is installed" % self.version
        else:
            head = "This install is not the MHGU %s build" % EXPECTED
        return ("%s. Mods and cheats written for %s will not line up, so "
                "update the game to %s in %s." % (head, EXPECTED, EXPECTED,
                                                  self.name))

    def tooltip(self):
        bits = []
        if self.source:
            bits.append("Version read from %s." % self.source)
        if self.build_id:
            bits.append("main build id %s." % self.build_id)
        bits.append("%s main build id starts with %s."
                    % (EXPECTED, EXPECTED_BUILD_ID))
        return "\n".join(bits)


def _title_version(value):
    # switch packs major, minor and patch into one number
    return "%d.%d.%d" % ((value >> 16) & 0xFFFF, (value >> 8) & 0xFF, value & 0xFF)


def _build_id(exefs):
    # build id of an nso main, empty when the header is not there
    for name in ("main", "main.nso"):
        path = os.path.join(exefs, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as handle:
                head = handle.read(_BUILD_AT + _BUILD_LEN)
        except OSError:
            continue
        if len(head) < _BUILD_AT + _BUILD_LEN or head[:4] != b"NSO0":
            continue
        return head[_BUILD_AT:_BUILD_AT + _BUILD_LEN].hex().upper()
    return ""


def _cnmt_version(registered):
    # eden writes plaintext cnmt records next to the installed content
    folder = os.path.join(registered, "yuzu_meta")
    best = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    for name in names:
        if not name.lower().endswith(".cnmt"):
            continue
        try:
            with open(os.path.join(folder, name), "rb") as handle:
                head = handle.read(_CNMT_SIZE)
        except OSError:
            continue
        if len(head) < _CNMT_SIZE:
            continue
        title_id, version, _kind = struct.unpack_from(_CNMT_FMT, head, 0)
        if ("%016X" % title_id).startswith(TITLE_PREFIX):
            best = max(best, version)
    return best


def _shallow_files(folder):
    # the folder plus one level under it, updates can sit in a subfolder
    try:
        entries = os.listdir(folder)
    except OSError:
        return
    for name in entries:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            yield path
            continue
        if not os.path.isdir(path):
            continue
        try:
            inner = os.listdir(path)
        except OSError:
            continue
        for child in inner:
            child_path = os.path.join(path, child)
            if os.path.isfile(child_path):
                yield child_path


def _containers(folder):
    # (highest version tag, update container present)
    version = 0
    update = False
    for path in _shallow_files(folder):
        if os.path.splitext(path)[1].lower() not in _CONTAINER_EXTS:
            continue
        name = os.path.basename(path)
        match = _V_TAG.search(name)
        if match:
            version = max(version, int(match.group(1)))
        title = _TID_IN_NAME.search(name)
        if title and title.group(1).upper() != TITLE_ID:
            update = True
    return version, update


def _game_dirs(kind, mods_path):
    # folders holding the game itself, empty when the layout is not standard
    path = os.path.normpath(mods_path) if mods_path else ""
    if not path:
        return []
    if kind == "eden":
        root = os.path.dirname(os.path.dirname(path))
        return [os.path.join(root, "nand", folder, "Contents", "registered")
                for folder in _NAND]
    parts = path.split(os.sep)
    if len(parts) < 4 or parts[-2].lower() != "contents" \
            or parts[-3].lower() != "mods":
        return []
    root = os.sep.join(parts[:-3])
    games = os.path.join(root, "games")
    dirs = [os.path.join(games, parts[-1])]
    try:
        names = os.listdir(games)
    except OSError:
        return dirs
    # update content is installed under its own title id folder
    for name in names:
        if name.upper() == parts[-1].upper():
            continue
        if name.upper().startswith(TITLE_PREFIX):
            dirs.append(os.path.join(games, name))
    return dirs


def detect(kind, mods_path):
    # (version, source, verdict); silence is better than a false alarm
    dirs = [path for path in _game_dirs(kind, mods_path)
            if os.path.isdir(path)]
    if not dirs:
        return GameReport(kind, "", "", "unknown")
    build_id = ""
    for path in dirs:
        build_id = build_id or _build_id(os.path.join(path, "exefs"))
    if build_id == EXPECTED_BUILD_ID:
        return GameReport(kind, EXPECTED, "the exefs main build id", "ok",
                          build_id)
    version, source = 0, ""
    for path in dirs:
        value = _cnmt_version(path)
        if value:
            version, source = value, "the cnmt record Eden keeps"
            break
    if not version:
        for path in dirs:
            value, _update = _containers(path)
            if value:
                version, source = value, "an update container name"
                break
    if version:
        verdict = "ok" if version >= EXPECTED_TITLE_VERSION else "old"
        return GameReport(kind, _title_version(version), source, verdict,
                          build_id)
    if build_id:
        # an old extracted main with an untagged update on top reads the same
        # as a base-only install, so only the latter is worth a warning
        if any(_containers(path)[1] for path in dirs):
            return GameReport(kind, "", "an update dreamSort cannot version",
                              "unverified", build_id)
        return GameReport(kind, "", "the exefs main build id", "old", build_id)
    return GameReport(kind, "", "", "unknown")


def report(kind, mods_path):
    # never raises, a broken guess must not take the window down
    try:
        return detect(kind, mods_path)
    except Exception:
        return GameReport(kind, "", "", "unknown")
