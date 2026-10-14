import base64
import json
import math
import time

import pandas as pd
import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Qt, Signal
from PySide6.QtGui import QImage, QTextDocument, QTextTable
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QToolBar, QToolButton, QWidget

from py_spread.model import SheetModel
from py_spread.notebook import (
    Notebook,
    NotebookFormatError,
    IMPORTS_CELL,
    GraphChoice,
    GraphColumns,
    GraphError,
    cells_from_json,
    data_block,
    dataframe_code,
    graph_code,
    graph_columns,
    importing_cell,
    next_frame_name,
)
from py_spread.graph_dialog import MARKERS, GraphDialog
from py_spread.notebook_window import NotebookWindow, OutputView
from py_spread.storage import SheetData, SheetFileError, load_sheet, save_sheet
from py_spread.window import MainWindow


def block(top, left, bottom, right):
    return {(r, c) for r in range(top, bottom + 1) for c in range(left, right + 1)}


def frame(code: str, name: str = "df") -> pd.DataFrame:
    namespace = {"pd": pd}  # as the imports cell gives it
    exec(code, namespace)  # the generated cell, run as the kernel would
    return namespace[name]


@pytest.fixture
def sheet(app):
    model = SheetModel(rows=30, cols=8)
    model.set_cells({
        (0, 0): "Month", (0, 1): "Sales", (0, 2): "Note",
        (1, 0): "Jan", (1, 1): "$1,200", (1, 2): 'say "hi"',
        (2, 0): "Feb", (2, 1): "1450.5",
        (3, 0): "Mar", (3, 1): "=1/0", (3, 2): "x",
    })
    return model


# --- The generated DataFrame code ---

def test_header_row_names_columns(sheet):
    code = dataframe_code(sheet, block(0, 0, 3, 2))
    assert code.startswith("import pandas as pd\n\n# Cells A1:C4 of the sheet, with row 1 as the column names.")
    assert code.endswith("\ndf")
    df = frame(code)
    assert list(df.columns) == ["Month", "Sales", "Note"]
    assert list(df["Month"]) == ["Jan", "Feb", "Mar"]
    assert df["Sales"].tolist()[:2] == [1200, 1450.5]  # $1,200 is a number
    assert math.isnan(df["Sales"][2])  # the error cell is missing
    assert df["Note"][0] == 'say "hi"' and pd.isna(df["Note"][1])


def test_no_header_uses_letters(app):
    model = SheetModel(rows=10, cols=6)
    model.set_cells({(0, 1): "1", (1, 1): "2", (0, 2): "3", (1, 2): "4"})
    df = frame(dataframe_code(model, block(0, 1, 1, 2)))
    assert list(df.columns) == ["B", "C"]
    assert df["B"].dtype == "int64" and df["C"].tolist() == [3, 4]


def test_column_names_label_columns(app):
    model = SheetModel(rows=10, cols=6)
    model.set_cells({(0, 2): "1.5", (1, 2): "2"})
    model.name_column(2, "t")
    df = frame(dataframe_code(model, block(0, 2, 1, 2)))
    assert list(df.columns) == ["t"] and df["t"].tolist() == [1.5, 2.0]


def test_duplicate_and_blank_headers(app):
    model = SheetModel(rows=10, cols=6)
    model.set_cells({(0, 0): "x", (0, 1): "x", (1, 0): "1", (1, 1): "2", (1, 2): "3"})
    df = frame(dataframe_code(model, block(0, 0, 1, 2)))
    assert list(df.columns) == ["x", "x (B)", "C"]


def test_single_row_is_data_not_header(app):
    model = SheetModel(rows=10, cols=6)
    model.set_cells({(0, 0): "a", (0, 1): "b"})
    df = frame(dataframe_code(model, block(0, 0, 0, 1)))
    assert list(df.columns) == ["A", "B"] and df.iloc[0].tolist() == ["a", "b"]


def test_scattered_selection(sheet):
    cells = block(0, 0, 3, 0) | block(0, 2, 3, 2)  # columns A and C
    df = frame(dataframe_code(sheet, cells))
    assert list(df.columns) == ["Month", "Note"]


def test_data_block_trims_empty_edges(sheet):
    whole_columns = block(0, 0, 29, 3)  # A:D clicked in the column headers
    assert data_block(sheet, whole_columns) == block(0, 0, 3, 2)
    assert data_block(sheet, block(5, 0, 9, 3)) == set()
    scattered = block(0, 0, 29, 0) | block(0, 2, 29, 2)
    assert data_block(sheet, scattered) == block(0, 0, 3, 0) | block(0, 2, 3, 2)


# --- The generated graph code ---

@pytest.fixture
def pyplot():
    import matplotlib.pyplot as plt

    backend = plt.get_backend()
    plt.switch_backend("agg")
    yield plt
    plt.close("all")
    plt.switch_backend(backend)


def graph(model, cells, kind="line", marker=None, **columns):
    """Run the DataFrame and graph cells for these cells; the graph (a Seaborn FacetGrid)."""
    namespace = {}
    exec(dataframe_code(model, cells), namespace)
    exec(graph_code(model, cells, "df", kind, marker, **columns), namespace)
    return namespace["graph"]


@pytest.fixture
def sales(app):
    model = SheetModel(rows=80, cols=8)
    model.set_cells({(0, 0): "Month", (0, 1): "Sales", (0, 2): "Cost",
                     (1, 0): "Mar", (1, 1): "1200", (1, 2): "800",
                     (2, 0): "Jan", (2, 1): "1450.5", (2, 2): "n/a",
                     (3, 0): "Feb", (3, 1): "1700", (3, 2): "950"})
    return model


def plotted(g) -> list:
    """The graph's lines. (Seaborn also puts empty ones on the axes for its legend.)"""
    return [line for line in g.ax.get_lines() if len(line.get_xdata())]


def test_graph_of_one_column_by_default(sales, pyplot):
    code = graph_code(sales, block(0, 0, 3, 2))
    assert "x='Month', y='Sales'" in code and "melt" not in code and "hue" not in code
    g = graph(sales, block(0, 0, 3, 2))
    assert [t.get_text() for t in g.ax.get_xticklabels()] == ["Mar", "Jan", "Feb"]  # the sheet's order
    assert g.ax.get_ylabel() == "Sales" and g.legend is None


def test_graph_of_several_series(sales, pyplot):
    """As graphs made before the y was a single column could have."""
    g = graph(sales, block(0, 0, 3, 2), ys=["Sales", "Cost"])
    assert [t.get_text() for t in g.legend.texts] == ["Sales", "Cost"]
    sales_line, cost_line = plotted(g)
    assert list(sales_line.get_ydata()) == [1200, 1450.5, 1700]
    assert list(cost_line.get_ydata()) == [800, 950]  # n/a isn't graphed
    assert sales_line.get_marker() == "None"  # no markers unless asked for
    assert g.ax.get_xlabel() == "Month"


@pytest.mark.parametrize("marker", [m for m in MARKERS if m])
def test_line_markers(sales, pyplot, marker):
    code = graph_code(sales, block(0, 0, 3, 2), "df", "line", marker)
    assert f"marker={marker!r}, height=4" in code
    assert {line.get_marker() for line in plotted(graph(sales, block(0, 0, 3, 2), "line", marker))} == {marker}


def test_graph_of_one_series(sales, pyplot):
    code = graph_code(sales, block(0, 0, 3, 1))
    assert "melt" not in code and "pd." not in code  # nothing to reshape or fix
    g = graph(sales, block(0, 0, 3, 1))
    assert g.ax.get_ylabel() == "Sales" and g.legend is None  # named on the y axis, as in a chart


