import pytest

from py_spread.formula import move_references
from py_spread.shift_dialog import InsertCellsDialog
from py_spread.model import SheetModel
from py_spread.numformat import NumberFormat
from py_spread.textstyle import CellStyle
from py_spread.window import MainWindow


def grid(model, rows):
    return [[model.get_cell(r, c) for c in range(len(rows[0]))] for r in range(len(rows))]


def load(model, rows):
    model.set_cells({(r, c): v for r, row in enumerate(rows) for c, v in enumerate(row) if v})


@pytest.fixture
def model(app):
    return SheetModel(rows=10, cols=6)


# 3x3 block of data in A1:C3
DATA = [["a1", "b1", "c1"], ["a2", "b2", "c2"], ["a3", "b3", "c3"]]


def test_shift_down(model):
    load(model, DATA)
    assert model.insert_cells(1, 1, 1, 1, "down") is None  # at B2
    assert grid(model, [[""] * 3] * 4) == [["a1", "b1", "c1"], ["a2", "", "c2"], ["a3", "b2", "c3"], ["", "b3", ""]]


def test_shift_right(model):
    load(model, DATA)
    model.insert_cells(1, 1, 1, 2, "right")  # B2:C2
    assert grid(model, [[""] * 5] * 3) == [["a1", "b1", "c1", "", ""], ["a2", "", "", "b2", "c2"],
                                           ["a3", "b3", "c3", "", ""]]


def test_shift_up(model):
    load(model, [[""] * 3, [""] * 3] + DATA)  # data in A3:C5, two empty rows above
    model.insert_cells(3, 0, 4, 0, "up")      # A4:A5: blanks there, and the cells there and above move up
    assert [model.get_cell(r, 0) for r in range(5)] == ["a1", "a2", "a3", "", ""]
    assert model.get_cell(4, 1) == "b3"       # other columns stay put


def test_shift_left(model):
    load(model, [["", "x", "y", "z"]])
    model.insert_cells(0, 2, 0, 2, "left")    # C1
    assert [model.get_cell(0, c) for c in range(4)] == ["x", "y", "", "z"]


@pytest.mark.parametrize("shift, edge", [("up", "top"), ("left", "left")])
def test_no_room_up_or_left(model, shift, edge):
    load(model, DATA)
    steps = model.undo_stack.count()
    problem = model.insert_cells(1, 1, 1, 1, shift)
    assert edge in problem
    assert grid(model, DATA) == DATA
    assert model.undo_stack.count() == steps  # nothing recorded


def test_down_grows_the_sheet(model):
    model.set_cell(9, 0, "last")
    model.insert_cells(0, 0, 2, 0, "down")
    assert model.rowCount() == 13
    assert model.get_cell(12, 0) == "last"


def test_formulas_follow_moved_cells(model):
    load(model, [["1"], ["2"], ["3"], ["4"], ["5"]])
    model.set_cell(0, 2, "=SUM(A1:A5)")
    model.set_cell(1, 2, "=A4*10")
    model.set_cell(2, 2, "=$A$5")
    model.insert_cells(2, 0, 2, 0, "down")   # at A3
    assert model.get_cell(0, 2) == "=SUM(A1:A6)"  # the range grows
    assert model.get_cell(1, 2) == "=A5*10"
    assert model.get_cell(2, 2) == "=$A$6"        # anchored references follow too
    assert model.display_text(0, 2) == "15"
    assert model.display_text(1, 2) == "40"


def test_moved_formulas_keep_pointing_at_the_same_cells(model):
    load(model, [["1", "=A1*2"], ["2", "=A2*2"]])
    model.insert_cells(0, 1, 0, 1, "down")    # only column B moves
    assert model.get_cell(1, 1) == "=A1*2" and model.get_cell(2, 1) == "=A2*2"
    assert model.display_text(2, 1) == "4"


def test_reference_pushed_off_becomes_ref_error(model):
    model.set_cell(5, 3, "=A1+1")              # A1 is empty, so the shift is allowed
    assert model.insert_cells(2, 0, 3, 0, "up") is None  # A3:A4 up by two: rows 1-2 go off
    assert model.get_cell(5, 3) == "=#REF!+1"


def test_formats_and_styles_move(model):
    model.set_cell(0, 0, "5")
    model.set_formats({(0, 0): NumberFormat("currency")}, "Currency Format")
    model.set_styles({(0, 0): CellStyle(bold=True)}, "Bold")
    model.insert_cells(0, 0, 0, 0, "down")
    assert model.cell_format(0, 0) is None and model.cell_style(0, 0) == CellStyle()
    assert model.display_text(1, 0) == "$5.00" and model.cell_style(1, 0).bold


