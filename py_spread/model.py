"""Sheet data model: sparse storage of raw cell text and number formats behind
a Qt table model, plus the unit its trig functions take angles in."""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QFont, QUndoCommand, QUndoStack

from .formula import (
    CIRCULAR_ERROR,
    REF_ERROR,
    CellError,
    FormulaError,
    evaluate,
    format_number,
    is_formula,
    move_references,
    ordered_references,
    parse,
    parse_number,
    references,
)
from .functions import DEGREES
from . import names
from .numformat import NumberFormat, format_value, parse_formatted
from .textstyle import PLAIN, CellStyle
from .references import cell_name, column_name
from .storage import SheetData

SHIFTS = ("down", "right", "up", "left")
DEFAULT_ROWS = 1000
DEFAULT_COLS = 52
UNDO_LIMIT = 1000


class _CellsCommand(QUndoCommand):
    """One undoable change: the raw text, number formats, and text styles of
    some cells, and cell and column names, before and after, each as a
    (texts, formats, styles, names, columns) tuple of dicts."""

    def __init__(self, model, before: tuple, after: tuple, description: str):
        super().__init__(description)
        self.model = model
        self.before = before
        self.after = after
        self._done = False

    def redo(self):
        # QUndoStack.push calls redo() to make the change in the first place;
        # only later calls are redos the user asked for.
        self.model._apply(*self.after, from_history=self._done)
        self._done = True

    def undo(self):
        self.model._apply(*self.before, from_history=True)


class _AngleUnitCommand(QUndoCommand):
    """One undoable switch of the unit SIN, COS, and TAN take angles in."""

    def __init__(self, model, unit: str):
        super().__init__(f"Angles in {unit.capitalize()}")
        self.model = model
        self.before = model.angle_unit
        self.after = unit

    def redo(self):
        self.model._apply_angle_unit(self.after)

    def undo(self):
        self.model._apply_angle_unit(self.before)


