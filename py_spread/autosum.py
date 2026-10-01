"""AutoSum, behind the toolbar's Σ button.

In order of priority, pressing Σ:
1. If the selection holds any numbers, waits for a cell to be clicked and puts
   the sum of the selection there.
2. Otherwise, if there are numbers above the current cell, sums them into it.
3. Otherwise, if there are numbers to its left, sums them into it.
"""

from PySide6.QtCore import QItemSelectionModel, QObject, Signal

from .references import cell_name


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


def sum_formula(ranges) -> str:
    return "=SUM(" + ", ".join(range_name(r) for r in ranges) + ")"


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
        self._cells = None  # cells being summed while waiting for a click
        model.contents_changed.connect(self.cancel)
        view.escape_pressed.connect(self.cancel)

    @property
    def pending(self) -> bool:
        return self._cells is not None

    def trigger(self) -> None:
        if self.pending:
            self.cancel()
            return
        selected = {(i.row(), i.column()) for i in self.view.selectedIndexes()}
        if any(isinstance(self.model.value(*cell), float) for cell in selected):
            self._cells = selected
            self.view.pick_handler = self._place
            self.pending_changed.emit(True)
            self.message.emit("Click the cell where the sum should go. Esc cancels.")
            return

        current = self.view.currentIndex()
        row, col = current.row(), current.column()
        run = run_above(self.model, row, col) or run_left(self.model, row, col)
        if run is None:
            self.message.emit("Nothing to sum: select some numbers, or start below or right of them.")
            return
        self.message.emit("")
        self.model.set_cell(row, col, sum_formula([run]))

    def cancel(self) -> None:
        if not self.pending:
            return
        self._cells = None
        self.view.pick_handler = None
        self.pending_changed.emit(False)
        self.message.emit("")

    def _place(self, index) -> None:
        target = (index.row(), index.column())
        if target in self._cells:
            self.message.emit("Pick a cell outside the ones being summed. Esc cancels.")
            return
        formula = sum_formula(cell_ranges(self._cells))
        self.cancel()
        self.model.set_cell(*target, formula)
        selection = self.view.selectionModel()
        selection.setCurrentIndex(index, QItemSelectionModel.ClearAndSelect)
