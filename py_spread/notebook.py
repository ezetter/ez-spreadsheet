"""A sheet's notebook: Python code cells, like a Jupyter notebook's, saved with
the sheet in Jupyter's own notebook format (nbformat 4).

Selected cells can be sent to the notebook as a pandas DataFrame: a new
notebook cell holds the data, written out as Python, so it's readable,
editable, and works the same after the kernel restarts.
"""

import re
import uuid
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from .errors import CellError
from .references import cell_name, column_name

NBFORMAT, NBFORMAT_MINOR = 4, 5
KERNELSPEC = {"name": "python3", "display_name": "Python 3", "language": "python"}
IMPORTS_CELL = "import pandas as pd\nimport seaborn as sns"  # a new notebook's first cell
_IMPORTS = {"pandas": re.compile(r"^import pandas as pd\s*$", re.M),
            "seaborn": re.compile(r"^import seaborn as sns\s*$", re.M)}


@dataclass
class NotebookCell:
    source: str = ""
    outputs: list = field(default_factory=list)  # nbformat output dicts
    execution_count: int | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_json(self) -> dict:
        return {"cell_type": "code", "id": self.id, "metadata": {}, "source": self.source,
                "outputs": self.outputs, "execution_count": self.execution_count}


class NotebookFormatError(ValueError):
    """A saved notebook can't be read; the message says why."""


class Notebook(QObject):
    """The cells of a sheet's notebook. Views follow it through its signals."""

    changed = Signal()  # anything changed (the sheet then has unsaved changes)
    cell_added = Signal(str, int)  # id, position
    cell_removed = Signal(str)
    cell_moved = Signal(str, int)  # id, new position
    cell_updated = Signal(str)  # its outputs or execution count changed
    reset = Signal()  # every cell was replaced (a sheet was opened)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cells: list[NotebookCell] = []

    def cell(self, cell_id: str) -> NotebookCell:
        return next(cell for cell in self.cells if cell.id == cell_id)

    def index_of(self, cell_id: str) -> int:
        return next(i for i, cell in enumerate(self.cells) if cell.id == cell_id)

    def add_cell(self, source: str = "", position: int | None = None) -> NotebookCell:
        cell = NotebookCell(source)
        position = len(self.cells) if position is None else position
        self.cells.insert(position, cell)
        self.cell_added.emit(cell.id, position)
        self.changed.emit()
        return cell

    def remove_cell(self, cell_id: str) -> None:
        self.cells.pop(self.index_of(cell_id))
        self.cell_removed.emit(cell_id)
        self.changed.emit()

    def move_cell(self, cell_id: str, offset: int) -> None:
        old = self.index_of(cell_id)
        new = min(max(old + offset, 0), len(self.cells) - 1)
        if new != old:
            self.cells.insert(new, self.cells.pop(old))
            self.cell_moved.emit(cell_id, new)
            self.changed.emit()

    def set_source(self, cell_id: str, source: str) -> None:
        cell = self.cell(cell_id)
        if cell.source != source:
            cell.source = source
            self.changed.emit()

    def clear_outputs(self, cell_id: str) -> None:
        cell = self.cell(cell_id)
        cell.outputs = []
        self.cell_updated.emit(cell_id)
        self.changed.emit()

    def add_output(self, cell_id: str, output: dict) -> None:
        cell = self.cell(cell_id)
        last = cell.outputs[-1] if cell.outputs else None
        if output.get("output_type") == "clear_output":
            cell.outputs = []
        elif (output.get("output_type") == "stream" and last and last.get("output_type") == "stream"
              and last.get("name") == output.get("name")):
            # Printed text is one output per stream, as Jupyter keeps it.
            last["text"] = joined_text(last.get("text", "")) + joined_text(output.get("text", ""))
        else:
            cell.outputs.append(output)
        self.cell_updated.emit(cell_id)
        self.changed.emit()

    def set_execution_count(self, cell_id: str, count: int | None) -> None:
        self.cell(cell_id).execution_count = count
        self.cell_updated.emit(cell_id)
        self.changed.emit()

    def to_json(self) -> dict:
        """The notebook as a Jupyter notebook (.ipynb) document."""
        return {
            "cells": [cell.to_json() for cell in self.cells],
            "metadata": {"kernelspec": KERNELSPEC, "language_info": {"name": "python"}},
            "nbformat": NBFORMAT,
            "nbformat_minor": NBFORMAT_MINOR,
        }

    def load(self, document: dict | None) -> None:
        """Replace every cell with those of a notebook document (or none)."""
        self.cells = cells_from_json(document) if document else []
        self.reset.emit()

    @property
    def is_empty(self) -> bool:
        return not self.cells


