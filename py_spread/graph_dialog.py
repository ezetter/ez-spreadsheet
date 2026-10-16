"""The Chart dialog: the kind of chart, the columns across, up, coloring
the points, and splitting the chart into panels, and the marker drawn on
each point, for a Seaborn chart of selected cells in the notebook, or for
changing one of the notebook's charts. (The code calls charts graphs.)"""

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

from .appearance import error_color
from .frame_name_dialog import FrameNameField
from .notebook import (
    ALL_SERIES,
    CATEGORICAL,
    COL_WRAP,
    FACETED,
    GRAPH_TYPES,
    NEEDS_MARKERS,
    REGRESSION,
    GraphChoice,
)

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
TYPE_OF = {"swarm": "strip", "reg": "scatter"}  # the chart type of kinds that are a checkbox of another
NO_HUE = "None"
NO_COL = "None"
NEW_CHART = "New chart"
ALL_YS = "All"  # a line chart's y: every other column with numbers, a line each
CATEGORIES_TIP = ("Take the Y axis column's values as the categories, turning the chart sideways: "
                  "categories down the side, numbers across. A column of text always is.")
HUE_TIP = "A column whose values color the points, with a legend"
COL_TIP = (f"A column whose values each get a panel, {COL_WRAP} to a row, sharing their axes: categories "
           "(text), or numbers such as years")
NO_COLS_TIP = "There's no column, besides the X and Y axes', to split the chart by."
REGRESSION_TIP = ("Fit a straight line to the points, with a band showing its 95% confidence interval "
                  "(Seaborn's lmplot). It needs numbers across, so the X axis offers only columns with numbers.")
NO_REGRESSION_TIP = "A linear regression needs two columns with numbers: one across, and one up."
_CURRENT = object()  # (for _set_axes: the Col chosen now)


def graph_labels(graphs) -> list[str]:
    """How the Chart list names each of the notebook's charts: "df2: Sales
    against Month", numbered if two would read the same."""
    labels = [f"{graph.frame}: {graph.title}" if graph.frame else graph.title.capitalize() for graph in graphs]
    return [f"{label} ({labels[:i].count(label) + 1})" if labels.count(label) > 1 else label
            for i, label in enumerate(labels)]


