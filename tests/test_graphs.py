import ast
import itertools

import pytest

from py_spread.graph_dialog import GraphDialog, graph_labels
from py_spread.graphs import GraphCell, change_graph, find_graphs, frame_cell, read_graph
from py_spread.model import SheetModel
from py_spread.notebook import Notebook, graph_code


@pytest.fixture
def sales(app):
    model = SheetModel(rows=10, cols=4)
    model.set_cells({(0, 0): "Month", (0, 1): "Sales", (0, 2): "Cost",
                     (1, 0): "Jan", (1, 1): "1", (1, 2): "2", (2, 0): "Feb", (2, 1): "3", (2, 2): "x"})
    return model


def cells(columns: int):
    return {(row, col) for row in range(3) for col in range(columns)}


SETTINGS = [("line", None), ("line", "o"), ("line", "*"), ("scatter", None), ("scatter", "D")]


def test_reads_generated_graphs(sales):
    graph = read_graph(graph_code(sales, cells(3), "df2", "scatter", "D"))
    assert (graph.kind, graph.marker, graph.frame) == ("scatter", "D", "df2")
    assert (graph.x_label, graph.y_labels, graph.title) == ("Month", ["Sales", "Cost"], "Sales and Cost against Month")
    graph = read_graph(graph_code(sales, cells(2)))
    assert (graph.kind, graph.marker, graph.frame, graph.y_labels) == ("line", None, "df", ["Sales"])


@pytest.mark.parametrize("before, after", list(itertools.permutations(SETTINGS, 2)))
def test_changes_any_setting_to_any_other(sales, before, after):
    original = graph_code(sales, cells(3), "df", *before)
    changed = change_graph(original, *after)
    ast.parse(changed)
    assert (read_graph(changed).kind, read_graph(changed).marker) == after
    assert changed == graph_code(sales, cells(3), "df", *after)  # just as if made that way
    assert change_graph(changed, *before) == original


def test_keeps_other_changes_to_the_code(sales):
    code = graph_code(sales, cells(2)).replace("height=4", "height=6") + "\ngraph.set(title='Mine')"
    changed = change_graph(code, "scatter", "s")
    assert "height=6" in changed and changed.endswith("graph.set(title='Mine')")


def test_hand_written_graphs():
    code = "import seaborn as sns\nsns.relplot(data=d, x='Mês', y='Preço', marker='o')"
    graph = read_graph(code)
    assert (graph.kind, graph.marker, graph.x_label, graph.frame) == ("scatter", "o", "Mês", None)  # relplot's default
    changed = change_graph(code, "line", None)
    assert changed == "import seaborn as sns\nsns.relplot(kind='line', data=d, x='Mês', y='Preço')"
    assert change_graph(changed, "scatter", "+") == (
        "import seaborn as sns\nsns.relplot(kind='scatter', marker='+', data=d, x='Mês', y='Preço')")


def test_marker_alone_on_its_line_goes_with_its_line():
    code = "g = sns.relplot(\n    data=df, x='a', y='b',\n    kind='line',\n    marker='o',\n)\n"
    assert change_graph(code, "line", None) == "g = sns.relplot(\n    data=df, x='a', y='b',\n    kind='line',\n)\n"


@pytest.mark.parametrize("code", [
    "x = 1",
    "sns.relplot(x='a', y='b', kind='line')\nsns.relplot(x='a', y='c', kind='line')",  # two graphs
    "sns.relplot(x='a', y='b', kind='line'",  # not Python
    "sns.relplot(x='a', y='b', kind=k)",  # kind isn't written out
    "sns.relplot(x='a', y='b', kind='hist')",
    "sns.relplot(x='a', y='b', marker=m)",
])
def test_not_graphs_that_can_be_changed(code):
    assert read_graph(code) is None
    with pytest.raises(ValueError):
        change_graph(code, "line", None)


def test_finds_the_notebooks_graphs(sales, app):
    notebook = Notebook()
    first = notebook.add_cell("df = 1")
    graph = notebook.add_cell(graph_code(sales, cells(3)))
    notebook.add_cell("print('hi')")
    other = notebook.add_cell("sns.relplot(data=df, x='a', y='b', kind='line', marker='s')")
    found = find_graphs(notebook)
    assert [g.cell_id for g in found] == [graph.id, other.id]
    assert (found[1].kind, found[1].marker, found[1].frame) == ("line", "s", "df")
    assert frame_cell(notebook, graph.id, "df") == first.id


def test_frame_cell_is_the_nearest_above(app):
    notebook = Notebook()
    notebook.add_cell("df = 1")
    nearest = notebook.add_cell("x = 0\ndf = 2")
    graph = notebook.add_cell("graph")
    notebook.add_cell("df = 3")  # below: not it
    assert frame_cell(notebook, graph.id, "df") == nearest.id
    assert frame_cell(notebook, graph.id, "df7") is None and frame_cell(notebook, graph.id, None) is None


def test_titles_and_labels():
    graphs = [GraphCell("a", "line", None, "df", "Month", ["Sales"]),
              GraphCell("b", "line", None, "df", "Month", ["Sales"]),
              GraphCell("c", "line", None, None, None, []),
              GraphCell("d", "line", None, "df3", None, [])]
    assert graph_labels(graphs) == ["df: Sales against Month (1)", "df: Sales against Month (2)", "A graph",
                                    "df3: a graph of df3"]


# --- The Graph dialog, for changing a graph ---

def two_graphs():
    return [GraphCell("a", "line", None, "df", "Month", ["Sales"]),
            GraphCell("b", "scatter", "D", "df2", "Day", ["Rain", "Sun"])]


def test_dialog_lists_the_graphs(app):
    dialog = GraphDialog(None, graphs=two_graphs(), current=1)
    assert [dialog.graph_box.itemText(i) for i in range(2)] == [
        "df: Sales against Month", "df2: Rain and Sun against Day"]
    assert (dialog.chosen_graph(), dialog.kind(), dialog.marker()) == (1, "scatter", "D")


def test_choosing_a_graph_shows_its_settings(app):
    dialog = GraphDialog(None, graphs=two_graphs(), current=1)
    dialog.graph_box.setCurrentIndex(0)
    assert (dialog.chosen_graph(), dialog.kind(), dialog.marker()) == (0, "line", None)
    assert dialog.marker_box.model().item(0).isEnabled()  # None is fine for a line
    dialog.graph_box.setCurrentIndex(1)
    assert (dialog.kind(), dialog.marker()) == ("scatter", "D")


def test_marker_the_list_lacks(app):
    dialog = GraphDialog(None, graphs=[GraphCell("a", "line", "p", "df", "x", ["y"])])
    assert dialog.marker() == "p"


def test_new_graphs_have_no_graph_list(app):
    assert GraphDialog(None, "x", ["y"]).chosen_graph() is None
