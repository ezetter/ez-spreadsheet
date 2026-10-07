"""Main window: a cell-reference label and edit bar above the grid."""

import dataclasses
import os

from PySide6.QtCore import QEvent, QItemSelection, QItemSelectionModel, QStandardPaths, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QFont, QKeySequence, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStyledItemDelegate,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .appearance import APPEARANCES, GridStyle, apply_appearance, saved_appearance
from .autosum import AGGREGATES, Aggregate, AutoSumController
from .clipboard import ClipboardController
from .csvfile import read_csv, write_csv
from .fill import FILL_MODES, FillController, FillMode
from .fill_dialogs import FillDialogs
from .functions import ANGLE_UNITS, DEGREES, RADIANS
from .names_dialog import NameCellDialog, NamesDialog
from .shift_dialog import SHIFT_LABELS, DeleteCellsDialog, InsertCellsDialog, ask_shift
from .model import DEFAULT_COLS, DEFAULT_ROWS, SheetModel
from .numformat import GENERAL, MAX_DECIMALS, NumberFormat, format_number
from .textstyle import PLAIN
from .references import cell_name
from .storage import EXTENSION, SheetData, SheetFileError, load_sheet, save_sheet

FILE_FILTER = f"Py-Spread Sheets (*{EXTENSION})"
COLUMN_WIDTH = 100  # default sizes at 100% zoom
ROW_HEIGHT = 24
ZOOM_LEVELS = (50, 67, 75, 80, 90, 100, 110, 125, 150, 175, 200, 250, 300)  # percent
CSV_FILTER = "CSV Files (*.csv);;Text Files (*.txt *.tsv);;All Files (*)"

# A clicked cell reference can be inserted after any of these characters.
REFERENCE_TRIGGERS = "=+-*/^(,:"


class ReferenceInserter:
    """Inserts clicked cell references into a formula being typed in a line edit.

    A reference is accepted right after "=", an operator, "(", ",", or ":".
    Clicking again straight after an insertion replaces that reference, as in
    other spreadsheets.
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
        self._grid_style = GridStyle()  # kept: setStyle doesn't take ownership
        self.setStyle(self._grid_style)
        self.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.horizontalHeader().setDefaultSectionSize(COLUMN_WIDTH)
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.verticalHeader().setMinimumSectionSize(8)  # room to zoom out

        self.cell_delegate = CellDelegate(self)
        self.cell_delegate.return_pressed.connect(lambda: self.move_current(1, 0))
        self.setItemDelegate(self.cell_delegate)

        # Returns the ReferenceInserter for the formula being edited, if any.
        self.reference_target = lambda: None
        # When set, a left click on a cell goes to this callable instead of selecting it.
        self.pick_handler = None
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
        if not (self._pick_cell(event) or self._insert_reference(event)):
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if not (self._pick_cell(event) or self._insert_reference(event)):
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        if not self._swallow_mouse:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._swallow_mouse:
            self._swallow_mouse = False
            return
        super().mouseReleaseEvent(event)

    def _pick_cell(self, event) -> bool:
        index = self.indexAt(event.position().toPoint())
        if self.pick_handler is None or event.button() != Qt.LeftButton or not index.isValid():
            return False
        self._swallow_mouse = True
        self.pick_handler(index)
        return True

    def _insert_reference(self, event) -> bool:
        """If a formula is waiting for a reference, insert the clicked cell's name."""
        target = self.reference_target()
        index = self.indexAt(event.position().toPoint())
        if event.button() != Qt.LeftButton or target is None or not index.isValid() or not target.accepts():
            return False
        target.insert(self.model().reference_text(index.row(), index.column()))
        target.edit.setFocus()
        self._swallow_mouse = True
        return True

    def closeEditor(self, editor, hint):
        # Reference mode turns off click focus; restore it so the view can take focus back.
        self.setFocusPolicy(Qt.StrongFocus)
        super().closeEditor(editor, hint)
        self.editor_closed.emit()

    def selection_bounds(self) -> tuple[int, int, int, int]:
        """(top, left, bottom, right) of the selection, or of the current cell."""
        indexes = self.selectedIndexes() or [self.currentIndex()]
        rows = [index.row() for index in indexes]
        cols = [index.column() for index in indexes]
        return min(rows), min(cols), max(rows), max(cols)

    def select_range(self, top: int, left: int, bottom: int, right: int) -> None:
        """Select a block of cells, make its top-left current, and scroll to it."""
        model = self.model()
        corner = model.index(top, left)
        selection = self.selectionModel()
        selection.setCurrentIndex(corner, QItemSelectionModel.NoUpdate)
        selection.select(QItemSelection(corner, model.index(bottom, right)), QItemSelectionModel.ClearAndSelect)
        self.scrollTo(corner)

    def move_current(self, d_row: int, d_col: int) -> None:
        current = self.currentIndex()
        row = min(max(current.row() + d_row, 0), self.model().rowCount() - 1)
        col = min(max(current.column() + d_col, 0), self.model().columnCount() - 1)
        self.setCurrentIndex(self.model().index(row, col))


