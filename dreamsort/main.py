# entry point

import sys

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .ui.theme import apply_theme, configure_high_dpi


def main(argv=None):
    configure_high_dpi()
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("dreamSort")
    app.setOrganizationName("dreamSort")
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
