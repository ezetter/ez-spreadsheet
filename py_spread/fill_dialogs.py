"""Dialogs asking for Fill settings when they can't be inferred from the cells."""

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .fill import (
    LetterSequence,
    RandomFill,
    RandomLetters,
    RandomPattern,
    SequenceFill,
    UniformFill,
    check_letter_sequence,
    check_letters,
    check_pattern,
    check_random,
    check_sequence,
    is_letters,
    is_whole,
    letter_cycle,
    letter_sequence_values,
    sequence_values,
    written_as_float,
)
from .formula import format_number, parse_number


class _FillDialog(QDialog):
    """A form with an error/summary line and OK enabled only for valid entries."""

    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self.form = QFormLayout()
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.note)
        layout.addWidget(self.buttons)

    def number_field(self, label: str, value: float | str | None = None, placeholder: str = "") -> QLineEdit:
        if value is None:
            text = ""
        elif isinstance(value, str):
            text = value
        else:
            text = format_number(value)
        field = QLineEdit(text)
        field.setPlaceholderText(placeholder)
        field.textChanged.connect(self.update_state)
        self.form.addRow(label, field)
        return field

    def choice(self, label: str, options: list[str], selected: int) -> list[QRadioButton]:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        group = QButtonGroup(row)
        buttons = []
        for i, text in enumerate(options):
            button = QRadioButton(text)
            button.setChecked(i == selected)
            button.toggled.connect(self.update_state)
            group.addButton(button)
            row_layout.addWidget(button)
            buttons.append(button)
        self.form.addRow(label, row)
        return buttons

    def show_note(self, text: str, error: bool) -> None:
        self.note.setText(text)
        self.note.setStyleSheet("color: #c0392b;" if error else "")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(not error)

    def update_state(self, *_args) -> None:
        raise NotImplementedError


BOUND_HINT = "A number, or letters such as A or BCD"


def _bound(text: str) -> float | str | None:
    """A bound typed in a field: a number, a letter string, or None."""
    text = text.strip()
    return text if is_letters(text) else parse_number(text)


def _read_bounds(lower_field: QLineEdit, upper_field: QLineEdit):
    """(lower, upper), both numbers or both letter strings, or a message
    saying what's wrong."""
    lower, upper = _bound(lower_field.text()), _bound(upper_field.text())
    if lower is None or upper is None:
        return "Enter a number or letters (such as A or BCD) for each bound."
    if isinstance(lower, str) != isinstance(upper, str):
        return "The bounds must both be numbers, or both letters."
    return lower, upper


def _preview(values: list[str]) -> str:
    return ", ".join(values) if len(values) <= 4 else f"{values[0]}, {values[1]}, … {values[-1]}"


class RandomDialog(_FillDialog):
    def __init__(self, parent=None, initial: RandomFill | RandomLetters | RandomPattern | None = None,
                 keep_vowels: bool = True):
        super().__init__(parent, "Fill with Random Values")
        initial = initial or RandomFill(1, 100, integers=True)
        if isinstance(initial, RandomPattern):
            lower, upper, keep_vowels = initial.template, None, initial.keep_vowels
        else:
            lower, upper = initial.lower, initial.upper
        self.lower = self.number_field("Lower bound:", lower, BOUND_HINT)
        self.upper = self.number_field(
            "Upper bound:", upper, "Leave blank to use letters above as a pattern")
        integers = initial.integers if isinstance(initial, RandomFill) else True
        self.integers, self.floats = self.choice(
            "Numbers:", ["Integers", "Floating point"], 0 if integers else 1)
        self.keep_vowels = QCheckBox("Keep consonants and vowels in place")
        self.keep_vowels.setChecked(keep_vowels)
        self.keep_vowels.toggled.connect(self.update_state)
        self.form.addRow("Letters:", self.keep_vowels)
        self.update_state()

    def _is_pattern(self) -> bool:
        """Letters in the lower bound and nothing in the upper: random strings
        shaped like the lower bound."""
        return is_letters(self.lower.text().strip()) and not self.upper.text().strip()

    def _read(self) -> RandomFill | RandomLetters | RandomPattern | str:
        """The settings, or a message saying what's wrong with them."""
        if self._is_pattern():
            template = self.lower.text().strip()
            return check_pattern(template) or RandomPattern(template, self.keep_vowels.isChecked())
        bounds = _read_bounds(self.lower, self.upper)
        if isinstance(bounds, str):
            return bounds
        lower, upper = bounds
        if isinstance(lower, str):
            return check_letters(lower, upper) or RandomLetters(lower, upper)
        params = RandomFill(lower, upper, self.integers.isChecked())
        return check_random(params) or params

    def params(self) -> RandomFill | RandomLetters | RandomPattern | None:
        result = self._read()
        return None if isinstance(result, str) else result

    def update_state(self, *_args) -> None:
        pattern = self._is_pattern()
        letters = pattern or all(isinstance(_bound(f.text()), str) for f in (self.lower, self.upper))
        self.integers.setEnabled(not letters)
        self.floats.setEnabled(not letters)
        self.keep_vowels.setEnabled(pattern)
        result = self._read()
        if isinstance(result, str):
            self.show_note(result, error=True)
        elif isinstance(result, RandomPattern):
            if result.keep_vowels:
                self.show_note(f"Random strings shaped like {result.template}: a random vowel "
                               "for each vowel and a random consonant for each consonant.", error=False)
            else:
                self.show_note(f"Random {len(result.template)}-letter strings, any letter "
                               "in each position.", error=False)
        elif isinstance(result, RandomLetters):
            self.show_note(f"Random letter strings from {result.lower} to {result.upper}, "
                           "both included.", error=False)
        elif result.integers:
            self.show_note("Each bound can itself be picked.", error=False)
        else:
            self.show_note("", error=False)


