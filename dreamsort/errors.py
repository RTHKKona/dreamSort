# lightweight error catalog and catching framework
#
# numeric codes start at 0 and are grouped in blocks of ten so new codes
# can be added inside a category without renumbering the rest.

from __future__ import annotations

import functools
import sys
import traceback
from enum import IntEnum


class Severity:
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorCode(IntEnum):
    # generic 0-9
    UNKNOWN = 0
    CANCELLED = 1
    NOT_IMPLEMENTED = 2
    INVALID_ARGUMENT = 3
    INVALID_STATE = 4

    # storage and config 10-19
    CONFIG_READ = 10
    CONFIG_WRITE = 11
    CONFIG_INVALID = 12
    PATH_NOT_FOUND = 13
    PATH_INVALID = 14
    ACCESS_DENIED = 15
    DISK_FULL = 16
    ATOMIC_WRITE = 17

    # archive 20-29
    ARCHIVE_UNREADABLE = 20
    ARCHIVE_UNSUPPORTED = 21
    ARCHIVE_PASSWORD = 22
    ARCHIVE_TRAVERSAL = 23
    ARCHIVE_TOO_LARGE = 24
    ARCHIVE_TOO_MANY_FILES = 25
    ARCHIVE_EXECUTABLE = 26
    ARCHIVE_LINK = 27
    ARCHIVE_NO_BACKEND = 28

    # network 30-39
    NETWORK_UNREACHABLE = 30
    NETWORK_TIMEOUT = 31
    HTTP_STATUS = 32
    RATE_LIMITED = 33
    RESOURCE_GONE = 34
    BAD_RESPONSE = 35
    DOWNLOAD_FAILED = 36
    CHECKSUM_MISMATCH = 37

    # install and validation 50-59
    INSTALL_FAILED = 50
    MANIFEST_MISSING = 51
    MANIFEST_INVALID = 52
    UNSAFE_SCRIPT = 53
    TRIMMED_ARC = 54
    RULE_VIOLATION = 55

    # emulator and environment 70-79
    EMULATOR_NOT_FOUND = 70
    GAME_VERSION_MISMATCH = 71

    # special codes
    PIXELPACK_DETECTED = 1337


