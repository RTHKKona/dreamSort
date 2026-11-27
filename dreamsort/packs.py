# known modpack signatures
#
# a pack is identified by the way it was packaged, not by the mods inside:
# the component arcs belong to their original authors, so matching those
# would also flag a user who installed the originals by hand.

import os
import re
import zipfile

from .errors import DreamSortError, ErrorCode

try:
    import py7zr
except ImportError:
    py7zr = None

WALK_DEPTH = 6      # layout_cfg sits five levels under the mods folder
CFG_MAX = 4096      # every layout_cfg in the pack is under 1 KB
SCORE_FLOOR = 4

_FAMILIES = (
    ("textures", re.compile(r"^hd textures(?: v\d+(?:\.\d+)?)?$", re.I)),
    ("hud", re.compile(r"^hd ui(?: v\d+(?:\.\d+)?)?$", re.I)),
    ("cheats", re.compile(r"^pixel cheats(?: v\d+(?:\.\d+)?)?$", re.I)),
    ("fov", re.compile(r"^fov(?: v\d+(?:\.\d+)?)?(?: \((?:close|medium|far|extreme)\))?$", re.I)),
    ("fps", re.compile(r"^(?:60|120) ?fps(?: patch)?$", re.I)),
    ("resolution", re.compile(r"^4k-2k patch$", re.I)),
    ("extras", re.compile(r"^mh(?:xx|gu) (?:dlc injector|save ?editor)$", re.I)),
)

# one component on its own is enough when it carries the pack's naming, i.e.
# a version tag; a bare family name ("60FPS Patch") needs corroboration
_COMPONENT_SCORE = {
    "textures": 4, "hud": 4, "cheats": 4,
    "fov": 3, "extras": 3, "fps": 1, "resolution": 1,
}

SIGNATURES = (
    {
        "id": "hd_pixel_pack",
        "name": "HD Pixel Pack",
        "brand": "HDPP",
        "tutorial": "manual installation is trickier",
        "note": ("A repack of other authors' mods: HD textures, the HUD port, "
                 "FOV and resolution patches, cheats, a save editor and the DLC "
                 "injector, shipped as one download. The bundle carries no "
                 "per-mod credits and no permission notes."),
    },
)

_PAIR = re.compile(rb"\b[0-9A-Fa-f]{2}\b")
_PREFIX = re.compile(r"^~?\d+[_\-\s]+|^~")
_VERSION = re.compile(r"\bv\d+(?:\.\d+)?\b", re.I)


def folder_key(path):
    # stable key for the mute list
    return os.path.normcase(os.path.abspath(path or ""))


def _read(path, limit):
    try:
        with open(path, "rb") as handle:
            return handle.read(limit)
    except OSError:
        return b""


def _decoded_hex(raw):
    # layout_cfg keeps its strings as spaced hex pairs, so a plain text
    # search finds nothing; decode the pairs back first
    pairs = _PAIR.findall(raw)
    if len(pairs) < 8:
        return ""
    try:
        return bytes(int(pair, 16) for pair in pairs).decode("latin-1")
    except ValueError:
        return ""


def _cfg_paths(root):
    base = os.path.normpath(root)
    for current, dirs, files in os.walk(base):
        relative = os.path.relpath(current, base)
        depth = 0 if relative == os.curdir else relative.count(os.sep)
        if depth >= WALK_DEPTH:
            dirs[:] = []
        else:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if name.lower() == "layout_cfg":
                yield os.path.join(current, name)


def _brand(root, token):
    # first branded config, with its decoded text
    wanted = token.upper()
    for path in _cfg_paths(root):
        text = _decoded_hex(_read(path, CFG_MAX)).upper()
        if wanted in text:
            return path, text
    return None, ""


def _families(names):
    found = {}
    for name in names:
        base = os.path.basename(str(name).rstrip("/\\"))
        if base.lower().endswith((".zip", ".7z", ".rar")):
            base = base[:-4]
        base = _PREFIX.sub("", base)
        for family, pattern in _FAMILIES:
            if pattern.match(base):
                found.setdefault(family, []).append(base)
                break
    return found


def _versioned(name):
    return bool(_VERSION.search(name))


