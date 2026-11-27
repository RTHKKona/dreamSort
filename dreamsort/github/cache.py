# release observations on disk

import json
import os

from ..gamebanana.updater.cache import app_dir, root_key
from ..storage.atomic import atomic_write_json

TTL = 24 * 60 * 60           # a release older than this is worth a fresh look
KEEP = 14 * 24 * 60 * 60     # entries older than this are dropped


def cache_path(mode, root):
    # next to the gamebanana pages, same idea one file per install root
    return os.path.join(app_dir(), "update_cache",
                        "github-%s-%s.json" % (mode, root_key(root)))


def load(mode, root):
    empty = {"checked_at": 0, "releases": {}}
    try:
        with open(cache_path(mode, root), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict) or not isinstance(data.get("releases"), dict):
        return empty
    return {"checked_at": int(data.get("checked_at") or 0),
            "releases": data["releases"]}


def save(mode, root, data):
    path = cache_path(mode, root)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_json(path, data)
    except OSError:
        # a lost cache costs one refetch
        pass


def merge(releases, result, now):
    for key, entry in (result or {}).items():
        releases[key] = dict(entry, fetched_at=int(now))


def prune(releases, now):
    return {key: entry for key, entry in releases.items()
            if now - int(entry.get("fetched_at") or 0) <= KEEP}
