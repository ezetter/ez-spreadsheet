"""Dialogs for cell names: naming one cell, and the list of all names."""

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from PySide6.QtCore import Qt

from . import names
from .appearance import error_color
from .references import cell_name, parse_cell_name

DELETED = "#REF!"  # shown as the cell of a name whose cell was deleted


class _NoteDialog(QDialog):
    """A dialog with a note line that shows problems and turns OK off."""

    def _make_note_and_buttons(self, layout):
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def show_note(self, text: str, error: bool) -> None:
        self.note.setText(text)
        self.note.setStyleSheet(f"color: {error_color(self.palette())};" if error else "")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(not error)


class NameCellDialog(_NoteDialog):
    """Name one cell. Starts with its current name; clearing it removes the name."""

    def __init__(self, model, row: int, col: int, parent=None):
        super().__init__(parent)
        self.model, self.cell = model, (row, col)
        self.current = model.name_of(row, col)
        self.setWindowTitle(f"Name Cell {cell_name(row, col)}")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        value = model.display_text(row, col)
        layout.addWidget(QLabel(f"Name for {cell_name(row, col)}" + (f" (now {value})" if value else "")
                                + ", for use in formulas, such as =PI*r^2:"))
        self.name = QLineEdit(self.current or "")
        self.name.setPlaceholderText("A name such as r or tax_rate")
        self.name.textChanged.connect(self.update_state)
        layout.addWidget(self.name)
        self._make_note_and_buttons(layout)
        self.update_state()

    def update_state(self, *_args) -> None:
        text = self.name.text().strip()
        if not text:
            if self.current:
                self.show_note(f"OK removes the name {self.current}; formulas using it will show #NAME?.",
                               error=False)
            else:
                self.show_note("Enter a name.", error=True)
            return
        problem = self.model.name_problem(text, self.cell)
        if problem:
            self.show_note(problem, error=True)
        elif self.current and names.key(text) != names.key(self.current):
            self.show_note(f"Renames {self.current}. Formulas using {self.current} will show #NAME? "
                           f"until changed to {text}.", error=False)
        else:
            self.show_note("", error=False)

    def chosen_name(self) -> str:
        return self.name.text().strip()


class NamesDialog(_NoteDialog):
    """Every cell name, to rename, point at another cell, add, or delete.
    Changes apply together when OK is clicked."""

    NAME, CELL, VALUE = range(3)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Cell Names")
        self.resize(480, 380)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Formulas can use these names in place of cell references. "
                                "Edit a name or its cell to change it."))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Cell", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)
        for name, cell in model.cell_names().items():
            self._add_row(name, cell_name(*cell) if cell else DELETED)
        self.table.itemChanged.connect(self._on_edit)

        row_buttons = QHBoxLayout()
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self.add_name)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_selected)
        row_buttons.addWidget(self.add_button)
        row_buttons.addWidget(self.delete_button)
        row_buttons.addStretch()
        layout.addLayout(row_buttons)
        self._make_note_and_buttons(layout)
        self.update_state()

    def _add_row(self, name: str, cell_text: str) -> int:
        row = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(row)
        self.table.setItem(row, self.NAME, QTableWidgetItem(name))
        self.table.setItem(row, self.CELL, QTableWidgetItem(cell_text))
        value = QTableWidgetItem()
        value.setFlags(value.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, self.VALUE, value)
        self.table.blockSignals(False)
        self._show_value(row)
        return row

    def _show_value(self, row: int) -> None:
        cell = self._cell(self.table.item(row, self.CELL).text())
        text = self.model.display_text(*cell) if isinstance(cell, tuple) else ""
        self.table.blockSignals(True)
        self.table.item(row, self.VALUE).setText(text)
        self.table.blockSignals(False)

    def add_name(self) -> None:
        row = self._add_row("", "")
        self.table.setCurrentCell(row, self.NAME)
        self.table.editItem(self.table.item(row, self.NAME))
        self.update_state()

    def delete_selected(self) -> None:
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)
        self.update_state()

    def _on_edit(self, item) -> None:
        if item.column() == self.CELL:
            self._show_value(item.row())
        self.update_state()

    def _cell(self, text: str):
        """The (row, col) a Cell entry names, None for a deleted cell, or
        False if it isn't a cell name."""
        text = text.strip()
        if text.upper() == DELETED:
            return None
        try:
            row, col = parse_cell_name(text.replace("$", ""))
        except ValueError:
            return False
        return (row, col) if row >= 0 else False

    def _read(self):
        """{name: cell} from the table, or a message saying what's wrong."""
        result, by_key, by_cell = {}, {}, {}
        for row in range(self.table.rowCount()):
            name = self.table.item(row, self.NAME).text().strip()
            cell_text = self.table.item(row, self.CELL).text().strip()
            problem = names.syntax_problem(name)
            if problem:
                return f"Row {row + 1}: {problem}"
            cell = self._cell(cell_text)
            if cell is False:
                return f"{name}: enter its cell, such as B2."
            if names.key(name) in by_key:
                return f"{name} is used twice. Each name can name only one cell."
            if cell is not None and cell in by_cell:
                return f"{cell_name(*cell)} has two names, {by_cell[cell]} and {name}. A cell can have only one."
            by_key[names.key(name)] = name
            if cell is not None:
                by_cell[cell] = name
            result[name] = cell
        return result

    def update_state(self, *_args) -> None:
        result = self._read()
        if isinstance(result, str):
            self.show_note(result, error=True)
        elif any(cell is None for cell in result.values()):
            self.show_note(f"Names showing {DELETED} name cells that were deleted. "
                           "Give them a cell, or delete them.", error=False)
        else:
            self.show_note("", error=False)

    def chosen_names(self) -> dict:
        result = self._read()
        return result if isinstance(result, dict) else {}
