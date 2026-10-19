import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QToolBar, QToolButton

from ezsheet.autosum import AGGREGATES, aggregate_formula, cell_ranges, run_above, run_left
from ezsheet.model import SheetModel
from ezsheet.window import MainWindow


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


def test_aggregate_formula():
    assert aggregate_formula("SUM", [(0, 0, 99, 0)]) == "=SUM(A1:A100)"
    assert aggregate_formula("MEAN", [(0, 0, 0, 0), (2, 1, 3, 2)]) == "=MEAN(A1, B3:C4)"


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
    """Click the main part of the split button (not its menu arrow)."""
    button = window.autosum_button
    QTest.mouseClick(button, Qt.LeftButton, Qt.NoModifier, QPoint(4, button.height() // 2))


def test_sigma_is_first_toolbar_button(window):
    toolbar = window.findChild(QToolBar)
    assert toolbar.widgetForAction(toolbar.actions()[0]) is window.autosum_button
    assert window.autosum_button.text() == "Σ"
    assert window.autosum_button.popupMode() == QToolButton.MenuButtonPopup
    labels = [a.text().split()[-1] for a in window.autosum_button.menu().actions()]
    assert labels == ["Sum", "Mean", "Median", "Minimum", "Maximum", "Deviation", "Count", "Non-Empty"]
    assert window.aggregate_actions["SUM"].isChecked()


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
    # Several rows and columns: one result per column, spaced like the columns.
    assert [model.get_cell(4, c) for c in (4, 5, 6)] == ["=SUM(A1:A2)", "", "=SUM(C1)"]
    assert model.display_text(4, 6) == "10"


def test_single_row_across_columns_gets_one_total(window):
    model = window.model
    fill(model, {(0, 0): "1", (0, 1): "2", (0, 2): "3"})
    select(window, 0, 0, 0, 2)
    press_sigma(window)
    click_cell(window, 2, 0)
    assert model.get_cell(2, 0) == "=SUM(A1:C1)"
    assert model.get_cell(2, 1) == ""


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


def choose(window, function):
    window.aggregate_actions[function].trigger()


@pytest.mark.parametrize("function, symbol, expected", [
    ("MEAN", "x̄", "5"),
    ("MEDIAN", "x̃", "4"),
    ("STDDEV", "σ", "3.605551275"),
    ("MIN", "min", "2"),
    ("MAX", "max", "9"),
    ("COUNT", "n", "3"),
    ("COUNTA", "nₐ", "3"),
])
def test_choosing_function_runs_it_on_numbers_above(window, function, symbol, expected):
    model = window.model
    fill(model, {(0, 0): "2", (1, 0): "4", (2, 0): "9"})
    select(window, 3, 0, 3, 0)
    choose(window, function)
    assert model.get_cell(3, 0) == f"={function}(A1:A3)"
    assert model.display_text(3, 0) == expected
    assert window.autosum_button.text() == symbol
    assert window.aggregate_actions[function].isChecked()


def test_chosen_function_sticks_for_the_button(window):
    model = window.model
    fill(model, {(0, 0): "1", (0, 1): "3"})
    select(window, 1, 0, 1, 0)
    choose(window, "MEDIAN")  # median of A1 into A2
    select(window, 0, 2, 0, 2)
    press_sigma(window)  # numbers to the left of C1
    assert model.get_cell(0, 2) == "=MEDIAN(A1:B1)"


def test_choosing_while_waiting_switches_function(window):
    model = window.model
    fill(model, {(0, 0): "1", (1, 0): "2", (2, 0): "6"})
    select(window, 0, 0, 2, 0)
    press_sigma(window)
    choose(window, "MEAN")
    assert window.autosum.pending
    assert "mean" in window.statusBar().currentMessage()
    click_cell(window, 0, 2)
    assert model.get_cell(0, 2) == "=MEAN(A1:A3)"
    assert model.display_text(0, 2) == "3"


def test_choosing_function_switches_current_cell(window):
    model = window.model
    fill(model, {(0, 0): "2", (1, 0): "4", (2, 0): "9", (3, 0): "=SUM(A1:A3)"})
    select(window, 3, 0, 3, 0)
    choose(window, "MEAN")
    assert model.get_cell(3, 0) == "=MEAN(A1:A3)"
    assert model.display_text(3, 0) == "5"
    assert not window.autosum.pending
    assert window.edit_bar.text() == "=MEAN(A1:A3)"
    choose(window, "STDDEV")
    assert model.get_cell(3, 0) == "=STDDEV(A1:A3)"


def test_switch_keeps_all_arguments(window):
    model = window.model
    fill(model, {(0, 0): "1", (0, 1): "5", (4, 4): "=sum(A1, B1, 10)"})
    select(window, 4, 4, 4, 4)
    choose(window, "MEDIAN")
    assert model.get_cell(4, 4) == "=MEDIAN(A1, B1, 10)"
    assert model.display_text(4, 4) == "5"


def test_switch_while_editing_the_cell(window, app):
    model = window.model
    view = window.view
    fill(model, {(0, 0): "3", (1, 0): "5"})
    select(window, 2, 0, 2, 0)
    QTest.keyClick(view, "=")
    editor = view.viewport().findChild(QLineEdit)
    QTest.keyClicks(editor, "SUM(A1:A2)")
    choose(window, "MEAN")
    app.processEvents()
    assert model.get_cell(2, 0) == "=MEAN(A1:A2)"
    assert model.display_text(2, 0) == "4"
    assert not window.autosum.pending


def test_choosing_same_function_leaves_cell_alone(window):
    model = window.model
    fill(model, {(0, 0): "1", (1, 0): "=SUM(A1)"})
    select(window, 1, 0, 1, 0)
    choose(window, "SUM")
    assert model.get_cell(1, 0) == "=SUM(A1)"
    assert not window.autosum.pending


def test_compound_formula_is_not_switched(window):
    model = window.model
    fill(model, {(0, 0): "1", (1, 0): "=SUM(A1)*2"})
    select(window, 1, 0, 1, 0)
    choose(window, "MEAN")
    assert model.get_cell(1, 0) == "=SUM(A1)*2"
    assert window.autosum.pending  # a number is selected, so it waits for a click as before


def test_main_button_does_not_switch_cell(window):
    model = window.model
    fill(model, {(0, 0): "1", (1, 0): "=SUM(A1)"})
    select(window, 1, 0, 1, 0)
    window.autosum.set_aggregate(AGGREGATES[1])
    press_sigma(window)
    assert model.get_cell(1, 0) == "=SUM(A1)"
    assert window.autosum.pending


def columns_of_numbers(model):
    """A1:C5 — a header row, then four numbers in each of three columns."""
    fill(model, {(0, 0): "Q1", (0, 1): "Q2", (0, 2): "Q3"})
    for r in range(1, 5):
        for c in range(3):
            model.set_cell(r, c, str(r * (c + 1)))


def test_row_under_columns_gets_a_total_each(window):
    model = window.model
    columns_of_numbers(model)
    select(window, 5, 0, 5, 2)
    press_sigma(window)
    assert [model.get_cell(5, c) for c in range(3)] == ["=SUM(A2:A5)", "=SUM(B2:B5)", "=SUM(C2:C5)"]
    assert [model.display_text(5, c) for c in range(3)] == ["10", "20", "30"]
    assert not window.autosum.pending
    assert window.statusBar().currentMessage() == "Added 3 sum formulas."
    assert window.undo_action.text() == "Undo Sum"
    window.undo_action.trigger()
    assert all(model.get_cell(5, c) == "" for c in range(3))  # one step


def test_choosing_function_for_row_under_columns(window):
    model = window.model
    columns_of_numbers(model)
    select(window, 5, 0, 5, 2)
    choose(window, "MEAN")
    assert [model.get_cell(5, c) for c in range(3)] == ["=MEAN(A2:A5)", "=MEAN(B2:B5)", "=MEAN(C2:C5)"]
    assert [model.display_text(5, c) for c in range(3)] == ["2.5", "5", "7.5"]


def test_switching_a_row_of_totals(window):
    model = window.model
    columns_of_numbers(model)
    select(window, 5, 0, 5, 2)
    press_sigma(window)
    select(window, 5, 0, 5, 2)
    choose(window, "MEDIAN")
    assert [model.get_cell(5, c) for c in range(3)] == ["=MEDIAN(A2:A5)", "=MEDIAN(B2:B5)", "=MEDIAN(C2:C5)"]
    assert not window.autosum.pending  # numbers in the selection didn't start waiting for a click


def test_switching_leaves_other_selected_cells_alone(window):
    model = window.model
    fill(model, {(0, 0): "1", (1, 0): "=SUM(A1)", (1, 1): "=SUM(A1)*2", (1, 2): "note"})
    select(window, 1, 0, 1, 2)
    choose(window, "MEAN")
    assert [model.get_cell(1, c) for c in range(3)] == ["=MEAN(A1)", "=SUM(A1)*2", "note"]


def test_column_right_of_rows_gets_row_totals(window):
    model = window.model
    fill(model, {(0, 0): "1", (0, 1): "2", (1, 0): "3", (1, 1): "4", (2, 0): "5", (2, 1): "6"})
    select(window, 0, 2, 2, 2)
    press_sigma(window)
    assert [model.get_cell(r, 2) for r in range(3)] == ["=SUM(A1:B1)", "=SUM(A2:B2)", "=SUM(A3:B3)"]


def test_totals_do_not_include_each_other(window):
    model = window.model
    fill(model, {(0, 0): "1", (0, 1): "2", (1, 0): "3", (1, 1): "4"})
    select(window, 2, 0, 2, 2)  # C3 has nothing above; to its left are only the new totals
    press_sigma(window)
    assert [model.get_cell(2, c) for c in range(3)] == ["=SUM(A1:A2)", "=SUM(B1:B2)", ""]


def test_label_in_selection_is_kept(window):
    model = window.model
    fill(model, {(0, 1): "4", (1, 1): "5", (2, 0): "Total"})
    select(window, 2, 0, 2, 1)
    press_sigma(window)
    assert [model.get_cell(2, c) for c in range(2)] == ["Total", "=SUM(B1:B2)"]


def test_nothing_to_total_in_selection(window):
    select(window, 3, 3, 3, 5)
    press_sigma(window)
    assert window.model.sheet_data().cells == {}
    assert "Nothing to sum" in window.statusBar().currentMessage()



def test_selected_columns_get_a_result_each(window):
    model = window.model
    columns_of_numbers(model)  # numbers in A2:C5
    select(window, 1, 0, 4, 2)
    press_sigma(window)
    assert "first column" in window.statusBar().currentMessage()
    click_cell(window, 6, 0)
    assert [model.get_cell(6, c) for c in range(3)] == ["=SUM(A2:A5)", "=SUM(B2:B5)", "=SUM(C2:C5)"]
    assert [model.display_text(6, c) for c in range(3)] == ["10", "20", "30"]
    assert sorted((i.row(), i.column()) for i in window.view.selectedIndexes()) == [(6, 0), (6, 1), (6, 2)]
    assert window.view.currentIndex() == model.index(6, 0)
    window.undo_action.trigger()
    assert all(model.get_cell(6, c) == "" for c in range(3))  # one step


def test_column_results_can_go_elsewhere(window):
    model = window.model
    columns_of_numbers(model)
    select(window, 1, 0, 4, 2)
    choose(window, "MEAN")
    click_cell(window, 8, 3)
    assert [model.get_cell(8, c) for c in range(3, 6)] == ["=MEAN(A2:A5)", "=MEAN(B2:B5)", "=MEAN(C2:C5)"]


def test_column_without_numbers_is_skipped(window):
    model = window.model
    fill(model, {(0, 0): "bolt", (1, 0): "nut", (0, 1): "4", (1, 1): "6"})
    select(window, 0, 0, 1, 1)
    press_sigma(window)
    click_cell(window, 3, 0)
    assert [model.get_cell(3, c) for c in range(2)] == ["", "=SUM(B1:B2)"]


def test_column_results_must_not_land_in_selection(window):
    model = window.model
    columns_of_numbers(model)
    select(window, 1, 1, 4, 2)  # B2:C5
    press_sigma(window)
    click_cell(window, 6, 0)  # fine: A7 and B7
    assert [model.get_cell(6, c) for c in range(2)] == ["=SUM(B2:B5)", "=SUM(C2:C5)"]

    select(window, 1, 1, 4, 2)
    press_sigma(window)
    click_cell(window, 4, 0)  # A5 is outside, but B5 would land in the selection
    assert window.autosum.pending
    assert "outside" in window.statusBar().currentMessage()
    assert model.get_cell(4, 0) == "4"


def test_column_results_stop_at_sheet_edge(window):
    model = window.model
    columns_of_numbers(model)
    select(window, 1, 0, 4, 2)
    press_sigma(window)
    last = model.columnCount() - 1
    window.view.scrollTo(model.index(6, last))
    click_cell(window, 6, last)
    assert model.get_cell(6, last) == "=SUM(A2:A5)"


def test_count_non_empty_counts_text_too(window):
    model = window.model
    fill(model, {(0, 0): "East", (1, 0): "West", (2, 0): "=1/0", (0, 1): "x"})
    select(window, 3, 0, 3, 0)
    choose(window, "COUNTA")
    assert model.get_cell(3, 0) == "=COUNTA(A1:A3)" and model.display_text(3, 0) == "3"
    assert window.undo_action.text() == "Undo Count Non-Empty"
    select(window, 0, 0, 1, 1)  # a selection of text: it waits for a click
    press_sigma(window)
    assert window.statusBar().currentMessage() == (
        "Click the cell for the first column's count; the other columns' go to its right. Esc cancels.")
    window.autosum.cancel()
    select(window, 5, 3, 5, 3)
    press_sigma(window)
    assert window.statusBar().currentMessage() == (
        "Nothing to count: select some cells with something in them, or start below or right of them.")


def test_count_only_counts_numbers(window):
    model = window.model
    fill(model, {(0, 0): "East", (1, 0): "West"})
    select(window, 2, 0, 2, 0)
    choose(window, "COUNT")
    assert model.get_cell(2, 0) == ""
    assert window.statusBar().currentMessage() == (
        "Nothing to count: select some numbers, or start below or right of them.")


def test_sigma_button_keeps_its_width(window):
    button = window.autosum_button
    for aggregate in AGGREGATES:  # each fits its width, so the toolbar doesn't shift
        window.autosum.set_aggregate(aggregate)
        window._show_aggregate()
        assert button.sizeHint().width() <= button.minimumWidth()
    window.set_zoom(200)
    assert button.sizeHint().width() <= button.minimumWidth()


def test_sigma_button_stays_zoomed(window):
    size = window.autosum_button.font().pointSizeF()
    window.set_zoom(150)
    window.aggregate_actions["MEAN"].trigger()  # (its action changes: the button takes its font)
    window.autosum_action.setChecked(True)
    assert window.autosum_button.font().pointSizeF() == size * 1.5
    window.set_zoom(100)
    assert window.autosum_button.font().pointSizeF() == size