def test_scatter(sales, pyplot):
    code = graph_code(sales, block(0, 0, 3, 2), "df", "scatter")
    assert "kind='scatter',  # or 'line'" in code and "marker" not in code  # Seaborn's own circles
    g = graph(sales, block(0, 0, 3, 2), "scatter")
    assert plotted(g) == [] and len(g.ax.collections[0].get_offsets()) == 3
    g = graph(sales, block(0, 0, 3, 2), "scatter", "*", ys=["Cost"])
    assert len(g.ax.collections[0].get_offsets()) == 2  # n/a isn't graphed


def test_line_or_scatter_only(sales):
    with pytest.raises(ValueError):
        graph_code(sales, block(0, 0, 3, 2), "df", "bar")


def test_numeric_x(pyplot, app):
    model = SheetModel(rows=80, cols=4)
    model.set_cells({(row, 0): str(row) for row in range(60)} | {(row, 1): str(row * row) for row in range(60)})
    model.set_cell(7, 0, "")  # a point without an x is left out
    [line] = plotted(graph(model, block(0, 0, 59, 1)))
    assert len(line.get_xdata()) == 59 and line.get_xdata()[0] == 0


def test_x_of_numbers_and_text(pyplot, app):
    model = SheetModel(rows=10, cols=4)
    model.set_cells({(0, 0): "1", (1, 0): "two", (2, 0): "3", (0, 1): "5", (1, 1): "6", (2, 1): "7"})
    assert "astype('string')" in graph_code(model, block(0, 0, 2, 1))
    g = graph(model, block(0, 0, 2, 1))
    assert [t.get_text() for t in g.ax.get_xticklabels()] == ["1", "two", "3"]


def test_graph_names_dont_clash(pyplot, app):
    model = SheetModel(rows=10, cols=4)
    model.set_cells({(0, 0): "t", (0, 1): "Value", (0, 2): "Series",
                     (1, 0): "1", (1, 1): "2", (1, 2): "3", (2, 0): "2", (2, 1): "4", (2, 2): "5"})
    code = graph_code(model, block(0, 0, 2, 2), ys=["Value", "Series"])
    assert "var_name='Series 2', value_name='Value 2'" in code
    g = graph(model, block(0, 0, 2, 2), ys=["Value", "Series"])
    assert [t.get_text() for t in g.legend.texts] == ["Value", "Series"]


@pytest.mark.parametrize("cells, problem", [
    (block(0, 0, 3, 0), "at least two columns"),
    (block(0, 0, 3, 0) | block(0, 3, 3, 3), "no numbers"),  # D is empty
])
def test_cells_that_cant_be_graphed(sales, cells, problem):
    with pytest.raises(GraphError, match=problem):
        graph_code(sales, cells)
    with pytest.raises(GraphError, match=problem):
        graph_columns(sales, cells)


def test_categorical_scatter(pyplot, app):
    model = SheetModel(rows=10, cols=4)
    model.set_cells({(0, 0): "Width", (0, 1): "Species", (0, 2): "Length",
                     (1, 0): "1", (1, 1): "b", (1, 2): "4", (2, 0): "2", (2, 1): "a", (2, 2): "5",
                     (3, 0): "3", (3, 1): "b", (3, 2): "6"})
    columns = graph_columns(model, block(0, 0, 3, 2))
    assert columns.default_x("strip") == "Species" and columns.default_x("line") == "Width"
    code = graph_code(model, block(0, 0, 3, 2), "df", "strip", "D", x="Species")
    assert "sns.catplot(" in code and "x='Species', y='Length'," in code and "kind='strip',  # or 'swarm'" in code
    assert "# df as a graph: 'Length' against 'Species'." in code  # the next column with numbers after x
    g = graph(model, block(0, 0, 3, 2), "strip", "D", x="Species")
    assert [t.get_text() for t in g.ax.get_xticklabels()] == ["b", "a"]  # categories in the sheet's order
    g = graph(model, block(0, 0, 3, 2), "swarm", None, x="Species", ys=["Length"], hue="Width")
    assert g.ax.get_ylabel() == "Length" and g.legend is not None


def test_column_rules():
    columns = GraphColumns(["Species", "Width", "Length", "Site"], [False, True, True, False],
                           [True, False, False, True])
    assert columns.y_options("Width", "line") == ["Length"]
    assert columns.y_options("Width", "swarm") == ["Species", "Length", "Site"]
    assert columns.y_options("Species", "strip") == ["Width", "Length"]
    assert columns.x_options("Species", "strip") == ["Width", "Length"]
    assert columns.x_options("Species", "line") == columns.x_options("Width", "strip") == columns.labels
    assert columns.sideways(["Species"], "strip") and not columns.sideways(["Width"], "strip")


def test_sideways_categorical_scatter(pyplot, app):
    model = SheetModel(rows=10, cols=4)
    model.set_cells({(0, 0): "Species", (0, 1): "Width", (1, 0): "b", (1, 1): "1", (2, 0): "a", (2, 1): "n/a",
                     (3, 0): "b", (3, 1): "3"})
    cells = block(0, 0, 3, 1)
    code = graph_code(model, cells, "df", "swarm", "D", x="Width", ys=["Species"])
    assert "x='Width', y='Species'" in code and "pd.to_numeric(data['Width']" in code  # n/a across
    g = graph(model, cells, "swarm", "D", x="Width", ys=["Species"])
    assert [t.get_text() for t in g.ax.get_yticklabels()] == ["b", "a"] and g.ax.get_xlabel() == "Width"
    for kind, x in (("line", "Width"), ("strip", "Species")):  # line graphs, or categories both ways
        with pytest.raises(ValueError):
            graph_code(model, cells, "df", kind, None, x=x, ys=["Species"])


def test_hue(sales, pyplot):
    code = graph_code(sales, block(0, 0, 3, 2), "df", "scatter", "o", x="Sales", ys=["Cost"], hue="Month")
    assert "data=data, x='Sales', y='Cost', hue='Month'" in code
    assert "# df as a graph: 'Cost' against 'Sales', colored by 'Month'." in code
    g = graph(sales, block(0, 0, 3, 2), "scatter", "o", x="Sales", ys=["Cost"], hue="Month")
    assert [t.get_text() for t in g.legend.texts] == ["Mar", "Jan", "Feb"]
    for bad in ("Sales", "Nope"):  # x itself, or no such column
        with pytest.raises(ValueError):
            graph_code(sales, block(0, 0, 3, 2), "df", "line", None, x="Sales", ys=["Cost"], hue=bad)
    with pytest.raises(ValueError):  # several series are colored by series already
        graph_code(sales, block(0, 0, 3, 2), "df", "line", None, ys=["Sales", "Cost"], hue="Month")


def test_chosen_axes(sales, pyplot):
    code = graph_code(sales, block(0, 0, 3, 2), "df", "line", None, x="Sales", ys=["Cost"])
    assert "x='Sales', y='Cost'" in code and "pd.to_numeric(data['Cost']" in code  # Cost has n/a
    g = graph(sales, block(0, 0, 3, 2), "scatter", None)
    assert g.ax.get_xlabel() == "Month"
    with pytest.raises(ValueError):
        graph_code(sales, block(0, 0, 3, 2), "df", "line", None, x="Sales", ys=["Sales"])  # x up too
    with pytest.raises(ValueError):
        graph_code(sales, block(0, 0, 3, 2), "df", "line", None, x="Month", ys=["Nope"])


def test_x_with_the_only_numbers_goes_up_instead(app):
    model = SheetModel(rows=10, cols=4)
    model.set_cells({(0, 0): "n", (0, 1): "t", (1, 0): "1", (1, 1): "a", (2, 0): "2", (2, 1): "b"})
    columns = graph_columns(model, block(0, 0, 2, 1))
    assert columns.default_x("line") == "t" and columns.default_ys("t") == ["n"]


def test_graph_columns(sales):
    assert graph_columns(sales, block(0, 0, 3, 2)) == GraphColumns(
        ["Month", "Sales", "Cost"], [False, True, True], [True, False, True])  # Cost has n/a


# --- The Graph dialog ---

