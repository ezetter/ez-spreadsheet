"""The Insert Cells and Delete Cells dialogs: which way to shift cells."""

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QRadioButton, QVBoxLayout

SHIFT_LABELS = {
    "down": "Shift cells down",
    "right": "Shift cells right",
    "up": "Shift cells up",
    "left": "Shift cells left",
}


class ShiftDialog(QDialog):
    """Radio buttons for the four shifts. Choices that can't work for the
    selection are disabled, with the reason as their tooltip."""

    title = ""
    prompt = ""
    order = ("down", "right", "up", "left")

    def __init__(self, parent=None, shift: str | None = None, problems: dict[str, str] | None = None):
        super().__init__(parent)
        self.setWindowTitle(self.title)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.prompt))
        problems = problems or {}
        if shift is None or shift in problems:
            shift = next(key for key in self.order if key not in problems)
        self.buttons = {}
        for key in self.order:
            button = QRadioButton(SHIFT_LABELS[key])
            button.setChecked(key == shift)
            if key in problems:
                button.setEnabled(False)
                button.setToolTip(problems[key])
            layout.addWidget(button)
            self.buttons[key] = button
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def shift(self) -> str:
        return next(key for key, button in self.buttons.items() if button.isChecked())


class InsertCellsDialog(ShiftDialog):
    title = "Insert Cells"
    prompt = "Insert blank cells in place of the selection, and:"


class DeleteCellsDialog(ShiftDialog):
    title = "Delete Cells"
    prompt = "Delete the selected cells, and fill the gap by moving:"
    order = ("up", "left", "down", "right")


def ask_shift(dialog_class, parent, shift: str, problems: dict[str, str]) -> str | None:
    """Show the dialog; the chosen shift, or None if cancelled. Every shift
    being impossible also gives None, without showing the dialog."""
    if set(problems) >= set(SHIFT_LABELS):
        return None
    dialog = dialog_class(parent, shift, problems)
    return dialog.shift() if dialog.exec() == QDialog.Accepted else None
