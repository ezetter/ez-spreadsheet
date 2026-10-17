"""A sheet's filter, as Google Sheets has one (Data > Create a Filter): a block
of columns whose first row is its header, with a filter button in each of
its cells; the rows below it, to the last of the sheet's data, are shown or
hidden by what's chosen for each column: values to hide (shown as the cells
show them; "" for an empty one), and a condition (greater than 100, text
contains "east", ...). A row is shown if every column's filter shows it.
"""

from dataclasses import dataclass, field

from .formula import parse_number
from .references import cell_name, column_index, column_name

CONDITIONS = (  # (key, as the filter menu says it): Google Sheets' "Filter by condition", but dates and formulas
    ("none", "None"), ("empty", "Is empty"), ("not empty", "Is not empty"),
    ("contains", "Text contains"), ("not contains", "Text does not contain"),
    ("starts", "Text starts with"), ("ends", "Text ends with"), ("exactly", "Text is exactly"),
    ("greater", "Greater than"), ("greater or equal", "Greater than or equal to"),
    ("less", "Less than"), ("less or equal", "Less than or equal to"),
    ("equal", "Is equal to"), ("not equal", "Is not equal to"),
)
NO_VALUE = {"none", "empty", "not empty"}  # conditions without a value to compare with
_NUMERIC = {"greater": float.__gt__, "greater or equal": float.__ge__, "less": float.__lt__,
            "less or equal": float.__le__}
BLANK = ""  # an empty cell's value, among the values to hide


@dataclass(frozen=True)
class ColumnFilter:
    """What one column shows: not the `hidden` values, and only cells
    meeting `condition` (with `value`, for the ones that need one)."""

    hidden: frozenset = frozenset()
    condition: str = "none"
    value: str = ""

    @property
    def active(self) -> bool:
        return bool(self.hidden) or self.condition != "none"

    def shows(self, text: str, value) -> bool:
        """Whether a cell (as it's shown, and its value) passes this column's filter."""
        if text in self.hidden:
            return False
        condition, wanted = self.condition, self.value
        if condition == "none":
            return True
        if condition == "empty":
            return text == ""
        if condition == "not empty":
            return text != ""
        folded, wanted_folded = text.casefold(), wanted.casefold()
        if condition == "contains":
            return wanted_folded in folded
        if condition == "not contains":
            return wanted_folded not in folded
        if condition == "starts":
            return folded.startswith(wanted_folded)
        if condition == "ends":
            return folded.endswith(wanted_folded)
        if condition == "exactly":
            return text == wanted
        number = parse_number(wanted)
        if condition in _NUMERIC:  # numbers only: text never passes
            return isinstance(value, float) and number is not None and _NUMERIC[condition](value, number)
        same = (value == number) if isinstance(value, float) and number is not None else folded == wanted_folded
        return same if condition == "equal" else not same


@dataclass(frozen=True)
class SheetFilter:
    """The filter: its header row and columns, and each filtered column's ColumnFilter."""

    top: int
    left: int
    right: int
    columns: tuple = field(default=())  # ((col, ColumnFilter), ...), by column

    def column(self, col: int) -> ColumnFilter:
        return dict(self.columns).get(col, ColumnFilter())

    def with_column(self, col: int, column_filter: ColumnFilter) -> "SheetFilter":
        """This filter with a column's changed (one that does nothing, dropped)."""
        columns = dict(self.columns)
        columns.pop(col, None)
        if column_filter.active:
            columns[col] = column_filter
        return SheetFilter(self.top, self.left, self.right, tuple(sorted(columns.items())))

    def hidden_rows(self, bottom: int, text_of, value_of) -> set[int]:
        """The rows from below the header to `bottom` that the filter hides."""
        hidden = set()
        for row in range(self.top + 1, bottom + 1):
            if not all(column_filter.shows(text_of(row, col), value_of(row, col))
                       for col, column_filter in self.columns):
                hidden.add(row)
        return hidden

    def moved(self, move) -> "SheetFilter | None":
        """The filter once its cells move (move(row, col) is a cell's new
        place, or None if deleted): over the header cells left, or None if
        none are (its header row's deleted, or all its columns)."""
        places = [place for place in (move(self.top, col) for col in range(self.left, self.right + 1)) if place]
        if not places:
            return None
        columns = []
        for col, column_filter in self.columns:
            dest = move(self.top, col)
            if dest is not None:
                columns.append((dest[1], column_filter))
        cols = [col for _row, col in places]
        return SheetFilter(places[0][0], min(cols), max(cols), tuple(sorted(columns)))


def to_json(sheet_filter: SheetFilter) -> dict:
    data = {"header": f"{cell_name(sheet_filter.top, sheet_filter.left)}:"
                      f"{cell_name(sheet_filter.top, sheet_filter.right)}"}
    columns = {}
    for col, column_filter in sheet_filter.columns:
        entry = {}
        if column_filter.hidden:
            entry["hidden"] = sorted(column_filter.hidden)
        if column_filter.condition != "none":
            entry["condition"] = column_filter.condition
            if column_filter.condition not in NO_VALUE:
                entry["value"] = column_filter.value
        columns[column_name(col)] = entry
    if columns:
        data["columns"] = columns
    return data


def from_json(data, parse_cell) -> SheetFilter | None:
    """A filter read from a file (parse_cell("A1") is (row, col), or raises
    ValueError), or None if it's malformed."""
    try:
        start, end = data["header"].split(":")
        (top, left), (end_row, right) = parse_cell(start), parse_cell(end)
    except (TypeError, KeyError, ValueError, AttributeError):
        return None
    if end_row != top or right < left:
        return None
    columns = data.get("columns", {})
    if not isinstance(columns, dict):
        return None
    conditions = {key for key, _label in CONDITIONS}
    sheet_filter = SheetFilter(top, left, right)
    for letters, entry in columns.items():
        if not isinstance(letters, str) or not letters.isalpha() or not isinstance(entry, dict):
            return None
        col = column_index(letters.upper())
        hidden, condition, value = entry.get("hidden", []), entry.get("condition", "none"), entry.get("value", "")
        if (not left <= col <= right or not isinstance(hidden, list) or not all(isinstance(h, str) for h in hidden)
                or condition not in conditions or not isinstance(value, str)):
            return None
        sheet_filter = sheet_filter.with_column(col, ColumnFilter(frozenset(hidden), condition, value))
    return sheet_filter
