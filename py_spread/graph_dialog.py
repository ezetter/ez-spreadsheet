"""The Graph dialog: the kind of graph, the columns across and up, and the
marker drawn on each point, for a Seaborn graph of selected cells in the
notebook, or for changing one of the notebook's graphs."""

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

from .notebook import GRAPH_KINDS, NEEDS_MARKERS, GraphChoice

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
SCATTER_DEFAULT = "o"  # what a graph needing markers gets in place of None
ALL_OTHERS = "All other columns with numbers"


def graph_labels(graphs) -> list[str]:
    """How the Graph list names each of the notebook's graphs: "df2: Sales
    against Month", numbered if two would read the same."""
    labels = [f"{graph.frame}: {graph.title}" if graph.frame else graph.title.capitalize() for graph in graphs]
    return [f"{label} ({labels[:i].count(label) + 1})" if labels.count(label) > 1 else label
            for i, label in enumerate(labels)]


class GraphDialog(QDialog):
    """The graph type (Line, Scatter, or Categorical scatter), the X axis
    column, the Y axis column (or all the others with numbers, a series
    each), and a marker (None by default). For a new graph of `columns`
    (GraphColumns), the axes start at the type's defaults, and follow the
    type until an X axis is chosen (and the Y axis follows the X until it's
    chosen). Scatter graphs need markers to show
    their points, so None is unavailable for them; choosing one switches
    None to circles, and Line switches them back.

    Given the notebook's `graphs` (GraphCells), it's for changing one of
    them instead: a Graph list chooses which, starting at graphs[current],
    and the controls show what it draws now. Its columns can be changed if
    its DataFrame's cell was found."""

    def __init__(self, parent=None, columns=None, kind: str = "line", marker: str | None = None,
                 graphs=None, current: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Graph")
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * 48)
        self.graphs = list(graphs or [])
        self.columns = columns
        layout = QVBoxLayout(self)
        if self.graphs:
            summary = QLabel("Change one of the notebook's graphs. It's redrawn when you click OK.")
            summary.setWordWrap(True)
            layout.addWidget(summary)

        form = QFormLayout()
        self.graph_box = None
        if self.graphs:
            self.graph_box = QComboBox()
            self.graph_box.addItems(graph_labels(self.graphs))
            form.addRow("Graph:", self.graph_box)
        self.kind_box = QComboBox()
        for key, name in GRAPH_KINDS.items():
            self.kind_box.addItem(name, key)
        form.addRow("Graph type:", self.kind_box)
        self.x_box = QComboBox()
        form.addRow("X axis:", self.x_box)
        self.y_box = QComboBox()
        form.addRow("Y axis:", self.y_box)
        self.marker_box = QComboBox()
        for code, label in MARKERS.items():
            self.marker_box.addItem(label, code)
        form.addRow("Marker:", self.marker_box)
        layout.addLayout(form)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        self._loading = False
        self._none_replaced = False  # a scatter graph swapped None for circles, to undo on Line
        self._x_chosen = bool(self.graphs)  # a graph's own columns stay; a new one's follow the type
        self._y_chosen = bool(self.graphs)  # likewise, the y follows the x until chosen
        self.kind_box.currentIndexChanged.connect(lambda _index: self._kind_changed())
        self.x_box.activated.connect(self._x_picked)
        self.y_box.activated.connect(self._y_picked)
        self.x_box.currentIndexChanged.connect(lambda _index: self._x_changed())
        self.marker_box.activated.connect(self._marker_chosen)
        if self.graphs:
            self.graph_box.setCurrentIndex(current)
            self.graph_box.currentIndexChanged.connect(self._show_graph)
            self._show_graph(current)
        else:
            self._show(kind, marker, None, None)

    # --- What was chosen ---

    def chosen_graph(self) -> int | None:
        """Which of the graphs to change (an index), when changing one."""
        return self.graph_box.currentIndex() if self.graph_box is not None else None

    def kind(self) -> str:
        return self.kind_box.currentData()

    def marker(self) -> str | None:
        return self.marker_box.currentData()

    def x(self) -> str | None:
        return self.x_box.currentData()

    def ys(self) -> list[str]:
        return list(self.y_box.currentData() or [])

    def choice(self) -> GraphChoice:
        return GraphChoice(self.kind(), self.marker(), self.x(), self.ys())

    # --- Showing settings ---

    def _show_graph(self, index: int) -> None:
        graph = self.graphs[index]
        self.columns = graph.columns
        if graph.columns is not None and graph.x_label not in graph.columns.labels:
            self.columns = None  # its x isn't one of its DataFrame's columns: changed by hand
        self._show(graph.kind, graph.marker, graph.x_label, graph.y_labels)

    def _show(self, kind: str, marker: str | None, x: str | None, ys: list[str] | None) -> None:
        self._loading = True
        if marker is not None and self.marker_box.findData(marker) < 0:
            self.marker_box.addItem(marker, marker)  # one set in the code that the list doesn't have
        self._none_replaced = False
        self.marker_box.setCurrentIndex(max(0, self.marker_box.findData(marker)))
        self.kind_box.setCurrentIndex(max(0, self.kind_box.findData(kind)))
        self.x_box.clear()
        known = self.columns is not None
        for box in (self.x_box, self.y_box):
            box.setEnabled(known)
            box.setToolTip("" if known else "The columns can't be changed: the cell making the graph's "
                                             "DataFrame wasn't found, or was changed by hand.")
        if known:
            for label in self.columns.labels:
                self.x_box.addItem(label, label)
            self.x_box.setCurrentIndex(self.x_box.findData(x if x is not None else self.columns.default_x(kind)))
        else:
            self.x_box.addItem(x or "?", x)
        self._loading = False
        self._fill_ys(ys)
        self._kind_changed()

    def _fill_ys(self, ys: list[str] | None) -> None:
        """The Y axis choices for the X axis chosen, selecting `ys` (or the
        default: all the others with numbers)."""
        self._loading = True
        self.y_box.clear()
        if self.columns is None:
            self.y_box.addItem(", ".join(ys or []) or "?", list(ys or []))
        else:
            options = self.columns.y_options(self.x())
            if len(options) > 1:
                self.y_box.addItem(ALL_OTHERS, options)
            for label in options:
                self.y_box.addItem(label, [label])
            wanted = list(ys) if ys is not None else self.columns.default_ys(self.x())
            index = next((i for i in range(self.y_box.count()) if self.y_box.itemData(i) == wanted), -1)
            if index < 0 and ys is not None and len(wanted) > 1:  # some of the columns, set by hand
                self.y_box.addItem(", ".join(wanted), wanted)
                index = self.y_box.count() - 1
            self.y_box.setCurrentIndex(max(0, index))
        self._loading = False

    # --- Following changes ---

    def _kind_changed(self) -> None:
        if self._loading:
            return
        kind = self.kind()
        needs_markers = kind in NEEDS_MARKERS
        none_item = self.marker_box.model().item(0)
        none_item.setEnabled(not needs_markers)
        none_item.setToolTip("A scatter graph needs markers to show its points." if needs_markers else "")
        if needs_markers and self.marker() is None:
            self.marker_box.setCurrentIndex(self.marker_box.findData(SCATTER_DEFAULT))
            self._none_replaced = True
        elif not needs_markers and self._none_replaced:
            self.marker_box.setCurrentIndex(0)
            self._none_replaced = False
        if not self._x_chosen and self.columns is not None:  # a new graph's x follows the type
            x = self.columns.default_x(kind)
            if x != self.x():
                self.x_box.setCurrentIndex(self.x_box.findData(x))

    def _x_picked(self, _index: int) -> None:
        self._x_chosen = True  # the user's choice now, whatever the type

    def _y_picked(self, _index: int) -> None:
        self._y_chosen = True

    def _x_changed(self) -> None:
        if self._loading or self.columns is None:
            return
        ys = self.ys()
        options = self.columns.y_options(self.x())
        if not self._y_chosen or len(ys) > 1 or not ys or ys[0] not in options:
            ys = None  # the default (all the others), or what was chosen is now the x
        self._fill_ys(ys)

    def _marker_chosen(self, _index: int) -> None:
        self._none_replaced = False  # the marker is now the user's choice