class SheetModel(QAbstractTableModel):
    """Holds the raw text of each non-empty cell, keyed by (row, col), and each
    cell's explicit number format and text style, if it has them.

    Qt's EditRole is the raw text (e.g. "=A1+2"); DisplayRole is the computed
    value, formatted.
    """

    # Emitted when cell contents are edited (not when a whole sheet is loaded).
    contents_changed = Signal()
    # Emitted when cell names are added, changed, or removed (or a sheet is loaded).
    names_changed = Signal()
    # Emitted with the (row, col) cells an undo or redo changed.
    history_applied = Signal(list)
    # Emitted with the angle unit when it's switched or a sheet is loaded.
    angle_unit_changed = Signal(str)

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
        # Explicit number formats, set from the Format menu.
        self._formats: dict[tuple[int, int], NumberFormat] = {}
        # Bold and italic, for cells that aren't plain.
        self._styles: dict[tuple[int, int], CellStyle] = {}
        # Cell names, by names.key(name): (the name as typed, the (row, col) it
        # names, or None if that cell was deleted).
        self._names: dict[str, tuple[str, tuple[int, int] | None]] = {}
        # Column names: name -> column index. With column C named t, t5 means $C5.
        self._column_names: dict[str, int] = {}
        # Formats formula cells take from the cells they refer to. Cleared on every edit.
        self._inferred_formats: dict[tuple[int, int], NumberFormat | None] = {}
        # What SIN, COS, and TAN take angles in: DEGREES or RADIANS.
        self._angle_unit = DEGREES
        self._formula_sheet = _FormulaSheet(self)
        # Every edit goes through set_cells and lands here as one undo step.
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(UNDO_LIMIT)

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
        if role == Qt.FontRole:
            style = self._styles.get((row, col))
            if style is None:
                return None
            font = QFont()
            font.setBold(style.bold)
            font.setItalic(style.italic)
            return font
        if role == Qt.TextAlignmentRole:
            if isinstance(self.value(row, col), float):
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or role != Qt.EditRole:
            return False
        self.set_cell(index.row(), index.column(), value, "Typing")
        return True

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            name = self.column_name_of(section)
            return f"{column_name(section)} ({name})" if name else column_name(section)
        return str(section + 1)

    def get_cell(self, row: int, col: int) -> str:
        """The raw text as entered."""
        return self._cells.get((row, col), "")

    def set_cell(self, row: int, col: int, value, description: str = "Edit") -> None:
        self.set_cells({(row, col): value}, description)

    def set_cells(self, writes: dict[tuple[int, int], object], description: str = "Edit",
                  formats: dict[tuple[int, int], NumberFormat | None] | None = None,
                  styles: dict[tuple[int, int], CellStyle | None] | None = None,
                  names: dict[str, tuple | None] | None = None,
                  columns: dict[str, int | None] | None = None) -> None:
        """Set many cells' text, and optionally their number formats and text
        styles, and cell names (each keyed by names.key(name), as (name,
        cell) entries), and column names (name -> column index), where None
        removes one, as one undoable step,
        recalculating and notifying views a single time. `description` names
        the step in the Undo menu."""
        before, after = {}, {}
        for key, value in writes.items():
            text = "" if value is None else str(value)
            old = self._cells.get(key, "")
            if text != old:
                before[key] = old
                after[key] = text
        formats_before, formats_after = _changes(self._formats, formats)
        styles_before, styles_after = _changes(self._styles, {
            key: None if style == PLAIN else style for key, style in (styles or {}).items()})
        names_before, names_after = _changes(self._names, names)
        columns_before, columns_after = _changes(self._column_names, columns)
        if after or formats_after or styles_after or names_after or columns_after:
            self.undo_stack.push(_CellsCommand(
                self, (before, formats_before, styles_before, names_before, columns_before),
                (after, formats_after, styles_after, names_after, columns_after), description))

    def set_formats(self, formats: dict[tuple[int, int], NumberFormat | None], description: str) -> None:
        self.set_cells({}, description, formats)

    def set_styles(self, styles: dict[tuple[int, int], CellStyle | None], description: str) -> None:
        self.set_cells({}, description, styles=styles)

    def cell_style(self, row: int, col: int) -> CellStyle:
        return self._styles.get((row, col), PLAIN)

    def cell_format(self, row: int, col: int) -> NumberFormat | None:
        """The cell's explicit format, if it has one."""
        return self._formats.get((row, col))

    @property
    def angle_unit(self) -> str:
        return self._angle_unit

    def set_angle_unit(self, unit: str) -> None:
        """Switch the unit SIN, COS, and TAN take angles in, as one undoable step."""
        if unit != self._angle_unit:
            self.undo_stack.push(_AngleUnitCommand(self, unit))

    def _apply_angle_unit(self, unit: str) -> None:
        self._angle_unit = unit
        self._values.clear()
        self.angle_unit_changed.emit(unit)
        self.contents_changed.emit()
        if self._formula_keys:
            self.dataChanged.emit(self.index(0, 0), self.index(self._rows - 1, self._cols - 1))

    def _apply(self, texts: dict, formats: dict, styles: dict, names: dict, columns: dict,
               from_history: bool = False) -> None:
        changed = {key for key, text in texts.items() if self._store(key, text)}
        for table, updates in ((self._formats, formats), (self._styles, styles)):
            for key, value in updates.items():
                if table.get(key) != value:
                    if value is None:
                        del table[key]
                    else:
                        table[key] = value
                    changed.add(key)
        renamed = False
        for name_key, entry in names.items():
            old = self._names.get(name_key)
            if old != entry:
                # The cells named before and after count as changed, for selecting.
                for named in (old, entry):
                    if named is not None and named[1] is not None:
                        changed.add(named[1])
                if entry is None:
                    del self._names[name_key]
                else:
                    self._names[name_key] = entry
                renamed = True
        for name, col in columns.items():
            old = self._column_names.get(name)
            if old != col:
                for named in (old, col):
                    if named is not None:
                        changed.add((0, named))  # for selecting, the column's first cell
                        self.headerDataChanged.emit(Qt.Horizontal, named, named)
                if col is None:
                    del self._column_names[name]
                else:
                    self._column_names[name] = col
                renamed = True
        if renamed:
            self._parsed.clear()  # formulas resolve names when parsed
            self.names_changed.emit()
            if not changed:
                changed = {(0, 0)}  # a name of a deleted cell: still refresh
        if not changed:
            return
        changed = sorted(changed)
        self._values.clear()
        self._inferred_formats.clear()
        self.contents_changed.emit()
        if self._formula_keys:
            # Any formula might depend on these cells, so refresh the whole sheet.
            self.dataChanged.emit(self.index(0, 0), self.index(self._rows - 1, self._cols - 1))
        else:
            rows = [row for row, _ in changed]
            cols = [col for _, col in changed]
            self.dataChanged.emit(self.index(min(rows), min(cols)), self.index(max(rows), max(cols)))
        if from_history:
            self.history_applied.emit(changed)

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
        return SheetData(self._rows, self._cols, dict(self._cells), dict(self._formats),
                         dict(self._styles), self._angle_unit,
                         {name: cell for name, cell in self._names.values()},
                         dict(self._column_names))

    def load_sheet_data(self, sheet: SheetData) -> None:
        """Replace the whole sheet, including its size."""
        self.beginResetModel()
        self._rows = sheet.rows
        self._cols = sheet.cols
        self._cells = {key: text for key, text in sheet.cells.items() if text}
        self._formula_keys = {key for key, text in self._cells.items() if is_formula(text)}
        self._formats = dict(sheet.formats)
        self._styles = dict(sheet.styles)
        self._angle_unit = sheet.angle_unit
        self._names = {names.key(name): (name, cell) for name, cell in sheet.names.items()}
        self._column_names = dict(sheet.column_names)
        self._parsed.clear()
        self._values.clear()
        self._inferred_formats.clear()
        self.undo_stack.clear()  # a new sheet starts with no history
        self.endResetModel()
        self.angle_unit_changed.emit(self._angle_unit)
        self.names_changed.emit()

    def insert_problem(self, top: int, left: int, bottom: int, right: int, shift: str) -> str | None:
        """Why blank cells can't be inserted in place of a block with this
        shift, or None if they can. Shifting up or left fails when the block
        is at the top or left of the sheet, or when anything would be pushed
        off it; shifting down or right always works (the sheet grows)."""
        if shift == "up" and top == 0:
            return "The selection is in the first row, so there's nowhere to shift cells up to."
        if shift == "left" and left == 0:
            return "The selection is in the first column, so there's nowhere to shift cells left to."
        move = _shifter(top, left, bottom, right, shift)
        if any(min(move(*key)) < 0 for key in self._occupied()):
            edge = "top" if shift == "up" else "left"
            return f"There's no room: cells would be pushed off the {edge} of the sheet."
        return None

    def insert_cells(self, top: int, left: int, bottom: int, right: int, shift: str) -> str | None:
        """Insert blank cells in place of a block, shifting the cells there and
        beyond `shift` ("down", "right", "up", or "left") by the block's size,
        as one undoable step. Formulas follow the cells they refer to. Returns
        a message (see insert_problem) if it can't be done."""
        problem = self.insert_problem(top, left, bottom, right, shift)
        if problem:
            return problem
        move = _shifter(top, left, bottom, right, shift)
        destinations = [move(*key) for key in self._occupied()]
        if destinations:
            self.ensure_size(max(r for r, _ in destinations) + 1, max(c for _, c in destinations) + 1)
        self._rearrange(move, None, "Insert Cells")
        return None

    def delete_problem(self, top: int, left: int, bottom: int, right: int, shift: str) -> str | None:
        """Why a block can't be deleted with this shift, or None if it can. The
        cells that close the gap come from the opposite side, so there must be
        some: shifting up needs rows below the block, and so on."""
        if shift == "up" and bottom == self._rows - 1:
            return "The selection reaches the last row, so there are no cells below to shift up."
        if shift == "left" and right == self._cols - 1:
            return "The selection reaches the last column, so there are no cells to its right to shift left."
        if shift == "down" and top == 0:
            return "The selection is in the first row, so there are no cells above to shift down."
        if shift == "right" and left == 0:
            return "The selection is in the first column, so there are no cells to its left to shift right."
        return None

    def delete_cells(self, top: int, left: int, bottom: int, right: int, shift: str) -> str | None:
        """Delete a block of cells and close the gap: cells beyond it move in
        the direction of `shift` ("up": the cells below move up, and so on),
        as one undoable step. References to deleted cells become #REF!; ranges
        shrink. Returns a message (see delete_problem) if it can't be done."""
        problem = self.delete_problem(top, left, bottom, right, shift)
        if problem:
            return problem
        height, width = bottom - top + 1, right - left + 1
        vertical = shift in ("up", "down")

        def deleted(row: int, col: int) -> bool:
            return top <= row <= bottom and left <= col <= right

        def move(row: int, col: int) -> tuple[int, int] | None:
            if deleted(row, col):
                return None
            in_columns, in_rows = left <= col <= right, top <= row <= bottom
            if shift == "up" and in_columns and row > bottom:
                return row - height, col
            if shift == "left" and in_rows and col > right:
                return row, col - width
            if shift == "down" and in_columns and row < top:
                return row + height, col
            if shift == "right" and in_rows and col < left:
                return row, col + width
            return row, col

        def move_range(start, end):
            # A deleted corner moves to the nearest surviving cell inside the
            # range, so the range shrinks; it's #REF! if nothing survives.
            if deleted(*start):
                start = (bottom + 1, start[1]) if vertical else (start[0], right + 1)
            if deleted(*end):
                end = (top - 1, end[1]) if vertical else (end[0], left - 1)
            if min(end) < 0:
                return None
            new_start, new_end = move(*start), move(*end)
            axis = 0 if vertical else 1
            if new_start is None or new_end is None or new_start[axis] > new_end[axis]:
                return None
            return new_start, new_end

        self._rearrange(move, move_range, "Delete Cells")
        return None

    def _occupied(self) -> set:
        """Cells with text, a number format, or a style."""
        return set(self._cells) | set(self._formats) | set(self._styles)

    def _rearrange(self, move, move_range, description: str) -> None:
        """Move every cell (with its format and style) to move(row, col), or
        remove it if that's None, rewriting formulas to follow, as one step."""
        occupied = self._occupied()
        cells, formats, styles = {}, {}, {}
        for key, text in self._cells.items():
            if (dest := move(*key)) is not None:
                cells[dest] = (move_references(text, move, move_range, self.name_set())
                               if is_formula(text) else text)
        for table, moved in ((self._formats, formats), (self._styles, styles)):
            for key, value in table.items():
                if (dest := move(*key)) is not None:
                    moved[dest] = value
        keys = occupied | set(cells) | set(formats) | set(styles)
        # Names follow their cells; a deleted cell's name is kept, as #REF!.
        moved_names = {name_key: (name, move(*cell) if cell else None)
                       for name_key, (name, cell) in self._names.items()}
        self.set_cells(
            {key: cells.get(key, "") for key in keys},
            description,
            {key: formats.get(key) for key in keys},
            {key: styles.get(key) for key in keys},
            moved_names,
        )

    # --- Cell names ---

    def name_set(self) -> names.Names:
        """The sheet's cell and column names, as formulas see them. (`in` it
        says whether a bare reference would mean a name rather than a cell.)"""
        return names.Names({name: cell for name, cell in self._names.values()}, self._column_names)

    def reference_text(self, row: int, col: int) -> str:
        """How to write the cell in a formula: B2, or $B2 if a name is
        spelled B2 (a bare B2 would mean the name)."""
        return names.cell_text(cell_name(row, col), self.name_set())

    def cell_names(self) -> dict[str, tuple[int, int] | None]:
        """Every name, as typed, and the cell it names (None: deleted)."""
        return {name: cell for name, cell in sorted(self._names.values(), key=lambda e: e[0].upper())}

    def name_of(self, row: int, col: int) -> str | None:
        """The cell's name, if it has one."""
        return next((name for name, cell in self._names.values() if cell == (row, col)), None)

    def alias_of(self, row: int, col: int) -> str | None:
        """What a formula can call the cell other than its reference: its
        name, or else its column alias (t5 in a column named t)."""
        column = self.column_name_of(col)
        return self.name_of(row, col) or (f"{column}{row + 1}" if column else None)

    def column_names(self) -> dict[str, int]:
        """Every column name and the column it names."""
        return dict(sorted(self._column_names.items(), key=lambda item: item[0].upper()))

    def column_name_of(self, col: int) -> str | None:
        return next((name for name, named in self._column_names.items() if named == col), None)

    def name_problem(self, name: str, cell: tuple[int, int]) -> str | None:
        """Why `cell` can't be given `name`, or None if it can."""
        problem = names.syntax_problem(name)
        if problem:
            return problem
        existing = self._names.get(names.key(name))
        if existing and existing[1] != cell:
            where = cell_name(*existing[1]) if existing[1] else "a deleted cell"
            return f"{existing[0]} already names {where}."
        if name in self._column_names:
            return f"{name} already names column {column_name(self._column_names[name])}."
        cells = {other: named for other, named in self.cell_names().items() if named != cell}
        cells[name] = cell
        return names.conflict(cells, self._column_names)

    def column_name_problem(self, name: str, col: int) -> str | None:
        """Why column `col` can't be given `name`, or None if it can."""
        problem = names.column_syntax_problem(name)
        if problem:
            return problem
        if self._column_names.get(name, col) != col:
            return f"{name} already names column {column_name(self._column_names[name])}."
        existing = self._names.get(names.key(name))
        if existing:
            where = cell_name(*existing[1]) if existing[1] else "a deleted cell"
            return f"{name} already names {where}."
        columns = {other: named for other, named in self._column_names.items() if named != col}
        columns[name] = col
        return names.conflict(self.cell_names(), columns)

    def name_column(self, col: int, name: str) -> str | None:
        """Give column `col` the name, so name1, name2, ... mean its cells,
        replacing any name it had; an empty name removes its name. One
        undoable step. Returns a problem, if any."""
        name = name.strip()
        current = self.column_name_of(col)
        if name:
            problem = self.column_name_problem(name, col)
            if problem:
                return problem
        changes = {}
        if current:
            changes[current] = None
        if name:
            changes[name] = col
        description = ("Remove Column Name" if not name
                       else ("Rename Column" if current else "Name Column"))
        self.set_cells({}, description, columns=changes)
        return None

    def name_cell(self, row: int, col: int, name: str) -> str | None:
        """Give the cell `name`, replacing any name it had; an empty name
        removes its name. One undoable step. Returns a problem, if any."""
        name = name.strip()
        current = self.name_of(row, col)
        if name:
            problem = self.name_problem(name, (row, col))
            if problem:
                return problem
        changes = {}
        if current:
            changes[names.key(current)] = None
        if name:
            changes[names.key(name)] = (name, (row, col))
        description = "Remove Name" if not name else ("Rename Cell" if current else "Name Cell")
        self.set_cells({}, description, names=changes)
        return None

    def replace_names(self, new_names: dict[str, tuple[int, int] | None], description: str,
                      new_columns: dict[str, int] | None = None) -> None:
        """Make the sheet's cell names exactly `new_names` (name -> cell), and
        its column names `new_columns` (name -> column index) if given, as one
        undoable step. The caller checks them first (see names.conflict)."""
        changes = {name_key: None for name_key in self._names}
        changes.update({names.key(name): (name, cell) for name, cell in new_names.items()})
        column_changes = None
        if new_columns is not None:
            column_changes = {name: None for name in self._column_names}
            column_changes.update(new_columns)
        self.set_cells({}, description, names=changes, columns=column_changes)

    def ensure_size(self, rows: int, cols: int) -> None:
        """Grow the sheet, if needed, to at least `rows` by `cols`."""
        if rows > self._rows:
            self.beginInsertRows(QModelIndex(), self._rows, rows - 1)
            self._rows = rows
            self.endInsertRows()
        if cols > self._cols:
            self.beginInsertColumns(QModelIndex(), self._cols, cols - 1)
            self._cols = cols
            self.endInsertColumns()

    def displayed_rows(self) -> list[list[str]]:
        """What each cell shows, from A1 to the last non-empty row and column."""
        if not self._cells:
            return []
        bottom = max(row for row, _ in self._cells)
        right = max(col for _, col in self._cells)
        return [[self.display_text(r, c) for c in range(right + 1)] for r in range(bottom + 1)]

    def clear_cells(self, indexes) -> None:
        self.set_cells({(index.row(), index.column()): "" for index in indexes}, "Clear")

    def display_text(self, row: int, col: int) -> str:
        raw = self.get_cell(row, col)
        value = self.value(row, col)
        if not isinstance(value, float):
            return str(value) if is_formula(raw) else raw
        fmt = self._formats.get((row, col))
        if fmt is None and not is_formula(raw):
            return raw  # typed numbers show as typed, e.g. $1,234.50
        fmt = fmt or self.number_format(row, col)
        return format_value(value, fmt) if fmt else format_number(value)

    def number_format(self, row: int, col: int) -> NumberFormat | None:
        """The format the cell's number is shown with: its explicit format;
        else the one it was typed with ($1,234.50 is currency with 2 decimals);
        else, for a formula, the format of the first formatted cell it refers
        to, so =SUM(A1:A9) over dollar amounts shows dollars. None means general."""
        return self._shown_format((row, col), set())

    def _shown_format(self, key, seen: set) -> NumberFormat | None:
        explicit = self._formats.get(key)
        if explicit is not None:
            return explicit
        raw = self._cells.get(key)
        if raw is None:
            return None
        if key not in self._formula_keys:
            typed = parse_formatted(raw)
            return typed[1] if typed else None
        if key in self._inferred_formats:
            return self._inferred_formats[key]
        if key in seen or len(seen) > 100:
            return None  # circular, or a very long chain of formulas
        seen.add(key)
        inferred = None
        ast = self._parse(key)[0]
        if not isinstance(ast, CellError):
            for node in ordered_references(ast):
                if node[0] == "ref":
                    candidates = [node[1:]]
                else:
                    candidates = sorted(k for k in self._cells if _in_range(k, node[1:]))
                for candidate in candidates:
                    fmt = self._shown_format(candidate, seen)
                    if fmt is not None and fmt.kind != "general":
                        inferred = fmt
                        break
                if inferred:
                    break
        self._inferred_formats[key] = inferred
        return inferred

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
                ast = parse(self._cells[key][1:], self.name_set())
                self._parsed[key] = (ast, *references(ast))
            except FormulaError as e:
                self._parsed[key] = (CellError(e.code), set(), [])
        return self._parsed[key]

    def _dependencies(self, key) -> list:
        """Formula cells that `key` refers to and that still need computing."""
        _, cells, ranges = self._parse(key)
        pending = [c for c in cells if c in self._formula_keys and c not in self._values]
        if ranges:
            # Scan the formula cells rather than every cell in each range.
            pending += [
                f for f in self._formula_keys
                if f not in self._values and any(_in_range(f, r) for r in ranges)
            ]
        return pending

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
            pending = self._dependencies(key)
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
        ast = self._parse(key)[0]
        if isinstance(ast, CellError):
            return ast
        try:
            return evaluate(ast, self._formula_sheet)
        except FormulaError as e:
            return CellError(e.code)


