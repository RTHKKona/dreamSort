# background update check

import random
import threading
import time

from ..gamebanana.client import GBError
from .thread_worker import Worker


class UpdateCheckWorker(Worker):
    # one request per page, slow on purpose, stoppable

    def __init__(self, mod_ids, client, budget=200, gap=(0.8, 1.5),
                 force=False):
        super().__init__(lambda: None)
        self.mod_ids = [str(mod_id) for mod_id in mod_ids]
        self.client = client
        self.budget = max(int(budget), 0)
        self.gap = gap
        self.force = bool(force)
        self._cancel = threading.Event()
        self._sleep = time.sleep

    def cancel(self):
        self._cancel.set()

    def run(self):
        pages = {}
        stopped = ""
        ids = self.mod_ids[:self.budget]
        total = len(ids)
        for index, mod_id in enumerate(ids, 1):
            if self._cancel.is_set():
                stopped = "canceled"
                break
            self.progress.emit({"index": index, "total": total, "text": mod_id})
            try:
                profile, meta = self.client.fetch_profile_meta(
                    mod_id, force=self.force)
                pages[mod_id] = {"profile": profile, "meta": meta}
            except GBError as exc:
                pages[mod_id] = {
                    "error": "gone" if exc.gone else
                              ("rate_limited" if exc.status == 429 else "failed"),
                    "message": str(exc), "http": exc.status}
                if exc.status == 429:
                    # a batch never keeps going after a 429
                    stopped = "rate_limited"
                    break
            except Exception as exc:
                pages[mod_id] = {"error": "failed", "message": str(exc)}
            if index < total and not self._cancel.is_set():
                self._sleep(random.uniform(*self.gap))
        self.finished.emit({"pages": pages, "stopped": stopped,
                            "checked": len(pages)})
