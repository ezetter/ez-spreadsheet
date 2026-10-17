"""Cell and column names, usable in formulas.

A cell name is an alias for one cell, such as r for B2 (=PI*r^2). It always
means the same cell, like an anchored reference ($B$2): copying a formula that
uses it doesn't change which cell it refers to.

A column name is an alias for a column: with column C named t, t1 means $C1,
t2 means $C2, and so on. Like $C1, the row number moves when a formula is
filled or copied down (=x*t1 becomes =x*t2) and the column doesn't. Column
aliases also work as range corners: =SUM(t1:t9).

Names are case-sensitive (r and R are different names), and every name, of
either kind, is different from every other. A cell has at most one name, and
so does a column. A name can look like a cell reference, such as A1; a bare A1
in a formula then means the name, and the cell is written with a $: $A1, A$1,
or $A$1.
"""

import re

from .functions import CONSTANTS, FUNCTIONS
from .references import cell_name, column_name

MAX_LENGTH = 64
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ALIAS = re.compile(r"([A-Za-z_][A-Za-z0-9_]*?)([0-9]+)")  # column name, then a row number


def key(name: str) -> str:
    """How names are compared: exactly, so R and r are different names."""
    return name


def syntax_problem(name: str) -> str | None:
    """Why `name` can't be a cell name on its own terms (not counting other
    names), or None if it can."""
    if not name:
        return "Enter a name."
    if len(name) > MAX_LENGTH:
        return f"A name can be at most {MAX_LENGTH} characters long."
    if not _NAME.fullmatch(name):
        return ("A name must start with a letter or underscore and contain only letters, "
                "digits, and underscores.")
    # Functions and constants are matched in any case, so they're kept apart
    # from names in any case too.
    if name.upper() in FUNCTIONS:
        return f"{name.upper()} is a function, so it can't be a name."
    if name.upper() in CONSTANTS:
        return f"{name.upper()} is a constant, so it can't be a name."
    return None


def column_syntax_problem(name: str) -> str | None:
    """Like syntax_problem, for a column name."""
    problem = syntax_problem(name)
    if problem:
        return problem
    if name[-1].isdigit():
        return (f"A column name can't end with a digit: a row number follows it "
                f"({name}1 would be ambiguous).")
    return None


class Names:
    """A sheet's names as formulas see them: `cells` maps cell names to the
    (row, col) they name (None if that cell was deleted), and `columns` maps
    column names to column indexes."""

    def __init__(self, cells: dict | None = None, columns: dict | None = None):
        self.cells = dict(cells or {})
        self.columns = dict(columns or {})

    def alias(self, text: str) -> tuple[str, int, int] | None:
        """For a column alias such as t5: (the column name, the row, the
        column). The row is -1 for t0, which names no cell."""
        match = _ALIAS.fullmatch(text)
        if not match or match[1] not in self.columns:
            return None
        return match[1], int(match[2]) - 1, self.columns[match[1]]

    def taken(self, text: str, corner: bool = False) -> bool:
        """Whether a bare reference spelled `text` would mean a name instead
        of a cell. Range corners (A1 in A1:B9) can be column aliases, but not
        cell names."""
        return self.alias(text) is not None or (not corner and text in self.cells)

    def __contains__(self, text: str) -> bool:
        return self.taken(text)


def as_names(names) -> Names:
    """A Names, from a Names or a collection of cell names."""
    if isinstance(names, Names):
        return names
    if isinstance(names, dict):
        return Names(cells=names)
    return Names(cells={name: None for name in names})


def cell_text(text: str, names, corner: bool = False) -> str:
    """A bare cell reference `text`, such as B2, written so that it still
    means the cell when a name is spelled the same: then it gets a $ before
    its column ($B2)."""
    return "$" + text if as_names(names).taken(text, corner) else text


def unnamed_meaning(text: str) -> str:
    """What formulas using `text` (such as r or t1) will mean once it's no
    longer a name: the cell it's spelled like, or nothing (#NAME?)."""
    if re.fullmatch(r"[A-Za-z]+[0-9]+", text):
        return f"cell {text.upper()}"
    return "#NAME?"


def conflict(cell_names: dict, column_names: dict) -> str | None:
    """Why this set of names can't be used together, or None if it can.
    `cell_names` maps names to cells (or None), `column_names` names to
    column indexes."""
    for name in column_names:
        problem = column_syntax_problem(name)
        if problem:
            return problem
        if name in cell_names:
            return f"{name} names both a cell and a column; each name can name only one thing."
    view = Names(cell_names, column_names)
    named_cells = {}
    for name, cell in cell_names.items():
        problem = syntax_problem(name)
        if problem:
            return problem
        alias = view.alias(name)
        if alias:
            return (f"{name} would mean row {alias[1] + 1} of the column named {alias[0]}, "
                    "so it can't name a cell.")
        if cell is not None:
            if cell in named_cells:
                return (f"{cell_name(*cell)} has two names, {named_cells[cell]} and {name}. "
                        "A cell can have only one.")
            named_cells[cell] = name
    named_columns = {}
    for name, col in column_names.items():
        if col in named_columns:
            return (f"Column {column_name(col)} has two names, {named_columns[col]} and {name}. "
                    "A column can have only one.")
        named_columns[col] = name
    return None
