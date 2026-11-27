# resumable download

import hashlib
import http.client
import json
import os
import time
import urllib.error
import urllib.request

from PySide6.QtCore import Signal

from ..errors import ErrorCode
from .thread_worker import Worker

CHUNK = 64 * 1024
MAX_ATTEMPTS = 3
ROUNDS = 2


class DownloadWorker(Worker):
    # one file, resumed from the .part if possible

    cancelled = Signal()

    def __init__(self, job):
        super().__init__(lambda: None)
        self.job = job
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _state_path(self):
        return self.job["dest"] + ".part.json"

    def _partial_path(self):
        return self.job["dest"] + ".part"

    def _load_state(self):
        try:
            with open(self._state_path(), "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, ValueError):
            return {}
        return state if isinstance(state, dict) else {}

    def _save_state(self, state):
        try:
            with open(self._state_path(), "w", encoding="utf-8") as handle:
                json.dump(state, handle)
        except OSError:
            pass

    def _discard_partial(self):
        # a bad body must not be resumed
        for path in (self._partial_path(), self._state_path()):
            try:
                os.remove(path)
            except OSError:
                pass

    def _fetch_once(self, headers):
        request = urllib.request.Request(self.job["url"], headers=headers)
        return urllib.request.urlopen(request, timeout=self.job.get("timeout", 30))

    def run(self):
        dest = self.job["dest"]
        url = self.job["url"]
        expected_md5 = (self.job.get("expected_md5") or "").lower()
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        state = self._load_state()
        if state.get("url") != url:
            state = {}
        message = "Download failed."
        for round_index in range(ROUNDS):
            if round_index:
                # the previous body did not survive the checksum
                self._discard_partial()
                state = {}
            outcome, message = self._attempt(url, expected_md5, state)
            if outcome == "cancel":
                self.cancelled.emit()
                return
            if outcome == "ok":
                os.replace(self._partial_path(), dest)
                try:
                    os.remove(self._state_path())
                except OSError:
                    pass
                self.finished.emit({"dest": dest, "job": self.job})
                return
        self._discard_partial()
        code = (ErrorCode.CHECKSUM_MISMATCH if "checksum" in message.lower()
                else ErrorCode.DOWNLOAD_FAILED)
        self.fail(message, code=code)

    def _attempt(self, url, expected_md5, state):
        # one burst of resumes, then the caller may restart clean
        partial = self._partial_path()
        for attempt in range(MAX_ATTEMPTS):
            if self._cancel:
                return "cancel", ""
            start = os.path.getsize(partial) if os.path.exists(partial) else 0
            headers = {"User-Agent": "dreamSort/7.2"}
            if start:
                headers["Range"] = "bytes=%d-" % start
                if state.get("etag"):
                    headers["If-Range"] = state["etag"]
            try:
                response = self._fetch_once(headers)
            except (urllib.error.URLError, urllib.error.HTTPError,
                    TimeoutError, OSError, http.client.HTTPException) as exc:
                if attempt == MAX_ATTEMPTS - 1:
                    return "bad", "Download failed: %s" % exc
                time.sleep(0.6 * (attempt + 1))
                continue

            with response:
                status = getattr(response, "status", 200)
                existing = start if status == 206 else 0
                total_header = response.headers.get("Content-Length")
                total = existing + int(total_header) if total_header else 0
                state["url"] = url
                state["etag"] = response.headers.get("ETag", "")
                self._save_state(state)

                mode = "ab" if existing else "wb"
                received = existing
                incomplete = False
                try:
                    with open(partial, mode) as out:
                        while True:
                            if self._cancel:
                                return "cancel", ""
                            chunk = response.read(CHUNK)
                            if not chunk:
                                break
                            out.write(chunk)
                            received += len(chunk)
                            self.progress.emit({
                                "received": received,
                                "total": total,
                                "text": self.job.get("label", "Downloading"),
                                "entry_id": self.job.get("entry_id"),
                            })
                except (OSError, http.client.HTTPException):
                    # a dropped connection otherwise looks like a clean eof
                    incomplete = True
                if not incomplete and total and received < total:
                    incomplete = True
                if incomplete:
                    if attempt == MAX_ATTEMPTS - 1:
                        return "bad", "Download failed: the connection kept dropping."
                    time.sleep(0.6 * (attempt + 1))
                    continue
            break
        else:
            return "bad", "Download failed after retries."

        if expected_md5:
            # read the finished file back, resumed pieces cannot be trusted
            actual = _hash_file(partial).hexdigest()
            if actual.lower() != expected_md5:
                return "bad", "Downloaded file failed the checksum."
        return "ok", ""


def _hash_file(path):
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest
