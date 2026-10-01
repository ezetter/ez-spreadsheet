"""Filling the selected cells: the toolbar's Fill button.

Three modes:
- Random: random numbers between a lower and upper bound, integers or floats.
- Sequence: evenly stepped numbers from lower to upper (or upper to lower).
- Uniform: the same value in every cell.

Cells are filled down each column, then across the columns (or optionally
across each row, then down). Before asking with a dialog, the first cells of
the selection are checked for a value to work from:
- Uniform uses the first cell's value.
- Sequence continues from the first two numbers (their difference is the step).
- Random picks numbers between the first two numbers, replacing them too.
"""

import math
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, Signal

from .formula import format_number, is_formula, shift_references


@dataclass(frozen=True)
class FillMode:
    key: str
    label: str


FILL_MODES = [
    FillMode("random", "Random"),
    FillMode("sequence", "Sequence"),
    FillMode("uniform", "Uniform"),
]


@dataclass(frozen=True)
class RandomFill:
    lower: float
    upper: float
    integers: bool


@dataclass(frozen=True)
class SequenceFill:
    lower: float
    upper: float
    step: float | None = None  # None spreads the values evenly over the cells
    descending: bool = False
    across_first: bool = False  # fill across each row before moving down


@dataclass(frozen=True)
class UniformFill:
    value: str


def order_cells(cells, across_first: bool = False) -> list[tuple[int, int]]:
    """Cells in fill order: down each column then across, or across each row then down."""
    if across_first:
        return sorted(cells)
    return sorted(cells, key=lambda cell: (cell[1], cell[0]))


def is_whole(value: float) -> bool:
    return float(value).is_integer()


def check_random(params: RandomFill) -> str | None:
    """Why the settings can't be used, or None if they're fine."""
    if params.lower >= params.upper:
        return "The lower bound must be less than the upper bound."
    if params.integers and not (is_whole(params.lower) and is_whole(params.upper)):
        return "Integer bounds must be whole numbers. Use floating point for a range within one integer."
    return None


def check_sequence(params: SequenceFill) -> str | None:
    if params.lower >= params.upper:
        return "The lower bound must be less than the upper bound."
    if params.step is not None and params.step <= 0:
        return "The step must be greater than zero."
    return None


def random_values(params: RandomFill, count: int, rng: np.random.Generator) -> list[str]:
    if params.integers:
        numbers = rng.integers(int(params.lower), int(params.upper), size=count, endpoint=True)
        return [str(int(n)) for n in numbers]
    numbers = rng.uniform(params.lower, params.upper, size=count)
    return [format_number(float(n)) for n in numbers]


def sequence_numbers(params: SequenceFill, count: int) -> list[float]:
    """The sequence for `count` cells. It's shorter than `count` when an
    explicit step reaches the far bound before the cells run out."""
    span = params.upper - params.lower
    if params.step is None:
        step = span / (count - 1) if count > 1 else 0.0
        length = count
    else:
        step = params.step
        length = min(count, math.floor(span / step + 1e-9) + 1)
    if params.descending:
        return [params.upper - i * step for i in range(length)]
    return [params.lower + i * step for i in range(length)]


def sequence_values(params: SequenceFill, count: int) -> list[str]:
    # format_number writes whole numbers as integers and trims float noise
    # such as 0.30000000000000004.
    return [format_number(n) for n in sequence_numbers(params, count)]


def infer(mode: FillMode, first_raw: list[str], first_values: list, count: int):
    """Fill settings implied by the first one or two cells of the selection
    (their raw text and computed values), or None if they don't imply any."""
    if mode.key == "uniform":
        return UniformFill(first_raw[0]) if first_raw and first_raw[0] else None
    if len(first_values) < 2 or not all(isinstance(v, float) for v in first_values):
        return None
    a, b = first_values
    if mode.key == "random":
        lower, upper = min(a, b), max(a, b)
        return RandomFill(lower, upper, integers=is_whole(a) and is_whole(b))
    step = b - a
    if step == 0:
        return UniformFill(first_raw[0])
    last = a + (count - 1) * step
    return SequenceFill(min(a, last), max(a, last), abs(step), descending=step < 0)


class FillController(QObject):
    message = Signal(str)  # status text; empty clears it

    def __init__(self, view, model, dialogs, rng=None):
        super().__init__(view)
        self.view = view
        self.model = model
        self.dialogs = dialogs  # asks for settings: random(), sequence(), uniform()
        self.rng = rng if rng is not None else np.random.default_rng()
        self.mode = next(m for m in FILL_MODES if m.key == "sequence")
        self._last = {}  # settings last entered in each dialog, offered next time

    def run(self, mode: FillMode | None = None) -> None:
        if mode is not None:
            self.mode = mode
        cells = {(i.row(), i.column()) for i in self.view.selectedIndexes()}
        if not cells:
            current = self.view.currentIndex()
            cells = {(current.row(), current.column())}
        ordered = order_cells(cells)
        first = ordered[:2]
        params = infer(
            self.mode,
            [self.model.get_cell(*c) for c in first],
            [self.model.value(*c) for c in first],
            len(cells),
        )
        if params is None:
            params = self._ask(len(cells))
            if params is None:
                return  # cancelled
        self.message.emit(self._fill(cells, params))

    def _ask(self, count: int):
        key = self.mode.key
        initial = self._last.get(key)
        if key == "random":
            params = self.dialogs.random(initial)
        elif key == "sequence":
            params = self.dialogs.sequence(initial, count)
        else:
            params = self.dialogs.uniform(initial)
        if params is not None:
            self._last[key] = params
        return params

    def _fill(self, cells, params) -> str:
        """Write the values; returns a status message."""
        if isinstance(params, UniformFill):
            ordered = order_cells(cells)
            source = ordered[0]
            text = params.value
            writes = {}
            for cell in ordered:
                if is_formula(text):
                    # Like pasting: references move with each cell.
                    writes[cell] = shift_references(text, cell[0] - source[0], cell[1] - source[1])
                else:
                    writes[cell] = text
            self.model.set_cells(writes)
            return f"Filled {len(cells)} cells with {text}."

        if isinstance(params, RandomFill):
            ordered = order_cells(cells)
            values = random_values(params, len(ordered), self.rng)
            self.model.set_cells(dict(zip(ordered, values)))
            kind = "integers" if params.integers else "numbers"
            return (f"Filled {len(cells)} cells with random {kind} from "
                    f"{format_number(params.lower)} to {format_number(params.upper)}.")

        ordered = order_cells(cells, params.across_first)
        values = sequence_values(params, len(ordered))
        self.model.set_cells(dict(zip(ordered, values)))
        text = f"Filled {len(values)} cells with a sequence from {values[0]} to {values[-1]}."
        if len(values) < len(ordered):
            text += f" The sequence ended, so {len(ordered) - len(values)} cells were left unchanged."
        return text
