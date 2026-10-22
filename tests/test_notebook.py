import base64
import json
import math
import time

import pandas as pd
import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QImage, QTextDocument, QTextTable
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QToolBar, QToolButton, QWidget

from ezsheet.model import SheetModel
from ezsheet.notebook import (
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
from ezsheet.graph_dialog import MARKERS, GraphDialog
from ezsheet.notebook_window import NotebookWindow, OutputView
from ezsheet.storage import SheetData, SheetFileError, load_sheet, save_sheet
from ezsheet.window import MainWindow


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
    return namespace["chart"]


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


def test_line_chart_of_every_column_by_default(sales, pyplot):
    code = graph_code(sales, block(0, 0, 3, 2))
    assert "value_vars=['Sales', 'Cost']" in code and "hue='Series'" in code  # All: a line each
    g = graph(sales, block(0, 0, 3, 2))
    assert [t.get_text() for t in g.ax.get_xticklabels()] == ["Mar", "Jan", "Feb"]  # the sheet's order
    assert [t.get_text() for t in g.legend.texts] == ["Sales", "Cost"]


def test_other_charts_of_one_column_by_default(sales, pyplot):
    for kind in ("scatter", "strip", "swarm"):
        code = graph_code(sales, block(0, 0, 3, 2), "df", kind, "o")
        assert "x='Month', y='Sales'" in code and "melt" not in code
    assert graph(sales, block(0, 0, 3, 2), "scatter", "o").ax.get_ylabel() == "Sales"


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
    assert g.ax.get_ylabel() == "Sales" and g.legend is None  # named on the y axis


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
    (block(0, 0, 3, 0), "no numbers"),  # Month's text
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
    assert "# df as a chart: 'Length' against 'Species'." in code  # the next column with numbers after x
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


def years_model():
    model = SheetModel(rows=10, cols=4)
    model.set_cells({(0, 0): "Year", (0, 1): "Sales", (0, 2): "Site",
                     (1, 0): "2022", (1, 1): "5", (1, 2): "N", (2, 0): "2020", (2, 1): "3", (2, 2): "S",
                     (3, 0): "2021", (3, 1): "4", (3, 2): "N", (4, 0): "2020", (4, 1): "3.5", (4, 2): "S"})
    return model


def test_years_as_y_categories(pyplot, app):
    model, cells = years_model(), block(0, 0, 4, 2)
    columns = graph_columns(model, cells)
    assert columns.x_options("Year", "strip") == ["Year", "Sales", "Site"]  # numbers up: values
    assert columns.x_options("Year", "strip", y_categories=True) == ["Sales"]  # categories up: numbers across
    assert columns.sideways(["Year"], "swarm", True) and not columns.sideways(["Year"], "line", True)
    code = graph_code(model, cells, "df", "strip", "o", x="Sales", ys=["Year"], y_categories=True)
    assert "x='Sales', y='Year', orient='h'," in code
    g = graph(model, cells, "strip", "o", x="Sales", ys=["Year"], y_categories=True)
    assert [t.get_text() for t in g.ax.get_yticklabels()] == ["2020", "2021", "2022"]
    assert g.ax.get_xlabel() == "Sales"
    upright = graph_code(model, cells, "df", "strip", "o", x="Sales", ys=["Year"])
    assert "orient" not in upright  # without it, Sales across are the categories
    with pytest.raises(ValueError):  # categories up need numbers across
        graph_code(model, cells, "df", "strip", "o", x="Site", ys=["Year"], y_categories=True)


def test_hue(sales, pyplot):
    code = graph_code(sales, block(0, 0, 3, 2), "df", "scatter", "o", x="Sales", ys=["Cost"], hue="Month")
    assert "data=data, x='Sales', y='Cost', hue='Month'" in code
    assert "# df as a chart: 'Cost' against 'Sales', colored by 'Month'." in code
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


@pytest.fixture
def regions(app):
    """Sales and Cost by month for three regions: A1:D7."""
    model = SheetModel(rows=20, cols=6)
    rows = [("Region", "Month", "Sales", "Cost"), ("North", "Jan", "100", "60"), ("North", "Feb", "120", "70"),
            ("South", "Jan", "90", "50"), ("South", "Feb", "95", "55"), ("East", "Jan", "80", "40"),
            ("East", "Feb", "85", "45")]
    model.set_cells({(r, c): value for r, row in enumerate(rows) for c, value in enumerate(row)})
    return model


def panels(g) -> dict[str, int]:
    """Each panel's title, and how many lines it has."""
    return {ax.get_title(): len([line for line in ax.get_lines() if len(line.get_xdata())]) for ax in g.axes.flat}


def test_col_splits_a_line_chart_into_panels(regions, pyplot):
    code = graph_code(regions, block(0, 0, 6, 3), "df", "line", None, x="Month", ys=["Sales"], col="Region")
    assert "# df as a chart: 'Sales' against 'Month', a panel for each 'Region'." in code
    assert "    col='Region', col_wrap=2,  # a panel for each, 2 to a row\n" in code
    assert "height=2.5, aspect=1.2," in code  # smaller, so two fit across the notebook
    g = graph(regions, block(0, 0, 6, 3), "line", None, x="Month", ys=["Sales"], col="Region")
    assert panels(g) == {"Region = North": 1, "Region = South": 1, "Region = East": 1}
    assert g.axes.shape == (3,) and g.figure.get_size_inches()[0] < 8  # two to a row


def test_col_with_every_column_and_a_hue(regions, pyplot):
    code = graph_code(regions, block(0, 0, 6, 3), "df", "line", None, x="Month", ys=["Sales", "Cost"], col="Region")
    assert "melt(id_vars=['Month', 'Region'], value_vars=['Sales', 'Cost']" in code  # the panels' categories stay
    g = graph(regions, block(0, 0, 6, 3), "line", "o", x="Month", ys=["Sales", "Cost"], col="Region")
    assert set(panels(g).values()) == {2} and [t.get_text() for t in g.legend.texts] == ["Sales", "Cost"]
    g = graph(regions, block(0, 0, 6, 3), "line", None, x="Sales", ys=["Cost"], hue="Month", col="Region")
    assert set(panels(g).values()) == {2} and [t.get_text() for t in g.legend.texts] == ["Jan", "Feb"]


def test_scatter_chart_with_col(regions, pyplot):
    code = graph_code(regions, block(0, 0, 6, 3), "df", "scatter", "o", x="Sales", ys=["Cost"], col="Region")
    assert "col='Region', col_wrap=2," in code and "kind='scatter'," in code
    assert "marker='o', height=2.5, aspect=1.2," in code
    g = graph(regions, block(0, 0, 6, 3), "scatter", "o", x="Sales", ys=["Cost"], col="Region")
    assert [ax.get_title() for ax in g.axes.flat] == ["Region = North", "Region = South", "Region = East"]
    assert [len(ax.collections[0].get_offsets()) for ax in g.axes.flat] == [2, 2, 2]  # each region's points


def test_categorical_scatter_with_col(regions, pyplot):
    code = graph_code(regions, block(0, 0, 6, 3), "df", "swarm", "D", x="Month", ys=["Sales"], col="Region")
    assert "sns.catplot(" in code and "col='Region', col_wrap=2," in code and "kind='swarm'," in code
    assert "marker='D', height=2.5, aspect=1.2," in code
    g = graph(regions, block(0, 0, 6, 3), "strip", "o", x="Month", ys=["Sales"], col="Region")
    assert [ax.get_title() for ax in g.axes.flat] == ["Region = North", "Region = South", "Region = East"]
    assert [t.get_text() for t in g.axes.flat[-1].get_xticklabels()] == ["Jan", "Feb"]  # (on the bottom row)
    sideways = graph(regions, block(0, 0, 6, 3), "strip", "o", x="Sales", ys=["Month"], col="Region")
    assert [t.get_text() for t in sideways.axes.flat[0].get_yticklabels()] == ["Jan", "Feb"]
    assert len(sideways.axes.flat) == 3


def test_col_isnt_x_or_y(regions):
    cells = block(0, 0, 6, 3)
    for kind, x, col in [("strip", "Month", "Month"), ("strip", "Month", "Cost"),
                         ("line", "Month", "Cost"), ("line", "Region", "Region"), ("line", "Month", "Nope")]:
        with pytest.raises(ValueError):
            graph_code(regions, cells, "df", kind, "o", x=x, ys=["Cost"], col=col)
    columns = graph_columns(regions, cells)
    assert columns.col_options("Month", ["Sales"]) == ["Region", "Cost"]  # any but x and y
    assert columns.col_options("Sales", ["Cost"]) == ["Region", "Month"]
    assert "col=" not in graph_code(regions, cells, "df", "line", None)


@pytest.fixture
def years(app):
    """Sales and Cost by month in two years: A1:D5, and a row without a year in A6:D6."""
    model = SheetModel(rows=20, cols=6)
    rows = [("Year", "Month", "Sales", "Cost"), ("2020", "Jan", "100", "60"), ("2020", "Feb", "120", "70"),
            ("2021", "Jan", "90", "50"), ("2021", "Feb", "95", "55"), ("", "Mar", "130", "80")]
    model.set_cells({(r, c): value for r, row in enumerate(rows) for c, value in enumerate(row)})
    return model


def test_col_of_numbers_such_as_years(years, pyplot):
    code = graph_code(years, block(0, 0, 4, 3), "df", "line", None, x="Month", col="Year")
    assert "melt(id_vars=['Month', 'Year'], value_vars=['Sales', 'Cost']" in code  # All, but the years
    assert "dropna" not in code and "astype" not in code
    g = graph(years, block(0, 0, 4, 3), "line", None, x="Month", col="Year")
    assert panels(g) == {"Year = 2020": 2, "Year = 2021": 2}


def test_col_of_whole_numbers_with_gaps(years, pyplot):
    code = graph_code(years, block(0, 0, 5, 3), "df", "line", None, x="Month", ys=["Sales"], col="Year")
    assert "data = data.dropna(subset=['Year'])  # rows without a 'Year' have no panel" in code
    assert "data['Year'] = data['Year'].astype(int)  # whole numbers: 2020, not 2020.0" in code
    g = graph(years, block(0, 0, 5, 3), "line", None, x="Month", ys=["Sales"], col="Year")
    assert panels(g) == {"Year = 2020": 1, "Year = 2021": 1}
    assert "dropna" not in graph_code(years, block(0, 0, 5, 3), "df", "line", None, x="Year", ys=["Sales"])


def test_linear_regression(regions, pyplot):
    code = graph_code(regions, block(0, 0, 6, 3), "df", "reg", "o", x="Sales", ys=["Cost"])
    assert code.endswith("chart = sns.lmplot(\n    data=df, x='Sales', y='Cost',\n"
                         "    markers='o', height=4, aspect=1.5,\n)")  # lmplot has no kind=
    g = graph(regions, block(0, 0, 6, 3), "reg", "o", x="Sales", ys=["Cost"])
    [points, band] = g.ax.collections
    assert len(points.get_offsets()) == 6 and len(plotted(g)) == 1  # the points, and the line fitted to them
    g = graph(regions, block(0, 0, 6, 3), "reg", "D", x="Sales", ys=["Cost"], hue="Month", col="Region")
    assert len(g.axes.flat) == 3 and [t.get_text() for t in g.legend.texts] == ["Jan", "Feb"]


def test_linear_regression_needs_numbers_across(regions, sales, pyplot):
    with pytest.raises(ValueError):
        graph_code(regions, block(0, 0, 6, 3), "df", "reg", "o", x="Month", ys=["Sales"])
    assert "x='Sales', y='Cost'" in graph_code(regions, block(0, 0, 6, 3), "df", "reg", "o")  # by default
    columns = graph_columns(regions, block(0, 0, 6, 3))
    assert columns.x_options(None, "reg") == ["Sales", "Cost"] and columns.can_regress
    assert not graph_columns(sales, block(0, 0, 3, 1)).can_regress  # Month and Sales: one column of numbers
    code = graph_code(sales, block(0, 0, 3, 2), "df", "reg", "o", x="Cost", ys=["Sales"])
    assert "data['Cost'] = pd.to_numeric(data['Cost'], errors='coerce')" in code and "astype" not in code
    g = graph(sales, block(0, 0, 3, 2), "reg", "o", x="Cost", ys=["Sales"])
    assert len(g.ax.collections[0].get_offsets()) == 2  # n/a isn't charted


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
    assert dialog_state(dialog) == ("line", "Month", ["Sales", "Cost"], None, None)  # All: a line each
    assert [dialog.kind_box.itemText(i) for i in range(3)] == ["Line", "Scatter", "Categorical scatter"]
    assert [dialog.marker_box.itemData(i) for i in range(dialog.marker_box.count())] == list(MARKERS)
    assert [dialog.x_box.itemText(i) for i in range(4)] == ["Month", "Sales", "Cost", "Note"]
    assert [dialog.y_box.itemText(i) for i in range(dialog.y_box.count())] == ["All", "Sales", "Cost"]
    assert not dialog.hue_box.isEnabled()  # each line has its own color
    assert [dialog.hue_box.itemText(i) for i in range(dialog.hue_box.count())] == [
        "None", "Sales", "Cost", "Note"]  # any column but x
    assert not dialog.form.isRowVisible(dialog.swarm_box)  # just for categorical scatters


def test_dialog_starts_with_the_last_choices(app):
    dialog = GraphDialog(None, sales_columns(), "scatter", "D")
    assert dialog_state(dialog) == ("scatter", "Month", ["Sales"], None, "D")
    assert dialog.choice() == GraphChoice("scatter", "D", "Month", ["Sales"], None, frame="df")


def test_choosing_the_axes_and_hue(app):
    dialog = GraphDialog(None, sales_columns())
    dialog.y_box.setCurrentIndex(2)
    dialog.y_box.activated.emit(2)  # as the user's choice is
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


def test_y_axis_as_categories_checkbox(app):
    columns = GraphColumns(["Year", "Sales", "Site"], [True, True, False], [False, False, True])
    dialog = GraphDialog(None, columns, "strip", "o")
    box = dialog.categories_box
    assert dialog.form.isRowVisible(box) and (dialog.x(), dialog.ys()) == ("Site", ["Year"])
    assert not box.isEnabled() and not box.isChecked()  # Site across is the categories
    dialog.x_box.setCurrentIndex(dialog.x_box.findData("Sales"))
    dialog.x_box.activated.emit(dialog.x_box.currentIndex())
    dialog.y_box.setCurrentIndex(dialog.y_box.findData(["Year"]))
    dialog.y_box.activated.emit(dialog.y_box.currentIndex())
    assert box.isEnabled() and not box.isChecked() and items(dialog.x_box) == ["Year", "Sales", "Site"]
    box.setChecked(True)  # the years are the categories, up the side
    assert items(dialog.x_box) == ["Sales"] and dialog.choice().y_categories
    dialog.y_box.setCurrentIndex(dialog.y_box.findData(["Site"]))
    assert box.isChecked() and not box.isEnabled()  # text up is always categories
    dialog.kind_box.setCurrentIndex(1)
    assert not dialog.form.isRowVisible(box) and not dialog.choice().y_categories


def test_all_is_for_line_charts(app):
    dialog = GraphDialog(None, sales_columns())
    dialog.kind_box.setCurrentIndex(1)  # Scatter: one column up
    assert dialog.ys() == ["Sales"] and items(dialog.y_box) == ["Sales", "Cost"]
    assert dialog.hue_box.isEnabled()
    dialog.kind_box.setCurrentIndex(0)  # and Line again: All, as nothing else was chosen
    assert dialog.ys() == ["Sales", "Cost"] and dialog.y_box.currentText() == "All"
    dialog.y_box.setCurrentIndex(2)
    dialog.y_box.activated.emit(2)
    dialog.kind_box.setCurrentIndex(2)
    dialog.kind_box.setCurrentIndex(0)
    assert dialog.ys() == ["Cost"]  # chosen, so it stays
    dialog.y_box.setCurrentIndex(0)
    dialog.y_box.activated.emit(0)  # All, chosen
    dialog.kind_box.setCurrentIndex(1)
    assert dialog.ys() == ["Sales"]  # not for Scatter


def test_no_all_with_one_column_of_numbers(app):
    dialog = GraphDialog(None, GraphColumns(["Month", "Sales", "Note"], [False, True, False], [True, False, True]))
    assert items(dialog.y_box) == ["Sales"] and dialog.ys() == ["Sales"]


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


def region_columns():
    return GraphColumns(["Region", "Month", "Sales", "Cost"], [False, False, True, True], [True, True, False, False])


def test_col_for_line_and_scatter_charts(app):
    dialog = GraphDialog(None, region_columns())
    assert dialog.form.isRowVisible(dialog.col_box) and dialog.col() is None  # None by default
    assert dialog.x() == "Region" and items(dialog.col_box) == ["None", "Month", "Sales", "Cost"]  # any but x
    dialog.x_box.setCurrentIndex(dialog.x_box.findData("Month"))
    dialog.x_box.activated.emit(dialog.x_box.currentIndex())
    assert items(dialog.col_box) == ["None", "Region", "Sales", "Cost"]
    dialog.col_box.setCurrentIndex(1)
    assert dialog.choice() == GraphChoice("line", None, "Month", ["Sales", "Cost"], None, False, "Region", "df")
    dialog.y_box.setCurrentIndex(dialog.y_box.findData(["Cost"]))
    dialog.y_box.activated.emit(dialog.y_box.currentIndex())
    assert dialog.choice().col == "Region"  # whatever's up
    dialog.kind_box.setCurrentIndex(1)  # Scatter: panels too
    assert dialog.form.isRowVisible(dialog.col_box)
    assert dialog.choice() == GraphChoice("scatter", "o", "Month", ["Cost"], None, False, "Region", "df")
    dialog.kind_box.setCurrentIndex(2)  # Categorical scatter: panels too
    assert dialog.form.isRowVisible(dialog.col_box)
    assert dialog.choice() == GraphChoice("strip", "o", "Month", ["Cost"], None, False, "Region", "df")
    dialog.kind_box.setCurrentIndex(0)
    assert dialog.col() == "Region"
    assert items(dialog.col_box) == ["None", "Region", "Sales"]  # not Cost, up
    dialog.x_box.setCurrentIndex(dialog.x_box.findData("Region"))  # Region across can't split it too
    assert dialog.col() is None and items(dialog.col_box) == ["None", "Month", "Sales"]


def test_col_of_numbers_isnt_one_of_alls_lines(app):
    columns = GraphColumns(["Year", "Month", "Sales", "Cost"], [True, False, True, True], [False, True, False, False])
    dialog = GraphDialog(None, columns)
    dialog.x_box.setCurrentIndex(dialog.x_box.findData("Month"))
    dialog.x_box.activated.emit(dialog.x_box.currentIndex())
    assert dialog.ys() == ["Year", "Sales", "Cost"] and items(dialog.col_box) == ["None", "Year", "Sales", "Cost"]
    dialog.col_box.setCurrentIndex(dialog.col_box.findData("Year"))
    assert dialog.y_box.currentText() == "All" and dialog.ys() == ["Sales", "Cost"]  # a panel for each year
    assert dialog.choice() == GraphChoice("line", None, "Month", ["Sales", "Cost"], None, False, "Year", "df")
    assert items(dialog.y_box) == ["All", "Year", "Sales", "Cost"]
    dialog.col_box.setCurrentIndex(0)
    assert dialog.y_box.currentText() == "All" and dialog.ys() == ["Year", "Sales", "Cost"]
    dialog.y_box.activated.emit(0)  # All, chosen: it still follows the col
    dialog.col_box.setCurrentIndex(dialog.col_box.findData("Year"))
    assert dialog.ys() == ["Sales", "Cost"]
    dialog.y_box.setCurrentIndex(dialog.y_box.findData(["Year"]))  # the years up: no panels of them
    assert (dialog.ys(), dialog.col()) == (["Year"], None) and dialog.y_box.itemData(0) == ["Year", "Sales", "Cost"]


def test_linear_regression_checkbox(app):
    dialog = GraphDialog(None, region_columns())
    assert not dialog.form.isRowVisible(dialog.regression_box)  # just for Scatter
    dialog.kind_box.setCurrentIndex(1)
    assert dialog.form.isRowVisible(dialog.regression_box) and not dialog.regression_box.isChecked()
    assert (dialog.kind(), dialog.x()) == ("scatter", "Region")
    dialog.regression_box.setChecked(True)
    assert (dialog.kind(), dialog.x(), dialog.ys(), dialog.marker()) == ("reg", "Sales", ["Cost"], "o")
    assert items(dialog.x_box) == ["Sales", "Cost"]  # numbers across, to fit a line to
    assert dialog.choice() == GraphChoice("reg", "o", "Sales", ["Cost"], None, False, None, "df")
    dialog.regression_box.setChecked(False)
    assert (dialog.kind(), dialog.x()) == ("scatter", "Region")  # it follows the type again
    dialog.kind_box.setCurrentIndex(2)
    assert not dialog.form.isRowVisible(dialog.regression_box) and dialog.kind() == "strip"


def test_linear_regression_takes_numbers_across(app):
    dialog = GraphDialog(None, region_columns(), "scatter", "o")
    dialog.x_box.setCurrentIndex(dialog.x_box.findData("Month"))
    dialog.x_box.activated.emit(dialog.x_box.currentIndex())
    dialog.hue_box.setCurrentIndex(dialog.hue_box.findData("Sales"))
    dialog.col_box.setCurrentIndex(dialog.col_box.findData("Region"))
    dialog.regression_box.setChecked(True)
    assert (dialog.x(), dialog.ys(), dialog.hue(), dialog.col()) == ("Sales", ["Cost"], None, "Region")
    assert items(dialog.hue_box) == ["None", "Region", "Month", "Cost"]  # any but x


def test_linear_regression_needs_two_columns_of_numbers(app):
    columns = GraphColumns(["Month", "Sales"], [False, True], [True, False])
    dialog = GraphDialog(None, columns, "reg", "o")  # the last choice
    assert dialog.kind() == "scatter" and not dialog.regression_box.isEnabled()
    assert "two columns with numbers" in dialog.regression_box.toolTip()
    remembered = GraphDialog(None, region_columns(), "reg", "D")
    assert remembered.kind_box.currentText() == "Scatter" and remembered.regression_box.isChecked()
    assert (remembered.kind(), remembered.x(), remembered.marker()) == ("reg", "Sales", "D")


def test_categorical_scatter_across_isnt_the_col(app):
    columns = GraphColumns(["Year", "Site", "Region", "Sales"], [True, False, False, True], [False, True, True, False])
    dialog = GraphDialog(None, columns)  # Year across, a line chart
    dialog.col_box.setCurrentIndex(dialog.col_box.findData("Site"))
    dialog.kind_box.setCurrentIndex(2)
    assert (dialog.x(), dialog.col()) == ("Region", "Site")  # the first column of text but the col


def test_scatter_with_a_col_of_numbers_has_another_y(app):
    columns = GraphColumns(["Region", "Year", "Sales"], [False, True, True], [True, False, False])
    dialog = GraphDialog(None, columns)
    dialog.col_box.setCurrentIndex(dialog.col_box.findData("Year"))
    assert dialog.ys() == ["Sales"]  # All, but the years
    dialog.kind_box.setCurrentIndex(1)
    assert (dialog.ys(), dialog.col()) == (["Sales"], "Year")  # not the years, the first after Region


def test_col_of_the_only_other_column_of_numbers(app):
    columns = GraphColumns(["Month", "Year", "Sales"], [False, True, True], [True, False, False])
    dialog = GraphDialog(None, columns)
    assert dialog.y_box.currentText() == "All"
    dialog.col_box.setCurrentIndex(dialog.col_box.findData("Year"))
    assert (dialog.ys(), dialog.col()) == (["Sales"], "Year") and items(dialog.y_box) == ["Year", "Sales"]
    dialog.col_box.setCurrentIndex(0)
    assert (dialog.ys(), dialog.col()) == (["Sales"], None)  # Sales was chosen for it; it stays


def test_no_col_without_another_column(app):
    dialog = GraphDialog(None, sales_columns())
    assert items(dialog.col_box) == ["None", "Sales", "Cost", "Note"] and dialog.col_box.isEnabled()
    dialog = GraphDialog(None, GraphColumns(["Month", "Sales"], [False, True], [True, False]))
    assert items(dialog.col_box) == ["None"] and not dialog.col_box.isEnabled()
    assert "no column, besides the X and Y" in dialog.col_box.toolTip()


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
    assert graph.startswith("# df as a chart") and "pd.to_numeric" not in graph  # Sales is all numbers
    sheet.set_cell(2, 1, "n/a")
    assert graph_code(sheet, cells, "df", import_pandas=False, import_seaborn=False).startswith("# df as a chart")
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
    evaluated = Signal(str, object, str)
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

    def evaluate(self, request_id, code, expression):
        self.questions = getattr(self, "questions", 0) + 1
        self.evaluated.emit(request_id, None, "FakeKernel doesn't evaluate.")  # (so just the cells' DataFrames)

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
    assert [a.text() for a in insert.actions()] == ["Sheet", "Pivot Table…", "", "Notebook"]  # charts are made in the notebook
    for menu in (window.notebook_button.menu(), notebook_submenu(insert), notebook_submenu(window.context_menu)):
        actions = menu.actions()
        assert [actions[0], actions[2], actions[3], actions[5]] == [
            window.open_notebook_action, window.dataframe_action, window.graph_action, window.load_data_action]
        assert [action.text() for action in actions] == ["Open", "", "DataFrame", "Chart", "",
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
    assert "chart = sns.relplot(" in graph_cell.source and "x='Month', y='Sales'" in graph_cell.source
    assert graph_cell.source.startswith("# df as a chart") and "import" not in graph_cell.source
    assert window.notebook_window.isVisible()
    assert "as df, with a chart" in window.statusBar().currentMessage()
    assert "kind='line'" in graph_cell.source and "marker" not in graph_cell.source
    dialogs.graph_change_answer = ("new", "scatter", "s")  # now there's a chart, New chart in the list
    window.view.select_range(0, 0, 3, 1)
    window.graph_action.trigger()
    source = window.notebook.cells[-1].source
    assert "df2 as a chart" in source and "kind='scatter'" in source and "marker='s'" in source
    assert dialogs.graph_change_prompts[-1][1] is None  # cells selected: it starts at New chart
    assert (window.graph_kind, window.graph_marker) == ("scatter", "s")  # where new ones start next time


def test_cancelling_the_graph_dialog(window, dialogs):
    dialogs.graph_answer = None
    window.view.select_range(0, 0, 3, 1)
    assert window.send_graph_to_notebook() is None
    assert window.notebook.is_empty and window.notebook_window is None
    assert (window.graph_kind, window.graph_marker) == ("line", None)


@pytest.mark.parametrize("selection, problem", [
    ((0, 2, 3, 3), "no numbers"),  # C and D, but D is empty
    ((0, 0, 3, 2), None),  # Sales has numbers, so Note's text just isn't charted
    ((10, 0, 12, 2), "The selection is empty."),
    ((0, 0, 3, 0), "no numbers"),  # one column, of text
])
def test_graph_problems(window, dialogs, selection, problem):
    if problem is None:
        window.view.select_range(*selection)
        assert window.send_graph_to_notebook() is not None
        return
    window.view.select_range(*selection)
    assert window.send_graph_to_notebook() is None
    assert problem in dialogs.errors[-1]  # an error, before any dialog
    assert window.notebook.is_empty and window.notebook_window is None
    assert dialogs.graph_prompts == []


def test_graph_needs_numbers(window, dialogs):
    window.model.set_cells({(1, 1): "x", (2, 1): "y", (3, 1): ""})
    window.view.select_range(0, 0, 3, 1)
    assert window.send_graph_to_notebook() is None
    assert dialogs.errors == ["There are no numbers to chart."]


# --- Changing a graph (Graph with no data selected) ---

def make_graph(window, dialogs, columns=1) -> str:
    """A new chart of A1:B4 (or more columns): its cell's id. The notebook is shown."""
    window.view.select_range(0, 0, 3, columns)
    saved, dialogs.graph_change_answer = dialogs.graph_change_answer, ("new", *dialogs.graph_answer)
    graph_id = window.send_graph_to_notebook()  # (New chart in the list, once there are charts)
    dialogs.graph_change_answer = saved
    return graph_id


def test_whole_sheet_when_one_cell_is_selected(window, dialogs):
    window.view.select_range(2, 2, 2, 2)
    graph_id = window.send_graph_to_notebook()
    assert dialogs.graph_prompts == [(["Month", "Sales", "Note"], ("line", None))]  # all of A1:C4
    assert window.notebook.cells[1].source.startswith("# Cells A1:C4 of the sheet")
    assert "Sent the whole sheet, A1:C4 to the notebook as df" in window.statusBar().currentMessage()
    assert graph_id == window.notebook.cells[2].id


@pytest.mark.parametrize("cells, problem", [
    ({}, "The sheet is empty."),
    ({(0, 0): "a", (0, 1): "b"}, "There are no numbers to chart."),
])
def test_whole_sheet_that_cant_be_charted(app, dialogs, cells, problem):
    window = MainWindow()
    window.kernel = FakeKernel()
    window.model.set_cells(cells)
    assert window.send_graph_to_notebook() is None
    assert dialogs.errors == [problem] and dialogs.graph_prompts == []
    window.setWindowModified(False)
    window.close()


def test_new_chart_from_the_list(window, dialogs):
    make_graph(window, dialogs)
    window.view.select_range(0, 0, 3, 2)
    dialogs.graph_change_answer = ("new", "scatter", "o")
    graph_id = window.send_graph_to_notebook()
    assert dialogs.graph_change_prompts[-1][1] is None  # several cells selected: New chart first
    assert dialogs.chart_prompts[-1][1:] == ("the selected cells, A1:C4", None)
    assert "df2 as a chart" in window.notebook.cell(graph_id).source
    window.view.select_range(10, 1, 10, 1)  # one cell: the whole sheet
    window.send_graph_to_notebook()
    assert dialogs.chart_prompts[-1][1:] == ("the whole sheet, A1:C4", None)
    assert dialogs.graph_change_prompts[-1][1] == 1  # the newest chart first
    assert "df3 as a chart" in window.notebook.cells[-1].source


def test_list_when_a_new_chart_cant_be_made(window, dialogs):
    graph_id = make_graph(window, dialogs)
    window.view.select_range(10, 0, 12, 2)  # empty
    dialogs.graph_change_answer = ("new", "line", None)
    assert window.send_graph_to_notebook() is None  # no OK for New chart
    assert dialogs.chart_prompts[-1][2] == "The selection is empty." and not dialogs.errors
    dialogs.graph_change_answer = (0, "scatter", "o")  # but a chart can still be changed
    assert window.send_graph_to_notebook() == graph_id


def test_change_a_graph(window, dialogs):
    graph_id = make_graph(window, dialogs)
    runs = len(window.kernel.runs)
    window.view.select_range(10, 0, 10, 0)  # one cell: the list starts at the newest chart
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
    assert "Redrawing the chart df: Sales against Month" in window.statusBar().currentMessage()
    nb.widgets[graph_id].editor.undo()  # the change is an edit in the cell, so Undo there reverts it
    assert "kind='line'" in window.notebook.cell(graph_id).source


@pytest.mark.parametrize("new_process", [
    lambda window: window.notebook_window.restart(),  # asked for, so before the new process even starts
    lambda window: window.kernel.state_changed.emit("starting"),  # as after Python crashed
])
def test_dataframe_made_again_after_a_restart(window, dialogs, new_process):
    graph_id = make_graph(window, dialogs)
    imports_id, frame_id = (cell.id for cell in window.notebook.cells[:2])
    new_process(window)  # pd, sns, and df are gone
    runs = len(window.kernel.runs)
    window.view.select_range(10, 0, 12, 2)
    dialogs.graph_change_answer = (0, "line", "o")
    window.send_graph_to_notebook()
    assert [run[0] for run in window.kernel.runs[runs:]] == [imports_id, frame_id, graph_id]


def test_dataframe_made_again_in_a_reopened_sheet(window, dialogs, tmp_path):
    make_graph(window, dialogs)
    window.save_to(str(tmp_path / "s.ezs"))
    window.open_path(str(tmp_path / "s.ezs"))
    imports_id, frame_id, graph_id = (cell.id for cell in window.notebook.cells)
    runs = len(window.kernel.runs)
    window.view.select_range(10, 0, 12, 2)
    dialogs.graph_change_answer = (0, "scatter", None)
    window.send_graph_to_notebook()
    assert [run[0] for run in window.kernel.runs[runs:]] == [imports_id, frame_id, graph_id]


def test_starts_with_the_current_graph(window, dialogs):
    first = make_graph(window, dialogs)
    make_graph(window, dialogs, columns=2)
    window.notebook_window.set_current(first)
    window.view.select_range(10, 0, 10, 0)
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
def test_charts_offered_whatever_the_selection(window, dialogs, selection):
    graph_id = make_graph(window, dialogs)
    cells_before = len(window.notebook.cells)
    window.view.select_range(*selection)
    dialogs.graph_change_answer = (0, "scatter", "x")
    assert window.send_graph_to_notebook() == graph_id
    several = selection[:2] != selection[2:]
    assert dialogs.graph_change_prompts[-1][1] == (None if several else 0)  # New chart, or the chart
    assert dialogs.graph_prompts == [(["Month", "Sales"], ("line", None))]  # only the first graph's
    assert len(dialogs.graph_change_prompts) == 1 and len(window.notebook.cells) == cells_before
    assert "marker='x'" in window.notebook.cell(graph_id).source


def test_change_a_graphs_columns(window, dialogs):
    graph_id = make_graph(window, dialogs, columns=2)  # Month, Sales, Note
    window.view.select_range(10, 0, 12, 2)
    dialogs.graph_change_answer = (0, "strip", "D", "Month", ["Sales"])
    window.send_graph_to_notebook()
    [(graphs, _)] = dialogs.graph_change_prompts
    assert graphs[0].columns.labels == ["Month", "Sales", "Note"]  # from the DataFrame's cell
    source = window.notebook.cell(graph_id).source
    assert source == graph_code(window.model, block(0, 0, 3, 2), "df", "strip", "D", x="Month", ys=["Sales"],
                                import_pandas=False, import_seaborn=False)
    assert window.kernel.runs[-1][0] == graph_id


def test_linear_regression_chart(window, dialogs):
    window.model.set_cells({(0, 3): "Cost", (1, 3): "800", (2, 3): "950", (3, 3): "990"})
    window.view.select_range(0, 0, 3, 3)  # Month, Sales, Note, Cost
    dialogs.graph_answer = ("reg", "D", "Sales", ["Cost"])
    graph_id = window.send_graph_to_notebook()
    source = window.notebook.cell(graph_id).source
    assert "sns.lmplot(" in source and "markers='D', height=4" in source and "kind=" not in source
    assert window.graph_kind == "reg"  # remembered for next time
    dialogs.graph_change_answer = (0, "scatter", "D")  # without the line: just the code's call changes
    window.send_graph_to_notebook()
    assert dialogs.graph_change_prompts[0][0][0].kind == "reg"
    source = window.notebook.cell(graph_id).source
    assert "sns.relplot(" in source and "kind='scatter',  # or 'line'" in source and "marker='D'," in source


def test_swarm_graph_with_hue(window, dialogs):
    window.view.select_range(0, 0, 3, 2)  # Month, Sales, Note
    dialogs.graph_answer = ("swarm", "D", "Month", ["Sales"], "Note")
    graph_id = window.send_graph_to_notebook()
    source = window.notebook.cell(graph_id).source
    assert "sns.catplot(" in source and "x='Month', y='Sales', hue='Note'" in source and "kind='swarm'" in source
    assert (window.graph_kind, window.graph_marker) == ("swarm", "D")  # remembered for next time


def test_change_a_graphs_hue(window, dialogs):
    graph_id = make_graph(window, dialogs, columns=2)
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


def test_new_chart_with_col(window, dialogs):
    window.view.select_range(0, 0, 3, 2)  # Month, Sales, Note
    dialogs.graph_answer = ("line", None, "Month", ["Sales"], None, False, "Note")
    graph_id = window.send_graph_to_notebook()
    source = window.notebook.cell(graph_id).source
    assert "col='Note', col_wrap=2," in source and "kind='line'" in source


def test_change_a_graphs_col(window, dialogs):
    graph_id = make_graph(window, dialogs, columns=2)  # Month, Sales, Note
    window.view.select_range(10, 0, 12, 2)
    dialogs.graph_change_answer = (0, "line", "o", "Month", ["Sales"], None, False, "Note")
    window.send_graph_to_notebook()
    source = window.notebook.cell(graph_id).source
    assert source == graph_code(window.model, block(0, 0, 3, 2), "df", "line", "o", x="Month", ys=["Sales"],
                                col="Note", import_pandas=False, import_seaborn=False)
    dialogs.graph_change_answer = (0, "line", None)  # the marker alone: the panels stay, read from the code
    window.send_graph_to_notebook()
    assert dialogs.graph_change_prompts[1][0][0].col == "Note"
    assert "col='Note'" in window.notebook.cell(graph_id).source
    dialogs.graph_change_answer = (0, "scatter", "o")  # Scatter has panels too: just the kind changes
    window.send_graph_to_notebook()
    source = window.notebook.cell(graph_id).source
    assert "col='Note', col_wrap=2," in source and "kind='scatter',  # or 'line'" in source
    assert "marker='o', height=2.5, aspect=1.2," in source
    dialogs.graph_change_answer = (0, "strip", "o")  # and a categorical scatter
    window.send_graph_to_notebook()
    source = window.notebook.cell(graph_id).source
    assert "col='Note', col_wrap=2," in source and "sns.catplot(" in source and "kind='strip',  # or 'swarm'" in source
    dialogs.graph_change_answer = (0, "strip", "o", "Month", ["Sales"], None, False, None)  # no panels
    window.send_graph_to_notebook()
    source = window.notebook.cell(graph_id).source
    assert "col=" not in source and "height=4, aspect=1.5" in source


def test_change_a_graph_to_sideways(window, dialogs):
    graph_id = make_graph(window, dialogs, columns=2)  # Month, Sales, Note
    window.view.select_range(10, 0, 12, 2)
    dialogs.graph_change_answer = (0, "strip", "o", "Sales", ["Note"])
    window.send_graph_to_notebook()
    source = window.notebook.cell(graph_id).source
    assert "sns.catplot(" in source and "x='Sales', y='Note'" in source


def test_years_up_as_categories(window, dialogs):
    window.model.set_cells({(0, 0): "Year", (0, 1): "Sales", (1, 0): "2021", (1, 1): "5", (2, 0): "2020",
                            (2, 1): "3", (3, 0): "2021", (3, 1): "4"})
    window.view.select_range(0, 0, 3, 1)
    dialogs.graph_answer = ("swarm", "o", "Sales", ["Year"], None, True)
    graph_id = window.send_graph_to_notebook()
    assert "x='Sales', y='Year', orient='h'" in window.notebook.cell(graph_id).source
    window.view.select_range(10, 0, 12, 2)
    dialogs.graph_change_answer = (0, "swarm", "o", "Sales", ["Year"], None, False)  # upright again
    window.send_graph_to_notebook()
    [(graphs, _)] = dialogs.graph_change_prompts
    assert graphs[0].y_categories
    assert "orient" not in window.notebook.cell(graph_id).source


def test_type_change_keeps_hand_edits(window, dialogs):
    graph_id = make_graph(window, dialogs)
    nb = window.notebook_window
    nb.replace_source(graph_id, window.notebook.cell(graph_id).source.replace("height=4", "height=7"))
    window.view.select_range(10, 0, 12, 2)
    dialogs.graph_change_answer = (0, "strip", "o")  # same columns
    window.send_graph_to_notebook()
    source = window.notebook.cell(graph_id).source
    assert "sns.catplot(" in source and "height=7" in source


def in_view(nb, widget) -> bool:
    """Whether a cell (or part of one) is wholly in the notebook's visible area."""
    top = widget.mapTo(nb.cell_area, QPoint(0, 0)).y()
    shown = nb.scroll.verticalScrollBar().value()
    return shown <= top and top + widget.height() <= shown + nb.scroll.viewport().height()


def tall_notebook(window):
    nb = window.show_notebook()
    nb.resize(820, 600)
    for number in range(12):
        nb.add_cell_below("\n".join(f"x{number} = {line}" for line in range(8)))
    QApplication.processEvents()
    return nb


def test_new_chart_scrolled_into_view(window, dialogs):
    nb = tall_notebook(window)
    nb.scroll.verticalScrollBar().setValue(0)
    graph_id = make_graph(window, dialogs)
    widget = nb.widgets[graph_id]
    assert wait_for(lambda: in_view(nb, widget), timeout=2)
    assert not widget.output_view.isHidden() and in_view(nb, widget.output_view)


def test_changed_chart_scrolled_into_view(window, dialogs):
    graph_id = make_graph(window, dialogs)
    nb = tall_notebook(window)  # more cells after the chart
    bar = nb.scroll.verticalScrollBar()
    assert wait_for(lambda: bar.maximum() > 0, timeout=2)
    QTest.qWait(400)  # the chart's own reveal is over
    bar.setValue(bar.maximum())
    assert not in_view(nb, nb.widgets[graph_id])
    window.view.select_range(10, 0, 10, 0)
    dialogs.graph_change_answer = (0, "scatter", "o")
    window.send_graph_to_notebook()
    assert wait_for(lambda: in_view(nb, nb.widgets[graph_id].output_view), timeout=2)


def test_scrolling_is_the_users_again_afterwards(window, dialogs):
    nb = tall_notebook(window)
    graph_id = make_graph(window, dialogs)
    assert wait_for(lambda: in_view(nb, nb.widgets[graph_id]), timeout=2)
    QTest.qWait(400)
    bar = nb.scroll.verticalScrollBar()
    bar.setValue(0)
    nb.notebook.add_output(graph_id, {"output_type": "stream", "name": "stdout", "text": "more\n"})
    QTest.qWait(200)
    assert bar.value() == 0  # not pulled back to the chart


def test_cancel_changes_nothing(window, dialogs):
    graph_id = make_graph(window, dialogs)
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
    from ezsheet.appearance import next_zoom
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
        for answer in (("strip", "o", "Width", ["Species"]),  # sideways: text up
                       ("swarm", "o", "Width", ["Width2"], None, True)):  # and numbers up as categories
            window.model.set_cells({(0, 3): "Width2", (1, 3): "1", (2, 3): "2", (3, 3): "1"})
            dialogs.graph_change_answer = ("new", *answer)  # there are charts now: New chart in the list
            window.view.select_range(0, 0, 3, 3)
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


def test_real_kernel_chart_comes_into_view(app, sheet, dialogs):
    window = MainWindow()
    window.model.set_cells({key: sheet.get_cell(*key) for key in block(0, 0, 3, 2)})
    try:
        nb = tall_notebook(window)
        nb.scroll.verticalScrollBar().setValue(0)
        window.view.select_range(0, 0, 3, 1)
        cells = len(window.notebook.cells)
        window.send_graph_to_notebook()  # (the notebook has code of its own: Python's asked about it first)
        assert wait_for(lambda: len(window.notebook.cells) == cells + 2)
        graph_id = window.notebook.cells[-1].id
        assert wait_for(lambda: graph_id not in nb.running and window.notebook.cell(graph_id).outputs)
        widget = nb.widgets[graph_id]
        assert wait_for(lambda: in_view(nb, widget.output_view), timeout=5)  # the drawn chart
    finally:
        window.notebook_window.hide()
        window.setWindowModified(False)
        window.close()


def test_real_kernel_errors_interrupt_and_restart(app):
    from ezsheet.kernel import KernelRunner
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
