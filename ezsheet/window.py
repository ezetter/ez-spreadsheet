"""Main window: a cell-reference label and edit bar above the grid."""

import dataclasses
import os
import uuid

from PySide6.QtCore import QEvent, QItemSelection, QItemSelectionModel, QPointF, QSize, QStandardPaths, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QUndoCommand,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStyle,
    QStyleOptionComboBox,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import appearance
from .appearance import (
    APPEARANCES,
    ZOOM_LEVELS,
    GridStyle,
    apply_appearance,
    next_zoom,
    saved_appearance,
    scaled_font,
)
from .autosum import AGGREGATES, Aggregate, AutoSumController
from .clipboard import ClipboardController
from .csvfile import read_csv, write_csv
from .fill import FILL_MODES, FillController, FillMode
from .fill_dialogs import FillDialogs
from .functions import ANGLE_UNITS, DEGREES, RADIANS
from .frame_name_dialog import FrameNameDialog
from .kernel import KernelRunner
from .graph_dialog import GraphDialog, graph_labels
from .graphs import (
    ChartFrame,
    change_graph,
    find_frames,
    find_graphs,
    dependent_cells,
    rename_frame,
    update_frame_code,
    used_names,
)
from .load_data import answer, columns_request, data_request, frame_columns, frames, frames_request, sheet_writes
from .load_data_dialog import LoadDataDialog
from .notebook import (
    IMPORTS_CELL,
    GraphChoice,
    GraphError,
    Notebook,
    assigned_names,
    data_block,
    dataframe_code,
    frame_graph_code,
    graph_code,
    graph_columns,
    importing_cell,
    next_frame_name,
)
from .notebook_window import NotebookWindow, kernel_folder
from .recent import add_recent_file, clear_recent_files, menu_labels, recent_files, remove_recent_file
from .names_dialog import NameCellDialog, NameColumnDialog, NamesDialog
from .shift_dialog import SHIFT_LABELS, DeleteCellsDialog, InsertCellsDialog, ask_shift
from .model import DEFAULT_COLS, DEFAULT_ROWS, SheetModel
from .colors import ICON_SIZE as COLOR_ICON_SIZE
from .colors import ColorMenu, fill_color_icon, text_color_icon
from .borders import BORDER_KINDS, MERGE_KINDS, border_icon, border_style_icon, border_styles, covered, merged
from .borders import merge_icon
from .custom_format_dialog import CustomFormatDialog
from .sort_dialog import SortDialog
from .sorting import ARROWS, ASCENDING, DESCENDING, has_header
from .numformat import DATE_KINDS, GENERAL, MAX_DECIMALS, MENU_FORMATS, NumberFormat, format_number, pattern_of
from .textstyle import BORDER_STYLES, MAX_SIZE, MIN_SIZE, PLAIN, SIZES, Border
from .references import cell_name, column_name
from .storage import EXTENSION, SheetData, SheetFileError, load_sheet, save_sheet

FILE_FILTER = f"EZ Sheet Sheets (*{EXTENSION})"
CUSTOM_FORMAT = "Custom number format…"  # the Number menu's last item
DEFAULT_FONT = "Default"  # the font box's first item: the sheet's own font
TOOLS = (  # what the toolbar's right-click menu shows and hides, in the toolbar's order
    ("autosum", "Σ AutoSum"), ("fill", "Fill"), ("notebook", "Notebook"), ("currency", "Currency ($)"),
    ("percent", "Percent (%)"), ("fewer", "Decrease Decimal Places (.0)"),
    ("more", "Increase Decimal Places (.00)"), ("formats", "More Formats (123)"), ("font", "Font"),
    ("size", "Font Size"), ("bold", "Bold"), ("italic", "Italic"), ("strikethrough", "Strikethrough"),
    ("text color", "Text Color"),
    ("fill color", "Fill Color"), ("borders", "Borders"), ("merge", "Merge Cells"),
    ("angle", "Angle Unit (DEG or RAD)"),
)
HIDDEN_TOOLS_KEY = "toolbar/hidden"  # the tools hidden, a preference
DEFAULT_HIDDEN_TOOLS = ("fill", "angle")  # hidden until shown (Edit > Fill and Formulas > Angles have them)
COLUMN_WIDTH = 100  # default sizes at 100% zoom
ROW_HEIGHT = 24
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
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        editor.setFont(styled.font)  # the cell's own font and size, as it's shown
        self.editor_created.emit(editor)
        return editor

    def initStyleOption(self, option, index):
        """The cell's font size, if it has its own, zoomed as the grid is."""
        super().initStyleOption(option, index)
        size = index.model().cell_style(index.row(), index.column()).size
        if size is not None:
            font = QFont(option.font)
            font.setPointSizeF(size * self.parent().zoom / 100)
            option.font = font

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


_ARROWS = {Qt.Key_Up: (-1, 0), Qt.Key_Down: (1, 0), Qt.Key_Left: (0, -1), Qt.Key_Right: (0, 1)}


class SheetView(QTableView):
    """Table view with spreadsheet-style keyboard and mouse behavior."""

    editor_closed = Signal()
    escape_pressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.zoom = 100  # percent: cells' own font sizes are zoomed with it
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
            # Cmd+arrow and Shift+Cmd+arrow (Cmd is Control to Qt on macOS, and arrows count as
            # keypad keys there)
            modifiers = event.modifiers() & ~Qt.KeypadModifier
            if key in _ARROWS and modifiers == Qt.ShiftModifier | Qt.ControlModifier:
                self.extend_to_data_edge(*_ARROWS[key])
                return
            if key in _ARROWS and modifiers == Qt.ControlModifier:
                self.move_to_data_edge(*_ARROWS[key])
                return
        super().keyPressEvent(event)

    def move_to_data_edge(self, d_row: int, d_col: int) -> None:
        """Cmd+arrow: move the current cell to the edge of the data that way:
        through the cells with something in them to the last before an empty
        cell, or, if the next cell is empty, on to the next cell with
        something in it, or else to the sheet's edge (as Shift+Cmd+arrow
        extends a selection)."""
        current = self.currentIndex()
        if not current.isValid():
            return
        vertical, step = d_row != 0, d_row or d_col
        line, start = (current.column(), current.row()) if vertical else (current.row(), current.column())
        end = self._data_edge(line, start, step, vertical)
        target = self.model().index(end, line) if vertical else self.model().index(line, end)
        # (Not setCurrentIndex: with Cmd held, Qt would leave the selection as it was.)
        self.selectionModel().setCurrentIndex(target, QItemSelectionModel.ClearAndSelect)
        self.scrollTo(target)

    def extend_to_data_edge(self, d_row: int, d_col: int) -> None:
        """Shift+Cmd+arrow: extend the selection in that direction, all its
        columns (up or down) or rows (left or right) together, as far as the
        current cell's column (or row) goes from the selection's edge: through
        the cells with something in them to the last before an empty cell, or
        to the sheet's edge. Where the next cell is empty, it goes on through
        the empty ones to the next cell with something in it (or the edge), so
        pressing again keeps going. The current cell stays where it is."""
        model = self.model()
        top, left, bottom, right = self.selection_bounds()
        current = self.currentIndex()
        vertical, step = d_row != 0, d_row or d_col
        if vertical:  # the current cell's column decides, if it's in the selection
            line = current.column() if current.isValid() and left <= current.column() <= right else left
            start = top if step < 0 else bottom
        else:
            line = current.row() if current.isValid() and top <= current.row() <= bottom else top
            start = left if step < 0 else right
        end = self._data_edge(line, start, step, vertical)
        if vertical:
            top, bottom = min(top, end), max(bottom, end)
            far = model.index(end, line)
        else:
            left, right = min(left, end), max(right, end)
            far = model.index(line, end)
        self.selectionModel().select(QItemSelection(model.index(top, left), model.index(bottom, right)),
                                     QItemSelectionModel.Select)
        self.scrollTo(far)

    def _data_edge(self, line: int, start: int, step: int, vertical: bool) -> int:
        """Where extending from `start` along a column (vertical) or row ends."""
        model = self.model()
        last = (model.rowCount() if vertical else model.columnCount()) - 1

        def filled(at: int) -> bool:
            return bool(model.get_cell(at, line) if vertical else model.get_cell(line, at))

        at = start + step
        if not 0 <= at <= last:
            return start  # already at the edge
        if filled(at):  # through the cells with something in them
            while 0 <= at + step <= last and filled(at + step):
                at += step
            return at
        while not filled(at) and 0 <= at + step <= last:  # through the empty ones, to the next filled
            at += step
        return at

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

    def whole_lines(self) -> tuple[str, list[int]] | None:
        """("columns", their indexes) if the selection is whole columns (all
        of their rows), ("rows", ...) if it's whole rows, else None. Selecting
        the whole sheet is neither."""
        ranges = list(self.selectionModel().selection())
        if not ranges:
            return None
        rows, cols = self.model().rowCount(), self.model().columnCount()
        columns = all(r.top() == 0 and r.bottom() == rows - 1 for r in ranges)
        whole_rows = all(r.left() == 0 and r.right() == cols - 1 for r in ranges)
        if columns == whole_rows:
            return None
        if columns:
            return "columns", sorted({c for r in ranges for c in range(r.left(), r.right() + 1)})
        return "rows", sorted({row for r in ranges for row in range(r.top(), r.bottom() + 1)})

    def select_lines(self, kind: str, indexes: list[int]) -> None:
        """Select whole "rows" or "columns", making the first one's first cell current."""
        model = self.model()
        selection = QItemSelection()
        for start, count in runs(indexes):
            if kind == "columns":
                selection.select(model.index(0, start), model.index(model.rowCount() - 1, start + count - 1))
            else:
                selection.select(model.index(start, 0), model.index(start + count - 1, model.columnCount() - 1))
        first = model.index(0, indexes[0]) if kind == "columns" else model.index(indexes[0], 0)
        self.selectionModel().setCurrentIndex(first, QItemSelectionModel.NoUpdate)
        self.selectionModel().select(selection, QItemSelectionModel.ClearAndSelect)
        self.scrollTo(first)

    def select_range(self, top: int, left: int, bottom: int, right: int) -> None:
        """Select a block of cells, make its top-left current, and scroll to it."""
        model = self.model()
        corner = model.index(top, left)
        selection = self.selectionModel()
        selection.setCurrentIndex(corner, QItemSelectionModel.NoUpdate)
        selection.select(QItemSelection(corner, model.index(bottom, right)), QItemSelectionModel.ClearAndSelect)
        self.scrollTo(corner)

    def move_current(self, d_row: int, d_col: int) -> None:
        """Move the current cell; a merged block is one cell, its top-left one."""
        current = self.currentIndex()
        row, col = current.row(), current.column()
        block = self.model().merge_at(row, col)
        if block is not None:  # from its far side
            row = block[2] if d_row > 0 else block[0] if d_row < 0 else row
            col = block[3] if d_col > 0 else block[1] if d_col < 0 else col
        row = min(max(row + d_row, 0), self.model().rowCount() - 1)
        col = min(max(col + d_col, 0), self.model().columnCount() - 1)
        block = self.model().merge_at(row, col)
        if block is not None:
            row, col = block[:2]
        self.setCurrentIndex(self.model().index(row, col))

    def show_merges(self) -> None:
        """Show the model's merged blocks as one cell each."""
        self.clearSpans()
        for top, left, bottom, right in self.model().merges():
            self.setSpan(top, left, bottom - top + 1, right - left + 1)

    def paintEvent(self, event):
        super().paintEvent(event)
        bordered = self.model().bordered_cells()
        if bordered:
            painter = QPainter(self.viewport())
            self._paint_borders(painter, bordered)
            painter.end()

    def _paint_borders(self, painter: QPainter, bordered: dict) -> None:
        """Cells' borders, on the grid lines around them (over the grid),
        but not between the cells of a merged block."""
        viewport = self.viewport().rect()
        first_row, first_col = max(self.rowAt(0), 0), max(self.columnAt(0), 0)
        last_row = self.rowAt(viewport.height() - 1)
        last_col = self.columnAt(viewport.width() - 1)
        last_row = self.model().rowCount() - 1 if last_row < 0 else last_row
        last_col = self.model().columnCount() - 1 if last_col < 0 else last_col
        model = self.model()
        for (row, col), borders in bordered.items():
            if not (first_row - 1 <= row <= last_row + 1 and first_col - 1 <= col <= last_col + 1):
                continue
            x0, y0 = self.columnViewportPosition(col), self.rowViewportPosition(row)
            x1, y1 = x0 + self.columnWidth(col) - 1, y0 + self.rowHeight(row) - 1
            block = model.merge_at(row, col)
            for side, border in borders.items():
                if block is not None and _inside_block(block, row, col, side):
                    continue
                line = {"top": (x0 - 1, y0 - 1, x1, y0 - 1), "bottom": (x0 - 1, y1, x1, y1),
                        "left": (x0 - 1, y0 - 1, x0 - 1, y1), "right": (x1, y0 - 1, x1, y1)}[side]
                _draw_border(painter, border, *line, side in ("top", "bottom"), self.zoom)


