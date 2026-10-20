import json

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication

from ezsheet.errors import CellError
from ezsheet.filtering import ColumnFilter
from ezsheet.numformat import NumberFormat
from ezsheet.pivot import FUNCTION_NAMES, Pivot, from_json, layout, to_json
from ezsheet.pivot_dialog import PivotDialog, describe
from ezsheet.storage import SheetFileError, load_workbook, save_workbook
from ezsheet.window import MainWindow
from ezsheet.workbook import WorkbookModel

DATA = [
    ("Region", "Month", "Sales", "Units"),
    ("East", "Jan", "1200", "3"),
    ("West", "Jan", "900", "2"),
    ("East", "Feb", "1500", "5"),
    ("West", "Feb", "700", "1"),
    ("East", "Jan", "100", "1"),
]


def fill(model, rows=DATA, top=0, left=0):
    model.set_cells({(top + r, left + c): v for r, row in enumerate(rows) for c, v in enumerate(row)})


@pytest.fixture
def book(app):
    book = WorkbookModel(rows=40, cols=15)
    fill(book)
    return book


def pivot(**fields):
    defaults = {"row": 0, "col": 6, "source": "Sheet1", "block": (0, 0, 5, 3), "rows": (0,), "values": ((2, "SUM"),)}
    return Pivot(**{**defaults, **fields})


def grid(cells) -> list[list[str]]:
    """A layout as rows of what's shown ("" where nothing is)."""
    height = max(r for r, _ in cells) + 1
    width = max(c for _, c in cells) + 1
    return [[str(cells[(r, c)].value) if (r, c) in cells else "" for c in range(width)] for r in range(height)]


def shown(model, top, left, height, width) -> list[list[str]]:
    return [[model.display_text(r, c) for c in range(left, left + width)] for r in range(top, top + height)]


# --- What it shows ---

def test_rows_and_a_value(book):
    cells = layout(pivot(), book)
    assert grid(cells) == [["Region", "SUM of Sales"], ["East", "2800.0"], ["West", "1600.0"],
                           ["Sum", "4400.0"]]
    assert cells[(0, 0)].bold and not cells[(1, 0)].bold and cells[(3, 1)].bold  # headers and totals


def test_every_aggregate(book):
    values = tuple((2, function) for function in FUNCTION_NAMES)
    assert FUNCTION_NAMES == ("SUM", "MEAN", "MEDIAN", "MIN", "MAX", "STDDEV", "COUNT", "COUNTA")
    cells = layout(pivot(rows=(1,), values=values), book)
    assert grid(cells)[0] == ["Month", "SUM of Sales", "MEAN of Sales", "MEDIAN of Sales", "MIN of Sales",
                              "MAX of Sales", "STDDEV of Sales", "COUNT of Sales", "COUNTA of Sales"]
    feb = [cells[(1, c)].value for c in range(1, 9)]
    assert feb[:5] == [2200.0, 1100.0, 1100.0, 700.0, 1500.0] and round(feb[5], 3) == 565.685
    assert feb[6:] == [2.0, 2.0]


def test_counting_a_text_column(book):
    cells = layout(pivot(rows=(1,), values=((0, "COUNT"), (0, "COUNTA"))), book)
    assert grid(cells) == [["Month", "COUNT of Region", "COUNTA of Region"], ["Feb", "0.0", "2.0"],
                           ["Jan", "0.0", "3.0"], ["Count / CountA", "0.0", "5.0"]]


def test_counts_arent_in_their_columns_format(book):
    book.set_formats({(row, 2): NumberFormat("currency") for row in range(1, 6)}, "Currency")
    book.set_pivots([pivot(values=((2, "SUM"), (2, "COUNT"), (2, "MAX")))], "Add Pivot Table")
    assert shown(book, 1, 7, 1, 3) == [["$2,800.00", "3", "$1,500.00"]]


def test_columns(book):
    cells = layout(pivot(column=1), book)
    assert grid(cells) == [["SUM of Sales", "Month", "", ""],
                           ["Region", "Feb", "Jan", "Sum"],
                           ["East", "1500.0", "1300.0", "2800.0"],
                           ["West", "700.0", "900.0", "1600.0"],
                           ["Sum", "2200.0", "2200.0", "4400.0"]]


