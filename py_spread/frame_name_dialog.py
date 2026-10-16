"""Naming a DataFrame that EzSheet puts in the notebook: the field the
DataFrame and Chart dialogs share, and the DataFrame dialog (Notebook >
DataFrame)."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from .appearance import error_color
from .notebook import frame_name_problem

NAME_TIP = "What the DataFrame is called in the notebook's Python, such as sales"
RENAME_TIP = ("The DataFrame this chart draws. A new name renames it in the cell making it, and in the "
              "cells after it that use it.")
FIXED_TIP = ("The DataFrame this chart draws. It can't be renamed here: the cell making it wasn't found, or "
             "isn't written as EzSheet writes it.")


class FrameNameField(QWidget):
    """A DataFrame's name, with a note under it saying why what's typed
    can't be one (`problem`), or what it does. For a new DataFrame, a name
    the notebook already sets (one of `taken`) is fine: the new one replaces
    it from there on. Renaming one, a name the notebook uses (one of `used`)
    isn't. Or the name can just be shown, fixed."""

    changed = Signal()

    def __init__(self, name: str, taken=(), used=(), parent=None):
        super().__init__(parent)
        self.taken, self.used = set(taken), set(used)
        self.renaming = None  # the name being changed, when renaming a DataFrame
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(name)
        self.edit.setToolTip(NAME_TIP)
        self.edit.selectAll()  # typing replaces the name it starts with
        layout.addWidget(self.edit)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.fixed = False
        self.edit.textChanged.connect(lambda _text: self._changed())
        self._changed()

    def name(self) -> str:
        return self.edit.text().strip()

    def problem(self) -> str | None:
        """Why the name typed can't be used, if it can't (a fixed one isn't asked)."""
        if self.fixed:
            return None
        name = self.name()
        problem = frame_name_problem(name)
        if problem is None and self.renaming is not None and name != self.renaming and name in self.used:
            problem = f"The notebook already uses {name}. Choose a name it doesn't."
        return problem

    def set_name(self, name: str) -> None:
        """A name to choose: a new DataFrame's."""
        self._set(name, fixed=False, renaming=None, tip=NAME_TIP)

    def set_renaming(self, name: str, typed: str | None = None) -> None:
        """An existing DataFrame's name, to rename it (to `typed`, to start with, if given)."""
        self._set(typed if typed is not None else name, fixed=False, renaming=name, tip=RENAME_TIP)

    def set_fixed(self, name: str | None) -> None:
        """A name shown, not changed: an existing chart's DataFrame's, when it can't be renamed."""
        self._set(name or "?", fixed=True, renaming=None, tip=FIXED_TIP)

    def _set(self, text: str, fixed: bool, renaming: str | None, tip: str) -> None:
        self.fixed, self.renaming = fixed, renaming
        self.edit.setEnabled(not fixed)
        self.edit.setToolTip(tip)
        self.edit.setText(text)
        self._changed()

    def _changed(self) -> None:
        problem, name = self.problem(), self.name()
        if problem:
            note = problem
        elif self.renaming is not None and name != self.renaming:
            note = f"Renames {self.renaming} to {name} in the cells that use it."
        elif self.renaming is None and not self.fixed and name in self.taken:
            note = f"The notebook already sets {name}; this one replaces it."
        else:
            note = ""
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
