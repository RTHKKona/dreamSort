# profile snapshots matched by uploaded file identity

import time


def _norm(value):
    # loose compare for ids and hashes
    return str(value or "").strip().lower()


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def entry_from_record(record, enabled=True, order=0):
    # one profile row off a sidecar record
    record = record or {}
    return {
        "gb_mod_id": str(record.get("gb_mod_id") or ""),
        "gb_file_id": str(record.get("gb_file_id") or ""),
        "filename": record.get("filename") or "",
        "md5": record.get("md5") or "",
        "version": record.get("version") or "",
        "page_url": record.get("page_url") or "",
        "enabled": bool(enabled),
        "order": _to_int(order),
    }


def match_entry(entry, record):
    # matched / mismatch / none against one installed record
    if not record:
        return "none"
    e_md5 = _norm(entry.get("md5"))
    r_md5 = _norm(record.get("md5"))
    e_mid = _norm(entry.get("gb_mod_id"))
    r_mid = _norm(record.get("gb_mod_id"))
    e_fid = _norm(entry.get("gb_file_id"))
    r_fid = _norm(record.get("gb_file_id"))

    if e_md5 and r_md5 and e_md5 == r_md5:
        return "matched"
    if e_mid and r_mid and e_mid != r_mid:
        # plainly different mods, the hashes say nothing useful
        return "none"
    if e_md5 and r_md5:
        # same mod, different upload
        return "mismatch"
    if e_fid and r_fid and e_fid == r_fid:
        return "matched"
    if e_mid and r_mid:
        return "mismatch"
    if _norm(entry.get("filename")) == _norm(record.get("filename")):
        return "matched"
    return "none"


def compare(entries, installed):
    # split the current install against a saved profile
    matched = []
    missing = []
    mismatched = []
    used = set()
    installed = list(installed or [])

    for entry in entries:
        mid = _norm(entry.get("gb_mod_id"))
        candidate = None
        if mid:
            for index, item in enumerate(installed):
                if index in used:
                    continue
                if _norm((item.get("record") or {}).get("gb_mod_id")) == mid:
                    candidate = index
                    break
        if candidate is None:
            fid = _norm(entry.get("gb_file_id"))
            if fid:
                for index, item in enumerate(installed):
                    if index in used:
                        continue
                    if _norm((item.get("record") or {}).get("gb_file_id")) == fid:
                        candidate = index
                        break
        record = installed[candidate]["record"] if candidate is not None else None
        status = match_entry(entry, record)
        if status == "matched":
            matched.append({"entry": entry, "installed": installed[candidate]})
            used.add(candidate)
        elif status == "mismatch":
            mismatched.append({"entry": entry, "installed": installed[candidate]})
            used.add(candidate)
        else:
            missing.append(entry)

    extra = [item for index, item in enumerate(installed) if index not in used]
    return {
        "matched": matched,
        "missing": missing,
        "mismatched": mismatched,
        "extra": extra,
    }


def build_profile(entries, mode):
    # persisted profile object
    return {
        "mode": mode,
        "updated_at": int(time.time()),
        "entries": list(entries),
    }


def normalize_profile(data):
    # keep what we can read from an imported profile
    if not isinstance(data, dict):
        return None
    entries = data.get("entries")
    if not isinstance(entries, list):
        return None
    clean = []
    seen = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        entry = {
            "gb_mod_id": str(item.get("gb_mod_id") or ""),
            "gb_file_id": str(item.get("gb_file_id") or ""),
            "filename": item.get("filename") or "",
            "md5": item.get("md5") or "",
            "version": item.get("version") or "",
            "page_url": item.get("page_url") or "",
            "enabled": bool(item.get("enabled", True)),
            "order": _to_int(item.get("order")),
        }
        # one row per uploaded file, duplicates would double count
        key = (_norm(entry["md5"]), _norm(entry["gb_file_id"]),
               _norm(entry["gb_mod_id"]), _norm(entry["filename"]))
        if key in seen:
            continue
        seen.add(key)
        clean.append(entry)
    return {"mode": data.get("mode", ""),
            "updated_at": _to_int(data.get("updated_at")),
            "entries": clean}
