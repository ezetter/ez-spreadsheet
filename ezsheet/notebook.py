"""A sheet's notebook: Python code cells, like a Jupyter notebook's, saved with
the sheet in Jupyter's own notebook format (nbformat 4).

Selected cells can be sent to the notebook as a pandas DataFrame: a new
notebook cell holds the data, written out as Python, so it's readable,
editable, and works the same after the kernel restarts.
"""

import builtins
import keyword
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


_USED_NAMES = {**dict.fromkeys(("pd", "sns", "chart", "data", "long"), "EZ Sheet's code uses it"),
               **dict.fromkeys(("In", "Out", "get_ipython", "display"), "the notebook's Python uses it")}


def frame_name_problem(name: str) -> str | None:
    """Why `name` can't be a DataFrame's (a Python name, and not one that
    something else needs), or None if it can."""
    if not name:
        return "The DataFrame needs a name."
    if not name.isidentifier():
        return "A name is letters, digits, and _, and can't start with a digit."
    if keyword.iskeyword(name):
        return f"{name} is one of Python's keywords."
    if name.startswith("_"):
        return "A name starting with _ is kept for Python's own use."
    if name in _USED_NAMES:
        return f"{name} can't be used: {_USED_NAMES[name]}."
    if hasattr(builtins, name):
        return f"{name} is one of Python's built-in names."
    return None


def assigned_names(notebook: Notebook) -> set[str]:
    """The names the notebook's cells set at the start of a line (df = ...)."""
    names = set()
    for cell in notebook.cells:
        names.update(re.findall(r"^(\w+)\s*=(?!=)", cell.source, re.M))
    return names


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
class FrameData:
    """A DataFrame's column labels, and each column's values: as selected
    cells make it (below the header row, if there is one), or as a DataFrame
    cell's code writes it out."""

    labels: list[str]
    columns: list[list]
    where: str = ""  # the cells' block, such as A1:C4
    header_row: int | None = None  # the sheet row giving the column labels


