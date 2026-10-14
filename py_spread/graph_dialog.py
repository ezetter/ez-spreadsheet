"""The Graph dialog: a line or scatter graph, and the marker drawn on each
point, for a Seaborn graph of selected cells in the notebook, or for changing
one of the notebook's graphs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
)

KINDS = {"line": "Line", "scatter": "Scatter"}
MARKERS = {  # Matplotlib's marker code -> its name in the dialog
    None: "None",
    "o": "● Circle",
    ".": "• Point",
    "s": "■ Square",
    "D": "◆ Diamond",
    "^": "▲ Triangle up",
    "v": "▼ Triangle down",
    "+": "+ Plus",
    "x": "× Cross",
    "*": "★ Star",
}
SCATTER_DEFAULT = "o"  # what a scatter graph gets in place of None


def describe(x_label: str, y_labels: list[str]) -> str:
    """What's graphed against what: "Sales and Cost against Month"."""
    if len(y_labels) == 1:
        ys = y_labels[0]
    elif len(y_labels) == 2:
        ys = f"{y_labels[0]} and {y_labels[1]}"
    else:
        ys = f"{', '.join(y_labels[:-1])}, and {y_labels[-1]}"
    return f"Graph {ys} against {x_label}."


def graph_labels(graphs) -> list[str]:
    """How the Graph list names each of the notebook's graphs: "df2: Sales
    against Month", numbered if two would read the same."""
    labels = [f"{graph.frame}: {graph.title}" if graph.frame else graph.title.capitalize() for graph in graphs]
    return [f"{label} ({labels[:i].count(label) + 1})" if labels.count(label) > 1 else label
            for i, label in enumerate(labels)]


class GraphDialog(QDialog):
    """Line or Scatter, and a marker (None by default). A scatter graph needs
    markers to show its points, so None is unavailable for one; choosing
    Scatter switches None to circles, and Line switches them back.

    Given the notebook's `graphs` (GraphCells), it's for changing one of
    them instead: a Graph list chooses which, starting at graphs[current],
    and shows its type and marker."""

    def __init__(self, parent=None, x_label: str = "", y_labels=(), kind: str = "line",
                 marker: str | None = None, graphs=None, current: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Graph")
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * 44)  # room for the summary
        self.graphs = list(graphs or [])
        layout = QVBoxLayout(self)
        summary = QLabel("Change one of the notebook's graphs. It's redrawn when you click OK."
                         if self.graphs else describe(x_label, list(y_labels)))
        summary.setWordWrap(True)
        summary.setTextFormat(Qt.PlainText)  # labels come from the sheet
        layout.addWidget(summary)

        form = QFormLayout()
        self.graph_box = None
        if self.graphs:
            self.graph_box = QComboBox()
            self.graph_box.addItems(graph_labels(self.graphs))
            self.graph_box.setCurrentIndex(current)
            form.addRow("Graph:", self.graph_box)
            kind, marker = self.graphs[current].kind, self.graphs[current].marker
        kinds = QHBoxLayout()
        self.kind_buttons = {}
        for key, label in KINDS.items():
            button = QRadioButton(label)
            kinds.addWidget(button)
            self.kind_buttons[key] = button
        kinds.addStretch()
        form.addRow("Graph type:", kinds)
        self.marker_box = QComboBox()
        for code, label in MARKERS.items():
            self.marker_box.addItem(label, code)
        form.addRow("Marker:", self.marker_box)
        layout.addLayout(form)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        self._none_replaced = False  # Scatter swapped None for circles, to undo on Line
        self.marker_box.activated.connect(self._marker_chosen)
        self._show_settings(kind, marker)
        for button in self.kind_buttons.values():
            button.toggled.connect(lambda checked: checked and self._kind_changed())
        if self.graph_box is not None:
            self.graph_box.currentIndexChanged.connect(
                lambda index: self._show_settings(self.graphs[index].kind, self.graphs[index].marker))

    def chosen_graph(self) -> int | None:
        """Which of the graphs to change (an index), when changing one."""
        return self.graph_box.currentIndex() if self.graph_box is not None else None

    def kind(self) -> str:
        return next(key for key, button in self.kind_buttons.items() if button.isChecked())

    def marker(self) -> str | None:
        return self.marker_box.currentData()

    def _show_settings(self, kind: str, marker: str | None) -> None:
        if marker is not None and self.marker_box.findData(marker) < 0:
            self.marker_box.addItem(marker, marker)  # one set in the code that the list doesn't have
        self._none_replaced = False
        self.marker_box.setCurrentIndex(max(0, self.marker_box.findData(marker)))
        self.kind_buttons[kind if kind in KINDS else "line"].setChecked(True)
        self._kind_changed()

    def _kind_changed(self) -> None:
        scatter = self.kind() == "scatter"
        none_item = self.marker_box.model().item(0)
        none_item.setEnabled(not scatter)
        none_item.setToolTip("A scatter graph needs markers to show its points." if scatter else "")
        if scatter and self.marker() is None:
            self.marker_box.setCurrentIndex(self.marker_box.findData(SCATTER_DEFAULT))
            self._none_replaced = True
        elif not scatter and self._none_replaced:
            self.marker_box.setCurrentIndex(0)
            self._none_replaced = False

    def _marker_chosen(self, _index: int) -> None:
        self._none_replaced = False  # the marker is now the user's choice
