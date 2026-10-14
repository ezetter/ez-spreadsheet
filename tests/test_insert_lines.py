import pytest
from PySide6.QtCore import QPoint

from py_spread.model import SheetModel
from py_spread.numformat import NumberFormat
from py_spread.textstyle import CellStyle
from py_spread.window import MainWindow, runs


def contents(model) -> dict:
    return {(row, col): model.get_cell(row, col) for (row, col) in sorted(model._cells)}


@pytest.fixture
def model(app):
    model = SheetModel(rows=10, cols=5)
    model.set_cells({(0, 0): "1", (0, 1): "2", (0, 2): "3", (0, 3): "=A1+B1+C1", (1, 3): "=SUM(A1:C1)",
                     (4, 2): "7"})
    return model


# --- The model ---

def test_insert_columns(model):
    model.set_formats({(0, 1): NumberFormat("currency", 2)}, "Currency")
    model.set_styles({(0, 2): CellStyle(bold=True)}, "Bold")
    model.insert_columns(1, 2)
    assert contents(model) == {(0, 0): "1", (0, 3): "2", (0, 4): "3", (0, 5): "=A1+D1+E1",
                               (1, 5): "=SUM(A1:E1)", (4, 4): "7"}
    assert model.value(0, 5) == 6 and model.value(1, 5) == 6
    assert model.cell_format(0, 3).kind == "currency" and model.cell_style(0, 4).bold
    assert model.columnCount() == 6  # grew to fit
    assert model.undo_stack.undoText() == "Insert Columns"


def test_column_names_move_with_their_columns(model):
    model.name_column(2, "t")
    model.name_cell(0, 1, "r")
    model.set_cell(2, 4, "=t5*r+$C$5")
    model.insert_columns(0)
    assert model.column_names() == {"t": 3} and model.cell_names() == {"r": (0, 2)}
    assert model.get_cell(2, 5) == "=t5*r+$D$5" and model.value(2, 5) == 7 * 2 + 7
    model.undo_stack.undo()
    assert model.column_names() == {"t": 2} and model.get_cell(2, 4) == "=t5*r+$C$5"


def test_columns_after_a_named_column_leave_it(model):
    model.name_column(1, "b")
    model.insert_columns(3)
    assert model.column_names() == {"b": 1}


def test_named_empty_column_grows_the_sheet(app):
    model = SheetModel(rows=5, cols=3)
    model.name_column(2, "z")
    model.insert_columns(1)
    assert model.column_names() == {"z": 3} and model.columnCount() == 4


def test_insert_rows(model):
    model.name_column(2, "t")
    model.set_cell(2, 4, "=t5+C1")
    model.insert_rows(1, 3)
    assert model.get_cell(0, 3) == "=A1+B1+C1"  # above the new rows: unchanged
    assert model.get_cell(4, 3) == "=SUM(A1:C1)" and model.get_cell(7, 2) == "7"
    assert model.get_cell(5, 4) == "=t8+C1"  # the alias follows its cell down the column
    assert model.column_names() == {"t": 2} and model.value(5, 4) == 10
    assert model.undo_stack.undoText() == "Insert Rows"
    model.undo_stack.undo()
    assert model.get_cell(4, 2) == "7" and model.get_cell(2, 4) == "=t5+C1"


def test_rows_push_empty_named_cells_and_grow(app):
    model = SheetModel(rows=5, cols=3)
    model.name_cell(4, 0, "last")
    model.insert_rows(0, 2)
    assert model.cell_names() == {"last": (6, 0)} and model.rowCount() == 7


def test_runs():
    assert runs([5, 1, 2]) == [(1, 2), (5, 1)] and runs([]) == []


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.model.set_cells({(0, 0): "a", (0, 1): "b", (0, 2): "c", (0, 3): "d", (1, 3): "=B1",
                            (2, 0): "x", (3, 0): "y"})
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def select_columns(window, left, right):
    window.view.select_range(0, left, window.model.rowCount() - 1, right)


def select_rows(window, top, bottom):
    window.view.select_range(top, 0, bottom, window.model.columnCount() - 1)


def test_recognizes_whole_columns_and_rows(window):
    select_columns(window, 1, 2)
    assert window.view.whole_lines() == ("columns", [1, 2])
    select_rows(window, 3, 3)
    assert window.view.whole_lines() == ("rows", [3])
    window.view.select_range(0, 0, 5, 5)
    assert window.view.whole_lines() is None
    window.view.select_range(0, 0, window.model.rowCount() - 1, window.model.columnCount() - 1)
    assert window.view.whole_lines() is None  # the whole sheet


