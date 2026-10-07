"""Filling the selected cells: the toolbar's Fill button.

Three modes:
- Random: random numbers between a lower and upper bound, integers or floats,
  or random letter strings between two letter strings.
- Sequence: evenly stepped numbers from lower to upper (or upper to lower), or
  letter strings from one to another, starting over when they run out.
- Uniform: the same value in every cell.

Letter strings are ordered like column names, with the rightmost letter
changing fastest: A … Z, AA, AB … AZ, BA … ZZ, AAA …. So BCD to DCB includes
CAD and DAA, but not DCE or ABC.

Cells are filled down each column, then across the columns (or optionally
across each row, then down). Before asking with a dialog, the first cells of
the selection are checked for a value to work from:
- Uniform uses the first cell's value.
- Sequence continues from the first two numbers (their difference is the step).
  Two letter strings are instead the range: A, C over four cells gives A, B, C, A.
- Random picks numbers or letter strings between the first two values,
  replacing them too. A letter string alone is a pattern: each position gets a
  random vowel where it has a vowel and a random consonant where it has a
  consonant (or any letter, if that's turned off in the dialog).
Numbers typed as floating point (1.0, 2.50, 1e3) make the fill floating point,
even when their values are whole. Numbers typed with a dollar sign or thousands
separators ($1.00, 1,000) are filled in the same style, and the first cell's
number format and bold/italic style, if it has them, are given to every
filled cell.
"""

import math
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, Signal

from .formula import format_number, is_formula, parse_number, shift_references
from .numformat import NumberFormat, format_value, parse_formatted
from .textstyle import PLAIN
from .references import column_index, column_name

MAX_LETTERS = 10  # longest letter string; keeps random picks within NumPy's int64
MAX_PATTERN = 100  # longest pattern for random letter strings
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
VOWELS = "AEIOU"  # Y counts as a consonant
CONSONANTS = "".join(c for c in ALPHABET if c not in VOWELS)


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
    floats: bool = False  # write whole values as floats too (3.0, not 3)
    # With one cell selected: how many cells to fill from it, down (or
    # across, with across_first). None fills the selected cells.
    cells: int | None = None


@dataclass(frozen=True)
class RandomLetters:
    lower: str
    upper: str


@dataclass(frozen=True)
class RandomPattern:
    """Random letter strings shaped like `template`, position by position."""

    template: str
    keep_vowels: bool = True  # vowels stay vowels and consonants stay consonants


@dataclass(frozen=True)
class LetterSequence:
    lower: str
    upper: str
    step: int = 1
    descending: bool = False
    across_first: bool = False
    cells: int | None = None  # as for SequenceFill


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


def written_as_float(text: str) -> bool:
    """Whether text is a number typed in floating point form, like 1.0 or 1e3."""
    return parse_number(text) is not None and any(c in text for c in ".eE")


def format_float(value: float) -> str:
    """Like format_number, but whole values keep a decimal point: 3.0, not 3."""
    text = format_number(value)
    return text if any(c in text for c in ".e") else text + ".0"


def is_letters(text: str) -> bool:
    return text.isascii() and text.isalpha()


def letter_index(text: str) -> int:
    """Position in the order A … Z, AA, AB, … (A is 0)."""
    return column_index(text)


def letter_text(index: int, lowercase: bool) -> str:
    text = column_name(index)
    return text.lower() if lowercase else text


def lowercase_letters(*texts: str) -> bool:
    """Output is lowercase only if every bound is; otherwise uppercase."""
    return all(t.islower() for t in texts)


def check_letters(lower: str, upper: str) -> str | None:
    if not (is_letters(lower) and is_letters(upper)):
        return "Letter bounds can contain only the letters A to Z."
    if max(len(lower), len(upper)) > MAX_LETTERS:
        return f"Letter bounds can be at most {MAX_LETTERS} letters long."
    if letter_index(lower) >= letter_index(upper):
        return "The lower bound must come before the upper bound (A … Z, AA, AB …)."
    return None


def check_letter_sequence(params: LetterSequence) -> str | None:
    if params.step < 1:
        return "The step must be a whole number of at least 1."
    return check_letters(params.lower, params.upper)


def random_letters(params: RandomLetters, count: int, rng: np.random.Generator) -> list[str]:
    lowercase = lowercase_letters(params.lower, params.upper)
    picks = rng.integers(letter_index(params.lower), letter_index(params.upper), size=count, endpoint=True)
    return [letter_text(int(i), lowercase) for i in picks]


