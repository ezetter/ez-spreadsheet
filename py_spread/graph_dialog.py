"""The Graph dialog: the kind of graph, the columns across, up, and
coloring the points, and the marker drawn on each point, for a Seaborn
graph of selected cells in the notebook, or for changing one of the
notebook's graphs."""

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

from .notebook import CATEGORICAL, GRAPH_TYPES, NEEDS_MARKERS, GraphChoice

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
NO_HUE = "None"


def graph_labels(graphs) -> list[str]:
    """How the Graph list names each of the notebook's graphs: "df2: Sales
    against Month", numbered if two would read the same."""
    labels = [f"{graph.frame}: {graph.title}" if graph.frame else graph.title.capitalize() for graph in graphs]
    return [f"{label} ({labels[:i].count(label) + 1})" if labels.count(label) > 1 else label
            for i, label in enumerate(labels)]


class GraphDialog(QDialog):
    """The graph type (Line, Scatter, or Categorical scatter, which can be a
    swarm plot), the X axis column, the Y axis column, the Hue column whose
    values color the points (None by default), and a marker (None by
    default). Up takes a column with numbers, except that a categorical
    scatter across a column of numbers can have its categories up, turning
    it sideways; across then takes only columns with numbers. For a new graph of `columns` (GraphColumns), the axes start at
    the type's defaults, and follow the type until an X axis is chosen (and
    the Y axis follows the X until it's chosen). Scatter graphs need markers
    to show their points, so None is unavailable for them; choosing one
    switches None to circles, and Line switches them back.

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

        self.form = form = QFormLayout()
        self.graph_box = None
        if self.graphs:
            self.graph_box = QComboBox()
            self.graph_box.addItems(graph_labels(self.graphs))
            form.addRow("Graph:", self.graph_box)
        self.kind_box = QComboBox()
        for key, name in GRAPH_TYPES.items():
            self.kind_box.addItem(name, key)
        form.addRow("Graph type:", self.kind_box)
        self.swarm_box = QCheckBox("Swarm plot")
        self.swarm_box.setToolTip("Spread each category's points out so none overlap, "
                                  "instead of scattering them a little at random")
        form.addRow("", self.swarm_box)
        self.x_box = QComboBox()
        form.addRow("X axis:", self.x_box)
        self.y_box = QComboBox()
        form.addRow("Y axis:", self.y_box)
        self.hue_box = QComboBox()
        self.hue_box.setToolTip("A column whose values color the points, with a legend")
        form.addRow("Hue:", self.hue_box)
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
        self.swarm_box.toggled.connect(lambda _checked: self._kind_changed())
        self.x_box.activated.connect(self._x_picked)
        self.y_box.activated.connect(self._y_picked)
        self.x_box.currentIndexChanged.connect(lambda _index: self._x_changed())
        self.y_box.currentIndexChanged.connect(lambda _index: self._y_changed())
        self.marker_box.activated.connect(self._marker_chosen)
        if self.graphs:
            self.graph_box.setCurrentIndex(current)
            self.graph_box.currentIndexChanged.connect(self._show_graph)
            self._show_graph(current)
        else:
            self._show(kind, marker, None, None, None)

    # --- What was chosen ---

    def chosen_graph(self) -> int | None:
        """Which of the graphs to change (an index), when changing one."""
        return self.graph_box.currentIndex() if self.graph_box is not None else None

    def kind(self) -> str:
        kind = self.kind_box.currentData()
        return "swarm" if kind in CATEGORICAL and self.swarm_box.isChecked() else kind

    def marker(self) -> str | None:
        return self.marker_box.currentData()

    def x(self) -> str | None:
        return self.x_box.currentData()

    def ys(self) -> list[str]:
        return list(self.y_box.currentData() or [])

    def hue(self) -> str | None:
        return None if len(self.ys()) > 1 else self.hue_box.currentData()  # several ys: a series each

    def choice(self) -> GraphChoice:
        return GraphChoice(self.kind(), self.marker(), self.x(), self.ys(), self.hue())

    # --- Showing settings ---

    def _show_graph(self, index: int) -> None:
        graph = self.graphs[index]
        self.columns = graph.columns
        if graph.columns is not None and graph.x_label not in graph.columns.labels:
            self.columns = None  # its x isn't one of its DataFrame's columns: changed by hand
        self._show(graph.kind, graph.marker, graph.x_label, graph.y_labels, graph.hue)

    def _show(self, kind: str, marker: str | None, x: str | None, ys: list[str] | None, hue: str | None) -> None:
        self._loading = True
        if marker is not None and self.marker_box.findData(marker) < 0:
            self.marker_box.addItem(marker, marker)  # one set in the code that the list doesn't have
        self._none_replaced = False
        self.marker_box.setCurrentIndex(max(0, self.marker_box.findData(marker)))
        self.kind_box.setCurrentIndex(max(0, self.kind_box.findData("strip" if kind in CATEGORICAL else kind)))
        self.swarm_box.setChecked(kind == "swarm")
        known = self.columns is not None
        for box in (self.x_box, self.y_box, self.hue_box):
            box.setEnabled(known)
            box.setToolTip("" if known else "The columns can't be changed: the cell making the graph's "
                                             "DataFrame wasn't found, or was changed by hand.")
        self._loading = False
        if known:
            x = x if x is not None else self.columns.default_x(kind)
            self._set_axes(x, list(ys) if ys is not None else self.columns.default_ys(x))
        else:
            self._loading = True
            self.x_box.clear()
            self.x_box.addItem(x or "?", x)
            self.y_box.clear()
            self.y_box.addItem(", ".join(ys or []) or "?", list(ys or []))
            self._loading = False
        self._fill_hues(hue)
        self._kind_changed()

    def _set_axes(self, x: str, ys: list[str] | None) -> None:
        """Fill the X and Y axis choices, which depend on the type and each
        other, selecting `x` and `ys` where they still work (else the
        defaults). A categorical scatter can have categories up, with
        numbers across; otherwise up takes numbers."""
        kind = self.kind()
        if ys is None or len(ys) == 1 and ys[0] not in self.columns.y_options(x, kind):
            ys = self.columns.default_ys(x)
        self._loading = True
        self.x_box.clear()
        for label in self.columns.x_options(ys[0] if len(ys) == 1 else None, kind):
            self.x_box.addItem(label, label)
        self.x_box.setCurrentIndex(max(0, self.x_box.findData(x)))
        self.y_box.clear()
        for label in self.columns.y_options(x, kind):
            self.y_box.addItem(label, [label])
        index = next((i for i in range(self.y_box.count()) if self.y_box.itemData(i) == ys), -1)
        if index < 0 and len(ys) > 1:  # a series each, from an older graph
            self.y_box.addItem(", ".join(ys), ys)
            index = self.y_box.count() - 1
        self.y_box.setCurrentIndex(max(0, index))
        self._loading = False
        self._y_changed()

    def _fill_hues(self, hue: str | None) -> None:
        """None, and the columns that can color the points, selecting `hue`."""
        self._loading = True
        self.hue_box.clear()
        self.hue_box.addItem(NO_HUE, None)
        options = self.columns.hue_options(self.x()) if self.columns is not None else [hue] if hue else []
        for label in options:
            self.hue_box.addItem(label, label)
        self.hue_box.setCurrentIndex(max(0, self.hue_box.findData(hue)) if hue in options else 0)
        self._loading = False
        self._y_changed()

    # --- Following changes ---

    def _kind_changed(self) -> None:
        if self._loading:
            return
        kind = self.kind()
        self.form.setRowVisible(self.swarm_box, kind in CATEGORICAL)
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
        if self.columns is None:
            return
        if not self._x_chosen:  # a new graph's x follows the type
            x = self.columns.default_x(kind)
            if x != self.x():
                self._set_axes(x, self.ys() if self._y_chosen else None)
                self._fill_hues(self.hue_box.currentData() if self.hue_box.currentData() != x else None)
        self._set_axes(self.x(), self.ys())  # what works across and up depends on the type

    def _x_picked(self, _index: int) -> None:
        self._x_chosen = True  # the user's choice now, whatever the type

    def _y_picked(self, _index: int) -> None:
        self._y_chosen = True

    def _x_changed(self) -> None:
        if self._loading or self.columns is None:
            return
        ys, hue = self.ys(), self.hue_box.currentData()
        self._set_axes(self.x(), ys if self._y_chosen else None)
        self._fill_hues(hue if hue != self.x() else None)

    def _y_changed(self) -> None:
        """Categories up limit what can go across; and several y columns (an
        older graph's) are colored a series each, so there's no hue."""
        if self._loading or self.columns is None:
            return
        ys = self.ys()
        across = self.columns.x_options(ys[0] if len(ys) == 1 else None, self.kind())
        if [self.x_box.itemData(i) for i in range(self.x_box.count())] != across:
            self._set_axes(self.x(), ys)
            return
        several = len(ys) > 1
        self.hue_box.setEnabled(not several)
        self.hue_box.setToolTip("Each column is its own series, in its own color." if several
                                else "A column whose values color the points, with a legend")

    def _marker_chosen(self, _index: int) -> None:
        self._none_replaced = False  # the marker is now the user's choice
