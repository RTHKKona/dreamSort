# storage

import os
import sys

from . import config as _config
from .atomic import (
    atomic_copy_file,
    atomic_write_json,
    atomic_write_text,
    _remove_quietly,
    _replace_with_retry,
    _sync_directory,
)
from .config import (
    CONFIG_NOTICES,
    read_config,
    resource_path,
    write_config,
    _parse_config_file,
)


def _app_root():
    # app dir
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    # repo root
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def config_path():
    # config path
    return os.path.join(_app_root(), "config.json")


# rebind config_path
_config.config_path = config_path

__all__ = [
    "atomic_copy_file",
    "atomic_write_json",
    "atomic_write_text",
    "CONFIG_NOTICES",
    "config_path",
    "read_config",
    "resource_path",
    "write_config",
]
