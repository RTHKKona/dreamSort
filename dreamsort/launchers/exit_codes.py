# recomp exit code table
#
# mirrors docs/EXIT-CODES.md. A code says whose code was running, not who
# caused the crash, so descriptions stay neutral.

from ..constants import Colors

# code -> (title, colour, meaning)
_TABLE = {
    0: ("Closed normally", Colors.TEXT_MUTED,
        "The window closed, Quit Game, Exit from the title screen, or the "
        "game's own exit."),
    20: ("Crashed in the port's own code", Colors.CONFLICT,
         "The runtime, the renderer, or a library or driver it called."),
    21: ("Crashed in the game's code", Colors.CONFLICT,
         "The game's own code, or the game gave up: a failed check, an "
         "abort, an svcBreak."),
    22: ("Crashed in a Forge plugin's code", Colors.CONFLICT,
         "A Forge plugin's code, or the game gave up during a plugin's "
         "call. The code says whose code was running, not who caused it."),
    23: ("Crashed in a mod's subsdk code", Colors.CONFLICT,
         "A mod's subsdk code, or a mod's subsdk could not be loaded."),
    24: ("Crashed in an engine module", Colors.CONFLICT,
         "An engine module's native code, or a library its folder brought "
         "along."),
    30: ("Can't start on this PC", Colors.CONFLICT,
         "No AVX2, no Vulkan 1.1 driver, or damaged or missing game files. "
         "A message box said why."),
    31: ("Closed to restart", Colors.TEXT_MUTED,
         "The settings menu's Restart: a new process takes over, so the "
         "code does not mean it ended."),
    1: ("Process killed", Colors.DRAG_HIGHLIGHT,
        "The process was ended, for example from Task Manager."),
    3: ("C runtime abort", Colors.CONFLICT,
        "An abort() the crash handler never saw."),
}

_UNKNOWN = ("Crash, cause unknown", Colors.CONFLICT,
            "Any other nonzero code. A game that hangs never exits, so it "
            "gets no code at all.")


def label(code):
    # 0xC0000005-style Windows codes and Linux signal codes read as hex
    if code is not None and code > 128:
        return "0x%X" % code
    return str(code)


def describe(code):
    # title, colour, meaning for any code
    return _TABLE.get(code, _UNKNOWN)


def is_quiet(code):
    # normal exit and restart need no dialog
    return code in (0, 31)