def sales_columns():
    return GraphColumns(["Month", "Sales", "Cost", "Note"], [False, True, True, False], [True, False, False, True])


def dialog_state(dialog):
    return dialog.kind(), dialog.x(), dialog.ys(), dialog.hue(), dialog.marker()


def test_dialog_starts_with_defaults(app):
    dialog = GraphDialog(None, sales_columns())
    assert dialog_state(dialog) == ("line", "Month", ["Sales"], None, None)
    assert [dialog.kind_box.itemText(i) for i in range(3)] == ["Line", "Scatter", "Categorical scatter"]
    assert [dialog.marker_box.itemData(i) for i in range(dialog.marker_box.count())] == list(MARKERS)
    assert [dialog.x_box.itemText(i) for i in range(4)] == ["Month", "Sales", "Cost", "Note"]
    assert [dialog.y_box.itemText(i) for i in range(dialog.y_box.count())] == ["Sales", "Cost"]  # one each
    assert [dialog.hue_box.itemText(i) for i in range(dialog.hue_box.count())] == [
        "None", "Sales", "Cost", "Note"]  # any column but x
    assert not dialog.form.isRowVisible(dialog.swarm_box)  # just for categorical scatters


def test_dialog_starts_with_the_last_choices(app):
    dialog = GraphDialog(None, sales_columns(), "scatter", "D")
    assert dialog_state(dialog) == ("scatter", "Month", ["Sales"], None, "D")
    assert dialog.choice() == GraphChoice("scatter", "D", "Month", ["Sales"], None)


def test_choosing_the_axes_and_hue(app):
    dialog = GraphDialog(None, sales_columns())
    dialog.y_box.setCurrentIndex(1)
    dialog.y_box.activated.emit(1)  # as the user's choice is
    dialog.hue_box.setCurrentIndex(dialog.hue_box.findData("Sales"))
    assert (dialog.ys(), dialog.hue()) == (["Cost"], "Sales")
    dialog.x_box.setCurrentIndex(1)  # Sales across: it can't color the points too
    assert [dialog.y_box.itemText(i) for i in range(dialog.y_box.count())] == ["Cost"]
    assert (dialog.ys(), dialog.hue()) == (["Cost"], None)
    assert [dialog.hue_box.itemText(i) for i in range(dialog.hue_box.count())] == ["None", "Month", "Cost", "Note"]
    dialog.hue_box.setCurrentIndex(dialog.hue_box.findData("Note"))
    dialog.x_box.setCurrentIndex(2)  # Cost across: Cost can't go up too; Note's hue stays
    assert (dialog.x(), dialog.ys(), dialog.hue()) == ("Cost", ["Sales"], "Note")


def test_categorical_scatter_takes_a_text_column_across(app):
    columns = GraphColumns(["Width", "Species", "Length"], [True, False, True], [False, True, False])
    dialog = GraphDialog(None, columns)
    assert dialog_state(dialog) == ("line", "Width", ["Length"], None, None)
    dialog.kind_box.setCurrentIndex(2)
    assert dialog_state(dialog) == ("strip", "Species", ["Length"], None, "o")  # needs markers
    assert not dialog.marker_box.model().item(0).isEnabled()
    dialog.kind_box.setCurrentIndex(0)
    assert dialog_state(dialog) == ("line", "Width", ["Length"], None, None)  # it follows the type...
    dialog.x_box.setCurrentIndex(2)
    dialog.x_box.activated.emit(2)  # ...until the user picks the x
    dialog.kind_box.setCurrentIndex(2)
    assert dialog.x() == "Length"


def iris_columns():
    return GraphColumns(["Species", "Width", "Length", "Site"], [False, True, True, False],
                        [True, False, False, True])


def items(box):
    return [box.itemText(i) for i in range(box.count())]


def test_categories_up_turn_a_categorical_scatter_sideways(app):
    dialog = GraphDialog(None, iris_columns(), "strip", "o")
    assert (dialog.x(), dialog.ys()) == ("Species", ["Width"])
    assert items(dialog.y_box) == ["Width", "Length"]  # categories across: numbers up
    dialog.x_box.setCurrentIndex(dialog.x_box.findData("Width"))
    dialog.x_box.activated.emit(dialog.x_box.currentIndex())
    assert items(dialog.y_box) == ["Species", "Length", "Site"]  # numbers across: categories can go up
    dialog.y_box.setCurrentIndex(dialog.y_box.findData(["Species"]))
    dialog.y_box.activated.emit(dialog.y_box.currentIndex())
    assert (dialog.x(), dialog.ys()) == ("Width", ["Species"])
    assert items(dialog.x_box) == ["Width", "Length"]  # categories up: only numbers across
    assert items(dialog.hue_box) == ["None", "Species", "Length", "Site"]
    dialog.kind_box.setCurrentIndex(1)  # Scatter: up takes numbers
    assert (dialog.x(), dialog.ys()) == ("Width", ["Length"])
    assert items(dialog.x_box) == ["Species", "Width", "Length", "Site"]


def test_line_graphs_take_numbers_up(app):
    dialog = GraphDialog(None, iris_columns())
    dialog.x_box.setCurrentIndex(dialog.x_box.findData("Width"))
    assert items(dialog.y_box) == ["Length"]


def test_swarm_plots(app):
    dialog = GraphDialog(None, sales_columns())
    dialog.kind_box.setCurrentIndex(2)
    assert dialog.form.isRowVisible(dialog.swarm_box) and dialog.kind() == "strip"
    dialog.swarm_box.setChecked(True)
    assert dialog.kind() == "swarm" and dialog.marker() == "o"
    dialog.kind_box.setCurrentIndex(1)
    assert not dialog.form.isRowVisible(dialog.swarm_box) and dialog.kind() == "scatter"
    swarm = GraphDialog(None, sales_columns(), "swarm", "D")  # the last choice was a swarm plot
    assert swarm.kind_box.currentText() == "Categorical scatter" and swarm.swarm_box.isChecked()


def test_scatter_needs_a_marker(app):
    dialog = GraphDialog(None, sales_columns())
    none = dialog.marker_box.model().item(0)
    dialog.kind_box.setCurrentIndex(1)
    assert dialog.marker() == "o" and not none.isEnabled()  # circles in place of None
    dialog.kind_box.setCurrentIndex(0)
    assert dialog.marker() is None and none.isEnabled()  # and back


def test_chosen_marker_stays(app):
    dialog = GraphDialog(None, sales_columns())
    dialog.kind_box.setCurrentIndex(1)
    dialog.marker_box.setCurrentIndex(dialog.marker_box.findData("s"))
    dialog.marker_box.activated.emit(dialog.marker_box.currentIndex())  # as a choice by the user does
    dialog.kind_box.setCurrentIndex(0)
    assert (dialog.kind(), dialog.marker()) == ("line", "s")


def test_scatter_from_the_start_gets_circles(app):
    assert GraphDialog(None, sales_columns(), "scatter", None).marker() == "o"


def test_importing_cells(app):
    notebook = Notebook()
    first = notebook.add_cell("x = 1").id
    both = notebook.add_cell(IMPORTS_CELL).id
    later = notebook.add_cell("import pandas as pd\ny = 2").id
    assert importing_cell(notebook, "pandas") == both and importing_cell(notebook, "seaborn") == both
    assert importing_cell(notebook, "pandas", before=both) is None
    assert importing_cell(notebook, "pandas", before=later) == both
    assert importing_cell(Notebook(), "seaborn") is None and first


def test_code_without_its_imports(sheet, app):
    cells = block(0, 0, 3, 1)
    assert dataframe_code(sheet, cells, "df", import_pandas=False).startswith("# Cells A1:B4")
    graph = graph_code(sheet, cells, "df", import_pandas=False, import_seaborn=False)
    assert graph.startswith("# df as a graph") and "pd.to_numeric" not in graph  # Sales is all numbers
    sheet.set_cell(2, 1, "n/a")
    assert graph_code(sheet, cells, "df", import_pandas=False, import_seaborn=False).startswith("# df as a graph")
    assert graph_code(sheet, cells, "df", import_seaborn=False).startswith("import pandas as pd\n\n# df")


