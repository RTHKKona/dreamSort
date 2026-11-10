# config file

import json
import os
import sys

from .atomic import atomic_write_json, atomic_write_text

def resource_path(relative_path):
    return os.path.join(getattr(sys, "_MEIPASS", os.path.abspath(".")), relative_path)

def config_path():
    # config.json location
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "config.json")


# notices for the ui
CONFIG_NOTICES = []


def _parse_config_file(path):
    # data + state
    try:
        with open(path, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
    except FileNotFoundError:
        return None, "missing"
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "corrupt"
    except OSError:
        return None, "unreadable"
    if not isinstance(data, dict):
        return None, "corrupt"
    return data, "ok"


def read_config():
    # load it, empty if it fails
    path = config_path()
    data, state = _parse_config_file(path)
    if state == "ok":
        return data
    if state != "corrupt":
        return {}

    bad_path = path + ".bad"
    try:
        os.replace(path, bad_path)
    except OSError:
        bad_path = None
    kept = (f"The damaged file was kept as '{os.path.basename(bad_path)}'."
            if bad_path else "The damaged file could not be moved aside.")

    backup, backup_state = _parse_config_file(path + ".bak")
    if backup_state == "ok":
        try:
            write_config(backup)
        except OSError:
            pass
        CONFIG_NOTICES.append(
            "config.json was unreadable, so your last saved settings and "
            f"profiles were restored from the backup.\n\n{kept}")
        return backup

    CONFIG_NOTICES.append(
        "config.json was unreadable and no backup was available, so settings "
        f"were reset to defaults.\n\n{kept}\nYour saved profiles may be "
        "recoverable from that file.")
    return {}


def write_config(data):
    # save it
    path = config_path()
    try:
        with open(path, "r", encoding="utf-8") as current_file:
            current = current_file.read()
        json.loads(current)
        atomic_write_text(path + ".bak", current)
    except (OSError, ValueError):
        pass
    atomic_write_json(path, data)
