import ast
import itertools

import pytest

from py_spread.graph_dialog import GraphDialog, graph_labels
from py_spread.graphs import GraphCell, change_graph, find_graphs, frame_cell, frame_data, read_graph
from py_spread.model import SheetModel
from py_spread.notebook import FrameData, GraphChoice, GraphColumns, Notebook, dataframe_code, graph_code


@pytest.fixture
def sales(app):
    model = SheetModel(rows=10, cols=4)
    model.set_cells({(0, 0): "Month", (0, 1): "Sales", (0, 2): "Cost",
                     (1, 0): "Jan", (1, 1): "1", (1, 2): "2", (2, 0): "Feb", (2, 1): "3", (2, 2): "x"})
    return model


def cells(columns: int):
    return {(row, col) for row in range(3) for col in range(columns)}


SETTINGS = [("line", None), ("line", "o"), ("line", "*"), ("scatter", None), ("scatter", "D"),
            ("strip", None), ("strip", "s"), ("swarm", "D")]


def test_reads_generated_graphs(sales):
    graph = read_graph(graph_code(sales, cells(3), "df2", "scatter", "D"))
    assert (graph.kind, graph.marker, graph.frame) == ("scatter", "D", "df2")
    assert (graph.x_label, graph.y_labels, graph.hue, graph.title) == ("Month", ["Sales"], None, "Sales against Month")
    graph = read_graph(graph_code(sales, cells(3), "df2", "line", None, x="Sales", ys=["Cost"], hue="Month"))
    assert (graph.x_label, graph.y_labels, graph.hue) == ("Sales", ["Cost"], "Month")
    graph = read_graph(graph_code(sales, cells(3), "df2", "line", None, ys=["Sales", "Cost"]))  # older: series
    assert (graph.y_labels, graph.hue, graph.title) == (["Sales", "Cost"], None, "Sales and Cost against Month")
    graph = read_graph(graph_code(sales, cells(2)))
    assert (graph.kind, graph.marker, graph.frame, graph.y_labels) == ("line", None, "df", ["Sales"])


@pytest.mark.parametrize("before, after", list(itertools.permutations(SETTINGS, 2)))
def test_changes_any_setting_to_any_other(sales, before, after):
    original = graph_code(sales, cells(3), "df", *before, ys=["Sales"])
    changed = change_graph(original, *after)
    ast.parse(changed)
    assert (read_graph(changed).kind, read_graph(changed).marker) == after
    assert changed == graph_code(sales, cells(3), "df", *after, ys=["Sales"])  # just as if made that way
    assert change_graph(changed, *before) == original


@pytest.fixture
def measures(app):
    model = SheetModel(rows=10, cols=4)
    model.set_cells({(0, 0): "Species", (0, 1): "Width", (0, 2): "Length", (1, 0): "a", (1, 1): "1",
                     (1, 2): "2", (2, 0): "b", (2, 1): "3", (2, 2): "5"})
    return model


WITH_REGRESSION = [("line", None), ("scatter", "D"), ("strip", "s"), ("swarm", "D"), ("reg", "o"), ("reg", None),
                   ("reg", "*")]


@pytest.mark.parametrize("col", [None, "Species"])
@pytest.mark.parametrize("before, after", list(itertools.permutations(WITH_REGRESSION, 2)))
def test_changes_to_and_from_linear_regressions(measures, before, after, col):
    original = graph_code(measures, cells(3), "df", *before, x="Width", ys=["Length"], col=col)
    changed = change_graph(original, *after)
    assert (read_graph(changed).kind, read_graph(changed).marker) == after
    assert changed == graph_code(measures, cells(3), "df", *after, x="Width", ys=["Length"], col=col)
    assert change_graph(changed, *before) == original


def test_hand_written_linear_regressions():
    graph = read_graph("sns.lmplot(data=d, x='a', y='b')")
    assert (graph.kind, graph.marker, graph.x_label, graph.y_labels) == ("reg", None, "a", ["b"])
    assert read_graph("sns.lmplot(data=d, x='a', y='b', markers='x')").marker == "x"
    assert read_graph("sns.lmplot(data=d, x='a', y='b', hue='c', markers=['o', 'x'])") is None  # one per hue
    assert change_graph("sns.lmplot(data=d, x='a', y='b')", "scatter", "o") == (
        "sns.relplot(kind='scatter', marker='o', data=d, x='a', y='b')")
    assert change_graph("sns.relplot(data=d, x='a', y='b', kind='line')", "reg", "s") == (
        "sns.lmplot(markers='s', data=d, x='a', y='b')")


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
    assert graph_labels(graphs) == ["df: Sales against Month (1)", "df: Sales against Month (2)", "A chart",
                                    "df3: a chart of df3"]


