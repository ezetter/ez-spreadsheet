"""AutoSum, behind the toolbar's Σ button.

The button applies an aggregate function (sum by default; its menu offers the
others). In order of priority, pressing it:
1. If the selection holds any numbers, waits for a cell to be clicked and puts
   the function of the selection there. If the selection spans several rows
   and columns, each column gets its own result instead: the first column's in
   the clicked cell, the others' in the cells to its right.
2. Otherwise, if there are numbers above the current cell, applies the
   function to them in the current cell.
3. Otherwise, if there are numbers to its left, does the same with those.
With several cells selected (say, the empty cells under several columns of
numbers), 2 and 3 apply to each empty one, so each column gets its own total.

Count Non-Empty (COUNTA) works the same way with cells of anything, text
included, where the others look for numbers.

Choosing a function from the menu while on a cell that already holds one,
such as =SUM(A1:A9), switches that cell, and any others selected that hold
one, to the new function instead.
"""

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from .formula import is_formula, replace_function
from .references import cell_name
from .names import cell_text


@dataclass(frozen=True)
class Aggregate:
    function: str  # formula function name
    label: str  # menu text
    symbol: str  # button text
    any_value: bool = False  # of cells with anything in them (COUNTA), not just numbers
    noun: str = ""  # what it makes, in messages, if not its label: a count

    @property
    def name(self) -> str:
        return self.noun or self.label.lower()

    def takes(self, value) -> bool:
        """Whether it's of a cell with this value: a number, or for one of any value, anything."""
        return value not in (None, "") if self.any_value else isinstance(value, float)


AGGREGATES = [
    Aggregate("SUM", "Sum", "Σ"),
    Aggregate("MEAN", "Mean", "x̄"),
    Aggregate("MEDIAN", "Median", "x̃"),
    Aggregate("STDDEV", "Standard Deviation", "σ"),
    Aggregate("COUNT", "Count", "n"),
    Aggregate("COUNTA", "Count Non-Empty", "nₐ", any_value=True, noun="count"),
]


def cell_ranges(cells) -> list[tuple[int, int, int, int]]:
    """Cover a set of (row, col) cells exactly with (top, left, bottom, right)
    rectangles: runs down each column, merged across neighboring columns
    that have the same run.
    """
    rows_by_col: dict[int, list[int]] = {}
    for row, col in cells:
        rows_by_col.setdefault(col, []).append(row)
    finished = []
    growing: dict[tuple[int, int], list[int]] = {}  # run -> rectangle ending at the previous column
    for col in sorted(rows_by_col):
        still_growing = {}
        for run in _runs(sorted(rows_by_col[col])):
            rect = growing.pop(run, None)
            if rect is not None and rect[3] == col - 1:
                rect[3] = col
            else:
                if rect is not None:
                    finished.append(rect)
                rect = [run[0], col, run[1], col]
            still_growing[run] = rect
        finished.extend(growing.values())
        growing = still_growing
    finished.extend(growing.values())
    return sorted(tuple(rect) for rect in finished)


def _runs(rows: list[int]) -> list[tuple[int, int]]:
    """Consecutive stretches of sorted row numbers, as (first, last)."""
    runs = []
    for row in rows:
        if runs and runs[-1][1] == row - 1:
            runs[-1] = (runs[-1][0], row)
        else:
            runs.append((row, row))
    return runs


def range_name(bounds: tuple[int, int, int, int], names=()) -> str:
    """A1:B9, or one cell's reference; a single cell spelled like one of the
    cell `names` gets a $ so it still means the cell. (Ranges always do.)"""
    top, left, bottom, right = bounds
    if (top, left) == (bottom, right):
        return cell_text(cell_name(top, left), names)
    return f"{cell_name(top, left)}:{cell_name(bottom, right)}"


def aggregate_formula(function: str, ranges, names=()) -> str:
    return f"={function}(" + ", ".join(range_name(r, names) for r in ranges) + ")"


def run_above(model, row: int, col: int, takes=None):
    """The block of numbers (or of the values `takes(value)` accepts)
    nearest above (row, col), skipping blank cells directly above it, as
    (top, left, bottom, right); or None."""
    return _run(model, row, col, -1, 0, takes)


def run_left(model, row: int, col: int, takes=None):
    """The block of numbers nearest to the left of (row, col), like run_above."""
    return _run(model, row, col, 0, -1, takes)


def _run(model, row, col, d_row, d_col, takes=None):
    takes = takes or (lambda value: isinstance(value, float))

    def value(steps):
        return model.value(row + d_row * steps, col + d_col * steps)

    limit = row if d_row else col  # cells available before the sheet edge
    step = 1
    while step <= limit and value(step) is None:
        step += 1
    first = step
    while step <= limit and takes(value(step)):
        step += 1
    if step == first:
        return None
    near = (row + d_row * first, col + d_col * first)
    far = (row + d_row * (step - 1), col + d_col * (step - 1))
    return (far[0], far[1], near[0], near[1])


