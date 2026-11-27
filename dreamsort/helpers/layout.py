# layout sniffing

import os
import re

EMULATOR_MARKERS = {"romfs", "exefs"}
RECOMP_MARKERS = {"nativnx", "arc", "scenes"}
CHEAT_MARKERS = {"cheats"}

SKIP_NAMES = {"__macosx", ".ds_store", "thumbs.db"}

ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _top_entries(path):
    # visible top level, noise dropped
    try:
        names = os.listdir(path)
    except OSError:
        return [], []
    dirs, files = [], []
    for name in names:
        if name.lower() in SKIP_NAMES or name.startswith("."):
            continue
        full = os.path.join(path, name)
        if os.path.isdir(full):
            dirs.append(name)
        elif os.path.isfile(full):
            files.append(name)
    return sorted(dirs), sorted(files)


def _has_marker(path, markers):
    try:
        top = {n.lower() for n in os.listdir(path)}
    except OSError:
        return False
    return bool(top & markers)


def classify_layout(source_dir):
    # rough mode guess from the top level
    if _has_marker(source_dir, EMULATOR_MARKERS):
        return "emulator"
    if _has_marker(source_dir, RECOMP_MARKERS):
        return "recomp"
    if _has_marker(source_dir, CHEAT_MARKERS):
        return "cheat"
    return "unknown"


def sanitize_name(name, fallback="Imported Mod"):
    # folder name safe for disk
    cleaned = ILLEGAL_CHARS.sub(" ", str(name or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        return fallback
    return cleaned[:60].rstrip(" .") or fallback


def _descend_wrapper(path, depth=3):
    # archives keep the folder layer a plain folder drop would have eaten
    for _level in range(depth):
        if _has_marker(path, EMULATOR_MARKERS | RECOMP_MARKERS):
            return path
        dirs, _files = _top_entries(path)
        if not dirs:
            return path
        inner = [os.path.join(path, d) for d in dirs
                 if d.lower() not in EMULATOR_MARKERS | RECOMP_MARKERS
                 | CHEAT_MARKERS]
        rootish = [p for p in inner
                   if _has_marker(p, EMULATOR_MARKERS | RECOMP_MARKERS)]
        if len(rootish) == 1:
            path = rootish[0]
            continue
        if len(inner) == 1:
            # plain nesting, no markers yet
            path = inner[0]
            continue
        return path
    return path


def find_mod_root(staging):
    # pick the folder that actually holds the mod
    dirs, files = _top_entries(staging)
    if _has_marker(staging, EMULATOR_MARKERS | RECOMP_MARKERS):
        return {"source": staging, "name": "", "variants": dirs}

    roots, names = [], []
    for name in dirs:
        if name.lower() in EMULATOR_MARKERS | RECOMP_MARKERS | CHEAT_MARKERS:
            continue
        path = _descend_wrapper(os.path.join(staging, name))
        if _has_marker(path, EMULATOR_MARKERS | RECOMP_MARKERS):
            roots.append(path)
            names.append(name)

    if len(roots) == 1:
        return {"source": roots[0], "name": os.path.basename(roots[0]),
                "variants": []}

    if len(roots) > 1:
        return {"source": staging, "name": "", "variants": names}

    if len(dirs) == 1 and dirs[0].lower() not in (
            EMULATOR_MARKERS | RECOMP_MARKERS | CHEAT_MARKERS):
        candidate = os.path.join(staging, dirs[0])
        return {"source": candidate, "name": dirs[0], "variants": []}

    if dirs:
        return {"source": staging, "name": "", "variants": dirs}

    # loose files plus docs: the staging dir itself is the mod
    return {"source": staging, "name": "", "variants": []}
