"""Dialogs asking for Fill settings when they can't be inferred from the cells."""

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .fill import RandomFill, SequenceFill, UniformFill, check_random, check_sequence, sequence_values
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

    def number_field(self, label: str, value: float | None = None, placeholder: str = "") -> QLineEdit:
        field = QLineEdit("" if value is None else format_number(value))
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


def _numbers(fields) -> list[float | None]:
    return [parse_number(field.text()) for field in fields]


class RandomDialog(_FillDialog):
    def __init__(self, parent=None, initial: RandomFill | None = None):
        super().__init__(parent, "Fill with Random Numbers")
        initial = initial or RandomFill(1, 100, integers=True)
        self.lower = self.number_field("Lower bound:", initial.lower)
        self.upper = self.number_field("Upper bound:", initial.upper)
        self.integers, self.floats = self.choice(
            "Values:", ["Integers", "Floating point"], 0 if initial.integers else 1)
        self.update_state()

    def params(self) -> RandomFill | None:
        lower, upper = _numbers([self.lower, self.upper])
        if lower is None or upper is None:
            return None
        params = RandomFill(lower, upper, self.integers.isChecked())
        return None if check_random(params) else params

    def update_state(self, *_args) -> None:
        lower, upper = _numbers([self.lower, self.upper])
        if lower is None or upper is None:
            self.show_note("Enter a number for each bound.", error=True)
            return
        problem = check_random(RandomFill(lower, upper, self.integers.isChecked()))
        if problem:
            self.show_note(problem, error=True)
        elif self.integers.isChecked():
            self.show_note("Each bound can itself be picked.", error=False)
        else:
            self.show_note("", error=False)


class SequenceDialog(_FillDialog):
    def __init__(self, parent=None, initial: SequenceFill | None = None, cell_count: int = 1):
        super().__init__(parent, "Fill with a Sequence")
        self.cell_count = cell_count
        initial = initial or SequenceFill(1, max(cell_count, 2))
        self.lower = self.number_field("Lower bound:", initial.lower)
        self.upper = self.number_field("Upper bound:", initial.upper)
        self.step = self.number_field(
            "Step:", initial.step, placeholder=f"Blank: spread over the {cell_count} cells")
        self.ascending, self.descending = self.choice(
            "Direction:", ["Ascending", "Descending"], 1 if initial.descending else 0)
        self.down_first, self.across_first = self.choice(
            "Order:", ["Down columns, then across", "Across rows, then down"],
            1 if initial.across_first else 0)
        self.update_state()

    def _read(self) -> SequenceFill | str:
        """The settings, or a message saying what's wrong with them."""
        lower, upper = _numbers([self.lower, self.upper])
        if lower is None or upper is None:
            return "Enter a number for each bound."
        step = None
        if self.step.text().strip():
            step = parse_number(self.step.text())
            if step is None:
                return "The step must be a number, or blank."
        params = SequenceFill(lower, upper, step, self.descending.isChecked(), self.across_first.isChecked())
        return check_sequence(params) or params

    def params(self) -> SequenceFill | None:
        result = self._read()
        return result if isinstance(result, SequenceFill) else None

    def update_state(self, *_args) -> None:
        result = self._read()
        if isinstance(result, str):
            self.show_note(result, error=True)
            return
        values = sequence_values(result, self.cell_count)
        shown = ", ".join(values) if len(values) <= 4 else f"{values[0]}, {values[1]}, … {values[-1]}"
        text = f"Fills {len(values)} of {self.cell_count} cells: {shown}"
        if len(values) < self.cell_count:
            text += f". The sequence ends there; {self.cell_count - len(values)} cells stay unchanged."
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

    def random(self, initial):
        return self._run(RandomDialog(self.parent, initial))

    def sequence(self, initial, cell_count):
        return self._run(SequenceDialog(self.parent, initial, cell_count))

    def uniform(self, initial):
        return self._run(UniformDialog(self.parent, initial))
