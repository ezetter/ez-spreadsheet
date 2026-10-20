"""Pivot tables (Insert > Pivot Table…): a summary of a block of cells (its
source, a header row over rows of data) put at a cell of a sheet, as Google
Sheets makes them.

Its rows are the source's rows grouped by the values of its row columns (one
row for each mix of them, sorted as Sort A → Z sorts); its columns, the
values of its column column, if it has one; and in each cell, an aggregate
(SUM, MEAN, ...) of a value column over the source rows in both groups, for
each value it shows. Grand totals follow: a row, and a column if there are
columns, labeled with the function they're of (Sum, Max, ...). Filters leave out source rows, as the sheet's filter hides them.

A pivot table isn't stored as cells: its sheet works out what it shows
(see layout) whenever anything changes, so it keeps up with its source. The
source takes in rows added just below it. If what it shows would cover
cells with something in them, it shows #REF! instead, at its corner, until
they're cleared.
"""

from dataclasses import dataclass, field, replace

from .autosum import AGGREGATES
from .errors import REF_ERROR, CellError, FormulaError
from .filtering import BLANKS, column_from_json, column_to_json
from .formula import sheet_prefix
from .functions import FUNCTIONS
from .references import cell_name, column_index, column_name, parse_cell_name
from .sorting import _rank

FUNCTION_NAMES = tuple(aggregate.function for aggregate in AGGREGATES)  # what values can be: SUM, MEAN, ...
# A grand total's label: the name of the function it's of (Sum, Max, ...).
TOTAL_NAMES = {"SUM": "Sum", "MEAN": "Mean", "MEDIAN": "Median", "MIN": "Min", "MAX": "Max", "STDDEV": "StdDev",
               "COUNT": "Count", "COUNTA": "CountA"}


def total_label(values) -> str:
    """What labels a pivot table's grand totals: its values' functions, each once (Sum, or Sum / Mean)."""
    return " / ".join(dict.fromkeys(TOTAL_NAMES.get(function, function.capitalize()) for _col, function in values))


@dataclass(frozen=True)
class Pivot:
    row: int  # its top-left cell, on its own sheet
    col: int
    source: str  # the source's sheet
    block: tuple | None  # the source's (top, left, bottom, right), header row first; None once it's deleted
    rows: tuple = ()  # the source columns its rows group by, outermost first
    column: int | None = None  # the source column its columns are the values of, if any
    values: tuple = ()  # ((source column, function name), ...)
    filters: tuple = field(default=())  # ((source column, ColumnFilter), ...)
    totals: bool = True  # grand totals

    def source_name(self) -> str:
        """Where its source is: Sheet1!A1:D20."""
        if self.block is None:
            return f"{sheet_prefix(self.source)}#REF!"
        top, left, bottom, right = self.block
        return f"{sheet_prefix(self.source)}{cell_name(top, left)}:{cell_name(bottom, right)}"

    def moved(self, move, anchor: bool, source: bool) -> "Pivot | None":
        """This pivot table once cells move (move(row, col) is a cell's new
        place, or None if deleted): its corner (if `anchor`; None if that's
        deleted) and its source (if `source`), which grows and shrinks with
        what's inserted and deleted in it, losing the columns deleted."""
        pivot = self
        if anchor:
            corner = move(self.row, self.col)
            if corner is None:
                return None
            pivot = replace(pivot, row=corner[0], col=corner[1])
        if source and self.block is not None:
            top, left, bottom, right = self.block
            edges = [move(row, col) for row in range(top, bottom + 1) for col in (left, right)]
            edges += [move(row, col) for col in range(left, right + 1) for row in (top, bottom)]
            edges = [cell for cell in edges if cell is not None]
            header = [move(top, col) for col in range(left, right + 1)]
            if not edges or not any(header):
                return replace(pivot, block=None)

            def moved_column(col):
                place = move(top, col)
                return None if place is None else place[1]

            rows, cols = [row for row, _ in edges], [col for _, col in edges]
            pivot = replace(
                pivot, block=(min(rows), min(cols), max(rows), max(cols)),
                rows=tuple(c for c in map(moved_column, self.rows) if c is not None),
                column=None if self.column is None else moved_column(self.column),
                values=tuple((c, f) for c, f in ((moved_column(col), f) for col, f in self.values) if c is not None),
                filters=tuple((c, cf) for c, cf in ((moved_column(col), cf) for col, cf in self.filters)
                              if c is not None))
        return pivot


