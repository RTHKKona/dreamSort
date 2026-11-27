# safe extraction

import os
import re
import shutil
import subprocess
import zipfile

try:
    import py7zr
    PY7ZR_SUPPORT = True
except ImportError:  # optional backend
    py7zr = None
    PY7ZR_SUPPORT = False

try:
    from py7zr.callbacks import ExtractCallback as _SevenZipCallback
except ImportError:  # py7zr below 0.21 has no callback class
    _SevenZipCallback = None

# loose caps so a bad archive cannot fill the drive
MAX_TOTAL_BYTES = 2 * 1024 ** 3
MAX_ENTRIES = 20000
MAX_RATIO = 100
RATIO_FLOOR = 64 * 1024 ** 2

EXECUTABLE_EXTS = {
    ".exe", ".dll", ".elf", ".so", ".bat", ".cmd", ".msi",
    ".scr", ".ps1", ".sh", ".app", ".jar", ".com",
}

# scripts a user can still agree to install
SCRIPT_EXTS = {".bat", ".cmd", ".ps1"}

SKIP_TOP = {"__macosx", ".ds_store", "thumbs.db"}

ARCHIVE_EXTS = {".zip", ".7z", ".rar"}


def _blocked(ext, allow_scripts):
    # scripts only go through once the risk prompt was accepted
    return ext in EXECUTABLE_EXTS and not (
        allow_scripts and ext in SCRIPT_EXTS)


if _SevenZipCallback is not None:
    class _SevenZipProgress(_SevenZipCallback):
        # py7zr wants an ExtractCallback instance, a plain function is refused
        def __init__(self, total, progress):
            super().__init__()
            self.total = max(total, 1)
            self.progress = progress
            self.done = 0

        def report_start_preparation(self):
            self.progress(0, self.total)

        def report_start(self, processing_file_path, processing_bytes):
            pass  # the tick comes when an entry is finished

        def report_update(self, decompressed_bytes):
            pass

        def report_end(self, processing_file_path, processed_bytes):
            self.done += 1
            self.progress(min(self.done, self.total), self.total)

        def report_warning(self, message):
            pass

        def report_postprocess(self):
            pass



class ArchiveSafetyError(Exception):
    # archive failed the safety checks
    pass


def archive_kind(path):
    # rough type from the suffix
    ext = os.path.splitext(path)[1].lower()
    if ext == ".zip":
        return "zip"
    if ext == ".7z":
        return "7z"
    if ext == ".rar":
        return "rar"
    return "unknown"


def rar_backend():
    # find something that can read rar
    for cli in ("7z", "7za", "7zr", "unrar"):
        found = shutil.which(cli)
        if found:
            return [found]
    return None


def _safe_join(root, member_name):
    # keep the member inside root
    norm = os.path.normpath(member_name).replace("\\", "/")
    if norm in (".", ""):
        raise ArchiveSafetyError("Archive has an invalid entry path.")
    if norm.startswith("../") or norm == "..":
        raise ArchiveSafetyError("Archive tries to escape the mods folder.")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm):
        raise ArchiveSafetyError("Archive uses an absolute path.")
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ArchiveSafetyError("Archive tries to escape the mods folder.")
    target = os.path.join(root, *parts)
    root_abs = os.path.normcase(os.path.abspath(root))
    if not os.path.normcase(os.path.abspath(target)).startswith(root_abs + os.sep) \
            and os.path.normcase(os.path.abspath(target)) != root_abs:
        raise ArchiveSafetyError("Archive entry lands outside the mods folder.")
    return target


def _is_symlink_attr(external_attr):
    # unix mode bits live in the high word
    mode = (external_attr >> 16) & 0o170000
    return mode == 0o120000


def _validate_extracted_tree(dest_dir, archive_size=0, allow_scripts=False):
    # walk what came out and check it again
    total = 0
    count = 0
    offenders = []
    root_abs = os.path.normcase(os.path.abspath(dest_dir))
    for root, dirs, files in os.walk(dest_dir, followlinks=False):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_TOP]
        for name in dirs:
            full = os.path.join(root, name)
            if not os.path.normcase(os.path.abspath(full)).startswith(root_abs + os.sep):
                raise ArchiveSafetyError("Archive entry lands outside the mods folder.")
        for name in files:
            full = os.path.join(root, name)
            if not os.path.normcase(os.path.abspath(full)).startswith(root_abs + os.sep):
                raise ArchiveSafetyError("Archive entry lands outside the mods folder.")
            count += 1
            if count > MAX_ENTRIES:
                raise ArchiveSafetyError("Archive contains too many files.")
            try:
                if os.path.islink(full):
                    raise ArchiveSafetyError("Archive contains a link: %s" % name)
                total += os.path.getsize(full)
            except OSError:
                continue
            if total > MAX_TOTAL_BYTES:
                raise ArchiveSafetyError("Archive unpacks to too much data.")
            ext = os.path.splitext(name)[1].lower()
            if _blocked(ext, allow_scripts):
                offenders.append(name)
    if offenders:
        raise ArchiveSafetyError(
            "Archive contains executable files (%s); not installing it."
            % ", ".join(sorted(set(offenders))[:5]))
    # only meaningful once there is a packed size to compare against
    if archive_size and total > max(archive_size * MAX_RATIO, RATIO_FLOOR):
        raise ArchiveSafetyError("Archive unpacks far beyond its packed size.")


