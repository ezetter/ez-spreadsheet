import pytest

from ezsheet.graph_dialog import GraphDialog
from ezsheet.graphs import change_graph, find_graphs, read_graph
from ezsheet.notebook import CATEGORICAL_KINDS, FrameData, GraphColumns, frame_graph_code
from ezsheet.window import MainWindow
from test_distribution import TIPS, draw, pyplot  # noqa: F401 (pyplot: a fixture)
from test_notebook import FakeKernel


# --- The code ---

@pytest.mark.parametrize("kind", ["box", "violin", "bar", "point"])
def test_box_violin_bar_and_point(kind):
    code = frame_graph_code(TIPS, "df", kind, None, "Day", ["Bill"], hue="Size", import_seaborn=False)
    assert "chart = sns.catplot(" in code and "data=df, x='Day', y='Bill', hue='Size'," in code
    assert f"    kind={kind!r},  # or " in code and "marker" not in code


@pytest.mark.parametrize("kind", ["box", "violin", "bar"])
def test_they_have_no_markers(kind):
    with pytest.raises(ValueError, match=f"a {kind} chart has no markers"):
        frame_graph_code(TIPS, "df", kind, "o", "Day", ["Bill"])


def test_sideways():
    code = frame_graph_code(TIPS, "df", "box", None, "Bill", ["Day"])
    assert "x='Bill', y='Day', orient='h'" in code


@pytest.mark.filterwarnings("ignore::matplotlib.MatplotlibDeprecationWarning")  # (Seaborn's own boxplot call)
@pytest.mark.parametrize("kind, others", [
    ("box", {}), ("violin", {"hue": "Size"}), ("box", {"col": "Size"}), ("violin", {"ys": ["Day"], "x": "Bill"}),
    ("bar", {"hue": "Size"}), ("point", {"col": "Size"}), ("bar", {"ys": ["Day"], "x": "Bill"}),
])
def test_drawn(pyplot, kind, others):  # noqa: F811
    columns = {"x": "Day", "ys": ["Bill"], **others}
    chart = draw(frame_graph_code(TIPS, "df", kind, None, **columns))
    assert chart.axes.size == (3 if "col" in others else 1)


# --- Read back, and changed ---

def test_read_and_changed():
    strip = frame_graph_code(TIPS, "df", "strip", "D", "Day", ["Bill"])
    box = change_graph(strip, "box", None)  # its marker goes
    assert box == frame_graph_code(TIPS, "df", "box", None, "Day", ["Bill"])
    graph = read_graph(box)
    assert (graph.kind, graph.marker, graph.x_label, graph.y_labels) == ("box", None, "Day", ["Bill"])
    violin = change_graph(box, "violin", None)
    assert violin == frame_graph_code(TIPS, "df", "violin", None, "Day", ["Bill"])
    assert change_graph(violin, "strip", "D") == strip
    scatter = change_graph(box, "scatter", "o")
    assert scatter == frame_graph_code(TIPS, "df", "scatter", "o", "Day", ["Bill"])
    assert read_graph("sns.catplot(data=d, x='a', y='b', kind='violin', marker='o')").marker is None


# --- The dialog ---

def test_dialog(app):
    dialog = GraphDialog(None, GraphColumns.of(TIPS), "strip", "D")
    assert [dialog.categorical_box.itemText(i) for i in range(dialog.categorical_box.count())] == list(
        CATEGORICAL_KINDS.values())
    assert dialog.kind() == "strip" and dialog.marker() == "D" and dialog.form.isRowVisible(dialog.marker_box)
    dialog.categorical_box.setCurrentIndex(dialog.categorical_box.findData("box"))
    assert dialog.kind() == "box" and dialog.marker() is None and not dialog.form.isRowVisible(dialog.marker_box)
    assert dialog.form.isRowVisible(dialog.categories_box)  # (sideways, as a strip can be)
    choice = dialog.choice()
    assert (choice.kind, choice.marker, choice.x, choice.ys) == ("box", None, "Day", ["Tip"])
    dialog.categorical_box.setCurrentIndex(dialog.categorical_box.findData("violin"))
    assert dialog.kind() == "violin"
    dialog.categorical_box.setCurrentIndex(dialog.categorical_box.findData("strip"))
    assert dialog.marker() == "D"  # its own again
    assert GraphDialog(None, GraphColumns.of(TIPS), "violin").categorical_box.currentText() == "Violin"


def test_a_box_plot_needs_no_marker(app):
    dialog = GraphDialog(None, GraphColumns.of(TIPS), "line")
    dialog.kind_box.setCurrentIndex(2)  # Categorical: a strip plot, circles
    assert dialog.marker() == "o"
    dialog.categorical_box.setCurrentIndex(dialog.categorical_box.findData("box"))
    dialog.kind_box.setCurrentIndex(0)  # back to Line: no marker again
    assert dialog.marker() is None


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.kernel = FakeKernel()
    window.model.set_cells({(0, 0): "Day", (0, 1): "Bill", (1, 0): "Thu", (1, 1): "10", (2, 0): "Fri",
                            (2, 1): "20", (3, 0): "Thu", (3, 1): "30"})
    window.show()
    yield window
    if window.notebook_window is not None:
        window.notebook_window.hide()
    window.setWindowModified(False)
    window.close()


def test_make_and_change_one(window, dialogs):
    dialogs.graph_answer = ("box", None)
    window.view.select_range(0, 0, 3, 1)
    window.graph_action.trigger()
    graph_id = window.notebook.cells[-1].id
    assert "kind='box'" in window.notebook.cell(graph_id).source
    dialogs.graph_change_answer = (0, "violin", None)
    window.view.setCurrentIndex(window.model.index(0, 0))
    window.graph_action.trigger()
    assert "kind='violin',  # or 'strip', 'swarm', 'box', 'bar', or 'point'" in window.notebook.cell(graph_id).source
    assert [graph.kind for graph in find_graphs(window.notebook)] == ["violin"]


def test_a_point_plot_can_have_a_marker(pyplot):  # noqa: F811
    code = frame_graph_code(TIPS, "df", "point", "D", "Day", ["Bill"])
    assert "kind='point'," in code and "marker='D'" in code
    chart = draw(code)
    assert "D" in [line.get_marker() for line in chart.ax.get_lines()]
    assert read_graph(code).marker == "D"
    bar = change_graph(code, "bar", None)  # a bar plot has none
    assert bar == frame_graph_code(TIPS, "df", "bar", None, "Day", ["Bill"])
    assert change_graph(bar, "point", None) == frame_graph_code(TIPS, "df", "point", None, "Day", ["Bill"])


def test_dialog_bar_and_point(app):
    dialog = GraphDialog(None, GraphColumns.of(TIPS), "strip", "o")
    assert [dialog.categorical_box.itemText(i) for i in range(6)] == [
        "Strip", "Swarm", "Box", "Violin", "Bar", "Point"]
    dialog.categorical_box.setCurrentIndex(dialog.categorical_box.findData("bar"))
    assert dialog.kind() == "bar" and dialog.marker() is None and not dialog.form.isRowVisible(dialog.marker_box)
    dialog.categorical_box.setCurrentIndex(dialog.categorical_box.findData("point"))
    assert dialog.kind() == "point" and dialog.marker() == "o" and dialog.form.isRowVisible(dialog.marker_box)
    none_item = dialog.marker_box.model().item(0)
    assert none_item.isEnabled()  # (a point plot draws its own points without one)