def check_pattern(template: str) -> str | None:
    if not is_letters(template):
        return "A pattern can contain only the letters A to Z."
    if len(template) > MAX_PATTERN:
        return f"A pattern can be at most {MAX_PATTERN} letters long."
    return None


def random_pattern(params: RandomPattern, count: int, rng: np.random.Generator) -> list[str]:
    """Each position picks from the vowels or consonants (or, without
    keep_vowels, the whole alphabet), in that position's case."""
    columns = []
    for char in params.template:
        if not params.keep_vowels:
            pool = ALPHABET
        else:
            pool = VOWELS if char.upper() in VOWELS else CONSONANTS
        if char.islower():
            pool = pool.lower()
        columns.append([pool[i] for i in rng.integers(0, len(pool), size=count)])
    return ["".join(chars) for chars in zip(*columns)]


def letter_cycle(params: LetterSequence) -> int:
    """How many letter strings the sequence has before it starts over."""
    return (letter_index(params.upper) - letter_index(params.lower)) // params.step + 1


def letter_sequence_values(params: LetterSequence, count: int) -> list[str]:
    """Letter strings from one bound toward the other, starting over when they
    run out before the cells do."""
    low, high = letter_index(params.lower), letter_index(params.upper)
    cycle = letter_cycle(params)
    start, sign = (high, -1) if params.descending else (low, 1)
    lowercase = lowercase_letters(params.lower, params.upper)
    return [letter_text(start + sign * (i % cycle) * params.step, lowercase) for i in range(count)]


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
    return [format_float(float(n)) for n in numbers]


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
    # Both formats trim float noise such as 0.30000000000000004; format_number
    # also writes whole values as integers.
    write = format_float if params.floats else format_number
    return [write(n) for n in sequence_numbers(params, count)]


def typed_style(first_raw: list[str]) -> NumberFormat | None:
    """The style the first cells' numbers were typed in ($1.00, 1,000), with
    as many decimals as the more precise of them; None for plain numbers."""
    styles = [parsed[1] for parsed in map(parse_formatted, first_raw) if parsed]
    if not styles:
        return None
    return NumberFormat(styles[0].kind, max(s.decimals for s in styles), styles[0].thousands)


def infer(mode: FillMode, first_raw: list[str], first_values: list, count: int,
          keep_vowels: bool = True):
    """Fill settings implied by the first one or two cells of the selection
    (their raw text and computed values), or None if they don't imply any.
    `keep_vowels` is used for a random letter pattern."""
    if mode.key == "uniform":
        return UniformFill(first_raw[0]) if first_raw and first_raw[0] else None
    if first_raw and _letter_bound(first_raw[0]):
        return _infer_letters(mode, first_raw, keep_vowels)
    if len(first_values) < 2 or not all(isinstance(v, float) for v in first_values):
        return None
    a, b = first_values
    floats = any(written_as_float(raw) for raw in first_raw)
    if mode.key == "random":
        lower, upper = min(a, b), max(a, b)
        return RandomFill(lower, upper, integers=is_whole(a) and is_whole(b) and not floats)
    step = b - a
    if step == 0:
        return UniformFill(first_raw[0])
    last = a + (count - 1) * step
    return SequenceFill(min(a, last), max(a, last), abs(step), descending=step < 0, floats=floats)


def _letter_bound(text: str) -> bool:
    return is_letters(text) and len(text) <= MAX_LETTERS


