# gb api client

import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request

from .urls import page_url

API_BASE = "https://gamebanana.com/apiv11/Mod/%s/ProfilePage"
FILE_URL = "https://gamebanana.com/dl/%s"
USER_AGENT = "dreamSort/7.2 (mod manager; https://gamebanana.com/tools/20124)"
JITTER = (0.8, 1.5)


class GBError(Exception):
    # network or response problem, with what to do about it
    def __init__(self, message, status=None, retryable=True, gone=False,
                 retry_after=0):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.gone = gone            # 404 / 410, never retried
        self.retry_after = retry_after


def _retry_after(headers):
    # only the plain seconds form is worth reading
    try:
        return max(int(str(headers.get("Retry-After") or "").strip()), 0)
    except (TypeError, ValueError):
        return 0


def _pause(attempt, retry_after=0):
    # jittered backoff, or whatever the server asked for
    if retry_after:
        return retry_after
    return random.uniform(*JITTER) * (attempt + 1)


def _text(value, default=""):
    if value in (None, ""):
        return default
    return str(value)


def _name_of(raw):
    # category blocks carry a single name field
    if not isinstance(raw, dict):
        return ""
    return _text(raw.get("_sName"))


class GameBananaClient:
    # thin client, all fields treated as optional

    def __init__(self, timeout=15, cache_ttl=300):
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self.attempts = 3
        self._cache = {}
        self._sleep = time.sleep

    def fetch_profile(self, mod_id):
        return self.fetch_profile_meta(mod_id)[0]

    def fetch_profile_meta(self, mod_id, force=False):
        # profile plus the response facts worth caching
        mod_id = str(mod_id)
        cached = self._cache.get(mod_id)
        if cached and not force and cached[0] > time.time():
            return cached[1], cached[2]
        raw, meta = self._request_json(API_BASE % mod_id)
        profile = self.parse_profile(raw, mod_id)
        meta["fetched_at"] = int(time.time())
        self._cache[mod_id] = (time.time() + self.cache_ttl, profile, meta)
        return profile, meta

    def _request_json(self, url):
        # one request, retried only when the failure looks temporary
        last = None
        for attempt in range(self.attempts):
            try:
                request = urllib.request.Request(
                    url, headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "application/json",
                    })
                with urllib.request.urlopen(
                        request, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    status = getattr(resp, "status", 200)
                    headers = dict(resp.headers)
            except urllib.error.HTTPError as exc:
                status = exc.code
                gone = status in (404, 410)
                retryable = (not gone) and (status >= 500 or status == 429
                                            or status in (408, 425))
                error = GBError("GameBanana returned %d for that page."
                                % status, status=status, retryable=retryable,
                                gone=gone,
                                retry_after=_retry_after(exc.headers))
                if not retryable:
                    raise error
                last = error
                self._sleep(_pause(attempt, error.retry_after))
                continue
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = GBError("Could not reach GameBanana: %s" % exc)
                self._sleep(_pause(attempt))
                continue
            try:
                data = json.loads(body)
            except ValueError:
                # a broken body will not fix itself, no retry
                raise GBError("GameBanana sent something unreadable.",
                              status=status, retryable=False)
            return data, {"http": status, "etag": headers.get("ETag", "")}
        raise last or GBError("Could not reach GameBanana.")

    def probe_file(self, file_id):
        # a bare dl link says nothing about the file, the cdn redirect does
        file_id = str(file_id)
        url = FILE_URL % file_id
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                final = resp.geturl()
        except (urllib.error.URLError, urllib.error.HTTPError,
                TimeoutError, OSError) as exc:
            raise GBError("Could not reach that download link: %s" % exc)
        name = os.path.basename(urllib.parse.urlsplit(final).path)
        name = urllib.parse.unquote(name) or ("file-%s.zip" % file_id)
        return {"id": file_id, "name": name, "size": 0, "date": "",
                "md5": "", "url": url, "integrations": []}

    @staticmethod
    def parse_profile(raw, mod_id):
        if not isinstance(raw, dict):
            raise GBError("Unexpected response from GameBanana.")
        submitter = raw.get("_aSubmitter")
        author = _text(submitter.get("_sName")) \
            if isinstance(submitter, dict) else ""
        files = []
        remote_install = False
        for item in raw.get("_aFiles") or []:
            if not isinstance(item, dict):
                continue
            file_id = _text(item.get("_idRow"))
            integrations = []
            for integration in item.get("_aModManagerIntegrations") or []:
                if not isinstance(integration, dict):
                    continue
                integrations.append({
                    "alias": _text(integration.get("_sModManagerAlias")),
                    "url": _text(integration.get("_sDownloadUrl")),
                    "installer": _text(integration.get("_sInstallerName")),
                    "tool_id": _text(integration.get("_idToolRow")),
                    "supports_remote": bool(
                        integration.get("_bSupportsRemoteInstall")),
                })
                if integration.get("_bSupportsRemoteInstall"):
                    remote_install = True
            files.append({
                "id": file_id,
                "name": _text(item.get("_sFile")),
                "size": int(item.get("_nFilesize") or 0),
                "date": _text(item.get("_tsDateAdded")),
                "md5": _text(item.get("_sMd5Checksum")),
                "url": _text(item.get("_sDownloadUrl"))
                       or (FILE_URL % file_id if file_id else ""),
                "integrations": integrations,
            })
        game = raw.get("_aGame")
        game = game if isinstance(game, dict) else {}
        return {
            "mod_id": str(mod_id),
            "name": _text(raw.get("_sName"), "Unknown mod"),
            "author": author,
            "version": _text(raw.get("_sVersion")),
            "updated_at": _text(raw.get("_tsDateModified")),
            "page_url": _text(raw.get("_sProfileUrl")) or page_url(mod_id),
            "game": {
                "id": _text(game.get("_idRow")),
                "name": _text(game.get("_sName")),
                "abbrev": _text(game.get("_sAbbreviation")),
            },
            "category": _name_of(raw.get("_aCategory")),
            "super_category": _name_of(raw.get("_aSuperCategory")),
            "files": files,
            "remote_install": remote_install,
        }
