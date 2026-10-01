"""Reading and writing sheets as .pysheet files.

A .pysheet file is JSON holding each non-empty cell's raw text (formulas
included) keyed by its A1 name:

    {
      "format": "py-spread",
      "version": 1,
      "rows": 1000,
      "columns": 52,
      "cells": {"A1": "Item", "B1": "Qty", "B3": "=B2*3"}
    }
"""

import json
import os
import tempfile
from dataclasses import dataclass, field

from .references import cell_name, parse_cell_name

FORMAT = "py-spread"
VERSION = 1
EXTENSION = ".pysheet"


class SheetFileError(Exception):
    """A file couldn't be read or written; the message is shown to the user."""


@dataclass
class SheetData:
    rows: int
    cols: int
    cells: dict[tuple[int, int], str] = field(default_factory=dict)


def save_sheet(path: str, sheet: SheetData) -> None:
    ordered = sorted(sheet.cells.items())  # row by row, so files diff nicely
    document = {
        "format": FORMAT,
        "version": VERSION,
        "rows": sheet.rows,
        "columns": sheet.cols,
        "cells": {cell_name(row, col): text for (row, col), text in ordered},
    }
    # Write to a temporary file and swap it in, so a failed save can't
    # leave a half-written file in place of the old one.
    directory = os.path.dirname(os.path.abspath(path))
    try:
        fd, temp_path = tempfile.mkstemp(dir=directory, prefix=".", suffix=EXTENSION)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(document, f, indent=2, ensure_ascii=False)
                f.write("\n")
            # mkstemp makes owner-only files; give the result normal permissions.
            os.chmod(temp_path, _file_mode(path))
            os.replace(temp_path, path)
        except BaseException:
            os.unlink(temp_path)
            raise
    except OSError as e:
        raise SheetFileError(f"Couldn't save {path}: {e.strerror or e}") from e


def _file_mode(path: str) -> int:
    """Permissions for a saved file: keep an existing file's, else the umask default."""
    try:
        return os.stat(path).st_mode & 0o7777
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        return 0o666 & ~umask


def load_sheet(path: str) -> SheetData:
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
    except OSError as e:
        raise SheetFileError(f"Couldn't open {path}: {e.strerror or e}") from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise SheetFileError(f"{path} isn't a Py-Spread sheet (it isn't valid JSON).") from e

    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise SheetFileError(f"{path} isn't a Py-Spread sheet.")
    version = document.get("version")
    if not isinstance(version, int) or version > VERSION:
        raise SheetFileError(f"{path} was saved by a newer version of Py-Spread.")

    rows = document.get("rows")
    cols = document.get("columns")
    cells = document.get("cells", {})
    if not (_positive_int(rows) and _positive_int(cols) and isinstance(cells, dict)):
        raise SheetFileError(f"{path} is damaged: bad sheet size or cell table.")

    sheet = SheetData(rows, cols)
    for name, text in cells.items():
        try:
            row, col = parse_cell_name(name)
        except ValueError:
            raise SheetFileError(f"{path} is damaged: {name!r} isn't a cell name.") from None
        if row < 0 or not isinstance(text, str):
            raise SheetFileError(f"{path} is damaged: bad entry for cell {name}.")
        if text:
            sheet.cells[(row, col)] = text
            # Grow the sheet if a cell lies outside the recorded size.
            sheet.rows = max(sheet.rows, row + 1)
            sheet.cols = max(sheet.cols, col + 1)
    return sheet


def _positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
