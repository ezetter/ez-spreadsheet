"""The Insert Cells dialog: which way to shift the cells in the way."""

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QRadioButton, QVBoxLayout

SHIFT_LABELS = {
    "down": "Shift cells down",
    "right": "Shift cells right",
    "up": "Shift cells up",
    "left": "Shift cells left",
}


class InsertCellsDialog(QDialog):
    """Choices that can't work for the selection are disabled, with the
    reason as their tooltip."""

    def __init__(self, parent=None, shift: str = "down", problems: dict[str, str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Insert Cells")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Insert blank cells in place of the selection, and:"))
        problems = problems or {}
        if shift in problems:
            shift = next(key for key in SHIFT_LABELS if key not in problems)
        self.buttons = {}
        for key, label in SHIFT_LABELS.items():
            button = QRadioButton(label)
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


def ask_shift(parent, shift: str, problems: dict[str, str]) -> str | None:
    """Show the dialog; the chosen shift, or None if cancelled."""
    dialog = InsertCellsDialog(parent, shift, problems)
    return dialog.shift() if dialog.exec() == QDialog.Accepted else None