def test_frame_names(app):
    notebook = Notebook()
    assert next_frame_name(notebook) == "df"
    notebook.add_cell("df = 1")
    assert next_frame_name(notebook) == "df2"
    notebook.add_cell("x = 2\ndf2 = 3\ndf3 == df2")  # a comparison isn't an assignment
    assert next_frame_name(notebook) == "df3"


# --- The notebook ---

def test_notebook_cells(app):
    notebook = Notebook()
    changes = []
    notebook.changed.connect(lambda: changes.append(1))
    a = notebook.add_cell("a = 1")
    b = notebook.add_cell("b = 2", 0)
    assert [c.source for c in notebook.cells] == ["b = 2", "a = 1"]
    notebook.move_cell(b.id, 1)
    assert [c.id for c in notebook.cells] == [a.id, b.id]
    notebook.add_output(a.id, {"output_type": "stream", "name": "stdout", "text": "x"})
    notebook.add_output(a.id, {"output_type": "clear_output"})
    assert notebook.cell(a.id).outputs == []
    notebook.remove_cell(b.id)
    assert len(notebook.cells) == 1 and len(changes) == 6


def test_printed_text_is_one_output_per_stream(app):
    notebook = Notebook()
    cell = notebook.add_cell()
    for name, text in (("stdout", "a\n"), ("stdout", ["b\n", "c\n"]), ("stderr", "oops\n"), ("stdout", "d\n")):
        notebook.add_output(cell.id, {"output_type": "stream", "name": name, "text": text})
    notebook.add_output(cell.id, {"output_type": "display_data", "data": {"text/plain": "x"}, "metadata": {}})
    notebook.add_output(cell.id, {"output_type": "stream", "name": "stdout", "text": "e\n"})
    assert [(o["output_type"], o.get("text")) for o in cell.outputs] == [
        ("stream", "a\nb\nc\n"), ("stream", "oops\n"), ("stream", "d\n"), ("display_data", None), ("stream", "e\n")]


def test_notebook_is_a_jupyter_document(app):
    notebook = Notebook()
    cell = notebook.add_cell("print(1)")
    notebook.add_output(cell.id, {"output_type": "stream", "name": "stdout", "text": "1\n"})
    notebook.set_execution_count(cell.id, 1)
    document = notebook.to_json()
    assert document["nbformat"] == 4 and document["metadata"]["kernelspec"]["name"] == "python3"
    assert document["cells"][0] == {"cell_type": "code", "id": cell.id, "metadata": {},
                                    "source": "print(1)", "execution_count": 1,
                                    "outputs": [{"output_type": "stream", "name": "stdout", "text": "1\n"}]}
    other = Notebook()
    other.load(json.loads(json.dumps(document)))
    assert other.to_json() == document


def test_loads_list_sources(app):
    cells = cells_from_json({"cells": [{"cell_type": "code", "source": ["a = 1\n", "a"], "outputs": []}]})
    assert cells[0].source == "a = 1\na"


@pytest.mark.parametrize("document", [
    [], {"cells": "x"}, {"cells": [{"cell_type": "markdown", "source": ""}]},
    {"cells": [{"cell_type": "code", "source": 5}]},
    {"cells": [{"cell_type": "code", "source": "", "execution_count": "1"}]},
    {"cells": [{"cell_type": "code", "id": "a", "source": ""}, {"cell_type": "code", "id": "a", "source": ""}]},
])
def test_bad_notebooks(document):
    with pytest.raises(NotebookFormatError):
        cells_from_json(document)


def test_saved_with_the_sheet(tmp_path, app):
    notebook = Notebook()
    notebook.add_cell("x = 1")
    path = str(tmp_path / "s.ezs")
    save_sheet(path, SheetData(10, 5, notebook=notebook.to_json()))
    assert load_sheet(path).notebook == notebook.to_json()
    save_sheet(path, SheetData(10, 5))
    assert "notebook" not in json.loads(open(path).read()) and load_sheet(path).notebook is None


def test_damaged_notebook_in_file(tmp_path):
    path = tmp_path / "bad.ezs"
    path.write_text(json.dumps({"format": "ezsheet", "version": 7, "rows": 10, "columns": 5,
                                "cells": {}, "notebook": {"cells": 3}}))
    with pytest.raises(SheetFileError, match="damaged"):
        load_sheet(str(path))


# --- Showing outputs ---

def png() -> str:
    image = QImage(40, 20, QImage.Format_RGB32)
    image.fill(0x336699)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return base64.b64encode(bytes(data)).decode()


def test_output_view(app):
    parent = QWidget()  # never shown, so the view isn't a window of its own
    view = OutputView(parent)
    view.show_outputs([
        {"output_type": "stream", "name": "stdout", "text": "hello <world>\n"},
        {"output_type": "execute_result", "data": {"text/html": "<table><tr><td>42</td></tr></table>",
                                                   "text/plain": "42"}, "execution_count": 1},
        {"output_type": "display_data", "data": {"image/png": png(), "text/plain": "<Figure>"}},
        {"output_type": "error", "ename": "ZeroDivisionError", "evalue": "division by zero",
         "traceback": ["\x1b[31mZeroDivisionError\x1b[39m: division by zero"]},
    ])
    text = view.toPlainText()
    assert "hello <world>" in text and "42" in text
    assert "ZeroDivisionError: division by zero" in text and "\x1b" not in text
    assert "<Figure>" not in text  # the image is shown instead of its text
    assert not view.document().resource(QTextDocument.ImageResource, "output:image2").isNull()
    assert not view.isHidden()
    view.show_outputs([])
    assert view.isHidden() and view.toPlainText() == ""


def test_dataframes_look_like_jupyters(app):
    parent = QWidget()  # kept, or it's deleted along with the view
    view = OutputView(parent)
    frame_html = pd.DataFrame({"a": [1, 2]})._repr_html_()
    assert '<table border="1" class="dataframe">' in frame_html
    view.show_outputs([{"output_type": "execute_result", "data": {"text/html": frame_html}, "metadata": {},
                        "execution_count": 1}])
    table = next(frame for frame in view.document().rootFrame().childFrames()
                 if isinstance(frame, QTextTable))
    assert table.format().border() == 0  # no grid
    assert (table.rows(), table.columns()) == (3, 2)


def test_bad_image_shows_its_text(app):
    parent = QWidget()  # kept, or it's deleted along with the view
    view = OutputView(parent)
    view.show_outputs([{"output_type": "display_data", "metadata": {},
                        "data": {"image/png": "not base64!", "text/plain": "<Figure>"}}])
    assert "<Figure>" in view.toPlainText()


# --- In the window, with a stand-in kernel ---

class FakeKernel(QObject):
    state_changed = Signal(str)
    started = Signal(str, int)
    output = Signal(str, dict)
    finished = Signal(str, object, str)
    cancelled = Signal(str)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.runs, self.interrupts, self.restarts, self.shutdowns = [], 0, 0, 0
        self.has_kernel, self.working_dir, self.count = False, None, 0

    def run(self, cell_id, code):
        self.runs.append((cell_id, code))
        self.count += 1
        self.output.emit(cell_id, {"output_type": "execute_result", "metadata": {},
                                   "data": {"text/plain": f"result {self.count}"}, "execution_count": self.count})
        self.finished.emit(cell_id, self.count, "ok")

    def interrupt(self):
        self.interrupts += 1

    def restart(self):
        self.restarts += 1

    def shutdown(self, timeout=5.0):
        self.shutdowns += 1