def _rescale_header(header, base_size: int, old_zoom: int, new_zoom: int) -> None:
    """Scale a header's sections from one zoom to another. Sections the user
    resized keep their size relative to the default."""
    old_default = header.defaultSectionSize()
    new_default = max(1, round(base_size * new_zoom / 100))
    custom = {i: header.sectionSize(i) for i in range(header.count())
              if header.sectionSize(i) != old_default}
    header.setDefaultSectionSize(new_default)  # (this resets every section to the default)
    for i, size in custom.items():
        header.resizeSection(i, max(1, round(size * new_zoom / old_zoom)))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1100, 700)
        self.file_path: str | None = None
        self._set_file_path(None)

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
        self.autosum = AutoSumController(self.view, self.model)
        self.fill = FillController(self.view, self.model, FillDialogs(self))
        self._build_file_menu()
        self._build_edit_menu()
        self._build_insert_menu()
        self._build_format_menu()
        self._build_formulas_menu()
        self._build_claude_menu()
        self._build_view_menu()
        self._build_toolbar()
        self.model.angle_unit_changed.connect(self._show_angle_unit)

        self._bar_refs = ReferenceInserter(self.edit_bar)
        self._grid_refs = None  # ReferenceInserter for the open in-cell editor
        self.view.reference_target = self._reference_target

        self.view.selectionModel().currentChanged.connect(self._on_current_changed)
        self._build_context_menu()
        self.view.selectionModel().currentChanged.connect(self._show_current_style)
        self.model.dataChanged.connect(self._show_current_style)
        self.model.modelReset.connect(self._show_current_style)
        self.view.cell_delegate.editor_created.connect(self._on_editor_created)
        self.view.editor_closed.connect(self._on_editor_closed)
        self.model.dataChanged.connect(self._on_data_changed)
        self.model.names_changed.connect(self._show_current_name)
        self.model.contents_changed.connect(lambda: self.setWindowModified(True))
        # Undoing back to the saved state makes the sheet unmodified again.
        # (Bound methods, not lambdas: Qt disconnects them when the window is
        # destroyed, before the undo stack's last signals during teardown.)
        self.model.undo_stack.cleanChanged.connect(self._on_clean_changed)
        self.model.history_applied.connect(self._show_changed_cells)
        self.edit_bar.returnPressed.connect(self._commit_edit_bar)
        self.edit_bar.textChanged.connect(self._update_reference_mode)
        self.edit_bar.cursorPositionChanged.connect(self._update_reference_mode)
        self.edit_bar.installEventFilter(self)
        QApplication.instance().focusChanged.connect(self._update_reference_mode)

        self.view.setCurrentIndex(self.model.index(0, 0))
        self.view.setFocus()

    def _build_file_menu(self):
        menu = self.menuBar().addMenu("File")
        for name, shortcut, slot in (
            ("New", QKeySequence.New, self.new_file),
            ("Open…", QKeySequence.Open, self.open_file),
            ("Save", QKeySequence.Save, self.save),
            ("Save As…", QKeySequence.SaveAs, self.save_as),
        ):
            action = QAction(name, self)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda _checked=False, s=slot: s())
            menu.addAction(action)
        menu.addSeparator()
        for name, slot in (("Import CSV…", self.import_csv), ("Export CSV…", self.export_csv)):
            action = QAction(name, self)
            action.triggered.connect(lambda _checked=False, s=slot: s())
            menu.addAction(action)

    def _build_edit_menu(self):
        menu = self.menuBar().addMenu("Edit")
        self.edit_menu = menu
        self.insert_shift = "down"  # last choice in the Insert Cells dialog
        self.delete_shift = "up"  # and in the Delete Cells dialog
        stack = self.model.undo_stack
        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcuts(QKeySequence.Undo)
        self.undo_action.triggered.connect(lambda _checked=False: self._history_action("undo"))
        self.undo_action.setEnabled(stack.canUndo())
        stack.canUndoChanged.connect(self.undo_action.setEnabled)
        stack.undoTextChanged.connect(self._on_undo_text)
        menu.addAction(self.undo_action)

        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcuts(QKeySequence.Redo)  # includes Cmd+Shift+Z
        self.redo_action.triggered.connect(lambda _checked=False: self._history_action("redo"))
        self.redo_action.setEnabled(stack.canRedo())
        stack.canRedoChanged.connect(self.redo_action.setEnabled)
        stack.redoTextChanged.connect(self._on_redo_text)
        menu.addAction(self.redo_action)
        menu.addSeparator()

        self.clipboard_actions = {}
        for name, shortcut, method in (
            ("Cut", QKeySequence.Cut, "cut"),
            ("Copy", QKeySequence.Copy, "copy"),
            ("Paste", QKeySequence.Paste, "paste"),
        ):
            action = QAction(name, self)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda _checked=False, m=method: self._clipboard_action(m))
            menu.addAction(action)
            self.clipboard_actions[name] = action
        menu.addSeparator()
        self.insert_cells_action = QAction("Insert Cells…", self)
        self.insert_cells_action.triggered.connect(lambda _checked=False: self.insert_cells())
        menu.addAction(self.insert_cells_action)
        self.delete_cells_action = QAction("Delete Cells…", self)
        self.delete_cells_action.triggered.connect(lambda _checked=False: self.delete_cells())
        menu.addAction(self.delete_cells_action)

    def _build_context_menu(self):
        """The grid's secondary-click menu, made of the Edit menu's actions."""
        menu = QMenu(self)
        for action in self.clipboard_actions.values():
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(self.insert_cells_action)
        menu.addAction(self.delete_cells_action)
        menu.addSeparator()
        menu.addMenu(self.fill_menu)
        menu.addAction(self.name_cell_action)
        menu.addSeparator()
        menu.addAction(self.ask_claude_action)
        self.context_menu = menu
        # Qt selects a right-clicked cell outside the selection, and keeps the
        # selection when it's inside it, as other spreadsheets do.
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos):
        self._commit_pending_edit()
        self.context_menu.popup(self.view.viewport().mapToGlobal(pos))

    def _build_claude_menu(self):
        menu = self.menuBar().addMenu("Claude")
        self.claude_windows = []  # open Ask Claude windows
        self.ask_claude_action = QAction("Ask Claude…", self)
        self.ask_claude_action.setShortcut(QKeySequence("Ctrl+Shift+A"))  # ⌘⇧A on macOS
        self.ask_claude_action.triggered.connect(lambda _checked=False: self.ask_claude())
        menu.addAction(self.ask_claude_action)

    def ask_claude(self):
        """Open a window for asking Claude about the selected cells, or for
        having it fill the sheet."""
        # Imported here so the Anthropic SDK loads only when it's first used.
        from .claude_window import ClaudeWindow

        self._commit_pending_edit()
        window = ClaudeWindow(self.model, set(self._selected_cells()), parent=self, view=self.view)
        window.destroyed.connect(lambda _obj=None, w=window: self.claude_windows.remove(w)
                                 if w in self.claude_windows else None)
        self.claude_windows.append(window)
        window.show()
        return window

    def _build_view_menu(self):
        menu = self.menuBar().addMenu("View")
        self.zoom = 100  # percent
        self._zoom_base_fonts = None  # each zoomable widget's font at 100%, saved on first zoom
        self.zoom_actions = {}
        for name, shortcuts, slot in (
            # ⌘= as well as ⌘+, so Shift isn't needed for the + key
            ("Zoom In", [QKeySequence(QKeySequence.ZoomIn), QKeySequence("Ctrl+=")], self.zoom_in),
            ("Zoom Out", [QKeySequence(QKeySequence.ZoomOut)], self.zoom_out),
            ("Actual Size", [QKeySequence("Ctrl+0")], lambda: self.set_zoom(100)),
        ):
            action = QAction(name, self)
            action.setShortcuts(shortcuts)
            action.triggered.connect(lambda _checked=False, s=slot: s())
            menu.addAction(action)
            self.zoom_actions[name] = action

        # Appearance: follow the Mac, or always light or dark (remembered).
        menu.addSeparator()
        appearance_menu = menu.addMenu("Appearance")
        group = QActionGroup(self)
        self.appearance_actions = {}
        for key, (label, _scheme) in APPEARANCES.items():
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, k=key: self.set_appearance(k))
            group.addAction(action)
            appearance_menu.addAction(action)
            self.appearance_actions[key] = action
        self.set_appearance(saved_appearance(), save=False)

    def set_appearance(self, key: str, save: bool = True) -> None:
        """Match the Mac's appearance ("system"), or always use "light" or "dark"."""
        apply_appearance(key, save)
        self.appearance_actions[key].setChecked(True)

    def zoom_in(self):
        self.set_zoom(next((z for z in ZOOM_LEVELS if z > self.zoom), self.zoom))

    def zoom_out(self):
        self.set_zoom(next((z for z in reversed(ZOOM_LEVELS) if z < self.zoom), self.zoom))

    def set_zoom(self, percent: int) -> None:
        """Scale the grid (text, rows, columns, headers), the cell bar, the
        toolbar, and the status bar to `percent` of their normal size."""
        if self._zoom_base_fonts is None:
            self._zoom_base_fonts = {widget: QFont(widget.font()) for widget in self._zoomable_widgets()}
        old, self.zoom = self.zoom, percent
        for widget, base in self._zoom_base_fonts.items():
            font = QFont(base)
            if base.pointSizeF() > 0:
                font.setPointSizeF(base.pointSizeF() * percent / 100)
            else:
                font.setPixelSize(max(1, round(base.pixelSize() * percent / 100)))
            widget.setFont(font)
        _rescale_header(self.view.horizontalHeader(), COLUMN_WIDTH, old, percent)
        _rescale_header(self.view.verticalHeader(), ROW_HEIGHT, old, percent)
        for action, limit in ((self.zoom_actions["Zoom In"], ZOOM_LEVELS[-1]),
                              (self.zoom_actions["Zoom Out"], ZOOM_LEVELS[0])):
            action.setEnabled(percent != limit)
        self.statusBar().showMessage(f"Zoom {percent}%", 2000)

    def _zoomable_widgets(self) -> list:
        """Widgets whose font sets their size. (The menu bar is the Mac's own,
        so it isn't zoomed.)"""
        toolbar_widgets = [self.toolbar.widgetForAction(action) for action in self.toolbar.actions()
                           if not action.isSeparator()]
        return [self.view, self.view.horizontalHeader(), self.view.verticalHeader(),
                self.cell_label, self.edit_bar, self.statusBar(), *toolbar_widgets]

    def _build_insert_menu(self):
        menu = self.menuBar().addMenu("Insert")
        self.charts = []  # open chart windows
        # Charts start as line charts; the chart window switches the type.
        self.chart_action = QAction("Chart", self)
        self.chart_action.setToolTip(
            "Chart the selected cells: the first column is x, the others are y. "
            "Switch between line and scatter in the chart window.")
        self.chart_action.triggered.connect(lambda _checked=False: self.make_chart())
        menu.addAction(self.chart_action)

    def _build_chart_button(self, toolbar):
        self.chart_button = QToolButton()
        self.chart_button.setDefaultAction(self.chart_action)
        toolbar.addWidget(self.chart_button)

    def make_chart(self):
        """Open a line chart window for the selected cells; returns it, or None
        if the cells can't be charted (the status bar says why)."""
        # Imported here so Matplotlib loads only when a chart is first made.
        from .chart import ChartError, ChartWindow, chart_data

        self._commit_pending_edit()
        cells = self._selected_cells()
        try:
            chart_data(self.model, cells)
        except ChartError as e:
            self._show_status(f"Can't make a chart: {e}")
            return None
        window = ChartWindow(self.model, cells, "line", parent=self)
        window.destroyed.connect(lambda _obj=None, w=window: self._forget_chart(w))
        self.charts.append(window)
        window.show()
        self._show_status("")
        return window

    def _forget_chart(self, window):
        if window in self.charts:
            self.charts.remove(window)

    def close_charts(self):
        for window in list(self.charts):
            window.close()
        self.charts.clear()

    def _build_format_menu(self):
        menu = self.menuBar().addMenu("Format")
        self.format_actions = {}
        for name, fmt, example in (
            ("General", GENERAL, "1234.5"),
            ("Number", NumberFormat("number"), "1,234.50"),
            ("Currency", NumberFormat("currency"), "$1,234.50"),
        ):
            action = QAction(f"{name}  ({example})", self)
            action.triggered.connect(lambda _checked=False, n=name, f=fmt: self._set_number_format(n, f))
            menu.addAction(action)
            self.format_actions[name] = action
        menu.addSeparator()
        for name, delta in (("Increase Decimals", 1), ("Decrease Decimals", -1)):
            action = QAction(name, self)
            action.triggered.connect(lambda _checked=False, n=name, d=delta: self._change_decimals(n, d))
            menu.addAction(action)
            self.format_actions[name] = action
        menu.addSeparator()
        # Checked when the current cell has the style.
        for name, attribute, shortcut in (("Bold", "bold", QKeySequence.Bold),
                                          ("Italic", "italic", QKeySequence.Italic)):
            action = QAction(name, self)
            action.setCheckable(True)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda _checked=False, n=name, a=attribute: self._toggle_style(n, a))
            menu.addAction(action)
            self.format_actions[name] = action
    def _build_formulas_menu(self):
        menu = self.menuBar().addMenu("Formulas")
        group = QActionGroup(self)  # one of them is checked: the sheet's angle unit
        self.angle_actions = {}
        for unit in ANGLE_UNITS:
            action = QAction(f"Angles in {unit.capitalize()}", self)
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, u=unit: self.set_angle_unit(u))
            menu.addAction(action)
            self.angle_actions[unit] = action

        menu.addSeparator()
        self.name_cell_action = QAction("Name Cell…", self)
        self.name_cell_action.triggered.connect(lambda _checked=False: self.name_cell())
        menu.addAction(self.name_cell_action)
        self.names_action = QAction("Names…", self)
        self.names_action.triggered.connect(lambda _checked=False: self.edit_names())
        menu.addAction(self.names_action)

    def name_cell(self) -> bool:
        """Name the current cell, so formulas can use the name in place of
        its reference (=PI*r^2). Its current name can be changed or removed."""
        self._commit_pending_edit()
        index = self.view.currentIndex()
        name = self._ask_cell_name(index.row(), index.column())
        if name is None:
            return False
        problem = self.model.name_cell(index.row(), index.column(), name)
        if problem:  # (the dialog checks first; this is a safeguard)
            self._show_error("Couldn't name the cell.", problem)
            return False
        return True

    def _ask_cell_name(self, row: int, col: int) -> str | None:
        """The name chosen in the Name Cell dialog, or None if cancelled."""
        dialog = NameCellDialog(self.model, row, col, self)
        return dialog.chosen_name() if dialog.exec() == QDialog.Accepted else None

    def edit_names(self) -> bool:
        """Show every cell name, to rename, redefine, add, or delete."""
        self._commit_pending_edit()
        chosen = self._ask_names()
        if chosen is None:
            return False
        self.model.replace_names(chosen, "Edit Names")
        return True

    def _ask_names(self) -> dict | None:
        """The names as left in the Names dialog, or None if cancelled."""
        dialog = NamesDialog(self.model, self)
        return dialog.chosen_names() if dialog.exec() == QDialog.Accepted else None

    def set_angle_unit(self, unit: str):
        """Make SIN, COS, and TAN take angles in `unit` (DEGREES or RADIANS)."""
        self._commit_pending_edit()
        self.model.set_angle_unit(unit)

    def _toggle_angle_unit(self):
        self.set_angle_unit(RADIANS if self.model.angle_unit == DEGREES else DEGREES)

    def _show_angle_unit(self, *_args):
        unit = self.model.angle_unit
        other = RADIANS if unit == DEGREES else DEGREES
        self.angle_actions[unit].setChecked(True)
        self.angle_button_action.setIconText("DEG" if unit == DEGREES else "RAD")
        self.angle_button_action.setToolTip(f"SIN, COS, and TAN take angles in {unit}. "
                                            f"Click to use {other}.")

    def _toggle_style(self, name: str, attribute: str):
        """Like other spreadsheets: if the current cell already has the style,
        remove it from the selected cells; otherwise give it to them."""
        self._commit_pending_edit()
        current = self.view.currentIndex()
        turn_on = not getattr(self.model.cell_style(current.row(), current.column()), attribute)
        styles = {
            key: dataclasses.replace(self.model.cell_style(*key), **{attribute: turn_on})
            for key in self._selected_cells()
        }
        self.model.set_styles(styles, name)
        self._show_current_style()

    def _show_current_style(self, *_args):
        current = self.view.currentIndex()
        style = self.model.cell_style(current.row(), current.column()) if current.isValid() else PLAIN
        self.format_actions["Bold"].setChecked(style.bold)
        self.format_actions["Italic"].setChecked(style.italic)

    def _selected_cells(self) -> list[tuple[int, int]]:
        indexes = self.view.selectedIndexes() or [self.view.currentIndex()]
        return [(i.row(), i.column()) for i in indexes if i.isValid()]

    def _set_number_format(self, name: str, fmt: NumberFormat):
        self._commit_pending_edit()
        self.model.set_formats({key: fmt for key in self._selected_cells()}, f"{name} Format")

    def _change_decimals(self, name: str, delta: int):
        """Show one more or one fewer decimal place in each selected number,
        starting from how it's shown now."""
        self._commit_pending_edit()
        formats = {}
        for row, col in self._selected_cells():
            value = self.model.value(row, col)
            if not isinstance(value, float):
                continue
            shown = self.model.number_format(row, col)
            if shown is None or shown.kind == "general":
                text = format_number(value)
                decimals = len(text.split(".")[1]) if "." in text and "e" not in text else 0
                shown = NumberFormat("number", decimals, thousands=False)
            decimals = min(max(shown.decimals + delta, 0), MAX_DECIMALS)
            formats[(row, col)] = dataclasses.replace(shown, decimals=decimals)
        self.model.set_formats(formats, name)

    def _build_toolbar(self):
        toolbar = self.addToolBar("Tools")
        self.toolbar = toolbar
        toolbar.setMovable(False)
        self.autosum_action = QAction(self)
        self.autosum_action.setCheckable(True)  # stays pressed while waiting for a click
        # The system UI font misplaces the marks in x̄ and x̃; Helvetica Neue doesn't.
        symbol_font = QFont()
        symbol_font.setFamilies(["Helvetica Neue", *symbol_font.families()])
        button_font = QFont(symbol_font)
        button_font.setPointSize(18)
        self.autosum_action.setFont(button_font)
        self.autosum_action.triggered.connect(self._autosum)

        # The arrow beside the button picks which function it applies.
        menu = QMenu(self)
        menu.setFont(symbol_font)
        group = QActionGroup(self)
        self.aggregate_actions = {}
        for aggregate in AGGREGATES:
            action = menu.addAction(f"{aggregate.symbol}   {aggregate.label}")
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, a=aggregate: self._choose_aggregate(a))
            self.aggregate_actions[aggregate.function] = action

        self.autosum_button = QToolButton()
        self.autosum_button.setDefaultAction(self.autosum_action)
        self.autosum_button.setMenu(menu)
        self.autosum_button.setPopupMode(QToolButton.MenuButtonPopup)
        toolbar.addWidget(self.autosum_button)
        self._show_aggregate()

        self.autosum.pending_changed.connect(self.autosum_action.setChecked)
        self.autosum.message.connect(self._show_status)

        self._build_fill_button(toolbar)
        self._build_chart_button(toolbar)
        self._add_currency_button(toolbar)
        self._add_angle_button(toolbar)
        self.statusBar()  # create it now so the window doesn't resize on the first message

    def _add_currency_button(self, toolbar):
        """A toolbar button for the Format menu's Currency action; the button
        shows the action's icon text."""
        toolbar.addSeparator()
        action = self.format_actions["Currency"]
        action.setIconText("$")
        action.setToolTip("Currency format ($1,234.50)")
        toolbar.addAction(action)
        button = toolbar.widgetForAction(action)
        font = button.font()
        font.setPointSize(15)  # closer to the Σ button; the menu item keeps normal text
        button.setFont(font)
        self._add_style_buttons(toolbar)

    def _add_style_buttons(self, toolbar):
        """B and I toolbar buttons for the Format menu's Bold and Italic, drawn
        in bold and italic; they're pressed when the current cell has the style."""
        for name, label, tip in (("Bold", "B", "Bold (⌘B)"), ("Italic", "I", "Italic (⌘I)")):
            action = self.format_actions[name]
            action.setIconText(label)
            action.setToolTip(tip)
            toolbar.addAction(action)
            button = toolbar.widgetForAction(action)
            font = button.font()
            font.setPointSize(15)
            font.setBold(name == "Bold")
            font.setItalic(name == "Italic")
            button.setFont(font)

    def _add_angle_button(self, toolbar):
        """A toolbar button showing the angle unit, DEG or RAD, that switches it."""
        toolbar.addSeparator()
        self.angle_button_action = QAction(self)
        self.angle_button_action.triggered.connect(lambda _checked=False: self._toggle_angle_unit())
        toolbar.addAction(self.angle_button_action)
        self._show_angle_unit()

    def _build_fill_button(self, toolbar):
        self.fill_action = QAction(self)
        self.fill_action.triggered.connect(lambda _checked=False: self._fill())

        # The arrow beside the button picks the fill mode.
        menu = QMenu(self)
        group = QActionGroup(self)
        self.fill_actions = {}
        for mode in FILL_MODES:
            action = menu.addAction(mode.label)
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, m=mode: self._fill(m))
            self.fill_actions[mode.key] = action
        # The same actions also make up Edit > Fill.
        self.edit_menu.addSeparator()
        fill_menu = self.edit_menu.addMenu("Fill")
        self.fill_menu = fill_menu
        for action in self.fill_actions.values():
            fill_menu.addAction(action)

        self.fill_button = QToolButton()
        self.fill_button.setDefaultAction(self.fill_action)
        self.fill_button.setMenu(menu)
        self.fill_button.setPopupMode(QToolButton.MenuButtonPopup)
        toolbar.addWidget(self.fill_button)
        self.fill.message.connect(self._show_status)
        self._show_fill_mode()

    def _fill(self, mode: FillMode | None = None):
        """Fill the selection; a mode picked from the menu becomes the button's."""
        self._commit_pending_edit()
        self.autosum.cancel()
        self.view.setFocus()
        self.fill.run(mode)
        self._show_fill_mode()

    def _show_fill_mode(self):
        mode = self.fill.mode
        self.fill_action.setText(f"Fill: {mode.label}")
        self.fill_action.setToolTip(
            f"Fill the selected cells ({mode.label.lower()}). Values already in the first "
            "cells are used when they show what to do; otherwise a dialog asks. "
            "The arrow chooses another kind of fill."
        )
        self.fill_actions[mode.key].setChecked(True)

    def _choose_aggregate(self, aggregate: Aggregate):
        """A function picked from the menu becomes the button's. It then switches
        the function of the selected cells if the current cell has one, or
        else runs right away."""
        self.autosum.set_aggregate(aggregate)
        self._show_aggregate()
        if self.autosum.pending:
            return
        self._commit_pending_edit()
        if not self.autosum.switch_selected_cells():
            self._autosum()

    def _show_aggregate(self):
        aggregate = self.autosum.aggregate
        self.autosum_action.setText(aggregate.symbol)
        self.autosum_action.setToolTip(
            f"{aggregate.label}: of the selected numbers, into the cell you click next; "
            "or of the numbers above or left of the current cell. "
            "The arrow chooses another function."
        )
        self.aggregate_actions[aggregate.function].setChecked(True)

    def _autosum(self):
        self._commit_pending_edit()
        self.view.setFocus()  # so Escape reaches the grid to cancel
        self.autosum.trigger()
        self.autosum_action.setChecked(self.autosum.pending)

    def _show_status(self, text: str):
        if text:
            self.statusBar().showMessage(text)
        else:
            self.statusBar().clearMessage()

    def _on_clean_changed(self, clean: bool):
        self.setWindowModified(not clean)

    def _on_undo_text(self, text: str):
        self.undo_action.setText(f"Undo {text}".strip())

    def _on_redo_text(self, text: str):
        self.redo_action.setText(f"Redo {text}".strip())

    def insert_cells(self) -> bool:
        """Ask which way to shift, then insert blank cells in place of the selection."""
        self._commit_pending_edit()
        top, left, bottom, right = self.view.selection_bounds()
        problems = {}  # shifts that can't work here, disabled in the dialog
        for key in SHIFT_LABELS:
            problem = self.model.insert_problem(top, left, bottom, right, key)
            if problem:
                problems[key] = problem
        shift = self._ask_insert_shift(problems)
        if shift is None:
            return False
        self.insert_shift = shift
        problem = self.model.insert_cells(top, left, bottom, right, shift)
        if problem:
            self._show_error("Couldn't insert the cells.", problem)
            return False
        self.view.select_range(top, left, bottom, right)
        cells = (bottom - top + 1) * (right - left + 1)
        self._show_status(f"Inserted {cells} blank cell{'s' if cells != 1 else ''}; "
                          f"{SHIFT_LABELS[shift].lower()}.")
        return True

    def _ask_insert_shift(self, problems: dict[str, str]) -> str | None:
        return ask_shift(InsertCellsDialog, self, self.insert_shift, problems)

    def delete_cells(self) -> bool:
        """Ask which way to shift, then delete the selected cells and close the gap."""
        self._commit_pending_edit()
        top, left, bottom, right = self.view.selection_bounds()
        problems = {}  # shifts that can't work here, disabled in the dialog
        for key in SHIFT_LABELS:
            problem = self.model.delete_problem(top, left, bottom, right, key)
            if problem:
                problems[key] = problem
        if len(problems) == len(SHIFT_LABELS):
            self._show_error("Couldn't delete the cells.",
                             "The selection covers the whole sheet, so there are no cells to fill the gap. "
                             "To empty the cells, press Delete.")
            return False
        shift = self._ask_delete_shift(problems)
        if shift is None:
            return False
        self.delete_shift = shift
        problem = self.model.delete_cells(top, left, bottom, right, shift)
        if problem:
            self._show_error("Couldn't delete the cells.", problem)
            return False
        self.view.select_range(top, left, bottom, right)
        cells = (bottom - top + 1) * (right - left + 1)
        self._show_status(f"Deleted {cells} cell{'s' if cells != 1 else ''}; "
                          f"{SHIFT_LABELS[shift].lower()}.")
        return True

    def _ask_delete_shift(self, problems: dict[str, str]) -> str | None:
        return ask_shift(DeleteCellsDialog, self, self.delete_shift, problems)

    def _history_action(self, method: str):
        # While text is being edited (cell editor or edit bar), undo the typing.
        # Keyboard shortcuts reach the line edit directly; this covers the menu.
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            getattr(focus, method)()
        else:
            getattr(self.model.undo_stack, method)()

    def _show_changed_cells(self, cells):
        """After an undo or redo, select the cells it changed."""
        rows = [row for row, _ in cells]
        cols = [col for _, col in cells]
        self.view.select_range(min(rows), min(cols), max(rows), max(cols))

    def _clipboard_action(self, method: str):
        # While text is being edited (cell editor or edit bar), act on the text.
        # Keyboard shortcuts reach the line edit directly; this covers the menu.
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            getattr(focus, method)()
        else:
            getattr(self.clipboard, method)()

    # --- Files ---

    def new_file(self) -> None:
        if self.maybe_save():
            self._load(self._empty_sheet(), None)

    def open_file(self) -> None:
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Sheet", self._dialog_dir(), FILE_FILTER)
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> bool:
        try:
            sheet = load_sheet(path)
        except SheetFileError as e:
            self._show_error("Couldn't open the sheet.", str(e))
            return False
        self._load(sheet, path)
        return True

    def open_or_create(self, path: str) -> bool:
        """Open a file, or if there's nothing there yet, start an empty sheet
        that Save will write to that path."""
        path = os.path.abspath(path)
        if os.path.exists(path) or not os.path.isdir(os.path.dirname(path)):
            return self.open_path(path)  # reports a bad folder as an error
        self._load(self._empty_sheet(), path)
        return True

    def _empty_sheet(self) -> SheetData:
        """A new sheet, taking angles in the same unit as the current one."""
        return SheetData(DEFAULT_ROWS, DEFAULT_COLS, angle_unit=self.model.angle_unit)

    def save(self) -> bool:
        if self.file_path is None:
            return self.save_as()
        return self.save_to(self.file_path)

    def save_as(self) -> bool:
        suggested = self.file_path or os.path.join(self._dialog_dir(), "Untitled" + EXTENSION)
        path, _ = QFileDialog.getSaveFileName(self, "Save Sheet", suggested, FILE_FILTER)
        if not path:
            return False
        if not os.path.splitext(path)[1]:
            path += EXTENSION
        return self.save_to(path)

    def save_to(self, path: str) -> bool:
        self._commit_pending_edit()
        try:
            save_sheet(path, self.model.sheet_data())
        except SheetFileError as e:
            self._show_error("Couldn't save the sheet.", str(e))
            return False
        self._set_file_path(path)
        self.model.undo_stack.setClean()
        self.setWindowModified(False)
        return True

    def import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import CSV", self._dialog_dir(), CSV_FILTER)
        if path:
            self.import_csv_from(path)

    def import_csv_from(self, path: str) -> bool:
        """Put a CSV file's fields into the sheet at the selected cell, as one
        undoable step, growing the sheet if they don't fit."""
        self._commit_pending_edit()
        try:
            rows = read_csv(path)
        except SheetFileError as e:
            self._show_error("Couldn't import the CSV file.", str(e))
            return False
        name = os.path.basename(path)
        if not rows:
            self._show_status(f"{name} is empty, so nothing was imported.")
            return False
        top, left, _, _ = self.view.selection_bounds()
        height, width = len(rows), max(len(row) for row in rows)
        self.model.ensure_size(top + height, left + width)
        writes = {
            (top + r, left + c): row[c] if c < len(row) else ""
            for r, row in enumerate(rows)
            for c in range(width)
        }
        self.model.set_cells(writes, "Import CSV")
        self.view.select_range(top, left, top + height - 1, left + width - 1)
        self._show_status(
            f"Imported {height} rows × {width} columns from {name} at {cell_name(top, left)}.")
        return True

    def export_csv(self) -> None:
        name = os.path.splitext(os.path.basename(self.file_path or "Untitled"))[0]
        suggested = os.path.join(self._dialog_dir(), name + ".csv")
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", suggested, CSV_FILTER)
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".csv"
        self.export_csv_to(path)

    def export_csv_to(self, path: str) -> bool:
        """Write what the cells show (formula results, not formulas), from A1
        to the last filled row and column."""
        self._commit_pending_edit()
        rows = self.model.displayed_rows()
        if not rows:
            self._show_status("The sheet is empty, so there's nothing to export.")
            return False
        try:
            write_csv(path, rows)
        except SheetFileError as e:
            self._show_error("Couldn't export the CSV file.", str(e))
            return False
        self._show_status(
            f"Exported {len(rows)} rows × {len(rows[0])} columns to {os.path.basename(path)}.")
        return True

    def maybe_save(self) -> bool:
        """Offer to save unsaved changes. Returns False if the user cancels."""
        self._commit_pending_edit()
        if not self.isWindowModified():
            return True
        answer = self._ask_to_save()
        if answer == QMessageBox.Save:
            return self.save()
        return answer == QMessageBox.Discard

    def closeEvent(self, event):
        if self.maybe_save():
            event.accept()
        else:
            event.ignore()

    def _load(self, sheet: SheetData, path: str | None) -> None:
        self.close_charts()  # they show the old sheet's cells
        self.clipboard.cancel()
        self.autosum.cancel()
        self.model.load_sheet_data(sheet)
        self.view.setCurrentIndex(self.model.index(0, 0))
        self._refresh_bar(self.view.currentIndex())
        self._set_file_path(path)
        self.setWindowModified(False)

    def _commit_pending_edit(self) -> None:
        """Store text still being typed, so saving includes it."""
        if self._grid_refs is not None:
            editor = self._grid_refs.edit
            self.view.cell_delegate.commitData.emit(editor)
            self.view.cell_delegate.closeEditor.emit(editor, QStyledItemDelegate.NoHint)
        elif self.edit_bar.hasFocus():
            self._store_edit_bar()

    def _set_file_path(self, path: str | None) -> None:
        self.file_path = path
        self.setWindowFilePath(path or "")
        name = os.path.basename(path) if path else "Untitled"
        self.setWindowTitle(f"{name}[*] — Py-Spread")

    def _dialog_dir(self) -> str:
        if self.file_path:
            return os.path.dirname(self.file_path)
        return QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)

    def _ask_to_save(self):
        name = os.path.basename(self.file_path) if self.file_path else "Untitled"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setText(f'Do you want to save the changes you made to "{name}"?')
        box.setInformativeText("Your changes will be lost if you don't save them.")
        box.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Save)
        return box.exec()

    def _show_error(self, text: str, detail: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Critical)
        box.setText(text)
        box.setInformativeText(detail)
        box.exec()

    # --- Formula editing ---

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

    def _show_current_name(self):
        if not self.edit_bar.hasFocus():  # don't clobber text being typed in the bar
            self._refresh_bar(self.view.currentIndex())

    def _refresh_bar(self, index):
        self._bar_refs.reset()
        if not index.isValid():
            self.cell_label.setText("")
            self.edit_bar.setText("")
            return
        name = self.model.name_of(index.row(), index.column())
        reference = cell_name(index.row(), index.column())
        self.cell_label.setText(f"{reference} ({name})" if name else reference)
        self.edit_bar.setText(self.model.get_cell(index.row(), index.column()))

    def _store_edit_bar(self):
        index = self.view.currentIndex()
        if index.isValid():
            self.model.set_cell(index.row(), index.column(), self.edit_bar.text(), "Typing")

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
