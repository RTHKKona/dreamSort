# script scanner for incoming mods

import os
import re
import shutil
import subprocess
import zipfile

try:
    import py7zr
except ImportError:  # optional backend
    py7zr = None

# a mod of game files never needs to run something
SCRIPT_EXTS = (".bat", ".cmd", ".ps1")

MAX_TEXT = 512 * 1024   # per script, enough for the head of the file
MAX_FOUND = 300         # stop scanning after this many script files

SKIP_DIRS = {"__macosx", ".git", "node_modules"}

# (label, pattern) - .{0,80} keeps a match on one line
RISK_RULES = (
    ("deletes files or folders",
     re.compile(
         r"\b(?:del|erase|rmdir|rd)\b.{0,80}(?:/s\b|/q\b)"
         r"|\bremove-item\b.{0,80}-recurse\b"
         r"|\brm\b.{0,80}-[rf]{1,2}\b|\bformat\s+[a-z]:", re.I)),
    ("changes Windows settings",
     re.compile(
         r"\breg\s+(?:add|delete|import)\b|\bbcdedit\b|\bschtasks\b"
         r"|\bsc\s+(?:stop|delete|config)\b|\bnetsh\b|\bsetx\b|\bwmic\b"
         r"|\bpowercfg\b|\bnet\s+(?:user|localgroup)\b", re.I)),
    ("closes other programs or restarts the PC",
     re.compile(r"\btaskkill\b|\btskill\b|\bstop-process\b|\bpkill\b"
                r"|\bkillall\b|\bshutdown\s+/|\blogoff\b", re.I)),
    ("lifts itself to administrator",
     re.compile(r"\brunas\b|-verb\s+runas\b|\btakeown\b|\bicacls\b"
                r"|\bstart-process\b.{0,80}-verb", re.I)),
    ("downloads code from the internet",
     re.compile(r"invoke-webrequest|invoke-restmethod|\biwr\b|\birm\b"
                r"|downloadstring|downloadfile|\bcurl\b|\bwget\b|bitsadmin"
                r"|start-bitstransfer|certutil.{0,80}-urlcache", re.I)),
    ("runs hidden or encoded commands",
     re.compile(r"-enc(?:odedcommand)?\b|-windowstyle\s+hidden|\bmshta\b"
                r"|\bwscript\b|\bcscript\b|frombase64string"
                r"|certutil.{0,80}-decode", re.I)),
    ("executes generated code",
     re.compile(r"\biex\b|invoke-expression|\beval\b"
                r"|new-object\s+net\.webclient", re.I)),
    ("writes outside the mods folder",
     re.compile(r"%appdata%|%localappdata%|%userprofile%|%systemroot%"
                r"|%programfiles%|\\windows\\|c:\\windows"
                r"|\$env:(?:appdata|localappdata|userprofile|systemroot)"
                r"|\b(?:system32|syswow64)\b|\\program files", re.I)),
    ("reads browser or account data",
     re.compile(r"login data|\bcookies\b|wallet\.dat|\bweb data\b"
                r"|discord.{0,30}token", re.I)),
)


def risks_in(text):
    # labels the text trips, in rule order
    if not text:
        return []
    labels = []
    for label, pattern in RISK_RULES:
        if label not in labels and pattern.search(text):
            labels.append(label)
    return labels


def _read_text(path):
    # head of a script, whatever the codepage
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_TEXT)
    except OSError:
        return ""
    return data.decode("utf-8", "replace")


def _add(findings, name, where, text):
    if len(findings) >= MAX_FOUND:
        return
    findings.append({"name": name, "where": where,
                     "risks": risks_in(text), "inspected": bool(text)})


def _scan_dir(path, findings):
    # loose folder or a copied mod tree
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and d.lower() not in SKIP_DIRS]
        for name in files:
            if not name.lower().endswith(SCRIPT_EXTS):
                continue
            full = os.path.join(root, name)
            _add(findings, name, os.path.relpath(full, path), _read_text(full))


def _scan_zip(path, findings):
    try:
        archive = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError):
        return
    with archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.lower().endswith(SCRIPT_EXTS):
                continue
            text = ""
            if 0 < info.file_size <= MAX_TEXT:
                try:
                    text = archive.read(info).decode("utf-8", "replace")
                except Exception:  # encrypted or damaged member
                    text = ""
            _add(findings, os.path.basename(info.filename), info.filename, text)


def _scan_7z(path, findings):
    if py7zr is None:
        return
    try:
        with py7zr.SevenZipFile(path, mode="r") as archive:
            names = [info.filename for info in archive.list()
                     if not getattr(info, "is_directory", False)]
            scripts = [n for n in names if n.lower().endswith(SCRIPT_EXTS)]
            texts = {}
            if scripts:
                try:
                    # listing leaves the stream busy, start it over
                    try:
                        archive.reset()
                    except Exception:
                        pass
                    # read() hands back the members as buffers
                    members = archive.read(targets=scripts) or {}
                    for name, buffer in members.items():
                        try:
                            texts[name] = buffer.read(MAX_TEXT).decode(
                                "utf-8", "replace")
                        except Exception:
                            texts[name] = ""
                except Exception:  # older py7zr, names are enough
                    texts = {}
            for name in scripts:
                _add(findings, os.path.basename(name), name, texts.get(name, ""))
    except Exception:  # bad header, unsupported filter
        return


def _archive_cli():
    # 7-Zip / unrar, same tools the extractor uses
    for cli in ("7z", "7za", "7zr", "unrar"):
        found = shutil.which(cli)
        if found:
            return [found]
    return None


def _scan_rar(path, findings):
    backend = _archive_cli()
    if backend is None:
        return
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        result = subprocess.run(backend + ["l", "-ba", path],
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", startupinfo=startupinfo)
    except OSError:
        return
    if result.returncode != 0:
        return
    for line in result.stdout.splitlines():
        # date time attr size packed name
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        name = parts[5].strip()
        if name.lower().endswith(SCRIPT_EXTS):
            # the listing has no contents to read
            _add(findings, os.path.basename(name), name, "")


def scan_paths(paths):
    """Script files in the items about to be installed, with what they do."""
    findings = []
    for path in paths or []:
        path = str(path or "").strip().strip('"')
        if not path or not os.path.exists(path):
            continue
        if os.path.isdir(path):
            _scan_dir(path, findings)
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext == ".zip":
            _scan_zip(path, findings)
        elif ext == ".7z":
            _scan_7z(path, findings)
        elif ext == ".rar":
            _scan_rar(path, findings)
    return findings