_BORDER_WIDTHS = {"thin": 1, "medium": 2, "thick": 3, "dashed": 1, "dotted": 1, "double": 1}


def _inside_block(block, row: int, col: int, side: str) -> bool:
    """Whether a cell's side is between two cells of its merged block."""
    top, left, bottom, right = block
    return {"top": row > top, "bottom": row < bottom, "left": col > left, "right": col < right}[side]


def _draw_border(painter: QPainter, border, x0: int, y0: int, x1: int, y1: int, across: bool,
                 zoom: int) -> None:
    """One side's line, in its style and color, zoomed as the grid is."""
    width = max(1, round(_BORDER_WIDTHS[border.style] * zoom / 100))
    pen = QPen(QColor(border.color), width)
    pen.setCapStyle(Qt.FlatCap)
    pen.setStyle({"dashed": Qt.DashLine, "dotted": Qt.DotLine}.get(border.style, Qt.SolidLine))
    painter.setPen(pen)
    if border.style == "double":  # two thin lines, one each side of the grid line
        gap = max(1, round(zoom / 100))
        dx, dy = (0, gap) if across else (gap, 0)
        painter.drawLine(x0 - dx, y0 - dy, x1 - dx, y1 - dy)
        painter.drawLine(x0 + dx, y0 + dy, x1 + dx, y1 + dy)
    else:
        painter.drawLine(x0, y0, x1, y1)


def runs(indexes: list[int]) -> list[tuple[int, int]]:
    """Sorted row or column indexes as (first, count) runs: [1, 2, 5] is [(1, 2), (5, 1)]."""
    found = []
    for index in sorted(set(indexes)):
        if found and found[-1][0] + found[-1][1] == index:
            found[-1] = (found[-1][0], found[-1][1] + 1)
        else:
            found.append((index, 1))
    return found


def _section_ratios(header) -> list[float]:
    """Each section's size as a multiple of the default, so it survives zooming."""
    default = header.defaultSectionSize()
    return [header.sectionSize(i) / default for i in range(header.count())]