def _frame(model, cells) -> FrameData:
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
    return FrameData(where=f"{cell_name(rows[0], cols[0])}:{cell_name(rows[-1], cols[-1])}",
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
    comment, assignment = dataframe_parts(model, cells, name)
    lines = ["import pandas as pd", ""] if import_pandas else []
    return "\n".join([*lines, comment, assignment, name])


FRAME_COMMENT = re.compile(r"^# Cells [A-Z]+\d+:[A-Z]+\d+ of the sheet\b.*$", re.M)  # as dataframe_parts writes it


def dataframe_parts(model, cells, name: str) -> tuple[str, str]:
    """dataframe_code's comment saying which cells it's of, and its
    `name = pd.DataFrame({...})` (see dataframe_code)."""
    frame = _frame(model, cells)
    note = f", with row {frame.header_row + 1} as the column names" if frame.header_row is not None else ""
    lines = [f"{name} = pd.DataFrame({{"]
    for label, values in zip(frame.labels, frame.columns):
        lines.append(f"    {label!r}: [{', '.join(_python_value(v) for v in values)}],")
    lines.append("})")
    return f"# Cells {frame.where} of the sheet{note}.", "\n".join(lines)


# --- Graphing them with Seaborn ---

GRAPH_TYPES = {"line": "Line", "scatter": "Scatter", "strip": "Categorical",
               "hist": "Distribution"}  # the Chart dialog's
GRAPH_KINDS = ("line", "scatter", "strip", "swarm", "box", "violin", "reg", "hist", "kde", "ecdf")  # Seaborn's
# kinds: swarm, box, and violin are categorical too, reg a scatter with a linear regression line, and kde
# and ecdf distributions
CATEGORICAL = {"strip", "swarm", "box", "violin"}  # drawn with catplot, x being categories
CATEGORICAL_KINDS = {"strip": "Strip", "swarm": "Swarm", "box": "Box", "violin": "Violin"}  # the dialog's Kind
REGRESSION = {"reg"}  # drawn with lmplot, which fits a line to numbers both ways
DISTRIBUTION = {"hist", "kde", "ecdf"}  # drawn with displot, of x's numbers (and y's); the rest with relplot
DISTRIBUTION_KINDS = {"hist": "Histogram", "kde": "KDE", "ecdf": "ECDF"}  # the Chart dialog's Kind
BIVARIATE = {"hist", "kde"}  # distributions that can be of a y column too, as well as x
NEEDS_MARKERS = {"scatter", "strip", "swarm", "reg"}  # their points are nothing but markers
NO_MARKERS = {"box", "violin", *DISTRIBUTION}  # no points to mark: their shapes sum the values up
ALL_SERIES = {"line"}  # kinds whose y can be all the other columns with numbers, a series (line) each
OTHER_KINDS = {"line": "  # or 'scatter'", "scatter": "  # or 'line'",
               "strip": "  # or 'swarm', 'box', or 'violin'", "swarm": "  # or 'strip', 'box', or 'violin'",
               "box": "  # or 'violin', 'strip', or 'swarm'", "violin": "  # or 'box', 'strip', or 'swarm'",
               "hist": "  # or 'kde' or 'ecdf'", "kde": "  # or 'hist' or 'ecdf'",
               "ecdf": "  # or 'hist' or 'kde'"}  # what follows kind=, naming the other kinds its function draws
FACETED = set(GRAPH_KINDS)  # kinds that can be split by a column's values (col=), a panel for each
COL_WRAP = 2  # panels to a row


class GraphError(ValueError):
    """The selected cells can't be graphed; the message says why."""


def plot_function(kind: str) -> str:
    """The Seaborn function drawing a kind of graph."""
    if kind in DISTRIBUTION:
        return "displot"
    return "catplot" if kind in CATEGORICAL else "lmplot" if kind in REGRESSION else "relplot"


def marker_keyword(kind: str) -> str:
    """What the function drawing a kind of graph calls its marker."""
    return "markers" if kind in REGRESSION else "marker"


@dataclass
class GraphChoice:
    """What the Chart dialog chose: the kind of chart, its marker, the x
    column, the y column (in a list; graphs made before the y was a single
    column could have several, a series each), the hue column, if any,
    coloring the points by its values, and whether a categorical chart's
    y column is its categories, turning it sideways (as a column of text
    always is; for one of numbers, such as years, it has to be asked for),
    the col column, if any, splitting it into a panel for each of its
    values (categories, or numbers such as years), and for a new chart,
    what to call its DataFrame (None: the next of df, df2, ...). For a
    distribution, ys is empty unless it's of a y column too, and it can have
    a density curve over a histogram's bars (kde) and a rug of ticks."""

    kind: str
    marker: str | None
    x: str
    ys: list[str]
    hue: str | None = None
    y_categories: bool = False
    col: str | None = None
    frame: str | None = None
    kde: bool = False
    rug: bool = False


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@dataclass
class GraphColumns:
    """The columns a graph can use: their labels, and whether each has
    numbers (so it can go up the y axis) and text (categories)."""

    labels: list[str]
    numbers: list[bool]
    text: list[bool]

    @classmethod
    def of(cls, frame: FrameData) -> "GraphColumns":
        columns = cls(frame.labels, [any(_is_number(v) for v in column) for column in frame.columns],
                      [any(isinstance(v, str) for v in column) for column in frame.columns])
        if not any(columns.numbers):
            raise GraphError("There are no numbers to chart.")
        return columns

    @property
    def only_distribution(self) -> bool:
        """Whether there's just the one column: a distribution can be of it,
        but the other charts need one across and another up."""
        return len(self.labels) < 2

    def category(self, label: str) -> bool:
        """Whether a column is just categories: text, without numbers."""
        index = self.labels.index(label)
        return self.text[index] and not self.numbers[index]

    def y_options(self, x: str, kind: str = "line") -> list[str]:
        """The columns that can go up the y axis against x: those with
        numbers, and for a categorical chart across a column of numbers,
        columns of categories too (which turn the graph sideways)."""
        if kind in DISTRIBUTION:  # (as well as x: none, unless it's chosen)
            return [label for label, numbers in zip(self.labels, self.numbers) if numbers and label != x]
        sideways = kind in CATEGORICAL and self.numbers[self.labels.index(x)]
        return [label for label, numbers in zip(self.labels, self.numbers)
                if label != x and (numbers or sideways and self.category(label))]

    def x_options(self, y: str | None, kind: str = "line", y_categories: bool = False) -> list[str]:
        """The columns that can go across: any, except that with categories
        up a categorical chart (sideways), only those with numbers; and a
        linear regression needs numbers across too."""
        if self.sideways([y] if y in self.labels else [], kind, y_categories) or kind in DISTRIBUTION:
            return [label for label, numbers in zip(self.labels, self.numbers) if numbers and label != y]
        if kind in REGRESSION:
            return [label for label, numbers in zip(self.labels, self.numbers) if numbers]
        return list(self.labels)

    @property
    def can_regress(self) -> bool:
        """Whether there are numbers to fit a line to: two columns of them."""
        return sum(self.numbers) >= 2

    def sideways(self, ys: list[str], kind: str, y_categories: bool = False) -> bool:
        """Whether a categorical chart has its categories up the y axis: a
        column of text, or one of numbers (such as years) taken as categories."""
        return kind in CATEGORICAL and len(ys) == 1 and (y_categories or self.category(ys[0]))

    def hue_options(self, x: str) -> list[str]:
        """The columns that can color the points: any but x."""
        return [label for label in self.labels if label != x]

    def col_options(self, x: str, ys: list[str]) -> list[str]:
        """The columns that can split the chart into panels, one for each of
        their values: any but x and the ys, whether of categories (text) or
        of numbers such as years."""
        return [label for label in self.labels if label != x and label not in ys]

    def default_x(self, kind: str, col: str | None = None) -> str:
        """The first column that leaves another with numbers for y; for a
        categorical chart, the first such with text, as its categories,
        and for a linear regression or a distribution, with numbers. Not
        the col splitting the chart into panels, if there's another."""
        if kind in DISTRIBUTION:
            usable = self.x_options(None, kind)
            return ([label for label in usable if label != col] or usable)[0]
        if self.only_distribution:
            raise GraphError(f"A {'line chart' if kind == 'line' else 'scatter chart'} needs at least two columns: "
                             "one for x, and another for y.")
        usable = [label for label in self.labels if self.y_options(label)]
        usable = [label for label in usable if label != col] or usable
        if kind in CATEGORICAL:
            usable = [label for label, text in zip(self.labels, self.text) if text and label in usable] or usable
        if kind in REGRESSION:
            usable = [label for label in usable if label in self.x_options(None, kind)] or usable
        return usable[0]

    def default_ys(self, x: str, kind: str = "line", col: str | None = None) -> list[str]:
        """For a line chart, all the columns with numbers but x and the col
        splitting it into panels (such as years), a line each; otherwise the
        first column with numbers after x (but the col), else before it. A
        distribution is just of x, to start with."""
        if kind in DISTRIBUTION:
            return []
        options = self.y_options(x)  # (numbers only: a chart is sideways only if asked for)
        options = [label for label in options if label != col] or options
        if kind in ALL_SERIES:
            return options
        after = [label for label in options if self.labels.index(label) > self.labels.index(x)]
        return [(after or options)[0]]

    def default_choice(self, kind: str, marker: str | None) -> GraphChoice:
        x = self.default_x(kind)
        return GraphChoice(kind, marker, x, self.default_ys(x, kind))


def graph_columns(model, cells) -> GraphColumns:
    """The columns a graph of the cells could use; GraphError if the cells
    can't be graphed."""
    return GraphColumns.of(_frame(model, cells))


def graph_code(model, cells, frame_name: str = "df", kind: str = "line", marker: str | None = None,
               x: str | None = None, ys: list[str] | None = None, hue: str | None = None,
               y_categories: bool = False, import_pandas: bool = True, import_seaborn: bool = True,
               col: str | None = None, kde: bool = False, rug: bool = False) -> str:
    """Python that graphs the DataFrame `frame_name`, which dataframe_code
    makes of the same cells, with Seaborn (see frame_graph_code). GraphError
    if the cells can't be graphed."""
    return frame_graph_code(_frame(model, cells), frame_name, kind, marker, x, ys, hue, y_categories,
                            import_pandas, import_seaborn, col, kde, rug)


def frame_graph_code(frame: FrameData, frame_name: str = "df", kind: str = "line", marker: str | None = None,
                     x: str | None = None, ys: list[str] | None = None, hue: str | None = None,
                     y_categories: bool = False, import_pandas: bool = True, import_seaborn: bool = True,
                     col: str | None = None, kde: bool = False, rug: bool = False) -> str:
    """Python that graphs a DataFrame with Seaborn: column `x` across (text
    gives categories, in the sheet's order) and the `ys` column up (by
    default, the first column across and the next with numbers up, or for a
    line chart all the others with numbers, a line each), with
    the points colored by the `hue` column's values, if given. `kind` is
    "line" or "scatter" (relplot), or a categorical chart (catplot):
    "strip" jitters each category's points, "swarm" spreads them so none
    overlap, "box" draws a box from its values' first quartile to their
    third, with the median across it and whiskers out to the rest, and
    "violin" the shape of their spread (a KDE, mirrored), with a box
    inside; or "reg" (lmplot), a scatter with a linear regression line
    fitted to its points, and the line's 95% confidence band, which needs
    numbers across too. A categorical chart can have its categories up the y axis
    instead, with numbers across, turning it sideways: as a y column of text
    does, or one of numbers (such as years) with `y_categories`. `marker` is a Matplotlib marker such as "o" for each point
    (None: none on a line, Seaborn's dots otherwise). Text in the y column
    is left out. Several `ys` (All, for a line chart, or as charts made
    before the y was a single column could have) make a series each,
    colored instead of by a hue. Any chart can be split by the `col`
    column: a panel for each of its values (categories, or numbers such as
    years, in order), side by side, COL_WRAP to a row, sharing their axes.
    `import_pandas` and `import_seaborn` false leave out those imports (an
    earlier cell has them). GraphError if it can't be graphed. For a
    distribution ("hist", "kde", or "ecdf"), see distribution_code.
    """
    if kind not in GRAPH_KINDS:
        raise ValueError(f"kind must be one of {', '.join(GRAPH_KINDS)}, not {kind!r}")
    if kind in DISTRIBUTION:
        return distribution_code(frame, frame_name, kind, x, ys, hue, import_pandas, import_seaborn, col, kde, rug)
    if marker and kind in NO_MARKERS:
        raise ValueError(f"a {kind} chart has no markers")
    columns = GraphColumns.of(frame)
    x = x if x is not None else columns.default_x(kind)
    ys = list(ys) if ys is not None else columns.default_ys(x, kind, col)
    sideways = columns.sideways(ys, kind, y_categories)  # the categories go up, and the numbers across
    if (x not in columns.labels or not ys or any(y not in columns.y_options(x, kind) for y in ys)
            or len(ys) > 1 and any(columns.category(y) for y in ys)
            or x not in columns.x_options(ys[0] if len(ys) == 1 else None, kind, y_categories)):
        raise ValueError(f"can't chart {ys!r} against {x!r}")
    if hue is not None and (hue not in columns.hue_options(x) or len(ys) > 1):
        raise ValueError(f"can't color the chart by {hue!r}")
    if col is not None and (kind not in FACETED or col not in columns.col_options(x, ys)):
        raise ValueError(f"can't split the chart by {col!r}")
    values = dict(zip(frame.labels, frame.columns))

    if sideways:  # the axis of labels; the columns of numbers
        labeled, measured = ys[0], [x]
    elif kind in REGRESSION:  # a line fitted to numbers both ways
        labeled, measured = None, [x, *ys]
    else:
        labeled, measured = x, ys
    fixes = []  # changes Seaborn needs, made to a copy of the DataFrame
    if labeled is not None and any(isinstance(v, str) for v in values[labeled]) and any(
            _is_number(v) for v in values[labeled]):
        fixes.append(f"data[{labeled!r}] = data[{labeled!r}].astype('string')  # numbers and text: all labels")
    for column in measured:
        if any(isinstance(v, str) for v in values[column]):
            fixes.append(f"data[{column!r}] = pd.to_numeric(data[{column!r}], errors='coerce')  # text isn't charted")
    if col is not None and None in values[col] and all(
            _is_number(v) and float(v).is_integer() for v in values[col] if v is not None):  # years, with gaps
        fixes += [f"data = data.dropna(subset=[{col!r}])  # rows without a {col!r} have no panel",
                  f"data[{col!r}] = data[{col!r}].astype(int)  # whole numbers: 2020, not 2020.0"]

    lines = ["import pandas as pd"] if import_pandas and any("pd." in fix for fix in fixes) else []
    lines += ["import seaborn as sns"] if import_seaborn else []
    lines += [""] if lines else []
    named = [repr(y) for y in ys]  # repr: a label can't break out of the comment
    series = named[0] if len(named) == 1 else f"{', '.join(named[:-1])} and {named[-1]}"
    colored = f", colored by {hue!r}" if hue is not None else ""
    colored += f", a panel for each {col!r}" if col is not None else ""
    lines += [f"# {frame_name} as a chart: {series} against {x!r}{colored}.", "sns.set_theme(style='whitegrid')"]
    data = frame_name
    if fixes:
        lines += [f"data = {frame_name}.copy()", *fixes]
        data = "data"
    if len(ys) == 1:
        plotted = f"data={data}, x={x!r}, y={ys[0]!r}" + (f", hue={hue!r}" if hue is not None else "")
        plotted += ", orient='h'" if sideways else ""  # needed when the categories are numbers
    else:  # one column of values, with another naming each value's series
        series_name, value = _unused("Series", frame.labels), _unused("Value", frame.labels)
        kept = [x] if col is None else [x, col]  # col's categories stay with their values
        lines.append(f"long = {data}.melt(id_vars={kept!r}, value_vars={ys!r}, "
                     f"var_name={series_name!r}, value_name={value!r})")
        plotted = f"data=long, x={x!r}, y={value!r}, hue={series_name!r}"
    marker = f"{marker_keyword(kind)}={marker!r}, " if marker else ""
    lines += [f"chart = sns.{plot_function(kind)}(", f"    {plotted},"]
    if col is not None:  # smaller panels, so two to a row fit the notebook
        lines.append(f"    col={col!r}, col_wrap={COL_WRAP},  # a panel for each, {COL_WRAP} to a row")
    if kind not in REGRESSION:  # (lmplot has just the one kind)
        lines.append(f"    kind={kind!r},{OTHER_KINDS[kind]}")
    size = "height=2.5, aspect=1.2" if col is not None else "height=4, aspect=1.5"
    lines += [f"    {marker}{size},", ")"]
    return "\n".join(lines)


def distribution_code(frame: FrameData, frame_name: str = "df", kind: str = "hist", x: str | None = None,
                      ys: list[str] | None = None, hue: str | None = None, import_pandas: bool = True,
                      import_seaborn: bool = True, col: str | None = None, kde: bool = False,
                      rug: bool = False) -> str:
    """Python that charts how a DataFrame's column `x` is distributed, with
    Seaborn's displot: a histogram ("hist"), a kernel density estimate's
    smooth curve ("kde"), or an empirical cumulative distribution ("ecdf").
    A histogram or KDE can be of a y column too (`ys`, one at most), how the
    two vary together: a heatmap of counts, or density contours. A
    histogram of x alone can have its KDE curve drawn over it (`kde`); any
    can have a `rug`, a tick along the axis for each value. `hue` and `col`
    are as for frame_graph_code. Text in x or y isn't charted. GraphError
    if it can't be."""
    columns = GraphColumns.of(frame)
    x = x if x is not None else columns.default_x(kind, col)
    ys = list(ys or [])
    if (x not in columns.x_options(None, kind) or len(ys) > 1 or ys and kind not in BIVARIATE
            or any(y not in columns.y_options(x, kind) for y in ys)):
        raise ValueError(f"can't chart the distribution of {[x, *ys]!r}")
    if hue is not None and hue not in columns.hue_options(x):
        raise ValueError(f"can't color the chart by {hue!r}")
    if col is not None and col not in columns.col_options(x, ys):
        raise ValueError(f"can't split the chart by {col!r}")
    if kde and (kind != "hist" or ys):
        raise ValueError("only a histogram of one column can have a KDE curve over it")
    values = dict(zip(frame.labels, frame.columns))
    fixes = []
    for column in [x, *ys]:
        if any(isinstance(v, str) for v in values[column]):
            fixes.append(f"data[{column!r}] = pd.to_numeric(data[{column!r}], errors='coerce')  # text isn't charted")
    if hue is not None and any(isinstance(v, str) for v in values[hue]) and any(_is_number(v) for v in values[hue]):
        fixes.append(f"data[{hue!r}] = data[{hue!r}].astype('string')  # numbers and text: all labels")
    if col is not None and None in values[col] and all(
            _is_number(v) and float(v).is_integer() for v in values[col] if v is not None):  # years, with gaps
        fixes += [f"data = data.dropna(subset=[{col!r}])  # rows without a {col!r} have no panel",
                  f"data[{col!r}] = data[{col!r}].astype(int)  # whole numbers: 2020, not 2020.0"]

    lines = ["import pandas as pd"] if import_pandas and any("pd." in fix for fix in fixes) else []
    lines += ["import seaborn as sns"] if import_seaborn else []
    lines += [""] if lines else []
    of = f"{x!r} and {ys[0]!r}" if ys else repr(x)  # repr: a label can't break out of the comment
    colored = f", colored by {hue!r}" if hue is not None else ""
    colored += f", a panel for each {col!r}" if col is not None else ""
    lines += [f"# {frame_name} as a chart: the distribution of {of}{colored}.", "sns.set_theme(style='whitegrid')"]
    data = frame_name
    if fixes:
        lines += [f"data = {frame_name}.copy()", *fixes]
        data = "data"
    plotted = f"data={data}, x={x!r}" + (f", y={ys[0]!r}" if ys else "") + (f", hue={hue!r}" if hue else "")
    lines += ["chart = sns.displot(", f"    {plotted},"]
    if col is not None:
        lines.append(f"    col={col!r}, col_wrap={COL_WRAP},  # a panel for each, {COL_WRAP} to a row")
    lines.append(f"    kind={kind!r},{OTHER_KINDS[kind]}")
    if kde:
        lines.append("    kde=True,  # its density curve over the bars")
    if rug:
        lines.append("    rug=True,  # a tick along the axis for each value")
    size = "height=2.5, aspect=1.2" if col is not None else "height=4, aspect=1.5"
    lines += [f"    {size},", ")"]
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
