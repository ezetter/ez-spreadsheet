"""Sheet data model: sparse storage of raw cell text behind a Qt table model."""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

DEFAULT_ROWS = 1000
DEFAULT_COLS = 52


def column_name(col: int) -> str:
    """Convert a zero-based column index to a spreadsheet letter name (0 -> A, 26 -> AA)."""
    name = ""
    col += 1
    while col:
        col, rem = divmod(col - 1, 26)
        name = chr(ord("A") + rem) + name
    return name


def cell_name(row: int, col: int) -> str:
    """Zero-based (row, col) to an A1-style reference."""
    return f"{column_name(col)}{row + 1}"


class SheetModel(QAbstractTableModel):
    """Holds the raw text of each non-empty cell, keyed by (row, col)."""

    def __init__(self, rows: int = DEFAULT_ROWS, cols: int = DEFAULT_COLS, parent=None):
        super().__init__(parent)
        self._rows = rows
        self._cols = cols
        self._cells: dict[tuple[int, int], str] = {}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._rows

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._cols

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.DisplayRole, Qt.EditRole):
            return self._cells.get((index.row(), index.column()), "")
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
        return self._cells.get((row, col), "")

    def set_cell(self, row: int, col: int, value) -> None:
        text = "" if value is None else str(value)
        key = (row, col)
        if text:
            if self._cells.get(key) == text:
                return
            self._cells[key] = text
        elif key in self._cells:
            del self._cells[key]
        else:
            return
        index = self.index(row, col)
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])

    def clear_cells(self, indexes) -> None:
        for index in indexes:
            self.set_cell(index.row(), index.column(), "")
