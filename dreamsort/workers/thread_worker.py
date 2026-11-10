# thread plumbing

import traceback

from PySide6.QtCore import QObject, QThread, Signal, Slot


class Worker(QObject):
    # run in a thread

    progress = Signal(object)      # dict
    finished = Signal(object)      # result
    error = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    @Slot()
    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception:
            traceback.print_exc()
            self.error.emit(traceback.format_exc())
            return
        self.finished.emit(result)


def _track(parent, thread, worker):
    # keep refs alive
    if parent is None:
        return
    active = getattr(parent, "_active_threads", None)
    if active is None:
        active = []
        parent._active_threads = active
    entry = (thread, worker)
    active.append(entry)

    def _release():
        if entry in active:
            active.remove(entry)

    thread.finished.connect(_release)


def _wire(parent, thread, worker, on_done, on_error, on_progress):
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)
    if on_done:
        worker.finished.connect(on_done)
    if on_error:
        worker.error.connect(on_error)
    if on_progress:
        worker.progress.connect(on_progress)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    _track(parent, thread, worker)


def run_in_thread(parent, fn, *args, on_done=None, on_error=None,
                  on_progress=None, **kwargs):
    # fire and forget
    thread = QThread(parent)
    worker = Worker(fn, *args, **kwargs)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    _wire(parent, thread, worker, on_done, on_error, on_progress)
    thread.start()
    return thread, worker


def run_worker(parent, worker, on_done=None, on_error=None, on_progress=None,
               start_slot="run"):
    # custom worker
    thread = QThread(parent)
    worker.moveToThread(thread)
    thread.started.connect(getattr(worker, start_slot))
    _wire(parent, thread, worker, on_done, on_error, on_progress)
    thread.start()
    return thread, worker
