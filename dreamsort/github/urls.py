# repo links

import re

WEB = "https://github.com/%s/%s"
_NAME = re.compile(r"^[0-9A-Za-z._-]+$")


def repo_url(owner, repo):
    return WEB % (owner, repo)


def _clean(text):
    # strip the parts that only decorate a link
    raw = str(text or "").strip().strip("<>\"'")
    if not raw:
        return ""
    if raw.lower().startswith("git@github.com:"):
        raw = raw[len("git@github.com:"):]
    elif "://" in raw:
        raw = raw.split("://", 1)[1]
    low = raw.lower()
    if low.startswith("github.com/"):
        raw = raw[len("github.com/"):]
    elif "github.com/" in low:
        raw = raw[low.index("github.com/") + len("github.com/"):]
    raw = raw.split("?", 1)[0].split("#", 1)[0]
    return raw.strip("/")


def parse_repo(text):
    # owner, repo and the tag when the link names a release
    raw = _clean(text)
    if not raw:
        return None
    parts = [part for part in raw.split("/") if part]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not _NAME.match(owner) or not _NAME.match(repo):
        return None
    tag = ""
    if len(parts) >= 5 and parts[2] == "releases" and parts[3] == "tag":
        tag = parts[4]
    return {"owner": owner, "repo": repo, "tag": tag,
            "url": repo_url(owner, repo)}


def key_of(owner, repo):
    # cache key, github treats owner and repo as case-insensitive
    return ("%s/%s" % (owner, repo)).lower()
