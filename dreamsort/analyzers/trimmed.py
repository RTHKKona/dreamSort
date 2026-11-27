# trimmed-arc detection for emulator installs
#
# arcBarber writes a "partial" .arc: same header as the game's, far fewer
# entries, so it only works where the loader merges it into the original
# (the recomp). Ryujinx and Eden replace the file outright, so the entries
# that were left out read as missing.

import io
import os
import struct
import zipfile

try:
    import py7zr
except ImportError:  # optional backend, same as the installer
    py7zr = None

HEAD, ENTRY = 12, 80
ROMFS_HEADS = ("romfs", "romfslite", "romfs_ext")
MAX_TABLE_BYTES = 0xFFFF * ENTRY     # the header's count field is 16 bits
MAX_7Z_BYTES = 8 * 1024 * 1024       # a trimmed arc is small by nature
SUSPECT_ENTRIES = 3                  # no original to compare: only tiny is sure of nothing
MAX_HITS = 40

SKIP_DIRS = {"__macosx", ".git", "node_modules"}


def _read_table(handle):
    # version, entry count, (name, type) pairs - the header only
    head = handle.read(HEAD)
    if len(head) < HEAD or head[:4] != b"ARC\0":
        return None
    version, count = struct.unpack_from("<HH", head, 4)
    table = handle.read(count * ENTRY)
    if len(table) < count * ENTRY:
        return None
    names = set()
    for index in range(count):
        base = index * ENTRY
        raw = table[base:base + 64].split(b"\0", 1)[0]
        names.add((raw.decode("latin-1", "replace"),
                   struct.unpack_from("<I", table, base + 64)[0]))
    return version, count, names


def _table_from_path(path):
    try:
        with open(path, "rb") as handle:
            return _read_table(handle)
    except OSError:
        return None


def _table_from_bytes(data):
    return _read_table(io.BytesIO(data[:HEAD + MAX_TABLE_BYTES]))


def _romfs_rel(member):
    # where the file sits inside a romfs, "romfs/arc/x.arc" -> "arc/x.arc"
    parts = [p for p in str(member).replace("\\", "/").split("/") if p]
    for index, part in enumerate(parts[:-1]):
        if part.lower() in ROMFS_HEADS:
            return "/".join(parts[index + 1:])
    if parts and parts[0].lower() == "nativenx":
        # a bare nativeNX/ folder is romfs/nativeNX/ (same as the recomp reads)
        return "/".join(parts)
    return None


def _reference(rel, root):
    # the game's own copy of that archive, if we have a dump to look in
    if not rel or not root:
        return None
    normalised = rel.replace("/", os.sep)
    for base in (os.path.join(root, "data", "romfs"), os.path.join(root, "romfs"),
                 root, os.path.join(root, "data")):
        candidate = os.path.join(base, normalised)
        if os.path.isfile(candidate):
            return candidate
    return None


def _judge(version, count, names, reference_root, rel):
    # "trimmed" is what arcmerge.h calls partial: shares entries with the
    # game's archive and lacks the rest
    reference = _reference(rel, reference_root)
    if reference:
        original = _table_from_path(reference)
        if original and original[0] == version:
            shared = len(names & original[2])
            lacks = len(original[2] - names)
            return ("trimmed" if shared and lacks else None), True
    if count <= SUSPECT_ENTRIES:
        return "suspect", False
    return None, False


def _add(hits, where, version, count, names, reference_root, rel):
    if len(hits) >= MAX_HITS:
        return
    verdict, compared = _judge(version, count, names, reference_root, rel)
    if not verdict:
        return
    hits.append({"where": where, "entries": count, "kind": verdict,
                 "compared": compared})


def _scan_file(path, label, reference_root, hits):
    rel = _romfs_rel(label)
    if rel is None or not str(label).lower().endswith(".arc"):
        return
    table = _table_from_path(path)
    if table:
        _add(hits, label, table[0], table[1], table[2], reference_root, rel)


def _scan_dir(path, reference_root, hits):
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and d.lower() not in SKIP_DIRS]
        for name in files:
            if not name.lower().endswith(".arc"):
                continue
            full = os.path.join(root, name)
            _scan_file(full, os.path.relpath(full, path), reference_root, hits)


def _scan_zip(path, reference_root, hits):
    try:
        archive = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError):
        return
    with archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".arc"):
                continue
            rel = _romfs_rel(info.filename)
            if rel is None:
                continue
            try:
                with archive.open(info) as handle:
                    table = _read_table(handle)
            except Exception:  # encrypted or damaged member
                table = None
            if table:
                _add(hits, info.filename, table[0], table[1], table[2],
                     reference_root, rel)


def _scan_7z(path, reference_root, hits):
    if py7zr is None:
        return
    try:
        with py7zr.SevenZipFile(path, mode="r") as archive:
            wanted = []
            for info in archive.list():
                if getattr(info, "is_directory", False):
                    continue
                if not info.filename.lower().endswith(".arc"):
                    continue
                if _romfs_rel(info.filename) is None:
                    continue
                if getattr(info, "uncompressed", 0) > MAX_7Z_BYTES:
                    continue        # a real archive, never a partial
                wanted.append(info.filename)
            if not wanted:
                return
            try:
                archive.reset()
            except Exception:
                pass
            members = archive.read(targets=wanted) or {}
            for name, buffer in members.items():
                try:
                    data = buffer.read()
                except Exception:
                    continue
                table = _table_from_bytes(data)
                if table:
                    _add(hits, name, table[0], table[1], table[2],
                         reference_root, _romfs_rel(name))
    except Exception:  # bad header, unsupported filter
        return


def scan_paths(items, reference_root=None):
    """The .arc files in the items about to be installed that are trimmed."""
    hits = []
    for item in items or []:
        path = str(item or "").strip().strip('"')
        if not path or not os.path.exists(path):
            continue
        if os.path.isdir(path):
            _scan_dir(path, reference_root, hits)
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext == ".zip":
            _scan_zip(path, reference_root, hits)
        elif ext == ".7z":
            _scan_7z(path, reference_root, hits)
    return hits
