# theme

import sys
from string import Template

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QGuiApplication, QFont

from ..constants import Colors

# every colour the stylesheet uses; high contrast overrides the same names
DEFAULT_TOKENS = {
    "window": "#2b2b2b",
    "card": "#3c3c3c",
    "cardBorder": "#555555",
    "rowBg": "#363636",
    "rowHover": "#3c3c3c",
    "surface": "#363636",
    "surfaceHover": "#424242",
    "surfacePressed": "#2f2f2f",
    "chipBg": "#363636",
    "border": "#5f5f5f",
    "borderHover": "#8a8a8a",
    "controlBorder": "1px",
    "text": "#ffebcd",
    "valueText": "#ffebcd",
    "keyText": "#e6ddcf",
    "sectionText": "#d2c9bb",
    "textMuted": "#b3a998",
    "textDisabled": "#a99f8d",
    "rowRule": "#4a4a4a",
    "sectionRule": "#7a7a7a",
    "divider": "#505050",
    "focus": "#ffd54a",
    "inputFocus": "#9a9a9a",
    "primary": "#ffebcd",
    "primaryHover": "#e3cdb0",
    "primaryPressed": "#cfb99c",
    "primaryText": "#1a1a1a",
    "accent": "#ffb74d",
    "selectedRow": "#5a5233",
    "selectedBorder": "#d1b66b",
    "selectedBar": "#d1b66b",
    "menuBg": "#363636",
    "menuHover": "#5c5c5c",
    "tooltipBg": "#1f1f1f",
    "tooltipText": "#ffebcd",
    "tooltipBorder": "#6e6e6e",
    "splitter": "#454545",
    "splitterHover": "#5a5a5a",
    "scrollHandle": "#454545",
    "scrollHover": "#5a5a5a",
    "headerBg": "#4c4c4c",
    "treeBg": "#3c3c3c",
    "treeSelect": "#636363",
    "sectionRowBg": "#3c3c3c",
    "sectionRowBorder": "#454545",
    "link": "#c6dcf1",
    "noConflict": Colors.NO_CONFLICT_FILL,
    "engineModule": Colors.ENGINE_MODULE,
}

HIGH_CONTRAST_TOKENS = {
    "window": "#000000",
    "card": "#121212",
    "cardBorder": "#bdbdbd",
    "rowBg": "#121212",
    "rowHover": "#2a2a2a",
    "surface": "#121212",
    "surfaceHover": "#2e2e2e",
    "surfacePressed": "#000000",
    "chipBg": "#2a2a2a",
    "border": "#bdbdbd",
    "borderHover": "#ffffff",
    "controlBorder": "2px",
    "text": "#ffffff",
    "valueText": "#ededed",
    "keyText": "#ffffff",
    "sectionText": "#ffffff",
    "textMuted": "#c8c8c8",
    "textDisabled": "#c8c8c8",
    "rowRule": "#9a9a9a",
    "sectionRule": "#ffffff",
    "divider": "#9a9a9a",
    "focus": "#ffd54a",
    "inputFocus": "#ffd54a",
    "primary": "#ffd08a",
    "primaryHover": "#ffdfae",
    "primaryPressed": "#f0b86a",
    "primaryText": "#000000",
    "accent": "#ffd54a",
    "selectedRow": "#2a2a2a",
    "selectedBorder": "#ffffff",
    "selectedBar": "#ffd08a",
    "menuBg": "#121212",
    "menuHover": "#3a3a3a",
    "tooltipBg": "#000000",
    "tooltipText": "#ffffff",
    "tooltipBorder": "#bdbdbd",
    "splitter": "#9a9a9a",
    "splitterHover": "#ffffff",
    "scrollHandle": "#bdbdbd",
    "scrollHover": "#ffffff",
    "headerBg": "#2a2a2a",
    "treeBg": "#121212",
    "treeSelect": "#3a3a3a",
    "sectionRowBg": "#2a2a2a",
    "sectionRowBorder": "#bdbdbd",
    "link": "#ffffff",
}

# padding that keeps a control the same size under its 1px and 2px borders
PAD = "4px 10px"
PAD_FOCUS = "3px 9px"

