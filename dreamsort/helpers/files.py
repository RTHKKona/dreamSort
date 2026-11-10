# file helpers

import os
import platform
import shutil
import subprocess
import sys

def rename_prefixed_file(path, enabled, kind, progress_queue, display_name=None):
    # toggle the underscore
    filename = os.path.basename(path)
    clean_name = filename[1:] if filename.startswith("_") else filename
    target = clean_name if enabled else f"_{clean_name}"
    if target == filename:
        return True
    try:
        shutil.move(path, os.path.join(os.path.dirname(path), target))
    except Exception as exc:
        progress_queue.put({
            "type": "error",
            "message": f"Failed to rename {kind} '{display_name or clean_name}': {exc}",
        })
        return False
    return True


def is_process_running(process_name):
    system = platform.system()
    try:
        if system == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            command = ["tasklist", "/FI", f"IMAGENAME eq {process_name}.exe"]
            output = subprocess.check_output(
                command, startupinfo=startupinfo, stderr=subprocess.STDOUT
            )
            return process_name.lower() in output.decode(errors="ignore").lower()
        command = ["pgrep", "-f", process_name]
        output = subprocess.check_output(command, stderr=subprocess.STDOUT)
        return output.strip() != b""
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def open_in_file_explorer(path):
    if not path or not os.path.isdir(path):
        return False
    try:
        if sys.platform == "win32":
            os.startfile(os.path.normpath(path))
        elif sys.platform == "darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])
        return True
    except Exception:
        return False
