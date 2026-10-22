import pytest

from ezsheet.graph_dialog import GraphDialog
from ezsheet.graphs import change_graph, find_graphs, read_graph
from ezsheet.model import SheetModel
from ezsheet.notebook import (
    DISTRIBUTION_KINDS,
    FrameData,
    GraphColumns,
    GraphError,
    dataframe_code,
    distribution_code,
    frame_graph_code,
    graph_code,
)
from ezsheet.window import MainWindow
from test_notebook import FakeKernel, block

TIPS = FrameData(["Day", "Tip", "Bill", "Size"],
                 [["Thu", "Fri", "Thu", "Sat", "Fri", "Thu"], [1.0, 2.5, 3.0, 2.0, 4.5, "n/a"],
                  [10.0, 20.0, 30.0, 15.0, 41.0, 12.0], [2, 3, 2, 4, 2, 3]])


@pytest.fixture
def pyplot():
    import matplotlib.pyplot as plt

    backend = plt.get_backend()
    plt.switch_backend("agg")
    yield plt
    plt.close("all")
    plt.switch_backend(backend)


def draw(code: str, frame: FrameData = TIPS):
    """Run a chart cell's code on the frame, as df; the chart (a Seaborn FacetGrid)."""
    import pandas as pd

    namespace = {"df": pd.DataFrame(dict(zip(frame.labels, frame.columns)))}
    exec(code, namespace)
    return namespace["chart"]


# --- The code ---

def test_a_histogram_by_default():
    code = distribution_code(TIPS)
    assert "chart = sns.displot(" in code and "data=data, x='Tip'," in code
    assert "kind='hist',  # or 'kde' or 'ecdf'" in code and "y=" not in code and "kde=" not in code
    assert "data['Tip'] = pd.to_numeric(data['Tip'], errors='coerce')  # text isn't charted" in code
    assert code.startswith("import pandas as pd\nimport seaborn as sns\n\n# df as a chart: the distribution of 'Tip'.")
    assert frame_graph_code(TIPS, kind="hist") == code


def test_every_choice():
    code = distribution_code(TIPS, "tips", "hist", "Bill", hue="Day", col="Size", kde=True, rug=True,
                             import_pandas=False, import_seaborn=False)
    assert code.splitlines() == [
        "# tips as a chart: the distribution of 'Bill', colored by 'Day', a panel for each 'Size'.",
        "sns.set_theme(style='whitegrid')",
        "chart = sns.displot(",
        "    data=tips, x='Bill', hue='Day',",
        "    col='Size', col_wrap=2,  # a panel for each, 2 to a row",
        "    kind='hist',  # or 'kde' or 'ecdf'",
        "    kde=True,  # its density curve over the bars",
        "    rug=True,  # a tick along the axis for each value",
        "    height=2.5, aspect=1.2,",
        ")"]


def test_of_two_columns():
    code = distribution_code(TIPS, kind="kde", x="Bill", ys=["Size"])
    assert "x='Bill', y='Size'" in code and "the distribution of 'Bill' and 'Size'" in code


@pytest.mark.parametrize("kind, x, ys, others, problem", [
    ("ecdf", "Bill", ["Size"], {}, "can't chart the distribution"),  # an ECDF is of one column
    ("hist", "Day", [], {}, "can't chart the distribution"),  # text across
    ("hist", "Bill", ["Day"], {}, "can't chart the distribution"),
    ("hist", "Bill", ["Size", "Tip"], {}, "can't chart the distribution"),
    ("hist", "Bill", ["Size"], {"kde": True}, "only a histogram of one column"),
    ("kde", "Bill", [], {"kde": True}, "only a histogram of one column"),
    ("hist", "Bill", [], {"hue": "Bill"}, "can't color"),
    ("hist", "Bill", ["Size"], {"col": "Size"}, "can't split"),
])
def test_what_wont_do(kind, x, ys, others, problem):
    with pytest.raises(ValueError, match=problem):
        distribution_code(TIPS, kind=kind, x=x, ys=ys, **others)


@pytest.mark.parametrize("kind, ys, others", [
    ("hist", [], {"kde": True, "rug": True, "hue": "Day"}),
    ("kde", [], {"rug": True}),
    ("ecdf", [], {"hue": "Day", "col": "Size"}),
    ("hist", ["Size"], {}),
    ("kde", ["Size"], {"rug": True}),
])
def test_drawn(pyplot, kind, ys, others):
    chart = draw(distribution_code(TIPS, kind=kind, x="Bill", ys=ys, **others))
    assert chart.axes.size == (3 if "col" in others else 1)  # (a panel for each Size: 2, 3, and 4)


