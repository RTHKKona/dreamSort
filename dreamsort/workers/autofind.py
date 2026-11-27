# auto-find search job
#
# pure filesystem work for a worker thread; no Qt widgets here.

import os

FOLDER_BUDGET = 40000
_SKIP_NAMES = ("node_modules", "$recycle.bin")
_PROGRESS_EVERY = 250


def _is_reparse(entry):
    # a junction or symlink must not be followed; the tag is Windows-only
    try:
        stat = entry.stat(follow_symlinks=False)
    except OSError:
        return False
    tag = getattr(stat, "st_reparse_tag",
                   getattr(stat, "st_reparse_file_tag", 0))
    return tag != 0


def search_recomp_roots(user_roots, program_roots, exe_names,
                        cancel_event=None, progress=None):
    # return every folder holding a recomp exe, up to the folder budget
    names = {name.lower() for name in exe_names}
    found = []
    seen = set()
    state = {"budget": FOLDER_BUDGET, "scanned": 0}

    def walk(start, depth):
        if not start:
            return
        stack = [(os.path.normpath(start), 0)]
        while stack and state["budget"] > 0:
            if cancel_event is not None and cancel_event.is_set():
                return
            path, level = stack.pop()
            if path in seen:
                continue
            seen.add(path)
            state["budget"] -= 1
            state["scanned"] += 1
            try:
                entries = list(os.scandir(path))
            except OSError:
                continue
            if state["scanned"] % _PROGRESS_EVERY == 0 and progress is not None:
                progress({"scanned": state["scanned"], "path": path})
            if any(e.is_file() and e.name.lower() in names for e in entries):
                if path not in found:
                    found.append(path)
                continue
            if level >= depth:
                continue
            for entry in entries:
                if not entry.is_dir(follow_symlinks=False) or _is_reparse(entry):
                    continue
                name = entry.name.lower()
                if name.startswith(".") or name in _SKIP_NAMES:
                    continue
                stack.append((entry.path, level + 1))

    for root in user_roots:
        if os.path.isdir(root):
            walk(root, 3)
    for root in program_roots:
        if os.path.isdir(root):
            walk(root, 2)
    if cancel_event is not None and cancel_event.is_set():
        return {"found": found, "cancelled": True,
                "scanned": state["scanned"]}
    return {"found": found, "cancelled": False, "scanned": state["scanned"]}
