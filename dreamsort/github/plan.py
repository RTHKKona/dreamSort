# records plus cached releases -> one state per folder

import time

from .updates import CURRENT, NO_ASSET, NONE, UNKNOWN, UPDATE, evaluate

ERROR_TTL = 60 * 60          # a repo that failed is worth one more look


def _fresh(entry, now, ttl):
    return now - int(entry.get("fetched_at") or 0) <= ttl


def build(records, releases, prefs, now=None, ttl=None):
    # pure: no io, no network, no qt
    now = time.time() if now is None else now
    ttl = 24 * 60 * 60 if ttl is None else ttl
    items, due = {}, set()

    for folder_id, record in records.items():
        github = (record or {}).get("github") or {}
        key = ("%s/%s" % (github.get("owner") or "",
                          github.get("repo") or "")).lower()
        tracked = bool(github.get("owner") and github.get("repo"))
        item = {"folder_id": folder_id, "repo": key if tracked else "",
                "status": NONE, "knowledge": "never", "tag": "",
                "installed_tag": github.get("tag") or "", "release": None,
                "asset": None, "error": "", "name": "", "page_url": ""}
        if tracked:
            entry = releases.get(key) or {}
            if not entry:
                due.add(key)
            elif entry.get("error"):
                item.update(status=UNKNOWN, knowledge="failed",
                            error=entry.get("message") or "check failed")
                if not _fresh(entry, now, ERROR_TTL):
                    # a blip heals on its own clock, not once a day
                    due.add(key)
            else:
                item["knowledge"] = ("fresh" if _fresh(entry, now, ttl)
                                     else "stale")
                if item["knowledge"] != "fresh":
                    due.add(key)
                release = entry.get("release") or {}
                item["release"] = release
                item["name"] = release.get("name") or key
                item["page_url"] = release.get("html_url") or ""
                item["tag"] = release.get("tag") or ""
                status, asset = evaluate(record, release)
                item.update(status=status, asset=asset)
        items[folder_id] = item

    return {"items": items, "due": sorted(due), "summary": summary(items)}


def summary(items):
    # counts for the bar text
    return {
        "updates": sum(1 for item in items.values()
                       if item["status"] == UPDATE),
        "current": sum(1 for item in items.values()
                       if item["status"] == CURRENT),
        "linked": sum(1 for item in items.values() if item["repo"]),
    }


def badges(items):
    # text and chip kind per folder, only where something is worth saying
    out = {}
    for folder_id, item in items.items():
        if item["status"] == UPDATE:
            out[folder_id] = ("update", "update")
        elif item["status"] == NO_ASSET:
            out[folder_id] = ("no file", "muted")
        elif item["status"] == UNKNOWN and item["knowledge"] == "failed":
            out[folder_id] = ("check failed", "muted")
    return out
