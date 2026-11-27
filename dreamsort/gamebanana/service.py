# app-scoped gb glue

import os

from PySide6.QtCore import QObject, Signal

from ..gamebanana.client import GameBananaClient
from ..gamebanana.links import build_record
from ..gamebanana.policy import check_profile
from ..gamebanana.updates import known_ids_for, pick_installable_file
from ..gamebanana.urls import parse_link
from ..helpers.layout import sanitize_name
from ..storage import config_path
from ..workers import DownloadWorker, run_in_thread, run_worker


class GameBananaService(QObject):
    # outlives the view, hands archives to whoever is showing

    profile_ready = Signal(object)
    archive_ready = Signal(object)
    failed = Signal(str)
    progress = Signal(object)
    queue_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.client = GameBananaClient()
        self._pending = None
        self._pending_context = None
        self._pending_file_id = None
        self._active_threads = []
        self._queue = []
        self._next_id = 1
        self._active_entry = None

    # urls and profile fetch

    def install_from_url(self, text, context=None):
        parsed = parse_link(text)
        if not parsed:
            self.failed.emit("That does not look like a GameBanana link.")
            return
        self._pending_context = context
        self._pending_file_id = parsed.get("file_id")
        if not parsed.get("mod_id"):
            # bare download link, the cdn name is all we get
            run_in_thread(self, self._probe_file, parsed["file_id"],
                          on_done=self._on_file_probe, on_error=self._on_error)
            return
        run_in_thread(self, self._fetch_profile, parsed["mod_id"],
                      on_done=self._on_profile, on_error=self._on_error)

    def _fetch_profile(self, mod_id):
        return self.client.fetch_profile(mod_id)

    def _probe_file(self, file_id):
        return self.client.probe_file(file_id)

    def _on_file_probe(self, file):
        # no page to check, so no section or game gate applies
        profile = {
            "mod_id": "",
            "name": os.path.splitext(file["name"])[0],
            "author": "",
            "version": "",
            "updated_at": "",
            "page_url": "",
            "files": [file],
        }
        pending = {"profile": profile, "file": file,
                   "context": self._pending_context}
        self._pending_context = None
        self._pending_file_id = None
        self._start_download(pending)

    def _on_profile(self, profile):
        reason = check_profile(profile)
        if reason:
            self._pending_context = None
            self._pending_file_id = None
            self.failed.emit(reason)
            return
        file = pick_installable_file(
            profile, None,
            want_id=self._pending_file_id
            or (self._pending_context or {}).get("want_file_id"))
        if not file:
            self._pending_context = None
            self._pending_file_id = None
            self.failed.emit("No installable file found on that page.")
            return
        self._pending_file_id = None
        pending = {"profile": profile, "file": file,
                   "context": self._pending_context}
        self._pending_context = None
        context = pending.get("context") or {}
        if context.get("auto_confirm"):
            self._start_download(pending)
        else:
            self._pending = pending
            self.profile_ready.emit({"profile": profile, "file": file})

    def proceed_download(self):
        pending = self._pending
        if not pending:
            return
        self._pending = None
        self._start_download(pending)

    def cancel_pending(self):
        self._pending = None

    # download queue

    def entries(self):
        # snapshot for the ui
        return list(self._queue)

    def active_count(self):
        return sum(1 for entry in self._queue
                   if entry["status"] in ("queued", "downloading", "fetching"))

    def install_archive(self, url, name, size=0, context=None, record=None,
                        profile=None):
        # a direct file from a source that is not gamebanana
        if not url:
            self.failed.emit("That release has no downloadable file.")
            return
        pending = {
            "profile": profile or {"name": os.path.splitext(name or "")[0],
                                   "mod_id": "", "version": "",
                                   "page_url": "", "files": []},
            "file": {"id": "", "name": name or "download.zip", "url": url,
                     "size": int(size or 0), "md5": "", "date": ""},
            "context": context,
            "record": record,
        }
        self._start_download(pending)

    def _start_download(self, pending):
        context = pending.pop("context", None)
        profile, file = pending["profile"], pending["file"]
        record = pending.get("record")
        if not file.get("url"):
            self.failed.emit("That file has no direct download link.")
            return
        dest_dir = os.path.join(os.path.dirname(config_path()), "downloads")
        os.makedirs(dest_dir, exist_ok=True)
        safe_name = sanitize_name(file["name"] or ("file-%s" % file["id"]),
                                  fallback="file-%s" % file["id"])
        dest = os.path.join(dest_dir, safe_name)
        entry = {
            "id": self._next_id,
            "label": profile.get("name") or safe_name,
            "filename": file.get("name") or safe_name,
            "status": "queued",
            "received": 0,
            "total": int(file.get("size") or 0),
            "text": "",
            "profile": profile,
            "file": file,
            "context": context,
            "dest": dest,
            "record": record,
            "error": "",
        }
        self._next_id += 1
        self._queue.append(entry)
        self.queue_changed.emit()
        self._pump()

    def _pump(self):
        if self._active_entry is not None:
            return
        entry = next((item for item in self._queue
                      if item["status"] == "queued"), None)
        if entry is None:
            return
        entry["status"] = "downloading"
        self._active_entry = entry
        job = {
            "url": entry["file"]["url"],
            "dest": entry["dest"],
            "file_id": entry["file"]["id"],
            "expected_md5": entry["file"].get("md5", ""),
            "label": entry["label"],
            "profile": entry["profile"],
            "file": entry["file"],
            "context": entry["context"],
            "entry_id": entry["id"],
            "record": entry.get("record"),
        }
        worker = DownloadWorker(job)
        entry["worker"] = worker
        entry_id = entry["id"]
        run_worker(self, worker, on_done=self._on_download_done,
                   on_error=self._on_download_error,
                   on_progress=self._on_download_progress)
        worker.cancelled.connect(
            lambda _id=entry_id: self._on_download_cancelled(_id))
        self.queue_changed.emit()

    def _on_download_cancelled(self, entry_id):
        entry = self._entry_by_id(entry_id)
        if entry is not None:
            entry["worker"] = None
            entry["status"] = "canceled"
        if self._active_entry is entry:
            self._active_entry = None
        self.queue_changed.emit()
        self._pump()

    def _on_download_progress(self, message):
        entry = self._entry_by_id(message.get("entry_id"))
        if entry is None or entry.get("status") != "downloading":
            self.progress.emit(message)
            return
        entry["received"] = message.get("received", entry["received"])
        entry["total"] = message.get("total", entry["total"])
        entry["text"] = message.get("text", "")
        self.progress.emit(message)
        self.queue_changed.emit()

    def _discard_archive(self, dest):
        # drop whatever a cancelled job left behind
        for path in (dest, dest + ".part", dest + ".part.json"):
            try:
                os.remove(path)
            except OSError:
                pass

    def _on_download_done(self, payload):
        job = payload["job"]
        entry = self._entry_by_id(job.get("entry_id"))
        canceled = entry is not None and entry["status"] == "canceled"
        if entry is not None:
            entry["worker"] = None
        if self._active_entry is entry:
            self._active_entry = None
        if canceled:
            self._discard_archive(payload["dest"])
            self.queue_changed.emit()
            self._pump()
            return
        profile, file = job["profile"], job["file"]
        # a non-gamebanana source brings its own record
        record = job.get("record") or build_record(
            profile.get("mod_id"), file.get("id"), file.get("name"),
            file.get("md5", ""), file.get("date", ""),
            profile.get("version", ""), known_ids_for(profile))
        if entry is not None:
            entry["status"] = "ready"
            entry["dest"] = payload["dest"]
            entry["record"] = record
        self.archive_ready.emit({
            "archive": payload["dest"],
            "profile": profile,
            "file": file,
            "record": record,
            "context": job.get("context"),
            "entry_id": job.get("entry_id"),
        })
        self.queue_changed.emit()
        self._pump()

    def _on_download_error(self, message):
        worker = self.sender()
        entry = None
        if worker is not None:
            entry = next((item for item in self._queue
                          if item.get("worker") is worker), None)
        if entry is None:
            entry = self._active_entry
        canceled = entry is not None and entry["status"] == "canceled"
        if entry is not None:
            entry["worker"] = None
            if not canceled:
                entry["status"] = "error"
                entry["error"] = str(message)
        if self._active_entry is entry:
            self._active_entry = None
        if not canceled:
            self.failed.emit(str(message))
        self.queue_changed.emit()
        self._pump()

    def _entry_by_id(self, entry_id):
        return next((item for item in self._queue if item["id"] == entry_id),
                    None)

    def cancel_download(self, entry_id):
        entry = self._entry_by_id(entry_id)
        if entry is None:
            return
        worker = entry.get("worker")
        if worker is not None and hasattr(worker, "cancel"):
            worker.cancel()
        if entry["status"] in ("queued", "downloading"):
            entry["status"] = "canceled"
        if self._active_entry is entry:
            self._active_entry = None
            self._pump()
        self.queue_changed.emit()

    def mark_installed(self, entry_id):
        entry = self._entry_by_id(entry_id)
        if entry is not None:
            entry["status"] = "installed"
            self.queue_changed.emit()

    def clear_finished(self):
        self._queue = [item for item in self._queue
                        if item["status"] in ("queued", "downloading")]
        self.queue_changed.emit()

    # update checks live in gamebanana.updater

    def shutdown(self, timeout_ms=30000):
        # stop any in-flight jobs before teardown
        for entry in list(self._queue):
            worker = entry.get("worker")
            if worker is not None and hasattr(worker, "cancel"):
                worker.cancel()
        for thread, _worker in list(getattr(self, "_active_threads", [])):
            try:
                thread.quit()
                thread.wait(timeout_ms)
            except RuntimeError:
                pass

    def _on_error(self, message):
        self.failed.emit(message)
