# atomic writes

import json
import os
import shutil
import tempfile
import time

def _replace_with_retry(tmp_path, target, attempts=5):
    # retry on windows
    for attempt in range(attempts):
        try:
            os.replace(tmp_path, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.1 * (attempt + 1))


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _sync_directory(directory):
    # fsync
    if os.name != "posix":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def atomic_write_text(path, text, encoding="utf-8", newline=None):
    """Write text to path."""
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as tmp_file:
            tmp_file.write(text)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        try:
            # keep the old permissions
            shutil.copymode(path, tmp_path)
        except OSError:
            pass
        _replace_with_retry(tmp_path, path)
    except BaseException:
        _remove_quietly(tmp_path)
        raise
    _sync_directory(directory)


def atomic_write_json(path, data, indent=2):
    # serialize first
    atomic_write_text(path, json.dumps(data, indent=indent))


def atomic_copy_file(src, dst):
    """Copy src over dst."""
    dst = os.path.abspath(dst)
    directory = os.path.dirname(dst)
    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=os.path.basename(dst) + ".", suffix=".tmp")
    os.close(fd)
    try:
        shutil.copy2(src, tmp_path)
        _replace_with_retry(tmp_path, dst)
    except BaseException:
        _remove_quietly(tmp_path)
        raise
    _sync_directory(directory)