def _infer_letters(mode: FillMode, first_raw: list[str], keep_vowels: bool):
    first = first_raw[0]
    second = first_raw[1] if len(first_raw) > 1 else ""
    if mode.key == "random" and not second:
        return RandomPattern(first, keep_vowels)
    if not _letter_bound(second):
        return None
    if letter_index(first) == letter_index(second):
        return UniformFill(first)
    lower, upper = sorted((first, second), key=letter_index)
    if mode.key == "random":
        return RandomLetters(lower, upper)
    return LetterSequence(lower, upper, descending=letter_index(first) > letter_index(second))


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
        # Whether random letter patterns keep vowels and consonants in place;
        # on by default, and changed by the checkbox in the Random dialog.
        self.keep_vowels = True
        self._source_format = None  # explicit format of the first cell being filled
        self._source_style = PLAIN  # bold/italic of the first cell being filled
        self._style = None  # style the first cells' numbers were typed in

    def run(self, mode: FillMode | None = None) -> None:
        if mode is not None:
            self.mode = mode
        cells = {(i.row(), i.column()) for i in self.view.selectedIndexes()}
        if not cells:
            current = self.view.currentIndex()
            cells = {(current.row(), current.column())}
        ordered = order_cells(cells)
        first = ordered[:2]
        self._source_format = self.model.cell_format(*ordered[0])
        self._source_style = self.model.cell_style(*ordered[0])
        self._style = typed_style([self.model.get_cell(*c) for c in first])
        params = infer(
            self.mode,
            [self.model.get_cell(*c) for c in first],
            [self.model.value(*c) for c in first],
            len(cells),
            self.keep_vowels,
        )
        if params is None:
            params = self._ask(len(cells))
            if params is None:
                return  # cancelled
        line = self._line_of_cells(cells, params)
        self.message.emit(self._fill(line or cells, params))
        if line:
            rows = [row for row, _ in line]
            cols = [col for _, col in line]
            self.view.select_range(min(rows), min(cols), max(rows), max(cols))

    def _line_of_cells(self, cells, params) -> set | None:
        """For a sequence given a number of cells while one cell is selected:
        that many cells from it, down a column or (with across_first) along a
        row, growing the sheet if they run past its edge. Otherwise None."""
        count = getattr(params, "cells", None)
        if count is None or len(cells) != 1:
            return None
        (row, col), = cells
        if params.across_first:
            self.model.ensure_size(row + 1, col + count)
            return {(row, col + i) for i in range(count)}
        self.model.ensure_size(row + count, col + 1)
        return {(row + i, col) for i in range(count)}

    def _ask(self, count: int):
        key = self.mode.key
        initial = self._last.get(key)
        if key == "random":
            params = self.dialogs.random(initial, self.keep_vowels)
            if isinstance(params, RandomPattern):
                self.keep_vowels = params.keep_vowels
        elif key == "sequence":
            params = self.dialogs.sequence(initial, count)
        else:
            params = self.dialogs.uniform(initial)
        if params is not None:
            self._last[key] = params
        return params

    def _write(self, writes: dict) -> None:
        # Filled cells get the first cell's number format and style, if it has them.
        formats = {key: self._source_format for key in writes} if self._source_format else None
        styles = {key: self._source_style for key in writes} if self._source_style != PLAIN else None
        self.model.set_cells(writes, f"{self.mode.label} Fill", formats, styles)

    def _styled(self, values: list[str]) -> list[str]:
        """Numbers written in the style the first cells were typed in."""
        if self._style is None:
            return values
        return [format_value(parse_number(v), self._style) for v in values]

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
                    writes[cell] = shift_references(text, cell[0] - source[0], cell[1] - source[1],
                                                    self.model.name_set())
                else:
                    writes[cell] = text
            self._write(writes)
            return f"Filled {len(cells)} cells with {text}."

        if isinstance(params, RandomPattern):
            ordered = order_cells(cells)
            self._write(dict(zip(ordered, random_pattern(params, len(ordered), self.rng))))
            if params.keep_vowels:
                return (f"Filled {len(cells)} cells with random letters shaped like {params.template} "
                        "(vowels and consonants kept in place).")
            return f"Filled {len(cells)} cells with random {len(params.template)}-letter strings."

        if isinstance(params, RandomLetters):
            ordered = order_cells(cells)
            self._write(dict(zip(ordered, random_letters(params, len(ordered), self.rng))))
            return f"Filled {len(cells)} cells with random letters from {params.lower} to {params.upper}."

        if isinstance(params, LetterSequence):
            ordered = order_cells(cells, params.across_first)
            values = letter_sequence_values(params, len(ordered))
            self._write(dict(zip(ordered, values)))
            return f"Filled {len(cells)} cells with letters from {values[0]} to {values[-1]}."

        if isinstance(params, RandomFill):
            ordered = order_cells(cells)
            values = self._styled(random_values(params, len(ordered), self.rng))
            self._write(dict(zip(ordered, values)))
            kind = "integers" if params.integers else "numbers"
            return (f"Filled {len(cells)} cells with random {kind} from "
                    f"{format_number(params.lower)} to {format_number(params.upper)}.")

        ordered = order_cells(cells, params.across_first)
        values = self._styled(sequence_values(params, len(ordered)))
        self._write(dict(zip(ordered, values)))
        text = f"Filled {len(values)} cells with a sequence from {values[0]} to {values[-1]}."
        if len(values) < len(ordered):
            text += f" The sequence ended, so {len(ordered) - len(values)} cells were left unchanged."
        return text
