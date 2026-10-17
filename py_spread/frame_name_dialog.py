"""Naming a DataFrame that EZ Sheet puts in the notebook: the field the
DataFrame and Chart dialogs share, and the DataFrame dialog (Notebook >
DataFrame), which also renames the notebook's DataFrames and updates their
data."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from .appearance import error_color
from .graphs import frame_labels
from .notebook import frame_name_problem

NAME_TIP = "What the DataFrame is called in the notebook's Python, such as sales"
RENAME_TIP = ("The DataFrame this chart draws. A new name renames it in the cell making it, and in the "
              "cells after it that use it.")
FRAME_RENAME_TIP = ("The DataFrame's name. A new name renames it in its cell, and in the cells after it that "
                    "use it.")
NEW_FRAME = "New DataFrame"
FIXED_TIP = ("The DataFrame this chart draws. It can't be renamed here: the cell making it wasn't found, or "
             "isn't written as EZ Sheet writes it.")


class FrameNameField(QWidget):
    """A DataFrame's name, with a note under it saying why what's typed
    can't be one (`problem`), or what it does. For a new DataFrame, a name
    the notebook already sets (one of `taken`) is fine: the new one replaces
    it from there on. Renaming one, a name the notebook uses (one of `used`)
    isn't. Or the name can just be shown, fixed.

    With `choices` ([(name, label)], the notebook's DataFrames), it's a box
    to type in that lists them too: choosing one puts its name in, which
    means that DataFrame, not a new one of that name (see chosen)."""

    changed = Signal()

    def __init__(self, name: str, taken=(), used=(), parent=None, choices=None):
        super().__init__(parent)
        self.taken, self.used = set(taken), set(used)
        self.renaming = None  # the name being changed, when renaming a DataFrame
        self.choices = dict(choices or [])  # name -> label
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.box = None
        if choices is not None:
            self.box = QComboBox()
            self.box.setEditable(True)
            self.box.setInsertPolicy(QComboBox.NoInsert)  # a name typed isn't one to choose
            self.box.setCompleter(None)  # (it would complete names to the labels)
            for choice, label in self.choices.items():
                self.box.addItem(label, choice)
            self.box.setCurrentIndex(-1)
            self.box.activated.connect(lambda index: self.edit.setText(self.box.itemData(index)))
            self.edit = self.box.lineEdit()
            self.edit.setText(name)
            layout.addWidget(self.box)
        else:
            self.edit = QLineEdit(name)
            layout.addWidget(self.edit)
        self.edit.setToolTip(NAME_TIP)
        self.edit.selectAll()  # typing replaces the name it starts with
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.fixed = False
        self.edit.textChanged.connect(lambda _text: self._changed())
        self._changed()

    def name(self) -> str:
        return self.edit.text().strip()

    def chosen(self) -> str | None:
        """The DataFrame chosen from the choices (or typed), for a new chart of it; None for a new one."""
        name = self.name()
        return name if self.renaming is None and not self.fixed and name in self.choices else None

    def problem(self) -> str | None:
        """Why the name typed can't be used, if it can't (a fixed one isn't asked)."""
        if self.fixed or self.chosen() is not None:
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
        if self.box is not None:
            self.box.setEnabled(not fixed)
            # A chart's own DataFrame can be renamed, not changed for another.
            for index in range(self.box.count()):
                self.box.model().item(index).setEnabled(renaming is None)
        self.edit.setEnabled(not fixed)
        self.edit.setToolTip(tip)
        self.edit.setText(text)
        self.edit.selectAll()  # typing replaces it
        self._changed()

    def _changed(self) -> None:
        problem, name = self.problem(), self.name()
        if problem:
            note = problem
        elif self.chosen() is not None:
            note = f"Charts the notebook's {self.choices[name]}."
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
    """Notebook > DataFrame's dialog: a new DataFrame of `source` (such as
    "the selected cells, A1:C4", or "the whole sheet, A1:D19"), called `name`
    to start with. With the notebook's `frames` (FrameCells), a DataFrame
    list chooses New DataFrame or one of them, starting at frames[current]
    (None: New DataFrame), to rename, or to update its data from `source`
    (Update data, unchecked to start with), or both. `problem` says why
    `source` has no data, so there's nothing for a new DataFrame or an update.
    `taken` are the names the notebook already sets (fine for a new
    DataFrame, which replaces it), and `used` the ones it uses (not for a
    rename)."""

    def __init__(self, parent, name: str, source: str, taken=(), frames=(), current: int | None = None,
                 problem: str | None = None, used=()):
        super().__init__(parent)
        self.setWindowTitle("DataFrame")
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * 52)
        self.frames = list(frames)
        self.source, self.problem = source, problem
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.form = form = QFormLayout()
        self.frame_box = None
        if self.frames:
            self.frame_box = QComboBox()
            self.frame_box.addItem(NEW_FRAME, None)
            for index, label in enumerate(frame_labels(self.frames)):
                self.frame_box.addItem(label, index)
            form.addRow("DataFrame:", self.frame_box)
        self.field = FrameNameField(name, taken, used)
        form.addRow("Name:", self.field)
        self.update_box = QCheckBox(f"Update its data from {source}")
        form.addRow("", self.update_box)
        layout.addLayout(form)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.ok_button = self.buttons.button(QDialogButtonBox.Ok)
        self._typed = {None: name}  # the names typed: a new DataFrame's, and the frames' (by index)
        self.field.changed.connect(self._name_changed)
        self.update_box.toggled.connect(lambda _checked: self._update_ok())
        if self.frame_box is not None:
            self.frame_box.setCurrentIndex(0 if current is None else current + 1)
            self.frame_box.currentIndexChanged.connect(lambda _index: self._show())
        self._show()

    def chosen_frame(self) -> int | None:
        """Which of the frames to change (an index), or None for a new DataFrame."""
        return self.frame_box.currentData() if self.frame_box is not None else None

    def name(self) -> str:
        return self.field.name()

    def update(self) -> bool:
        """Whether to write a DataFrame's data afresh from the sheet."""
        return self.chosen_frame() is not None and self.update_box.isChecked()

    def _show(self) -> None:
        index = self.chosen_frame()
        self.form.setRowVisible(self.update_box, index is not None)
        if index is None:
            self.field.set_name(self._typed[None])
            if self.problem is not None:
                self._say(f"A new DataFrame of {self.source} can't be made. {self.problem}", error=True)
            else:
                self._say(f"A DataFrame of {self.source}, in a new notebook cell.")
        else:
            frame = self.frames[index]
            self.field.set_renaming(frame.name, self._typed.get(index))
            self.field.edit.setToolTip(FRAME_RENAME_TIP)
            summary = f"Rename {frame.name}, or update its data, or both. Its cell runs again when you click OK."
            if frame.data is None and frame.updatable:  # your own code makes it
                summary += f" Updating its data replaces {_shortened(frame.code)} with the sheet's."
            self._say(summary)
            if not frame.updatable:
                tip = f"It's made along with others ({_shortened(frame.code)}), so its data can't be written here."
            else:
                tip = self.problem or (f"Write its data afresh from {self.source}, in its cell. The cells depending "
                                       "on it run again.")
            self.update_box.setEnabled(self.problem is None and frame.updatable)
            self.update_box.setToolTip(tip)
            if not self.update_box.isEnabled():
                self.update_box.setChecked(False)
        self._update_ok()

    def _say(self, text: str, error: bool = False) -> None:
        self.summary.setText(text)
        self.summary.setStyleSheet(f"color: {error_color(self.palette())};" if error else "")

    def _name_changed(self) -> None:
        self._typed[self.chosen_frame()] = self.field.edit.text()  # kept while another is looked at
        self._update_ok()

    def _update_ok(self) -> None:
        """OK, if the name will do, and a new DataFrame has data."""
        new = self.chosen_frame() is None
        self.ok_button.setEnabled(self.field.problem() is None and not (new and self.problem is not None))


def _shortened(code: str, most: int = 60) -> str:
    """Code's first line, cut short if it's long."""
    line = code.splitlines()[0] if code else ""
    return line if len(line) <= most and "\n" not in code else line[:most - 1].rstrip() + "…"
