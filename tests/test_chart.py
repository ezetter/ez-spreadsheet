import math

import numpy as np
import pytest
from PySide6.QtWidgets import QToolBar

from py_spread.chart import ChartError, chart_data
from py_spread.model import SheetModel
from py_spread.storage import SheetData, save_sheet
from py_spread.window import MainWindow


def sheet(app, rows, top=0, left=0):
    model = SheetModel(rows=30, cols=10)
    model.set_cells({(top + r, left + c): v for r, row in enumerate(rows) for c, v in enumerate(row)})
    return model


def block(top, left, bottom, right):
    return {(r, c) for r in range(top, bottom + 1) for c in range(left, right + 1)}


def same(a, b):
    return np.allclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float), equal_nan=True)


# --- Chart data ---

def test_header_names_series(app):
    model = sheet(app, [["t", "a", "b"], ["1", "2", "3"], ["2", "4", "6"]])
    data = chart_data(model, block(0, 0, 2, 2))
    assert data.x_label == "t"
    assert data.x == [1.0, 2.0] and not data.categorical
    assert [name for name, _ in data.series] == ["a", "b"]
    assert same(data.series[1][1], [3, 6])


def test_no_header(app):
    model = sheet(app, [["1", "2", "3"], ["2", "4", "6"]], left=2)
    data = chart_data(model, block(0, 2, 1, 4))
    assert data.x_label == ""
    assert [name for name, _ in data.series] == ["Column D", "Column E"]


def test_text_x_is_categories(app):
    model = sheet(app, [["Month", "Sales"], ["Jan", "$1,200"], ["Feb", "1,450"]])
    data = chart_data(model, block(0, 0, 2, 1))
    assert data.categorical and data.x == ["Jan", "Feb"]
    assert same(data.series[0][1], [1200, 1450])


def test_gaps_and_formulas(app):
    model = sheet(app, [["1", "10"], ["2", ""], ["3", "n/a"], ["4", "=B1*2"], ["5", "=1/0"]])
    data = chart_data(model, block(0, 0, 4, 1))
    assert same(data.series[0][1], [10, math.nan, math.nan, 20, math.nan])


def test_rows_without_x_are_left_out(app):
    model = sheet(app, [["1", "10"], ["", "15"], ["3", "30"]])
    data = chart_data(model, block(0, 0, 2, 1))
    assert data.x == [1.0, 3.0]
    assert same(data.series[0][1], [10, 30])


def test_scattered_columns(app):
    model = sheet(app, [["1", "skip", "5"], ["2", "skip", "7"]])
    data = chart_data(model, block(0, 0, 1, 0) | block(0, 2, 1, 2))
    assert len(data.series) == 1 and same(data.series[0][1], [5, 7])


@pytest.mark.parametrize("rows, cells, message", [
    ([["1"], ["2"]], block(0, 0, 1, 0), "at least two columns"),
    ([["x", "y"]], block(0, 0, 0, 1), "rows of data"),
    ([["1", "a"], ["2", "b"]], block(0, 0, 1, 1), "no numbers"),
])
def test_cannot_chart(app, rows, cells, message):
    with pytest.raises(ChartError, match=message):
        chart_data(sheet(app, rows), cells)


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    yield window
    window.close_charts()
    window.setWindowModified(False)
    window.close()


def fill(window, rows):
    window.model.set_cells({(r, c): v for r, row in enumerate(rows) for c, v in enumerate(row)})


DATA = [["x", "up", "down"], ["1", "1", "9"], ["2", "4", "8"], ["3", "9", "7"]]


def test_line_chart(window):
    fill(window, DATA)
    window.view.select_range(0, 0, 3, 2)
    chart = window.make_chart()
    assert chart.windowTitle() == "Line Chart of A1:C4"
    lines = chart.axes.get_lines()
    assert [line.get_label() for line in lines] == ["up", "down"]
    assert same(lines[0].get_xdata(), [1, 2, 3]) and same(lines[0].get_ydata(), [1, 4, 9])
    assert chart.axes.get_xlabel() == "x"
    assert chart.axes.get_legend() is not None


def test_scatter_chart(window):
    fill(window, DATA)
    window.view.select_range(0, 0, 3, 1)
    chart = window.make_chart()
    chart.kind_box.setCurrentIndex(1)
    assert chart.windowTitle() == "Scatter Chart of A1:B4"
    assert chart.axes.get_lines() == []
    points = chart.axes.collections[0].get_offsets()
    assert same(points, [[1, 1], [2, 4], [3, 9]])
    assert chart.axes.get_ylabel() == "up"  # one series: named on the axis, no legend
    assert chart.axes.get_legend() is None


def test_switching_chart_type(window):
    fill(window, DATA)
    window.view.select_range(0, 0, 3, 2)
    chart = window.make_chart()
    chart.kind_box.setCurrentIndex(1)
    assert chart.kind == "scatter"
    assert len(chart.axes.collections) == 2 and chart.axes.get_lines() == []
    assert chart.windowTitle().startswith("Scatter Chart")


def test_chart_follows_edits(window):
    fill(window, DATA)
    window.view.select_range(0, 0, 3, 1)
    chart = window.make_chart()
    window.model.set_cell(2, 1, "100")
    assert same(chart.axes.get_lines()[0].get_ydata(), [1, 100, 9])
    window.model.set_cells({(r, 1): "" for r in range(1, 4)})
    assert "no numbers" in chart.problem.text()
    window.model.undo_stack.undo()
    assert chart.problem.text() == ""


def test_chart_button_and_menu(window):
    fill(window, DATA)
    toolbar = window.findChild(QToolBar)
    assert toolbar.widgetForAction(toolbar.actions()[2]) is window.chart_button
    assert window.chart_button.text() == "Chart"
    assert window.chart_button.menu() is None  # no line/scatter choice on the toolbar
    insert = [m for m in window.menuBar().actions() if m.text() == "Insert"][0].menu()
    assert [a.text() for a in insert.actions()] == ["Chart"]
    window.view.select_range(0, 0, 3, 1)
    window.chart_button.click()
    insert.actions()[0].trigger()
    assert [c.kind for c in window.charts] == ["line", "line"]  # always starts as a line chart


def test_chart_toolbar_has_no_subplots_button(window):
    from py_spread.chart import ChartToolbar
    fill(window, DATA)
    window.view.select_range(0, 0, 3, 1)
    chart = window.make_chart()
    toolbar = chart.findChild(ChartToolbar)
    tips = [a.toolTip() for a in toolbar.actions()]
    assert not any("subplot" in tip.lower() for tip in tips)
    assert any("zoom" in tip.lower() for tip in tips) and any("save" in tip.lower() for tip in tips)


def test_cannot_chart_shows_why(window):
    window.view.select_range(0, 0, 3, 0)
    assert window.make_chart() is None
    assert window.charts == []
    assert "at least two columns" in window.statusBar().currentMessage()


def test_opening_a_sheet_closes_charts(window, tmp_path, app):
    fill(window, DATA)
    window.view.select_range(0, 0, 3, 1)
    window.make_chart()
    path = str(tmp_path / "s.ezs")
    save_sheet(path, SheetData(10, 5))
    window.setWindowModified(False)
    window.open_path(path)
    app.processEvents()
    assert window.charts == []
