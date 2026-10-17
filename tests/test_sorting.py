import pytest
from PySide6.QtCore import QPoint

from ezsheet.errors import CellError
from ezsheet.model import SheetModel
from ezsheet.numformat import NumberFormat
from ezsheet.sorting import ASCENDING, DESCENDING, has_header, sorted_rows
from ezsheet.textstyle import CellStyle
from ezsheet.window import MainWindow


# --- The order ---

def order(values, ascending=ASCENDING):
    rows = list(range(len(values)))
    return [values[row] for row in sorted_rows(rows, lambda row, _col: values[row], [(0, ascending)])]


def test_numbers_then_text_then_errors_then_empty():
    error = CellError("#DIV/0!")
    values = ["pear", 10.0, None, "Apple", error, 2.5, "", "banana"]
    assert order(values) == [2.5, 10.0, "Apple", "banana", "pear", error, None, ""]
    assert order(values, DESCENDING) == [error, "pear", "banana", "Apple", 10.0, 2.5, None, ""]  # empty still last


def test_ties_keep_their_order_and_more_columns():
    table = {0: ("b", 1.0), 1: ("a", 2.0), 2: ("b", 0.0), 3: ("a", 1.0)}
    value = lambda row, col: table[row][col]
    assert sorted_rows(range(4), value, [(0, ASCENDING)]) == [1, 3, 0, 2]  # (a's, b's: each as they were)
    assert sorted_rows(range(4), value, [(0, ASCENDING), (1, DESCENDING)]) == [1, 3, 0, 2]
    assert sorted_rows(range(4), value, [(0, DESCENDING), (1, ASCENDING)]) == [2, 0, 3, 1]


def grid(rows):
    return lambda row, col: rows[row][col] if row < len(rows) and col < len(rows[row]) else None


@pytest.mark.parametrize("rows, bold, header", [
    ([["Month", "Sales"], ["Jan", 1200.0], ["Feb", 900.0]], set(), True),  # text over numbers
    ([["Name"], ["bob"], ["al"]], set(), False),  # a list of names: no telling
    ([["Name"], ["bob"], ["al"]], {(0, 0)}, True),  # but a bold one over plain is
    ([["Name"], ["bob"], ["al"]], {(0, 0), (1, 0)}, False),
    ([[1.0, "x"], [2.0, "y"]], set(), False),  # numbers on top
    ([["Only"]], set(), False),
])
def test_header_guess(rows, bold, header):
    assert has_header(grid(rows), lambda r, c: (r, c) in bold, 0, 0, len(rows) - 1, len(rows[0]) - 1) is header


# --- In the model ---

@pytest.fixture
def model(app):
    model = SheetModel(rows=20, cols=6)
    model.set_cells({
        (0, 0): "Name", (0, 1): "Score", (0, 2): "Double",
        (1, 0): "bob", (1, 1): "5", (1, 2): "=B2*2",
        (2, 0): "Al", (2, 1): "12", (2, 2): "=B3*2",
        (3, 0): "cy", (3, 1): "1", (3, 2): "=$B$2",
    })
    model.set_formats({(2, 1): NumberFormat("currency")}, "Currency")
    model.set_styles({(2, 0): CellStyle(bold=True, fill="#fff2cc")}, "Style")
    return model


def column(model, col, rows=range(4)):
    return [model.get_cell(row, col) for row in rows]


def test_rows_move_whole(model):
    assert model.sort_rows(1, 0, 3, 2, [(1, ASCENDING)])
    assert column(model, 0) == ["Name", "cy", "bob", "Al"] and column(model, 1) == ["Score", "1", "5", "12"]
    assert column(model, 2) == ["Double", "=$B$2", "=B3*2", "=B4*2"]  # (relative references move with them)
    assert [model.value(row, 2) for row in (2, 3)] == [10.0, 24.0]
    assert model.cell_format(3, 1) == NumberFormat("currency") and model.cell_style(3, 0).fill == "#fff2cc"
    assert model.cell_format(2, 1) is None and model.cell_style(2, 0) == CellStyle()
    model.undo_stack.undo()  # one step
    assert column(model, 0) == ["Name", "bob", "Al", "cy"] and model.cell_format(2, 1) == NumberFormat("currency")


def test_sorted_already(model):
    model.sort_rows(1, 0, 3, 2, [(1, ASCENDING)])
    steps = model.undo_stack.count()
    assert not model.sort_rows(1, 0, 3, 2, [(1, ASCENDING)]) and model.undo_stack.count() == steps


def test_data_block_takes_in_styles(model):
    model.set_styles({(9, 5): CellStyle(fill="#ff0000")}, "Fill")
    assert model.data_block() == (0, 0, 9, 5) and model.used_range() == (0, 0, 3, 2)


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.model.set_cells({
        (0, 0): "Name", (0, 1): "Score", (0, 3): "note",
        (1, 0): "bob", (1, 1): "5", (1, 3): "b",
        (2, 0): "Al", (2, 1): "12", (2, 3): "a",
        (3, 0): "cy", (3, 1): "1", (3, 3): "c",
    })
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def data_menu(window):
    menu = [m for m in window.menuBar().actions() if m.text() == "Data"][0].menu()
    return {action.text(): action for action in menu.actions() if action.text()}