def test_columns_with_several_values(book):
    cells = layout(pivot(column=1, values=((2, "SUM"), (3, "MEAN")), totals=False), book)
    assert grid(cells) == [["Month", "Feb", "", "Jan", ""],
                           ["Region", "SUM of Sales", "MEAN of Units", "SUM of Sales", "MEAN of Units"],
                           ["East", "1500.0", "5.0", "1300.0", "2.0"],
                           ["West", "700.0", "1.0", "900.0", "2.0"]]


def test_totals_are_named_for_their_function(book):
    assert grid(layout(pivot(values=((2, "MAX"),)), book))[-1] == ["Max", "1500.0"]
    cells = layout(pivot(column=1, values=((2, "SUM"), (3, "MEAN"), (2, "SUM"))), book)
    assert grid(cells)[0][1::3] == ["Feb", "Jan", "Sum / Mean"]  # (its block's header: each function once)
    assert grid(cells)[-1][:2] == ["Sum / Mean", "2200.0"]


def test_rows_within_rows(book):
    cells = layout(pivot(rows=(0, 1), values=((3, "SUM"),)), book)
    assert grid(cells) == [["Region", "Month", "SUM of Units"],
                           ["East", "Feb", "5.0"], ["", "Jan", "4.0"],  # (East's label once)
                           ["West", "Feb", "1.0"], ["", "Jan", "2.0"],
                           ["Sum", "", "12.0"]]


def test_no_rows_just_totals(book):
    cells = layout(pivot(rows=(), column=0, totals=False), book)
    assert cells[(1, 1)].value == "East" and cells[(2, 0)].value == "Sum" and cells[(2, 1)].value == 2800.0


def test_numbers_sort_as_numbers_and_blanks_last(book):
    fill(book, [("Size", "Count"), ("10", "1"), ("9", "2"), ("", "3"), ("10", "4")], 10, 0)
    cells = layout(pivot(block=(10, 0, 14, 1), values=((1, "SUM"),)), book)
    assert [row[0] for row in grid(cells)] == ["Size", "9", "10", "(Blanks)", "Sum"]


def test_formats_and_errors_carry_over(book):
    book.set_formats({(row, 2): NumberFormat("currency") for row in range(1, 6)}, "Currency")
    book.set_cells({(6, 0): "North", (6, 2): "lots"})  # text in a value column: left out
    cells = layout(pivot(values=((2, "SUM"), (2, "STDDEV"))), book)
    assert cells[(1, 1)].fmt == NumberFormat("currency")
    assert cells[(2, 2)].value == CellError("#DIV/0!") and cells[(3, 2)].value == 141.4213562373095  # North: none


def test_filters(book):
    leave_out_west = ((0, ColumnFilter(frozenset({"West"}))),)
    assert grid(layout(pivot(rows=(1,), filters=leave_out_west), book))[1:] == [
        ["Feb", "1500.0"], ["Jan", "1300.0"], ["Sum", "2800.0"]]
    big = ((2, ColumnFilter(condition="greater", value="800")),)
    assert grid(layout(pivot(filters=big), book))[1:] == [["East", "2700.0"], ["West", "900.0"],
                                                         ["Sum", "3600.0"]]


def test_takes_in_rows_added_below(book):
    book.set_cells({(6, 0): "North", (6, 2): "50"})
    assert grid(layout(pivot(), book))[2] == ["North", "50.0"]
    book.set_cells({(8, 0): "South", (8, 2): "5"})  # (past a blank row: not)
    assert len(grid(layout(pivot(), book))) == 5


def test_no_source(book):
    assert layout(pivot(), None) == layout(pivot(block=None), book)
    assert layout(pivot(), None)[(0, 0)].value == CellError("#REF!")


def test_json_round_trip():
    each = pivot(column=1, values=((2, "SUM"), (3, "MEDIAN")), filters=((0, ColumnFilter(frozenset({"West"}))),),
                 totals=False)
    data = to_json(each)
    assert data == {"at": "G1", "sheet": "Sheet1", "range": "A1:D6", "rows": ["A"], "column": "B",
                    "values": [{"column": "C", "function": "SUM"}, {"column": "D", "function": "MEDIAN"}],
                    "filters": {"A": {"hidden": ["West"]}}, "totals": False}
    assert from_json(data) == each
    assert from_json({**data, "range": None}) is None
    assert from_json({**data, "values": [{"column": "C", "function": "PRODUCT"}]}) is None
    assert from_json({**data, "values": []}) is None
    del data["range"]
    assert from_json(data).block is None


