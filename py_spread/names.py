"""Cell names: aliases such as r for B2, usable in formulas (=PI*r^2).

A name always means the same cell, like an anchored reference ($B$2): copying
a formula that uses it doesn't change which cell it refers to. Names are
case-sensitive (r and R are different names), each names one cell, and a cell
has at most one name.

A name can look like a cell reference, such as A1. In a formula, a bare A1
then means the name, and the cell is written with a $: $A1, A$1, or $A$1.
Ranges (A1:B9) always mean cells.
"""

import re

from .functions import CONSTANTS, FUNCTIONS

MAX_LENGTH = 64
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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


def cell_text(text: str, names) -> str:
    """A bare cell reference `text`, such as B2, written so that it still
    means the cell when a name is spelled the same: then it gets a $ before
    its column ($B2)."""
    return "$" + text if text in names else text
