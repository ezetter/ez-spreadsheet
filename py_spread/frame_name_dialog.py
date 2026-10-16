"""Naming a DataFrame that EzSheet puts in the notebook: the field the
DataFrame and Chart dialogs share, and the DataFrame dialog (Notebook >
DataFrame)."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from .appearance import error_color
from .notebook import frame_name_problem

NAME_TIP = "What the DataFrame is called in the notebook's Python, such as sales"
FIXED_TIP = "The DataFrame this chart draws. To rename it, change its name in the cells' code."


class FrameNameField(QWidget):
    """A DataFrame's name, with a note under it saying why what's typed
    can't be one (`problem`), or that the notebook already sets it (one of
    `taken`), which is fine: the new one replaces it from there on."""

    changed = Signal()

    def __init__(self, name: str, taken=(), parent=None):
        super().__init__(parent)
        self.taken = set(taken)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(name)
        self.edit.setToolTip(NAME_TIP)
        self.edit.selectAll()  # typing replaces the name it starts with
        layout.addWidget(self.edit)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self._fixed = False
        self.edit.textChanged.connect(lambda _text: self._changed())
        self._changed()

    def name(self) -> str:
        return self.edit.text().strip()

    def problem(self) -> str | None:
        """Why the name typed can't be used, if it can't (a fixed one isn't asked)."""
        return None if self._fixed else frame_name_problem(self.name())

    def set_name(self, name: str) -> None:
        """A name to change: a new DataFrame's."""
        self._fixed = False
        self.edit.setEnabled(True)
        self.edit.setToolTip(NAME_TIP)
        self.edit.setText(name)
        self._changed()

    def set_fixed(self, name: str | None) -> None:
        """A name shown, not changed: an existing chart's DataFrame's."""
        self._fixed = True
        self.edit.setText(name or "?")
        self.edit.setEnabled(False)
        self.edit.setToolTip(FIXED_TIP)
        self._changed()

    def _changed(self) -> None:
        problem = self.problem()
        taken = not self._fixed and self.name() in self.taken
        note = problem or (f"The notebook already sets {self.name()}; this one replaces it." if taken else "")
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.note.setStyleSheet(f"color: {error_color(self.palette())};" if problem else "")
        self.changed.emit()


class FrameNameDialog(QDialog):
    """What to call the DataFrame Notebook > DataFrame makes of `source`
    (such as "the selected cells, A1:C4"), starting at `name`. `taken` are
    the names the notebook already sets."""

    def __init__(self, parent, name: str, source: str, taken=()):
        super().__init__(parent)
        self.setWindowTitle("DataFrame")
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * 48)
        layout = QVBoxLayout(self)
        intro = QLabel(f"A DataFrame of {source}, in a new notebook cell.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.field = FrameNameField(name, taken)
        form.addRow("Name:", self.field)
        layout.addLayout(form)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.ok_button = self.buttons.button(QDialogButtonBox.Ok)
        self.field.changed.connect(self._update_ok)
        self._update_ok()

    def name(self) -> str:
        return self.field.name()

    def _update_ok(self) -> None:
        self.ok_button.setEnabled(self.field.problem() is None)
