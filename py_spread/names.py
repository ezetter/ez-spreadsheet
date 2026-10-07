"""Cell names: aliases such as r for B2, usable in formulas (=PI*r^2).

A name always means the same cell, like an anchored reference ($B$2): copying
a formula that uses it doesn't change which cell it refers to. Names are
case-insensitive, each names one cell, and a cell has at most one name.
"""

import re

from .functions import CONSTANTS, FUNCTIONS

MAX_LENGTH = 64
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CELL_LIKE = re.compile(r"\$?[A-Za-z]+\$?[0-9]+")  # what formulas read as a cell reference


def key(name: str) -> str:
    """How names are compared: R and r are the same name."""
    return name.upper()


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
    if _CELL_LIKE.fullmatch(name):
        return f"{name} looks like a cell reference, so it can't be a name."
    if key(name) in FUNCTIONS:
        return f"{key(name)} is a function, so it can't be a name."
    if key(name) in CONSTANTS:
        return f"{key(name)} is a constant, so it can't be a name."
    return None