# --- The Graph dialog, for changing a graph ---

def two_graphs():
    return [GraphCell("a", "line", None, "df", "Month", ["Sales"]),
            GraphCell("b", "scatter", "D", "df2", "Day", ["Rain", "Sun"])]


def test_dialog_lists_the_graphs(app):
    dialog = GraphDialog(None, graphs=two_graphs(), current=1)
    assert [dialog.graph_box.itemText(i) for i in range(3)] == [
        "New chart", "df: Sales against Month", "df2: Rain and Sun against Day"]
    assert (dialog.chosen_graph(), dialog.kind(), dialog.marker()) == (1, "scatter", "D")


def test_choosing_a_graph_shows_its_settings(app):
    dialog = GraphDialog(None, graphs=two_graphs(), current=1)
    dialog.graph_box.setCurrentIndex(1)  # after New chart
    assert (dialog.chosen_graph(), dialog.kind(), dialog.marker()) == (0, "line", None)
    assert dialog.marker_box.model().item(0).isEnabled()  # None is fine for a line
    dialog.graph_box.setCurrentIndex(2)
    assert (dialog.kind(), dialog.marker()) == ("scatter", "D")


def test_marker_the_list_lacks(app):
    dialog = GraphDialog(None, graphs=[GraphCell("a", "line", "p", "df", "x", ["y"])], current=0)
    assert dialog.marker() == "p"


def test_new_graphs_have_no_graph_list(app):
    columns = GraphColumns(["x", "y"], [True, True], [False, False])
    assert GraphDialog(None, columns).chosen_graph() is None


# --- Categorical scatter, and the data behind a graph ---

def test_reads_categorical_scatters(sales):
    code = graph_code(sales, cells(3), "df", "strip", "D", x="Month", ys=["Sales"])
    assert "chart = sns.catplot(" in code and "    kind='strip',  # or 'swarm'\n" in code
    graph = read_graph(code)
    assert (graph.kind, graph.marker, graph.x_label, graph.y_labels) == ("strip", "D", "Month", ["Sales"])
    assert read_graph("sns.catplot(data=d, x='a', y='b')").kind == "strip"  # catplot's default
    assert read_graph(change_graph(code, "swarm", None)).kind == "swarm"
    assert read_graph("sns.catplot(data=d, x='a', y='b', kind='box')") is None  # not one the dialog has


def test_switches_between_relplot_and_catplot(sales):
    line = graph_code(sales, cells(3), "df", "line", None, ys=["Sales"])
    strip = change_graph(line, "strip", "o")
    assert strip == graph_code(sales, cells(3), "df", "strip", "o", ys=["Sales"])
    assert change_graph(strip, "line", None) == line
    older = strip.replace("  # or 'swarm'", "")  # a categorical scatter made before swarm plots
    assert change_graph(older, "scatter", "o") == graph_code(sales, cells(3), "df", "scatter", "o", ys=["Sales"])


def test_frame_data_from_a_dataframe_cell(sales):
    code = dataframe_code(sales, cells(3), "df2")
    data = frame_data(code, "df2")
    assert data.labels == ["Month", "Sales", "Cost"] and data.columns[2] == [2, "x"]
    assert frame_data(code, "df") is None
    assert frame_data("df = pd.DataFrame(rows)", "df") is None  # not written out
    assert frame_data("df = pd.DataFrame({'a': [1], 'b': [1, 2]})", "df") is None  # uneven


def test_found_graphs_know_their_data(sales, app):
    notebook = Notebook()
    notebook.add_cell(dataframe_code(sales, cells(3)))
    notebook.add_cell(graph_code(sales, cells(3)))
    notebook.add_cell("sns.relplot(data=other, x='a', y='b', kind='line')")  # its DataFrame's not here
    made, lost = find_graphs(notebook)
    assert made.data.labels == ["Month", "Sales", "Cost"] and made.columns.numbers == [False, True, True]
    assert lost.data is None and lost.columns is None


