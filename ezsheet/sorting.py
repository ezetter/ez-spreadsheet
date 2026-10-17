"""Sorting rows by their columns' values, as Google Sheets does: A → Z puts
numbers first (smallest first), then text (ignoring case), then errors;
Z → A the other way round; empty cells go last either way. Ties keep their
order, so sorting by one column and then another sorts by both.

The rows move whole, within the block sorted: each cell with its text,
number format, and style. A formula's relative references move with it, as
when it's copied, so =B2*C2 in row 2 is =B7*C7 in row 7.
"""

ASCENDING, DESCENDING = True, False
ARROWS = {ASCENDING: "A → Z", DESCENDING: "Z → A"}


def _rank(value):
    """How a value sorts: None for an empty cell (always last)."""
    if value is None or value == "":
        return None
    if isinstance(value, float):
        return (0, value)
    if isinstance(value, str):
        return (1, value.casefold())
    return (2, str(value))  # an error, such as #DIV/0!


def sorted_rows(rows, value_of, keys) -> list[int]:
    """The rows in their sorted order: value_of(row, col) is a cell's value;
    `keys` are (col, ascending) pairs, the first sorting most."""
    order = list(rows)
    for col, ascending in reversed(keys):  # (each sort keeps the last one's order among ties)
        ranks = {row: _rank(value_of(row, col)) for row in order}
        present = sorted((row for row in order if ranks[row] is not None), key=ranks.get, reverse=not ascending)
        order = present + [row for row in order if ranks[row] is None]
    return order


def has_header(value_of, bold_of, top: int, left: int, bottom: int, right: int) -> bool:
    """A guess at whether a block's first row is its header, to keep it on
    top: it's all text, and has numbers below (Month over 1200), or it's bold
    and the row below isn't. A plain list of text has none."""
    if bottom <= top:
        return False
    first = {col: value_of(top, col) for col in range(left, right + 1)}
    filled = {col: value for col, value in first.items() if value not in (None, "")}
    if not filled or not all(isinstance(value, str) for value in filled.values()):
        return False
    if any(isinstance(value_of(row, col), float) for col in filled for row in range(top + 1, bottom + 1)):
        return True
    return all(bold_of(top, col) for col in filled) and not all(bold_of(top + 1, col) for col in filled)
