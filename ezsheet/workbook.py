"""A spreadsheet's sheets, switched between by the tabs below the grid.

Each sheet is a SheetModel of its own; the WorkbookModel shows the grid one
of them at a time, the current sheet, and passes on everything else asked
of it to that sheet, so the rest of the app works on the sheet shown. Its
sheets share one undo history: undoing a change to a sheet goes to it.

A formula can refer to another sheet's cells by its name (Sheet2!A1; see
formula.py). Renaming a sheet rewrites the formulas that name it; inserting
or deleting its rows or columns moves their references, as for its own
(see SheetModel._rearrange). A formula naming a sheet that isn't there (it
was deleted) is #REF!, until there's one of that name again.
"""

from PySide6.QtCore import QIdentityProxyModel, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from .formula import rename_sheet, same_sheet
from .model import DEFAULT_COLS, DEFAULT_ROWS, UNDO_LIMIT, SheetModel
from .storage import MAX_TITLE, SheetData, WorkbookData, title_problem

_RELAYED = ("names_changed", "merges_changed", "filter_changed")  # the current sheet's, passed on


class _SheetsCommand(QUndoCommand):
    """Sheets added, deleted, or moved: the sheets, in order, before and
    after, and the one shown."""

    def __init__(self, workbook, before: list, after: list, shown_before, shown_after, description: str):
        super().__init__(description)
        self.workbook = workbook
        self.before, self.after = before, after
        self.shown_before, self.shown_after = shown_before, shown_after

    def redo(self):
        self.workbook._set_sheets(self.after, self.shown_after)

    def undo(self):
        self.workbook._set_sheets(self.before, self.shown_before)


class _RenameCommand(QUndoCommand):
    def __init__(self, workbook, sheet: SheetModel, old: str, new: str):
        super().__init__("Rename Sheet")
        self.workbook, self.sheet, self.old, self.new = workbook, sheet, old, new

    def redo(self):
        self.workbook._retitle(self.sheet, self.new)

    def undo(self):
        self.workbook._retitle(self.sheet, self.old)


