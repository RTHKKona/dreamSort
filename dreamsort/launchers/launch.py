# launch helpers

import os
import subprocess
import sys


def _bundle_binary(bundle, inner):
    return os.path.join(bundle, "Contents", "MacOS", inner)


def launch_ryujinx(exe_path, game_file_path):
    # start ryujinx
    command = [exe_path, game_file_path]
    if sys.platform == "darwin" and exe_path.endswith(".app"):
        command[0] = _bundle_binary(exe_path, "Ryujinx")
    subprocess.Popen(command)
    return command


def launch_recomp(exe_path):
    # start recomp
    command = [exe_path]
    if sys.platform == "darwin" and exe_path.endswith(".app"):
        command = [_bundle_binary(exe_path, "mhgurecomp")]
    subprocess.Popen(command, cwd=os.path.dirname(exe_path))
    return command