@pytest.fixture
def window(app, sheet):
    window = MainWindow()
    window.kernel = FakeKernel()
    window.model.set_cells({key: sheet.get_cell(*key) for key in block(0, 0, 3, 2)})
    window.show()
    yield window
    if window.notebook_window is not None:
        window.notebook_window.hide()
    window.setWindowModified(False)
    window.close()


def test_send_to_notebook(window):
    window.view.select_range(0, 0, 3, 2)
    cell_id = window.send_to_notebook()
    notebook_window = window.notebook_window
    assert notebook_window.isVisible()
    imports, cell = window.notebook.cells  # a new notebook: its imports cell comes first
    assert imports.source == IMPORTS_CELL == "import pandas as pd\nimport seaborn as sns"
    assert window.kernel.runs == [(imports.id, IMPORTS_CELL), (cell_id, cell.source)]
    assert cell.source.startswith("# Cells A1:C4 of the sheet") and "import" not in cell.source
    assert "df = pd.DataFrame({" in cell.source
    assert cell.execution_count == 2
    widget = notebook_window.widgets[cell_id]
    assert widget.prompt.text() == "[2]:" and "result 2" in widget.output_view.toPlainText()
    assert window.isWindowModified()
    assert "as df" in window.statusBar().currentMessage()


def test_whole_columns_send_just_their_data(window):
    window.view.select_range(0, 0, window.model.rowCount() - 1, 4)  # columns A to E
    cell_id = window.send_to_notebook()
    source = window.notebook.cell(cell_id).source
    assert "# Cells A1:C4 of the sheet" in source
    df = frame(source)
    assert df.shape == (3, 3)


def test_empty_selection_makes_nothing(window):
    window.view.select_range(10, 0, 12, 2)
    assert window.send_to_notebook() is None
    assert window.notebook.is_empty and window.notebook_window is None
    assert "empty" in window.statusBar().currentMessage()


def test_second_selection_appends_df2(window):
    window.view.select_range(0, 0, 3, 0)
    window.send_to_notebook()
    window.notebook_window.set_current(window.notebook.cells[0].id)
    window.view.select_range(0, 1, 3, 1)
    second = window.send_to_notebook()
    assert window.notebook.cells[-1].id == second  # new data goes at the end
    assert "df2 = pd.DataFrame" in window.notebook.cell(second).source


def notebook_submenu(menu):
    return next(action.menu() for action in menu.actions() if action.text() == "Notebook")


def test_tool_in_toolbar_menus_and_context_menu(window, monkeypatch):
    toolbar = window.findChild(QToolBar)
    assert window.notebook_button in [toolbar.widgetForAction(action) for action in toolbar.actions()]
    shown = []
    monkeypatch.setattr(window.notebook_button, "showMenu", lambda: shown.append(1))  # (it would block)
    window.notebook_button.click()
    assert shown == [1]  # the button itself shows the menu, not just its arrow
    insert = [m for m in window.menuBar().actions() if m.text() == "Insert"][0].menu()
    for menu in (window.notebook_button.menu(), notebook_submenu(insert), notebook_submenu(window.context_menu)):
        actions = menu.actions()
        assert [actions[0], actions[2], actions[3], actions[5]] == [
            window.open_notebook_action, window.dataframe_action, window.graph_action, window.load_data_action]
        assert [action.text() for action in actions] == ["Open", "", "DataFrame", "Graph", "",
                                                         "Load Data to Sheet…"]


def test_open_starts_a_new_notebook_with_its_imports(window):
    window.view.select_range(0, 0, 3, 2)
    window.open_notebook_action.trigger()
    nb = window.notebook_window
    [imports] = window.notebook.cells
    assert nb.isVisible() and imports.source == IMPORTS_CELL
    assert window.kernel.runs == [(imports.id, IMPORTS_CELL)]  # run, so pd and sns are ready
    cell_id = window.send_to_notebook()
    nb.hide()
    window.open_notebook_action.trigger()
    assert nb.isVisible() and [c.id for c in window.notebook.cells] == [imports.id, cell_id]
    assert len(window.kernel.runs) == 2  # opening it again added and ran nothing


def test_opening_a_notebook_with_cells_adds_nothing(window, tmp_path):
    window.notebook.load({"cells": [{"cell_type": "code", "source": "x = 1", "outputs": []}]})
    window.open_notebook_action.trigger()
    assert [c.source for c in window.notebook.cells] == ["x = 1"] and window.kernel.runs == []


def test_a_notebook_without_imports_keeps_them_in_its_cells(window):
    window.notebook.load({"cells": [{"cell_type": "code", "source": "x = 1", "outputs": []}]})
    window.view.select_range(0, 0, 3, 1)
    window.send_to_notebook()
    assert window.notebook.cells[-1].source.startswith("import pandas as pd\n")
    window.graph_action.trigger()
    assert window.notebook.cells[-1].source.startswith("import seaborn as sns\n")
    assert len(window.notebook.cells) == 4  # no imports cell was added


def test_imports_run_again_before_new_cells(window, tmp_path):
    window.view.select_range(0, 0, 3, 1)
    window.send_to_notebook()
    window.save_to(str(tmp_path / "s.ezs"))
    window.open_path(str(tmp_path / "s.ezs"))  # a new Python process: nothing has run
    imports = window.notebook.cells[0].id
    runs = len(window.kernel.runs)
    window.view.select_range(0, 0, 3, 1)
    window.graph_action.trigger()
    assert [run[0] for run in window.kernel.runs[runs:]] == [imports, *(c.id for c in window.notebook.cells[-2:])]
    view_menu = [m for m in window.menuBar().actions() if m.text() == "View"][0].menu()
    assert window.show_notebook_action in view_menu.actions()


def test_notebook_saved_and_opened_with_sheet(window, tmp_path):
    window.view.select_range(0, 0, 3, 2)
    window.send_to_notebook()
    path = str(tmp_path / "s.ezs")
    assert window.save_to(path)
    assert not window.isWindowModified()
    assert window.notebook_window.windowTitle() == "Notebook — s.ezs"
    other = MainWindow()
    other.kernel = FakeKernel()
    other.open_path(path)
    assert [c.source for c in other.notebook.cells] == [c.source for c in window.notebook.cells]
    assert other.notebook.cells[0].outputs  # outputs are kept, like Jupyter
    assert other.kernel.runs == []  # opening runs nothing
    assert other.kernel.shutdowns == 1  # the previous sheet's kernel was stopped
    other.setWindowModified(False)


def test_editing_notebook_marks_sheet_modified(window, tmp_path):
    window.save_to(str(tmp_path / "s.ezs"))
    nb = window.show_notebook()
    nb.add_cell_below("x = 1")
    assert window.isWindowModified()
    window.save_to(str(tmp_path / "s.ezs"))
    window.model.set_cell(9, 0, "a")
    window.model.undo_stack.undo()  # back to the saved sheet...
    assert not window.isWindowModified()
    nb.widgets[nb.current_id].editor.setPlainText("x = 2")
    window.model.set_cell(9, 0, "a")
    window.model.undo_stack.undo()
    assert window.isWindowModified()  # ...but the notebook still has changes


def test_shift_return_runs_and_moves_on(window):
    nb = window.show_notebook()
    first = nb.add_cell_below("1 + 1")
    QTest.keyClick(nb.widgets[first].editor, Qt.Key_Return, Qt.ShiftModifier)
    assert window.kernel.runs[-1] == (first, "1 + 1")
    assert len(window.notebook.cells) == 3 and nb.current_id == window.notebook.cells[2].id  # after the imports
    QTest.keyClick(nb.widgets[first].editor, Qt.Key_Return, Qt.ControlModifier)  # run in place
    assert window.kernel.runs[-1][0] == first and len(window.notebook.cells) == 3


def test_editor_indents(window):
    nb = window.show_notebook()
    cell = nb.add_cell_below()
    editor = nb.widgets[cell].editor
    QTest.keyClicks(editor, "for i in range(3):")
    QTest.keyClick(editor, Qt.Key_Return)
    QTest.keyClicks(editor, "print(i)")
    assert window.notebook.cell(cell).source == "for i in range(3):\n    print(i)"