# code -> (default message, severity, retryable)
_SPECS = {
    ErrorCode.UNKNOWN: (
        "Something went wrong, but no details were recorded",
        Severity.ERROR, False),
    ErrorCode.CANCELLED: (
        "The operation was cancelled", Severity.INFO, False),
    ErrorCode.NOT_IMPLEMENTED: (
        "That feature is not available yet", Severity.ERROR, False),
    ErrorCode.INVALID_ARGUMENT: (
        "An argument was invalid", Severity.ERROR, False),
    ErrorCode.INVALID_STATE: (
        "The operation is not valid in the current state",
        Severity.ERROR, False),

    ErrorCode.CONFIG_READ: (
        "Settings could not be read", Severity.ERROR, False),
    ErrorCode.CONFIG_WRITE: (
        "Settings could not be saved", Severity.ERROR, False),
    ErrorCode.CONFIG_INVALID: (
        "Settings contain invalid values", Severity.ERROR, False),
    ErrorCode.PATH_NOT_FOUND: (
        "That file or folder no longer exists", Severity.ERROR, False),
    ErrorCode.PATH_INVALID: (
        "That path is not valid", Severity.ERROR, False),
    ErrorCode.ACCESS_DENIED: (
        "Permission was denied", Severity.ERROR, False),
    ErrorCode.DISK_FULL: (
        "The disk is full", Severity.ERROR, True),
    ErrorCode.ATOMIC_WRITE: (
        "Could not safely write the file", Severity.ERROR, False),

    ErrorCode.ARCHIVE_UNREADABLE: (
        "The archive could not be read", Severity.ERROR, False),
    ErrorCode.ARCHIVE_UNSUPPORTED: (
        "That archive type is not supported", Severity.ERROR, False),
    ErrorCode.ARCHIVE_PASSWORD: (
        "The archive is password protected", Severity.ERROR, False),
    ErrorCode.ARCHIVE_TRAVERSAL: (
        "The archive tries to write outside its destination folder",
        Severity.CRITICAL, False),
    ErrorCode.ARCHIVE_TOO_LARGE: (
        "The archive unpacks to too much data", Severity.ERROR, False),
    ErrorCode.ARCHIVE_TOO_MANY_FILES: (
        "The archive contains too many files", Severity.ERROR, False),
    ErrorCode.ARCHIVE_EXECUTABLE: (
        "The archive contains an executable file", Severity.ERROR, False),
    ErrorCode.ARCHIVE_LINK: (
        "The archive contains a link entry", Severity.ERROR, False),
    ErrorCode.ARCHIVE_NO_BACKEND: (
        "No tool is installed that can read that archive",
        Severity.ERROR, False),

    ErrorCode.NETWORK_UNREACHABLE: (
        "Could not reach the network", Severity.ERROR, True),
    ErrorCode.NETWORK_TIMEOUT: (
        "The network request timed out", Severity.ERROR, True),
    ErrorCode.HTTP_STATUS: (
        "The server returned an error", Severity.ERROR, False),
    ErrorCode.RATE_LIMITED: (
        "The server's rate limit was reached", Severity.WARNING, True),
    ErrorCode.RESOURCE_GONE: (
        "That page or file no longer exists", Severity.ERROR, False),
    ErrorCode.BAD_RESPONSE: (
        "The server sent an unreadable response", Severity.ERROR, False),
    ErrorCode.DOWNLOAD_FAILED: (
        "The download failed", Severity.ERROR, True),
    ErrorCode.CHECKSUM_MISMATCH: (
        "The downloaded file failed its checksum", Severity.ERROR, False),

    ErrorCode.INSTALL_FAILED: (
        "The mod could not be installed", Severity.ERROR, False),
    ErrorCode.MANIFEST_MISSING: (
        "No manifest was found at the mod root", Severity.ERROR, False),
    ErrorCode.MANIFEST_INVALID: (
        "The manifest is invalid", Severity.ERROR, False),
    ErrorCode.UNSAFE_SCRIPT: (
        "The mod ships script files", Severity.WARNING, False),
    ErrorCode.TRIMMED_ARC: (
        "The mod ships trimmed .arc files", Severity.WARNING, False),
    ErrorCode.RULE_VIOLATION: (
        "A mod rule was violated", Severity.ERROR, False),

    ErrorCode.EMULATOR_NOT_FOUND: (
        "The emulator installation was not found", Severity.ERROR, False),
    ErrorCode.GAME_VERSION_MISMATCH: (
        "The installed game version does not match",
        Severity.WARNING, False),

    ErrorCode.PIXELPACK_DETECTED: (
        "Pixelpack mod detected", Severity.WARNING, False),
}

_FALLBACK_SPEC = ("Uncatalogued error", Severity.ERROR, False)


def spec(code):
    # message, severity, retryable for a code
    return _SPECS.get(ErrorCode(code), _FALLBACK_SPEC)


def default_message(code):
    return spec(code)[0]


def severity_of(code):
    return spec(code)[1]


def is_retryable(code):
    return spec(code)[2]


class DreamSortError(Exception):
    # a catalogued failure; str() is the user-facing line and keeps the
    # [E<code>] number so it can be quoted in a bug report.

    def __init__(self, code, context="", details=None, retryable=None,
                 message=None, traceback_text=""):
        self.code = ErrorCode(code)
        self.context = str(context or "")
        self.details = details
        self._retryable_override = retryable
        self._message_override = message
        self.traceback_text = traceback_text
        super().__init__(str(self))

    @property
    def number(self):
        return int(self.code)

    @property
    def severity(self):
        return severity_of(self.code)

    @property
    def retryable(self):
        if self._retryable_override is not None:
            return self._retryable_override
        return is_retryable(self.code)

    def __str__(self):
        base = self._message_override or default_message(self.code)
        line = "[E%d] %s" % (self.number, base)
        if self.context:
            line += ": " + self.context
        return line


def _client_code(exc):
    # map the project's own client exceptions by class name so this module
    # stays a leaf and does not import the network clients.
    name = type(exc).__name__
    status = getattr(exc, "status", None)
    if name == "GBError":
        if getattr(exc, "gone", False):
            return ErrorCode.RESOURCE_GONE
        if status == 429:
            return ErrorCode.RATE_LIMITED
        if status is not None:
            return ErrorCode.HTTP_STATUS
        return ErrorCode.NETWORK_UNREACHABLE
    if name == "GitHubError":
        if getattr(exc, "rate_limited", False):
            return ErrorCode.RATE_LIMITED
        if getattr(exc, "gone", False):
            return ErrorCode.RESOURCE_GONE
        if status is not None:
            return ErrorCode.HTTP_STATUS
        return ErrorCode.NETWORK_UNREACHABLE
    if name == "ArchiveSafetyError":
        return _archive_code(str(exc))
    return None


