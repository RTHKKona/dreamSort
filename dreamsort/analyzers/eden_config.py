# eden cheat switch

import os
import shutil

SWITCH_KEY = "enable_cheats_by_default"
USE_GLOBAL_KEY = "enable_cheats_by_default\\use_global"
DEFAULT_KEY = "enable_cheats_by_default\\default"
SECTION = "Core"
BACKUP_SUFFIX = ".dreamsort.bak"
GLOBAL_FILE = "qt-config.ini"
PER_GAME_FOLDER = "custom"


def config_dir_for(eden_root):
    # eden root
    return os.path.join(eden_root, "config") if eden_root else ""


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except OSError:
        return None


def _newline_of(text):
    return "\r\n" if "\r\n" in text else "\n"


def _join(lines, newline):
    return newline.join(lines) + newline if lines else ""


def _section_bounds(lines, section):
    # start and end of a section
    start = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if start is not None:
                return start, index
            if stripped[1:-1].strip().lower() == section.lower():
                start = index + 1
    if start is None:
        return None
    return start, len(lines)


def read_value(path, key, default=None):
    # read a key from [Core]
    text = _read(path)
    if text is None:
        return default
    lines = text.splitlines()
    bounds = _section_bounds(lines, SECTION)
    if bounds is None:
        return default
    for line in lines[bounds[0]:bounds[1]]:
        stripped = line.strip()
        if not stripped or stripped[0] in ";#" or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip().lower() == key.lower():
            return value.strip()
    return default


def _as_bool(raw, default):
    if raw is None:
        return default
    return raw.strip().strip('"').lower() in ("1", "true", "yes", "on")


def _bool_text(value):
    return "true" if value else "false"


def _set_key(text, key, value):
    # write a key in [Core]
    newline = _newline_of(text)
    lines = text.splitlines()
    bounds = _section_bounds(lines, SECTION)
    if bounds is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("[%s]" % SECTION)
        lines.append("%s=%s" % (key, value))
        return _join(lines, newline)
    start, end = bounds
    for index in range(start, end):
        stripped = lines[index].strip()
        if "=" not in stripped:
            continue
        name = stripped.split("=", 1)[0].strip()
        if name.lower() == key.lower():
            lines[index] = "%s=%s" % (key, value)
            return _join(lines, newline)
    lines.insert(end, "%s=%s" % (key, value))
    return _join(lines, newline)


def _backup(path):
    try:
        shutil.copy2(path, path + BACKUP_SUFFIX)
        return True
    except OSError:
        return False


def _write(path, text):
    temp = path + ".dreamsort.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(temp, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temp, path)
        return True
    except OSError:
        try:
            os.remove(temp)
        except OSError:
            pass
        return False


def cheat_switch(config_dir, title_id):
    # what eden will do
    info = {
        "enabled": True,
        "source": "default",
        "global_path": "",
        "global_raw": None,
        "global_value": True,
        "per_game_path": "",
        "per_game_present": False,
        "use_global": True,
        "is_default": True,
        "per_game_raw": None,
    }
    if not config_dir:
        return info

    global_path = os.path.join(config_dir, GLOBAL_FILE)
    per_game_path = os.path.join(config_dir, PER_GAME_FOLDER, title_id + ".ini")
    info["global_path"] = global_path
    info["per_game_path"] = per_game_path

    raw = read_value(global_path, SWITCH_KEY)
    info["global_raw"] = raw
    info["global_value"] = _as_bool(raw, True)
    info["enabled"] = info["global_value"]
    if raw is None:
        info["source"] = "Eden default"
    else:
        info["source"] = "global ini"

    if not os.path.isfile(per_game_path):
        return info

    info["per_game_present"] = True
    use_global = _as_bool(read_value(per_game_path, USE_GLOBAL_KEY), True)
    info["use_global"] = use_global
    if use_global:
        return info

    is_default = _as_bool(read_value(per_game_path, DEFAULT_KEY), True)
    info["is_default"] = is_default
    if is_default:
        info["enabled"] = True
        info["source"] = "per-game default"
        return info

    raw = read_value(per_game_path, SWITCH_KEY)
    info["per_game_raw"] = raw
    info["enabled"] = _as_bool(raw, True)
    info["source"] = "per-game ini"
    return info


def set_enabled(config_dir, title_id, enabled=True):
    # flip the switch
    if not config_dir:
        return False, "No Eden folder is loaded."
    wanted = _bool_text(enabled)

    global_path = os.path.join(config_dir, GLOBAL_FILE)
    text = _read(global_path)
    if text is None:
        text = "[%s]%s" % (SECTION, os.linesep)
    if os.path.isfile(global_path):
        _backup(global_path)
    if not _write(global_path, _set_key(text, SWITCH_KEY, wanted)):
        return False, "Could not write %s." % global_path

    per_game_path = os.path.join(config_dir, PER_GAME_FOLDER, title_id + ".ini")
    if os.path.isfile(per_game_path):
        text = _read(per_game_path) or ""
        _backup(per_game_path)
        if not _write(per_game_path, _set_key(text, USE_GLOBAL_KEY, "true")):
            return False, "Could not write %s." % per_game_path

    state = cheat_switch(config_dir, title_id)
    if bool(state["enabled"]) != bool(enabled):
        return False, ("The ini was written but Eden still reads %s (%s)."
                       % (state["enabled"], state["source"]))
    return True, "Eden now reads %s, set in %s." % (wanted, global_path)


def describe(state):
    # one line for the ui
    return "enabled=%s (%s)" % ("true" if state["enabled"] else "false",
                                state["source"])
