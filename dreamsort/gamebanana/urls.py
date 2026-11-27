# link parsing

import re
from urllib.parse import parse_qs, urlsplit

ALLOWED_HOSTS = {"gamebanana.com", "www.gamebanana.com"}
MOD_PATH_RE = re.compile(r"^/(?:mods|Mod)/(?:download/)?(\d+)", re.I)
FILE_PATH_RE = re.compile(r"^/(?:mmdl|dl)/(\d+)(?:,[^,]+,[^,]+)?$", re.I)
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
PROTO_PREFIX = "drmsrt:"


def page_url(mod_id):
    # public page for the mod
    if not mod_id:
        return ""
    return "https://gamebanana.com/mods/%s" % mod_id


def _strip_alias(raw):
    # tools hand over their own alias, only the url behind it matters
    match = SCHEME_RE.match(raw)
    if not match:
        return raw
    scheme = match.group(0)[:-1].lower()
    if scheme in ("http", "https"):
        return raw
    return raw[match.end():]


def _parse_web_url(raw):
    parts = urlsplit(raw if "://" in raw else "https://" + raw)
    if parts.netloc.lower() not in ALLOWED_HOSTS:
        return None
    path = parts.path.rstrip("/")
    file_match = FILE_PATH_RE.match(path)
    if file_match:
        # mmdl carries the submission after the file id, dl does not
        pieces = path.split("/")[-1].split(",")
        mod_id = pieces[2] if len(pieces) > 2 else None
        return {
            "mod_id": mod_id,
            "file_id": file_match.group(1),
            "url": page_url(mod_id),
            "source": "mmdl" if len(pieces) > 1 else "file",
        }
    match = MOD_PATH_RE.match(path)
    if not match:
        return None
    query = parse_qs(parts.query)
    file_id = (query.get("fileid") or query.get("file") or [None])[0]
    return {
        "mod_id": match.group(1),
        "file_id": str(file_id) if file_id else None,
        "url": page_url(match.group(1)),
        "source": "page",
    }


def parse_link(text):
    # accept a gb page, a download link or an alias payload
    if not text:
        return None
    raw = str(text).strip().strip('"').strip("'")
    if not raw:
        return None
    raw = _strip_alias(raw).strip()
    if not raw:
        return None
    if raw.startswith("//"):
        # protocol handlers sometimes double up the slash
        raw = raw.lstrip("/")
    if re.fullmatch(r"\d+", raw):
        return {"mod_id": raw, "file_id": None, "url": page_url(raw),
                "source": "id"}
    if raw.lower().startswith("mod/"):
        mod_id = raw[4:].strip("/")
        if mod_id.isdigit():
            return {"mod_id": mod_id, "file_id": None,
                    "url": page_url(mod_id), "source": "id"}
        return None
    return _parse_web_url(raw)


def is_gb_link(text):
    return parse_link(text) is not None