def test_toolbar_commands(window):
    nb = window.show_notebook()
    imports = window.notebook.cells[0].id
    a = nb.add_cell_below("a")
    b = nb.add_cell_below("b")
    nb.actions_by_name["Run All"].trigger()
    assert [run[0] for run in window.kernel.runs[1:]] == [imports, a, b]
    nb.actions_by_name["↑"].trigger()
    assert [c.id for c in window.notebook.cells] == [imports, b, a]
    nb.actions_by_name["Interrupt"].trigger()
    nb.actions_by_name["Restart"].trigger()
    assert (window.kernel.interrupts, window.kernel.restarts) == (1, 1)
    nb.actions_by_name["Delete"].trigger()
    assert [c.id for c in window.notebook.cells] == [imports, a]


def test_kernel_status_and_problems(window):
    nb = window.show_notebook()
    assert nb.status.text() == "Python: stopped"
    window.kernel.state_changed.emit("busy")
    assert nb.status.text() == "Python: running"
    window.kernel.failed.emit("The Python kernel couldn't start: no ipykernel")
    assert not nb.problem.isHidden() and "no ipykernel" in nb.problem.text()
    window.kernel.state_changed.emit("starting")
    assert nb.problem.isHidden() and nb.status.text() == "Starting Python…"
    cell = nb.add_cell_below("x")
    nb.running.add(cell)  # as if waiting its turn
    nb._on_cell_updated(cell)
    assert nb.widgets[cell].prompt.text() == "[*]:"
    window.kernel.cancelled.emit(cell)  # Interrupt dropped it
    assert nb.widgets[cell].prompt.text() == "[ ]:" and not nb.running


def test_closing_notebook_hides_it(window):
    nb = window.show_notebook()
    nb.add_cell_below("x")
    assert nb.close()  # accepted, so it never holds up quitting
    assert not nb.isVisible() and window.show_notebook() is nb and len(window.notebook.cells) == 2


def test_closing_sheet_stops_kernel_and_hides_notebook(app):
    window = MainWindow()
    window.kernel = FakeKernel()
    window.show()
    nb = window.show_notebook()
    window.close()
    assert window.kernel.shutdowns == 1 and not nb.isVisible()


def test_kernel_starts_in_sheets_folder(app, tmp_path):
    window = MainWindow()
    window.save_to(str(tmp_path / "s.ezs"))
    assert window.kernel.working_dir == str(tmp_path)
    window.setWindowModified(False)


def test_graph_from_the_notebook_menu(window, dialogs):
    window.view.select_range(0, 0, window.model.rowCount() - 1, 1)  # columns A and B: Month, Sales
    window.graph_action.trigger()
    assert dialogs.graph_prompts == [(["Month", "Sales"], ("line", None))]
    imports, frame_cell, graph_cell = window.notebook.cells
    assert [run[0] for run in window.kernel.runs] == [imports.id, frame_cell.id, graph_cell.id]  # in order
    assert frame_cell.source == dataframe_code(window.model, block(0, 0, 3, 1), "df", import_pandas=False)
    assert "graph = sns.relplot(" in graph_cell.source and "x='Month', y='Sales'" in graph_cell.source
    assert graph_cell.source.startswith("# df as a graph") and "import" not in graph_cell.source
    assert window.notebook_window.isVisible()
    assert "as df, with a graph" in window.statusBar().currentMessage()
    assert "kind='line'" in graph_cell.source and "marker" not in graph_cell.source
    dialogs.graph_answer = ("scatter", "s")
    window.view.select_range(0, 0, 3, 1)
    window.graph_action.trigger()
    source = window.notebook.cells[-1].source
    assert "df2 as a graph" in source and "kind='scatter'" in source and "marker='s'" in source
    window.graph_action.trigger()
    assert dialogs.graph_prompts[-1][1] == ("scatter", "s")  # the dialog starts from the last choices


def test_cancelling_the_graph_dialog(window, dialogs):
    dialogs.graph_answer = None
    window.view.select_range(0, 0, 3, 1)
    assert window.send_graph_to_notebook() is None
    assert window.notebook.is_empty and window.notebook_window is None
    assert (window.graph_kind, window.graph_marker) == ("line", None)


@pytest.mark.parametrize("selection, problem", [
    ((0, 2, 3, 3), "Select at least two columns"),  # C and D, but D is empty
    ((0, 0, 3, 2), None),  # Sales has numbers, so Note's text just isn't graphed
    ((10, 0, 12, 2), "no graphs to change"),  # empty: for changing a graph, but there are none
    ((0, 0, 3, 0), "no graphs to change"),  # one column: likewise
])
def test_graph_problems(window, dialogs, selection, problem):
    if problem is None:
        window.view.select_range(*selection)
        assert window.send_graph_to_notebook() is not None
        return
    window.model.set_cells({(0, 1): "Sales", (1, 1): "x", (2, 1): "y", (3, 1): "z"})  # no numbers
    window.view.select_range(*selection)
    assert window.send_graph_to_notebook() is None
    assert problem in window.statusBar().currentMessage()
    assert window.notebook.is_empty and window.notebook_window is None
    assert dialogs.graph_prompts == []  # told before the dialog, not after


def test_graph_needs_numbers(window):
    window.model.set_cells({(1, 1): "x", (2, 1): "y", (3, 1): ""})
    window.view.select_range(0, 0, 3, 1)
    assert window.send_graph_to_notebook() is None
    assert "no numbers to graph" in window.statusBar().currentMessage()


# --- Changing a graph (Graph with no data selected) ---

def make_graph(window, columns=1) -> str:
    """A graph of A1:B4 (or more columns): its cell's id. The notebook is shown."""
    window.view.select_range(0, 0, 3, columns)
    return window.send_graph_to_notebook()


def test_no_graphs_to_change(window, dialogs):
    window.view.select_range(10, 0, 12, 2)  # empty
    assert window.send_graph_to_notebook() is None
    assert "no graphs to change" in window.statusBar().currentMessage()
    assert dialogs.graph_change_prompts == [] and dialogs.graph_prompts == []


def test_change_a_graph(window, dialogs):
    graph_id = make_graph(window)
    runs = len(window.kernel.runs)
    window.view.select_range(10, 0, 12, 2)
    dialogs.graph_change_answer = (0, "scatter", "s")
    assert window.send_graph_to_notebook() == graph_id
    [(graphs, current)] = dialogs.graph_change_prompts
    assert [g.cell_id for g in graphs] == [graph_id] and current == 0
    assert (graphs[0].kind, graphs[0].marker, graphs[0].title) == ("line", None, "Sales against Month")
    source = window.notebook.cell(graph_id).source
    assert "kind='scatter',  # or 'line'" in source and "marker='s', height=4" in source
    nb = window.notebook_window
    assert nb.widgets[graph_id].editor.toPlainText() == source and nb.current_id == graph_id
    assert [run[0] for run in window.kernel.runs[runs:]] == [graph_id]  # its DataFrame is still there
    assert len(window.notebook.cells) == 3  # nothing added
    assert "Redrawing the graph df: Sales against Month" in window.statusBar().currentMessage()
    nb.widgets[graph_id].editor.undo()  # the change is an edit in the cell, so Undo there reverts it
    assert "kind='line'" in window.notebook.cell(graph_id).source


@pytest.mark.parametrize("new_process", [
    lambda window: window.notebook_window.restart(),  # asked for, so before the new process even starts
    lambda window: window.kernel.state_changed.emit("starting"),  # as after Python crashed
])
def test_dataframe_made_again_after_a_restart(window, dialogs, new_process):
    graph_id = make_graph(window)
    imports_id, frame_id = (cell.id for cell in window.notebook.cells[:2])
    new_process(window)  # pd, sns, and df are gone
    runs = len(window.kernel.runs)
    window.view.select_range(10, 0, 12, 2)
    dialogs.graph_change_answer = (0, "line", "o")
    window.send_graph_to_notebook()
    assert [run[0] for run in window.kernel.runs[runs:]] == [imports_id, frame_id, graph_id]


