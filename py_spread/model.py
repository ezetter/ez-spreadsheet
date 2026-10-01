"""Sheet data model: sparse storage of raw cell text behind a Qt table model."""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal

from .formula import (
    CIRCULAR_ERROR,
    REF_ERROR,
    VALUE_ERROR,
    CellError,
    FormulaError,
    evaluate,
    format_number,
    is_formula,
    parse,
    parse_number,
    references,
)
from .references import column_name
from .storage import SheetData

DEFAULT_ROWS = 1000
DEFAULT_COLS = 52


class SheetModel(QAbstractTableModel):
    """Holds the raw text of each non-empty cell, keyed by (row, col).

    Qt's EditRole is the raw text (e.g. "=A1+2"); DisplayRole is the computed value.
    """

    # Emitted when cell contents are edited (not when a whole sheet is loaded).
    contents_changed = Signal()

    def __init__(self, rows: int = DEFAULT_ROWS, cols: int = DEFAULT_COLS, parent=None):
        super().__init__(parent)
        self._rows = rows
        self._cols = cols
        self._cells: dict[tuple[int, int], str] = {}
        self._formula_keys: set[tuple[int, int]] = set()
        # Parsed formulas, as (ast or CellError, referenced cells).
        self._parsed: dict[tuple[int, int], tuple] = {}
        # Computed values: float, str, or CellError. Cleared on every edit.
        self._values: dict[tuple[int, int], object] = {}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._rows

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._cols

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if role == Qt.EditRole:
            return self.get_cell(row, col)
        if role == Qt.DisplayRole:
            return self.display_text(row, col)
        if role == Qt.TextAlignmentRole:
            if isinstance(self.value(row, col), float):
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or role != Qt.EditRole:
            return False
        self.set_cell(index.row(), index.column(), value)
        return True

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return column_name(section)
        return str(section + 1)

    def get_cell(self, row: int, col: int) -> str:
        """The raw text as entered."""
        return self._cells.get((row, col), "")

    def set_cell(self, row: int, col: int, value) -> None:
        self.set_cells({(row, col): value})

    def set_cells(self, writes: dict[tuple[int, int], object]) -> None:
        """Set many cells at once, recalculating and notifying views a single time."""
        changed = [key for key, value in writes.items() if self._store(key, value)]
        if not changed:
            return
        self._values.clear()
        self.contents_changed.emit()
        if self._formula_keys:
            # Any formula might depend on these cells, so refresh the whole sheet.
            self.dataChanged.emit(self.index(0, 0), self.index(self._rows - 1, self._cols - 1))
        else:
            rows = [row for row, _ in changed]
            cols = [col for _, col in changed]
            self.dataChanged.emit(self.index(min(rows), min(cols)), self.index(max(rows), max(cols)))

    def _store(self, key, value) -> bool:
        """Store one cell's raw text; returns whether it changed."""
        text = "" if value is None else str(value)
        if text:
            if self._cells.get(key) == text:
                return False
            self._cells[key] = text
        elif key in self._cells:
            del self._cells[key]
        else:
            return False
        if is_formula(text):
            self._formula_keys.add(key)
        else:
            self._formula_keys.discard(key)
        self._parsed.pop(key, None)
        return True

    def sheet_data(self) -> SheetData:
        return SheetData(self._rows, self._cols, dict(self._cells))

    def load_sheet_data(self, sheet: SheetData) -> None:
        """Replace the whole sheet, including its size."""
        self.beginResetModel()
        self._rows = sheet.rows
        self._cols = sheet.cols
        self._cells = {key: text for key, text in sheet.cells.items() if text}
        self._formula_keys = {key for key, text in self._cells.items() if is_formula(text)}
        self._parsed.clear()
        self._values.clear()
        self.endResetModel()

    def clear_cells(self, indexes) -> None:
        self.set_cells({(index.row(), index.column()): "" for index in indexes})

    def display_text(self, row: int, col: int) -> str:
        raw = self.get_cell(row, col)
        if not is_formula(raw):
            return raw
        value = self.value(row, col)
        return format_number(value) if isinstance(value, float) else str(value)

    def value(self, row: int, col: int):
        """The computed value: None (empty), float, str, or CellError."""
        key = (row, col)
        if key in self._values:
            return self._values[key]
        raw = self._cells.get(key)
        if raw is None:
            return None
        if key in self._formula_keys:
            self._compute(key)
        else:
            number = parse_number(raw)
            self._values[key] = raw if number is None else number
        return self._values[key]

    def _parse(self, key):
        if key not in self._parsed:
            try:
                ast = parse(self._cells[key][1:])
                self._parsed[key] = (ast, references(ast))
            except FormulaError as e:
                self._parsed[key] = (CellError(e.code), set())
        return self._parsed[key]

    def _compute(self, root) -> None:
        """Evaluate a formula cell, first evaluating the formulas it depends on.

        Uses an explicit stack rather than recursion so long dependency chains
        can't overflow Python's recursion limit. A dependency that is already
        being evaluated further up the stack means a circular reference.
        """
        stack = [root]
        in_progress = set()
        while stack:
            key = stack[-1]
            if key in self._values:
                stack.pop()
                in_progress.discard(key)
                continue
            _, refs = self._parse(key)
            pending = [r for r in refs if r in self._formula_keys and r not in self._values]
            if any(r in in_progress for r in pending):
                self._values[key] = CellError(CIRCULAR_ERROR)
            elif pending and key not in in_progress:
                in_progress.add(key)
                stack.extend(pending)
                continue
            else:
                self._values[key] = self._evaluate(key)
            stack.pop()
            in_progress.discard(key)

    def _evaluate(self, key):
        ast, _ = self._parse(key)
        if isinstance(ast, CellError):
            return ast
        try:
            return evaluate(ast, self._lookup)
        except FormulaError as e:
            return CellError(e.code)

    def _lookup(self, row: int, col: int) -> float:
        if not (0 <= row < self._rows and 0 <= col < self._cols):
            raise FormulaError(REF_ERROR)
        value = self.value(row, col)
        if value is None:
            return 0.0
        if isinstance(value, float):
            return value
        if isinstance(value, CellError):
            raise FormulaError(value.code)
        raise FormulaError(VALUE_ERROR)
