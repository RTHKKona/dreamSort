# what we accept off gamebanana

import os
import re

from ..helpers.archive import rar_backend

ALLOWED_SECTIONS = {"plugins", "recompplugins", "music"}
RECOMP_ONLY_SECTIONS = {"recompplugins"}
MODULE_SECTIONS = {"recompmodule"}
MHGU_GAME_ID = "17088"
MHGU_GAME_HINTS = {"monsterhuntergenerationsultimate", "mhgu"}
ARCHIVE_EXTS = {".zip", ".7z", ".rar"}
MANIFEST_NAMES = {"manifest.json", "manifest.txt"}


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def archive_ext(filename):
    # suffix only, callers still need to open the archive
    return os.path.splitext(str(filename or ""))[1].lower()


def archive_usable(filename):
    # rar needs an external tool, no point queuing what we cannot open
    ext = archive_ext(filename)
    if ext not in ARCHIVE_EXTS:
        return False
    if ext == ".rar" and not rar_backend():
        return False
    return True


def _section_names(profile):
    names = [profile.get("super_category"), profile.get("category")]
    names.extend(profile.get("sections") or [])
    return [name for name in names if name]


def check_game(profile):
    game = profile.get("game") or {}
    if not game.get("id") and not game.get("name"):
        return None
    if str(game.get("id") or "") == MHGU_GAME_ID:
        return None
    if _norm(game.get("name")) in MHGU_GAME_HINTS:
        return None
    if _norm(game.get("abbrev")) == "mhgu":
        return None
    return "That mod is for %s, not Monster Hunter Generations Ultimate." % (
        game.get("name") or "another game")


def check_section(profile):
    names = _section_names(profile)
    if not names:
        return None
    if any(_norm(name) in MODULE_SECTIONS for name in names):
        # a module is native code in the port's own process, not a mod
        return ("Recomp-Module pages are engine modules: a .dll in "
                "engine_modules/<name>/, not a mod. dreamSort does not install "
                "or update those; copy the folder into the port's "
                "engine_modules/ and add its name to enabled.txt yourself.")
    if any(_norm(name) in ALLOWED_SECTIONS for name in names):
        return None
    return ("Only Plugins, Recomp-Plugins and Music are supported; "
            "that mod is in '%s'." % names[0])


def check_files(profile):
    files = profile.get("files") or []
    if not files:
        return "No files are attached to that GameBanana page."
    if any(archive_usable(file.get("name")) for file in files):
        return None
    names = [file.get("name") or "" for file in files]
    if any(archive_ext(name) == ".rar" for name in names):
        return ("That mod only offers a .rar and no RAR tool was found; "
                "install 7-Zip (7z or unrar on PATH) to use it.")
    return "That mod's files are not zip, 7z or rar, so they cannot be installed."


def manifest_at_root(folder):
    # the 1-click requirement, checked where the details panel reads it
    try:
        names = {name.lower() for name in os.listdir(folder)}
    except OSError:
        return False
    return bool(names & MANIFEST_NAMES)


def mode_for_profile(profile):
    # a section only one loader reads, so install can pick the right one
    names = _section_names(profile or {})
    if any(_norm(name) in RECOMP_ONLY_SECTIONS for name in names):
        return "recomp"
    return None


def check_profile(profile):
    # first reason that blocks, None when the page passes
    if not isinstance(profile, dict):
        return "GameBanana did not return a usable page."
    return check_game(profile) or check_section(profile) or check_files(profile)