def test_dataframe_made_again_in_a_reopened_sheet(window, dialogs, tmp_path):
    make_graph(window)
    window.save_to(str(tmp_path / "s.ezs"))
    window.open_path(str(tmp_path / "s.ezs"))
    imports_id, frame_id, graph_id = (cell.id for cell in window.notebook.cells)
    runs = len(window.kernel.runs)
    window.view.select_range(10, 0, 12, 2)
    dialogs.graph_change_answer = (0, "scatter", None)
    window.send_graph_to_notebook()
    assert [run[0] for run in window.kernel.runs[runs:]] == [imports_id, frame_id, graph_id]


def test_starts_with_the_current_graph(window, dialogs):
    first = make_graph(window)
    make_graph(window, columns=2)
    window.notebook_window.set_current(first)
    window.view.select_range(10, 0, 12, 2)
    window.send_graph_to_notebook()  # cancelled
    graphs, current = dialogs.graph_change_prompts[-1]
    assert len(graphs) == 2 and graphs[current].cell_id == first
    window.notebook_window.set_current(window.notebook.cells[0].id)  # a DataFrame cell: the last graph
    window.send_graph_to_notebook()
    assert dialogs.graph_change_prompts[-1][1] == 1


@pytest.mark.parametrize("selection", [
    (0, 1, 3, 1),  # one column of data
    (0, 1, 99, 1),  # a whole column, as clicking its header selects
    (2, 2, 2, 2),  # one cell, with data
    (20, 3, 22, 3),  # one empty column
])
def test_one_column_changes_a_graph(window, dialogs, selection):
    graph_id = make_graph(window)
    cells_before = len(window.notebook.cells)
    window.view.select_range(*selection)
    dialogs.graph_change_answer = (0, "scatter", "x")
    assert window.send_graph_to_notebook() == graph_id
    assert dialogs.graph_prompts == [(["Month", "Sales"], ("line", None))]  # only the first graph's
    assert len(dialogs.graph_change_prompts) == 1 and len(window.notebook.cells) == cells_before
    assert "marker='x'" in window.notebook.cell(graph_id).source


def test_change_a_graphs_columns(window, dialogs):
    graph_id = make_graph(window, columns=2)  # Month, Sales, Note
    window.view.select_range(10, 0, 12, 2)
    dialogs.graph_change_answer = (0, "strip", "D", "Month", ["Sales"])
    window.send_graph_to_notebook()
    [(graphs, _)] = dialogs.graph_change_prompts
    assert graphs[0].columns.labels == ["Month", "Sales", "Note"]  # from the DataFrame's cell
    source = window.notebook.cell(graph_id).source
    assert source == graph_code(window.model, block(0, 0, 3, 2), "df", "strip", "D", x="Month", ys=["Sales"],
                                import_pandas=False, import_seaborn=False)
    assert window.kernel.runs[-1][0] == graph_id


def test_swarm_graph_with_hue(window, dialogs):
    window.view.select_range(0, 0, 3, 2)  # Month, Sales, Note
    dialogs.graph_answer = ("swarm", "D", "Month", ["Sales"], "Note")
    graph_id = window.send_graph_to_notebook()
    source = window.notebook.cell(graph_id).source
    assert "sns.catplot(" in source and "x='Month', y='Sales', hue='Note'" in source and "kind='swarm'" in source
    assert (window.graph_kind, window.graph_marker) == ("swarm", "D")  # remembered for next time


def test_change_a_graphs_hue(window, dialogs):
    graph_id = make_graph(window, columns=2)
    window.view.select_range(10, 0, 12, 2)
    dialogs.graph_change_answer = (0, "line", None, "Month", ["Sales"], "Note")
    window.send_graph_to_notebook()
    assert "hue='Note'" in window.notebook.cell(graph_id).source
    [(graphs, _)] = dialogs.graph_change_prompts
    assert graphs[0].hue is None
    dialogs.graph_change_answer = (0, "scatter", "o")  # keeps the hue, now read from the code
    window.send_graph_to_notebook()
    source = window.notebook.cell(graph_id).source
    assert "hue='Note'" in source and "kind='scatter'" in source
    assert dialogs.graph_change_prompts[1][0][0].hue == "Note"


def test_change_a_graph_to_sideways(window, dialogs):
    graph_id = make_graph(window, columns=2)  # Month, Sales, Note
    window.view.select_range(10, 0, 12, 2)
    dialogs.graph_change_answer = (0, "strip", "o", "Sales", ["Note"])
    window.send_graph_to_notebook()
    source = window.notebook.cell(graph_id).source
    assert "sns.catplot(" in source and "x='Sales', y='Note'" in source


def test_type_change_keeps_hand_edits(window, dialogs):
    graph_id = make_graph(window)
    nb = window.notebook_window
    nb.replace_source(graph_id, window.notebook.cell(graph_id).source.replace("height=4", "height=7"))
    window.view.select_range(10, 0, 12, 2)
    dialogs.graph_change_answer = (0, "strip", "o")  # same columns
    window.send_graph_to_notebook()
    source = window.notebook.cell(graph_id).source
    assert "sns.catplot(" in source and "height=7" in source


def test_cancel_changes_nothing(window, dialogs):
    graph_id = make_graph(window)
    source, runs = window.notebook.cell(graph_id).source, len(window.kernel.runs)
    window.view.select_range(10, 0, 12, 2)
    assert window.send_graph_to_notebook() is None
    assert window.notebook.cell(graph_id).source == source and len(window.kernel.runs) == runs


# --- Zoom ---

def activate(widget):
    """Bring a window to the front. (qWaitForWindowActive won't do: it counts
    the notebook as active whenever the sheet, its parent, is.)"""
    widget.activateWindow()
    assert wait_for(lambda: QApplication.activeWindow() is widget, timeout=5)


def test_zoom_applies_to_the_window_in_front(window):
    nb = window.show_notebook()
    cell = nb.add_cell_below("x = 1")
    activate(nb)
    code_size = nb.widgets[cell].editor.font().pointSizeF()
    sheet_size = window.view.font().pointSizeF()
    window.zoom_actions["Zoom In"].trigger()  # as Cmd+= does from the Mac's menu bar
    window.zoom_actions["Zoom In"].trigger()
    assert (nb.zoom, window.zoom) == (125, 100)
    assert nb.widgets[cell].editor.font().pointSizeF() == pytest.approx(code_size * 1.25)
    assert window.view.font().pointSizeF() == sheet_size
    assert nb.status.text() == "Zoom 125%"
    activate(window)
    window.zoom_actions["Zoom Out"].trigger()
    assert (nb.zoom, window.zoom) == (125, 90)
    activate(nb)
    window.zoom_actions["Actual Size"].trigger()
    assert (nb.zoom, window.zoom) == (100, 90)
    assert nb.widgets[cell].editor.font().pointSizeF() == pytest.approx(code_size)


def test_zoom_limits_follow_the_window_in_front(window):
    activate(window)
    window.set_zoom(300)
    assert not window.zoom_actions["Zoom In"].isEnabled()
    nb = window.show_notebook()
    activate(nb)
    assert window.zoom_actions["Zoom In"].isEnabled()  # the notebook is at 100%
    for _ in range(20):
        window.zoom_actions["Zoom Out"].trigger()
    assert (nb.zoom, window.zoom) == (50, 300)
    assert not window.zoom_actions["Zoom Out"].isEnabled() and window.zoom_actions["Zoom In"].isEnabled()
    activate(window)
    assert window.zoom_actions["Zoom Out"].isEnabled() and not window.zoom_actions["Zoom In"].isEnabled()