def _score(names, brand=False, tutorial=False, comment=False):
    # names are folder or archive top-level names; nothing is unpacked
    families = _families(names)
    score = 0
    signals = []
    if len(families) >= 4:
        score += 2
        signals.append("bundle: " + ", ".join(
            sorted(hits[0] for hits in families.values())))
        # the pack names its parts with versions; a bundle of bare names
        # still needs the HUD brand or the tutorial to be sure
        score += min(2, sum(1 for hits in families.values()
                            if _versioned(hits[0])))
    else:
        for family, hits in families.items():
            base = hits[0]
            score += _COMPONENT_SCORE[family] if _versioned(base) else 1
            signals.append("component: " + base)
    if brand:
        score += 4
        signals.append("HUD config branded %s" % brand)
    if tutorial:
        score += 2
        signals.append("ships the pack's manual install tutorial")
    if comment:
        score += 1
        signals.append("archive comment repeats the tutorial text")
    return score, signals


def _finding(signature, where, score, signals):
    return {
        "id": signature["id"],
        "name": signature["name"],
        "score": score,
        "signals": signals,
        "where": where,
        "note": signature["note"],
    }


def scan_root(root):
    # mods folder as installed on disk; only actual mod folders count
    if not root or not os.path.isdir(root):
        return None
    try:
        names = [entry.name for entry in os.scandir(root) if entry.is_dir()]
    except OSError:
        return None
    parked = os.path.join(root, "disabled_mods")
    if os.path.isdir(parked):
        try:
            names += [entry.name for entry in os.scandir(parked)
                      if entry.is_dir()]
        except OSError:
            pass

    # a single mod dropped on its own is named like a component, so the
    # folder's own name counts as well as what is inside it
    names.append(os.path.basename(os.path.normpath(root)))

    for signature in SIGNATURES:
        path, _ignored = _brand(root, signature["brand"])
        brand = signature["brand"] if path else ""
        score, signals = _score(names, brand=brand)
        if score >= SCORE_FLOOR:
            return _finding(signature, root, score, signals)
    return None


def _archive_names(path):
    # entry names plus the zip comment, no extraction
    lower = path.lower()
    try:
        if lower.endswith(".zip"):
            with zipfile.ZipFile(path, "r") as archive:
                comment = archive.comment.decode("utf-8", "replace")
                return archive.namelist(), comment
        if lower.endswith(".7z") and py7zr is not None:
            with py7zr.SevenZipFile(path, mode="r") as archive:
                return [item.filename for item in archive.list()], ""
    except Exception:
        return [], ""
    return [], ""


def _has_tutorial(names):
    wanted = {"install tutorial.txt", "installation tutorial.txt"}
    return any(os.path.basename(str(name).rstrip("/\\")).lower() in wanted
               for name in names)


def scan_archive(path):
    # a pack archive or a single component before it is unpacked
    if not path or not os.path.isfile(path):
        return None
    names, comment = _archive_names(path)
    if not names:
        return None

    top = {str(name).split("/")[0].split("\\")[0] for name in names
           if name and not str(name).startswith("/")}
    # a component zip often holds romfs at the root, so its file name counts
    stem = os.path.basename(path)
    if stem.lower().endswith((".zip", ".7z", ".rar")):
        stem = stem[:-4]
    top.add(stem)
    for signature in SIGNATURES:
        score, signals = _score(
            top,
            tutorial=_has_tutorial(names),
            comment=signature["tutorial"] in comment.lower())
        if score >= SCORE_FLOOR:
            return _finding(signature, path, score, signals)
    return None



def scan_inputs(items):
    # anything about to be installed
    hits = []
    for item in items or ():
        path = str(item).strip().strip('"')
        hit = scan_root(path) if os.path.isdir(path) else scan_archive(path)
        if hit:
            hits.append(hit)
    return hits


def pixelpack_error(finding):
    # wrap a finding as the 1337 error
    return DreamSortError(
        ErrorCode.PIXELPACK_DETECTED,
        context="%s at %s" % (finding.get("name", "unknown pack"),
                              finding.get("where", "")),
        details=finding)


def assert_clean(items):
    # hard gate for callers that must never accept a pixelpack
    hits = scan_inputs(items)
    if not hits:
        return
    err = pixelpack_error(hits[0])
    err.details = {"hits": hits}
    raise err
