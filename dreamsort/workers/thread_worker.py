# thread plumbing

import traceback

from PySide6.QtCore import QObject, QThread, Signal, Slot

from .. import app_logging
from ..errors import DreamSortError, ErrorCode, capture


class Worker(QObject):
    # run in a thread

    progress = Signal(object)      # dict
    finished = Signal(object)      # result
    error = Signal(str)           # user-facing line
    error_info = Signal(object)    # DreamSortError

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def fail(self, exc, code=None, context=""):
        # report a failure on both signals; accepts an exception or string.
        # legacy string signal first so existing handlers always run.
        if isinstance(exc, BaseException):
            err = capture(exc, code=code, context=context)
            traceback.print_exception(type(exc), exc, exc.__traceback__)
        else:
            err = DreamSortError(code or ErrorCode.UNKNOWN,
                                 context=str(exc))
        # processing failures must land in dreamsort.log too
        app_logging.log_error(err)
        self.error.emit(str(err))
        self.error_info.emit(err)

    @Slot()
    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:
            self.fail(exc)
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


def _wire(parent, thread, worker, on_done, on_error, on_progress,
          on_error_info=None):
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)
    worker.error_info.connect(thread.quit)
    # optional signal for jobs that stop without a result
    cancelled = getattr(worker, "cancelled", None)
    if cancelled is not None:
        cancelled.connect(thread.quit)
    if on_done:
        worker.finished.connect(on_done)
    if on_error:
        worker.error.connect(on_error)
    if on_error_info:
        worker.error_info.connect(on_error_info)
    if on_progress:
        worker.progress.connect(on_progress)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    _track(parent, thread, worker)


def run_in_thread(parent, fn, *args, on_done=None, on_error=None,
                  on_progress=None, on_error_info=None, **kwargs):
    # fire and forget
    thread = QThread(parent)
    worker = Worker(fn, *args, **kwargs)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    _wire(parent, thread, worker, on_done, on_error, on_progress,
          on_error_info)
    thread.start()
    return thread, worker


def run_worker(parent, worker, on_done=None, on_error=None, on_progress=None,
               on_error_info=None, start_slot="run"):
    # custom worker
    thread = QThread(parent)
    worker.moveToThread(thread)
    thread.started.connect(getattr(worker, start_slot))
    _wire(parent, thread, worker, on_done, on_error, on_progress,
          on_error_info)
    thread.start()
    return thread, worker