def test_one_column_is_just_a_distribution(app):
    model = SheetModel(rows=10, cols=3)
    model.set_cells({(0, 0): "Bill", (1, 0): "10", (2, 0): "20", (3, 0): "15"})
    cells = block(0, 0, 3, 0)
    code = graph_code(model, cells, kind="hist")
    assert "x='Bill'" in code
    with pytest.raises(GraphError, match="A line chart needs at least two columns"):
        graph_code(model, cells)
    namespace = {}
    exec(dataframe_code(model, cells), namespace)
    assert GraphColumns.of(FrameData(["Bill"], [[1.0]])).only_distribution


def test_its_columns():
    columns = GraphColumns.of(TIPS)
    assert columns.x_options(None, "hist") == ["Tip", "Bill", "Size"]  # numbers only
    assert columns.x_options("Size", "kde") == ["Tip", "Bill"]
    assert columns.y_options("Tip", "hist") == ["Bill", "Size"]
    assert columns.default_x("ecdf") == "Tip" and columns.default_x("hist", col="Tip") == "Bill"
    assert columns.default_ys("Tip", "kde") == [] and not columns.only_distribution


# --- Read back, and changed ---

def test_read_back():
    graph = read_graph(distribution_code(TIPS, kind="hist", x="Bill", hue="Day", kde=True, rug=True))
    assert (graph.kind, graph.marker, graph.x_label, graph.y_labels, graph.hue, graph.kde, graph.rug) == (
        "hist", None, "Bill", [], "Day", True, True)
    assert graph.title == "the distribution of Bill"
    graph = read_graph(distribution_code(TIPS, kind="kde", x="Bill", ys=["Size"]))
    assert graph.title == "the distribution of Bill and Size" and not graph.kde
    assert read_graph("chart = sns.displot(data=df, x='Tip')").kind == "hist"  # (displot's own)
    assert read_graph("chart = sns.displot(data=df, x='Tip', kind='violin')") is None


def test_changed_in_place():
    code = distribution_code(TIPS, kind="hist", x="Bill", kde=True)
    changed = change_graph(code, "kde", None, False, True)
    assert "kind='kde',  # or 'hist' or 'ecdf'" in changed and "kde=True" not in changed
    assert "    rug=True,  # a tick along the axis for each value\n    height=4" in changed
    assert "density curve" not in changed  # (its comment goes with it)
    assert change_graph(changed, "hist", None, True, False) == code
    assert change_graph("chart = sns.displot(data=df, x='Tip')", "ecdf", None, False, True) == (
        "chart = sns.displot(kind='ecdf', rug=True, data=df, x='Tip')")
    assert change_graph("chart = sns.displot(data=df, x='Tip', kde=False)", "hist", None, True) == (
        "chart = sns.displot(data=df, x='Tip', kde=True)")


@pytest.mark.parametrize("code, args, problem", [
    ("chart = sns.displot(data=df, x='Tip')", ("scatter", "o"), "can't become"),
    ("chart = sns.relplot(data=df, x='Tip', y='Bill')", ("hist", None), "can't become"),
    ("chart = sns.displot(data=df, x='Tip', y='Bill')", ("ecdf", None), "an ECDF is of one column"),
    ("chart = sns.displot(data=df, x='Tip', y='Bill')", ("hist", None, True), "only a histogram of one column"),
])
def test_cant_be_changed_so(code, args, problem):
    with pytest.raises(ValueError, match=problem):
        change_graph(code, *args)


# --- The dialog ---

def state(dialog):
    return dialog.kind(), dialog.x(), dialog.ys(), dialog.hue(), dialog.marker(), dialog.kde(), dialog.rug()


def visible(dialog, widget):
    return dialog.form.isRowVisible(widget)