def joined_text(value) -> str:
    """Jupyter keeps multi-line text either as a string or a list of lines."""
    return "".join(value) if isinstance(value, list) else str(value)


def cells_from_json(document) -> list[NotebookCell]:
    """The code cells of a Jupyter notebook document; NotebookFormatError if
    it isn't one."""
    if not isinstance(document, dict) or not isinstance(document.get("cells"), list):
        raise NotebookFormatError("the notebook has no list of cells")
    cells = []
    for number, data in enumerate(document["cells"], start=1):
        if not isinstance(data, dict) or data.get("cell_type") != "code":
            raise NotebookFormatError(f"notebook cell {number} isn't a code cell")
        source = data.get("source", "")
        if isinstance(source, list) and all(isinstance(line, str) for line in source):
            source = "".join(source)  # Jupyter often stores source as a list of lines
        outputs = data.get("outputs", [])
        count = data.get("execution_count")
        if (not isinstance(source, str) or not isinstance(outputs, list)
                or not all(isinstance(output, dict) for output in outputs)
                or not (count is None or isinstance(count, int) and not isinstance(count, bool))):
            raise NotebookFormatError(f"notebook cell {number} is damaged")
        cell = NotebookCell(source, outputs, count)
        if isinstance(data.get("id"), str) and data["id"]:
            cell.id = data["id"]
        cells.append(cell)
    if len({cell.id for cell in cells}) != len(cells):
        raise NotebookFormatError("two notebook cells have the same id")
    return cells


# --- Sending cells to the notebook as a DataFrame ---

def importing_cell(notebook: Notebook, module: str, before: str | None = None) -> str | None:
    """The first cell (above the cell `before`, if given) that imports
    "pandas" as pd or "seaborn" as sns, such as a new notebook's first cell."""
    cells = notebook.cells[:notebook.index_of(before)] if before is not None else notebook.cells
    return next((cell.id for cell in cells if _IMPORTS[module].search(cell.source)), None)


def next_frame_name(notebook: Notebook) -> str:
    """df, or df2, df3, ... if earlier cells already assign df."""
    used = set()
    for cell in notebook.cells:
        used.update(re.findall(r"^(df\d*)\s*=(?!=)", cell.source, re.M))
    if "df" not in used:
        return "df"
    number = 2
    while f"df{number}" in used:
        number += 1
    return f"df{number}"


def data_block(model, cells) -> set[tuple[int, int]]:
    """The selected (row, col) cells inside the smallest block holding every
    selected cell that has something in it, so selecting whole columns or rows
    takes just their data. Empty if every selected cell is."""
    filled = [(row, col) for row, col in cells if model.get_cell(row, col)]
    if not filled:
        return set()
    top, bottom = min(row for row, _ in filled), max(row for row, _ in filled)
    left, right = min(col for _, col in filled), max(col for _, col in filled)
    return {(row, col) for row, col in cells if top <= row <= bottom and left <= col <= right}


@dataclass
class _Frame:
    """The DataFrame that selected cells make: its column labels, and each
    column's values (below the header row, if there is one)."""

    where: str  # the cells' block, such as A1:C4
    header_row: int | None  # the sheet row giving the column labels
    labels: list[str]
    columns: list[list]


def _frame(model, cells) -> _Frame:
    rows = sorted({row for row, _ in cells})
    cols = sorted({col for _, col in cells})

    def value(row, col):
        if (row, col) not in cells:
            return None
        found = model.value(row, col)
        return None if found is None or isinstance(found, CellError) else found

    first = [value(rows[0], col) for col in cols]
    header = (len(rows) > 1 and any(isinstance(v, str) and v.strip() for v in first)
              and not any(isinstance(v, float) for v in first))
    labels = []
    for col, title in zip(cols, first):
        label = title.strip() if header and isinstance(title, str) and title.strip() else None
        label = label or model.column_name_of(col) or column_name(col)
        if label in labels:
            label = f"{label} ({column_name(col)})"  # keep labels unique
        labels.append(label)
    data_rows = rows[1:] if header else rows
    return _Frame(where=f"{cell_name(rows[0], cols[0])}:{cell_name(rows[-1], cols[-1])}",
                  header_row=rows[0] if header else None, labels=labels,
                  columns=[[value(row, col) for row in data_rows] for col in cols])


