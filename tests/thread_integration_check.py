import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from dreamsort import packs
from dreamsort.errors import DreamSortError, ErrorCode
from dreamsort.workers import run_in_thread

app = QApplication([])


def run_and_collect(fn, *args, **kwargs):
    loop = QEventLoop()
    collect = {}

    def check():
        if len(collect) == 2:
            loop.quit()

    timeout = QTimer()
    timeout.timeout.connect(loop.quit)
    timeout.start(5000)

    refs = run_in_thread(
        app, fn, *args,
        on_error=lambda text: (collect.setdefault("text", text), check()),
        on_error_info=lambda err: (collect.setdefault("err", err), check()),
        **kwargs)
    loop.exec()
    timeout.stop()
    thread, _worker = refs
    thread.wait(5000)
    # let the queued deleteLater calls run before the next loop
    for _ in range(5):
        app.processEvents()
    return collect


# 1. a builtin exception is normalized across the thread boundary
def fail():
    raise FileNotFoundError("missing mod")


first = run_and_collect(fail)
assert isinstance(first["err"], DreamSortError)
assert first["err"].code == ErrorCode.PATH_NOT_FOUND
assert first["text"].startswith("[E13]"), first["text"]
print("thread string signal :", first["text"])
print("thread object signal :", first["err"].code, first["err"].severity)

# 2. the 1337 hard gate
packs.scan_inputs = lambda _items: [
    {"name": "HD Pixel Pack", "where": "E:\\mods"}]
gate = run_and_collect(packs.assert_clean, ["x"])
assert gate["err"].code == ErrorCode.PIXELPACK_DETECTED
assert gate["text"].startswith("[E1337]"), gate["text"]
print("pixelpack gate       :", gate["text"])
print("INTEGRATION OK")
# final drain so every owned QObject is deleted inside a running loop
for _ in range(10):
    app.processEvents()