class WorkbookModel(QIdentityProxyModel):
    """The grid's model: the current sheet's cells. What isn't a Qt model's
    (set_cells, value, ...) is the current sheet's (see __getattr__)."""

    contents_changed = Signal()  # any sheet's cells, or the sheets
    names_changed = Signal()  # these, the current sheet's (or another sheet's shown)
    history_applied = Signal(list)
    angle_unit_changed = Signal(str)
    merges_changed = Signal()
    filter_changed = Signal()
    sheets_changed = Signal()  # a sheet added, deleted, renamed, or moved
    sheet_about_to_change = Signal()  # another sheet's about to be shown,
    sheet_shown = Signal()  # and now it is

    def __init__(self, rows: int = DEFAULT_ROWS, cols: int = DEFAULT_COLS, parent=None):
        super().__init__(parent)
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(UNDO_LIMIT)
        self._current = None
        self._sheets = [self._make_sheet(SheetData(rows, cols))]
        self._show(self._sheets[0])

    def __getattr__(self, name):
        current = self.__dict__.get("_current")
        if current is None:
            raise AttributeError(name)
        return getattr(current, name)

    # --- The sheets ---

    def sheets(self) -> list[SheetModel]:
        return list(self._sheets)

    def titles(self) -> list[str]:
        return [sheet.title for sheet in self._sheets]

    def current_sheet(self) -> SheetModel:
        return self._current

    def current_index(self) -> int:
        return self._sheets.index(self._current)

    def sheet_named(self, title: str) -> SheetModel | None:
        """The sheet with this name (in any case), if there is one."""
        return next((sheet for sheet in self._sheets if same_sheet(sheet.title, title)), None)

    def show_index(self, index: int) -> None:
        self._show(self._sheets[index])

    def show_sheet(self, sheet: SheetModel) -> None:
        if sheet in self._sheets:
            self._show(sheet)

    def new_title(self) -> str:
        """A name for a new sheet: Sheet2, Sheet3, ..., one not taken."""
        number = len(self._sheets) + 1
        while self.sheet_named(f"Sheet{number}") is not None:
            number += 1
        return f"Sheet{number}"

    def title_problem(self, title: str, index: int) -> str | None:
        """Why sheet `index` can't be named `title`, if it can't."""
        return title_problem(title, [sheet.title for i, sheet in enumerate(self._sheets) if i != index])

    def add_sheet(self, index: int | None = None, data: SheetData | None = None,
                  description: str = "Add Sheet") -> SheetModel:
        """A new sheet (empty, or of `data`) at `index` (else last), shown,
        as one undoable step."""
        if data is None:
            data = SheetData(DEFAULT_ROWS, DEFAULT_COLS, angle_unit=self._current.angle_unit, name=self.new_title())
        sheet = self._make_sheet(data)
        after = list(self._sheets)
        after.insert(len(after) if index is None else index, sheet)
        self.undo_stack.push(_SheetsCommand(self, list(self._sheets), after, self._current, sheet, description))
        return sheet

    def duplicate_sheet(self, index: int) -> SheetModel:
        """A copy of a sheet, just after it, named Copy of Sheet1 (or so)."""
        data = self._sheets[index].sheet_data()
        title, number = f"Copy of {data.name}", 2
        while self.sheet_named(title[:MAX_TITLE]) is not None:
            title, number = f"Copy of {data.name} {number}", number + 1
        data.name = title[:MAX_TITLE]
        return self.add_sheet(index + 1, data, "Duplicate Sheet")

    def delete_sheet(self, index: int) -> bool:
        """Delete a sheet (not the only one), as one undoable step. Formulas
        naming it are #REF! until it's back."""
        if len(self._sheets) == 1:
            return False
        sheet = self._sheets[index]
        after = [each for each in self._sheets if each is not sheet]
        shown = self._current if self._current is not sheet else after[min(index, len(after) - 1)]
        self.undo_stack.push(_SheetsCommand(self, list(self._sheets), after, sheet, shown, "Delete Sheet"))  # (undone: it's shown)
        return True

    def move_sheet(self, start: int, end: int) -> None:
        """Move a sheet's tab from `start` to `end`, as one undoable step."""
        if start == end:
            return
        after = list(self._sheets)
        after.insert(end, after.pop(start))
        self.undo_stack.push(_SheetsCommand(self, list(self._sheets), after, self._current, self._current,
                                            "Move Sheet"))

    def rename_sheet(self, index: int, title: str) -> str | None:
        """Name a sheet `title`, rewriting the formulas that name it, as one
        undoable step. Returns a problem, if any (see title_problem)."""
        title = title.strip()
        sheet = self._sheets[index]
        old = sheet.title
        if title == old:
            return None
        problem = self.title_problem(title, index)
        if problem:
            return problem
        rewrites = []
        for each in self._sheets:
            writes = {key: renamed for key, text in each.formula_cells().items()
                      if (renamed := rename_sheet(text, old, title)) != text}
            if writes:
                rewrites.append((each, writes))
        self.undo_stack.beginMacro("Rename Sheet")
        self.undo_stack.push(_RenameCommand(self, sheet, old, title))
        for each, writes in rewrites:
            each.set_cells(writes, "Rename Sheet", show=False)
        self.undo_stack.endMacro()
        return None

    # --- Saving and opening ---

    def workbook_data(self) -> WorkbookData:
        return WorkbookData([sheet.sheet_data() for sheet in self._sheets], self.current_index())

    def load_workbook_data(self, book: WorkbookData) -> None:
        """Replace every sheet, with no undo history."""
        self.undo_stack.clear()
        old = self._sheets
        self._sheets = [self._make_sheet(data) for data in book.sheets]
        self._show(self._sheets[book.active], announce=False)
        for sheet in old:
            sheet.deleteLater()
        self.sheets_changed.emit()

    # --- How they work together ---

    def sheet_changed(self, sheet: SheetModel) -> None:
        """A sheet's changed: the others' formulas may refer to it."""
        for other in self._sheets:
            if other is not sheet:
                other.recalculate()

    def _make_sheet(self, data: SheetData) -> SheetModel:
        sheet = SheetModel(data.rows, data.cols, parent=self, workbook=self, title=data.name)
        sheet.load_sheet_data(data, clear_history=False)
        for name in _RELAYED:
            getattr(sheet, name).connect(lambda s=sheet, n=name: s is self._current and getattr(self, n).emit())
        sheet.angle_unit_changed.connect(lambda unit, s=sheet: s is self._current and self.angle_unit_changed.emit(unit))
        sheet.history_applied.connect(lambda cells, s=sheet: s is self._current and self.history_applied.emit(cells))
        sheet.contents_changed.connect(self.contents_changed)
        return sheet

    def _show(self, sheet: SheetModel, announce: bool = True) -> None:
        if sheet is self._current:
            return
        if announce and self._current is not None:
            self.sheet_about_to_change.emit()
        self._current = sheet
        self.setSourceModel(sheet)
        self.angle_unit_changed.emit(sheet.angle_unit)
        for name in _RELAYED:
            getattr(self, name).emit()
        self.sheet_shown.emit()

    def _set_sheets(self, sheets: list, shown: SheetModel) -> None:
        self._sheets = list(sheets)
        for sheet in self._sheets:
            sheet.recalculate()  # (formulas naming a sheet added or deleted)
        self.sheets_changed.emit()
        self._show(shown)
        self.contents_changed.emit()

    def _retitle(self, sheet: SheetModel, title: str) -> None:
        sheet.title = title
        for each in self._sheets:
            each.recalculate()
        self.sheets_changed.emit()
        self._show(sheet)
        self.contents_changed.emit()
