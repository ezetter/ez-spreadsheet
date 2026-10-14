import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtTest import QTest

from py_spread.window import MainWindow

SHIFT_CMD = Qt.ShiftModifier | Qt.ControlModifier  # Cmd is Control to Qt on macOS


@pytest.fixture
def window(app):
    window = MainWindow()
    # Column B: rows 1-5 filled, 6 empty, 7-8 filled. Column C: rows 2-5. Column D: row 5 only.
    window.model.set_cells({(r, 1): str(r) for r in (0, 1, 2, 3, 4, 6, 7)}
                           | {(r, 2): str(r) for r in (1, 2, 3, 4)} | {(4, 3): "x"})
    window.show()
    window.view.setFocus()
    yield window
    window.setWindowModified(False)
    window.close()


def selected(window) -> set:
    return {(i.row(), i.column()) for i in window.view.selectedIndexes()}


def column(col, first, last) -> set:
    return {(row, col) for row in range(first, last + 1)}


def press(window, key, modifiers=SHIFT_CMD):
    QTest.keyClick(window.view, key, modifiers)


def test_up_to_the_first_empty_cell(window):
    window.view.select_range(7, 1, 7, 1)  # B8
    press(window, Qt.Key_Up)
    assert selected(window) == column(1, 6, 7)  # B7:B8; B6 is empty
    assert window.view.currentIndex().row() == 7  # the current cell stays put


def test_up_to_the_top_of_the_sheet(window):
    window.view.select_range(3, 1, 3, 1)  # B4
    press(window, Qt.Key_Up)
    assert selected(window) == column(1, 0, 3)


def test_down_and_on_past_a_gap(window):
    window.view.select_range(0, 1, 0, 1)
    press(window, Qt.Key_Down)
    assert selected(window) == column(1, 0, 4)  # B1:B5
    press(window, Qt.Key_Down)  # next to the empty B6: on to the next filled cell
    assert selected(window) == column(1, 0, 6)
    press(window, Qt.Key_Down)
    assert selected(window) == column(1, 0, 7)


def test_from_an_empty_cell_to_the_next_filled_or_the_edge(window):
    window.view.select_range(10, 1, 10, 1)  # B11, below everything
    press(window, Qt.Key_Up)
    assert selected(window) == column(1, 7, 10)  # up to B8, the first with something in it
    window.view.select_range(10, 5, 10, 5)  # F11: nothing above at all
    press(window, Qt.Key_Up)
    assert selected(window) == column(5, 0, 10)


def test_left_and_right(window):
    window.view.select_range(4, 2, 4, 2)  # C5, in row 5: B5, C5, D5 filled
    press(window, Qt.Key_Right)
    assert selected(window) == {(4, 2), (4, 3)}
    window.view.select_range(4, 3, 4, 3)
    press(window, Qt.Key_Left)
    assert selected(window) == {(4, 1), (4, 2), (4, 3)}
    window.view.select_range(4, 0, 4, 0)  # A5, empty, at the left edge already
    press(window, Qt.Key_Left)
    assert selected(window) == {(4, 0)}


def test_all_the_selected_columns_go_together(window):
    window.view.select_range(4, 1, 4, 3)  # B5:D5, the current cell B5
    press(window, Qt.Key_Up)
    assert selected(window) == column(1, 0, 4) | column(2, 0, 4) | column(3, 0, 4)  # as far as B goes


def test_the_current_cells_column_decides(window):
    window.view.select_range(4, 1, 4, 3)
    window.view.selectionModel().setCurrentIndex(window.model.index(4, 2), QItemSelectionModel.NoUpdate)
    press(window, Qt.Key_Up)  # C goes up to C2 (C1 is empty)
    assert selected(window) == column(1, 1, 4) | column(2, 1, 4) | column(3, 1, 4)
    assert window.view.currentIndex().column() == 2


def test_all_the_selected_rows_go_together(window):
    window.view.select_range(1, 1, 2, 1)  # B2:B3
    press(window, Qt.Key_Right)  # row 2: C2, then D2 is empty
    assert selected(window) == {(1, 1), (1, 2), (2, 1), (2, 2)}


def test_a_taller_selection_extends_from_its_edge(window):
    window.view.select_range(2, 1, 3, 2)  # B3:C4
    press(window, Qt.Key_Down)  # from row 4, B goes on to B5
    assert selected(window) == column(1, 2, 4) | column(2, 2, 4)


def test_arrows_flagged_as_keypad_keys(window):
    window.view.select_range(7, 1, 7, 1)
    press(window, Qt.Key_Up, SHIFT_CMD | Qt.KeypadModifier)  # as macOS sends them
    assert selected(window) == column(1, 6, 7)


def test_other_arrow_keys_still_move(window):
    window.view.select_range(3, 1, 3, 1)
    press(window, Qt.Key_Up, Qt.ShiftModifier)  # Shift alone extends by one cell, as before
    assert selected(window) == column(1, 2, 3)


# --- Cmd+arrow: moving there ---

def current(window) -> tuple[int, int]:
    index = window.view.currentIndex()
    return index.row(), index.column()


def test_cmd_up_moves_through_the_data_and_past_gaps(window):
    window.view.select_range(7, 1, 7, 1)  # B8
    press(window, Qt.Key_Up, Qt.ControlModifier)
    assert current(window) == (6, 1) and selected(window) == {(6, 1)}  # B7, the last before the empty B6
    press(window, Qt.Key_Up, Qt.ControlModifier)
    assert current(window) == (4, 1)  # past the gap, to B5
    press(window, Qt.Key_Up, Qt.ControlModifier)
    assert current(window) == (0, 1)  # through the data to the top
    press(window, Qt.Key_Up, Qt.ControlModifier)
    assert current(window) == (0, 1)  # already at the edge


def test_cmd_down_left_and_right(window):
    window.view.select_range(0, 1, 0, 1)
    press(window, Qt.Key_Down, Qt.ControlModifier)
    assert current(window) == (4, 1)
    press(window, Qt.Key_Right, Qt.ControlModifier)
    assert current(window) == (4, 3)  # B5, C5, D5
    press(window, Qt.Key_Right, Qt.ControlModifier)
    assert current(window) == (4, window.model.columnCount() - 1)  # nothing more: the sheet's edge
    press(window, Qt.Key_Left, Qt.ControlModifier)
    assert current(window) == (4, 3)


def test_cmd_arrow_collapses_a_selection(window):
    window.view.select_range(1, 1, 3, 2)  # B2:C4, current B2
    press(window, Qt.Key_Down, Qt.ControlModifier | Qt.KeypadModifier)  # as macOS sends it
    assert current(window) == (4, 1) and selected(window) == {(4, 1)}


def test_plain_arrows_still_move_one_cell(window):
    window.view.select_range(3, 1, 3, 1)
    press(window, Qt.Key_Up, Qt.NoModifier)
    assert current(window) == (2, 1)
