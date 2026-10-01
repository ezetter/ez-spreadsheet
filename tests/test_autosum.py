import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QToolBar

from py_spread.autosum import cell_ranges, run_above, run_left, sum_formula
from py_spread.model import SheetModel
from py_spread.window import MainWindow


@pytest.mark.parametrize("cells, expected", [
    ({(0, 0)}, [(0, 0, 0, 0)]),
    ({(r, 0) for r in range(100)}, [(0, 0, 99, 0)]),
    ({(r, c) for r in range(3) for c in range(4)}, [(0, 0, 2, 3)]),
    ({(0, 0), (1, 0), (5, 0)}, [(0, 0, 1, 0), (5, 0, 5, 0)]),
    ({(0, 0), (0, 2)}, [(0, 0, 0, 0), (0, 2, 0, 2)]),
    ({(0, 0), (1, 0), (0, 1)}, [(0, 0, 1, 0), (0, 1, 0, 1)]),
])
def test_cell_ranges(cells, expected):
    covered = {(r, c) for t, l, b, rt in cell_ranges(cells) for r in range(t, b + 1) for c in range(l, rt + 1)}
    assert covered == cells
    assert sorted(cell_ranges(cells)) == sorted(expected)


def test_sum_formula():
    assert sum_formula([(0, 0, 99, 0)]) == "=SUM(A1:A100)"
    assert sum_formula([(0, 0, 0, 0), (2, 1, 3, 2)]) == "=SUM(A1, B3:C4)"


@pytest.fixture
def model(app):
    return SheetModel(rows=20, cols=10)


def fill(model, cells):
    for (row, col), text in cells.items():
        model.set_cell(row, col, text)


def test_run_above(model):
    fill(model, {(0, 0): "Qty", (1, 0): "1", (2, 0): "2", (3, 0): "=A2+A3"})
    assert run_above(model, 4, 0) == (1, 0, 3, 0)  # stops at the header text


def test_run_above_skips_blanks_just_above(model):
    fill(model, {(0, 0): "1", (1, 0): "", (2, 0): "2", (3, 0): "3"})
    assert run_above(model, 6, 0) == (2, 0, 3, 0)  # stops at the gap in the numbers


def test_run_above_none(model):
    fill(model, {(0, 0): "text"})
    assert run_above(model, 3, 0) is None
    assert run_above(model, 0, 0) is None


def test_run_left(model):
    fill(model, {(2, 0): "x", (2, 1): "4", (2, 2): "5"})
    assert run_left(model, 2, 4) == (2, 1, 2, 2)
    assert run_left(model, 3, 4) is None


@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    yield window
    window.setWindowModified(False)
    window.close()


def select(window, top, left, bottom, right):
    model = window.model
    selection = window.view.selectionModel()
    selection.setCurrentIndex(model.index(top, left), QItemSelectionModel.NoUpdate)
    selection.select(QItemSelection(model.index(top, left), model.index(bottom, right)),
                     QItemSelectionModel.ClearAndSelect)


def click_cell(window, row, col):
    view = window.view
    point = view.visualRect(view.model().index(row, col)).center()
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, point)


def press_sigma(window):
    toolbar = window.findChild(QToolBar)
    QTest.mouseClick(toolbar.widgetForAction(window.autosum_action), Qt.LeftButton)


def test_sigma_is_first_toolbar_button(window):
    toolbar = window.findChild(QToolBar)
    assert toolbar.actions()[0] is window.autosum_action
    assert window.autosum_action.text() == "Σ"


def test_selected_numbers_sum_into_clicked_cell(window):
    model = window.model
    fill(model, {(0, 0): "Qty", (1, 0): "1", (2, 0): "2", (3, 0): "3"})
    select(window, 0, 0, 3, 0)
    press_sigma(window)
    assert window.autosum.pending
    assert window.autosum_action.isChecked()
    assert "Click the cell" in window.statusBar().currentMessage()
    click_cell(window, 5, 2)
    assert model.get_cell(5, 2) == "=SUM(A1:A4)"
    assert model.display_text(5, 2) == "6"
    assert window.view.currentIndex() == model.index(5, 2)
    assert [(i.row(), i.column()) for i in window.view.selectedIndexes()] == [(5, 2)]
    assert window.edit_bar.text() == "=SUM(A1:A4)"
    assert not window.autosum.pending
    assert not window.autosum_action.isChecked()
    assert window.statusBar().currentMessage() == ""


