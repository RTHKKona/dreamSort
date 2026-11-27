# releases api

import json
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com/repos/%s/%s/releases"
USER_AGENT = "dreamSort/7.2 (mod manager)"
TIMEOUT = 15


class GitHubError(Exception):
    # network, api or rate limit problem, phrased for the ui
    def __init__(self, message, status=None, retryable=False,
                 rate_limited=False, gone=False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.rate_limited = rate_limited
        self.gone = gone


def _remaining(headers):
    try:
        return int(str(headers.get("X-RateLimit-Remaining") or "").strip())
    except (TypeError, ValueError):
        return -1


def _reset_in(headers):
    try:
        reset = int(str(headers.get("X-RateLimit-Reset") or "").strip())
    except (TypeError, ValueError):
        return 0
    return max(reset - int(time.time()), 0)


class GitHubClient:
    # latest release per repo, answers kept in memory for a while

    def __init__(self, token="", timeout=TIMEOUT, cache_ttl=300):
        self.token = str(token or "").strip()
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._cache = {}
        self._sleep = time.sleep

    def _headers(self):
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        return headers

    def _get(self, url):
        request = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            headers = dict(exc.headers or {})
            status = exc.code
            if status == 404:
                raise GitHubError("No such repository or no releases yet.",
                                  status=status, gone=True)
            limited = status == 403 and _remaining(headers) == 0
            if status == 403 and not limited:
                raise GitHubError("GitHub refused that request.", status=status)
            if limited:
                wait = _reset_in(headers)
                raise GitHubError(
                    "GitHub's hourly quota is used up, try again in %d minute%s."
                    % (max(wait // 60, 1), "" if wait // 60 == 1 else "s"),
                    status=status, rate_limited=True,
                    retryable=wait > 0)
            raise GitHubError("GitHub returned %d." % status, status=status,
                              retryable=status >= 500)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GitHubError("Could not reach GitHub: %s" % exc, retryable=True)
        except ValueError:
            raise GitHubError("GitHub sent something unreadable.")

    def latest_release(self, owner, repo, force=False):
        # release dict plus the request facts, latest first
        key = ("%s/%s" % (owner, repo)).lower()
        cached = self._cache.get(key)
        if cached and not force and cached[0] > time.time():
            return cached[1], cached[2]
        release, meta = self._fetch(owner, repo)
        self._cache[key] = (time.time() + self.cache_ttl, release, meta)
        return release, meta

    def _fetch(self, owner, repo):
        base = API % (urllib.parse.quote(owner), urllib.parse.quote(repo))
        try:
            raw, headers = self._get(base + "/latest")
        except GitHubError as exc:
            if not exc.gone:
                raise
            # a repo that only ships prereleases has no "latest"
            raw, headers = self._newest_of(base)
        return parse_release(raw, owner, repo), {
            "http": 200, "remaining": _remaining(headers)}

    def _newest_of(self, base):
        raw, headers = self._get(base + "?per_page=10")
        if not isinstance(raw, list) or not raw:
            raise GitHubError("That repository has no published releases.",
                              gone=True)
        for item in raw:
            if isinstance(item, dict) and not item.get("draft"):
                return item, headers
        raise GitHubError("That repository has no published releases.",
                          gone=True)


def parse_release(raw, owner, repo):
    # only the fields the manager needs, everthing else stays behind
    if not isinstance(raw, dict):
        raise GitHubError("Unexpected release from GitHub.")
    tag = str(raw.get("tag_name") or "").strip()
    assets = []
    for item in raw.get("assets") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("browser_download_url") or "").strip()
        if not url:
            continue
        assets.append({
            "name": str(item.get("name") or "").strip(),
            "url": url,
            "size": int(item.get("size") or 0),
        })
    return {
        "owner": owner,
        "repo": repo,
        "tag": tag,
        "name": str(raw.get("name") or tag).strip(),
        "published_at": str(raw.get("published_at") or ""),
        "html_url": str(raw.get("html_url") or ""),
        "prerelease": bool(raw.get("prerelease")),
        "draft": bool(raw.get("draft")),
        "assets": assets,
        "zipball": str(raw.get("zipball_url") or ""),
    }
