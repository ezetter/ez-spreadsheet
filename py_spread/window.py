"""Main window: a cell-reference label and edit bar above the grid."""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .clipboard import ClipboardController
from .model import SheetModel
from .references import cell_name

# A clicked cell reference can be inserted after any of these characters.
REFERENCE_TRIGGERS = "=+-*/^("


class ReferenceInserter:
    """Inserts clicked cell references into a formula being typed in a line edit.

    A reference is accepted right after '=', an operator, or '('. Clicking again
    straight after an insertion replaces that reference, as in other spreadsheets.
    """

    def __init__(self, edit: QLineEdit):
        self.edit = edit
        self._last = None  # (start, end, text) of the most recent insertion

    def reset(self) -> None:
        self._last = None

    def _replacing(self) -> bool:
        return self._last is not None and self._last[1:] == (self.edit.cursorPosition(), self.edit.text())

    def accepts(self) -> bool:
        text = self.edit.text()
        if not text.startswith("="):
            return False
        if self._replacing():
            return True
        before = text[: self.edit.cursorPosition()].rstrip()
        return bool(before) and before[-1] in REFERENCE_TRIGGERS

    def insert(self, ref: str) -> None:
        text = self.edit.text()
        pos = self.edit.cursorPosition()
        start = self._last[0] if self._replacing() else pos
        new_text = text[:start] + ref + text[pos:]
        end = start + len(ref)
        # Record first: setText notifies listeners, which call accepts().
        self._last = (start, end, new_text)
        self.edit.setText(new_text)
        self.edit.setCursorPosition(end)


class CellDelegate(QStyledItemDelegate):
    """Cell delegate that reports new editors and Return presses, and draws the
    dashed outline around copied cells."""

    editor_created = Signal(QLineEdit)
    return_pressed = Signal()

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        self.editor_created.emit(editor)
        return editor

    def eventFilter(self, editor, event):
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, QStyledItemDelegate.NoHint)
            self.return_pressed.emit()
            return True
        return super().eventFilter(editor, event)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        marquee = self.parent().marquee
        if marquee is None:
            return
        top, left, bottom, right = marquee
        row, col = index.row(), index.column()
        if not (top <= row <= bottom and left <= col <= right):
            return
        rect = option.rect
        painter.save()
        painter.setPen(QPen(option.palette.highlight().color(), 2, Qt.DashLine))
        if row == top:
            painter.drawLine(rect.left(), rect.top() + 1, rect.right(), rect.top() + 1)
        if row == bottom:
            painter.drawLine(rect.left(), rect.bottom() - 1, rect.right(), rect.bottom() - 1)
        if col == left:
            painter.drawLine(rect.left() + 1, rect.top(), rect.left() + 1, rect.bottom())
        if col == right:
            painter.drawLine(rect.right() - 1, rect.top(), rect.right() - 1, rect.bottom())
        painter.restore()


