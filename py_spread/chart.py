"""Charts of selected cells, drawn with Matplotlib.

The first selected column holds the x values; each other selected column is a
series of y values. If the first selected row has text in the y columns, it's
a header naming the series (and the x axis). A text x column gives category
labels on the x axis. Empty or non-numeric y cells leave gaps.
"""

import math
from dataclasses import dataclass

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .references import cell_name, column_name

CHART_KINDS = {"line": "Line", "scatter": "Scatter"}
MARKER_LIMIT = 50  # line charts with up to this many points mark each one


class ChartError(Exception):
    """The selected cells can't be charted; the message says why."""


@dataclass
class ChartData:
    x_label: str
    x: list  # floats (NaN where empty), or category labels
    categorical: bool
    series: list[tuple[str, np.ndarray]]  # (name, y values with NaN gaps)


def chart_data(model, cells) -> ChartData:
    """Chart data from the selected (row, col) cells of a SheetModel."""
    rows = sorted({row for row, _ in cells})
    cols = sorted({col for _, col in cells})
    if len(cols) < 2:
        raise ChartError("Select at least two columns: the first for x, the others for y.")
    x_col, y_cols = cols[0], cols[1:]

    def is_text(row, col):
        return isinstance(model.value(row, col), str)

    header = any(is_text(rows[0], col) for col in y_cols)
    if header:
        names = [model.display_text(rows[0], col) or f"Column {column_name(col)}" for col in cols]
        rows = rows[1:]
    else:
        names = [f"Column {column_name(col)}" for col in cols]
    if not rows:
        raise ChartError("Select some rows of data below the header.")

    x_values = [model.value(row, x_col) for row in rows]
    categorical = any(v is not None and not isinstance(v, float) for v in x_values)
    if categorical:
        x = [model.display_text(row, x_col) for row in rows]
    else:
        # Rows without an x value can't be placed, so they're left out.
        rows = [row for row, v in zip(rows, x_values) if v is not None]
        x = [model.value(row, x_col) for row in rows]

    series = []
    for name, col in zip(names[1:], y_cols):
        y = np.array([_number(model.value(row, col)) for row in rows], dtype=float)
        series.append((name, y))
    if not series or all(np.isnan(y).all() for _, y in series):
        raise ChartError("There are no numbers to plot in the y columns.")
    return ChartData(names[0] if header else "", x, categorical, series)


def _number(value) -> float:
    return value if isinstance(value, float) and math.isfinite(value) else math.nan


def draw(axes, data: ChartData, kind: str) -> None:
    axes.clear()
    for name, y in data.series:
        if kind == "scatter":
            axes.scatter(data.x, y, label=name)
        else:
            # Small markers keep a value between two gaps visible; with many
            # points they'd just clutter the line.
            marker = "o" if len(data.x) <= MARKER_LIMIT else None
            axes.plot(data.x, y, label=name, marker=marker, markersize=3)
    axes.set_xlabel(data.x_label)
    if len(data.series) == 1:
        axes.set_ylabel(data.series[0][0])
    else:
        axes.legend()
    axes.grid(True, alpha=0.3)


class ChartWindow(QWidget):
    """A window showing a chart of some cells. It redraws when the sheet
    changes, and its kind can be switched between line and scatter."""

    def __init__(self, model, cells, kind: str = "line", parent=None):
        super().__init__(parent, Qt.Window)
        self.model = model
        self.cells = set(cells)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(720, 520)

        self.figure = Figure(layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.axes = self.figure.add_subplot()
        self.kind_box = QComboBox()
        for key, label in CHART_KINDS.items():
            self.kind_box.addItem(label, key)
        self.kind_box.setCurrentIndex(list(CHART_KINDS).index(kind))
        self.kind_box.currentIndexChanged.connect(self.redraw)
        self.problem = QLabel()  # says why the chart can't be drawn, if it can't

        controls = QHBoxLayout()
        controls.addWidget(NavigationToolbar2QT(self.canvas, self))
        controls.addStretch()
        controls.addWidget(QLabel("Chart type:"))
        controls.addWidget(self.kind_box)
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.canvas)
        layout.addWidget(self.problem)

        rows = [row for row, _ in self.cells]
        cols = [col for _, col in self.cells]
        self.range_name = f"{cell_name(min(rows), min(cols))}:{cell_name(max(rows), max(cols))}"
        model.contents_changed.connect(self.redraw)
        self.redraw()

    @property
    def kind(self) -> str:
        return self.kind_box.currentData()

    def redraw(self, *_args) -> None:
        self.setWindowTitle(f"{CHART_KINDS[self.kind]} Chart of {self.range_name}")
        try:
            data = chart_data(self.model, self.cells)
        except ChartError as e:
            self.axes.clear()
            self.problem.setText(str(e))
        else:
            draw(self.axes, data, self.kind)
            self.problem.setText("")
        self.canvas.draw_idle()