class GraphDialog(QDialog):
    """The chart type (Line, Scatter, which can have a linear regression
    line fitted to it, or Categorical scatter, which can be a swarm plot),
    the X axis column, the Y axis column, the Hue column whose values color
    the points (None by default), the Col column splitting it into a panel
    for each of its values (None by default; a column of numbers, such as
    years, isn't one of All's lines then), and a marker (None by default).
    Up takes a column with numbers, except that a categorical scatter
    across a column of numbers can have its categories up, turning it
    sideways: a column of text, or one of numbers (such as years) with "Y
    axis as categories" checked. Across then takes only columns with
    numbers, as it does for a linear regression. For a new graph of
    `columns` (GraphColumns), the axes start at the type's defaults, and
    follow the type until an X axis is chosen (and the Y axis follows the
    X until it's chosen). Scatter graphs need markers to show their points,
    so None is unavailable for them; choosing one switches None to circles,
    and Line switches them back.

    Given the notebook's `graphs` (GraphCells), a Chart list chooses New
    chart or one of them to change, starting at graphs[current] (None: New
    chart); the controls show what a chart draws now, and its columns can be
    changed if its DataFrame's cell was found. A new chart is of `columns`,
    from `new_source` (such as "the selected cells, A1:C4"), or can't be
    made, for the reason `new_problem` gives.

    At the top, the DataFrame's name: for a new chart, starting at `frame`,
    and changeable (a Python name; one of `taken`, which the notebook
    already sets, is replaced); for one of the graphs, its own, shown."""

    def __init__(self, parent=None, columns=None, kind: str = "line", marker: str | None = None,
                 graphs=None, current: int | None = None, new_source: str = "", new_problem: str | None = None,
                 frame: str = "df", taken=()):
        super().__init__(parent)
        self.setWindowTitle("Chart")
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * 48)
        self.graphs = list(graphs or [])
        self.columns = columns
        self._new = (columns, kind, marker)  # what a new chart starts from
        self.new_source, self.new_problem = new_source, new_problem
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.form = form = QFormLayout()
        self._new_name = frame  # what a new chart's DataFrame is called, as typed
        self.name_field = FrameNameField(frame, taken)
        form.addRow("DataFrame name:", self.name_field)
        self.graph_box = None
        if self.graphs:
            self.graph_box = QComboBox()
            self.graph_box.addItem(NEW_CHART, None)
            for index, label in enumerate(graph_labels(self.graphs)):
                self.graph_box.addItem(label, index)
            form.addRow("Chart:", self.graph_box)
        self.kind_box = QComboBox()
        for key, name in GRAPH_TYPES.items():
            self.kind_box.addItem(name, key)
        form.addRow("Chart type:", self.kind_box)
        self.swarm_box = QCheckBox("Swarm plot")
        self.swarm_box.setToolTip("Spread each category's points out so none overlap, "
                                  "instead of scattering them a little at random")
        form.addRow("", self.swarm_box)
        self.categories_box = QCheckBox("Y axis as categories")
        self.categories_box.setToolTip(CATEGORIES_TIP)
        form.addRow("", self.categories_box)
        self.regression_box = QCheckBox("Linear regression")
        self.regression_box.setToolTip(REGRESSION_TIP)
        form.addRow("", self.regression_box)
        self.x_box = QComboBox()
        form.addRow("X axis:", self.x_box)
        self.y_box = QComboBox()
        form.addRow("Y axis:", self.y_box)
        self.hue_box = QComboBox()
        self.hue_box.setToolTip(HUE_TIP)
        form.addRow("Hue:", self.hue_box)
        self.col_box = QComboBox()
        self.col_box.setToolTip(COL_TIP)
        form.addRow("Col:", self.col_box)
        self.marker_box = QComboBox()
        for code, label in MARKERS.items():
            self.marker_box.addItem(label, code)
        form.addRow("Marker:", self.marker_box)
        layout.addLayout(form)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.ok_button = box.button(QDialogButtonBox.Ok)

        self._loading = False
        self._allowed = True  # whether the type can be chosen (see _allow)
        self._older_ys = None  # the series of a chart being changed that has several (they stay)
        self._every = []  # what All takes up now
        self._none_replaced = False  # a scatter graph swapped None for circles, to undo on Line
        self._x_chosen = bool(self.graphs)  # a graph's own columns stay; a new one's follow the type
        self._y_chosen = bool(self.graphs)  # likewise, the y follows the x until chosen
        self.kind_box.currentIndexChanged.connect(lambda _index: self._kind_changed())
        self.swarm_box.toggled.connect(lambda _checked: self._kind_changed())
        self.regression_box.toggled.connect(lambda _checked: self._kind_changed())
        self.categories_box.toggled.connect(lambda _checked: self._categories_toggled())
        self.x_box.activated.connect(self._x_picked)
        self.y_box.activated.connect(self._y_picked)
        self.x_box.currentIndexChanged.connect(lambda _index: self._x_changed())
        self.y_box.currentIndexChanged.connect(lambda _index: self._y_changed())
        self.col_box.currentIndexChanged.connect(lambda _index: self._col_changed())
        self.name_field.changed.connect(self._name_changed)
        self.marker_box.activated.connect(self._marker_chosen)
        if self.graphs:
            self.graph_box.setCurrentIndex(0 if current is None else current + 1)
            self.graph_box.currentIndexChanged.connect(lambda _index: self._show_item())
            self._show_item()
        else:
            self._show_new()

    # --- What was chosen ---

    def chosen_graph(self) -> int | None:
        """Which of the graphs to change (an index), or None for a new chart."""
        return self.graph_box.currentData() if self.graph_box is not None else None

    def kind(self) -> str:
        kind = self.kind_box.currentData()
        if kind in CATEGORICAL and self.swarm_box.isChecked():
            return "swarm"
        if kind == TYPE_OF["reg"] and self.regression_box.isChecked():
            return "reg"
        return kind

    def marker(self) -> str | None:
        return self.marker_box.currentData()

    def x(self) -> str | None:
        return self.x_box.currentData()

    def ys(self) -> list[str]:
        return list(self.y_box.currentData() or [])

    def hue(self) -> str | None:
        return None if len(self.ys()) > 1 else self.hue_box.currentData()  # several ys: a series each

    def col(self) -> str | None:
        """The column splitting the chart into panels, if any."""
        return self.col_box.currentData() if self.kind() in FACETED else None

    def y_categories(self) -> bool:
        """Whether a categorical scatter is sideways, with the y column its categories."""
        return self.kind() in CATEGORICAL and self.categories_box.isChecked()

    def frame(self) -> str | None:
        """A new chart's DataFrame name (None when changing a chart)."""
        return self.name_field.name() if self.chosen_graph() is None else None

    def choice(self) -> GraphChoice:
        return GraphChoice(self.kind(), self.marker(), self.x(), self.ys(), self.hue(), self.y_categories(),
                           self.col(), self.frame())

    # --- Showing settings ---

    def _show_item(self) -> None:
        index = self.graph_box.currentData()
        if index is None:
            self._show_new()
        else:
            self._show_graph(index)

    def _show_new(self) -> None:
        """New chart: its columns from the cells being charted, starting at
        the defaults; or, if they can't be charted, why not (and no OK)."""
        columns, kind, marker = self._new
        self.columns = columns
        self._x_chosen = self._y_chosen = False
        self._older_ys = None
        problem = self.new_problem
        if problem is not None:
            self._say(f"A new chart of {self.new_source} can't be made. {problem}", error=True)
        else:
            self._say(f"A new chart of {self.new_source}." if self.new_source else "")
        self.name_field.set_name(self._new_name)
        self._allow(problem is None)
        self._show(kind, marker, None, None, None, False, None)

    def _show_graph(self, index: int) -> None:
        graph = self.graphs[index]
        self._x_chosen = self._y_chosen = True  # a chart's own columns stay, whatever the type
        self._older_ys = graph.y_labels if len(graph.y_labels) > 1 else None  # its series, kept as they are
        self._say("Change this chart. It's redrawn when you click OK.")
        self.name_field.set_fixed(graph.frame)
        self._allow(True)
        self.columns = graph.columns
        if graph.columns is not None and graph.x_label not in graph.columns.labels:
            self.columns = None  # its x isn't one of its DataFrame's columns: changed by hand
        self._show(graph.kind, graph.marker, graph.x_label, graph.y_labels, graph.hue, graph.y_categories,
                   graph.col)

    def _show(self, kind: str, marker: str | None, x: str | None, ys: list[str] | None, hue: str | None,
              y_categories: bool, col: str | None) -> None:
        self._loading = True
        if marker is not None and self.marker_box.findData(marker) < 0:
            self.marker_box.addItem(marker, marker)  # one set in the code that the list doesn't have
        self._none_replaced = False
        self.marker_box.setCurrentIndex(max(0, self.marker_box.findData(marker)))
        self.kind_box.setCurrentIndex(max(0, self.kind_box.findData(TYPE_OF.get(kind, kind))))
        self.swarm_box.setChecked(kind == "swarm")
        self.regression_box.setChecked(kind in REGRESSION and (self.columns is None or self.columns.can_regress))
        self.categories_box.setChecked(y_categories)
        known = self.columns is not None
        for box in (self.x_box, self.y_box, self.hue_box, self.col_box, self.categories_box):
            box.setEnabled(known)
            box.setToolTip("" if known else "The columns can't be changed: the cell making the chart's "
                                             "DataFrame wasn't found, or was changed by hand.")
        self._loading = False
        if known:
            x = x if x is not None else self.columns.default_x(kind)
            self._every = []  # (what All took up for another chart)
            self._set_axes(x, list(ys) if ys is not None else None, col)
        else:
            self._loading = True
            self.x_box.clear()
            self.x_box.addItem(x or "?", x)
            self.y_box.clear()
            self.y_box.addItem(", ".join(ys or []) or "?", list(ys or []))
            self._loading = False
            self._fill_cols(col)
        self._fill_hues(hue)
        self._kind_changed()

    def _set_axes(self, x: str, ys: list[str] | None, col=_CURRENT) -> None:
        """Fill the X and Y axis choices, which depend on the type and each
        other, and the Col choices, which depend on both, selecting `x`,
        `ys`, and `col` where they still work (else the defaults). A
        categorical scatter can have categories up, with numbers across;
        otherwise up takes numbers. All, for a line chart, takes every
        column with numbers but x and the col."""
        kind = self.kind()
        col = self.col_box.currentData() if col is _CURRENT else col
        splitting = col if kind in FACETED else None
        if x not in self.columns.x_options(None, kind):  # a linear regression's x has to have numbers
            x = self.columns.default_x(kind, splitting)
        options = self.columns.y_options(x, kind)
        every = [y for y in self.columns.y_options(x) if y != splitting] if kind in ALL_SERIES else []
        if ys is not None and len(ys) > 1 and ys == self._every and len(every) > 1:
            ys = every  # All still, though what it takes may have changed
        if (ys is None or any(y not in options for y in ys)
                or len(ys) > 1 and ys != every and ys != self._older_ys):
            ys = self.columns.default_ys(x, kind, splitting)
        self._every = every
        self._loading = True
        self._show_categories(x, ys)
        self.x_box.clear()
        for label in self.columns.x_options(ys[0] if len(ys) == 1 else None, kind, self.y_categories()):
            self.x_box.addItem(label, label)
        self.x_box.setCurrentIndex(max(0, self.x_box.findData(x)))
        self.y_box.clear()
        if len(every) > 1:
            self.y_box.addItem(ALL_YS, every)
        for label in options:
            self.y_box.addItem(label, [label])
        index = next((i for i in range(self.y_box.count()) if self.y_box.itemData(i) == ys), -1)
        if index < 0 and len(ys) > 1:  # a series each, from an older chart
            self.y_box.addItem(", ".join(ys), ys)
            index = self.y_box.count() - 1
        self.y_box.setCurrentIndex(max(0, index))
        self._fill_cols(col)  # not x or y
        self._loading = False
        self._y_changed()

    def _show_categories(self, x: str, ys: list[str]) -> None:
        """Y axis as categories: always so for a column of text up (sideways),
        never for one across (it's the categories), and the user's choice
        when there are numbers both ways."""
        y = ys[0] if len(ys) == 1 else None
        if y is not None and self.columns.category(y):
            checked, enabled, tip = True, False, "A column of text up is always categories."
        elif y is None or self.columns.category(x):
            checked, enabled, tip = False, False, "The categories are across, in the X axis column."
        else:
            checked, enabled, tip = self.categories_box.isChecked(), True, CATEGORIES_TIP
        self.categories_box.setChecked(checked)
        self.categories_box.setEnabled(enabled)
        self.categories_box.setToolTip(tip)

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

    def _fill_cols(self, col: str | None) -> None:
        """None, and the columns that can split a chart into panels,
        selecting `col` if it's still one."""
        known = self.columns is not None
        options = self.columns.col_options(self.x(), self._col_ys()) if known else [col] if col else []
        loading, self._loading = self._loading, True
        self.col_box.clear()
        self.col_box.addItem(NO_COL, None)
        for label in options:
            self.col_box.addItem(label, label)
        self.col_box.setCurrentIndex(max(0, self.col_box.findData(col)) if col in options else 0)
        self._loading = loading
        if known:
            self.col_box.setEnabled(bool(options))
            self.col_box.setToolTip(COL_TIP if options else NO_COLS_TIP)

    def _col_ys(self) -> list[str]:
        """What's up that the col can't be: nothing for All (which leaves
        out the col), or for a type without panels (the col waits, should
        Line be chosen again)."""
        ys = self.ys()
        return [] if self.kind() not in FACETED or len(ys) > 1 and ys == self._every else ys

    def _say(self, text: str, error: bool = False) -> None:
        self.summary.setText(text)
        self.summary.setVisible(bool(text))
        self.summary.setStyleSheet(f"color: {error_color(self.palette())};" if error else "")

    def _allow(self, allowed: bool) -> None:
        """Whether the type, marker, and name can be chosen, and OK clicked."""
        self._allowed = allowed
        for widget in (self.kind_box, self.swarm_box, self.regression_box, self.marker_box, self.name_field):
            widget.setEnabled(allowed)
        self._update_ok()

    def _update_ok(self) -> None:
        """OK, unless a new chart can't be made, or its DataFrame's name won't do."""
        self.ok_button.setEnabled(self._allowed and self.name_field.problem() is None)

    def _name_changed(self) -> None:
        if self.chosen_graph() is None:
            self._new_name = self.name_field.edit.text()  # kept while a chart to change is looked at
        self._update_ok()

    # --- Following changes ---

    def _kind_changed(self) -> None:
        if self._loading:
            return
        kind = self.kind()
        self.form.setRowVisible(self.swarm_box, kind in CATEGORICAL)
        self.form.setRowVisible(self.categories_box, kind in CATEGORICAL)
        self.form.setRowVisible(self.col_box, kind in FACETED)
        self.form.setRowVisible(self.regression_box, self.kind_box.currentData() == TYPE_OF["reg"])
        can_regress = self.columns is None or self.columns.can_regress
        self.regression_box.setEnabled(self._allowed and can_regress)
        self.regression_box.setToolTip(REGRESSION_TIP if can_regress else NO_REGRESSION_TIP)
        needs_markers = kind in NEEDS_MARKERS
        none_item = self.marker_box.model().item(0)
        none_item.setEnabled(not needs_markers)
        none_item.setToolTip("A scatter chart needs markers to show its points." if needs_markers else "")
        if needs_markers and self.marker() is None:
            self.marker_box.setCurrentIndex(self.marker_box.findData(SCATTER_DEFAULT))
            self._none_replaced = True
        elif not needs_markers and self._none_replaced:
            self.marker_box.setCurrentIndex(0)
            self._none_replaced = False
        if self.columns is None:
            return
        if not self._x_chosen:  # a new graph's x follows the type
            x = self.columns.default_x(kind, self.col_box.currentData())
            if x != self.x():
                self._set_axes(x, self.ys() if self._y_chosen else None)
                self._fill_hues(self.hue_box.currentData() if self.hue_box.currentData() != x else None)
        # What works across and up depends on the type; and a new chart's y follows it until chosen.
        x, hue = self.x(), self.hue_box.currentData()
        self._set_axes(x, self.ys() if self._y_chosen else None)
        if self.x() != x:  # numbers across, for a linear regression
            self._fill_hues(hue if hue != self.x() else None)

    def _categories_toggled(self) -> None:
        if not self._loading and self.columns is not None:
            self._set_axes(self.x(), self.ys())  # categories up: only numbers across

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
        """Categories up limit what can go across; the y column can't split
        the chart too; and several y columns (All, or an older graph's) are
        colored a series each, so there's no hue."""
        if self._loading or self.columns is None:
            return
        ys = self.ys()
        across = self.columns.x_options(ys[0] if len(ys) == 1 else None, self.kind(), self.y_categories())
        if [self.x_box.itemData(i) for i in range(self.x_box.count())] != across:
            self._set_axes(self.x(), ys)
            return
        if self.col_box.currentData() not in (None, *self.columns.col_options(self.x(), self._col_ys())):
            self._set_axes(self.x(), ys, None)  # it took the col's column: no panels, and All takes it again
            return
        several = len(ys) > 1
        self.hue_box.setEnabled(not several)
        self.hue_box.setToolTip("Each column is its own series, in its own color." if several else HUE_TIP)

    def _col_changed(self) -> None:
        """A column of numbers splitting a line chart isn't one of All's lines."""
        if not self._loading and self.columns is not None:
            self._set_axes(self.x(), self.ys())

    def _marker_chosen(self, _index: int) -> None:
        self._none_replaced = False  # the marker is now the user's choice