# --- On its sheet ---

def test_shown_in_the_sheet_and_kept_up(book):
    book.set_pivots([pivot()], "Add Pivot Table")
    assert shown(book, 0, 6, 4, 2) == [["Region", "SUM of Sales"], ["East", "2800"], ["West", "1600"],
                                       ["Sum", "4400"]]
    assert book.value(1, 7) == 2800.0 and book.get_cell(1, 7) == "" and book.content(1, 7) == "2800"
    assert book.data(book.index(0, 6), Qt.FontRole).bold() and book.data(book.index(1, 6), Qt.FontRole) is None
    book.set_cell(1, 2, "2200")  # the source changes: so does it
    assert book.display_text(1, 7) == "3800"
    book.set_cells({(9, 0): "=H2*2", (9, 1): "=SUM(H2:H3)"})  # formulas can use it
    assert book.value(9, 0) == 7600.0 and book.value(9, 1) == 5400.0
    assert book.used_range() == (0, 0, 9, 7)
    assert book.pivot_at(2, 7) == pivot() and book.pivot_at(4, 7) is None


def test_of_another_sheet(book):
    book.add_sheet()
    other = book.current_sheet()
    other.set_pivots([pivot(row=0, col=0)], "Add Pivot Table")
    assert book.display_text(3, 1) == "4400"
    book.show_index(0)
    book.set_cell(2, 2, "1000")
    assert other.display_text(3, 1) == "4500"
    book.rename_sheet(0, "Sales Data")  # its source follows
    assert other.pivots()[0].source == "Sales Data" and other.display_text(3, 1) == "4500"
    book.show_index(0)
    book.insert_rows(0)  # and moves with its cells
    assert other.pivots()[0].block == (1, 0, 6, 3) and other.display_text(3, 1) == "4500"
    book.delete_sheet(0)
    assert other.value(0, 0) == CellError("#REF!")
    book.undo_stack.undo()
    assert other.display_text(3, 1) == "4500"


def test_room(book):
    assert book.pivot_room_problem(pivot(col=2)) == "It would cover C1, which has something in it."
    assert book.pivot_room_problem(pivot(row=38)) == (
        "There isn't room for it there: it would go past the edge of the sheet.")
    book.set_pivots([pivot()], "Add Pivot Table")
    assert book.pivot_room_problem(pivot(row=2, col=7)) == "It would cover another pivot table."
    assert book.pivot_room_problem(pivot(row=2, col=7), ()) is None


def test_crowded_out_until_theres_room(book):
    book.set_pivots([pivot()], "Add Pivot Table")
    book.set_cell(2, 7, "mine")  # typed into it
    assert book.value(0, 6) == CellError("#REF!") and book.display_text(2, 7) == "mine"
    assert book.data(book.index(0, 6), Qt.ToolTipRole) == (
        "This pivot table needs room: H3 is in the way. Clear it, or move the pivot table, to show it.")
    assert book.pivot_at(0, 6) is not None and book.pivot_at(1, 7) is None
    book.set_cell(2, 7, "")
    assert book.display_text(1, 7) == "2800"
    book.set_cell(4, 7, "x")  # just below it
    assert book.display_text(3, 6) == "Sum"
    book.set_cells({(6, 0): "North", (6, 2): "5"})  # it grows into the cell that's taken
    assert book.value(0, 6) == CellError("#REF!")


def test_moves_with_its_cells(book):
    book.set_pivots([pivot(rows=(1,), values=((3, "SUM"),))], "Add Pivot Table")
    book.insert_columns(0)  # before the source and the pivot table
    assert book.pivots() == (pivot(col=7, block=(0, 1, 5, 4), rows=(2,), values=((4, "SUM"),)),)
    assert book.display_text(3, 8) == "12"
    book.delete_columns(4)  # its value column
    assert book.pivots()[0].values == () and book.value(0, 6) == CellError("#REF!")
    book.undo_stack.undo()
    book.delete_rows(0)  # its corner's row
    assert book.pivots() == ()


