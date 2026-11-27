# toggleable file logging
#
# a windowed exe has no console, so print/stderr vanish; the rotating file
# handler keeps a bounded, self-trimming log next to the executable.

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_FILE_NAME = "dreamsort.log"
MAX_BYTES = 1024 * 1024       # 1 MB per file
BACKUP_COUNT = 2              # ~3 MB total
LOGGER_NAME = "dreamsort"

# severity name -> logging level
_LEVELS = {
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

_logger = logging.getLogger(LOGGER_NAME)
_logger.setLevel(logging.DEBUG)
_logger.propagate = False

_state = {
    "enabled": False,
    "path": "",
    "file_handler": None,
    "stream_handler": None,
}


def _formatter():
    return logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")


def default_log_dir():
    # same base the frozen config uses: the folder holding the exe
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # project root when running from source
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _attach_stream():
    # console output for dev runs; stderr is None under a windowed exe
    if _state["stream_handler"] is not None or sys.stderr is None \
            or getattr(sys, "frozen", False):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_formatter())
    handler.setLevel(logging.DEBUG)
    _logger.addHandler(handler)
    _state["stream_handler"] = handler


def set_enabled(enabled):
    # flip the file handler without touching the console handler
    enabled = bool(enabled)
    handler = _state["file_handler"]
    if enabled and handler is None:
        try:
            handler = RotatingFileHandler(
                _state["path"], maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT, encoding="utf-8")
        except OSError as exc:
            # unwritable location; stay console-only
            _logger.warning("Could not open log file: %s", exc)
            _state["enabled"] = False
            return
        handler.setFormatter(_formatter())
        handler.setLevel(logging.DEBUG)
        _logger.addHandler(handler)
        _state["file_handler"] = handler
        _logger.info("File logging enabled at %s", _state["path"])
    elif not enabled and handler is not None:
        _logger.removeHandler(handler)
        handler.close()
        _state["file_handler"] = None
    _state["enabled"] = _state["file_handler"] is not None


def init_logging(enabled, log_dir=None):
    # always drop a prior file handler so its path cannot go stale
    existing = _state["file_handler"]
    if existing is not None:
        _logger.removeHandler(existing)
        existing.close()
        _state["file_handler"] = None
    _state["path"] = os.path.join(log_dir or default_log_dir(),
                                  LOG_FILE_NAME)
    _attach_stream()
    set_enabled(enabled)


def is_enabled():
    return _state["enabled"]


def log_path():
    return _state["path"]


# level shortcuts
def debug(message, *args, **kwargs):
    _logger.debug(message, *args, **kwargs)


def info(message, *args, **kwargs):
    _logger.info(message, *args, **kwargs)


def warning(message, *args, **kwargs):
    _logger.warning(message, *args, **kwargs)


def error(message, *args, **kwargs):
    _logger.error(message, *args, **kwargs)


def exception(message, *args, **kwargs):
    # appends the active traceback
    _logger.exception(message, *args, **kwargs)


def log_error(err):
    # render a DreamSortError at the level its severity maps to
    level = _LEVELS.get(getattr(err, "severity", "error"), logging.ERROR)
    _logger.log(level, "%s", err)
    tb_text = getattr(err, "traceback_text", "")
    if tb_text:
        _logger.log(level, "traceback:\n%s", tb_text.rstrip())


def install_excepthook():
    # catch truly uncaught crashes that would otherwise die silently
    sys.excepthook = _excepthook


def _excepthook(exc_type, exc, tb):
    _logger.critical("Uncaught exception", exc_info=(exc_type, exc, tb))


def install_qt_message_handler():
    # route Qt's own warnings into the same log
    from PySide6.QtCore import qInstallMessageHandler

    def handler(mode, context, message):
        level = _qt_level(mode)
        _logger.log(level, "Qt: %s", message)

    qInstallMessageHandler(handler)


def _qt_level(mode):
    # compare by value to avoid enum spelling differences across versions
    try:
        value = int(mode)
    except (TypeError, ValueError):
        return logging.INFO
    # 0 debug, 1 warning, 2 critical, 3 fatal, 4 info (Qt numeric order)
    return {
        0: logging.DEBUG,
        1: logging.WARNING,
        2: logging.ERROR,
        3: logging.CRITICAL,
        4: logging.INFO,
    }.get(value, logging.INFO)
