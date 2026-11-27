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
    process = subprocess.Popen(command)
    return process, command


def launch_recomp(exe_path):
    # start recomp
    command = [exe_path]
    if sys.platform == "darwin" and exe_path.endswith(".app"):
        command = [_bundle_binary(exe_path, "mhgurecomp")]
    process = subprocess.Popen(command, cwd=os.path.dirname(exe_path))
    return process, command


def launch_eden(exe_path):
    # start eden, no game argument on purpose: it boots to the game list
    command = [exe_path]
    if sys.platform == "darwin" and exe_path.endswith(".app"):
        command = [_bundle_binary(exe_path, "eden")]
    process = subprocess.Popen(command, cwd=os.path.dirname(exe_path))
    return process, command
