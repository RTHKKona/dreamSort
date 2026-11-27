# entry point

import sys
import traceback

from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import app_logging
from .errors import capture
from .platform import ensure_registered
from .storage import read_config
from .ui import dialogs
from .ui.main_window import MainWindow
from .ui.theme import apply_theme, configure_high_dpi

SERVER_NAME = "dreamsort-single-instance"
PROTO_PREFIX = "drmsrt:"


def _send_to_existing(url):
    # hand the url to the running instance, if any
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(600):
        return False
    if url:
        socket.write(url.encode("utf-8"))
        socket.flush()
        socket.waitForBytesWritten(600)
    socket.disconnectFromServer()
    return True


def main(argv=None):
    args = list(sys.argv if argv is None else argv)
    url = next((a for a in args[1:]
                if a.lower().startswith(PROTO_PREFIX)
                or "gamebanana.com" in a.lower()), "")
    if _send_to_existing(url):
        return 0

    # file logging is up before any window so startup crashes are captured
    app_logging.init_logging(
        bool(read_config().get("logging_enabled", True)))
    app_logging.install_excepthook()

    try:
        configure_high_dpi()
        app = QApplication(args)
        app_logging.install_qt_message_handler()
        app.setApplicationName("dreamSort")
        app.setOrganizationName("dreamSort")
        apply_theme(app, bool(read_config().get("high_contrast", False)))

        ensure_registered()

        server = QLocalServer()
        QLocalServer.removeServer(SERVER_NAME)
        server.listen(SERVER_NAME)

        window = MainWindow()
        window._local_server = server
        server.newConnection.connect(
            lambda: window.attach_protocol_connection(
                server.nextPendingConnection()))
        if url:
            window.enqueue_protocol_url(url)
        window.show()
    except Exception as exc:
        # last resort: keep the traceback in the log and show the clean line
        err = capture(exc)
        traceback.print_exc()
        try:
            dialogs.error(None, "dreamSort failed to start", str(err))
        except Exception:
            pass
        return 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
