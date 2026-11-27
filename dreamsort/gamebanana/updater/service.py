# gui thread owner of update checks

import time

from PySide6.QtCore import QObject, Signal

from ...workers import UpdateCheckWorker, run_worker
from .cache import load, merge, prune, save
from .model import badges
from .plan import build

COOLDOWN = 15 * 60           # after a rate limit, leave the api alone a while
STOPPED = {
    "rate_limited": "GameBanana rate limited the check; the rest retries later.",
    "canceled": "The update check was canceled.",
}


class Updater(QObject):
    # one check at a time, badges out of the cached pages

    statuses_ready = Signal(object)
    busy_changed = Signal(bool)

    def __init__(self, client, prefs, save_prefs, parent=None):
        super().__init__(parent)
        self.client = client
        self.prefs = prefs if isinstance(prefs, dict) else {}
        self._save_prefs = save_prefs
        self.items = {}
        self.summary = {"updates": 0, "choices": 0, "current": 0, "linked": 0}
        self.error = ""
        self._mode = ""
        self._root = ""
        self._records = {}
        self._pages = {}
        self._checked_at = 0
        self._worker = None
        self._busy = False
        self._cooldown = 0.0

    # prefs

    def on_launch(self):
        return bool(self.prefs.get("on_launch", True))

    def set_on_launch(self, on):
        self.prefs["on_launch"] = bool(on)
        self._save()

    def _save(self):
        if self._save_prefs is not None:
            self._save_prefs()

    # checks

    def busy(self):
        return self._busy

    def check(self, mode, root, records, force=False, budget=200, only=None):
        # refresh what the cache cannot answer, then publish what we know
        if self._busy:
            return False
        if not root or not records:
            self._records, self.items = dict(records or {}), {}
            self.summary = {"updates": 0, "choices": 0, "current": 0,
                            "linked": 0}
            self.statuses_ready.emit({"items": {}, "summary": self.summary,
                                      "error": ""})
            return False
        self._mode, self._root = mode, root
        self._records = dict(records)
        data = load(mode, root)
        self._pages, self._checked_at = data["pages"], data["checked_at"]
        plan = self._publish(self._records)
        due = [str(only)] if only else plan["due"]
        if not due:
            return False
        if not force:
            if not self.on_launch():
                return False
            if time.time() < self._cooldown:
                return False
        self._start(due, budget, force)
        return True

    def _start(self, due, budget, force=False):
        self._worker = UpdateCheckWorker(due, self.client, budget=budget,
                                         force=force)
        self._busy = True
        self.busy_changed.emit(True)
        run_worker(self, self._worker, on_done=self._on_pages,
                   on_error=self._on_error)

    def _on_pages(self, result):
        self._worker = None
        result = result or {}
        merge(self._pages, result, time.time())
        self._checked_at = int(time.time())
        self._pages = prune(self._pages, self._checked_at)
        save(self._mode, self._root, {"checked_at": self._checked_at,
                                      "pages": self._pages})
        stopped = result.get("stopped") or ""
        if stopped == "rate_limited":
            # the pages left in the batch keep their old stamp and retry later
            self._cooldown = time.time() + COOLDOWN
        self.error = STOPPED.get(stopped, "")
        self._finish()
        self._publish(self._records)

    def _on_error(self, message):
        self._worker = None
        self._finish()
        self.error = str(message)
        self.statuses_ready.emit({"items": self.items,
                                  "summary": self.summary,
                                  "error": self.error})

    def _finish(self):
        self._busy = False
        self.busy_changed.emit(False)

    def _publish(self, records):
        plan = build(records, self._pages, self.prefs, time.time())
        self.items, self.summary = plan["items"], plan["summary"]
        self.statuses_ready.emit({"items": self.items, "summary": self.summary,
                                  "error": self.error})
        return plan

    def republish(self):
        # after a pref change, no network
        self._publish(self._records)

    # ui helpers

    def badges(self):
        return badges(self.items)

    def item(self, folder_id):
        return self.items.get(folder_id)

    def ignore(self, folder_id):
        # skip the version being offered, not the page
        item = self.items.get(folder_id) or {}
        file = item.get("file") or {}
        if not item.get("page_id") or not file.get("id"):
            return False
        ignored = self.prefs.setdefault("ignored", {})
        ignored[item["page_id"]] = {"ignored_file_id": str(file["id"])}
        self._save()
        self.republish()
        return True

    def unignore(self, page_id):
        ignored = self.prefs.get("ignored") or {}
        if str(page_id) in ignored:
            ignored.pop(str(page_id), None)
            self._save()
            self.republish()

    def shutdown(self, timeout_ms=0):
        if self._worker is not None and hasattr(self._worker, "cancel"):
            self._worker.cancel()
