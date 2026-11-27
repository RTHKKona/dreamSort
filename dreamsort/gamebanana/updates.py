# update comparison

import os

from .policy import archive_usable

# statuses a page can give for one installed record
UNLINKED = "unlinked"
UNKNOWN = "unknown"
GONE = "installed_gone"
CURRENT = "up_to_date"
UPDATE = "update_available"
CHOICE = "needs_choice"

# statuses that would download something
ACTIONABLE = (UPDATE,)


def _file_id(file):
    try:
        return int(file.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def _usable_files(page):
    # files we could actually open once downloaded
    files = page.get("files") if isinstance(page, dict) else None
    return [file for file in (files or [])
            if archive_usable(file.get("name"))]


def _newest_first(files):
    return sorted(files, key=_file_id, reverse=True)


def _norm(value):
    return str(value or "").strip().lower()


def _as_id(value):
    # ids are ints in the api, strings in the sidecar
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _md5_changed(installed, offered):
    # only counts when both sides actually have a hash
    a, b = _norm(installed), _norm(offered)
    return bool(a and b and a != b)


def _known_ids(record):
    # written on install, older sidecars may carry the short key
    raw = (record.get("gb_known_file_ids")
           or record.get("known_file_ids") or [])
    return {_norm(value) for value in raw if _norm(value)}


def evaluate(record, page):
    # status, the file that would replace the installed one, other options
    if not record:
        return UNLINKED, None, []
    usable = _usable_files(page)
    if not usable:
        return UNKNOWN, None, []

    installed = _as_id(record.get("gb_file_id"))
    ids = {_norm(file.get("id")) for file in usable}
    if installed and _norm(installed) not in ids:
        # what we installed is not offered any more: name the newest, never auto
        return GONE, _newest_first(usable)[0], []

    known = _known_ids(record)
    if known:
        # newer only within the lineage of what was installed
        candidates = [f for f in usable if _norm(f.get("id")) not in known]
    elif len(usable) == 1:
        only = usable[0]
        if installed and _norm(only.get("id")) == _norm(installed):
            if _md5_changed(record.get("md5"), only.get("md5")):
                return UPDATE, only, []
            return CURRENT, None, []
        candidates = usable
    else:
        # no lineage recorded on a page with options: the user picks,
        # and the copy already installed is not one of the options
        others = [f for f in usable
                  if not (installed and _norm(f.get("id")) == _norm(installed))]
        return CHOICE, None, _newest_first(others or usable)

    if len(candidates) > 1:
        return CHOICE, None, _newest_first(candidates)
    if len(candidates) == 1:
        return UPDATE, candidates[0], []

    # nothing new: a file replaced under the same id still counts
    if installed:
        match = next((f for f in usable
                      if _norm(f.get("id")) == _norm(installed)), None)
        if match and _md5_changed(record.get("md5"), match.get("md5")):
            return UPDATE, match, []
    return CURRENT, None, []


def known_ids_for(page, record=None):
    # ids visible now, so a later check can tell new from old
    ids = {_norm(file.get("id")) for file in _usable_files(page)}
    ids |= _known_ids(record or {})
    return sorted(ids, key=_as_id)


def pick_installable_file(page, record, want_id=None):
    # newest usable file, pinned to the one already installed when possible
    files = _usable_files(page)
    if not files:
        return None
    files = _newest_first(files)
    if want_id:
        match = next((f for f in files if _norm(f["id"]) == _norm(want_id)), None)
        if match:
            return match
    if record:
        file_id = _norm(record.get("gb_file_id"))
        if file_id:
            match = next((f for f in files if _norm(f["id"]) == file_id), None)
            if match:
                return match
        filename = record.get("filename") or ""
        if filename:
            stem = os.path.splitext(filename)[0].lower()
            same = [f for f in files
                    if os.path.splitext(f["name"])[0].lower() == stem]
            if len(same) == 1:
                return same[0]
    return files[0]
