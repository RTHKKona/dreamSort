# gui thread owner of github checks

import random
import time

from PySide6.QtCore import QObject, Signal

from ..workers import run_in_thread
from . import cache
from .client import GitHubClient, GitHubError
from .plan import badges, build
from .updates import UPDATE

COOLDOWN = 15 * 60           # after a rate limit, leave the api alone a while


class GitHubUpdates(QObject):
    # one check at a time, states out of the cached releases

    statuses_ready = Signal(object)
    busy_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self, token="", prefs=None, save_prefs=None, parent=None):
        super().__init__(parent)
        self.token = str(token or "").strip()
        self.prefs = prefs if isinstance(prefs, dict) else {}
        self._save_prefs = save_prefs
        self.items = {}
        self.summary = {"updates": 0, "current": 0, "linked": 0}
        self.error = ""
        self._mode = ""
        self._root = ""
        self._records = {}
        self._releases = {}
        self._checked_at = 0
        self._busy = False
        self._cooldown = 0.0

    # prefs

    def on_launch(self):
        # off means only an explicit check touches the network
        return bool(self.prefs.get("on_launch", True))

    def set_on_launch(self, on):
        # one switch covers both sources
        self.prefs["on_launch"] = bool(on)
        if self._save_prefs is not None:
            self._save_prefs()

    def busy(self):
        return self._busy

    # checks

    def check(self, mode, root, records, force=False, only=None):
        # refresh what the cache cannot answer, then publish what we know
        if self._busy:
            return False
        if not root or not records:
            self._records, self.items = dict(records or {}), {}
            self.summary = {"updates": 0, "current": 0, "linked": 0}
            self.statuses_ready.emit({"items": {}, "summary": self.summary,
                                      "error": ""})
            return False
        self._mode, self._root = mode, root
        self._records = dict(records)
        data = cache.load(mode, root)
        self._releases, self._checked_at = data["releases"], data["checked_at"]
        plan = self._publish()
        due = [str(only)] if only else plan["due"]
        if not due:
            return False
        if not force:
            if not self.on_launch():
                return False
            if time.time() < self._cooldown:
                return False
        self._start(due)
        return True

    def _start(self, due):
        self._busy = True
        self.busy_changed.emit(True)
        run_in_thread(self, self._fetch_many, due,
                      on_done=self._on_releases, on_error=self._on_error)

    def _fetch_many(self, keys):
        # worker thread, one request per repo
        client = GitHubClient(self.token)
        result = {}
        for index, key in enumerate(keys):
            owner, _, repo = key.partition("/")
            try:
                release, _meta = client.latest_release(owner, repo, force=True)
                result[key] = {"release": release}
            except GitHubError as exc:
                result[key] = {"error": "rate" if exc.rate_limited
                               else "failed", "message": str(exc)}
            if index < len(keys) - 1:
                time.sleep(random.uniform(0.2, 0.5))
        return result

    def _on_releases(self, result):
        now = time.time()
        result = result or {}
        cache.merge(self._releases, result, now)
        self._checked_at = int(now)
        self._releases = cache.prune(self._releases, self._checked_at)
        cache.save(self._mode, self._root, {"checked_at": self._checked_at,
                                            "releases": self._releases})
        if any(entry.get("error") == "rate" for entry in result.values()):
            self._cooldown = time.time() + COOLDOWN
        self.error = ""
        self._finish()
        self._publish()

    def _on_error(self, message):
        self._finish()
        self.error = str(message)
        self.failed.emit(self.error)
        self.statuses_ready.emit({"items": self.items,
                                  "summary": self.summary,
                                  "error": self.error})

    def _finish(self):
        self._busy = False
        self.busy_changed.emit(False)

    def _publish(self):
        plan = build(self._records, self._releases, self.prefs, time.time())
        self.items, self.summary = plan["items"], plan["summary"]
        self.statuses_ready.emit({"items": self.items, "summary": self.summary,
                                  "error": self.error})
        return plan

    def republish(self):
        # after a link change, no network
        self._publish()

    # ui helpers

    def badges(self):
        return badges(self.items)

    def item(self, folder_id):
        return self.items.get(folder_id)

    def prepare_install(self, folder_id):
        # what the download queue needs to replace this install, or None
        item = self.items.get(folder_id)
        if not item or item.get("status") != UPDATE:
            return None
        release, asset = item.get("release") or {}, item.get("asset") or {}
        if not asset.get("url"):
            return None
        owner, _, repo = str(item.get("repo") or "").partition("/")
        tag = release.get("tag") or ""
        github = {"owner": owner, "repo": repo, "tag": tag,
                  "asset": asset.get("name") or ""}
        record = {"github": github,
                  "filename": asset.get("name") or "",
                  "version": tag,
                  "page_url": release.get("html_url") or "",
                  "installed_at": int(time.time())}
        profile = {"name": item.get("name") or repo or owner,
                   "version": tag,
                   "page_url": release.get("html_url") or "",
                   "mod_id": ""}
        return {"url": asset["url"],
                "name": asset.get("name") or ("%s-%s.zip" % (repo, tag)),
                "size": int(asset.get("size") or 0),
                "context": {"update_mod_id": folder_id},
                "record": record,
                "profile": profile}

    def shutdown(self):
        pass
