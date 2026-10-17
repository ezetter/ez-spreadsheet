"""Dialogs for names: naming a cell or a column, and the list of all names."""

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
from .references import cell_name, column_index, column_name, parse_cell_name

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
        intro = QLabel(f"Name for {cell_name(row, col)}" + (f" (now {value})" if value else "")
                       + ", for use in formulas, such as =PI*r^2:")
        intro.setWordWrap(True)
        layout.addWidget(intro)
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
                self.show_note(f"OK removes the name {self.current}; formulas using it will then mean "
                               f"{names.unnamed_meaning(self.current)}.", error=False)
            else:
                self.show_note("Enter a name.", error=True)
            return
        problem = self.model.name_problem(text, self.cell)
        if problem:
            self.show_note(problem, error=True)
        elif self.current and names.key(text) != names.key(self.current):
            self.show_note(f"Renames {self.current}. Formulas using {self.current} will then mean "
                           f"{names.unnamed_meaning(self.current)} until changed to {text}.", error=False)
        else:
            self.show_note("", error=False)

    def chosen_name(self) -> str:
        return self.name.text().strip()


class NameColumnDialog(_NoteDialog):
    """Name a column, so name1, name2, ... mean its cells. Starts with its
    current name; clearing it removes the name."""

    def __init__(self, model, col: int, parent=None):
        super().__init__(parent)
        self.model, self.col = model, col
        self.current = model.column_name_of(col)
        letters = column_name(col)
        self.setWindowTitle(f"Name Column {letters}")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        intro = QLabel(f"Name for column {letters}. With the name t, formulas can use t1 for "
                       f"${letters}1, t2 for ${letters}2, and so on; filling or copying a formula "
                       "down moves to the next row's cell (t1 becomes t2).")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.name = QLineEdit(self.current or "")
        self.name.setPlaceholderText("A name such as t or price (not ending in a digit)")
        self.name.textChanged.connect(self.update_state)
        layout.addWidget(self.name)
        self._make_note_and_buttons(layout)
        self.update_state()

    def update_state(self, *_args) -> None:
        text = self.name.text().strip()
        if not text:
            if self.current:
                meaning = names.unnamed_meaning(f"{self.current}1")
                then = (f"mean cells {self.current.upper()}1, {self.current.upper()}2, …"
                        if meaning.startswith("cell") else f"show {meaning}")
                self.show_note(f"OK removes the name {self.current}; formulas using "
                               f"{self.current}1, {self.current}2, … will then {then}.", error=False)
            else:
                self.show_note("Enter a name.", error=True)
            return
        problem = self.model.column_name_problem(text, self.col)
        if problem:
            self.show_note(problem, error=True)
        else:
            letters = column_name(self.col)
            self.show_note(f"{text}1 will mean ${letters}1, {text}2 ${letters}2, and so on.", error=False)

    def chosen_name(self) -> str:
        return self.name.text().strip()


class NamesDialog(_NoteDialog):
    """Every cell and column name, to rename, point at another cell or
    column, add, or delete. Changes apply together when OK is clicked."""

    NAME, CELL, VALUE = range(3)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Names")
        self.resize(520, 400)
        layout = QVBoxLayout(self)
        intro = QLabel("Formulas can use these names in place of cell references. A name for a cell "
                       "(such as B2) means that cell; a name for a column (such as C:C), say t, "
                       "makes t1, t2, … mean its cells. Edit a name or what it refers to to change it.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Refers To", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)
        for name, cell in model.cell_names().items():
            self._add_row(name, cell_name(*cell) if cell else DELETED)
        for name, col in model.column_names().items():
            letters = column_name(col)
            self._add_row(name, f"{letters}:{letters}")
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
        target = self._target(self.table.item(row, self.CELL).text())
        if isinstance(target, tuple):
            text = self.model.display_text(*target)
        elif isinstance(target, int) and not isinstance(target, bool):
            text = f"Column {column_name(target)}"
        else:
            text = ""
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

    def _target(self, text: str):
        """What a Refers To entry names: a (row, col) cell, a column index
        (written C:C, or just C), None for a deleted cell, or False if it's
        neither."""
        text = text.strip().replace("$", "")
        if text.upper() == DELETED:
            return None
        first, colon, last = text.partition(":")
        if (colon and first.upper() == last.upper() or not colon) and first.isalpha() and first.isascii():
            return column_index(first)
        try:
            row, col = parse_cell_name(text)
        except ValueError:
            return False
        return (row, col) if row >= 0 else False

    def _read(self):
        """({name: cell}, {name: column}) from the table, or a message saying
        what's wrong."""
        cells, columns = {}, {}
        for row in range(self.table.rowCount()):
            name = self.table.item(row, self.NAME).text().strip()
            target = self._target(self.table.item(row, self.CELL).text())
            problem = names.syntax_problem(name)
            if problem:
                return f"Row {row + 1}: {problem}"
            if target is False:
                return f"{name}: enter what it refers to, a cell such as B2 or a column such as C:C."
            if name in cells or name in columns:
                return f"{name} is used twice. Each name can name only one thing."
            if isinstance(target, int) and not isinstance(target, bool):
                columns[name] = target
            else:
                cells[name] = target
        return names.conflict(cells, columns) or (cells, columns)

    def update_state(self, *_args) -> None:
        result = self._read()
        if isinstance(result, str):
            self.show_note(result, error=True)
        elif any(cell is None for cell in result[0].values()):
            self.show_note(f"Names showing {DELETED} name cells that were deleted. "
                           "Give them a cell, or delete them.", error=False)
        else:
            self.show_note("", error=False)

    def chosen_names(self) -> tuple[dict, dict]:
        """The cell names ({name: cell}) and column names ({name: column})."""
        result = self._read()
        return result if isinstance(result, tuple) else ({}, {})
