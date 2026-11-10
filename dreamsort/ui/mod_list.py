# mod list

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .dnd import has_local_urls, has_mod_row, mod_id_from_mime, paths_from_mime
from .mod_row import ModRow


class ModListWidget(QWidget):
    # row stack

    dropPaths = Signal(list)          # install
    reorderRequested = Signal(str, int)  # insert index

    def __init__(self, parent=None, accept_drops=True):
        super().__init__(parent)
        self.setObjectName("modContainer")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(5, 2, 5, 2)
        self._layout.setSpacing(4)
        self._layout.addStretch(1)

        self._items = []          # rows
        self.rows = {}            # mod_id -> row
        self._drop_index = None
        self._indicator = None
        self.setAcceptDrops(accept_drops)

    # contents
    def add_item(self, widget):
        self._items.append(widget)
        self._layout.insertWidget(self._layout.count() - 1, widget)

    def add_row(self, row):
        self.rows[row.mod_id] = row
        self.add_item(row)

    def add_divider(self, text):
        label = QLabel(text, self)
        label.setObjectName("cheatsDivider")
        self.add_item(label)
        return label

    def clear_items(self):
        for widget in self._items:
            self._layout.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._items = []
        self.rows = {}
        self._drop_index = None
        self._hide_indicator()

    def remove_row(self, row, delete=True):
        if row is None or row not in self._items:
            return False
        self._items.remove(row)
        self._layout.removeWidget(row)
        self.rows.pop(row.mod_id, None)
        if delete:
            row.setParent(None)
            row.deleteLater()
        return True

    def row_widgets(self):
        return [w for w in self._items if isinstance(w, ModRow)]

    def sortable_rows(self):
        # orderable rows only
        return [w for w in self._items
                if isinstance(w, ModRow) and w.checkbox is not None]

    def order_ids(self):
        return [w.mod_id for w in self._items if isinstance(w, ModRow)]

    # reorder
    def _sync_layout(self):
        for widget in self._items:
            self._layout.removeWidget(widget)
        for index, widget in enumerate(self._items):
            self._layout.insertWidget(index, widget)

    def move_row(self, mod_id, target_index):
        # move to index
        row = self.rows.get(mod_id)
        if row is None or row not in self._items:
            return False
        if row.checkbox is None:
            # not orderable
            return False
        rows = self.sortable_rows()
        others = [w for w in rows if w is not row]
        target_index = max(0, min(int(target_index), len(others)))
        # keep the rest in order
        if target_index >= len(others):
            anchor = None
        else:
            anchor = others[target_index]
        self._items.remove(row)
        if anchor is None:
            # past the last row
            if rows:
                last = others[-1] if others else None
                if last is not None:
                    position = self._items.index(last) + 1
                else:
                    position = 0
            else:
                position = 0
            self._items.insert(position, row)
        else:
            self._items.insert(self._items.index(anchor), row)
        self._sync_layout()
        return True

    def reorder_to(self, ordered_ids):
        # top, in this order
        rows = {w.mod_id: w for w in self.sortable_rows()}
        head = [rows[i] for i in ordered_ids if i in rows]
        if not head:
            return False
        sortable = self.sortable_rows()
        sortable_ids = {id(w) for w in sortable}
        rest = [w for w in sortable if w not in head]
        kept = [w for w in self._items if id(w) not in sortable_ids]
        self._items = head + rest + kept
        self._sync_layout()
        return True

    # drag and drop
    def _can_drop(self, source_id):
        # orderable rows only
        row = self.rows.get(source_id)
        return (row is not None and row in self._items
                and row.checkbox is not None)

    def _index_at(self, y):
        rows = self.sortable_rows()
        if rows and y > rows[-1].geometry().bottom():
            # empty space means the end
            start = self._items.index(rows[-1]) + 1
            for widget in self._items[start:]:
                if not widget.isVisible():
                    continue
                area = widget.geometry()
                if area.y() <= y <= area.y() + area.height():
                    return None
            return len(rows)
        for index, row in enumerate(rows):
            geometry = row.geometry()
            if y < geometry.y() + geometry.height() / 2:
                return index
        return len(rows)

    def _show_indicator(self, index):
        if self._indicator is None:
            self._indicator = QFrame(self)
            self._indicator.setObjectName("dropIndicator")
            self._indicator.setFixedHeight(2)
            self._indicator.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        rows = self.sortable_rows()
        self._layout.removeWidget(self._indicator)
        if index < len(rows):
            self._layout.insertWidget(self._layout.indexOf(rows[index]),
                                      self._indicator)
        else:
            self._layout.insertWidget(self._layout.count() - 1, self._indicator)
        self._indicator.show()

    def _hide_indicator(self):
        if self._indicator is not None:
            self._layout.removeWidget(self._indicator)
            self._indicator.hide()

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if has_mod_row(mime):
            if self._can_drop(mod_id_from_mime(mime)):
                event.acceptProposedAction()
                return
            event.ignore()
            return
        if has_local_urls(mime):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        mime = event.mimeData()
        if has_mod_row(mime):
            index = (self._index_at(event.position().y())
                     if self._can_drop(mod_id_from_mime(mime)) else None)
            if index is None:
                self._drop_index = None
                self._hide_indicator()
                event.ignore()
                return
            self._drop_index = index
            self._show_indicator(index)
            event.acceptProposedAction()
            return
        if has_local_urls(mime):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._hide_indicator()
        self._drop_index = None
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        self._hide_indicator()
        if has_mod_row(mime):
            source_id = mod_id_from_mime(mime)
            index = self._drop_index
            if index is None:
                index = self._index_at(event.position().y())
            self._drop_index = None
            if index is not None and self._can_drop(source_id):
                self.reorderRequested.emit(source_id, index)
                event.acceptProposedAction()
                return
            event.ignore()
            return
        if has_local_urls(mime):
            self._drop_index = None
            self.dropPaths.emit(paths_from_mime(mime))
            event.acceptProposedAction()
            return
        event.ignore()


class ModScrollArea(QScrollArea):
    # scroll wrapper

    def __init__(self, content: ModListWidget, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setWidget(content)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
