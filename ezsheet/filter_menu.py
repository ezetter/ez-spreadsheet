"""A filter button's menu, as Google Sheets has it: sort the filter's rows by
the column, filter by condition, or filter by values (a list of the column's
values, each checked if it's shown), then OK."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .filtering import BLANK, CONDITIONS, NO_VALUE, ColumnFilter

BLANKS = "(Blanks)"  # how the list shows an empty cell's value


class FilterMenu(QMenu):
    """For one column: `values` are its values as its cells show them
    (sorted, "" for empty), and `current` its ColumnFilter now. `applied`
    gives the new ColumnFilter on OK; `sort` asks to sort by the column."""

    applied = Signal(object)
    sort = Signal(bool)  # ascending

    def __init__(self, values: list[str], current: ColumnFilter, parent=None):
        super().__init__(parent)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)
        for ascending, label in ((True, "Sort A → Z"), (False, "Sort Z → A")):
            button = QPushButton(label)
            button.setFlat(True)
            button.setStyleSheet("text-align: left;")
            button.clicked.connect(lambda _checked=False, a=ascending: self._sort(a))
            layout.addWidget(button)

        layout.addWidget(_heading("Filter by condition"))
        self.condition_box = QComboBox()
        for key, label in CONDITIONS:
            self.condition_box.addItem(label, key)
        self.condition_box.setCurrentIndex(max(0, self.condition_box.findData(current.condition)))
        layout.addWidget(self.condition_box)
        self.value_edit = QLineEdit(current.value)
        self.value_edit.setPlaceholderText("Value")
        layout.addWidget(self.value_edit)
        self.condition_box.currentIndexChanged.connect(lambda _index: self._condition_changed())

        layout.addWidget(_heading("Filter by values"))
        links = QHBoxLayout()
        for label, checked in (("Select all", True), ("Clear", False)):
            button = QPushButton(label)
            button.setFlat(True)
            button.clicked.connect(lambda _checked=False, c=checked: self._check_all(c))
            links.addWidget(button)
        links.addStretch()
        layout.addLayout(links)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.textChanged.connect(self._search)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setMinimumHeight(160)
        for value in values:
            item = QListWidgetItem(value if value != BLANK else BLANKS)
            item.setData(Qt.UserRole, value)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if value in current.hidden else Qt.Checked)
            self.list.addItem(item)
        layout.addWidget(self.list)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self.ok_button = buttons.button(QDialogButtonBox.Ok)
        action = QWidgetAction(self)
        action.setDefaultWidget(panel)
        self.addAction(action)
        self._condition_changed()

    def column_filter(self) -> ColumnFilter:
        """What's chosen: the values unchecked are hidden, and the condition."""
        hidden = frozenset(self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                           if self.list.item(i).checkState() != Qt.Checked)
        condition = self.condition_box.currentData()
        return ColumnFilter(hidden, condition, "" if condition in NO_VALUE else self.value_edit.text())

    def _condition_changed(self) -> None:
        self.value_edit.setEnabled(self.condition_box.currentData() not in NO_VALUE)

    def _check_all(self, checked: bool) -> None:
        """Select all or Clear: the values shown by the search."""
        for i in range(self.list.count()):
            item = self.list.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _search(self, text: str) -> None:
        folded = text.casefold()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(folded not in item.text().casefold())

    def _apply(self) -> None:
        self.close()
        self.applied.emit(self.column_filter())

    def _sort(self, ascending: bool) -> None:
        self.close()
        self.sort.emit(ascending)


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label
