# analyze the recomp's log.txt and suggest what to do
#
# log.txt is written next to mhgurecomp.exe. The pattern table is data
# driven so new signatures can be added without touching the engine.

from __future__ import annotations

import os
import re

from ..errors import Severity

LOG_NAME = "log.txt"
MAX_BYTES = 2 * 1024 * 1024      # cap how much of a large log is read
TAIL_LINES = 2000
MAX_FINDINGS = 25

# (regex, title, severity, suggestion); first match on a line wins
_PATTERNS = (
    (re.compile(r"romfs.*(?:not found|missing|failed|cannot|can't|unable)", re.I),
     "Game data (romfs) not found", Severity.ERROR,
     "Keep mhgurecomp.exe together with the data files it shipped with; do "
     "not move the exe on its own. Re-extract the full recomp bundle if "
     "files were deleted, then try again."),
    (re.compile(r"(?:could not|cannot|can't|unable to|failed to)\s+"
                r"(?:open|find|load|mount|read).*romfs", re.I),
     "Game data (romfs) not found", Severity.ERROR,
     "Keep mhgurecomp.exe together with the data files it shipped with; do "
     "not move the exe on its own. Re-extract the full recomp bundle if "
     "files were deleted, then try again."),
    (re.compile(r"\.nro\b.*(?:not found|missing|failed|error|cannot|can't|unable)",
                re.I),
     "Plugin (.nro) failed to load", Severity.ERROR,
     "Open the mod's romfs/nativenx/plugins folder, disable the mod named "
     "in the log, and re-add it from its original GameBanana page."),
    (re.compile(r"(?:failed|unable)\s+to\s+load.*\.nro", re.I),
     "Plugin (.nro) failed to load", Severity.ERROR,
     "Open the mod's romfs/nativenx/plugins folder, disable the mod named "
     "in the log, and re-add it from its original GameBanana page."),
    (re.compile(r"engine[_ ]module", re.I),
     "Engine module failed to load", Severity.ERROR,
     "Open engine_modules and make sure enabled.txt only lists folders that "
     "still contain their .dll. Disable the named module, then re-launch."),
    (re.compile(r"\.(?:dll|so|dylib)\b.*(?:not found|missing|failed|error|"
                r"cannot|can't|unable|load)", re.I),
     "Engine module failed to load", Severity.ERROR,
     "Open engine_modules and make sure enabled.txt only lists folders that "
     "still contain their .dll. Disable the named module, then re-launch."),
    (re.compile(r"duplicate|already\s+(?:loaded|exists|registered)|conflict",
                re.I),
     "Duplicate file or module", Severity.WARNING,
     "The same file is supplied more than once. Look for a mod in both "
     "mods/ and engine_modules, and remove duplicate folders or repeated "
     "entries in load_order.txt."),
    (re.compile(r"vulkan|device\s+lost|gpu|graphics\s+(?:driver|device)|"
                r"shader\s+(?:compile|fail)", re.I),
     "Graphics driver / GPU error", Severity.ERROR,
     "Update your graphics driver, close other GPU apps, and disable any "
     "GPU overclock. 'Device lost' usually means a driver crash; retry "
     "with fewer mods."),
    (re.compile(r"out\s+of\s+memory|bad_alloc|allocation\s+failed|"
                r"insufficient\s+memory", re.I),
     "Out of memory", Severity.ERROR,
     "Close other programs and disable high-resolution texture packs, or "
     "reduce the number of enabled mods."),
    (re.compile(r"version\s+mismatch|incompatible|outdated|unsupported\s+"
                r"version|wrong\s+version", re.I),
     "Version mismatch", Severity.WARNING,
     "Something was built for a different recomp version. Run the recomp "
     "updater, then confirm each mod targets this build."),
    (re.compile(r"save\s+(?:data\s+)?(?:corrupt|failed|error)|corrupt(?:ed|ion)?",
                re.I),
     "Save data problem", Severity.ERROR,
     "Back up the save folder first, then restore an earlier save so the "
     "damaged one is not overwritten."),
    (re.compile(r"no such file|file\s+not\s+found|cannot find|can't find|"
                r"could not find", re.I),
     "A required file is missing", Severity.ERROR,
     "Verify the recomp folder is complete and no antivirus quarantined "
     "files; re-extract the bundle if something is missing."),
    (re.compile(r"access\s+(?:denied|violation)|permission\s+denied", re.I),
     "Access denied", Severity.ERROR,
     "Check antivirus or Controlled Folder Access, and run from a "
     "user-writable folder rather than Program Files."),
    (re.compile(r"fatal|segfault|segmentation fault|unhandled\s+exception|"
                r"abort(?:ed)?|crashed", re.I),
     "Recomp crashed", Severity.CRITICAL,
     "Note the file in the lines above, disable the mods loaded just "
     "before it, and send log.txt to the recomp author if it still "
     "crashes with no mods enabled."),
)

_GENERIC = re.compile(r"error|exception|fail", re.I)

_GENERIC_SUGGESTION = (
    "dreamSort does not recognize this error. Open the full log, read the "
    "lines just before it, and if it happens with all mods disabled, send "
    "log.txt to the recomp author.")


def expected_log_path(root):
    return os.path.join(root, LOG_NAME) if root else ""


def find_log(root):
    path = expected_log_path(root)
    return path if path and os.path.isfile(path) else ""


def _read_lines(path):
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_BYTES)
    except OSError:
        return []
    text = raw.decode("utf-8", "replace")
    return text.splitlines()[-TAIL_LINES:]


def _match(line):
    for pattern, title, severity, suggestion in _PATTERNS:
        if pattern.search(line):
            return title, severity, suggestion
    if _GENERIC.search(line):
        return "Unrecognized error", Severity.WARNING, _GENERIC_SUGGESTION
    return None


def analyze(root):
    # structured findings for a recomp root, or a not-found report
    path = find_log(root)
    if not path:
        return {
            "found": False,
            "path": expected_log_path(root),
            "findings": [],
            "summary": "No log.txt found. Run the recomp once; it writes "
                       "log.txt next to mhgurecomp.exe.",
        }

    findings = []
    generic_count = 0
    for index, line in enumerate(_read_lines(path), 1):
        matched = _match(line)
        if matched is None:
            continue
        title, severity, suggestion = matched
        if title == "Unrecognized error":
            generic_count += 1
            if generic_count > 3:
                continue
        findings.append({
            "line_number": index,
            "line": line.strip()[:300],
            "title": title,
            "severity": severity,
            "suggestion": suggestion,
        })
        if len(findings) >= MAX_FINDINGS:
            break

    return {
        "found": True,
        "path": path,
        "findings": findings,
        "summary": _summary(findings),
    }


def _summary(findings):
    if not findings:
        return ("No obvious problems found in log.txt. If the recomp is "
                "misbehaving, share the full log anyway.")
    critical = sum(1 for f in findings
                    if f["severity"] == Severity.CRITICAL)
    if critical:
        return ("Found %d issue%s, including %d crash. Start with the "
                "suggestions below." % (
                    len(findings), "" if len(findings) == 1 else "s",
                    critical))
    return "Found %d issue%s. Each entry includes a suggested fix." % (
        len(findings), "" if len(findings) == 1 else "s")
