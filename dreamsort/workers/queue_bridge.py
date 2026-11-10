# queue to signal

from PySide6.QtCore import QObject, Signal


class QueueBridge(QObject):
    # stands in for a Queue

    message = Signal(object)

    def put(self, msg, *args, **kwargs):
        # fine from a worker thread
        self.message.emit(msg)