def _shifter(top: int, left: int, bottom: int, right: int, shift: str):
    """Where each cell goes when blank cells are inserted in place of a block:
    the block and the cells beyond it in the direction of the shift move by
    the block's height (or width)."""
    height, width = bottom - top + 1, right - left + 1

    def move(row: int, col: int) -> tuple[int, int]:
        in_columns, in_rows = left <= col <= right, top <= row <= bottom
        if shift == "down" and in_columns and row >= top:
            return row + height, col
        if shift == "right" and in_rows and col >= left:
            return row, col + width
        if shift == "up" and in_columns and row <= bottom:
            return row - height, col
        if shift == "left" and in_rows and col <= right:
            return row, col - width
        return row, col

    return move


def _changes(table: dict, updates: dict | None) -> tuple[dict, dict]:
    """(before, after) for the entries of `updates` that differ from `table`."""
    before, after = {}, {}
    for key, value in (updates or {}).items():
        old = table.get(key)
        if value != old:
            before[key] = old
            after[key] = value
    return before, after


def _in_range(key, bounds) -> bool:
    top, left, bottom, right = bounds
    return top <= key[0] <= bottom and left <= key[1] <= right


class _FormulaSheet:
    """The sheet as formula evaluation sees it (see formula.evaluate)."""

    def __init__(self, model: SheetModel):
        self.model = model

    @property
    def angle_unit(self) -> str:
        return self.model.angle_unit

    def _check(self, row: int, col: int) -> None:
        if not (0 <= row < self.model.rowCount() and 0 <= col < self.model.columnCount()):
            raise FormulaError(REF_ERROR)

    def cell(self, row: int, col: int):
        self._check(row, col)
        return self.model.value(row, col)

    def cells_in(self, top: int, left: int, bottom: int, right: int) -> list:
        """Values of the non-empty cells in a range."""
        self._check(top, left)
        self._check(bottom, right)
        bounds = (top, left, bottom, right)
        keys = [key for key in self.model._cells if _in_range(key, bounds)]
        return [self.model.value(*key) for key in keys]