class AutoSumController(QObject):
    pending_changed = Signal(bool)  # waiting for the user to click the sum's cell
    message = Signal(str)  # status text; empty clears it

    def __init__(self, view, model):
        super().__init__(view)
        self.view = view
        self.model = model
        self.aggregate = AGGREGATES[0]
        self._cells = None  # cells being aggregated while waiting for a click
        model.contents_changed.connect(self.cancel)
        view.escape_pressed.connect(self.cancel)

    @property
    def pending(self) -> bool:
        return self._cells is not None

    def set_aggregate(self, aggregate: Aggregate) -> None:
        """Choose the function; if waiting for a click, keep waiting with it."""
        self.aggregate = aggregate
        if self.pending:
            self._prompt()

    def switch_selected_cells(self) -> bool:
        """If the current cell's formula is a single aggregate call, make it,
        and every other selected cell holding one, use the chosen function.
        Returns whether the current cell held one."""
        index = self.view.currentIndex()
        if not index.isValid() or self._switched(index.row(), index.column()) is None:
            return False
        cells = {(i.row(), i.column()) for i in self.view.selectedIndexes()} | {(index.row(), index.column())}
        writes = {cell: self._switched(*cell) for cell in cells}
        self.message.emit("")
        self.model.set_cells({cell: text for cell, text in writes.items() if text is not None},
                             "Change Function")
        return True

    def _switched(self, row: int, col: int) -> str | None:
        """The cell's formula calling the chosen function, if it's a single aggregate call."""
        raw = self.model.get_cell(row, col)
        if not is_formula(raw):
            return None
        return replace_function(raw, {a.function for a in AGGREGATES}, self.aggregate.function)

    def trigger(self) -> None:
        if self.pending:
            self.cancel()
            return
        selected = {(i.row(), i.column()) for i in self.view.selectedIndexes()}
        if any(self.aggregate.takes(self.model.value(*cell)) for cell in selected):
            self._cells = selected
            self.view.pick_handler = self._place
            self.pending_changed.emit(True)
            self._prompt()
            return

        current = self.view.currentIndex()
        if len(selected) > 1:
            # Each empty selected cell gets its own total; text such as a
            # "Total" label is left alone.
            targets = sorted(cell for cell in selected if not self.model.get_cell(*cell))
        else:
            targets = [(current.row(), current.column())]
        # Work every formula out before writing any, so new totals never
        # include each other.
        writes = {}
        for row, col in targets:
            takes = self.aggregate.takes
            run = run_above(self.model, row, col, takes) or run_left(self.model, row, col, takes)
            if run is not None:
                writes[(row, col)] = aggregate_formula(self.aggregate.function, [run], self.model.name_set())
        if not writes:
            self.message.emit(
                f"Nothing to {self.aggregate.name}: select some "
                f"{'cells with something in them' if self.aggregate.any_value else 'numbers'}, "
                "or start below or right of them."
            )
            return
        self.message.emit("" if len(writes) == 1 else
                          f"Added {len(writes)} {self.aggregate.name} formulas.")
        self.model.set_cells(writes, self.aggregate.label)

    def cancel(self) -> None:
        if not self.pending:
            return
        self._cells = None
        self.view.pick_handler = None
        self.pending_changed.emit(False)
        self.message.emit("")

    def _per_column(self) -> bool:
        """Whether the cells being aggregated get one result per column: they
        span several columns and several rows."""
        rows = {row for row, _ in self._cells}
        cols = {col for _, col in self._cells}
        return len(rows) > 1 and len(cols) > 1

    def _prompt(self) -> None:
        label = self.aggregate.name
        if self._per_column():
            self.message.emit(f"Click the cell for the first column's {label}; the other columns' "
                              "go to its right. Esc cancels.")
        else:
            self.message.emit(f"Click the cell where the {label} should go. Esc cancels.")

    def _place(self, index) -> None:
        row, col = index.row(), index.column()
        if self._per_column():
            writes = self._per_column_formulas(row, col)
        else:
            writes = {(row, col): aggregate_formula(self.aggregate.function, cell_ranges(self._cells),
                                                         self.model.name_set())}
        if any(target in self._cells for target in writes) or (row, col) in self._cells:
            self.message.emit("Pick a cell outside the selected ones. Esc cancels.")
            return
        self.cancel()
        self.model.set_cells(writes, self.aggregate.label)
        right = max([c for _, c in writes] + [col])
        self.view.select_range(row, col, row, right)

    def _per_column_formulas(self, row: int, col: int) -> dict:
        """One formula per selected column, laid out from (row, col) rightward
        with the same spacing as the columns. Columns without numbers are
        skipped, as are any that would land off the sheet."""
        columns: dict[int, set] = {}
        for cell in self._cells:
            columns.setdefault(cell[1], set()).add(cell)
        left = min(columns)
        writes = {}
        for source_col, cells in sorted(columns.items()):
            target_col = col + source_col - left
            if target_col >= self.model.columnCount():
                continue
            if any(self.aggregate.takes(self.model.value(*cell)) for cell in cells):
                writes[(row, target_col)] = aggregate_formula(self.aggregate.function, cell_ranges(cells),
                                                                     self.model.name_set())
        return writes