QSS = Template("""
QWidget {
    background: $window;
    color: $text;
}
QMainWindow, QDialog { background: $window; }

QToolTip {
    background: $tooltipBg;
    color: $tooltipText;
    border: 1px solid $tooltipBorder;
    padding: 4px 6px;
}

QFrame#listPanel, QFrame#detailsPanel, QFrame#modContainer {
    background: $window;
}
QFrame#detailsPanelInner { background: $window; }

/* holder stays clear so the strip's shadow shows through */
QWidget#downloadStripHolder { background: transparent; }

/* ---- column headings ---- */
QLabel#panelHeader {
    color: $textMuted;
    background: transparent;
    font-weight: bold;
    padding: 0 2px;
}

/* ---- mod rows: rounded via QSS, recoloured via dynamic properties ---- */
QFrame#modRow {
    background: $rowBg;
    border: 2px solid $noConflict;
    border-radius: 8px;
}
QFrame#modRow:hover { background: $rowHover; }
QFrame#modRow[conflictState="winner"]  { border-color: #86b894; }
QFrame#modRow[conflictState="loser"]   { border-color: #cf8a8a; }
QFrame#modRow[conflictState="none"]    { border-color: $noConflict; }
QFrame#modRow[conflictState="disabled"]{ border-color: #6e6e6e; }
QFrame#modRow[variant="cheat"]   { border-color: #a8814f; }
QFrame#modRow[variant="module"] { border-color: $engineModule; }
QFrame#modRow[variant="module"][conflictState="disabled"] { border-color: #6e6e6e; }
/* group header row: sits in the list like a row, not a label */
QFrame#modRow[variant="section"] {
    background: $sectionRowBg;
    border: 2px solid $sectionRowBorder;
    border-radius: 8px;
}
QFrame#modRow[variant="section"]:hover { background: #454545; }
QFrame#modRow[variant="section"] QLabel#modName {
    color: #d4a26a;
    font-weight: bold;
}
QFrame#modRow[selected="true"] {
    background: $selectedRow;
    border-color: $selectedBorder;
}
/* child rows: the recomp's plugin look, flat and indented */
QFrame#modRow[variant="child"] {
    background: transparent;
    border: none;
    border-radius: 0;
}
QFrame#modRow[variant="child"]:hover { background: #323232; }
QFrame#modRow[variant="child"][selected="true"] { background: #323232; }
QFrame#modRow[variant="child"][selected="true"] QLabel#modName {
    color: #d1b66b;
    font-weight: bold;
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
QLabel#chip[kind="module"] { background: $engineModule; }
QLabel#chip[kind="arc"]   { background: #3eff65; }
QLabel#chip[kind="muted"] { background: #6e6e6e; }
QLabel#chip[kind="update"] { background: #ffd166; color: #1f1f1f; }
QLabel#chip[kind="choice"] { background: #c9dcae; color: #1f1f1f; }
QLabel#chip[kind="none"]  { background: $noConflict; color: #1a1a1a; }

QLabel#dragHandle {
    color: $text;
    border: none;
    background: transparent;
    padding: 0px 4px;
}

/* ---- list group header ---- */
QLabel#listHeader {
    background: $sectionRowBg;
    color: #d4a26a;
    border: 2px solid $sectionRowBorder;
    border-radius: 8px;
    padding: 4px 8px;
    font-weight: bold;
}
QLabel#dropIndicator { background: $selectedBar; border-radius: 1px; }

/* ---- buttons: a visible edge, and a ring only when tabbing in ---- */
QPushButton {
    background: $surface;
    color: $text;
    border: $controlBorder solid $border;
    border-radius: 6px;
    padding: $pad;
    min-height: 18px;
}
QPushButton:hover    { background: $surfaceHover; border-color: $borderHover; }
QPushButton:pressed  { background: $surfacePressed; }
QPushButton:disabled { color: $textDisabled; background: $surface; }

QPushButton#primaryBtn {
    background: $primary;
    color: $primaryText;
    border-color: $primary;
    font-weight: bold;
}
QPushButton#primaryBtn:hover { background: $primaryHover; border-color: $primaryHover; }
QPushButton#primaryBtn:pressed { background: $primaryPressed; border-color: $primaryPressed; }
QPushButton#primaryBtn:disabled { color: $primaryText; }

/* plain until something is waiting to be written, then an accent outline */
QPushButton#applyBtn { font-weight: bold; }
QPushButton#applyBtn[unapplied="true"] {
    border: 2px solid $accent;
    padding: $padFocus;
    color: $accent;
}

QPushButton#viewBtn {
    background: $surface;
    color: $text;
    border-radius: 6px;
}
QPushButton#viewBtn:checked {
    background: $surfaceHover;
    border-color: $borderHover;
}

QPushButton#linkBtn {
    background: transparent;
    color: $link;
    border: none;
    border-radius: 4px;
    padding: 0 6px;
    text-decoration: underline;
    min-height: 0;
}
QPushButton#linkBtn:hover { background: $surfaceHover; }

QToolButton {
    background: $surface;
    color: $text;
    border: $controlBorder solid $border;
    border-radius: 6px;
    padding: $pad;
    min-height: 18px;
}
QToolButton:hover   { background: $surfaceHover; border-color: $borderHover; }
QToolButton:pressed { background: $surfacePressed; }
QToolButton::menu-indicator { image: none; width: 0px; }

QPushButton[kbFocus="true"], QToolButton[kbFocus="true"] {
    border: 2px solid $focus;
    padding: $padFocus;
}

/* ---- inputs ---- */
QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {
    background: $surface;
    color: $text;
    border: $controlBorder solid $border;
    border-radius: 6px;
    padding: $inputPad;
    selection-background-color: #636363;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {
    border-color: $inputFocus;
}
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: $surface;
    color: $text;
    border: 1px solid $border;
    selection-background-color: $surfaceHover;
}

QCheckBox { background: transparent; spacing: 6px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border-radius: 3px;
    border: 1px solid $borderHover;
    background: $surface;
}
QCheckBox::indicator:checked {
    background: #86b894;
    border-color: #86b894;
}
QCheckBox::indicator:disabled { background: #2f2f2f; border-color: #3a3a3a; }

/* ---- splitter / scrolling ---- */
QSplitter::handle          { background: $splitter; }
QSplitter::handle:hover    { background: $splitterHover; }
QScrollArea                { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical {
    background: $window; width: 12px; margin: 0px;
}
QScrollBar::handle:vertical {
    background: $scrollHandle; border-radius: 6px; min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: $scrollHover; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

/* ---- sections ---- */
QToolButton#sectionHeader {
    background: transparent;
    color: $textMuted;
    border: none;
    border-radius: 0;
    padding: 2px 4px;
    text-align: left;
}
QToolButton#sectionHeader:hover { color: $text; }
QToolButton#sectionHeader[kbFocus="true"] {
    border: 2px solid $focus;
    border-radius: 4px;
}

/* ---- details ---- */
QFrame#detailsCard { background: $card; border: 1px solid $cardBorder; border-radius: 8px; }
QFrame#conflictRow { background: $card; border-radius: 4px; }
QLabel#fieldLabel { color: $keyText; background: transparent; }

/* ---- details sheet: one card, so everything inside it stays clear ---- */
QFrame#detailsSheet { background: $card; border: 1px solid $cardBorder; border-radius: 12px; }
QWidget#sheetHost, QWidget#chipHost, QWidget#sectionGap, QLabel#sheetLabel, QWidget#sheetIcon,
QWidget#detailRow, QWidget#detailKey, QWidget#detailSection,
QWidget#detailRule, QWidget#sectionRule {
    background: transparent;
}
QLabel[role="key"]     { color: $keyText; }
QLabel[role="value"]   { color: $valueText; }
QLabel[role="section"] { color: $sectionText; font-weight: bold; }

/* ---- selection bar / banner ---- */
QFrame#selectionBar { background: $selectedBar; border-radius: 6px; }
QLabel#selectionLabel { color: #1a1a1a; font-weight: bold; background: transparent; }
QLabel#warningBanner {
    background: $surface;
    color: #cf8a8a;
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: bold;
}
QLabel#versionBanner {
    background: $surface;
    color: #d1b66b;
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: bold;
}
QLabel#packBanner {
    background: $surface;
    color: #d4a26a;
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: bold;
}
QLabel#statusLabel { background: transparent; }

/* ---- menus ---- */
QMenu {
    background: $menuBg;
    color: $text;
    border: 1px solid $tooltipBorder;
    padding: 4px;
}
QMenu::item { padding: 5px 24px 5px 12px; border-radius: 4px; }
QMenu::item:selected { background: $menuHover; }
QMenu::item:disabled { color: $textDisabled; }
QMenu::icon { margin-left: 4px; }
QMenu::separator { height: 1px; background: $divider; margin: 4px 8px; }

/* ---- tree ---- */
QTreeWidget {
    background: $treeBg;
    color: $text;
    border: 1px solid $border;
    alternate-background-color: $treeBg;
}
QTreeWidget::item:selected { background: $treeSelect; }
QHeaderView::section {
    background: $headerBg;
    color: $text;
    padding: 2px 6px;
    border: none;
}

/* ---- progress overlay ---- */
QFrame#progressOverlay { background: #000000; }
QFrame#progressCard { background: $window; border: 1px solid $cardBorder; border-radius: 8px; }
QProgressBar {
    background: $card;
    border: 1px solid $borderHover;
    border-radius: 6px;
    height: 14px;
    text-align: center;
    color: #1a1a1a;
}
QProgressBar::chunk { background: #86b894; border-radius: 6px; }

/* ---- load-order number gutter: 1 loads first ---- */
QLabel#modIndex {
    color: $textMuted;
    background: transparent;
}
""")