def test_notebook_zoom_scales_code_outputs_and_toolbar(window):
    nb = window.show_notebook()
    cell = nb.add_cell_below("1 + 1")
    nb.run_cell(cell)
    widget = nb.widgets[cell]
    run_button = nb.toolbar.widgetForAction(nb.actions_by_name["Run"])
    sizes = {w: w.font().pointSizeF() for w in (widget.editor, widget.prompt, widget.output_view, run_button,
                                                nb.status)}
    QApplication.processEvents()  # lays out the outputs
    heights = widget.editor.height(), widget.output_view.height()
    nb.set_zoom(200)
    QApplication.processEvents()
    for w, points in sizes.items():
        assert w.font().pointSizeF() == pytest.approx(points * 2)
    assert widget.editor.height() > heights[0] * 1.3 and widget.output_view.height() > heights[1] * 1.3
    later = nb.add_cell_below("y")  # new cells come zoomed
    assert nb.widgets[later].editor.font().pointSizeF() == pytest.approx(sizes[widget.editor] * 2)
    assert window.zoom == 100


def test_zoomed_plots_grow(app):
    parent = QWidget()
    view = OutputView(parent)
    retina = {"output_type": "display_data", "data": {"image/png": png()},  # 40 by 20 pixels...
              "metadata": {"image/png": {"width": 20, "height": 10}}}  # ...shown as 20 by 10 points
    plain = {"output_type": "display_data", "data": {"image/png": png()}, "metadata": {}}
    view.show_outputs([retina, plain])
    assert 'width="20" height="10"' in view.toHtml() and 'width="40" height="20"' in view.toHtml()
    view.set_zoom(200)
    assert 'width="40" height="20"' in view.toHtml() and 'width="80" height="40"' in view.toHtml()


def test_zoom_steps():
    from py_spread.appearance import next_zoom
    assert (next_zoom(100, 1), next_zoom(100, -1)) == (110, 90)
    assert (next_zoom(300, 1), next_zoom(50, -1)) == (300, 50)
    assert next_zoom(105, 1) == 110 and next_zoom(105, -1) == 100


# --- With a real kernel ---

def wait_for(predicate, timeout=60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_real_kernel_runs_the_dataframe(app, sheet):
    window = MainWindow()
    window.model.set_cells({key: sheet.get_cell(*key) for key in block(0, 0, 3, 2)})
    try:
        window.view.select_range(0, 0, 3, 2)
        cell_id = window.send_to_notebook()
        cell = window.notebook.cell(cell_id)
        assert wait_for(lambda: cell.execution_count is not None)
        html = "".join(o.get("data", {}).get("text/html", "") for o in cell.outputs)
        assert "<table" in html and "Month" in html and "1200.0" in html
        nb = window.notebook_window
        follow = nb.add_cell_below("print(df['Sales'].sum())\ndf.shape")
        nb.run_cell(follow)
        assert wait_for(lambda: window.notebook.cell(follow).execution_count is not None)
        outputs = window.notebook.cell(follow).outputs
        assert outputs[0]["text"] == "2650.5\n" and outputs[1]["data"]["text/plain"] == "(3, 3)"
    finally:
        if window.notebook_window is not None:
            window.notebook_window.hide()
        window.setWindowModified(False)
        window.close()
    assert not window.kernel.has_kernel


def test_real_kernel_draws_the_graph(app, sheet, dialogs):
    dialogs.graph_answer = ("scatter", "D")
    window = MainWindow()
    window.model.set_cells({key: sheet.get_cell(*key) for key in block(0, 0, 3, 2)})
    try:
        window.view.select_range(0, 0, 3, 1)
        graph_id = window.send_graph_to_notebook()
        cell = window.notebook.cell(graph_id)
        assert wait_for(lambda: cell.execution_count is not None)
        kinds = [o["output_type"] for o in cell.outputs]
        assert "error" not in kinds, cell.outputs
        assert any("image/png" in o.get("data", {}) for o in cell.outputs)
    finally:
        if window.notebook_window is not None:
            window.notebook_window.hide()
        window.setWindowModified(False)
        window.close()


def test_real_kernel_redraws_a_changed_graph(app, sheet, dialogs):
    window = MainWindow()
    window.model.set_cells({key: sheet.get_cell(*key) for key in block(0, 0, 3, 2)})
    try:
        window.view.select_range(0, 0, 3, 1)
        graph_id = window.send_graph_to_notebook()
        nb = window.notebook_window
        assert wait_for(lambda: not nb.running)
        nb.restart()  # forgets df
        assert wait_for(lambda: nb.status.text() == "Python: idle")
        window.view.select_range(10, 0, 12, 2)
        dialogs.graph_change_answer = (0, "scatter", "D")
        window.send_graph_to_notebook()
        assert wait_for(lambda: not nb.running)
        outputs = window.notebook.cell(graph_id).outputs
        assert "error" not in [o["output_type"] for o in outputs], outputs
        assert any("image/png" in o.get("data", {}) for o in outputs)
    finally:
        if window.notebook_window is not None:
            window.notebook_window.hide()
        window.setWindowModified(False)
        window.close()


def test_real_kernel_draws_a_categorical_scatter(app, dialogs):
    window = MainWindow()
    window.model.set_cells({(0, 0): "Species", (0, 1): "Width", (0, 2): "Site", (1, 0): "a", (1, 1): "1.5",
                            (1, 2): "N", (2, 0): "b", (2, 1): "2", (2, 2): "S", (3, 0): "a", (3, 1): "1.7",
                            (3, 2): "S"})
    dialogs.graph_answer = ("swarm", "D", "Species", ["Width"], "Site")
    try:
        window.view.select_range(0, 0, 3, 2)
        graph_id = window.send_graph_to_notebook()
        nb = window.notebook_window
        assert wait_for(lambda: not nb.running)
        outputs = window.notebook.cell(graph_id).outputs
        assert "error" not in [o["output_type"] for o in outputs], outputs
        assert any("image/png" in o.get("data", {}) for o in outputs)
        assert "kind='swarm'" in window.notebook.cell(graph_id).source
        dialogs.graph_answer = ("strip", "o", "Width", ["Species"])  # sideways
        window.view.select_range(0, 0, 3, 2)
        sideways_id = window.send_graph_to_notebook()
        assert wait_for(lambda: not nb.running)
        outputs = window.notebook.cell(sideways_id).outputs
        assert "error" not in [o["output_type"] for o in outputs], outputs
        assert any("image/png" in o.get("data", {}) for o in outputs)
    finally:
        if window.notebook_window is not None:
            window.notebook_window.hide()
        window.setWindowModified(False)
        window.close()


def test_real_kernel_errors_interrupt_and_restart(app):
    from py_spread.kernel import KernelRunner
    runner = KernelRunner()
    notebook = Notebook()
    nb = NotebookWindow(notebook, runner)
    try:
        bad = nb.add_cell_below("1/0")
        after = nb.add_cell_below("print('not run')")
        nb.run_all()
        assert wait_for(lambda: bad not in nb.running and after not in nb.running)
        assert notebook.cell(bad).outputs[-1]["ename"] == "ZeroDivisionError"
        assert notebook.cell(after).outputs == []  # stopped at the error, like Jupyter
        loop = nb.add_cell_below("import time\nx = 1\nwhile True: time.sleep(0.05)")
        nb.run_cell(loop)
        assert wait_for(lambda: nb.status.text() == "Python: running")
        nb.interrupt()
        assert wait_for(lambda: loop not in nb.running)
        assert notebook.cell(loop).outputs[-1]["ename"] == "KeyboardInterrupt"
        nb.restart()
        check = nb.add_cell_below("x")
        nb.run_cell(check)
        assert wait_for(lambda: check not in nb.running)
        assert notebook.cell(check).outputs[-1]["ename"] == "NameError"  # restarting forgot x
    finally:
        runner.shutdown()
    assert not runner.has_kernel
