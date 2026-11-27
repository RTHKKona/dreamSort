# backup-swap-commit

import json
import os
import shutil

from ..helpers.layout import sanitize_name
from ..storage.atomic import atomic_write_json, _remove_quietly

STAGING_PREFIX = "ds_drop_"
BACKUP_SUFFIX = ".ds_bak"
JOURNAL_NAME = ".dreamsort_commit.json"
SIDECAR_NAME = ".dreamsort.json"


def _journal_path(target_dir):
    return os.path.join(target_dir, JOURNAL_NAME)


def _write_journal(target_dir, payload):
    atomic_write_json(_journal_path(target_dir), payload)


def _clear_journal(target_dir):
    _remove_quietly(_journal_path(target_dir))


def _drop_tree(path):
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.exists(path):
        _remove_quietly(path)


def write_sidecar(mod_dir, record):
    # per-mod record that follows the folder around
    if not record:
        return
    atomic_write_json(os.path.join(mod_dir, SIDECAR_NAME), record)


def commit_mod(source, target_dir, dest_name, record=None):
    # swap the old mod out only after the new one is staged
    if not os.path.isdir(source):
        raise FileNotFoundError("Staged mod folder not found: %s" % source)
    dest_name = sanitize_name(dest_name)
    os.makedirs(target_dir, exist_ok=True)
    destination = os.path.join(target_dir, dest_name)
    backup = destination + BACKUP_SUFFIX

    had_backup = os.path.exists(backup)
    if os.path.exists(destination):
        if had_backup:
            _drop_tree(backup)
        shutil.move(destination, backup)
        had_backup = True

    journal = {
        "destination": destination,
        "backup": backup if had_backup else "",
        "source": source,
    }
    _write_journal(target_dir, journal)

    try:
        shutil.move(source, destination)
        if record:
            write_sidecar(destination, record)
        if had_backup:
            _drop_tree(backup)
        _clear_journal(target_dir)
    except BaseException:
        # put the old one back if we can
        if os.path.exists(backup):
            _drop_tree(destination)
            shutil.move(backup, destination)
        else:
            _drop_tree(destination)
        _clear_journal(target_dir)
        raise
    return destination


def recover_interrupted(target_dir):
    # undo a swap that did not finish last launch
    if not os.path.isdir(target_dir):
        return
    journal_path = _journal_path(target_dir)
    try:
        with open(journal_path, "r", encoding="utf-8") as handle:
            journal = json.load(handle)
    except (OSError, ValueError):
        return
    destination = journal.get("destination", "")
    backup = journal.get("backup", "")
    if backup and os.path.isdir(backup):
        _drop_tree(destination)
        try:
            shutil.move(backup, destination)
        except OSError:
            pass
    else:
        _drop_tree(destination)
    _clear_journal(target_dir)


def sweep_dir(target_dir):
    # drop old staging and backup leftovers
    if not os.path.isdir(target_dir):
        return
    try:
        names = os.listdir(target_dir)
    except OSError:
        return
    for name in names:
        full = os.path.join(target_dir, name)
        if name.startswith(STAGING_PREFIX) or name.endswith(BACKUP_SUFFIX):
            _drop_tree(full)


def is_scratch_name(name):
    # staging, backup or dotfile the scanners should skip
    return (name.startswith(STAGING_PREFIX) or name.endswith(BACKUP_SUFFIX)
            or name.startswith("."))