def _extract_zip(path, dest_dir, allow_scripts=False, progress=None):
    try:
        archive = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError):
        raise ArchiveSafetyError("Could not read the ZIP archive.")
    with archive:
        entries = [info for info in archive.infolist() if not info.is_dir()]
        # screen the manifest before writing anything
        if len(entries) > MAX_ENTRIES:
            raise ArchiveSafetyError("Archive contains too many files.")
        declared = 0
        for info in entries:
            if info.flag_bits & 0x1:
                raise ArchiveSafetyError("Archive is password protected.")
            if _is_symlink_attr(info.external_attr):
                raise ArchiveSafetyError("Archive contains a link entry.")
            ext = os.path.splitext(info.filename)[1].lower()
            if _blocked(ext, allow_scripts):
                raise ArchiveSafetyError(
                    "Archive contains an executable: %s" % info.filename)
            declared += info.file_size
            if declared > MAX_TOTAL_BYTES:
                raise ArchiveSafetyError("Archive unpacks to too much data.")
        total = len(entries)
        for index, info in enumerate(entries, 1):
            target = _safe_join(dest_dir, info.filename)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                with archive.open(info) as source, open(target, "wb") as out:
                    shutil.copyfileobj(source, out)
            except RuntimeError:  # encrypted or damaged member
                raise ArchiveSafetyError("Archive member is unreadable: %s"
                                         % info.filename)
            if progress:
                progress(index, total)


def _extract_7z(path, dest_dir, allow_scripts=False, progress=None):
    if py7zr is None:
        raise ArchiveSafetyError("Install 'py7zr' to open .7z archives.")
    try:
        with py7zr.SevenZipFile(path, mode="r") as archive:
            # same screen as zip, the backend can list before unpacking
            infos = archive.list()
            files = [info for info in infos
                     if not getattr(info, "is_directory", False)]
            if len(files) > MAX_ENTRIES:
                raise ArchiveSafetyError("Archive contains too many files.")
            declared = 0
            for info in files:
                if getattr(info, "is_symlink", False):
                    raise ArchiveSafetyError("Archive contains a link entry.")
                ext = os.path.splitext(info.filename)[1].lower()
                if _blocked(ext, allow_scripts):
                    raise ArchiveSafetyError(
                        "Archive contains an executable: %s" % info.filename)
                declared += int(getattr(info, "uncompressed", 0) or 0)
                if declared > MAX_TOTAL_BYTES:
                    raise ArchiveSafetyError("Archive unpacks to too much data.")
            total = len(files)
            _unpack_7z(archive, dest_dir, total, progress)
    except ArchiveSafetyError:
        raise
    except Exception as exc:  # backend specific failures
        raise ArchiveSafetyError("Could not unpack the 7z archive: %s" % exc)


def _unpack_7z(archive, dest_dir, total, progress):
    # callback only when the backend has the class; otherwise unpack bare
    callback = (_SevenZipProgress(total, progress)
                if _SevenZipCallback is not None and progress else None)
    try:
        if callback is not None:
            archive.extractall(path=dest_dir, callback=callback)
        else:
            archive.extractall(path=dest_dir)
    except (TypeError, ValueError):
        # older py7zr calls a function or refuses the callback entirely
        archive.extractall(path=dest_dir)
        if progress:
            progress(max(total, 1), max(total, 1))


def _extract_rar(path, dest_dir, progress=None):
    backend = rar_backend()
    if backend is None:
        raise ArchiveSafetyError(
            "A RAR extractor (7-Zip or unrar) was not found.")
    command = backend + ["x", "-y", "-o" + dest_dir, path]
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    if progress:
        progress(0, 1)
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", errors="replace",
                            startupinfo=startupinfo)
    if result.returncode != 0:
        raise ArchiveSafetyError("Could not read the RAR archive.")
    if progress:
        progress(1, 1)


def safe_extract(path, dest_dir, allow_scripts=False, progress=None):
    # unpack into dest_dir with the safety checks on
    kind = archive_kind(path)
    os.makedirs(dest_dir, exist_ok=True)
    try:
        packed = os.path.getsize(path)
    except OSError:
        packed = 0
    if kind == "zip":
        _extract_zip(path, dest_dir, allow_scripts, progress)
    elif kind == "7z":
        _extract_7z(path, dest_dir, allow_scripts, progress)
    elif kind == "rar":
        _extract_rar(path, dest_dir, progress)
    else:
        raise ArchiveSafetyError("Unsupported archive type: %s" % path)
    _validate_extracted_tree(dest_dir, packed, allow_scripts)