@dataclass(frozen=True)
class PivotCell:
    """What a pivot table shows in one cell."""

    value: object  # float, str, or CellError
    fmt: object = None  # a NumberFormat, its value column's, for an aggregate
    bold: bool = False  # headers and totals


def value_label(function: str, header: str) -> str:
    return f"{function} of {header}"


def headers(sheet, block) -> dict[int, str]:
    """Each source column's label: its header cell's text, or Column B."""
    top, left, _bottom, right = block
    return {col: sheet.display_text(top, col) or f"Column {column_name(col)}" for col in range(left, right + 1)}


def source_bottom(sheet, block) -> int:
    """The source's last row: taking in rows filled in just below it."""
    top, left, bottom, right = block
    while bottom + 1 < sheet.rowCount() and any(sheet.get_cell(bottom + 1, col) for col in range(left, right + 1)):
        bottom += 1
    return bottom


def layout(pivot: Pivot, sheet) -> dict[tuple[int, int], PivotCell]:
    """What the pivot table shows, by (row, col) from its corner. `sheet` is
    its source's sheet (with display_text, value, number_format, get_cell,
    and rowCount), or None if there's no such sheet: then it's #REF!."""
    if sheet is None or pivot.block is None or not pivot.values:
        return {(0, 0): PivotCell(CellError(REF_ERROR))}
    top, left, _bottom, right = pivot.block
    bottom = source_bottom(sheet, pivot.block)
    labels = headers(sheet, pivot.block)
    filters = [(col, column_filter) for col, column_filter in pivot.filters if column_filter.active]
    data = [row for row in range(top + 1, bottom + 1)
            if any(sheet.get_cell(row, col) for col in range(left, right + 1))  # (not blank rows)
            and all(f.shows(sheet.display_text(row, col), sheet.value(row, col)) for col, f in filters)]

    def groups(columns) -> dict[tuple, list[int]]:
        """The data rows by their texts in `columns`, sorted A → Z by their values."""
        found, order = {}, {}
        for row in data:
            key = tuple(sheet.display_text(row, col) for col in columns)
            if key not in found:
                found[key] = []
                order[key] = tuple(_order(sheet.value(row, col)) for col in columns)
            found[key].append(row)
        return {key: found[key] for key in sorted(found, key=order.get)}

    def aggregate(function: str, col: int, rows: list[int], bold: bool = False) -> PivotCell:
        try:
            value = FUNCTIONS[function].compute([[sheet.value(row, col) for row in rows]])
        except FormulaError as error:
            value = CellError(error.code)
        return PivotCell(value, None if FUNCTIONS[function].counts else formats[col], bold)

    formats = {col: _format_of(sheet, col, data) for col, _function in pivot.values}
    row_groups = groups(pivot.rows) if pivot.rows else {}
    column_groups = groups((pivot.column,)) if pivot.column is not None else None
    out = {}
    width = max(1, len(pivot.rows))  # the label columns
    count = len(pivot.values)
    names = [value_label(function, labels[col]) for col, function in pivot.values]

    # The headers.
    if column_groups is None:
        height = 1
        for i, col in enumerate(pivot.rows):
            out[(0, i)] = PivotCell(labels[col], bold=True)
        for v, name in enumerate(names):
            out[(0, width + v)] = PivotCell(name, bold=True)
        blocks = []
    else:
        height = 2
        blocks = [(key[0], rows) for key, rows in column_groups.items()]
        if pivot.totals:
            blocks.append((None, data))
        if count == 1:
            out[(0, 0)] = PivotCell(names[0], bold=True)
            out[(0, width)] = PivotCell(labels[pivot.column], bold=True)
        else:
            out[(0, 0)] = PivotCell(labels[pivot.column], bold=True)
        for i, col in enumerate(pivot.rows):
            out[(1, i)] = PivotCell(labels[col], bold=True)
        for b, (key, _rows) in enumerate(blocks):
            title = total_label(pivot.values) if key is None else key or BLANKS
            out[(1 if count == 1 else 0, width + b * count)] = PivotCell(title, bold=True)
            if count > 1:
                for v, name in enumerate(names):
                    out[(1, width + b * count + v)] = PivotCell(name, bold=True)

    # A row for each group, then the grand total.
    body = list(row_groups.items())
    previous = None
    for r, (key, rows) in enumerate(body, start=height):
        for i, text in enumerate(key):
            if previous is None or key[:i + 1] != previous[:i + 1]:  # (an outer group's label, once)
                out[(r, i)] = PivotCell(text or BLANKS)
        previous = key
        _values(out, r, width, pivot, rows, blocks, aggregate)
    if pivot.totals or not pivot.rows:
        r = height + len(body)
        out[(r, 0)] = PivotCell(total_label(pivot.values), bold=True)
        _values(out, r, width, pivot, data, blocks, aggregate, bold=True)
    return out