class SheetView(QTableView):
    """Table view with spreadsheet-style keyboard and mouse behavior."""

    editor_closed = Signal()
    escape_pressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.horizontalHeader().setDefaultSectionSize(100)
        self.verticalHeader().setDefaultSectionSize(24)

        self.cell_delegate = CellDelegate(self)
        self.cell_delegate.return_pressed.connect(lambda: self.move_current(1, 0))
        self.setItemDelegate(self.cell_delegate)

        # Returns the ReferenceInserter for the formula being edited, if any.
        self.reference_target = lambda: None
        self._swallow_mouse = False
        # (top, left, bottom, right) of copied cells, outlined until pasted or cancelled.
        self.marquee = None

    def set_marquee(self, bounds) -> None:
        if bounds != self.marquee:
            self.marquee = bounds
            self.viewport().update()

    def keyPressEvent(self, event):
        if self.state() != QAbstractItemView.EditingState:
            key = event.key()
            if key in (Qt.Key_Delete, Qt.Key_Backspace):
                self.model().clear_cells(self.selectedIndexes())
                return
            if key == Qt.Key_F2:
                self.edit(self.currentIndex())
                return
            if key == Qt.Key_Escape:
                self.escape_pressed.emit()
                return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if not self._insert_reference(event):
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if not self._insert_reference(event):
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        if not self._swallow_mouse:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._swallow_mouse:
            self._swallow_mouse = False
            return
        super().mouseReleaseEvent(event)

    def _insert_reference(self, event) -> bool:
        """If a formula is waiting for a reference, insert the clicked cell's name."""
        target = self.reference_target()
        index = self.indexAt(event.position().toPoint())
        if event.button() != Qt.LeftButton or target is None or not index.isValid() or not target.accepts():
            return False
        target.insert(cell_name(index.row(), index.column()))
        target.edit.setFocus()
        self._swallow_mouse = True
        return True

    def closeEditor(self, editor, hint):
        # Reference mode turns off click focus; restore it so the view can take focus back.
        self.setFocusPolicy(Qt.StrongFocus)
        super().closeEditor(editor, hint)
        self.editor_closed.emit()

    def move_current(self, d_row: int, d_col: int) -> None:
        current = self.currentIndex()
        row = min(max(current.row() + d_row, 0), self.model().rowCount() - 1)
        col = min(max(current.column() + d_col, 0), self.model().columnCount() - 1)
        self.setCurrentIndex(self.model().index(row, col))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Py-Spread")
        self.resize(1100, 700)

        self.model = SheetModel(parent=self)
        self.view = SheetView()
        self.view.setModel(self.model)

        self.cell_label = QLabel()
        self.cell_label.setMinimumWidth(60)
        self.cell_label.setAlignment(Qt.AlignCenter)
        self.edit_bar = QLineEdit()
        self.edit_bar.setPlaceholderText("Cell contents")

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 6, 6, 0)
        bar.addWidget(self.cell_label)
        bar.addWidget(self.edit_bar)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self.view)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.clipboard = ClipboardController(self.view, self.model)
        self._build_edit_menu()

        self._bar_refs = ReferenceInserter(self.edit_bar)
        self._grid_refs = None  # ReferenceInserter for the open in-cell editor
        self.view.reference_target = self._reference_target

        self.view.selectionModel().currentChanged.connect(self._on_current_changed)
        self.view.cell_delegate.editor_created.connect(self._on_editor_created)
        self.view.editor_closed.connect(self._on_editor_closed)
        self.model.dataChanged.connect(self._on_data_changed)
        self.edit_bar.returnPressed.connect(self._commit_edit_bar)
        self.edit_bar.textChanged.connect(self._update_reference_mode)
        self.edit_bar.cursorPositionChanged.connect(self._update_reference_mode)
        self.edit_bar.installEventFilter(self)
        QApplication.instance().focusChanged.connect(self._update_reference_mode)

        self.view.setCurrentIndex(self.model.index(0, 0))
        self.view.setFocus()

    def _build_edit_menu(self):
        menu = self.menuBar().addMenu("Edit")
        for name, shortcut, method in (
            ("Cut", QKeySequence.Cut, "cut"),
            ("Copy", QKeySequence.Copy, "copy"),
            ("Paste", QKeySequence.Paste, "paste"),
        ):
            action = QAction(name, self)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda _checked=False, m=method: self._clipboard_action(m))
            menu.addAction(action)

    def _clipboard_action(self, method: str):
        # While text is being edited (cell editor or edit bar), act on the text.
        # Keyboard shortcuts reach the line edit directly; this covers the menu.
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            getattr(focus, method)()
        else:
            getattr(self.clipboard, method)()

    def _reference_target(self):
        if self._grid_refs is not None:
            return self._grid_refs
        if self.edit_bar.hasFocus():
            return self._bar_refs
        return None

    def _update_reference_mode(self, *_args):
        # While a formula is waiting for a reference, clicking the grid must not
        # take focus away from the editor, which would commit the formula early.
        target = self._reference_target()
        accepting = target is not None and target.accepts()
        self.view.setFocusPolicy(Qt.NoFocus if accepting else Qt.StrongFocus)

    def _on_editor_created(self, editor):
        self._grid_refs = ReferenceInserter(editor)
        editor.textChanged.connect(self._on_grid_editor_text)
        editor.cursorPositionChanged.connect(self._update_reference_mode)

    def _on_grid_editor_text(self, text):
        self.edit_bar.setText(text)
        self._update_reference_mode()

    def _on_editor_closed(self):
        self._grid_refs = None
        self._refresh_bar(self.view.currentIndex())
        self._update_reference_mode()

    def _on_current_changed(self, current, _previous):
        self._refresh_bar(current)

    def _on_data_changed(self, top_left, bottom_right, _roles=()):
        if self.edit_bar.hasFocus():
            return  # don't clobber text being typed in the bar
        current = self.view.currentIndex()
        if (top_left.row() <= current.row() <= bottom_right.row()
                and top_left.column() <= current.column() <= bottom_right.column()):
            self._refresh_bar(current)

    def _refresh_bar(self, index):
        self._bar_refs.reset()
        if not index.isValid():
            self.cell_label.setText("")
            self.edit_bar.setText("")
            return
        self.cell_label.setText(cell_name(index.row(), index.column()))
        self.edit_bar.setText(self.model.get_cell(index.row(), index.column()))

    def _store_edit_bar(self):
        index = self.view.currentIndex()
        if index.isValid():
            self.model.set_cell(index.row(), index.column(), self.edit_bar.text())

    def _commit_edit_bar(self):
        self._store_edit_bar()
        self.view.move_current(1, 0)
        self.view.setFocus()

    def eventFilter(self, obj, event):
        if obj is self.edit_bar:
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                # Discard changes and return to the grid.
                self._refresh_bar(self.view.currentIndex())
                self.view.setFocus()
                return True
            if event.type() == QEvent.FocusOut and event.reason() not in (
                    Qt.ActiveWindowFocusReason, Qt.PopupFocusReason):
                # Leaving the bar commits what was typed, like leaving a cell.
                self._store_edit_bar()
        return super().eventFilter(obj, event)