def test_dialog(app):
    dialog = GraphDialog(None, GraphColumns.of(TIPS), "scatter", "o")
    assert [dialog.kind_box.itemText(i) for i in range(4)] == ["Line", "Scatter", "Categorical", "Distribution"]
    assert not visible(dialog, dialog.distribution_box) and not visible(dialog, dialog.rug_box)
    dialog.kind_box.setCurrentIndex(3)
    assert state(dialog) == ("hist", "Tip", [], None, None, False, False)
    assert [dialog.distribution_box.itemText(i) for i in range(3)] == list(DISTRIBUTION_KINDS.values())
    assert visible(dialog, dialog.distribution_box) and visible(dialog, dialog.kde_box)
    assert visible(dialog, dialog.rug_box) and not visible(dialog, dialog.marker_box)
    assert [dialog.x_box.itemText(i) for i in range(dialog.x_box.count())] == ["Tip", "Bill", "Size"]
    assert [dialog.y_box.itemText(i) for i in range(dialog.y_box.count())] == ["None", "Bill", "Size"]
    dialog.kde_box.setChecked(True)
    dialog.rug_box.setChecked(True)
    dialog.hue_box.setCurrentIndex(dialog.hue_box.findData("Day"))
    dialog.col_box.setCurrentIndex(dialog.col_box.findData("Size"))
    choice = dialog.choice()
    assert (choice.kind, choice.x, choice.ys, choice.hue, choice.col, choice.kde, choice.rug, choice.marker) == (
        "hist", "Tip", [], "Day", "Size", True, True, None)
    dialog.y_box.setCurrentIndex(dialog.y_box.findData(["Bill"]))  # two columns: no KDE curve
    assert not dialog.kde_box.isEnabled() and not dialog.kde() and dialog.ys() == ["Bill"]
    dialog.distribution_box.setCurrentIndex(dialog.distribution_box.findData("ecdf"))  # no y
    assert dialog.ys() == [] and not dialog.y_box.isEnabled() and not visible(dialog, dialog.kde_box)
    assert dialog.kind() == "ecdf" and dialog.rug()
    dialog.distribution_box.setCurrentIndex(dialog.distribution_box.findData("kde"))
    assert dialog.y_box.isEnabled()
    dialog.kind_box.setCurrentIndex(1)  # back to a scatter: its marker, and (not chosen) its own x and y
    assert state(dialog)[:3] == ("scatter", "Day", ["Tip"]) and dialog.marker() == "o"
    assert dialog.y_box.isEnabled() and not dialog.rug() and not dialog.kde()


def test_a_scatter_becoming_a_distribution_starts_with_no_y(app):
    dialog = GraphDialog(None, GraphColumns.of(TIPS), "scatter", "o")
    dialog.y_box.setCurrentIndex(dialog.y_box.findData(["Size"]))
    dialog._y_picked(0)
    dialog.kind_box.setCurrentIndex(3)
    assert dialog.ys() == [] and dialog.x() == "Tip"


def test_one_column_only_offers_distribution(app):
    dialog = GraphDialog(None, GraphColumns.of(FrameData(["Bill"], [[1.0, 2.0]])), "line")
    assert dialog.kind() == "hist" and dialog.x() == "Bill"
    model = dialog.kind_box.model()
    assert [model.item(i).isEnabled() for i in range(4)] == [False, False, False, True]


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.kernel = FakeKernel()
    window.model.set_cells({(0, 0): "Day", (0, 1): "Bill", (0, 2): "Tip", (1, 0): "Thu", (1, 1): "10",
                            (1, 2): "1.5", (2, 0): "Fri", (2, 1): "20", (2, 2): "3", (3, 0): "Thu", (3, 1): "30",
                            (3, 2): "4"})
    window.show()
    yield window
    if window.notebook_window is not None:
        window.notebook_window.hide()
    window.setWindowModified(False)
    window.close()


def test_make_one(window, dialogs):
    dialogs.graph_answer = ("hist", None, "Bill", [], "Day", False, None, True, True)
    window.view.select_range(0, 0, 3, 2)
    window.graph_action.trigger()
    source = window.notebook.cells[-1].source
    assert "chart = sns.displot(" in source and "x='Bill', hue='Day'" in source
    assert "kde=True" in source and "rug=True" in source
    assert (window.graph_kind, window.graph_marker) == ("hist", None)


def test_a_column_of_numbers(window, dialogs):
    dialogs.graph_answer = ("hist", None)
    window.view.select_range(0, 1, 3, 1)  # just Bill
    window.graph_action.trigger()
    assert dialogs.graph_prompts[-1][0] == ["Bill"]
    assert "x='Bill'" in window.notebook.cells[-1].source


def test_change_one(window, dialogs):
    dialogs.graph_answer = ("hist", None, "Bill", [])
    window.view.select_range(0, 0, 3, 2)
    window.graph_action.trigger()
    graph_id = window.notebook.cells[-1].id
    window.view.setCurrentIndex(window.model.index(0, 0))
    dialogs.graph_change_answer = (0, "kde", None, "Bill", [], None, False, None, False, True)
    window.graph_action.trigger()  # kind and rug: in place
    source = window.notebook.cell(graph_id).source
    assert "kind='kde'" in source and "rug=True" in source
    [graph] = find_graphs(window.notebook)
    assert (graph.kind, graph.rug) == ("kde", True)
    dialogs.graph_change_answer = (0, "scatter", "o", "Bill", ["Tip"])  # another kind: written afresh
    window.graph_action.trigger()
    source = window.notebook.cell(graph_id).source
    assert "sns.relplot(" in source and "x='Bill', y='Tip'" in source and "rug" not in source
