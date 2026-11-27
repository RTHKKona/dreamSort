# sidecar records

import json
import os
import time

from ..storage.atomic import atomic_write_json
from .urls import page_url

SIDECAR_NAME = ".dreamsort.json"


def record_path(mod_dir):
    return os.path.join(mod_dir, SIDECAR_NAME)


def read_record(mod_dir):
    # record next to the mod, None if absent or broken
    path = record_path(mod_dir)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_record(mod_dir, record):
    atomic_write_json(record_path(mod_dir), record)


def build_record(mod_id, file_id, filename, md5, file_date, version,
                 known_ids=None):
    # what gets remembered for later update checks
    record = {
        "gb_mod_id": str(mod_id or ""),
        "gb_file_id": str(file_id or ""),
        "filename": filename or "",
        "md5": md5 or "",
        "installed_file_date": file_date or "",
        "version": version or "",
        "page_url": page_url(mod_id) if mod_id else "",
        "installed_at": int(time.time()),
    }
    # every file the page offered now, so a later check can tell new from old
    known = [str(value) for value in (known_ids or []) if str(value or "")]
    if known:
        record["gb_known_file_ids"] = sorted(set(known), key=_as_int)
    return record


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