class _SectionSizesCommand(QUndoCommand):
    """Column widths or row heights moving with inserted columns or rows, as
    part of the insert's undo step."""

    def __init__(self, header, before: list[float], after: list[float]):
        super().__init__()
        self.header, self.before, self.after = header, before, after

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)

    def _apply(self, ratios: list[float]) -> None:
        header, default = self.header, self.header.defaultSectionSize()
        for i in range(header.count()):
            size = max(1, round((ratios[i] if i < len(ratios) else 1.0) * default))
            if header.sectionSize(i) != size:
                header.resizeSection(i, size)


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
        # The sheet's notebook, and the Python kernel its cells run in.
        self.notebook = Notebook(self)
        self.kernel = KernelRunner(self)
        self.notebook_window = None  # made when first shown
        self._notebook_dirty = False  # notebook changes since the last save
        self.file_path: str | None = None
        self._set_file_path(None)

        self.model = SheetModel(parent=self)
        self.view = SheetView()
        self.view.setModel(self.model)
        # The sheet's own font: what a cell without one of its own shows (at 100% zoom).
        self.default_font_family = self.view.font().family()
        self.default_font_size = self.view.font().pointSizeF()
        self._grown_rows = {}  # rows grown to fit their fonts: row -> how many times the default height

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
        self._build_data_menu()
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
        self.model.dataChanged.connect(self._fit_rows_to_fonts)
        self.model.modelReset.connect(self._rows_moved)
        self.model.rowsInserted.connect(self._rows_moved)
        self.model.rowsRemoved.connect(self._rows_moved)
        self.model.merges_changed.connect(self.view.show_merges)
        self.view.cell_delegate.editor_created.connect(self._on_editor_created)
        self.view.editor_closed.connect(self._on_editor_closed)
        self.model.dataChanged.connect(self._on_data_changed)
        self.model.names_changed.connect(self._show_current_name)
        self.model.contents_changed.connect(lambda: self.setWindowModified(True))
        self.notebook.changed.connect(self._on_notebook_changed)
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
            if name == "Open…":
                self.recent_menu = menu.addMenu("Open Recent")
                self.recent_menu.setToolTipsVisible(True)  # each sheet's full path
                self._update_recent_menu()
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
        menu.addAction(self.name_column_action)
        menu.addSeparator()
        self._add_notebook_menu(menu)
        menu.addAction(self.ask_claude_action)
        self.context_menu = menu
        # Qt selects a right-clicked cell outside the selection, and keeps the
        # selection when it's inside it, as other spreadsheets do.
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_context_menu)
        header = self.view.horizontalHeader()
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_menu)
        row_header = self.view.verticalHeader()
        row_header.setContextMenuPolicy(Qt.CustomContextMenu)
        row_header.customContextMenuRequested.connect(self._show_row_header_menu)
        self.view.selectionModel().selectionChanged.connect(self._update_line_actions)

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
        self.view_menu = menu
        self.zoom = 100  # percent
        self._zoom_base_fonts = None  # each zoomable widget's font at 100%, saved on first zoom
        self.zoom_actions = {}
        # These zoom the notebook instead when it's in front, as the Mac's
        # menu bar, shortcuts included, stays this window's.
        for name, shortcuts, slot in (
            # ⌘= as well as ⌘+, so Shift isn't needed for the + key
            ("Zoom In", [QKeySequence(QKeySequence.ZoomIn), QKeySequence("Ctrl+=")],
             lambda: self._zoom_target().zoom_in()),
            ("Zoom Out", [QKeySequence(QKeySequence.ZoomOut)], lambda: self._zoom_target().zoom_out()),
            ("Actual Size", [QKeySequence("Ctrl+0")], lambda: self._zoom_target().set_zoom(100)),
        ):
            action = QAction(name, self)
            action.setShortcuts(shortcuts)
            action.triggered.connect(lambda _checked=False, s=slot: s())
            menu.addAction(action)
            self.zoom_actions[name] = action
        QGuiApplication.instance().focusWindowChanged.connect(self._update_zoom_actions)

        self.show_notebook_action = QAction("Notebook", self)
        self.show_notebook_action.setToolTip("Open the sheet's notebook")
        self.show_notebook_action.triggered.connect(lambda _checked=False: self.show_notebook())
        menu.addSeparator()
        menu.addAction(self.show_notebook_action)

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
        self.set_zoom(next_zoom(self.zoom, 1))

    def zoom_out(self):
        self.set_zoom(next_zoom(self.zoom, -1))

    def set_zoom(self, percent: int) -> None:
        """Scale the grid (text, rows, columns, headers), the cell bar, the
        toolbar, and the status bar to `percent` of their normal size."""
        if self._zoom_base_fonts is None:
            self._zoom_base_fonts = {widget: QFont(widget.font()) for widget in self._zoomable_widgets()}
        old, self.zoom = self.zoom, percent
        self.view.zoom = percent
        for widget, base in self._zoom_base_fonts.items():
            widget.setFont(scaled_font(base, percent))
        _rescale_header(self.view.horizontalHeader(), COLUMN_WIDTH, old, percent)
        _rescale_header(self.view.verticalHeader(), ROW_HEIGHT, old, percent)
        self._fit_rows_to_fonts()
        self._update_zoom_actions()
        self.statusBar().showMessage(f"Zoom {percent}%", 2000)

    def _zoom_target(self):
        """What View > Zoom applies to: the notebook when it's the active
        window, otherwise the sheet."""
        notebook_window = self.notebook_window
        if notebook_window is not None and notebook_window.isActiveWindow():
            return notebook_window
        return self

    def _update_zoom_actions(self, *_args) -> None:
        """Zoom In and Zoom Out are unavailable at the limits of what they'd zoom."""
        zoom = self._zoom_target().zoom
        self.zoom_actions["Zoom In"].setEnabled(zoom != ZOOM_LEVELS[-1])
        self.zoom_actions["Zoom Out"].setEnabled(zoom != ZOOM_LEVELS[0])

    def _zoomable_widgets(self) -> list:
        """Widgets whose font sets their size. (The menu bar is the Mac's own,
        so it isn't zoomed.)"""
        toolbar_widgets = [self.toolbar.widgetForAction(action) for action in self.toolbar.actions()
                           if not action.isSeparator()]
        return [self.view, self.view.horizontalHeader(), self.view.verticalHeader(),
                self.cell_label, self.edit_bar, self.statusBar(), *toolbar_widgets]

    def _build_insert_menu(self):
        menu = self.menuBar().addMenu("Insert")
        # Notebook: open it as it is, or add the selected cells as a DataFrame,
        # or as a DataFrame and a chart.
        self.open_notebook_action = QAction("Open", self)
        self.open_notebook_action.setToolTip("Open the sheet's notebook without adding anything to it")
        self.open_notebook_action.triggered.connect(lambda _checked=False: self.show_notebook())
        self.dataframe_action = QAction("DataFrame", self)
        self.dataframe_action.setToolTip(
            "Put the selected cells in a pandas DataFrame in the sheet's notebook, and run it")
        self.dataframe_action.triggered.connect(lambda _checked=False: self.send_to_notebook())
        self.graph_action = QAction("Chart", self)
        self.graph_action.setToolTip(
            "Put the selected cells in a DataFrame in the sheet's notebook and chart it with Seaborn, "
            "choosing the kind of chart and its columns")
        self.graph_action.triggered.connect(lambda _checked=False: self.send_graph_to_notebook())
        self.graph_kind, self.graph_marker = "line", None  # the Chart dialog's last choices
        self.load_data_action = QAction("Load Data to Sheet…", self)
        self.load_data_action.setToolTip("Put one of the notebook's DataFrames in the sheet, at the current cell")
        self.load_data_action.triggered.connect(lambda _checked=False: self.load_data_to_sheet())
        self._evaluations = {}  # request id -> what to do with the notebook's answer
        self._evaluating_with = None  # the kernel whose answers come to _on_evaluated
        self._add_notebook_menu(menu)

    def _add_notebook_menu(self, menu=None) -> QMenu:
        """A Notebook menu (Open, DataFrame, Graph, Load Data to Sheet): a
        submenu of `menu`, or one of its own."""
        submenu = menu.addMenu("Notebook") if menu is not None else QMenu("Notebook", self)
        submenu.addAction(self.open_notebook_action)
        submenu.addSeparator()
        submenu.addAction(self.dataframe_action)
        submenu.addAction(self.graph_action)
        submenu.addSeparator()
        submenu.addAction(self.load_data_action)
        return submenu

    def _build_format_menu(self):
        menu = self.menuBar().addMenu("Format")
        self.format_actions = {}
        # Format > Number, as Google Sheets has it; the toolbar's 123 button shows it too. The current
        # cell's format is checked.
        self.number_menu = menu.addMenu("Number")
        group = QActionGroup(self)
        self.number_formats = {}  # name -> format
        for entry in MENU_FORMATS:
            if entry is None:
                self.number_menu.addSeparator()
                continue
            name, fmt, example = entry
            action = QAction(f"{name}  ({example})" if example else name, self)
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, n=name, f=fmt: self._set_number_format(n, f))
            self.number_menu.addAction(action)
            self.format_actions[name] = action
            self.number_formats[name] = fmt
        self.number_menu.addSeparator()
        action = QAction(CUSTOM_FORMAT, self)
        action.setCheckable(True)
        group.addAction(action)
        action.triggered.connect(lambda _checked=False: self._custom_number_format())
        self.number_menu.addAction(action)
        self.format_actions[CUSTOM_FORMAT] = action
        menu.addSeparator()
        for name, delta in (("Increase Decimals", 1), ("Decrease Decimals", -1)):
            action = QAction(name, self)
            action.triggered.connect(lambda _checked=False, n=name, d=delta: self._change_decimals(n, d))
            menu.addAction(action)
            self.format_actions[name] = action
        menu.addSeparator()
        # Checked when the current cell has the style.
        for name, attribute, shortcut in (("Bold", "bold", QKeySequence.Bold),
                                          ("Italic", "italic", QKeySequence.Italic),
                                          ("Strikethrough", "strikethrough", QKeySequence("Ctrl+Shift+X"))):
            action = QAction(name, self)
            action.setCheckable(True)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda _checked=False, n=name, a=attribute: self._toggle_style(n, a))
            menu.addAction(action)
            self.format_actions[name] = action
        menu.addSeparator()
        for name, shortcut, step in (("Increase Font Size", "Ctrl+Shift+.", 1),
                                     ("Decrease Font Size", "Ctrl+Shift+,", -1)):
            action = QAction(name, self)
            action.setShortcut(QKeySequence(shortcut))  # ⇧⌘. and ⇧⌘, as in Google Sheets
            action.triggered.connect(lambda _checked=False, s=step: self._step_font_size(s))
            menu.addAction(action)
            self.format_actions[name] = action
        action = QAction("Default Font", self)
        action.triggered.connect(lambda _checked=False: self._set_font(None, None, "Default Font"))
        menu.addAction(action)
        self.format_actions["Default Font"] = action
        menu.addSeparator()
        for key, name in (("color", "Text Color…"), ("fill", "Fill Color…")):
            action = QAction(name, self)
            action.triggered.connect(lambda _checked=False, k=key: self._custom_color(k))
            menu.addAction(action)
            self.format_actions[name] = action
        menu.addSeparator()
        self.border_style, self.border_color = "thin", "#000000"  # what the next borders are drawn in
        menu.addMenu(self._borders_menu(in_toolbar=False))
        menu.addMenu(self._merge_menu())

    def _build_data_menu(self):
        """Data: sort the sheet, or the selected range, by the current cell's
        column, A → Z or Z → A, or by several columns (Sort Range…)."""
        menu = self.menuBar().addMenu("Data")
        self.sort_actions = {}
        for key, ascending in (("sheet", ASCENDING), ("sheet", DESCENDING), ("range", ASCENDING),
                               ("range", DESCENDING)):
            if key == "range" and ascending:
                menu.addSeparator()
            action = QAction(self)
            action.triggered.connect(lambda _checked=False, k=key, a=ascending: self._sort_by_current(k, a))
            menu.addAction(action)
            self.sort_actions[(key, ascending)] = action
        action = QAction("Sort Range…", self)
        action.triggered.connect(lambda _checked=False: self.sort_range_dialog())
        menu.addAction(action)
        self.sort_actions["dialog"] = action
        self.view.selectionModel().currentChanged.connect(self._name_sort_actions)
        self.view.selectionModel().selectionChanged.connect(self._name_sort_actions)
        self._name_sort_actions()

    def _name_sort_actions(self, *_args) -> None:
        """The Data menu's sorts name the current cell's column."""
        current = self.view.currentIndex()
        letter = column_name(current.column() if current.isValid() else 0)
        multiple = len(self._selected_cells()) > 1
        for (key, ascending), action in ((k, a) for k, a in self.sort_actions.items() if k != "dialog"):
            what = "Sheet" if key == "sheet" else "Range"
            action.setText(f"Sort {what} by Column {letter} ({ARROWS[ascending]})")
            if key == "range":
                action.setEnabled(multiple)

    def _sort_by_current(self, key: str, ascending: bool) -> None:
        current = self.view.currentIndex()
        col = current.column() if current.isValid() else 0
        if key == "sheet":
            self.sort_sheet(col, ascending)
        else:
            self.sort_range(col, ascending)

    def _header_guess(self, top, left, bottom, right) -> bool:
        return has_header(self.model.value, lambda r, c: self.model.cell_style(r, c).bold, top, left, bottom, right)

    def sort_sheet(self, col: int, ascending: bool) -> bool:
        """Sort all the sheet's rows by a column (keeping a header row on
        top, if there plainly is one: see sorting.has_header)."""
        block = self.model.data_block()
        if block is None:
            self._show_status("There's nothing to sort.")
            return False
        top, left, bottom, right = block
        return self._sort((top, left, bottom, right), [(col, ascending)], self._header_guess(*block), "Sort Sheet")

    def sort_range(self, col: int, ascending: bool) -> bool:
        """Sort the selected cells' rows by a column (the current cell's, if
        it's in the selection), moving only the selected columns."""
        top, left, bottom, right = self._sort_block()
        col = col if left <= col <= right else left
        block = (top, left, bottom, right)
        return self._sort(block, [(col, ascending)], self._header_guess(*block), "Sort Range")

    def sort_range_dialog(self) -> bool:
        """Data > Sort Range…: the selected cells (or the whole sheet's data,
        with no more than one selected), by one or more columns, with or
        without a header row."""
        if len(self._selected_cells()) > 1:
            block = self._sort_block()
        else:
            block = self.model.data_block()
            if block is None:
                self._show_status("There's nothing to sort.")
                return False
        top, left, bottom, right = block
        current = self.view.currentIndex()
        col = current.column() if current.isValid() and left <= current.column() <= right else left
        answer = self._ask_sort(f"{cell_name(top, left)}:{cell_name(bottom, right)}", left, right,
                                lambda c: str(self.model.value(top, c) or ""), self._header_guess(*block), col)
        if answer is None:
            return False
        keys, header = answer
        return self._sort(block, keys, header, "Sort Range")

    def _sort_block(self) -> tuple[int, int, int, int]:
        """The selection, but no lower than the sheet's data (whole columns, say)."""
        self._commit_pending_edit()
        top, left, bottom, right = self.view.selection_bounds()
        data = self.model.data_block()
        if data is not None:
            bottom = max(top, min(bottom, data[2]))
        return top, left, bottom, right

    def _ask_sort(self, where: str, left: int, right: int, labels, header: bool, col: int):
        """The Sort Range dialog: (the sort columns, whether there's a header row), or None if cancelled."""
        dialog = SortDialog(self, where, left, right, labels, header, col)
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.sort_keys(), dialog.has_header()

    def _sort(self, block, keys, header: bool, description: str) -> bool:
        """Sort a block's rows (all but a header row, if it has one), saying how in the status bar."""
        self._commit_pending_edit()
        top, left, bottom, right = block
        if header:
            top += 1
        if top >= bottom:
            self._show_status("There's only one row to sort.")
            return False
        merged_here = [m for m in self.model.merges()
                       if m[0] <= bottom and top <= m[2] and m[1] <= right and left <= m[3]]
        if merged_here:
            m_top, m_left, m_bottom, m_right = merged_here[0]
            self._show_error("Couldn't sort.", f"Sorting can't move merged cells. Unmerge "
                             f"{cell_name(m_top, m_left)}:{cell_name(m_bottom, m_right)} first.")
            return False
        by = ", then ".join(f"column {column_name(col)} ({ARROWS[ascending]})" for col, ascending in keys)
        kept = f", keeping row {top} as the header" if header else ""
        if not self.model.sort_rows(top, left, bottom, right, keys, description):
            self._show_status(f"Rows {top + 1}–{bottom + 1} are sorted by {by} already{kept}.")
            return False
        self._show_status(f"Sorted rows {top + 1}–{bottom + 1} by {by}{kept}.")
        return True

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
        self.name_column_action = QAction("Name Column…", self)
        self.name_column_action.triggered.connect(lambda _checked=False: self.name_column())
        menu.addAction(self.name_column_action)
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

    def name_column(self, col: int | None = None) -> bool:
        """Name a column (the current cell's, unless given), so formulas can
        use name1, name2, ... for its cells. Its current name can be changed
        or removed."""
        self._commit_pending_edit()
        if col is None:
            col = self.view.currentIndex().column()
        name = self._ask_column_name(col)
        if name is None:
            return False
        problem = self.model.name_column(col, name)
        if problem:  # (the dialog checks first; this is a safeguard)
            self._show_error("Couldn't name the column.", problem)
            return False
        return True

    def _ask_column_name(self, col: int) -> str | None:
        """The name chosen in the Name Column dialog, or None if cancelled."""
        dialog = NameColumnDialog(self.model, col, self)
        return dialog.chosen_name() if dialog.exec() == QDialog.Accepted else None

    def _show_header_menu(self, pos):
        """A secondary click on a column header: select the column (keeping a
        selection of whole columns it's in), and offer to insert or delete
        columns, or name it."""
        col = self.view.horizontalHeader().logicalIndexAt(pos)
        if col < 0:
            return
        lines = self.view.whole_lines()
        if lines is None or lines[0] != "columns" or col not in lines[1]:
            self.view.select_range(0, col, self.model.rowCount() - 1, col)
        menu = QMenu(self)
        menu.addAction(self.insert_cells_action)
        menu.addAction(self.delete_cells_action)
        menu.addSeparator()
        menu.addAction("Name Column…", lambda: self.name_column(col))
        menu.addSeparator()
        for ascending in (ASCENDING, DESCENDING):
            menu.addAction(f"Sort Sheet {ARROWS[ascending]}", lambda a=ascending: self.sort_sheet(col, a))
        menu.popup(self.view.horizontalHeader().mapToGlobal(pos))
        self.header_menu = menu  # kept alive while it's shown

    def _show_row_header_menu(self, pos):
        """A secondary click on a row header: select the row (keeping a
        selection of whole rows it's in), and offer to insert or delete rows."""
        row = self.view.verticalHeader().logicalIndexAt(pos)
        if row < 0:
            return
        lines = self.view.whole_lines()
        if lines is None or lines[0] != "rows" or row not in lines[1]:
            self.view.select_range(row, 0, row, self.model.columnCount() - 1)
        menu = QMenu(self)
        menu.addAction(self.insert_cells_action)
        menu.addAction(self.delete_cells_action)
        menu.popup(self.view.verticalHeader().mapToGlobal(pos))
        self.header_menu = menu

    def edit_names(self) -> bool:
        """Show every cell and column name, to rename, redefine, add, or delete."""
        self._commit_pending_edit()
        chosen = self._ask_names()
        if chosen is None:
            return False
        cells, columns = chosen
        self.model.replace_names(cells, "Edit Names", columns)
        return True

    def _ask_names(self) -> tuple | None:
        """The cell and column names as left in the Names dialog, or None if cancelled."""
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

    _KEEP = object()  # (for _set_font: leave the family, or the size, as each cell has it)

    def _set_font(self, family, size, name: str) -> None:
        """Give the selected cells a font family and size (None: the sheet's
        own; _KEEP: each cell's as it is), as one undoable step."""
        self._commit_pending_edit()
        styles = {}
        for key in self._selected_cells():
            style = self.model.cell_style(*key)
            changes = {}
            if family is not self._KEEP:
                changes["font"] = None if family == self.default_font_family else family
            if size is not self._KEEP:
                changes["size"] = None if size is None or size == self.default_font_size else float(size)
            styles[key] = dataclasses.replace(style, **changes)
        self.model.set_styles(styles, name)
        self._show_current_style()

    def _step_font_size(self, step: int) -> None:
        """One point bigger or smaller (Format > Increase or Decrease Font
        Size, and the toolbar's + and −), from the current cell's size."""
        current = self.view.currentIndex()
        style = self.model.cell_style(current.row(), current.column()) if current.isValid() else PLAIN
        size = min(max(round((style.size or self.default_font_size) + step), MIN_SIZE), MAX_SIZE)
        self._set_font(self._KEEP, size, "Font Size")

    def _size_typed(self) -> None:
        """A size typed (or chosen) in the toolbar's size box."""
        text = self.font_size_box.currentText().strip()
        try:
            size = float(text)
        except ValueError:
            size = None
        if size is None or not MIN_SIZE <= size <= MAX_SIZE:
            self._show_status(f"A font size is a number from {MIN_SIZE} to {MAX_SIZE}.")
            self._show_current_style()
            return
        self._set_font(self._KEEP, int(size) if size.is_integer() else size, "Font Size")

    def _add_font_item(self, family: str) -> int:
        """A family in the font box, shown in itself; its index."""
        self.font_box.addItem(family, family)
        index = self.font_box.count() - 1
        self.font_box.setItemData(index, QFont(family), Qt.FontRole)
        return index

    def _show_current_style(self, *_args):
        current = self.view.currentIndex()
        style = self.model.cell_style(current.row(), current.column()) if current.isValid() else PLAIN
        self.format_actions["Bold"].setChecked(style.bold)
        self.format_actions["Italic"].setChecked(style.italic)
        self.format_actions["Strikethrough"].setChecked(style.strikethrough)
        self._paint_color_icons()
        if getattr(self, "font_box", None) is not None:
            self.font_box.blockSignals(True)
            index = self.font_box.findData(style.font) if style.font is not None else 0
            if index < 0:  # a font this Mac doesn't have (the sheet came from another): listed, still
                index = self._add_font_item(style.font)
            self.font_box.setCurrentIndex(index)
            self.font_box.blockSignals(False)
            size = style.size or self.default_font_size
            self.font_size_box.blockSignals(True)
            self.font_size_box.setCurrentText(f"{int(size)}" if float(size).is_integer() else f"{size:g}")
            self.font_size_box.blockSignals(False)
        self._show_current_format()

    def _fit_rows_to_fonts(self, *_args) -> None:
        """Rows grow to fit a cell's bigger font, and shrink back when it's
        smaller again; a row resized by hand is left as it is."""
        if not hasattr(self, "_grown_rows"):
            return
        header = self.view.verticalHeader()
        default = header.defaultSectionSize()
        sizes = self.model.row_font_sizes()
        for row in {*sizes, *self._grown_rows}:
            if row >= header.count():
                self._grown_rows.pop(row, None)
                continue
            scale = max(sizes.get(row, 0) / self.default_font_size, 1.0)
            target = round(default * scale)
            expected = round(default * self._grown_rows.get(row, 1.0))
            if abs(header.sectionSize(row) - expected) <= 1 and header.sectionSize(row) != target:
                header.resizeSection(row, target)  # (not resized by hand since it was fitted)
            if scale > 1:
                self._grown_rows[row] = scale
            else:
                self._grown_rows.pop(row, None)

    def _rows_moved(self, *_args) -> None:
        """Rows inserted or deleted: what was fitted where is fitted afresh."""
        self._grown_rows = {}
        self._fit_rows_to_fonts()

    def _selected_cells(self) -> list[tuple[int, int]]:
        indexes = self.view.selectedIndexes() or [self.view.currentIndex()]
        return [(i.row(), i.column()) for i in indexes if i.isValid()]

    def _set_number_format(self, name: str, fmt: NumberFormat):
        self._commit_pending_edit()
        self.model.set_formats({key: fmt for key in self._selected_cells()}, f"{name} Format")
        self._show_current_format()

    def _custom_number_format(self) -> None:
        """Format > Number > Custom number format…: a pattern for the selected
        cells, starting at the current cell's format, as one."""
        self._commit_pending_edit()
        current = self.view.currentIndex()
        fmt = self.model.number_format(current.row(), current.column()) if current.isValid() else None
        value = self.model.value(current.row(), current.column()) if current.isValid() else None
        pattern = self._ask_custom_format(pattern_of(fmt), value if isinstance(value, float) else 1234.5678)
        if pattern is None:
            self._show_current_format()  # (the menu checked it)
            return
        self.model.set_formats({key: NumberFormat("custom", pattern=pattern) for key in self._selected_cells()},
                               "Custom Number Format")
        self._show_current_format()

    def _ask_custom_format(self, pattern: str, sample: float) -> str | None:
        """The Custom number format dialog: the pattern, or None if cancelled."""
        dialog = CustomFormatDialog(self, pattern, sample)
        return dialog.pattern() if dialog.exec() == QDialog.Accepted else None

    def _show_current_format(self, *_args) -> None:
        """Check the Number menu's format for the current cell's: the one it
        is, or else the one of its kind (Number, for one with 3 decimals)."""
        current = self.view.currentIndex()
        fmt = (self.model.number_format(current.row(), current.column()) if current.isValid() else None) or GENERAL
        names = [name for name, known in self.number_formats.items() if known == fmt]
        if not names and fmt.kind == "custom":  # (Fraction is one, by its pattern)
            self.format_actions[CUSTOM_FORMAT].setChecked(True)
            return
        names = names or [name for name, known in self.number_formats.items() if known.kind == fmt.kind]
        self.format_actions[names[0] if names else "Automatic"].setChecked(True)

    def _change_decimals(self, name: str, delta: int):
        """Show one more or one fewer decimal place in each selected number,
        starting from how it's shown now."""
        self._commit_pending_edit()
        formats = {}
        for row, col in self._selected_cells():
            value = self.model.value(row, col)
            shown = self.model.number_format(row, col)
            if not isinstance(value, float) or shown is not None and shown.kind in (*DATE_KINDS, "custom"):
                continue  # (dates and times have no decimals to show; a custom format's are in its pattern)
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
        # View > Toolbar shows or hides it: the same action as the toolbar's own right-click menu, so
        # it can be brought back once it's hidden.
        self.toolbar_action = toolbar.toggleViewAction()
        self.toolbar_action.setText("Toolbar")
        first = self.view_menu.actions()[0]
        self.view_menu.insertAction(first, self.toolbar_action)
        self.view_menu.insertSeparator(first)
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
        self.notebook_button = QToolButton()
        self.notebook_button.setText("Notebook")
        self.notebook_button.setToolTip("Send the selected cells to the sheet's notebook, as a DataFrame "
                                        "or as a DataFrame and a chart")
        # An arrow beside the text, like Σ and Fill have, but the whole button shows the menu.
        self.notebook_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.notebook_button.setMenu(self._add_notebook_menu())
        self.notebook_button.clicked.connect(lambda _checked=False: self.notebook_button.showMenu())
        toolbar.addWidget(self.notebook_button)
        self._add_currency_button(toolbar)
        self._add_angle_button(toolbar)
        self._collect_tools()
        self.statusBar()  # create it now so the window doesn't resize on the first message

    def _collect_tools(self) -> None:
        """Each tool's toolbar items, by its key, for showing and hiding
        them; then those hidden before, hidden again (or, before any are
        chosen, Fill and the angle unit)."""
        widgets = {
            "autosum": [self.autosum_button], "fill": [self.fill_button], "notebook": [self.notebook_button],
            **{key: [button] for key, button in self.number_buttons.items()},
            "font": [self.font_box],
            "size": [self.font_size_buttons["smaller"], self.font_size_box, self.font_size_buttons["bigger"]],
            "bold": [self.style_buttons["Bold"]], "italic": [self.style_buttons["Italic"]],
            "strikethrough": [self.style_buttons["Strikethrough"]],
            "text color": [self.color_buttons["color"]], "fill color": [self.color_buttons["fill"]],
            "borders": [self.borders_button], "merge": [self.merge_button],
        }
        owner = {id(widget): key for key, group in widgets.items() for widget in group}
        self.tool_actions = {key: [] for key, _label in TOOLS}
        for action in self.toolbar.actions():
            if action is self.angle_button_action:
                self.tool_actions["angle"].append(action)
            elif not action.isSeparator():
                key = owner.get(id(self.toolbar.widgetForAction(action)))
                if key is not None:
                    self.tool_actions[key].append(action)
        saved = appearance.settings().value(HIDDEN_TOOLS_KEY)
        if saved is None:  # never chosen
            saved = DEFAULT_HIDDEN_TOOLS
        saved = saved.split(",") if isinstance(saved, str) else saved or []  # (QSettings may give a list)
        hidden = [key for key in saved if key in self.tool_actions]
        self._show_tools({key: key not in hidden for key in self.tool_actions}, save=False)

    def _show_tools(self, shown: dict[str, bool], save: bool = True) -> None:
        """Show or hide tools (key -> shown); separators show only between
        tools that are shown. `save` remembers which are hidden, for next time."""
        for key, visible in shown.items():
            for action in self.tool_actions[key]:
                action.setVisible(visible)
        # A separator shows if there are tools shown on both sides of it: some since the one before it.
        actions = self.toolbar.actions()
        for index, action in enumerate(actions):
            if action.isSeparator():
                right = any(a.isVisible() for a in actions[index + 1:] if not a.isSeparator())
                action.setVisible(self._shown_before(actions, index) and right)
        if save:
            hidden = [key for key in self.tool_actions if not self.tool_shown(key)]
            appearance.settings().setValue(HIDDEN_TOOLS_KEY, ",".join(hidden))

    @staticmethod
    def _shown_before(actions, index: int) -> bool:
        """Whether a tool's shown before the separator at `index`, since the
        last separator shown (one hidden isn't a gap between tools)."""
        for action in reversed(actions[:index]):
            if action.isSeparator():
                if action.isVisible():
                    return False
            elif action.isVisible():
                return True
        return False

    def tool_shown(self, key: str) -> bool:
        return any(action.isVisible() for action in self.tool_actions[key])

    def createPopupMenu(self):
        """The toolbar's right-click menu: each tool, checked if it's shown
        (choose it to show or hide it), Show All Tools, and Hide Toolbar."""
        menu = QMenu(self)
        for key, label in TOOLS:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.tool_shown(key))
            action.toggled.connect(lambda checked, k=key: self._show_tools({k: checked}))
        menu.addSeparator()
        menu.addAction("Show All Tools").triggered.connect(
            lambda _checked=False: self._show_tools({key: True for key in self.tool_actions}))
        menu.addSeparator()
        hide = menu.addAction("Hide Toolbar")
        hide.triggered.connect(lambda _checked=False: self.toolbar.hide())  # (View > Toolbar shows it again)
        return menu

    def _add_currency_button(self, toolbar):
        """Number format buttons, as Google Sheets has them: $ (Currency), %
        (Percent), fewer and more decimals (drawn .0← and .00→), and 123,
        showing the Format menu's Number menu of them all."""
        toolbar.addSeparator()
        self.number_buttons = {}
        for key, label, tip, action_name in (
                ("currency", "$", "Format as currency ($1,000.12)", "Currency"),
                ("percent", "%", "Format as percent (10.12%)", "Percent"),
                ("fewer", "", "Decrease decimal places", "Decrease Decimals"),
                ("more", "", "Increase decimal places", "Increase Decimals"),
                ("formats", "123", "More formats", None)):
            button = QToolButton()
            button.setText(label)
            button.setToolTip(tip)
            font = button.font()
            font.setPointSize(15)  # closer to the Σ button; the menu items keep normal text
            button.setFont(font)
            if action_name is not None:
                action = self.format_actions[action_name]
                button.clicked.connect(lambda _checked=False, a=action: a.trigger())
            else:  # an arrow beside it, as Notebook has, but the whole button shows the menu
                button.setMenu(self.number_menu)
                button.setPopupMode(QToolButton.MenuButtonPopup)
                button.clicked.connect(lambda _checked=False, b=button: b.showMenu())
            toolbar.addWidget(button)
            self.number_buttons[key] = button
        self._paint_decimal_icons()
        self._add_font_boxes(toolbar)
        self._add_style_buttons(toolbar)

    def _add_font_boxes(self, toolbar):
        """The font's family, and its size with − and + beside it, as Google Sheets has them."""
        toolbar.addSeparator()
        self.font_box = QComboBox()  # Default (the sheet's own), then the Mac's fonts, each shown in itself
        self.font_box.setToolTip("Font")
        self.font_box.setMaximumWidth(170)
        self.font_box.addItem(DEFAULT_FONT, None)
        self.font_box.insertSeparator(1)
        for family in QFontDatabase.families():
            if not family.startswith("."):  # (the system's own, hidden ones)
                self._add_font_item(family)
        self.font_box.activated.connect(
            lambda index: self._set_font(self.font_box.itemData(index), self._KEEP, "Font"))
        toolbar.addWidget(self.font_box)
        toolbar.addSeparator()
        self.font_size_buttons = {}
        for key, label, tip, step in (("smaller", "−", "Decrease font size (⇧⌘,)", -1),
                                      ("bigger", "+", "Increase font size (⇧⌘.)", 1)):
            button = QToolButton()
            button.setText(label)
            button.setToolTip(tip)
            font = button.font()
            font.setPointSize(15)
            button.setFont(font)
            button.clicked.connect(lambda _checked=False, s=step: self._step_font_size(s))
            self.font_size_buttons[key] = button
        toolbar.addWidget(self.font_size_buttons["smaller"])
        self.font_size_box = _SizeBox()
        self.font_size_box.setEditable(True)
        self.font_size_box.setInsertPolicy(QComboBox.NoInsert)
        self.font_size_box.setToolTip("Font size")
        for size in SIZES:
            self.font_size_box.addItem(str(size))
        self.font_size_box.textActivated.connect(lambda _text: self._size_typed())
        toolbar.addWidget(self.font_size_box)
        toolbar.addWidget(self.font_size_buttons["bigger"])

    def _paint_decimal_icons(self) -> None:
        """The fewer and more decimals buttons' icons, in the toolbar's text color."""
        color = self.palette().color(QPalette.ButtonText)
        for key, digits, left in (("fewer", ".0", True), ("more", ".00", False)):
            button = self.number_buttons[key]
            button.setIcon(_decimals_icon(digits, left, color, max(self.devicePixelRatioF(), 2.0)))
            button.setIconSize(QSize(32, 28))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.PaletteChange and getattr(self, "number_buttons", None):
            self._paint_decimal_icons()  # light to dark, or back
            self._paint_color_icons()
            self._paint_border_icons()

    def _add_style_buttons(self, toolbar):
        """B, I, and S toolbar buttons for the Format menu's Bold, Italic, and
        Strikethrough, drawn in bold, italic, and struck through; they're
        pressed when the current cell has the style. A separator sets them
        apart from the font boxes."""
        toolbar.addSeparator()
        self.style_buttons = {}
        for name, label, tip in (("Bold", "B", "Bold (⌘B)"), ("Italic", "I", "Italic (⌘I)"),
                                 ("Strikethrough", "S", "Strikethrough (⇧⌘X)")):
            action = self.format_actions[name]
            action.setIconText(label)
            action.setToolTip(tip)
            button = QToolButton()  # (its own, so hiding it on the toolbar leaves the Format menu's)
            button.setDefaultAction(action)
            toolbar.addWidget(button)
            self.style_buttons[name] = button
            font = button.font()
            font.setPointSize(15)
            font.setBold(name == "Bold")
            font.setItalic(name == "Italic")
            font.setStrikeOut(name == "Strikethrough")
            button.setFont(font)
        self._add_color_buttons(toolbar)
        self._add_border_buttons(toolbar)

    def _add_border_buttons(self, toolbar):
        """Borders (the borders menu, with its color and style) and Merge
        cells (merges the selection, or unmerges a merged cell; its arrow
        has Merge all, vertically, horizontally, and Unmerge), as Google
        Sheets has them."""
        toolbar.addSeparator()
        self.borders_button = QToolButton()
        self.borders_button.setToolTip("Borders")
        self.borders_button.setMenu(self._borders_menu(in_toolbar=True))
        self.borders_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.borders_button.clicked.connect(lambda _checked=False: self.borders_button.showMenu())
        toolbar.addWidget(self.borders_button)
        self.merge_button = QToolButton()
        self.merge_button.setToolTip("Merge cells")
        self.merge_button.setMenu(self._merge_menu())
        self.merge_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.merge_button.clicked.connect(lambda _checked=False: self._merge_or_unmerge())
        toolbar.addWidget(self.merge_button)
        self._paint_border_icons()

    def _paint_border_icons(self) -> None:
        """The border and merge icons, in the toolbar's text color (and the menus' choices)."""
        ink, ratio = self.palette().color(QPalette.ButtonText), max(self.devicePixelRatioF(), 2.0)
        self.borders_button.setIcon(border_icon("all", ink, ratio))
        self.merge_button.setIcon(merge_icon(ink, ratio))
        for action in self.border_actions:
            kind = action.data()
            action.setIcon(border_icon(kind, ink, ratio) if kind in dict(BORDER_KINDS) else
                           border_style_icon(kind, ink, ratio))

    def _borders_menu(self, in_toolbar: bool) -> QMenu:
        """The borders menu: Google Sheets' ten choices, and the color and
        style they draw in. (The toolbar's has the palette for the color;
        the Format menu's, which is the Mac's own menu, a color dialog.)"""
        if not hasattr(self, "border_actions"):
            self.border_actions = []
            self.border_style_actions = {}
        menu = QMenu("Borders", self)
        for key, name in BORDER_KINDS:
            action = menu.addAction(name)
            action.setData(key)
            action.triggered.connect(lambda _checked=False, k=key: self._apply_borders(k))
            self.border_actions.append(action)
            if key == "outer":
                menu.addSeparator()
        menu.addSeparator()
        if in_toolbar:
            colors = ColorMenu("Black", self)
            colors.setTitle("Border color")
            colors.chosen.connect(lambda color: self._set_border_color(color or "#000000"))
            colors.custom.connect(self._custom_border_color)
            menu.addMenu(colors)
        else:
            menu.addAction("Border Color…").triggered.connect(lambda _checked=False: self._custom_border_color())
        styles = menu.addMenu("Border style")
        group = QActionGroup(styles)
        for style in BORDER_STYLES:
            action = styles.addAction(style.capitalize())
            action.setData(style)
            action.setCheckable(True)
            action.setChecked(style == self.border_style)
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, s=style: self._set_border_style(s))
            self.border_actions.append(action)
            self.border_style_actions.setdefault(style, []).append(action)
        if hasattr(self, "merge_button"):  # (the toolbar's made: its icons are painted then)
            self._paint_border_icons()
        return menu

    def _merge_menu(self) -> QMenu:
        menu = QMenu("Merge Cells", self)
        for key, name in MERGE_KINDS:
            if key == "unmerge":
                menu.addSeparator()
            menu.addAction(name).triggered.connect(lambda _checked=False, k=key: self._merge(k))
        return menu

    def _selected_block(self) -> tuple[int, int, int, int]:
        """The selection's bounds, grown to take in any merged cells it touches."""
        top, left, bottom, right = self.view.selection_bounds()
        grown = True
        while grown:
            grown = False
            for m_top, m_left, m_bottom, m_right in self.model.merges():
                if m_top <= bottom and top <= m_bottom and m_left <= right and left <= m_right:
                    new = (min(top, m_top), min(left, m_left), max(bottom, m_bottom), max(right, m_right))
                    if new != (top, left, bottom, right):
                        top, left, bottom, right = new
                        grown = True
        return top, left, bottom, right

    def _apply_borders(self, kind: str) -> None:
        """A borders menu choice, for the selection, in the border color and style."""
        self._commit_pending_edit()
        styles = border_styles(self.model.cell_style, self._selected_block(), kind,
                               Border(self.border_style, self.border_color),
                               self.model.rowCount(), self.model.columnCount())
        self.model.set_styles(styles, "Clear Borders" if kind == "clear" else "Borders")

    def _set_border_style(self, style: str) -> None:
        self.border_style = style
        for each, actions in self.border_style_actions.items():
            for action in actions:
                action.setChecked(each == style)

    def _set_border_color(self, color: str) -> None:
        self.border_color = color

    def _custom_border_color(self) -> None:
        color = self._ask_color(self.border_color, "Border Color")
        if color is not None:
            self._set_border_color(color)

    def _merge_or_unmerge(self) -> None:
        """The merge button: unmerge the current merged cell, else merge the selection."""
        current = self.view.currentIndex()
        top, left, bottom, right = self.view.selection_bounds()
        block = self.model.merge_at(current.row(), current.column())
        if block is not None and block[0] <= top and block[1] <= left and bottom <= block[2] and right <= block[3]:
            self._merge("unmerge")
        else:
            self._merge("all")

    def _merge(self, how: str) -> None:
        """Merge the selection (how: all, vertically, horizontally) or
        unmerge it. Merging keeps each merged block's top-left value; if
        others would be lost, it asks first."""
        self._commit_pending_edit()
        block = self._selected_block()
        merges = merged(self.model.merges(), block, how)
        if how != "unmerge" and merges == set(self.model.merges()):
            self._show_status("Select more than one cell to merge them.")
            return
        lost = {key for key in covered(merges) - covered(self.model.merges()) if self.model.get_cell(*key)}
        if lost and not self._ask_merge_anyway():
            return
        self.model.set_merges(merges, {key: "" for key in lost}, "Unmerge Cells" if how == "unmerge" else
                              "Merge Cells")
        self.view.setCurrentIndex(self.model.index(*block[:2]))  # the merged cell, or the first unmerged one

    def _ask_merge_anyway(self) -> bool:
        """Whether to merge though only the top-left values will be kept."""
        answer = QMessageBox.question(self, "Merge Cells", "Merging cells keeps only the top-left value of each "
                                      "merged block. Merge anyway?", QMessageBox.Ok | QMessageBox.Cancel)
        return answer == QMessageBox.Ok

    def _add_color_buttons(self, toolbar):
        """Text color (an A) and fill color (a paint bucket), each showing
        Google Sheets' palette of colors, with Reset and Custom…; their bars
        show the current cell's colors."""
        self.color_buttons, self.color_menus = {}, {}
        for key, tip in (("color", "Text color"), ("fill", "Fill color")):
            menu = ColorMenu("Reset", self)
            menu.chosen.connect(lambda color, k=key: self._set_color(k, color))
            menu.custom.connect(lambda k=key: self._custom_color(k))
            button = QToolButton()
            button.setToolTip(tip)
            button.setIconSize(COLOR_ICON_SIZE)
            button.setMenu(menu)
            button.setPopupMode(QToolButton.MenuButtonPopup)  # an arrow beside it, as Notebook has
            button.clicked.connect(lambda _checked=False, b=button: b.showMenu())
            toolbar.addWidget(button)
            self.color_buttons[key], self.color_menus[key] = button, menu
        self._paint_color_icons()

    def _paint_color_icons(self, *_args) -> None:
        """The color buttons' icons, in the toolbar's text color, with the current cell's colors in their bars."""
        if not getattr(self, "color_buttons", None):
            return
        current = self.view.currentIndex()
        style = self.model.cell_style(current.row(), current.column()) if current.isValid() else PLAIN
        ink, ratio = self.palette().color(QPalette.ButtonText), max(self.devicePixelRatioF(), 2.0)
        shown = (style.color, style.fill, ink.name(), ratio)
        if shown == getattr(self, "_color_icons_shown", None):
            return  # (painted already)
        self._color_icons_shown = shown
        text_bar = QColor(style.color) if style.color else ink
        fill_bar = QColor(style.fill) if style.fill else None
        self.color_buttons["color"].setIcon(text_color_icon(ink, text_bar, ratio))
        self.color_buttons["fill"].setIcon(fill_color_icon(ink, fill_bar, ratio))

    _COLOR_NAMES = {"color": "Text Color", "fill": "Fill Color"}

    def _set_color(self, key: str, color: str | None) -> None:
        """The selected cells' text color, or fill color (None: Reset, none of their own)."""
        self._commit_pending_edit()
        styles = {cell: dataclasses.replace(self.model.cell_style(*cell), **{key: color})
                  for cell in self._selected_cells()}
        self.model.set_styles(styles, self._COLOR_NAMES[key])
        self._show_current_style()

    def _custom_color(self, key: str) -> None:
        """Custom…: any color, starting at the current cell's."""
        current = self.view.currentIndex()
        style = self.model.cell_style(current.row(), current.column()) if current.isValid() else PLAIN
        color = self._ask_color(getattr(style, key), self._COLOR_NAMES[key])
        if color is not None:
            self._set_color(key, color)

    def _ask_color(self, start: str | None, title: str) -> str | None:
        """The color dialog: the color chosen, #rrggbb, or None if cancelled."""
        color = QColorDialog.getColor(QColor(start) if start else QColor("#000000"), self, title)
        return color.name() if color.isValid() else None

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
        self.setWindowModified(not clean or self._notebook_dirty)

    def _on_notebook_changed(self):
        self._notebook_dirty = True
        self.setWindowModified(True)

    # --- Notebook ---

    def show_notebook(self):
        """Open the sheet's notebook window (making it the first time). A new
        notebook starts with a cell importing pandas and seaborn, which runs."""
        if self.notebook_window is None:
            self.notebook_window = NotebookWindow(self.notebook, self.kernel, parent=self, save=self.save)
            self.notebook_window.zoom_changed.connect(self._update_zoom_actions)
            self.notebook_window.set_sheet_name(os.path.basename(self.file_path) if self.file_path
                                                else "Untitled")
        if self.notebook.is_empty:
            self.notebook_window.run_cell(self.notebook_window.add_cell_below(IMPORTS_CELL))
        self.notebook_window.show()
        self.notebook_window.raise_()
        self.notebook_window.activateWindow()
        return self.notebook_window

    def send_to_notebook(self) -> str | None:
        """Notebook > DataFrame. The DataFrame dialog names a new pandas
        DataFrame (df, df2, ... to start with) of the selected cells, or (with
        no more than one cell selected) of the whole sheet's data, which goes
        in a new notebook cell and runs. With DataFrames in the notebook, it
        lists them too, to rename one, or update its data from those cells
        (see _change_frame): those its cells write out, and others its Python
        has, which it's asked for first (see _find_frames), so the dialog may
        come when Python answers. Returns the cell's id if it's done straight
        away, else None (as when there's no data and no DataFrame to change,
        or the dialog was cancelled)."""
        self._commit_pending_edit()
        cells, source, problem = self._sheet_data()
        done = []
        self._find_frames(lambda frames: done.append(self._dataframe_dialog(frames, cells, source, problem)))
        return done[0] if done else None

    def _find_frames(self, done) -> None:
        """done(the notebook's DataFrames, as FrameCells): the ones its cells
        write out, and the others its Python has, if it has code of your own
        that could make them (else the cells say what there is: no need to
        ask). If nothing in the notebook has run in this Python process (as
        when the sheet's just opened), it runs first. Python answers in the
        background, after the cells running; if it can't, done gets just the
        ones the cells write out."""
        if not self._notebook_has_own_code():
            done(find_frames(self.notebook))
            return
        self._run_notebook_if_not_run()
        self._show_status("Looking for DataFrames in the notebook…")

        def answered(value, _error):
            self._show_status("")
            done(find_frames(self.notebook, frames(value) if value is not None else ()))

        self._ask_notebook(*frames_request(), answered)

    def _notebook_has_code(self) -> bool:
        """Whether the notebook has any code but a new notebook's imports."""
        return any(cell.source.strip() and cell.source.strip() != IMPORTS_CELL for cell in self.notebook.cells)

    def _notebook_has_own_code(self) -> bool:
        """Whether the notebook has code but the imports, DataFrames, and
        charts EZ Sheet writes: yours, which may make DataFrames of its own."""
        written = ({frame.cell_id for frame in find_frames(self.notebook)}
                   | {graph.cell_id for graph in find_graphs(self.notebook)})
        return any(cell.source.strip() and cell.source.strip() != IMPORTS_CELL and cell.id not in written
                   for cell in self.notebook.cells)

    def _run_notebook_if_not_run(self) -> None:
        """Run all the notebook's cells, if none has run (or is running) in
        this Python process, so its DataFrames are there to ask about."""
        window = self.notebook_window
        if window is None or not (window.ran or window.running):
            self._show_status("Running the notebook…")
            self.show_notebook().run_all()

    def _dataframe_dialog(self, frames, cells, source: str, problem: str | None) -> str | None:
        """The DataFrame dialog, with the notebook's `frames`, and what comes
        of it: a new DataFrame of `cells`, or one of `frames` changed (see
        send_to_notebook)."""
        if problem is not None and not frames:
            self._show_status(f"There's nothing to make a DataFrame of: {problem[0].lower()}{problem[1:]} "
                              "Select cells with data to make a DataFrame of them.")
            return None
        answer = self._ask_dataframe(frames, self._first_frame(frames), next_frame_name(self.notebook), source,
                                     problem)
        if answer is None:
            return None
        index, name, update = answer
        if index is not None:
            return self._change_frame(frames[index], name, update, cells, source)
        self.show_notebook()  # a new notebook gets its imports cell first
        pandas = importing_cell(self.notebook, "pandas")
        [cell_id] = self._run_in_notebook([dataframe_code(self.model, cells, name, pandas is None)], [pandas])
        self.notebook_window.reveal(cell_id)  # so its table can be seen
        self._show_status(f"Sent {source} to the notebook as {name}.")
        return cell_id

    def _first_frame(self, frames) -> int | None:
        """Which item the DataFrame dialog's list starts at: New DataFrame
        (None), unless no more than one cell is selected and the notebook's
        current cell makes one of the DataFrames."""
        current_id = self.notebook_window.current_id if self.notebook_window is not None else None
        ids = [frame.cell_id for frame in frames]
        return ids.index(current_id) if len(self._selected_cells()) <= 1 and current_id in ids else None

    def _change_frame(self, frame, name: str, update: bool, cells, source: str) -> str | None:
        """Rename one of the notebook's DataFrames (in its cell, and the cells
        after it that use it), or write its data afresh from the sheet's
        cells (in its cell, keeping anything else there), or both. Its cell
        runs again; with new data, so do the cells after it that depend on it
        (its charts among them; see dependent_cells). Returns its cell's id, or None if there was
        nothing to change or it couldn't be changed."""
        renamed, unread = {}, []
        try:
            if name != frame.name:
                renamed, unread = rename_frame(self.notebook, frame.cell_id, frame.name, name)
            if update:
                code = renamed.get(frame.cell_id, self.notebook.cell(frame.cell_id).source)
                pandas = importing_cell(self.notebook, "pandas", frame.cell_id)
                renamed[frame.cell_id] = update_frame_code(code, name, self.model, cells, import_pandas=pandas is None)
        except ValueError as e:
            self._show_error(f"Couldn't change the DataFrame {frame.name}.", str(e))
            return None
        if not renamed:
            self._show_status(f"{frame.name} is unchanged: give it a new name, or check Update data.")
            return None
        window = self.show_notebook()
        for cell_id, code in renamed.items():
            window.replace_source(cell_id, code)
        users = dependent_cells(self.notebook, frame.cell_id, name) if update else []
        window.ran.discard(frame.cell_id)  # Python has its old name, or data
        window.run_needed([importing_cell(self.notebook, "pandas", frame.cell_id), frame.cell_id])
        for cell_id in users:  # with the new data, and what's worked out from it; charts redrawn with it
            window.run_needing(cell_id, [importing_cell(self.notebook, module, cell_id)
                                         for module in ("pandas", "seaborn")])
        window.set_current(frame.cell_id, focus=True)
        window.reveal(frame.cell_id)
        done = []
        if name != frame.name:
            done.append(f"Renamed {frame.name} to {name} in {_cells(len(renamed))}.")
        if update:
            rerun = f" Running the {_cells(len(users))} depending on it again." if users else ""
            done.append(f"Updated {name} with {source}.{rerun}")
        self._show_status(" ".join(done) + _unread_note(unread, frame.name))
        return frame.cell_id

    def send_graph_to_notebook(self) -> str | None:
        """Notebook > Chart. With charts in the notebook, the Chart dialog
        lists them, and New chart: change one, or make a new one. Without,
        it's straight to a new one. A new chart is of the selected cells, or
        (with no more than one cell selected) of the whole sheet's data, put
        in a new DataFrame; or of one of the notebook's DataFrames, chosen in
        the dialog (its own, or yours: see _find_chart_frames, which may
        mean the dialog comes once Python answers). It goes in the notebook
        as a DataFrame cell (unless it's of one already there) and a Seaborn
        chart cell, which run. Returns the chart cell's id if it's done
        straight away, else None (as when there's nothing that can be
        charted, which an error says, or the dialog was cancelled)."""
        self._commit_pending_edit()
        cells, source, problem = self._sheet_data()
        columns = None
        if problem is None:
            try:
                columns = graph_columns(self.model, cells)
            except GraphError as e:
                problem = str(e)
        done = []
        self._find_chart_frames(
            lambda chart_frames: done.append(self._chart_dialog(chart_frames, cells, source, columns, problem)))
        return done[0] if done else None

    def _find_chart_frames(self, done) -> None:
        """done(the notebook's DataFrames, as ChartFrames): see _find_frames.
        For your own, Python is asked what's in their columns too."""
        def found(frame_cells):
            own = [frame.name for frame in frame_cells if frame.data is None]
            if not own:
                done([ChartFrame.of(frame, frame.data) for frame in frame_cells])
                return

            def answered(value, error):
                data = frame_columns(value) if value is not None else {}
                done([ChartFrame.of(frame, frame.data if frame.data is not None
                                    else data.get(frame.name, f"Python couldn't say what's in it: {error}"))
                      for frame in frame_cells])

            self._ask_notebook(*columns_request(own), answered)

        self._find_frames(found)

    def _chart_dialog(self, chart_frames, cells, source: str, columns, problem: str | None) -> str | None:
        """The Chart dialog, and what comes of it (see send_graph_to_notebook)."""
        graphs = find_graphs(self.notebook)
        of = {option.frame.name: option for option in chart_frames}
        for graph in graphs:  # a chart of your own DataFrame: its columns, from what Python says
            option = of.get(graph.frame)
            if graph.data is None and option is not None and option.columns is not None \
                    and option.frame.cell_id == graph.frame_cell:
                graph.data, graph.columns = option.data, option.columns
        frame = next_frame_name(self.notebook)
        if not graphs:
            if problem is not None and not chart_frames:
                self._show_error(f"Can't make a chart of {source}.", problem)
                return None
            choice = self._ask_graph_options(columns, source, frame, chart_frames, problem)
            index = None
        else:
            answer = self._ask_chart(graphs, self._first_chart(graphs), columns, source, problem, frame,
                                     chart_frames)
            if answer is None:
                return None
            index, choice = answer
        if choice is None:
            return None
        if index is not None:
            return self._change_chart(graphs, index, choice)
        if choice.frame in of:
            return self._chart_frame(of[choice.frame], choice)
        return self._make_chart(cells, source, choice)

    def _chart_frame(self, option: ChartFrame, choice: GraphChoice) -> str | None:
        """A chart of one of the notebook's DataFrames, in a new cell at the
        notebook's end, which runs (after its DataFrame's cell, and the
        imports, if they haven't run in this Python process). Returns the
        chart cell's id."""
        self.graph_kind, self.graph_marker = choice.kind, choice.marker
        self.show_notebook()
        pandas, seaborn = importing_cell(self.notebook, "pandas"), importing_cell(self.notebook, "seaborn")
        try:
            code = frame_graph_code(option.data, option.frame.name, choice.kind, choice.marker, choice.x,
                                    choice.ys, choice.hue, choice.y_categories, import_pandas=pandas is None,
                                    import_seaborn=seaborn is None, col=choice.col)
        except (ValueError, GraphError) as e:
            self._show_error(f"Couldn't make a chart of {option.frame.name}.", str(e))
            return None
        [graph_id] = self._run_in_notebook([code], [pandas, seaborn, option.frame.cell_id])
        self.notebook_window.reveal(graph_id)  # so the chart can be seen when it's drawn
        self._show_status(f"Charting {option.frame.name} in a new notebook cell.")
        return graph_id

    def _sheet_data(self) -> tuple[set, str, str | None]:
        """What a new chart or DataFrame is of: the selected cells, or, with
        no more than one cell selected, the whole sheet's data. (cells, how
        to name them, what's wrong if there's nothing there)."""
        selected = self._selected_cells()
        if len(selected) > 1:
            cells = data_block(self.model, selected)
            if not cells:
                return set(), "the selected cells", "The selection is empty."
            return cells, f"the selected cells, {_block_name(cells)}", None
        used = self.model.used_range()
        if used is None:
            return set(), "the sheet", "The sheet is empty."
        top, left, bottom, right = used
        cells = {(row, col) for row in range(top, bottom + 1) for col in range(left, right + 1)}
        return cells, f"the whole sheet, {cell_name(top, left)}:{cell_name(bottom, right)}", None

    def _first_chart(self, graphs) -> int | None:
        """Which item the Chart dialog's list starts at: New chart (None) with
        several cells selected; otherwise the chart in the notebook's current
        cell, or else the newest."""
        if len(self._selected_cells()) > 1:
            return None
        ids = [graph.cell_id for graph in graphs]
        current_id = self.notebook_window.current_id if self.notebook_window is not None else None
        return ids.index(current_id) if current_id in ids else len(ids) - 1

    def _make_chart(self, cells, source: str, choice: GraphChoice) -> str:
        """Put the cells in a DataFrame in a new notebook cell, and the chart
        chosen of it in the next; open the notebook and run them. Returns the
        chart cell's id."""
        self.graph_kind, self.graph_marker = choice.kind, choice.marker
        name = choice.frame or next_frame_name(self.notebook)
        self.show_notebook()  # a new notebook gets its imports cell first
        pandas, seaborn = importing_cell(self.notebook, "pandas"), importing_cell(self.notebook, "seaborn")
        graph = graph_code(self.model, cells, name, choice.kind, choice.marker, choice.x, choice.ys, choice.hue,
                           choice.y_categories, import_pandas=pandas is None, import_seaborn=seaborn is None,
                           col=choice.col)
        _frame_id, graph_id = self._run_in_notebook(
            [dataframe_code(self.model, cells, name, pandas is None), graph], [pandas, seaborn])
        self.notebook_window.reveal(graph_id)  # so the chart can be seen when it's drawn
        self._show_status(f"Sent {source} to the notebook as {name}, with a chart of it.")
        return graph_id

    def _change_chart(self, graphs, index: int, chosen: GraphChoice) -> str | None:
        """Redraw one of the notebook's charts with the choices made. New
        columns (across, up, for the hue, or splitting it into panels) mean
        writing its cell afresh, from its DataFrame's cell; otherwise just its
        kind and marker change in the code. A new name for its DataFrame
        renames it in its cell and the cells after it that use it. Returns
        its cell id, or None if it couldn't be changed."""
        graph = graphs[index]
        pandas = importing_cell(self.notebook, "pandas", graph.cell_id)
        seaborn = importing_cell(self.notebook, "seaborn", graph.cell_id)
        frame, renamed, unread = graph.frame, {}, []
        try:
            if chosen.frame and chosen.frame != graph.frame and graph.renamable:
                renamed, unread = rename_frame(self.notebook, graph.frame_cell, graph.frame, chosen.frame)
                frame = chosen.frame
            source = renamed.get(graph.cell_id, self.notebook.cell(graph.cell_id).source)
            columns_before = (graph.x_label, graph.y_labels, graph.hue, graph.col, graph.columns is not None
                              and graph.columns.sideways(graph.y_labels, graph.kind, graph.y_categories))
            columns_after = (chosen.x, chosen.ys, chosen.hue, chosen.col, graph.columns is not None
                             and graph.columns.sideways(chosen.ys, chosen.kind, chosen.y_categories))
            if graph.data is not None and columns_after != columns_before:
                source = frame_graph_code(graph.data, frame, chosen.kind, chosen.marker, chosen.x,
                                          chosen.ys, chosen.hue, chosen.y_categories,
                                          import_pandas=pandas is None, import_seaborn=seaborn is None,
                                          col=chosen.col)
            else:
                source = change_graph(source, chosen.kind, chosen.marker)
        except (ValueError, GraphError) as e:
            self._show_error("Couldn't change the chart.", str(e))
            return None
        window = self.show_notebook()
        for cell_id, renamed_source in renamed.items():
            if cell_id != graph.cell_id:
                window.replace_source(cell_id, renamed_source)
        window.replace_source(graph.cell_id, source)
        window.set_current(graph.cell_id, focus=True)
        if renamed:
            window.ran.discard(graph.frame_cell)  # Python has the DataFrame by its old name
        # After a restart, or in a reopened sheet, the imports and the DataFrame have to run again first.
        window.run_needing(graph.cell_id, [pandas, seaborn, graph.frame_cell])
        window.reveal(graph.cell_id)  # so the chart can be seen when it's redrawn
        label = graph_labels([*graphs[:index], dataclasses.replace(graph, frame=frame), *graphs[index + 1:]])[index]
        status = f"Redrawing the chart {label}."
        if renamed:
            status = f"Renamed {graph.frame} to {frame} in {_cells(len(renamed))}. {status}"
        self._show_status(status + _unread_note(unread, graph.frame))
        return graph.cell_id

    def _ask_chart(self, graphs, current: int | None, columns, source: str, problem: str | None,
                   frame: str, chart_frames=()) -> tuple[int | None, GraphChoice] | None:
        """The Chart dialog with its list of the notebook's charts and New
        chart (current None): (which, None for a new one; the choices), or
        None if cancelled. `problem` says why a new chart of `source` can't
        be made; `frame` is what its DataFrame's name starts at, and
        `chart_frames` the notebook's DataFrames it can be of instead."""
        dialog = GraphDialog(self, columns, self.graph_kind, self.graph_marker, graphs=graphs, current=current,
                             new_source=source, new_problem=problem, frame=frame,
                             taken=assigned_names(self.notebook), used=used_names(self.notebook),
                             chart_frames=chart_frames)
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.chosen_graph(), dialog.choice()

    def _ask_graph_options(self, columns, source: str, frame: str, chart_frames=(),
                           problem: str | None = None) -> GraphChoice | None:
        """The Chart dialog for a new chart of these GraphColumns, its
        DataFrame's name starting at `frame`, or of one of `chart_frames`:
        the choices, or None if cancelled. `problem` says why there's none
        of `source`."""
        dialog = GraphDialog(self, columns, self.graph_kind, self.graph_marker, new_source=source, frame=frame,
                             taken=assigned_names(self.notebook), chart_frames=chart_frames, new_problem=problem)
        return dialog.choice() if dialog.exec() == QDialog.Accepted else None

    def _ask_dataframe(self, frames, current: int | None, name: str, source: str,
                       problem: str | None) -> tuple[int | None, str, bool] | None:
        """The DataFrame dialog: (which of the notebook's `frames` to change,
        None for a new DataFrame of `source`, starting at frames[current];
        its name, starting at `name` for a new one; whether to update its
        data), or None if cancelled. `problem` says why `source` has no data."""
        dialog = FrameNameDialog(self, name, source, assigned_names(self.notebook), frames, current, problem,
                                 used_names(self.notebook))
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.chosen_frame(), dialog.name(), dialog.update()

    def load_data_to_sheet(self) -> None:
        """Ask the notebook's Python for its DataFrames, then which one to
        load, and put its data in the sheet at the current cell. If nothing
        in the notebook has run in this Python process (as when the sheet's
        just opened), it runs first. Python answers in the background (after
        any cells still running), so the rest happens when it does."""
        self._commit_pending_edit()
        if not self._notebook_has_code() and not self.kernel.has_kernel:
            self._show_status("The notebook has no DataFrames to load. Make one in a cell first.")
            return
        if self._notebook_has_code():
            self._run_notebook_if_not_run()  # as when the sheet's just opened: so its DataFrames are there
        self._show_status("Looking for DataFrames in the notebook…")
        self._ask_notebook(*frames_request(), self._frames_found)

    def _frames_found(self, value, error: str) -> None:
        if value is None:
            self._show_status(f"Couldn't look for DataFrames: {error}")
            return
        found = frames(value)
        if not found:
            self._show_status("The notebook has no DataFrames to load. Make one in a cell and run it first.")
            return
        current = self.view.currentIndex()
        top, left = (current.row(), current.column()) if current.isValid() else (0, 0)
        name = self._ask_frame_to_load(found, cell_name(top, left))
        if name is None:
            self._show_status("")
            return
        self._show_status(f"Loading {name}…")
        self._ask_notebook(*data_request(name),
                           lambda value, error: self._frame_data_arrived(name, top, left, value, error))

    def _frame_data_arrived(self, name: str, top: int, left: int, value, error: str) -> None:
        if value is None:
            self._show_error(f"Couldn't load {name}.", error)
            return
        data = answer(value)
        writes = sheet_writes(data, top, left)
        height, width = len(data["rows"]) + 1, len(data["columns"])
        self.model.ensure_size(top + height, left + width)
        self.model.set_cells(writes, "Load Data")
        self.view.select_range(top, left, top + height - 1, left + max(width, 1) - 1)
        rows = height - 1
        self._show_status(f"Loaded {name} at {cell_name(top, left)}: {rows:,} row{'s' if rows != 1 else ''} "
                          f"× {width} column{'s' if width != 1 else ''}, with its column names above.")

    def _ask_frame_to_load(self, found: list[tuple[str, int, int]], cell: str) -> str | None:
        """The Load Data to Sheet dialog: the chosen DataFrame's name, or None if cancelled."""
        dialog = LoadDataDialog(self, found, cell)
        return dialog.chosen() if dialog.exec() == QDialog.Accepted else None

    def _ask_notebook(self, code: str, expression: str, done) -> None:
        """Quietly evaluate `expression` (after `code`) in the notebook's Python;
        done(its repr or None, why not) when the answer comes."""
        if self._evaluating_with is not self.kernel:
            self.kernel.evaluated.connect(self._on_evaluated)
            self._evaluating_with = self.kernel
        request_id = uuid.uuid4().hex
        self._evaluations[request_id] = done
        self.kernel.evaluate(request_id, code, expression)

    def _on_evaluated(self, request_id: str, value, error: str) -> None:
        done = self._evaluations.pop(request_id, None)
        if done is not None:
            done(value, error)

    def _run_in_notebook(self, sources: list[str], needed=()) -> list[str]:
        """Open the notebook, add cells with these sources at its end, and
        run them in order, after any `needed` cells (such as the imports) that
        haven't run in this Python process. Returns their ids."""
        window = self.show_notebook()
        if window.current_id is not None:
            window.set_current(self.notebook.cells[-1].id)  # new cells go at the end
        window.run_needed(needed)
        ids = []
        for source in sources:
            ids.append(window.add_cell_below(source))
            window.run_cell(ids[-1])
        return ids

    def _on_undo_text(self, text: str):
        self.undo_action.setText(f"Undo {text}".strip())

    def _on_redo_text(self, text: str):
        self.redo_action.setText(f"Redo {text}".strip())

    def insert_cells(self) -> bool:
        """Ask which way to shift, then insert blank cells in place of the
        selection; or, with whole rows or columns selected, insert rows or
        columns."""
        self._commit_pending_edit()
        lines = self.view.whole_lines()
        if lines is not None:
            return self.insert_lines(*lines)
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

    def insert_lines(self, kind: str, indexes: list[int]) -> bool:
        """Insert blank "rows" or "columns" before each run of the ones given
        (as many as there are in the run), moving the rest down or right with
        their widths or heights, as one undo step. The new ones are selected."""
        self._commit_pending_edit()
        noun = kind[:-1] if len(indexes) == 1 else kind
        header = self.view.horizontalHeader() if kind == "columns" else self.view.verticalHeader()
        before = _section_ratios(header)
        blocks = runs(indexes)
        stack = self.model.undo_stack
        stack.beginMacro(f"Insert {noun.capitalize()}")
        for start, count in reversed(blocks):  # from the end, so the others don't move first
            if kind == "columns":
                self.model.insert_columns(start, count)
            else:
                self.model.insert_rows(start, count)
        after = [1.0] * header.count()  # the new ones at the default size
        for old, ratio in enumerate(before):
            new = old + sum(count for start, count in blocks if start <= old)
            if new < len(after):
                after[new] = ratio
        stack.push(_SectionSizesCommand(header, before, after))
        stack.endMacro()
        inserted, moved = [], 0
        for start, count in blocks:
            inserted += range(start + moved, start + moved + count)
            moved += count
        self.view.select_lines(kind, inserted)
        self._show_status(f"Inserted {len(indexes)} blank {noun}.")
        return True

    def _update_line_actions(self, *_args) -> None:
        """Insert Cells… and Delete Cells… become Insert Columns and Delete
        Columns (or Rows) for whole columns (or rows)."""
        lines = self.view.whole_lines()
        if lines is None:
            insert, delete = "Insert Cells…", "Delete Cells…"
        else:
            kind, indexes = lines
            noun = (kind[:-1] if len(indexes) == 1 else kind).capitalize()
            insert, delete = f"Insert {noun}", f"Delete {noun}"
        self.insert_cells_action.setText(insert)
        self.delete_cells_action.setText(delete)

    def delete_lines(self, kind: str, indexes: list[int]) -> bool:
        """Delete whole "rows" or "columns", moving the rest up or left with
        their heights or widths, as one undo step. What moved into their place
        is selected."""
        self._commit_pending_edit()
        noun = kind[:-1] if len(indexes) == 1 else kind
        header = self.view.horizontalHeader() if kind == "columns" else self.view.verticalHeader()
        before = _section_ratios(header)
        blocks = runs(indexes)
        stack = self.model.undo_stack
        stack.beginMacro(f"Delete {noun.capitalize()}")
        for start, count in reversed(blocks):  # from the end, so the others don't move first
            if kind == "columns":
                self.model.delete_columns(start, count)
            else:
                self.model.delete_rows(start, count)
        gone = set(indexes)
        after = [ratio for i, ratio in enumerate(before) if i not in gone]
        after += [1.0] * (header.count() - len(after))  # the sheet keeps its size
        stack.push(_SectionSizesCommand(header, before, after))
        stack.endMacro()
        selected, removed = [], 0
        for start, count in blocks:
            selected += range(start - removed, start - removed + count)
            removed += count
        self.view.select_lines(kind, selected)
        self._show_status(f"Deleted {len(indexes)} {noun}.")
        return True

    def _ask_insert_shift(self, problems: dict[str, str]) -> str | None:
        return ask_shift(InsertCellsDialog, self, self.insert_shift, problems)

    def delete_cells(self) -> bool:
        """Ask which way to shift, then delete the selected cells and close the
        gap; or, with whole rows or columns selected, delete them."""
        self._commit_pending_edit()
        lines = self.view.whole_lines()
        if lines is not None:
            return self.delete_lines(*lines)
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
        self._remember_recent(path)
        return True

    def open_document(self, path: str) -> bool:
        """A sheet the Finder opens here (a .ezs double-clicked, or dropped on
        the app): in this window, as File > Open does, once its changes are
        saved or discarded. The sheet it has open already is just brought
        to the front."""
        self.raise_()
        self.activateWindow()
        if self.file_path and os.path.exists(path) and os.path.samefile(self.file_path, path):
            return True
        if not self.maybe_save():
            return False
        return self.open_path(path)

    def open_recent(self, path: str) -> bool:
        """Open a sheet from File > Open Recent. One that's no longer there is
        taken off the list."""
        if not self.maybe_save():
            return False
        if not os.path.isfile(path):
            self._show_error("Couldn't open the sheet.",
                             f"{path} isn't there anymore. It may have been moved, renamed, or deleted, "
                             "so it's been taken off Open Recent.")
            remove_recent_file(path)
            self._update_recent_menu()
            return False
        return self.open_path(path)

    def clear_recent(self) -> None:
        clear_recent_files()
        self._update_recent_menu()

    def _remember_recent(self, path: str) -> None:
        add_recent_file(path)
        self._update_recent_menu()

    def _update_recent_menu(self) -> None:
        """List the recent sheets, newest first, then Clear Menu."""
        menu = self.recent_menu
        menu.clear()
        paths = recent_files()
        for path, label in zip(paths, menu_labels(paths)):
            action = menu.addAction(label.replace("&", "&&"))  # a lone & would underline the next letter
            action.setToolTip(path)
            action.triggered.connect(lambda _checked=False, p=path: self.open_recent(p))
        if paths:
            menu.addSeparator()
        clear = menu.addAction("Clear Menu")
        clear.setEnabled(bool(paths))
        clear.triggered.connect(lambda _checked=False: self.clear_recent())

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
        sheet = self.model.sheet_data()
        sheet.notebook = None if self.notebook.is_empty else self.notebook.to_json()
        try:
            save_sheet(path, sheet)
        except SheetFileError as e:
            self._show_error("Couldn't save the sheet.", str(e))
            return False
        self._set_file_path(path)
        self.model.undo_stack.setClean()
        self._notebook_dirty = False
        self.setWindowModified(False)
        self._remember_recent(path)
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
            self.kernel.shutdown()  # no Python process outlives the sheet
            if self.notebook_window is not None:
                self.notebook_window.hide()  # it belongs to the sheet
            event.accept()
        else:
            event.ignore()

    def _load(self, sheet: SheetData, path: str | None) -> None:
        self.clipboard.cancel()
        self.autosum.cancel()
        self.kernel.shutdown()  # the old sheet's Python variables go with it
        self.notebook.load(sheet.notebook)  # (its cells aren't run until asked)
        self._notebook_dirty = False
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
        self.setWindowTitle(f"{name}[*] — EZ Sheet")
        self.kernel.working_dir = kernel_folder(path)  # notebook code's relative paths start here
        if self.notebook_window is not None:
            self.notebook_window.set_sheet_name(name)

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
        name = self.model.alias_of(index.row(), index.column())
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