def test_undo_and_clearing(book):
    book.set_pivots([pivot()], "Add Pivot Table")
    assert book.undo_stack.undoText() == "Add Pivot Table"
    book.clear_cells([book.index(1, 7)])  # not its corner: nothing
    assert book.pivots() == (pivot(),)
    book.clear_cells([book.index(r, c) for r in range(4) for c in range(6, 8)])  # all of it: it goes
    assert book.pivots() == () and book.display_text(1, 7) == ""
    book.undo_stack.undo()
    assert book.display_text(1, 7) == "2800"


def test_saved_and_opened(book, tmp_path):
    book.set_pivots([pivot(column=1)], "Add Pivot Table")
    path = str(tmp_path / "pivot.ezs")
    save_workbook(path, book.workbook_data())
    assert json.loads(open(path).read())["sheets"][0]["pivots"] == [to_json(pivot(column=1))]
    opened = WorkbookModel()
    opened.load_workbook_data(load_workbook(path))
    assert opened.pivots() == (pivot(column=1),) and opened.display_text(4, 9) == "4400"
    document = json.loads(open(path).read())
    document["sheets"][0]["pivots"] = [{"at": "G1"}]
    open(path, "w").write(json.dumps(document))
    with pytest.raises(SheetFileError, match="bad pivot table"):
        load_workbook(path)


# --- The dialog ---

def test_dialog(app):
    values = {0: ["East", "West"], 1: ["Feb", "Jan"]}
    labels = {0: "Region", 1: "Month", 2: "Sales"}
    dialog = PivotDialog(None, "Sheet1!A1:C6", labels, values.get, pivot(values=((2, "SUM"),)))
    assert dialog.choice() == {"rows": (0,), "column": None, "values": ((2, "SUM"),), "filters": (), "totals": True}
    assert dialog.ok_button.text() == "Choose Where…" and dialog.ok_button.isEnabled()
    functions = dialog.value_lines[0][2]
    assert [functions.itemText(i) for i in range(functions.count())] == [
        "SUM", "MEAN", "MEDIAN", "MIN", "MAX", "STDDEV", "COUNT", "COUNTA"]
    assert dialog.value_lines[0][1].itemText(1) == "Month (column B)"
    dialog.add_row(1)
    dialog.column_box.setCurrentIndex(dialog.column_box.findData(1))
    dialog.add_value(2, "MEDIAN")
    dialog.totals_box.setChecked(False)
    dialog.add_filter(0, ColumnFilter())
    line = dialog.filter_lines[0][0]
    menu = dialog.choose_filter(line)
    assert [menu.list.item(i).text() for i in range(menu.list.count())] == ["East", "West"]
    menu.list.item(1).setCheckState(Qt.Unchecked)
    menu.ok_button.click()
    assert dialog.filter_lines[0][3].text() == "Leaving out 1 value"
    assert dialog.choice() == {"rows": (0, 1), "column": 1, "values": ((2, "SUM"), (2, "MEDIAN")),
                               "filters": ((0, ColumnFilter(frozenset({"West"}))),), "totals": False}
    for line, *_ in list(dialog.value_lines):
        dialog._remove(dialog.value_lines, line)
    assert not dialog.ok_button.isEnabled() and dialog.problem.text() == "Add a value to show."
    assert PivotDialog(None, "x", labels, values.get, pivot(), editing=True).ok_button.text() == "Update"


def test_describing_filters():
    assert describe(ColumnFilter()) == "All"
    assert describe(ColumnFilter(frozenset({"a", "b"}), "greater", "5")) == "Leaving out 2 values; Greater than 5"
    assert describe(ColumnFilter(condition="not empty")) == "Is not empty"


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    fill(window.model)
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def click(window, row, col):
    view = window.view
    view.pick_handler(window.model.index(row, col)) if view.pick_handler else None


def message(window):
    return window.statusBar().currentMessage()


