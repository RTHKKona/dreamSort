# page observations on disk

import hashlib
import json
import os

from ...storage import atomic_write_json

TTL = 24 * 60 * 60           # a page older than this is worth a fresh look
KEEP = 14 * 24 * 60 * 60     # entries older than this are dropped


def app_dir():
    from ... import storage
    return os.path.dirname(storage.config_path())


def root_key(root):
    norm = os.path.normcase(os.path.abspath(root or ""))
    return hashlib.sha1(norm.encode("utf-8", "replace")).hexdigest()[:12]


def cache_path(mode, root):
    # one file per install root, so modes never share a page's answer
    return os.path.join(app_dir(), "update_cache",
                        "%s-%s.json" % (mode, root_key(root)))


def load(mode, root):
    empty = {"checked_at": 0, "pages": {}}
    try:
        with open(cache_path(mode, root), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict) or not isinstance(data.get("pages"), dict):
        return empty
    return {"checked_at": int(data.get("checked_at") or 0),
            "pages": data["pages"]}


def save(mode, root, data):
    path = cache_path(mode, root)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_json(path, data)
    except OSError:
        # a lost cache costs one refetch
        pass


def merge(pages, result, now):
    # fold one worker run into the stored pages
    for page_id, entry in (result.get("pages") or {}).items():
        meta = entry.get("meta") or {}
        if entry.get("profile"):
            pages[page_id] = {"fetched_at": int(now),
                              "http": meta.get("http", 200),
                              "etag": meta.get("etag", ""),
                              "profile": entry["profile"]}
            continue
        pages[page_id] = {"fetched_at": int(now),
                          "http": entry.get("http") or 0,
                          "error": entry.get("error") or "failed",
                          "message": entry.get("message", "")}


def prune(pages, now):
    return {page_id: entry for page_id, entry in pages.items()
            if now - int(entry.get("fetched_at") or 0) <= KEEP}