def _values(out, r, width, pivot, rows, blocks, aggregate, bold=False) -> None:
    """A row's aggregates: for each value, or each column group's values."""
    count = len(pivot.values)
    if not blocks:
        for v, (col, function) in enumerate(pivot.values):
            out[(r, width + v)] = aggregate(function, col, rows, bold)
        return
    in_row = set(rows)
    for b, (key, block_rows) in enumerate(blocks):
        both = [row for row in block_rows if row in in_row]
        if not both and key is not None:
            continue  # nothing there: blank
        for v, (col, function) in enumerate(pivot.values):
            out[(r, width + b * count + v)] = aggregate(function, col, both, bold or key is None)


def _order(value):
    rank = _rank(value)
    return (1,) if rank is None else (0, rank)  # (empty ones last)


def _format_of(sheet, col: int, rows: list[int]):
    """A value column's number format, as its first number shows it ($, %, ...), if it has one."""
    for row in rows:
        if isinstance(sheet.value(row, col), float):
            fmt = sheet.number_format(row, col)
            return fmt if fmt is not None and fmt.kind not in ("general", "text") else None
    return None


# --- In a file ---

def to_json(pivot: Pivot) -> dict:
    data = {"at": cell_name(pivot.row, pivot.col), "sheet": pivot.source}
    if pivot.block is not None:
        top, left, bottom, right = pivot.block
        data["range"] = f"{cell_name(top, left)}:{cell_name(bottom, right)}"
    data["rows"] = [column_name(col) for col in pivot.rows]
    if pivot.column is not None:
        data["column"] = column_name(pivot.column)
    data["values"] = [{"column": column_name(col), "function": function} for col, function in pivot.values]
    if pivot.filters:
        data["filters"] = {column_name(col): column_to_json(cf) for col, cf in pivot.filters}
    if not pivot.totals:
        data["totals"] = False
    return data


def from_json(data) -> Pivot | None:
    """A pivot table read from a file, or None if it's malformed."""
    try:
        row, col = parse_cell_name(data["at"])
        source = data["sheet"]
        block = None
        if "range" in data:
            start, end = data["range"].split(":")
            (top, left), (bottom, right) = parse_cell_name(start), parse_cell_name(end)
            if min(top, left) < 0 or top > bottom or left > right:
                return None
            block = (top, left, bottom, right)
        rows = tuple(_column(letters) for letters in data.get("rows", []))
        column = _column(data["column"]) if "column" in data else None
        values = tuple((_column(entry["column"]), entry["function"]) for entry in data["values"])
        filters = tuple((_column(letters), column_from_json(entry))
                        for letters, entry in data.get("filters", {}).items())
        totals = data.get("totals", True)
    except (TypeError, KeyError, ValueError, AttributeError):
        return None
    if (min(row, col) < 0 or not isinstance(source, str) or not values or not isinstance(totals, bool)
            or any(function not in FUNCTION_NAMES for _col, function in values)
            or any(cf is None for _col, cf in filters)):
        return None
    return Pivot(row, col, source, block, rows, column, values, filters, totals)


def _column(letters) -> int:
    if not isinstance(letters, str) or not letters.isalpha() or not letters.isascii():
        raise ValueError(letters)
    return column_index(letters.upper())