def test_insert_is_one_undo_step(model):
    load(model, DATA)
    model.set_cell(5, 5, "=B3")
    model.insert_cells(0, 0, 2, 2, "right")
    assert model.undo_stack.undoText() == "Insert Cells"
    model.undo_stack.undo()
    assert grid(model, DATA) == DATA
    assert model.get_cell(5, 5) == "=B3"


@pytest.mark.parametrize("formula, expected", [
    ("=A1+B2", "=A1+B3"),
    ("=sum(b1:b9)", "=sum(b1:B10)"),     # unmoved text is kept as typed
    ("=A1 ! bad", "=A1 ! bad"),
])
def test_move_references(formula, expected):
    def move(row, col):
        return (row + 1, col) if col == 1 and row >= 1 else (row, col)
    assert move_references(formula, move) == expected


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
    assert "Insert Cells…" in [a.text() for a in edit.actions()]
    load(window.model, DATA)
    window.view.select_range(0, 0, 1, 0)
    dialogs.insert_shift = "right"
    window.insert_cells_action.trigger()
    assert [window.model.get_cell(0, c) for c in range(4)] == ["", "a1", "b1", "c1"]
    assert window.insert_shift == "right"  # offered next time
    selected = sorted((i.row(), i.column()) for i in window.view.selectedIndexes())
    assert selected == [(0, 0), (1, 0)]
    assert "Inserted 2 blank cells; shift cells right." in window.statusBar().currentMessage()


def test_cancel_changes_nothing(window, dialogs):
    load(window.model, DATA)
    dialogs.insert_shift = None
    assert not window.insert_cells()
    assert grid(window.model, DATA) == DATA


def test_no_room_shows_error(window, dialogs):
    load(window.model, DATA)
    window.view.select_range(1, 0, 1, 0)  # A2: shifting up would push a1 off the top
    dialogs.insert_shift = "up"           # (the dialog disables this; the model checks anyway)
    assert not window.insert_cells()
    assert dialogs.errors and "no room" in dialogs.errors[0]


@pytest.mark.parametrize("bounds, data, disabled", [
    ((0, 1, 0, 2), [], {"up"}),                         # first row
    ((1, 0, 2, 0), [], {"left"}),                       # first column
    ((0, 0, 0, 0), [], {"up", "left"}),                 # A1
    ((3, 3, 4, 4), [], set()),                          # room everywhere, nothing in the way
    ((3, 3, 4, 4), [(0, 3)], {"up"}),                   # D1 would be pushed off the top
    ((3, 3, 4, 4), [(3, 0)], {"left"}),                 # A4 would be pushed off the left
    ((3, 3, 4, 4), [(0, 0)], set()),                    # A1 isn't in the way of either
])
def test_impossible_shifts_are_disabled(window, dialogs, bounds, data, disabled):
    window.model.set_cells({cell: "x" for cell in data})
    window.view.select_range(*bounds)
    dialogs.insert_shift = None
    window.insert_cells()
    assert set(dialogs.insert_problems) == disabled


def test_formats_count_as_in_the_way(window, dialogs):
    window.model.set_styles({(0, 2): CellStyle(bold=True)}, "Bold")  # C1, empty but bold
    window.view.select_range(2, 2, 2, 2)
    dialogs.insert_shift = None
    window.insert_cells()
    assert set(dialogs.insert_problems) == {"up"}


def test_dialog_disables_problem_choices(app):
    dialog = InsertCellsDialog(shift="up", problems={"up": "first row", "left": "first column"})
    assert not dialog.buttons["up"].isEnabled()
    assert dialog.buttons["up"].toolTip() == "first row"
    assert not dialog.buttons["left"].isEnabled()
    assert dialog.buttons["down"].isEnabled() and dialog.buttons["right"].isEnabled()
    assert dialog.shift() == "down"  # the remembered choice isn't available, so the first that is


def test_dialog(app):
    dialog = InsertCellsDialog(shift="left")
    assert dialog.shift() == "left"
    dialog.buttons["up"].setChecked(True)
    assert dialog.shift() == "up"
    assert [b.text() for b in dialog.buttons.values()] == [
        "Shift cells down", "Shift cells right", "Shift cells up", "Shift cells left"]
