"""The Pivot Table dialog (Insert > Pivot Table…): what a pivot table of a
block of cells shows. Its rows (the columns they group by, outermost
first), its columns (a column whose values they are, or none), its values
(each a column and the aggregate of it: SUM, MEAN, ...), and its filters
(each a column and what of it to leave in, chosen as with the sheet's
filter), and whether it has grand totals."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .autosum import AGGREGATES
from .filter_menu import FilterMenu
from .filtering import CONDITIONS, NO_VALUE, ColumnFilter
from .references import column_name

NO_COLUMN = "(None)"


class PivotDialog(QDialog):
    """Of the block `where` (Sheet1!A1:D20), whose columns are `labels`
    (column -> its header's text), starting as pivot table `start` shows
    (a pivot.Pivot). `values_of(col)` gives a column's values, as its cells
    show them, for its filter's list. `editing`: changing a pivot table
    there is, not making one."""

    def __init__(self, parent, where: str, labels: dict[int, str], values_of, start, editing: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Edit Pivot Table" if editing else "Pivot Table")
        self.labels, self.values_of = labels, values_of
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"A pivot table of {where}, its first row naming the columns."))

        self.row_lines, self.value_lines, self.filter_lines = [], [], []
        self.rows_box = self._section(layout, "Rows", "Add Row", lambda: self.add_row(next(iter(labels))),
                                      "Group the rows by each of these columns' values, the first outermost")
        self.column_box = QComboBox()
        self.column_box.addItem(NO_COLUMN, None)
        for col in labels:
            self.column_box.addItem(self._label(col), col)
        columns = QGroupBox("Columns")
        columns.setToolTip("A column for each of this column's values")
        QVBoxLayout(columns).addWidget(self.column_box)
        layout.addWidget(columns)
        self.values_box = self._section(layout, "Values", "Add Value", lambda: self.add_value(*self._next_value()),
                                        "What to show: an aggregate of a column over each group's rows")
        self.filters_box = self._section(layout, "Filters", "Add Filter",
                                         lambda: self.add_filter(next(iter(labels)), ColumnFilter()),
                                         "Leave out rows by their values in a column")
        self.totals_box = QCheckBox("Show grand totals")
        self.totals_box.setChecked(start.totals)
        layout.addWidget(self.totals_box)
        self.problem = QLabel()
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.Ok)
        self.ok_button.setText("Update" if editing else "Choose Where…")
        if not editing:
            self.ok_button.setToolTip("Then click the cell for its top-left corner, on this sheet or another")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for col in start.rows:
            self.add_row(col)
        self.column_box.setCurrentIndex(max(0, self.column_box.findData(start.column)))
        for col, function in start.values:
            self.add_value(col, function)
        for col, column_filter in start.filters:
            self.add_filter(col, column_filter)
        self._check()

    def _section(self, layout, title: str, add: str, slot, tip: str) -> QVBoxLayout:
        box = QGroupBox(title)
        box.setToolTip(tip)
        inner = QVBoxLayout(box)
        lines = QVBoxLayout()
        inner.addLayout(lines)
        button = QPushButton(add)
        button.clicked.connect(lambda _checked=False: slot())
        inner.addWidget(button, 0, Qt.AlignLeft)
        layout.addWidget(box)
        return lines

    def _label(self, col: int) -> str:
        return f"{self.labels[col]} (column {column_name(col)})"

    def _columns(self, current: int) -> QComboBox:
        box = QComboBox()
        for col in self.labels:
            box.addItem(self._label(col), col)
        box.setCurrentIndex(max(0, box.findData(current)))
        return box

    def _line(self, section: QVBoxLayout, lines: list, widgets: list) -> QWidget:
        """A line of a section: its widgets, and Remove."""
        line = QWidget()
        row = QHBoxLayout(line)
        row.setContentsMargins(0, 0, 0, 0)
        for widget in widgets:
            row.addWidget(widget, 1 if isinstance(widget, (QComboBox, QLabel)) else 0)  # (the lists widen, not buttons)
        remove = QPushButton("Remove")
        remove.clicked.connect(lambda _checked=False: self._remove(lines, line))
        row.addWidget(remove)
        section.addWidget(line)
        lines.append((line, *widgets))
        self._check()
        return line

    def _remove(self, lines: list, line: QWidget) -> None:
        lines[:] = [entry for entry in lines if entry[0] is not line]
        line.deleteLater()
        self._check()

    def add_row(self, col: int) -> None:
        self._line(self.rows_box, self.row_lines, [self._columns(col)])

    def add_value(self, col: int, function: str) -> None:
        functions = QComboBox()
        for aggregate in AGGREGATES:
            functions.addItem(aggregate.function, aggregate.function)
            functions.setItemData(functions.count() - 1, aggregate.label, Qt.ToolTipRole)  # Standard Deviation
        functions.setCurrentIndex(max(0, functions.findData(function)))
        self._line(self.values_box, self.value_lines, [self._columns(col), functions])

    def _next_value(self) -> tuple[int, str]:
        """A new value's column: the last one, unless it's in use already."""
        used = {col for col, _function in self.pivot_values()}
        return next((col for col in reversed(list(self.labels)) if col not in used), list(self.labels)[-1]), "SUM"

    def add_filter(self, col: int, column_filter: ColumnFilter) -> None:
        columns, choose, summary = self._columns(col), QPushButton("Values…"), QLabel()
        choose.setToolTip("Choose which of the column's rows to leave in")
        line = self._line(self.filters_box, self.filter_lines, [columns, choose, summary])
        line.column_filter = column_filter
        self._summarize(line)
        columns.currentIndexChanged.connect(lambda _index: self._set_filter(line, ColumnFilter()))
        choose.clicked.connect(lambda _checked=False: self.choose_filter(line))

    def choose_filter(self, line) -> FilterMenu:
        """A filter's Values…: the sheet's filter menu, for its column."""
        col = next(entry for entry in self.filter_lines if entry[0] is line)[1].currentData()
        menu = FilterMenu(self.values_of(col), line.column_filter, self, sortable=False)
        menu.applied.connect(lambda column_filter: self._set_filter(line, column_filter))
        self.filter_menu = menu  # kept while it's shown
        button = next(entry for entry in self.filter_lines if entry[0] is line)[2]
        menu.popup(button.mapToGlobal(button.rect().bottomLeft()))
        return menu

    def _set_filter(self, line, column_filter: ColumnFilter) -> None:
        line.column_filter = column_filter
        self._summarize(line)

    def _summarize(self, line) -> None:
        summary = next(entry for entry in self.filter_lines if entry[0] is line)[3]
        summary.setText(describe(line.column_filter))

    def _check(self) -> None:
        """OK needs a value to show."""
        problem = None if self.value_lines else "Add a value to show."
        self.problem.setText(problem or "")
        self.problem.setVisible(problem is not None)
        self.ok_button.setEnabled(problem is None)

    def pivot_rows(self) -> tuple[int, ...]:
        return tuple(dict.fromkeys(columns.currentData() for _line, columns in self.row_lines))

    def pivot_column(self) -> int | None:
        return self.column_box.currentData()

    def pivot_values(self) -> tuple[tuple[int, str], ...]:
        return tuple((columns.currentData(), functions.currentData())
                     for _line, columns, functions in self.value_lines)

    def pivot_filters(self) -> tuple[tuple[int, ColumnFilter], ...]:
        found = {}
        for line, columns, _choose, _summary in self.filter_lines:
            if line.column_filter.active:
                found[columns.currentData()] = line.column_filter  # (a column's last, if it's there twice)
        return tuple(sorted(found.items()))

    def choice(self) -> dict:
        """What's chosen, as a pivot.Pivot's rows, column, values, filters, and totals."""
        return {"rows": self.pivot_rows(), "column": self.pivot_column(), "values": self.pivot_values(),
                "filters": self.pivot_filters(), "totals": self.totals_box.isChecked()}


def describe(column_filter: ColumnFilter) -> str:
    """A filter, briefly: All, Leaving out 2 values, Greater than 500, ..."""
    parts = []
    if column_filter.hidden:
        count = len(column_filter.hidden)
        parts.append(f"Leaving out {count} value{'s' if count != 1 else ''}")
    if column_filter.condition != "none":
        label = dict(CONDITIONS)[column_filter.condition]
        parts.append(label if column_filter.condition in NO_VALUE else f"{label} {column_filter.value}")
    return "; ".join(parts) or "All"
