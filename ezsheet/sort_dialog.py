"""The Sort Range dialog (Data > Sort Range…): whether the range's first row is
a header (kept on top, its labels naming the columns), and the columns to
sort by, each A → Z or Z → A: the first most, then the next among ties."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .references import column_name
from .sorting import ARROWS, ASCENDING, DESCENDING


class SortDialog(QDialog):
    """Sorting the block `where` (such as "A1:D20") of columns left..right.
    `labels(col)` gives a column's header label when the first row's a header
    (the first row starts checked as one if `header`). Starts sorting by
    `col`, A → Z."""

    def __init__(self, parent, where: str, left: int, right: int, labels, header: bool, col: int):
        super().__init__(parent)
        self.setWindowTitle("Sort Range")
        self.left, self.right, self.labels = left, right, labels
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Sort the rows of {where}."))
        self.header_box = QCheckBox("Data has header row")
        self.header_box.setToolTip("Keep the first row on top, and name the columns by it")
        self.header_box.setChecked(header)
        layout.addWidget(self.header_box)
        self.grid = QGridLayout()
        layout.addLayout(self.grid)
        self.keys = []  # (column box, direction box, remove button)
        self.add_button = QPushButton("Add another sort column")
        self.add_button.clicked.connect(lambda: self.add_key(self.left, ASCENDING))
        layout.addWidget(self.add_button)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Sort")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.header_box.toggled.connect(lambda _checked: self._name_columns())
        self.add_key(col, ASCENDING)

    def add_key(self, col: int, ascending: bool) -> None:
        row = len(self.keys)
        column_box, direction_box = QComboBox(), QComboBox()
        for each in range(self.left, self.right + 1):
            column_box.addItem("", each)
        column_box.setCurrentIndex(max(0, column_box.findData(col)))
        for direction in (ASCENDING, DESCENDING):
            direction_box.addItem(ARROWS[direction], direction)
        direction_box.setCurrentIndex(0 if ascending else 1)
        remove = QPushButton("Remove")
        remove.clicked.connect(lambda _checked=False, b=column_box: self._remove(b))
        self.grid.addWidget(QLabel("Sort by" if row == 0 else "then by"), row, 0)
        self.grid.addWidget(column_box, row, 1)
        self.grid.addWidget(direction_box, row, 2)
        self.grid.addWidget(remove, row, 3)
        self.keys.append((column_box, direction_box, remove))
        self._name_columns()

    def _remove(self, column_box) -> None:
        index = next(i for i, key in enumerate(self.keys) if key[0] is column_box)
        kept = [(k[0].currentData(), k[1].currentData()) for i, k in enumerate(self.keys) if i != index]
        for widgets in self.keys:
            for widget in widgets:
                widget.deleteLater()
        for i in range(self.grid.count() - 1, -1, -1):
            item = self.grid.takeAt(i)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.keys = []
        for col, ascending in kept:
            self.add_key(col, ascending)

    def _name_columns(self) -> None:
        """Each column by its letter, and its header label if the first row's a header."""
        header = self.header_box.isChecked()
        for column_box, _direction, remove in self.keys:
            for index in range(column_box.count()):
                col = column_box.itemData(index)
                label = self.labels(col) if header else ""
                column_box.setItemText(index, f"Column {column_name(col)}" + (f" ({label})" if label else ""))
            remove.setEnabled(len(self.keys) > 1)

    def has_header(self) -> bool:
        return self.header_box.isChecked()

    def sort_keys(self) -> list[tuple[int, bool]]:
        """(col, ascending) for each sort column, the first most."""
        return [(column_box.currentData(), direction_box.currentData()) for column_box, direction_box, _ in self.keys]
