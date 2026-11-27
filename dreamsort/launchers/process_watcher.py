# watch a Popen from a background thread

import threading

from PySide6.QtCore import QObject, Signal


class ProcessWatcher(QObject):
    # emits the exit code once the watched process ends
    process_exited = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None

    def watch(self, process):
        # one watcher per process
        self._process = process
        thread = threading.Thread(target=self._wait, daemon=True)
        thread.start()

    def _wait(self):
        process = self._process
        if process is None:
            return
        code = process.wait()
        self.process_exited.emit(code)