def test_menu_item_names_what_it_inserts(window):
    action = window.insert_cells_action
    assert action.text() == "Insert Cells…"
    select_columns(window, 1, 1)
    assert action.text() == "Insert Column"
    select_columns(window, 1, 3)
    assert action.text() == "Insert Columns"
    select_rows(window, 2, 4)
    assert action.text() == "Insert Rows"
    window.view.select_range(1, 1, 2, 2)
    assert action.text() == "Insert Cells…"


def test_insert_columns_without_asking(window, dialogs):
    select_columns(window, 1, 2)
    window.insert_cells_action.trigger()
    assert dialogs.insert_problems is None  # no Insert Cells dialog
    model = window.model
    assert [model.get_cell(0, c) for c in range(6)] == ["a", "", "", "b", "c", "d"]
    assert model.get_cell(1, 5) == "=D1"
    assert window.view.whole_lines() == ("columns", [1, 2])  # the new ones are selected
    assert window.statusBar().currentMessage() == "Inserted 2 blank columns."
    assert window.undo_action.text() == "Undo Insert Columns"
    window.undo_action.trigger()
    assert [model.get_cell(0, c) for c in range(4)] == ["a", "b", "c", "d"]


def test_insert_rows(window):
    select_rows(window, 2, 2)
    window.insert_cells()
    assert [window.model.get_cell(r, 0) for r in range(5)] == ["a", "", "", "x", "y"]
    assert window.view.whole_lines() == ("rows", [2])
    assert window.statusBar().currentMessage() == "Inserted 1 blank row."


def test_separate_columns_each_get_one(window):
    model, view = window.model, window.view
    selection = view.selectionModel()
    select_columns(window, 1, 1)
    from PySide6.QtCore import QItemSelection, QItemSelectionModel
    rows = model.rowCount() - 1
    selection.select(QItemSelection(model.index(0, 3), model.index(rows, 3)), QItemSelectionModel.Select)
    assert view.whole_lines() == ("columns", [1, 3])
    window.insert_cells()
    assert [model.get_cell(0, c) for c in range(6)] == ["a", "", "b", "c", "", "d"]
    assert view.whole_lines() == ("columns", [1, 4])
    window.undo_action.trigger()  # all one step
    assert [model.get_cell(0, c) for c in range(4)] == ["a", "b", "c", "d"]


def test_widths_move_with_their_columns(window):
    header = window.view.horizontalHeader()
    default = header.defaultSectionSize()
    header.resizeSection(2, 250)
    select_columns(window, 1, 1)
    window.insert_cells()
    assert (header.sectionSize(1), header.sectionSize(2), header.sectionSize(3)) == (default, default, 250)
    window.undo_action.trigger()
    assert (header.sectionSize(2), header.sectionSize(3)) == (250, default)
    window.redo_action.trigger()
    assert header.sectionSize(3) == 250
    window.set_zoom(200)
    window.undo_action.trigger()  # sizes are kept relative to the zoomed default
    assert header.sectionSize(2) == round(250 / default * header.defaultSectionSize())


def test_heights_move_with_their_rows(window):
    header = window.view.verticalHeader()
    default = header.defaultSectionSize()
    header.resizeSection(3, 60)
    select_rows(window, 0, 1)
    window.insert_cells()
    assert (header.sectionSize(3), header.sectionSize(5)) == (default, 60)


def test_column_header_menu(window):
    select_columns(window, 1, 2)
    window._show_header_menu(QPoint(window.view.columnViewportPosition(2) + 5, 5))
    assert [a.text() for a in window.header_menu.actions()] == ["Insert Columns", "", "Name Column…"]
    assert window.view.whole_lines() == ("columns", [1, 2])  # clicked inside the selection: kept
    window.header_menu.hide()
    window._show_header_menu(QPoint(window.view.columnViewportPosition(4) + 5, 5))
    assert window.view.whole_lines() == ("columns", [4])  # outside: just that column
    window.header_menu.hide()


def test_row_header_menu(window):
    header = window.view.verticalHeader()
    window._show_row_header_menu(QPoint(5, header.sectionViewportPosition(3) + 5))
    assert window.view.whole_lines() == ("rows", [3])
    assert [a.text() for a in window.header_menu.actions()] == ["Insert Row"]
    window.header_menu.actions()[0].trigger()
    assert window.model.get_cell(4, 0) == "y"
    window.header_menu.hide()