# only while high contrast is on; later rules win over the shared ones above
HIGH_CONTRAST_QSS = Template("""
/* ---- high contrast ---- */
QFrame#modRow[conflictState="disabled"],
QFrame#modRow[variant="module"][conflictState="disabled"] { border-color: #9a9a9a; }
QFrame#modRow[variant="section"]:hover,
QLabel#listHeader { background: #2a2a2a; color: #ffffff; border-color: #bdbdbd; }
QFrame#modRow[selected="true"],
QFrame#modRow[variant="child"][selected="true"] {
    background: #2a2a2a;
    border-color: #ffffff;
}
QFrame#modRow[variant="child"][selected="true"] {
    border: none;
}
QFrame#modRow[selected="true"] QLabel#modName,
QFrame#modRow[variant="child"][selected="true"] QLabel#modName,
QFrame#fileRow[selected="true"] QLabel#fileName {
    color: #ffffff;
    font-weight: bold;
}
QFrame#modRow[variant="child"]:hover, QFrame#fileRow:hover { background: #202020; }
QFrame#fileRow[active="false"] QLabel#fileName,
QFrame#fileRow[missing="true"] QLabel#fileName,
QFrame#modRow[conflictState="disabled"] QLabel#modName { color: #c8c8c8; }
QLabel#modIndex, QLabel#dragHandle, QLabel#fieldLabel,
QFrame#modRow[variant="section"] QLabel#modName { color: #ffffff; }
QLabel#chip[kind="muted"] { background: #c8c8c8; color: #000000; }

QFrame#detailsCard, QFrame#detailsSheet { border: 2px solid $cardBorder; }
QLabel#panelHeader { color: #ffffff; }
QFrame#selectionBar { background: #ffd08a; }
QLabel#warningBanner, QLabel#versionBanner, QLabel#packBanner {
    border: 1px solid #c8c8c8;
}
""")

