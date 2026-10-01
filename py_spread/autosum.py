"""AutoSum, behind the toolbar's Σ button.

The button applies an aggregate function (sum by default; its menu offers the
others). In order of priority, pressing it:
1. If the selection holds any numbers, waits for a cell to be clicked and puts
   the function of the selection there.
2. Otherwise, if there are numbers above the current cell, applies the
   function to them in the current cell.
3. Otherwise, if there are numbers to its left, does the same with those.

Choosing a function from the menu while on a cell that already holds one,
such as =SUM(A1:A9), switches that cell to the new function instead.
"""

from dataclasses import dataclass

from PySide6.QtCore import QItemSelectionModel, QObject, Signal

from .formula import is_formula, replace_function
from .references import cell_name


@dataclass(frozen=True)
class Aggregate:
    function: str  # formula function name
    label: str  # menu text
    symbol: str  # button text


AGGREGATES = [
    Aggregate("SUM", "Sum", "Σ"),
    Aggregate("MEAN", "Mean", "x̄"),
    Aggregate("MEDIAN", "Median", "x̃"),
    Aggregate("STDDEV", "Standard Deviation", "σ"),
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


def range_name(bounds: tuple[int, int, int, int]) -> str:
    top, left, bottom, right = bounds
    if (top, left) == (bottom, right):
        return cell_name(top, left)
    return f"{cell_name(top, left)}:{cell_name(bottom, right)}"


def aggregate_formula(function: str, ranges) -> str:
    return f"={function}(" + ", ".join(range_name(r) for r in ranges) + ")"


def run_above(model, row: int, col: int):
    """The block of numbers nearest above (row, col), skipping blank cells
    directly above it, as (top, left, bottom, right); or None."""
    return _run(model, row, col, -1, 0)


def run_left(model, row: int, col: int):
    """The block of numbers nearest to the left of (row, col), like run_above."""
    return _run(model, row, col, 0, -1)


def _run(model, row, col, d_row, d_col):
    def value(steps):
        return model.value(row + d_row * steps, col + d_col * steps)

    limit = row if d_row else col  # cells available before the sheet edge
    step = 1
    while step <= limit and value(step) is None:
        step += 1
    first = step
    while step <= limit and isinstance(value(step), float):
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

    def switch_current_cell(self) -> bool:
        """If the current cell's formula is a single aggregate call, make it
        use the chosen function. Returns whether the cell held one."""
        index = self.view.currentIndex()
        if not index.isValid():
            return False
        raw = self.model.get_cell(index.row(), index.column())
        if not is_formula(raw):
            return False
        names = {a.function for a in AGGREGATES}
        switched = replace_function(raw, names, self.aggregate.function)
        if switched is None:
            return False
        self.message.emit("")
        self.model.set_cell(index.row(), index.column(), switched, "Change Function")
        return True

    def trigger(self) -> None:
        if self.pending:
            self.cancel()
            return
        selected = {(i.row(), i.column()) for i in self.view.selectedIndexes()}
        if any(isinstance(self.model.value(*cell), float) for cell in selected):
            self._cells = selected
            self.view.pick_handler = self._place
            self.pending_changed.emit(True)
            self._prompt()
            return

        current = self.view.currentIndex()
        row, col = current.row(), current.column()
        run = run_above(self.model, row, col) or run_left(self.model, row, col)
        if run is None:
            self.message.emit(
                f"Nothing to {self.aggregate.label.lower()}: select some numbers, "
                "or start below or right of them."
            )
            return
        self.message.emit("")
        self.model.set_cell(row, col, aggregate_formula(self.aggregate.function, [run]), self.aggregate.label)

    def cancel(self) -> None:
        if not self.pending:
            return
        self._cells = None
        self.view.pick_handler = None
        self.pending_changed.emit(False)
        self.message.emit("")

    def _prompt(self) -> None:
        self.message.emit(f"Click the cell where the {self.aggregate.label.lower()} should go. Esc cancels.")

    def _place(self, index) -> None:
        target = (index.row(), index.column())
        if target in self._cells:
            self.message.emit("Pick a cell outside the selected ones. Esc cancels.")
            return
        formula = aggregate_formula(self.aggregate.function, cell_ranges(self._cells))
        self.cancel()
        self.model.set_cell(*target, formula, self.aggregate.label)
        selection = self.view.selectionModel()
        selection.setCurrentIndex(index, QItemSelectionModel.ClearAndSelect)
