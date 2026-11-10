# theme

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QFont
from PySide6.QtWidgets import QApplication

from ..constants import Colors

QSS = """
QWidget {
    background: #2b2b2b;
    color: #ffebcd;
    font-size: 9pt;
}
QMainWindow, QDialog { background: #2b2b2b; }

QFrame#listPanel, QFrame#detailsPanel, QFrame#modContainer {
    background: #2b2b2b;
}
QFrame#detailsPanelInner { background: #2b2b2b; }

/* ---- mod rows: rounded via QSS, recoloured via dynamic properties ---- */
QFrame#modRow {
    background: #363636;
    border: 2px solid @noConflictFill;
    border-radius: 8px;
}
QFrame#modRow:hover { background: #3c3c3c; }
QFrame#modRow[conflictState="winner"]  { border-color: #86b894; }
QFrame#modRow[conflictState="loser"]   { border-color: #cf8a8a; }
QFrame#modRow[conflictState="none"]    { border-color: @noConflictFill; }
QFrame#modRow[conflictState="disabled"]{ border-color: #6e6e6e; }
QFrame#modRow[variant="cheat"]   { border-color: #a8814f; }
QFrame#modRow[variant="special"] { background: #2b2b2b; border: none; }
QFrame#modRow[variant="special"]:hover { background: #333333; }
QFrame#modRow[selected="true"] {
    background: #5a5233;
    border-color: #d1b66b;
}

QFrame#fileRow {
    background: transparent;
    border: none;
}
QFrame#fileRow:hover { background: #323232; }
QLabel#fileName { background: transparent; }
QLabel#modName {background: transparent;}
QFrame#fileRow[selected="true"] QLabel#fileName {
    color: #d1b66b;
    font-weight: bold;
}
QFrame#fileRow[active="false"] QLabel#fileName { color: #6e6e6e; }
QFrame#fileRow[missing="true"] QLabel#fileName { color: #6e6e6e; }

QLabel#chip {
    padding: 1px 6px;
    border-radius: 6px;
    font-size: 10px;
    font-weight: bold;
    color: #1a1a1a;
    background: #4fc3f7;
}
QLabel#chip[kind="romfs"] { background: #4fc3f7; }
QLabel#chip[kind="exefs"] { background: #ffb74d; }
QLabel#chip[kind="forge"] { background: #ce93d8; }
QLabel#chip[kind="arc"]   { background: #3eff65; }
QLabel#chip[kind="none"]  { background: @noConflictFill; color: #1a1a1a; }

QLabel#dragHandle {
    color: #ffebcd;
    border: none;
    background: transparent;
    padding: 0px 4px;
}

QLabel#cheatsDivider {
    color: #d4a26a;
    padding: 8px 5px 2px 5px;
    background: transparent;
}
QLabel#dropIndicator { background: #d1b66b; border-radius: 1px; }

/* ---- buttons ---- */
QPushButton {
    background: #363636;
    color: #ffebcd;
    border: none;
    border-radius: 6px;
    padding: 5px 10px;
    min-height: 18px;
}
QPushButton:hover    { background: #424242; }
QPushButton:pressed  { background: #333333; }
QPushButton:disabled { color: #a99f8d; }

QPushButton#primaryBtn {
    background: #ffebcd;
    color: #1a1a1a;
    font-weight: bold;
}
QPushButton#primaryBtn:hover { background: #e3cdb0; }

QPushButton#viewBtn {
    background: #363636;
    color: #ffebcd;
    border-radius: 6px;
}
QPushButton#viewBtn:checked {
    background: #454545;
    border: 1px solid #5a5a5a;
}

/* ---- inputs ---- */
QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {
    background: #363636;
    color: #ffebcd;
    border: 1px solid #454545;
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: #636363;
}
QLineEdit:focus, QPlainTextEdit:focus { border-color: #636363; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: #363636;
    color: #ffebcd;
    border: 1px solid #454545;
    selection-background-color: #424242;
}

QCheckBox { background: transparent; spacing: 6px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border-radius: 3px;
    border: 1px solid #454545;
    background: #363636;
}
QCheckBox::indicator:checked {
    background: #86b894;
    border-color: #86b894;
}
QCheckBox::indicator:disabled { background: #2f2f2f; border-color: #3a3a3a; }

/* ---- splitter / scrolling ---- */
QSplitter::handle          { background: #454545; }
QSplitter::handle:hover    { background: #5a5a5a; }
QScrollArea                { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical {
    background: #2b2b2b; width: 12px; margin: 0px;
}
QScrollBar::handle:vertical {
    background: #454545; border-radius: 6px; min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #5a5a5a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

/* ---- sections ---- */
QToolButton#sectionHeader {
    background: transparent;
    color: #a99f8d;
    border: none;
    border-radius: 0;
    padding: 2px 4px;
    text-align: left;
}
QToolButton#sectionHeader:hover { color: #ffebcd; }

/* ---- details ---- */
QFrame#detailsCard { background: #3c3c3c; border-radius: 8px; }
QFrame#conflictRow { background: #3c3c3c; border-radius: 4px; }
QLabel#fieldLabel { color: #6e6e6e; background: transparent; }

/* ---- selection bar / banner ---- */
QFrame#selectionBar { background: #d1b66b; border-radius: 6px; }
QLabel#selectionLabel { color: #1a1a1a; font-weight: bold; background: transparent; }
QLabel#warningBanner {
    background: #363636;
    color: #cf8a8a;
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: bold;
}
QLabel#statusLabel { background: transparent; }

/* ---- menus ---- */
QMenu { background: #363636; border: 1px solid #454545; }
QMenu::item { padding: 4px 18px; }
QMenu::item:selected { background: #424242; }
QMenu::separator { height: 1px; background: #454545; margin: 4px 6px; }

/* ---- tree ---- */
QTreeWidget {
    background: #3c3c3c;
    color: #ffebcd;
    border: 1px solid #454545;
    alternate-background-color: #3c3c3c;
}
QTreeWidget::item:selected { background: #636363; }
QHeaderView::section {
    background: #4c4c4c;
    color: #ffebcd;
    padding: 2px 6px;
    border: none;
}

/* ---- progress overlay ---- */
QFrame#progressOverlay { background: #000000; }
QFrame#progressCard { background: #2b2b2b; border-radius: 8px; }
QProgressBar {
    background: #3c3c3c;
    border: none;
    border-radius: 6px;
    height: 14px;
    text-align: center;
    color: #1a1a1a;
}
QProgressBar::chunk { background: #86b894; border-radius: 6px; }

/* ---- load-order number gutter: 1 loads first ---- */
QLabel#modIndex {
    color: #a99f8d;
    background: transparent;
}

/* ---- details card values: indent lives in details_panel.card ---- */
"""

# colours come from constants
QSS = QSS.replace("@noConflictFill", Colors.NO_CONFLICT_FILL)


DPI_NOTICE_PREFIXES = (
    "SetProcessDpiAwarenessContext() failed",
    "Qt's default DPI awareness context is "
    "DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2",
)


def _silence_inherited_dpi_notice():
    # drop the dpi advisory
    from PySide6.QtCore import qInstallMessageHandler

    def _handler(_mode, context, message):
        if message and message.startswith(DPI_NOTICE_PREFIXES):
            return
        category = getattr(context, "category", "") or ""
        sys.stderr.write("%s%s\n" % (category + ": " if category else "", message))

    qInstallMessageHandler(_handler)


def configure_high_dpi():
    # before QApplication exists
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    _silence_inherited_dpi_notice()


def apply_theme(app):
    # install the font and stylesheet
    font = QFont()
    font.setPointSize(9)
    app.setFont(font)
    app.setStyleSheet(QSS)
    app.setStyle("Fusion")