def _block_name(cells) -> str:
    """The block holding the (row, col) cells, such as A1:C4."""
    rows, cols = [row for row, _ in cells], [col for _, col in cells]
    return f"{cell_name(min(rows), min(cols))}:{cell_name(max(rows), max(cols))}"


def _cells(count: int, what: str = "cell") -> str:
    """"1 cell", "3 cells"."""
    return f"{count} {what}{'' if count == 1 else 's'}"


def _unread_note(unread, name: str) -> str:
    """What a rename says of the cells using `name` it couldn't read (and so left as they are)."""
    if not unread:
        return ""
    still = "it still says" if len(unread) == 1 else "they still say"
    return (f" {_cells(len(unread))} using {name} couldn't be read as Python (such as one with a %magic), "
            f"so {still} {name}.")


class _SizeBox(QComboBox):
    """The font size box: as wide as two digits, a little room, and its
    arrow (in its font, so it zooms with the toolbar), not a combo box's
    usual width. (A three-digit size scrolls as it's typed.)"""

    def sizeHint(self):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        text = QSize(self.fontMetrics().horizontalAdvance("00") + 2, self.fontMetrics().height())
        return self.style().sizeFromContents(QStyle.CT_ComboBox, option, text, self).expandedTo(
            QSize(0, super().sizeHint().height()))

    def minimumSizeHint(self):
        return self.sizeHint()


def _decimals_icon(digits: str, left: bool, color, ratio: float = 2.0) -> QIcon:
    """Google Sheets' icon for fewer (.0 with ← under it) or more (.00 with
    →) decimal places."""
    width, height = 32, 28
    pixmap = QPixmap(round(width * ratio), round(height * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    font = QFont()
    font.setPixelSize(18)  # (regular weight, as the % and 123 beside it are)
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(0, -2, width, 19, Qt.AlignHCenter | Qt.AlignTop, digits)
    pen = QPen(color, 1.3)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    y, start, end = 23.5, width / 2 - 2, width / 2 + 11  # under the digits' right side
    tip, tail = (start, end) if left else (end, start)
    painter.drawLine(QPointF(tail, y), QPointF(tip, y))
    head = 4.0 if left else -4.0
    painter.drawLine(QPointF(tip, y), QPointF(tip + head, y - 3.5))
    painter.drawLine(QPointF(tip, y), QPointF(tip + head, y + 3.5))
    painter.end()
    return QIcon(pixmap)