def test_large_selection_uses_a_range(window):
    model = window.model
    fill(model, {(r, 0): str(r + 1) for r in range(100)})
    select(window, 0, 0, 99, 0)
    press_sigma(window)
    click_cell(window, 5, 1)
    assert model.get_cell(5, 1) == "=SUM(A1:A100)"
    assert model.display_text(5, 1) == "5050"


def test_scattered_selection(window):
    model = window.model
    fill(model, {(0, 0): "1", (1, 0): "2", (0, 2): "10"})
    view = window.view
    select(window, 0, 0, 1, 0)
    view.selectionModel().select(QItemSelection(model.index(0, 2), model.index(0, 2)), QItemSelectionModel.Select)
    press_sigma(window)
    click_cell(window, 4, 4)
    assert model.get_cell(4, 4) == "=SUM(A1:A2, C1)"
    assert model.display_text(4, 4) == "13"


def test_click_inside_summed_cells_keeps_waiting(window):
    model = window.model
    fill(model, {(0, 0): "1", (1, 0): "2"})
    select(window, 0, 0, 1, 0)
    press_sigma(window)
    click_cell(window, 1, 0)
    assert model.get_cell(1, 0) == "2"
    assert window.autosum.pending
    assert "outside" in window.statusBar().currentMessage()
    click_cell(window, 2, 0)
    assert model.get_cell(2, 0) == "=SUM(A1:A2)"


def test_escape_cancels_waiting(window):
    model = window.model
    fill(model, {(0, 0): "1"})
    select(window, 0, 0, 0, 0)
    press_sigma(window)
    QTest.keyClick(window.view, Qt.Key_Escape)
    assert not window.autosum.pending
    assert not window.autosum_action.isChecked()
    click_cell(window, 3, 3)
    assert model.get_cell(3, 3) == ""
    assert window.view.currentIndex() == model.index(3, 3)  # clicks select normally again


def test_pressing_sigma_again_cancels(window):
    fill(window.model, {(0, 0): "1"})
    select(window, 0, 0, 0, 0)
    press_sigma(window)
    press_sigma(window)
    assert not window.autosum.pending
    assert not window.autosum_action.isChecked()


def test_sums_numbers_above_current_cell(window):
    model = window.model
    fill(model, {(0, 1): "Price", (1, 1): "2.5", (2, 1): "4"})
    select(window, 3, 1, 3, 1)
    press_sigma(window)
    assert model.get_cell(3, 1) == "=SUM(B2:B3)"
    assert model.display_text(3, 1) == "6.5"
    assert not window.autosum.pending
    assert not window.autosum_action.isChecked()


def test_sums_numbers_left_of_current_cell(window):
    model = window.model
    fill(model, {(2, 0): "Q1", (2, 1): "100", (2, 2): "200"})
    select(window, 2, 3, 2, 3)
    press_sigma(window)
    assert model.get_cell(2, 3) == "=SUM(B3:C3)"


def test_above_takes_priority_over_left(window):
    model = window.model
    fill(model, {(0, 2): "7", (1, 0): "1", (1, 1): "2"})
    select(window, 1, 2, 1, 2)
    press_sigma(window)
    assert model.get_cell(1, 2) == "=SUM(C1)"


def test_selection_takes_priority_over_above(window):
    model = window.model
    fill(model, {(0, 0): "1", (1, 0): "2", (0, 3): "9"})
    select(window, 0, 3, 0, 3)  # current cell D1 holds a number; A1:A2 sit to the left
    press_sigma(window)
    assert window.autosum.pending


def test_nothing_to_sum(window):
    model = window.model
    select(window, 4, 4, 4, 4)
    press_sigma(window)
    assert model.get_cell(4, 4) == ""
    assert "Nothing to sum" in window.statusBar().currentMessage()
    assert not window.autosum_action.isChecked()


def test_sigma_commits_cell_being_edited(window):
    model = window.model
    view = window.view
    select(window, 2, 0, 2, 0)
    QTest.keyClick(view, "5")
    editor = view.viewport().findChild(QLineEdit)
    assert editor is not None
    press_sigma(window)
    # The typed 5 is committed first, so it's a selected number: Σ waits for a click.
    assert model.get_cell(2, 0) == "5"
    assert window.autosum.pending


def test_editing_cancels_waiting(window):
    model = window.model
    fill(model, {(0, 0): "1"})
    select(window, 0, 0, 0, 0)
    press_sigma(window)
    model.set_cell(5, 5, "x")
    assert not window.autosum.pending
