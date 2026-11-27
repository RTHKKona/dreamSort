# sidecar extras for a github source

import time

from ..gamebanana.links import read_record, write_record


def source(record):
    github = (record or {}).get("github") or {}
    if not github.get("owner") or not github.get("repo"):
        return None
    return github


def link(mod_dir, owner, repo, tag="", asset=""):
    # adds the source and keeps whatever gamebanana fields are there
    record = read_record(mod_dir) or {}
    record["github"] = {
        "owner": owner,
        "repo": repo,
        "tag": tag or "",
        "asset": asset or "",
        "linked_at": int(time.time()),
    }
    write_record(mod_dir, record)
    return record


def unlink(mod_dir):
    record = read_record(mod_dir)
    if not record or not record.get("github"):
        return False
    record.pop("github")
    write_record(mod_dir, record)
    return True


def keep_gamebanana(mod_dir, record):
    # the install rewrites the sidecar, so carry the gamebanana link over
    old = read_record(mod_dir) or {}
    for key in ("gb_mod_id", "gb_file_id", "gb_known_file_ids"):
        if old.get(key) and not record.get(key):
            record[key] = old[key]
    return record
