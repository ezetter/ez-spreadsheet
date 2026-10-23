import pytest

from ezsheet.graph_dialog import GraphDialog
from ezsheet.graphs import change_graph, find_graphs, read_graph
from ezsheet.notebook import JOINT_KINDS, FrameData, GraphColumns, GraphError, frame_graph_code
from ezsheet.window import MainWindow
from test_distribution import TIPS, draw, pyplot  # noqa: F401 (pyplot: a fixture)
from test_notebook import FakeKernel


# --- The code ---

def test_a_scatter_by_default():
    code = frame_graph_code(TIPS, "df", "joint-scatter", None, "Bill", ["Size"], import_seaborn=False)
    assert code.splitlines() == [
        "# df as a chart: 'Size' against 'Bill', with each one's distribution.",
        "sns.set_theme(style='whitegrid')",
        "chart = sns.jointplot(",
        "    data=df, x='Bill', y='Size',",
        "    kind='scatter',  # or 'kde', 'hist', 'hex', 'reg', or 'resid'",
        "    height=6,",
        ")"]


def test_its_choices():
    code = frame_graph_code(TIPS, "df", "joint-kde", None, "Bill", ["Tip"], hue="Day")
    assert "x='Bill', y='Tip', hue='Day'" in code and "kind='kde'," in code
    assert "pd.to_numeric(data['Tip']" in code  # (its text)
    assert "marker='D', height=6" in frame_graph_code(TIPS, "df", "joint-reg", "D", "Bill", ["Tip"])
    assert "x='Tip', y='Bill'" in frame_graph_code(TIPS, "df", "joint-hex")  # (the defaults: the first two with numbers)


@pytest.mark.parametrize("kind, others, problem", [
    ("joint-hex", {"hue": "Day"}, "can't color"),
    ("joint-reg", {"hue": "Day"}, "can't color"),
    ("joint-kde", {"marker": "o"}, "has no markers"),
    ("joint-scatter", {"col": "Day"}, "can't be split"),
    ("joint-scatter", {"ys": ["Day"]}, "can't chart"),
    ("joint-scatter", {"ys": []}, "can't chart"),
])
def test_what_wont_do(kind, others, problem):
    with pytest.raises(ValueError, match=problem):
        frame_graph_code(TIPS, "df", kind, others.pop("marker", None), "Bill", others.pop("ys", ["Tip"]), **others)


def test_needs_two_columns_of_numbers():
    with pytest.raises(GraphError, match="needs two columns with numbers"):
        frame_graph_code(FrameData(["Day", "Bill"], [["Thu"], [1.0]]), "df", "joint-scatter")


@pytest.mark.filterwarnings("ignore:Dataset has 0 variance")  # (Sat, in TIPS: one row)
@pytest.mark.parametrize("kind", list(JOINT_KINDS))
def test_drawn(pyplot, kind):  # noqa: F811
    hue = "Day" if kind in ("joint-scatter", "joint-kde", "joint-hist") else None
    chart = draw(frame_graph_code(TIPS, "df", kind, None, "Bill", ["Size"], hue=hue))
    assert type(chart).__name__ == "JointGrid"


# --- Read back, and changed ---

def test_read_and_changed():
    code = frame_graph_code(TIPS, "df", "joint-scatter", "D", "Bill", ["Size"])
    graph = read_graph(code)
    assert (graph.kind, graph.marker, graph.x_label, graph.y_labels) == ("joint-scatter", "D", "Bill", ["Size"])
    hexed = change_graph(code, "joint-hex", None)
    assert hexed == frame_graph_code(TIPS, "df", "joint-hex", None, "Bill", ["Size"])
    assert change_graph(hexed, "joint-scatter", "D") == code
    assert read_graph("g = sns.jointplot(data=df, x='a', y='b')").kind == "joint-scatter"  # (its own)
    assert read_graph("g = sns.jointplot(data=df, x='a', y='b', kind='kde')").kind == "joint-kde"
    with pytest.raises(ValueError, match="can't become"):
        change_graph(code, "scatter", "o")
    with pytest.raises(ValueError, match="can't have a hue"):
        change_graph(frame_graph_code(TIPS, "df", "joint-kde", None, "Bill", ["Size"], hue="Day"), "joint-hex", None)


# --- The dialog ---

def test_dialog(app):
    dialog = GraphDialog(None, GraphColumns.of(TIPS), "scatter", "o")
    dialog.kind_box.setCurrentIndex(dialog.kind_box.findData("joint-scatter"))
    assert dialog.kind_box.currentText() == "Joint" and dialog.kind() == "joint-scatter"
    assert [dialog.joint_box.itemText(i) for i in range(dialog.joint_box.count())] == list(JOINT_KINDS.values())
    assert dialog.form.isRowVisible(dialog.joint_box) and not dialog.form.isRowVisible(dialog.col_box)
    assert [dialog.x_box.itemText(i) for i in range(dialog.x_box.count())] == ["Tip", "Size"]  # (numbers; not y's)
    assert dialog.ys() == ["Bill"] and dialog.marker() == "o"
    dialog.hue_box.setCurrentIndex(dialog.hue_box.findData("Day"))
    choice = dialog.choice()
    assert (choice.kind, choice.x, choice.ys, choice.hue, choice.col, choice.marker) == (
        "joint-scatter", "Tip", ["Bill"], "Day", None, "o")
    dialog.joint_box.setCurrentIndex(dialog.joint_box.findData("joint-hex"))  # no hue, no marker
    assert not dialog.hue_box.isEnabled() and dialog.hue() is None and dialog.marker() is None
    assert not dialog.form.isRowVisible(dialog.marker_box)
    dialog.joint_box.setCurrentIndex(dialog.joint_box.findData("joint-reg"))  # a marker, still no hue
    assert dialog.marker() == "o" and dialog.hue() is None
    dialog.joint_box.setCurrentIndex(dialog.joint_box.findData("joint-kde"))
    assert dialog.hue() == "Day"


def test_needs_two_columns_with_numbers(app):
    dialog = GraphDialog(None, GraphColumns.of(FrameData(["Day", "Bill"], [["Thu", "Fri"], [1.0, 2.0]])))
    item = dialog.kind_box.model().item(dialog.kind_box.findData("joint-scatter"))
    assert not item.isEnabled() and "two columns with numbers" in item.toolTip()


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.kernel = FakeKernel()
    window.model.set_cells({(0, 0): "Bill", (0, 1): "Tip", (1, 0): "10", (1, 1): "1.5", (2, 0): "20",
                            (2, 1): "3", (3, 0): "30", (3, 1): "4"})
    window.show()
    yield window
    if window.notebook_window is not None:
        window.notebook_window.hide()
    window.setWindowModified(False)
    window.close()


def test_make_and_change_one(window, dialogs):
    dialogs.graph_answer = ("joint-scatter", None)
    window.view.select_range(0, 0, 3, 1)
    window.graph_action.trigger()
    graph_id = window.notebook.cells[-1].id
    assert "chart = sns.jointplot(" in window.notebook.cell(graph_id).source
    window.view.setCurrentIndex(window.model.index(0, 0))
    dialogs.graph_change_answer = (0, "joint-kde", None)  # in place
    window.graph_action.trigger()
    assert "kind='kde'," in window.notebook.cell(graph_id).source
    dialogs.graph_change_answer = (0, "scatter", "o")  # another kind: written afresh
    window.graph_action.trigger()
    assert "sns.relplot(" in window.notebook.cell(graph_id).source
    assert [graph.kind for graph in find_graphs(window.notebook)] == ["scatter"]
