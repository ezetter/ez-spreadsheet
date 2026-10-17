"""A1-style cell reference helpers."""

import re

_REF = re.compile(r"\$?([A-Za-z]+)\$?(\d+)")


def column_name(col: int) -> str:
    """Convert a zero-based column index to a spreadsheet letter name (0 -> A, 26 -> AA)."""
    name = ""
    col += 1
    while col:
        col, rem = divmod(col - 1, 26)
        name = chr(ord("A") + rem) + name
    return name


def column_index(letters: str) -> int:
    """Convert a column letter name to a zero-based index (A -> 0, AA -> 26)."""
    index = 0
    for ch in letters.upper():
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1


def cell_name(row: int, col: int) -> str:
    """Zero-based (row, col) to an A1-style reference."""
    return f"{column_name(col)}{row + 1}"


def parse_cell_name(text: str) -> tuple[int, int]:
    """A1-style reference (optionally with $ anchors) to zero-based (row, col)."""
    match = _REF.fullmatch(text)
    if not match:
        raise ValueError(f"not a cell reference: {text!r}")
    return int(match.group(2)) - 1, column_index(match.group(1))
