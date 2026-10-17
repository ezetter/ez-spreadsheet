"""The Load Data to Sheet dialog: which of the notebook's DataFrames to put
in the sheet."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QVBoxLayout

from .load_data import MAX_CELLS, describe, too_big


class LoadDataDialog(QDialog):
    """A list of the DataFrames, (name, rows, columns) each. Ones too big for
    the sheet are listed but can't be chosen."""

    def __init__(self, parent, frames: list[tuple[str, int, int]], cell: str):
        super().__init__(parent)
        self.setWindowTitle("Load Data to Sheet")
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * 50)
        layout = QVBoxLayout(self)
        intro = QLabel(f"Choose a DataFrame from the notebook to put in the sheet, starting at {cell}. "
                       "Its column names go in the first row. It replaces what's in those cells; "
                       "Undo puts them back.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.list = QListWidget()
        for name, rows, columns in frames:
            item = QListWidgetItem(describe(name, rows, columns))
            item.setData(Qt.UserRole, name)
            if too_big(rows, columns):
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled & ~Qt.ItemIsSelectable)
                item.setToolTip(f"Too big: the sheet can take up to {MAX_CELLS:,} values.")
            self.list.addItem(item)
        layout.addWidget(self.list)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.list.itemDoubleClicked.connect(lambda item: item.flags() & Qt.ItemIsEnabled and self.accept())
        self.list.currentItemChanged.connect(self._update_ok)
        first = next((i for i in range(self.list.count()) if self.list.item(i).flags() & Qt.ItemIsEnabled), None)
        if first is not None:
            self.list.setCurrentRow(first)
        self._update_ok()

    def chosen(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None and item.flags() & Qt.ItemIsEnabled else None

    def _update_ok(self, *_args) -> None:
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(self.chosen() is not None)