def test_make_one_by_clicking_where(window, dialogs):
    window.view.select_range(0, 0, 5, 3)
    dialogs.pivot_answer = {"column": 1}
    assert window.pivot_table()
    [(where, labels, start, editing)] = dialogs.pivot_prompts
    assert where == "Sheet1!A1:D6" and labels == {0: "Region", 1: "Month", 2: "Sales", 3: "Units"} and not editing
    assert start.rows == (0,) and start.values == ((3, "SUM"),)  # (the last column of numbers)
    assert message(window).startswith("Click the cell for the pivot table's top-left corner")
    assert window.view.viewport().cursor().shape() == Qt.CrossCursor
    click(window, 0, 2)  # on the data: no room
    assert message(window) == "It would cover C1, which has something in it. Click another cell, or press Esc."
    click(window, 0, 6)
    assert window.model.pivots() == (pivot(column=1, values=((3, "SUM"),)),)
    assert message(window) == "Made a pivot table of Sheet1!A1:D6 at G1. It keeps up as they change."
    assert window.view.selection_bounds() == (0, 6, 4, 9) and window.view.pick_handler is None
    assert window.undo_action.text() == "Undo Add Pivot Table"


def test_put_on_another_sheet(window, dialogs):
    window.view.select_range(0, 0, 5, 3)
    window.pivot_table()
    window.add_sheet()  # (clicking +, or a tab, while choosing)
    click(window, 1, 1)
    assert window.model.title == "Sheet2" and window.model.pivots()[0].source == "Sheet1"
    assert window.model.display_text(4, 1) == "Sum" and window.model.display_text(4, 2) == "12"
    window.sheet_tabs.setCurrentIndex(0)
    window.model.set_cell(1, 3, "13")
    window.sheet_tabs.setCurrentIndex(1)
    assert window.model.display_text(4, 2) == "22"


def test_esc_cancels(window, dialogs):
    window.pivot_table()  # (one cell selected: the sheet's data)
    assert dialogs.pivot_prompts[0][0] == "Sheet1!A1:D6"
    window.view.escape_pressed.emit()
    assert message(window) == "No pivot table made." and window.view.pick_handler is None
    dialogs.pivot_answer = None  # the dialog's Cancel
    assert not window.pivot_table() and window.view.pick_handler is None


def test_nothing_to_pivot(app, dialogs):
    window = MainWindow()
    assert not window.pivot_table()
    assert message(window) == "There's nothing to make a pivot table of. Select a table, with its header row."
    window.model.set_cells({(0, 0): "a", (0, 1): "b"})
    assert not window.pivot_table() and "header row with rows of data below it" in message(window)
    assert dialogs.pivot_prompts == []
    window.setWindowModified(False)
    window.close()


def test_edit_and_delete_from_the_menu(window, dialogs):
    window.model.set_pivots([pivot()], "Add Pivot Table")
    window.view.setCurrentIndex(window.model.index(1, 7))
    window._show_context_menu(QPoint(5, 5))
    window.context_menu.hide()
    assert window.pivot_action.text() == "Edit Pivot Table…" and window.delete_pivot_action.isVisible()
    dialogs.pivot_answer = {"values": ((3, "MEAN"),)}
    window.pivot_action.trigger()
    assert dialogs.pivot_prompts[-1][2:] == (pivot(), True)
    assert window.model.display_text(0, 7) == "MEAN of Units" and message(window) == "Changed the pivot table."
    window.delete_pivot_action.trigger()
    assert window.model.pivots() == () and message(window) == "Deleted the pivot table."
    assert window.pivot_action.text() == "Pivot Table…" and not window.delete_pivot_action.isVisible()


def test_edit_bar_and_copying(window):
    window.model.set_pivots([pivot()], "Add Pivot Table")
    window.view.setCurrentIndex(window.model.index(1, 7))
    assert window.edit_bar.text() == "" and window.edit_bar.placeholderText() == "2800"
    window.view.select_range(1, 6, 2, 7)
    window.clipboard.copy()
    assert QGuiApplication.clipboard().text() == "East\t2800\nWest\t1600"
    window.view.setCurrentIndex(window.model.index(10, 0))
    window.clipboard.paste()
    assert window.model.get_cell(10, 1) == "2800"
    window.view.setCurrentIndex(window.model.index(12, 0))
    assert window.edit_bar.placeholderText() == "Cell contents"
