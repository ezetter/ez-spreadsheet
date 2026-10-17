import pytest

from ezsheet.model import SheetModel
from ezsheet.numformat import NumberFormat
from ezsheet.shift_dialog import DeleteCellsDialog
from ezsheet.textstyle import CellStyle
from ezsheet.window import MainWindow

DATA = [["a1", "b1", "c1"], ["a2", "b2", "c2"], ["a3", "b3", "c3"]]


def load(model, rows):
    model.set_cells({(r, c): v for r, row in enumerate(rows) for c, v in enumerate(row) if v})


def grid(model, rows, cols):
    return [[model.get_cell(r, c) for c in range(cols)] for r in range(rows)]


@pytest.fixture
def model(app):
    return SheetModel(rows=10, cols=6)


def test_shift_up(model):
    load(model, DATA)
    assert model.delete_cells(1, 1, 1, 1, "up") is None  # B2
    assert grid(model, 3, 3) == [["a1", "b1", "c1"], ["a2", "b3", "c2"], ["a3", "", "c3"]]


def test_shift_left(model):
    load(model, DATA)
    model.delete_cells(0, 0, 1, 0, "left")  # A1:A2
    assert grid(model, 3, 3) == [["b1", "c1", ""], ["b2", "c2", ""], ["a3", "b3", "c3"]]


def test_shift_down(model):
    load(model, DATA)
    model.delete_cells(2, 0, 2, 0, "down")  # A3: the cells above move down
    assert [model.get_cell(r, 0) for r in range(3)] == ["", "a1", "a2"]


def test_shift_right(model):
    load(model, DATA)
    model.delete_cells(0, 2, 0, 2, "right")  # C1: the cells to its left move right
    assert [model.get_cell(0, c) for c in range(3)] == ["", "a1", "b1"]


@pytest.mark.parametrize("bounds, impossible", [
    ((0, 1, 0, 1), {"down"}),                  # first row: nothing above
    ((1, 0, 1, 0), {"right"}),                 # first column: nothing to the left
    ((9, 2, 9, 2), {"up"}),                    # last row: nothing below
    ((3, 5, 3, 5), {"left"}),                  # last column: nothing to the right
    ((3, 2, 4, 3), set()),
])
def test_delete_problems(model, bounds, impossible):
    assert {s for s in ("up", "left", "down", "right") if model.delete_problem(*bounds, s)} == impossible


def test_references_follow_and_ranges_shrink(model):
    load(model, [["1"], ["2"], ["3"], ["4"], ["5"]])
    model.set_cells({(0, 2): "=SUM(A1:A5)", (1, 2): "=A5*10", (2, 2): "=A3", (3, 2): "=SUM(A3:A3)"})
    model.delete_cells(2, 0, 2, 0, "up")  # A3
    assert model.get_cell(0, 2) == "=SUM(A1:A4)"
    assert model.get_cell(1, 2) == "=A4*10"
    assert model.get_cell(2, 2) == "=#REF!"        # the cell it referred to is gone
    assert model.get_cell(3, 2) == "=SUM(#REF!)"   # so is the whole range
    assert model.display_text(0, 2) == "12"
    assert model.display_text(2, 2) == "#REF!"


@pytest.mark.parametrize("formula, deleted, shift, expected", [
    ("=SUM(A1:A5)", (4, 0, 4, 0), "up", "=SUM(A1:A4)"),     # deleting the range's end
    ("=SUM(A1:A5)", (0, 0, 0, 0), "up", "=SUM(A1:A4)"),     # its start
    ("=SUM(A2:A4)", (0, 0, 0, 0), "up", "=SUM(A1:A3)"),     # above it: it moves
    ("=SUM(A1:E1)", (0, 1, 0, 2), "left", "=SUM(A1:C1)"),
    ("=SUM(A1:A5)", (1, 0, 3, 0), "down", "=SUM(A4:A5)"),   # cells above slide down
])
def test_ranges(model, formula, deleted, shift, expected):
    model.set_cell(8, 5, formula)
    model.delete_cells(*deleted, shift)
    assert model.get_cell(8, 5) == expected


def test_formats_and_styles(model):
    model.set_cells({(0, 0): "gone", (1, 0): "5"})
    model.set_formats({(0, 0): NumberFormat("number"), (1, 0): NumberFormat("currency")}, "Format")
    model.set_styles({(1, 0): CellStyle(italic=True)}, "Italic")
    model.delete_cells(0, 0, 0, 0, "up")
    assert model.display_text(0, 0) == "$5.00" and model.cell_style(0, 0).italic
    assert model.cell_format(1, 0) is None


def test_delete_is_one_undo_step(model):
    load(model, DATA)
    model.set_cell(5, 5, "=SUM(A1:A3)")
    model.delete_cells(0, 0, 2, 0, "left")
    assert model.undo_stack.undoText() == "Delete Cells"
    model.undo_stack.undo()
    assert grid(model, 3, 3) == DATA
    assert model.get_cell(5, 5) == "=SUM(A1:A3)"


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def test_edit_menu_item(window, dialogs):
    edit = [m for m in window.menuBar().actions() if m.text() == "Edit"][0].menu()
    names = [a.text() for a in edit.actions()]
    assert names.index("Delete Cells…") == names.index("Insert Cells…") + 1
    load(window.model, DATA)
    window.view.select_range(0, 1, 2, 1)  # column B
    dialogs.delete_shift = "left"
    window.delete_cells_action.trigger()
    assert grid(window.model, 3, 3) == [["a1", "c1", ""], ["a2", "c2", ""], ["a3", "c3", ""]]
    assert window.delete_shift == "left"
    assert "Deleted 3 cells; shift cells left." in window.statusBar().currentMessage()


def test_impossible_choices_are_passed_to_dialog(window, dialogs):
    window.view.select_range(0, 0, 0, 0)
    dialogs.delete_shift = None
    assert not window.delete_cells()
    assert set(dialogs.delete_problems) == {"down", "right"}


def test_whole_sheet_selected(window, dialogs):
    model = window.model
    window.view.select_range(0, 0, model.rowCount() - 1, model.columnCount() - 1)
    assert not window.delete_cells()
    assert dialogs.delete_problems is None  # no dialog
    assert "whole sheet" in dialogs.errors[0]


def test_dialog(app):
    dialog = DeleteCellsDialog(shift=None, problems={"down": "first row"})
    assert dialog.windowTitle() == "Delete Cells"
    assert list(dialog.buttons) == ["up", "left", "down", "right"]
    assert dialog.shift() == "up"
    assert not dialog.buttons["down"].isEnabled()
    dialog = DeleteCellsDialog(shift="up", problems={"up": "last row"})
    assert dialog.shift() == "left"