def test_changing_dialog_shows_the_graphs_columns(app):
    columns = GraphColumns(["Month", "Sales", "Cost"], [False, True, True], [True, False, False])
    graph = GraphCell("a", "strip", "D", "df", "Month", ["Cost"], FrameData(["Month", "Sales", "Cost"], []), columns)
    dialog = GraphDialog(None, graphs=[graph], current=0)
    assert (dialog.kind(), dialog.x(), dialog.ys(), dialog.marker()) == ("strip", "Month", ["Cost"], "D")
    assert dialog.x_box.isEnabled() and dialog.y_box.count() == 2 and dialog.hue() is None
    dialog.kind_box.setCurrentIndex(0)
    assert dialog.x() == "Month" and dialog.ys() == ["Cost"]  # a graph's own columns stay put


def test_changing_dialog_without_the_data(app):
    dialog = GraphDialog(None, graphs=[GraphCell("a", "line", None, "df", "Month", ["Sales", "Cost"])], current=0)
    assert not dialog.x_box.isEnabled() and not dialog.y_box.isEnabled()
    assert dialog.choice().x == "Month" and dialog.ys() == ["Sales", "Cost"]


def test_hue_in_the_changing_dialog(app):
    columns = GraphColumns(["Month", "Sales", "Region"], [False, True, False], [True, False, True])
    graph = GraphCell("a", "scatter", "o", "df", "Month", ["Sales"], FrameData(["Month", "Sales", "Region"], []),
                      columns, hue="Region")
    assert GraphDialog(None, graphs=[graph], current=0).choice().hue == "Region"


def test_line_chart_of_every_column_in_the_changing_dialog(app):
    columns = GraphColumns(["Month", "Sales", "Cost"], [False, True, True], [True, False, False])
    graph = GraphCell("a", "line", None, "df", "Month", ["Sales", "Cost"], FrameData(["Month", "Sales", "Cost"], []),
                      columns)
    dialog = GraphDialog(None, graphs=[graph], current=0)
    assert dialog.ys() == ["Sales", "Cost"] and dialog.y_box.currentText() == "All"
    assert not dialog.hue_box.isEnabled() and dialog.hue() is None  # colored a line each
    dialog.y_box.setCurrentIndex(1)
    assert dialog.ys() == ["Sales"] and dialog.hue_box.isEnabled()


def test_older_scatter_of_several_series_in_the_changing_dialog(app):
    columns = GraphColumns(["Month", "Sales", "Cost"], [False, True, True], [True, False, False])
    graph = GraphCell("a", "scatter", "o", "df", "Month", ["Sales", "Cost"],
                      FrameData(["Month", "Sales", "Cost"], []), columns)
    dialog = GraphDialog(None, graphs=[graph], current=0)
    assert dialog.y_box.currentText() == "Sales, Cost" and dialog.ys() == ["Sales", "Cost"]  # kept as it is
    assert [dialog.y_box.itemText(i) for i in range(dialog.y_box.count())] == ["Sales", "Cost", "Sales, Cost"]


def test_reads_col(sales):
    graph = read_graph(graph_code(sales, cells(3), "df", "line", None, x="Sales", ys=["Cost"], col="Month"))
    assert (graph.x_label, graph.y_labels, graph.col) == ("Sales", ["Cost"], "Month")
    assert read_graph(graph_code(sales, cells(3))).col is None
    every = read_graph("long = df.melt(id_vars=['Day', 'Site'], value_vars=['Rain', 'Sun'], var_name='Series', "
                       "value_name='Value')\nchart = sns.relplot(data=long, x='Day', y='Value', hue='Series', "
                       "col='Site', kind='line')")
    assert (every.y_labels, every.hue, every.col) == (["Rain", "Sun"], None, "Site")


def test_changing_a_chart_with_col_keeps_it(sales):
    code = graph_code(sales, cells(3), "df", "line", None, x="Sales", ys=["Cost"], col="Month")
    changed = change_graph(code, "scatter", "D")
    assert "col='Month', col_wrap=2," in changed and "marker='D', height=2.5, aspect=1.2," in changed
    assert read_graph(changed).col == "Month" and change_graph(changed, "line", None) == code


def test_col_in_the_changing_dialog(app):
    labels = ["Month", "Sales", "Region"]
    columns = GraphColumns(labels, [False, True, False], [True, False, True])
    graph = GraphCell("a", "line", None, "df", "Month", ["Sales"], FrameData(labels, []), columns, col="Region")
    dialog = GraphDialog(None, graphs=[graph], current=0)
    assert dialog.col() == "Region" and dialog.col_box.isEnabled()
    graph.data = graph.columns = None  # its DataFrame's cell wasn't found: shown, but greyed out
    dialog = GraphDialog(None, graphs=[graph], current=0)
    assert dialog.col() == "Region" and not dialog.col_box.isEnabled()