def test_data_menu_names_the_current_column(window):
    window.view.setCurrentIndex(window.model.index(0, 1))
    assert list(data_menu(window)) == [
        "Sort Sheet by Column B (A → Z)", "Sort Sheet by Column B (Z → A)", "Sort Range by Column B (A → Z)",
        "Sort Range by Column B (Z → A)", "Sort Range…"]
    assert not data_menu(window)["Sort Range by Column B (A → Z)"].isEnabled()  # (no range selected)
    window.view.select_range(0, 0, 3, 1)
    assert data_menu(window)["Sort Range by Column A (A → Z)"].isEnabled()


def test_sort_sheet_keeps_the_header(window):
    window.view.setCurrentIndex(window.model.index(2, 1))
    data_menu(window)["Sort Sheet by Column B (Z → A)"].trigger()
    assert column(window.model, 0) == ["Name", "Al", "bob", "cy"]
    assert column(window.model, 3) == ["note", "a", "b", "c"]  # whole rows
    assert window.statusBar().currentMessage() == (
        "Sorted rows 2–4 by column B (Z → A), keeping row 1 as the header.")
    assert window.undo_action.text() == "Undo Sort Sheet"


def test_sort_from_the_column_header(window):
    window._show_header_menu(QPoint(window.view.columnViewportPosition(0) + 5, 5))
    actions = {a.text(): a for a in window.header_menu.actions()}
    actions["Sort Sheet A → Z"].trigger()
    window.header_menu.hide()
    assert column(window.model, 0) == ["Name", "Al", "bob", "cy"]


def test_sort_range_moves_just_its_columns(window):
    window.view.select_range(1, 0, 3, 1)  # A2:B4, not D
    window.view.setCurrentIndex(window.model.index(1, 1))
    window.view.select_range(1, 0, 3, 1)
    window.sort_range(1, ASCENDING)
    assert column(window.model, 0) == ["Name", "cy", "bob", "Al"] and column(window.model, 3) == ["note", "b", "a", "c"]


def test_sort_range_dialog(window, dialogs):
    model = window.model
    model.set_cells({(4, 0): "Al", (4, 1): "3", (4, 3): "z"})
    dialogs.sort_answer = ([(0, ASCENDING), (1, DESCENDING)], True)
    window.view.setCurrentIndex(model.index(0, 0))
    window.sort_range_dialog()  # no selection: the sheet's data
    [(where, labels, header, col)] = dialogs.sort_prompts
    assert (where, labels, header, col) == ("A1:D5", ["Name", "Score", "", "note"], True, 0)
    assert column(model, 0, range(5)) == ["Name", "Al", "Al", "bob", "cy"]
    assert column(model, 1, range(5)) == ["Score", "12", "3", "5", "1"]  # Al's: by score, high first
    dialogs.sort_answer = None  # Cancel
    assert not window.sort_range_dialog()


def test_no_header_when_asked(window, dialogs):
    dialogs.sort_answer = ([(0, ASCENDING)], False)  # the header row's sorted in too
    window.sort_range_dialog()
    assert column(window.model, 0) == ["Al", "bob", "cy", "Name"]


def test_sorting_wont_move_merged_cells(window, dialogs):
    window.model.set_merges({(2, 2, 2, 3)})
    window.view.setCurrentIndex(window.model.index(1, 0))
    assert not window.sort_sheet(0, ASCENDING)
    assert dialogs.errors[-1] == "Sorting can't move merged cells. Unmerge C3:D3 first."
    assert column(window.model, 0) == ["Name", "bob", "Al", "cy"]


def test_nothing_to_sort(app):
    window = MainWindow()
    assert not window.sort_sheet(0, ASCENDING)
    assert window.statusBar().currentMessage() == "There's nothing to sort."
    window.model.set_cell(0, 0, "only")
    assert not window.sort_sheet(0, ASCENDING) and "one row" in window.statusBar().currentMessage()
    window.setWindowModified(False)
    window.close()


def test_sort_dialog(app):
    from ezsheet.sort_dialog import SortDialog
    dialog = SortDialog(None, "A1:C9", 0, 2, {0: "Name", 1: "Score", 2: ""}.get, True, 1)
    column_box = dialog.keys[0][0]
    assert [column_box.itemText(i) for i in range(3)] == ["Column A (Name)", "Column B (Score)", "Column C"]
    assert dialog.sort_keys() == [(1, ASCENDING)] and not dialog.keys[0][2].isEnabled()  # (one: can't remove it)
    dialog.add_key(0, DESCENDING)
    assert dialog.sort_keys() == [(1, ASCENDING), (0, DESCENDING)]
    dialog.keys[0][2].click()  # remove the first
    assert dialog.sort_keys() == [(0, DESCENDING)]
    dialog.header_box.setChecked(False)  # no header: just letters
    assert dialog.keys[0][0].itemText(0) == "Column A" and not dialog.has_header()