_tokens = dict(DEFAULT_TOKENS)
_high_contrast = False


def tokens():
    # the colours in use right now
    return dict(_tokens)


def token(name):
    # one colour of the theme in use
    return _tokens[name]


def high_contrast():
    return _high_contrast


def build_qss(values, hc=False):
    # the stylesheet for one theme
    pad = dict(values)
    wide = pad["controlBorder"] == "2px"
    # a thicker border takes the room back from the padding
    pad["pad"] = PAD_FOCUS if wide else PAD
    pad["padFocus"] = PAD_FOCUS
    pad["inputPad"] = "3px 7px" if wide else "4px 8px"
    qss = QSS.substitute(**pad)
    if hc:
        qss += HIGH_CONTRAST_QSS.substitute(**pad)
    return qss


class _KeyboardFocus(QObject):
    # marks buttons reached by keyboard, where a focus ring belongs
    def eventFilter(self, watched, event):
        if watched.inherits("QAbstractButton"):
            if event.type() == QEvent.FocusOut:
                self._mark(watched, False)
            elif event.type() == QEvent.MouseButtonPress:
                # a click on the focused button is still a mouse action
                self._mark(watched, False)
            elif event.type() == QEvent.FocusIn:
                self._mark(watched, event.reason() in (
                    Qt.TabFocusReason, Qt.BacktabFocusReason,
                    Qt.ShortcutFocusReason))
        return False

    @staticmethod
    def _mark(widget, tabbed):
        if widget.property("kbFocus") != tabbed:
            widget.setProperty("kbFocus", tabbed)
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)


_focus_filter = None


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


def apply_theme(app, hc=False):
    # install the font and stylesheet; safe to call again for a theme change
    global _tokens, _high_contrast, _focus_filter
    _high_contrast = bool(hc)
    _tokens = dict(DEFAULT_TOKENS)
    if _high_contrast:
        _tokens.update(HIGH_CONTRAST_TOKENS)
    font = QFont()
    font.setPointSize(9)
    app.setFont(font)
    app.setStyle("Fusion")
    app.setStyleSheet(build_qss(_tokens, _high_contrast))
    if _focus_filter is None:
        _focus_filter = _KeyboardFocus(app)
        app.installEventFilter(_focus_filter)
    from . import icons
    icons.refresh_icons()
