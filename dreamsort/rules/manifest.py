# manifest reader, txt and json

import json
import os
import re

from .model import valid_id

MANIFEST_NAMES = ["manifest.json", "manifest.txt", "mod.txt", "info.txt",
                  "mod.json", "info.json", "plugin.json"]
_GENERIC_JSON = {"mod.json", "info.json", "plugin.json"}
MAX_BYTES = 64 * 1024

_KEY_ALIASES = {
    "manifestversion": "manifest_version",
    "id": "id",
    "version": "version",
    "name": "name",
    "modname": "name",
    "mod": "name",
    "title": "name",
    "authors": "authors",
    "author": "authors",
    "description": "description",
    "summary": "description",
    "gamebananapage": "page_url",
    "gamebananalink": "page_url",
    "gamebananaurl": "page_url",
    "pageurl": "page_url",
    "url": "page_url",
    "link": "page_url",
    "requires": "requires",
    "conflicts": "conflicts",
    "load": "load",
    "loadafter": "load_after",
    "loadbefore": "load_before",
    "options": "options",
}

_OPS = (">=", "<=", "==", "!=", ">", "<")


def find_manifest(mod_dir):
    for name in MANIFEST_NAMES:
        path = os.path.join(mod_dir, name)
        if os.path.isfile(path):
            return path
    return None


def _norm_key(key):
    # drop punctuation like "author(s)" and any BOM artefact
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _strip_quotes(value):
    text = str(value).strip()
    if len(text) < 2:
        return text
    if text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1].strip()
    if text[0] in "\"\u201c\u2018\u00ab" and text[-1] in "\"\u201d\u2019\u00bb":
        return text[1:-1].strip()
    return text


def _req_token(token):
    token = token.strip()
    if not token:
        return None
    for op in _OPS:
        if op in token:
            ref, _, constraint = token.partition(op)
            return ref.strip(), op + (constraint.strip() or "*")
    return token, "*"


def _req_map(value):
    out = {}
    if isinstance(value, dict):
        for ref, constraint in value.items():
            out[str(ref).strip()] = str(constraint or "*").strip() or "*"
    elif isinstance(value, str):
        for token in value.split(","):
            parsed = _req_token(token)
            if parsed:
                out[parsed[0]] = parsed[1]
    return out


def _str_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _parse_txt(text):
    data = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        data[_norm_key(key)] = _strip_quotes(value)
    return data


def _normalize(data, filename):
    warnings = []
    if not isinstance(data, dict):
        return None, ["manifest is not an object"]

    mapped = {}
    for key, value in data.items():
        mapped[_KEY_ALIASES.get(_norm_key(key), _norm_key(key))] = value

    mod_id = str(mapped.get("id") or "").strip()
    # authors write their display name; the canonical id is lowercase
    if mod_id and valid_id(mod_id.lower()):
        mod_id = mod_id.lower()
    else:
        # still keep the display metadata; rules layer drops the entry
        mod_id = None
        warnings.append("invalid or missing manifest id")

    manifest_version = mapped.get("manifest_version")
    if isinstance(manifest_version, int) and manifest_version > 1:
        warnings.append("manifest_version %d is newer than supported"
                        % manifest_version)

    load = mapped.get("load") if isinstance(mapped.get("load"), dict) else {}
    after = _str_list(load.get("after", mapped.get("load_after")))
    before = _str_list(load.get("before", mapped.get("load_before")))

    authors = mapped.get("authors")
    if isinstance(authors, str):
        authors = _str_list(authors)

    return {
        "id": mod_id,
        "version": str(mapped.get("version") or "").strip() or None,
        "name": str(mapped.get("name") or "").strip(),
        "authors": tuple(authors or []),
        "description": str(mapped.get("description") or "").strip(),
        "page_url": str(mapped.get("page_url") or "").strip(),
        "requires": _req_map(mapped.get("requires")),
        "conflicts": _req_map(mapped.get("conflicts")),
        "load_after": tuple(after),
        "load_before": tuple(before),
        "options": mapped.get("options") if isinstance(mapped.get("options"),
                                                        dict) else {},
    }, warnings


def _read_file(path):
    # (normalized data or None, warnings); (None, []) means "not a manifest"
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return None, ["%s is too large" % os.path.basename(path)]
        with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
            text = handle.read(MAX_BYTES)
    except OSError:
        return None, ["%s is unreadable" % os.path.basename(path)]

    filename = os.path.basename(path).lower()
    if filename.endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError:
            return None, ["%s has invalid json" % filename]
        if filename in _GENERIC_JSON and not (
                isinstance(data, dict) and ("id" in data or "manifest_version" in data)):
            return None, []
    else:
        data = _parse_txt(text)

    return _normalize(data, filename)


def read_manifest(mod_dir):
    # walks the candidates in priority order, first usable one wins
    warnings = []
    for name in MANIFEST_NAMES:
        path = os.path.join(mod_dir, name)
        if not os.path.isfile(path):
            continue
        data, notes = _read_file(path)
        warnings.extend(notes)
        if data is not None:
            return data, warnings
    return None, warnings
