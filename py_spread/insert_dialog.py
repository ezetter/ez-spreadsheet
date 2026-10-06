"""The Insert Cells dialog: which way to shift the cells in the way."""

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QRadioButton, QVBoxLayout

SHIFT_LABELS = {
    "down": "Shift cells down",
    "right": "Shift cells right",
    "up": "Shift cells up",
    "left": "Shift cells left",
}


class InsertCellsDialog(QDialog):
    def __init__(self, parent=None, shift: str = "down"):
        super().__init__(parent)
        self.setWindowTitle("Insert Cells")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Insert blank cells in place of the selection, and:"))
        self.buttons = {}
        for key, label in SHIFT_LABELS.items():
            button = QRadioButton(label)
            button.setChecked(key == shift)
            layout.addWidget(button)
            self.buttons[key] = button
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def shift(self) -> str:
        return next(key for key, button in self.buttons.items() if button.isChecked())


def ask_shift(parent, shift: str) -> str | None:
    """Show the dialog; the chosen shift, or None if cancelled."""
    dialog = InsertCellsDialog(parent, shift)
    return dialog.shift() if dialog.exec() == QDialog.Accepted else None