def _archive_code(text):
    # archive errors carry their meaning in the message raised in archive.py
    lowered = text.lower()
    if any(word in lowered for word in ("escape", "outside", "absolute")):
        return ErrorCode.ARCHIVE_TRAVERSAL
    if "password" in lowered:
        return ErrorCode.ARCHIVE_PASSWORD
    if "executable" in lowered:
        return ErrorCode.ARCHIVE_EXECUTABLE
    if "link" in lowered:
        return ErrorCode.ARCHIVE_LINK
    if "too many" in lowered:
        return ErrorCode.ARCHIVE_TOO_MANY_FILES
    if any(word in lowered for word in ("too much", "too large", "far beyond")):
        return ErrorCode.ARCHIVE_TOO_LARGE
    if "not found" in lowered and "extractor" in lowered:
        return ErrorCode.ARCHIVE_NO_BACKEND
    if "unsupported" in lowered:
        return ErrorCode.ARCHIVE_UNSUPPORTED
    return ErrorCode.ARCHIVE_UNREADABLE


def _builtin_code(exc):
    if isinstance(exc, FileNotFoundError):
        return ErrorCode.PATH_NOT_FOUND
    if isinstance(exc, PermissionError):
        return ErrorCode.ACCESS_DENIED
    if isinstance(exc, (IsADirectoryError, NotADirectoryError)):
        return ErrorCode.PATH_INVALID
    if isinstance(exc, TimeoutError):
        return ErrorCode.NETWORK_TIMEOUT
    if isinstance(exc, NotImplementedError):
        return ErrorCode.NOT_IMPLEMENTED
    if isinstance(exc, ValueError):
        # JSONDecodeError is a ValueError
        if type(exc).__name__ == "JSONDecodeError":
            return ErrorCode.BAD_RESPONSE
        return ErrorCode.INVALID_ARGUMENT
    if isinstance(exc, TypeError):
        return ErrorCode.INVALID_ARGUMENT
    if isinstance(exc, OSError):
        if getattr(exc, "errno", None) == 28:
            return ErrorCode.DISK_FULL
        return ErrorCode.UNKNOWN
    return None


def infer_code(exc):
    return (_client_code(exc)
            or _builtin_code(exc)
            or ErrorCode.UNKNOWN)


def capture(exc, code=None, context=""):
    # normalize any exception into a DreamSortError, preserving the chain
    if isinstance(exc, DreamSortError):
        return exc
    resolved = ErrorCode(code) if code is not None else infer_code(exc)
    tb_text = "".join(traceback.format_exception(
        type(exc), exc, exc.__traceback__))
    err = DreamSortError(
        resolved,
        context=context or (str(exc) if resolved == ErrorCode.UNKNOWN else ""),
        traceback_text=tb_text)
    err.__cause__ = exc
    return err


def log_error(err):
    # delegate to the file logger when initialized; stderr as fallback
    try:
        from . import app_logging
        app_logging.log_error(err)
    except Exception:
        sys.stderr.write("%s\n" % err)


class error_guard:
    # catch around a block; default swallows after calling on_error so the
    # caller decides what recovery looks like.

    def __init__(self, code=None, *, context="", on_error=None,
                 reraise=False):
        self.code = code
        self.context = context
        self.on_error = on_error
        self.reraise = reraise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is None:
            return False
        err = capture(exc, code=self.code, context=self.context)
        traceback.print_exc()
        log_error(err)
        if self.on_error is not None:
            self.on_error(err)
        return not self.reraise


def guard(code=None, *, context="", on_error=None, reraise=True):
    # wrap a function so every raised exception is normalized

    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                err = capture(exc, code=code, context=context)
                traceback.print_exc()
                log_error(err)
                if on_error is not None:
                    on_error(err)
                if reraise:
                    raise err
                return None
        return wrapper
    return decorate
