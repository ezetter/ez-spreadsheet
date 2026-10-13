"""Reading and writing sheets as .ezs files.

A .ezs file is JSON holding each non-empty cell's raw text (formulas
included) keyed by its A1 name, and the unit SIN, COS, and TAN take angles in:

    {
      "format": "ezsheet",
      "version": 6,
      "rows": 1000,
      "columns": 52,
      "angles": "degrees",
      "cells": {"A1": "Item", "B1": "Qty", "B3": "=B2*3"}
    }

Number formats, text styles, cell names, and column names, if any, follow
under "formats", "styles", "names" (name to cell, or null for a name whose
cell was deleted), and "column_names" (name to column letters). The sheet's
notebook, if it has cells, is under "notebook", as a Jupyter notebook (.ipynb)
document.
"""

import json
import os
import tempfile
from dataclasses import dataclass, field

from . import names as cell_names
from . import numformat, textstyle
from .functions import ANGLE_UNITS, DEGREES
from .notebook import NotebookFormatError, cells_from_json
from .numformat import NumberFormat
from .textstyle import CellStyle
from .references import cell_name, column_index, column_name, parse_cell_name

FORMAT = "ezsheet"
VERSION = 7  # 2 number formats; 3 bold and italic; 4 the angle unit; 5 cell names;
# 6 column names; 7 the notebook
EXTENSION = ".ezs"


class SheetFileError(Exception):
    """A file couldn't be read or written; the message is shown to the user."""


@dataclass
class SheetData:
    rows: int
    cols: int
    cells: dict[tuple[int, int], str] = field(default_factory=dict)
    formats: dict[tuple[int, int], NumberFormat] = field(default_factory=dict)
    styles: dict[tuple[int, int], CellStyle] = field(default_factory=dict)
    angle_unit: str = DEGREES
    names: dict[str, tuple[int, int] | None] = field(default_factory=dict)  # name -> cell
    column_names: dict[str, int] = field(default_factory=dict)  # name -> column index
    notebook: dict | None = None  # a Jupyter notebook (.ipynb) document, if there are notebook cells


def save_sheet(path: str, sheet: SheetData) -> None:
    ordered = sorted(sheet.cells.items())  # row by row, so files diff nicely
    document = {
        "format": FORMAT,
        "version": VERSION,
        "rows": sheet.rows,
        "columns": sheet.cols,
        "angles": sheet.angle_unit,
        "cells": {cell_name(row, col): text for (row, col), text in ordered},
    }
    if sheet.formats:
        document["formats"] = {
            cell_name(row, col): numformat.to_json(fmt) for (row, col), fmt in sorted(sheet.formats.items())
        }
    if sheet.styles:
        document["styles"] = {
            cell_name(row, col): textstyle.to_json(style) for (row, col), style in sorted(sheet.styles.items())
        }
    if sheet.names:
        document["names"] = {
            name: cell_name(*cell) if cell else None
            for name, cell in sorted(sheet.names.items(), key=lambda item: item[0].upper())
        }
    if sheet.column_names:
        document["column_names"] = {
            name: column_name(col)
            for name, col in sorted(sheet.column_names.items(), key=lambda item: item[0].upper())
        }
    if sheet.notebook:
        document["notebook"] = sheet.notebook  # last, as it can be long
    write_text_atomically(path, json.dumps(document, indent=2, ensure_ascii=False) + "\n")


def write_text_atomically(path: str, text: str) -> None:
    """Write UTF-8 text to a temporary file and swap it in, so a failed save
    can't leave a half-written file in place of the old one."""
    directory = os.path.dirname(os.path.abspath(path))
    try:
        fd, temp_path = tempfile.mkstemp(dir=directory, prefix=".", suffix=os.path.splitext(path)[1])
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(text)
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
        raise SheetFileError(f"{path} isn't an EzSheet sheet (it isn't valid JSON).") from e

    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise SheetFileError(f"{path} isn't an EzSheet sheet.")
    version = document.get("version")
    if not isinstance(version, int) or version > VERSION:
        raise SheetFileError(f"{path} was saved by a newer version of EzSheet.")

    rows = document.get("rows")
    cols = document.get("columns")
    cells = document.get("cells", {})
    formats = document.get("formats", {})  # absent before version 2
    styles = document.get("styles", {})  # absent before version 3
    angle_unit = document.get("angles", DEGREES)  # absent before version 4
    names = document.get("names", {})  # absent before version 5
    column_names = document.get("column_names", {})  # absent before version 6
    if not (_positive_int(rows) and _positive_int(cols) and isinstance(cells, dict)
            and isinstance(formats, dict) and isinstance(styles, dict) and isinstance(names, dict)
            and isinstance(column_names, dict)):
        raise SheetFileError(f"{path} is damaged: bad sheet size, or cell, format, style, or name table.")
    if angle_unit not in ANGLE_UNITS:
        raise SheetFileError(f"{path} is damaged: angles must be degrees or radians.")

    sheet = SheetData(rows, cols, angle_unit=angle_unit)
    for name, text in cells.items():
        row, col = _cell_key(path, name)
        if not isinstance(text, str):
            raise SheetFileError(f"{path} is damaged: bad entry for cell {name}.")
        if text:
            sheet.cells[(row, col)] = text
            _grow_to_fit(sheet, row, col)
    for name, data in formats.items():
        row, col = _cell_key(path, name)
        fmt = numformat.from_json(data)
        if fmt is None:
            raise SheetFileError(f"{path} is damaged: bad format for cell {name}.")
        sheet.formats[(row, col)] = fmt
        _grow_to_fit(sheet, row, col)
    for name, data in styles.items():
        row, col = _cell_key(path, name)
        style = textstyle.from_json(data)
        if style is None:
            raise SheetFileError(f"{path} is damaged: bad style for cell {name}.")
        if style != textstyle.PLAIN:
            sheet.styles[(row, col)] = style
            _grow_to_fit(sheet, row, col)
    for name, cell_text in names.items():
        sheet.names[name] = None if cell_text is None else _cell_key(path, cell_text)
        if sheet.names[name]:
            _grow_to_fit(sheet, *sheet.names[name])
    for name, letters in column_names.items():
        if not isinstance(letters, str) or not letters.isalpha() or not letters.isascii():
            raise SheetFileError(f"{path} is damaged: bad column for the column name {name!r}.")
        sheet.column_names[name] = column_index(letters)
        sheet.cols = max(sheet.cols, sheet.column_names[name] + 1)
    problem = cell_names.conflict(sheet.names, sheet.column_names)
    if problem:
        raise SheetFileError(f"{path} is damaged: its names don't work together. {problem}")
    if "notebook" in document:  # absent before version 7, or with no notebook cells
        try:
            cells_from_json(document["notebook"])
        except NotebookFormatError as e:
            raise SheetFileError(f"{path} is damaged: {e}.") from None
        sheet.notebook = document["notebook"]
    return sheet


def _cell_key(path: str, name) -> tuple[int, int]:
    try:
        row, col = parse_cell_name(name)
    except (TypeError, ValueError):
        row = -1
    if row < 0:
        raise SheetFileError(f"{path} is damaged: {name!r} isn't a cell name.")
    return row, col


def _grow_to_fit(sheet: SheetData, row: int, col: int) -> None:
    # A cell outside the recorded size grows the sheet.
    sheet.rows = max(sheet.rows, row + 1)
    sheet.cols = max(sheet.cols, col + 1)


def _positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