MAX_FILL_CELLS = 100_000
DEFAULT_FILL_CELLS = 10


class SequenceDialog(_FillDialog):
    """Sequence settings. With several cells selected, they're the cells
    filled; with one, Num. cells says how many to fill from it, down or across
    as the order says."""

    def __init__(self, parent=None, initial: SequenceFill | LetterSequence | None = None, cell_count: int = 1):
        super().__init__(parent, "Fill with a Sequence")
        self.cell_count = cell_count
        if cell_count > 1:
            count = cell_count
        else:
            count = (initial.cells if initial and initial.cells else None) or DEFAULT_FILL_CELLS
        initial = initial or SequenceFill(1, max(count, 2))
        self.lower = self.number_field("Lower bound:", initial.lower, BOUND_HINT)
        self.upper = self.number_field("Upper bound:", initial.upper, BOUND_HINT)
        self.step = self.number_field(
            "Step:", initial.step, placeholder="Blank: spread evenly over the cells (1 for letters)")
        self.cells = QSpinBox()
        self.cells.setRange(1, MAX_FILL_CELLS)
        self.cells.setValue(count)
        self.cells.setEnabled(cell_count == 1)
        if cell_count > 1:
            self.cells.setToolTip("Set by the selected cells")
        self.cells.valueChanged.connect(self.update_state)
        self.form.addRow("Num. cells:", self.cells)
        self.ascending, self.descending = self.choice(
            "Direction:", ["Ascending", "Descending"], 1 if initial.descending else 0)
        self.down_first, self.across_first = self.choice(
            "Order:", ["Down columns, then across", "Across rows, then down"],
            1 if initial.across_first else 0)
        self.update_state()

    def _count(self) -> int:
        """How many cells will be filled."""
        return self.cells.value()

    def _read(self) -> SequenceFill | LetterSequence | str:
        """The settings, or a message saying what's wrong with them."""
        bounds = _read_bounds(self.lower, self.upper)
        if isinstance(bounds, str):
            return bounds
        lower, upper = bounds
        step = None
        if self.step.text().strip():
            step = parse_number(self.step.text())
            if step is None:
                return "The step must be a number, or blank."
        descending, across_first = self.descending.isChecked(), self.across_first.isChecked()
        cells = self._count() if self.cells.isEnabled() else None
        if isinstance(lower, str):
            if step is not None and not is_whole(step):
                return "For letters, the step must be a whole number."
            params = LetterSequence(lower, upper, 1 if step is None else int(step), descending,
                                    across_first, cells)
            return check_letter_sequence(params) or params
        # As with numbers in cells, typing 1.0 rather than 1 asks for floats.
        floats = any(written_as_float(f.text()) for f in (self.lower, self.upper, self.step))
        params = SequenceFill(lower, upper, step, descending, across_first, floats, cells)
        return check_sequence(params) or params

    def params(self) -> SequenceFill | LetterSequence | None:
        result = self._read()
        return None if isinstance(result, str) else result

    def update_state(self, *_args) -> None:
        result = self._read()
        if isinstance(result, str):
            self.show_note(result, error=True)
            return
        count = self._count()
        if isinstance(result, LetterSequence):
            values = letter_sequence_values(result, count)
            text = f"Fills {count} cells: {_preview(values)}"
            cycle = letter_cycle(result)
            if cycle < count:
                text += f". Starts over after {values[cycle - 1]}."
            self.show_note(text, error=False)
            return
        values = sequence_values(result, count)
        text = f"Fills {len(values)} of {count} cells: {_preview(values)}"
        if len(values) < count:
            text += f". The sequence ends there; {count - len(values)} cells stay unchanged."
        self.show_note(text, error=False)


class UniformDialog(_FillDialog):
    def __init__(self, parent=None, initial: UniformFill | None = None):
        super().__init__(parent, "Fill with One Value")
        self.value = QLineEdit(initial.value if initial else "")
        self.value.setPlaceholderText("A number, text, or =formula")
        self.value.textChanged.connect(self.update_state)
        self.form.addRow("Value:", self.value)
        self.update_state()

    def params(self) -> UniformFill | None:
        return UniformFill(self.value.text()) if self.value.text() else None

    def update_state(self, *_args) -> None:
        if self.value.text():
            self.show_note("", error=False)
        else:
            self.show_note("Enter the value to put in every selected cell.", error=True)


class FillDialogs:
    """Shows each dialog and returns its settings, or None if cancelled."""

    def __init__(self, parent):
        self.parent = parent

    def _run(self, dialog):
        return dialog.params() if dialog.exec() == QDialog.Accepted else None

    def random(self, initial, keep_vowels=True):
        return self._run(RandomDialog(self.parent, initial, keep_vowels))

    def sequence(self, initial, cell_count):
        return self._run(SequenceDialog(self.parent, initial, cell_count))

    def uniform(self, initial):
        return self._run(UniformDialog(self.parent, initial))
