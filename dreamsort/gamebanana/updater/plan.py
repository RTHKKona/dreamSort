# records plus cached pages -> one state per folder

import time

from ..updates import (CHOICE, CURRENT, GONE, UNKNOWN, UNLINKED, UPDATE,
                       evaluate)
from .model import summary

ERROR_TTL = 60 * 60          # a page that failed is worth one more look
GONE_TTL = 24 * 60 * 60      # a delisted page heals on the next day's check


def _fresh(entry, now, ttl):
    return now - int(entry.get("fetched_at") or 0) <= ttl


def build(records, pages, prefs, now=None, ttl=None):
    # pure: no io, no network, no qt
    now = time.time() if now is None else now
    ttl = 24 * 60 * 60 if ttl is None else ttl
    ignored = (prefs or {}).get("ignored") or {}
    items, due = {}, set()

    for folder_id, record in records.items():
        record = record or {}
        page_id = str(record.get("gb_mod_id") or "")
        item = {"folder_id": folder_id, "page_id": page_id,
                "status": UNLINKED, "knowledge": "never", "file": None,
                "options": [], "ignored": False, "name": "",
                "version": "", "page_url": record.get("page_url", ""),
                "section": ""}
        if page_id:
            entry = pages.get(page_id) or {}
            profile = entry.get("profile") or {}
            item["name"] = profile.get("name") or ""
            item["version"] = profile.get("version") or ""
            item["page_url"] = profile.get("page_url") or item["page_url"]
            item["section"] = profile.get("super_category") or ""
            if not entry:
                due.add(page_id)
            elif entry.get("error") == "gone":
                item.update(status=GONE, knowledge="fresh")
                if not _fresh(entry, now, GONE_TTL):
                    due.add(page_id)
            elif entry.get("error"):
                item.update(status=UNKNOWN, knowledge="failed")
                # a failed page is retried on its own clock, not once a day
                if not _fresh(entry, now, ERROR_TTL):
                    due.add(page_id)
            elif profile:
                item["knowledge"] = ("fresh" if _fresh(entry, now, ttl)
                                     else "stale")
                if item["knowledge"] != "fresh":
                    due.add(page_id)
                status, file, options = evaluate(record, profile)
                item.update(status=status, file=file, options=options)
                ignore_id = (ignored.get(page_id) or {}).get(
                    "ignored_file_id")
                if (status == UPDATE and file and ignore_id
                        and str(file.get("id")) == str(ignore_id)):
                    # a skipped version stays skipped until the page moves on
                    item.update(status=CURRENT, file=None, ignored=True)
        items[folder_id] = item

    return {"items": items, "due": sorted(due), "summary": summary(items)}
