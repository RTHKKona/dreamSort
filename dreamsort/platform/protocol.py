# custom protocol registration

import os
import sys

PROTOCOL = "drmsrt"


def _source_root():
    # dreamSort.py lives above the package, three levels from this file
    here = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def _launch_targets():
    # (program, script) the handler runs; script is empty for the frozen exe
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable), ""
    exe = sys.executable
    if os.name == "nt" and exe.lower().endswith("python.exe"):
        exe = exe[:-len("python.exe")] + "pythonw.exe"
    return exe, os.path.join(_source_root(), "dreamSort.py")


def _launch_command():
    # a browser click runs with a foreign cwd, so the script needs its path:
    # "-m dreamsort" only resolves when the cwd happens to be the project
    exe, script = _launch_targets()
    if not script:
        return '"%s" "%%1"' % exe
    return '"%s" "%s" "%%1"' % (exe, script)


def _register_windows():
    import winreg
    command = _launch_command()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                          r"Software\Classes\%s" % PROTOCOL) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ,
                          "URL: dreamSort Protocol")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                          r"Software\Classes\%s\shell\open\command"
                          % PROTOCOL) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
    return command


def _registered_command_windows():
    import winreg
    try:
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Classes\%s\shell\open\command" % PROTOCOL) as key:
            return winreg.QueryValueEx(key, "")[0]
    except OSError:
        return None


def _register_linux():
    # desktop file, no admin needed
    home = os.path.expanduser("~")
    apps = os.path.join(home, ".local", "share", "applications")
    os.makedirs(apps, exist_ok=True)
    desktop = os.path.join(apps, "dreamsort.desktop")
    exe, script = _launch_targets()
    exec_line = ('"%s" "%s" %%u' % (exe, script)) if script \
        else '"%s" %%u' % exe
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=dreamSort\n"
        "Exec=%s\n"
        "MimeType=x-scheme-handler/%s;\n"
        "NoDisplay=true\n" % (exec_line, PROTOCOL))
    try:
        with open(desktop, "w", encoding="utf-8") as handle:
            handle.write(content)
    except OSError:
        pass
    return exec_line


def ensure_registered(force=False):
    # re-register when the launcher moved; force rewrites a stale entry
    try:
        if os.name == "nt":
            wanted = _launch_command()
            if force or _registered_command_windows() != wanted:
                return _register_windows()
            return wanted
        return _register_linux()
    except OSError:
        return None