def dataframe_code(model, cells, name: str = "df", import_pandas: bool = True) -> str:
    """Python that makes a pandas DataFrame, called `name`, of the selected
    (row, col) cells' values, and shows it.

    The columns are the selected columns. If the first selected row is text
    (and there's more than one row), it gives the column labels; otherwise a
    column's name (Formulas > Name Column…) or its letter does. Numbers are
    numbers ($1,200 is 1200); empty cells, error values, and cells inside the
    block that weren't selected are missing values (NaN). With
    `import_pandas` false, it leaves out "import pandas as pd" (an earlier
    cell has it).
    """
    frame = _frame(model, cells)
    note = f", with row {frame.header_row + 1} as the column names" if frame.header_row is not None else ""
    lines = ["import pandas as pd", ""] if import_pandas else []
    lines += [f"# Cells {frame.where} of the sheet{note}.", f"{name} = pd.DataFrame({{"]
    for label, values in zip(frame.labels, frame.columns):
        lines.append(f"    {label!r}: [{', '.join(_python_value(v) for v in values)}],")
    lines += ["})", name]
    return "\n".join(lines)


# --- Graphing them with Seaborn ---

class GraphError(ValueError):
    """The selected cells can't be graphed; the message says why."""


def _graph_frame(model, cells) -> _Frame:
    frame = _frame(model, cells)
    if len(frame.labels) < 2:
        raise GraphError("Select at least two columns: the first for x, the others for y.")
    if not any(isinstance(v, float) for column in frame.columns[1:] for v in column):
        raise GraphError("There are no numbers to graph in the y columns.")
    return frame


def graph_columns(model, cells) -> tuple[str, list[str]]:
    """The labels of the x column and the y columns a graph of the cells
    would have; GraphError if the cells can't be graphed."""
    frame = _graph_frame(model, cells)
    return frame.labels[0], frame.labels[1:]


def graph_code(model, cells, frame_name: str = "df", kind: str = "line", marker: str | None = None,
               import_pandas: bool = True, import_seaborn: bool = True) -> str:
    """Python that graphs the DataFrame `frame_name`, which dataframe_code
    makes of the same cells, with Seaborn, the way a chart of them is drawn:
    the first column across (text gives category labels, in the sheet's
    order), and each other column a series up, named by its label. `kind` is
    "line" or "scatter", and `marker` a Matplotlib marker such as "o" for
    each point (None: none on a line, Seaborn's circles on a scatter graph).
    Text in the y columns is left out. GraphError if the cells can't be
    graphed. `import_pandas` and `import_seaborn` false leave out those
    imports (an earlier cell has them).
    """
    if kind not in ("line", "scatter"):
        raise ValueError(f"kind must be 'line' or 'scatter', not {kind!r}")
    frame = _graph_frame(model, cells)
    x_label, y_labels = frame.labels[0], frame.labels[1:]
    x_values, y_columns = frame.columns[0], frame.columns[1:]

    fixes = []  # changes Seaborn needs, made to a copy of the DataFrame
    if any(isinstance(v, str) for v in x_values) and any(isinstance(v, float) for v in x_values):
        fixes.append(f"data[{x_label!r}] = data[{x_label!r}].astype('string')  # numbers and text: all labels")
    for label, column in zip(y_labels, y_columns):
        if any(isinstance(v, str) for v in column):
            fixes.append(f"data[{label!r}] = pd.to_numeric(data[{label!r}], errors='coerce')  # text isn't graphed")

    lines = ["import pandas as pd"] if import_pandas and any("pd." in fix for fix in fixes) else []
    lines += ["import seaborn as sns"] if import_seaborn else []
    lines += [""] if lines else []
    up = "the second" if len(y_labels) == 1 else "the others"
    lines += [f"# {frame_name} as a graph: its first column across, {up} up.", "sns.set_theme(style='whitegrid')"]
    data = frame_name
    if fixes:
        lines += [f"data = {frame_name}.copy()", *fixes]
        data = "data"
    if len(y_labels) == 1:
        plotted = f"data={data}, x={x_label!r}, y={y_labels[0]!r}"
    else:  # one column of values, with another naming each value's series
        series, value = _unused("Series", frame.labels), _unused("Value", frame.labels)
        lines.append(f"long = {data}.melt(id_vars=[{x_label!r}], value_vars={y_labels!r}, "
                     f"var_name={series!r}, value_name={value!r})")
        plotted = f"data=long, x={x_label!r}, y={value!r}, hue={series!r}"
    other = "scatter" if kind == "line" else "line"
    marker = f"marker={marker!r}, " if marker else ""
    lines += [
        "graph = sns.relplot(",
        f"    {plotted},",
        f"    kind={kind!r},  # or {other!r}",
        f"    {marker}height=4, aspect=1.5,",
        ")",
    ]
    return "\n".join(lines)


def _unused(name: str, taken: list[str]) -> str:
    """`name`, or `name 2`, `name 3`, ... if a column already has it."""
    candidate, number = name, 1
    while candidate in taken:
        number += 1
        candidate = f"{name} {number}"
    return candidate


def _python_value(value) -> str:
    if value is None:
        return "None"
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))  # whole numbers as integers, so columns of them are int64
        return repr(value)
    return repr(value)