def test_col_of_years_in_the_changing_dialog(app):
    labels = ["Year", "Month", "Sales", "Cost"]
    columns = GraphColumns(labels, [True, False, True, True], [False, True, False, False])
    every = GraphCell("a", "line", None, "df", "Month", ["Sales", "Cost"], FrameData(labels, []), columns, col="Year")
    sales = GraphCell("b", "line", None, "df", "Month", ["Sales"], FrameData(labels, []), columns, col="Year")
    dialog = GraphDialog(None, graphs=[every, sales], current=1)
    assert (dialog.ys(), dialog.col()) == (["Sales"], "Year")
    dialog.graph_box.setCurrentIndex(1)  # All, but the years
    assert (dialog.y_box.currentText(), dialog.ys(), dialog.col()) == ("All", ["Sales", "Cost"], "Year")


def test_linear_regression_in_the_changing_dialog(app):
    labels = ["Width", "Length", "Species"]
    columns = GraphColumns(labels, [True, True, False], [False, False, True])
    graph = GraphCell("a", "reg", "s", "df", "Width", ["Length"], FrameData(labels, []), columns)
    dialog = GraphDialog(None, graphs=[graph], current=0)
    assert dialog.kind_box.currentText() == "Scatter" and dialog.regression_box.isChecked()
    assert dialog.choice() == GraphChoice("reg", "s", "Width", ["Length"], None, False, None)


def test_reads_numbers_up_as_categories():
    code = "chart = sns.catplot(data=df, x='Sales', y='Year', orient='h', kind='swarm')"
    graph = read_graph(code)
    assert graph.y_categories and graph.kind == "swarm"
    assert not read_graph(code.replace(", orient='h'", "")).y_categories
    assert change_graph(code, "strip", "o").count("orient='h'") == 1  # strip or swarm, still sideways


def test_charts_made_before_they_were_called_charts(sales):
    code = graph_code(sales, cells(3), "df2", "line", None)
    assert "# df2 as a chart:" in code and "\nchart = sns.relplot(" in code
    older = code.replace("as a chart", "as a graph").replace("chart = sns.", "graph = sns.")
    assert read_graph(older).frame == "df2"
    assert "graph = sns.relplot(" in change_graph(older, "scatter", "o")  # its own name stays


def test_new_chart_in_the_list(app):
    columns = GraphColumns(["Month", "Sales"], [False, True], [True, False])
    dialog = GraphDialog(None, columns, "scatter", "D", graphs=two_graphs(), current=None,
                         new_source="the whole sheet, A1:B4")
    assert dialog.graph_box.currentText() == "New chart" and dialog.chosen_graph() is None
    assert dialog.summary.text() == "A new chart of the whole sheet, A1:B4."
    assert (dialog.kind(), dialog.x(), dialog.ys(), dialog.marker()) == ("scatter", "Month", ["Sales"], "D")
    dialog.graph_box.setCurrentIndex(2)  # df2's chart
    assert (dialog.chosen_graph(), dialog.x()) == (1, "Day") and "Change this chart" in dialog.summary.text()
    dialog.graph_box.setCurrentIndex(0)  # and back: the new chart's own starting choices
    assert (dialog.kind(), dialog.x(), dialog.marker()) == ("scatter", "Month", "D")


def test_new_chart_that_cant_be_made(app):
    dialog = GraphDialog(None, None, graphs=two_graphs(), current=None, new_source="the sheet",
                         new_problem="The sheet is empty.")
    assert dialog.summary.text() == "A new chart of the sheet can't be made. The sheet is empty."
    assert not dialog.ok_button.isEnabled() and not dialog.kind_box.isEnabled()
    dialog.kind_box.setCurrentIndex(1)
    assert not dialog.regression_box.isEnabled()
    dialog.graph_box.setCurrentIndex(1)  # an existing chart can still be changed
    assert dialog.ok_button.isEnabled() and dialog.kind_box.isEnabled()


def test_no_list_without_charts(app):
    columns = GraphColumns(["Month", "Sales"], [False, True], [True, False])
    dialog = GraphDialog(None, columns, new_source="the selected cells, A1:B4")
    assert dialog.graph_box is None and dialog.chosen_graph() is None
    assert dialog.summary.text() == "A new chart of the selected cells, A1:B4."
