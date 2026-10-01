import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from py_spread.clipboard import from_tsv, to_tsv
from py_spread.window import MainWindow

COPY = (Qt.Key_C, Qt.ControlModifier)  # Qt maps Control to Cmd on macOS
CUT = (Qt.Key_X, Qt.ControlModifier)
PASTE = (Qt.Key_V, Qt.ControlModifier)


@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    window.view.setFocus()
    yield window
    window.close()


def press(window, key):
    QTest.keyClick(window.view, *key)


def select(window, top, left, bottom, right):
    model = window.model
    window.view.selectionModel().setCurrentIndex(model.index(top, left), QItemSelectionModel.NoUpdate)
    window.view.selectionModel().select(
        QItemSelection(model.index(top, left), model.index(bottom, right)),
        QItemSelectionModel.ClearAndSelect,
    )


def go(window, row, col):
    select(window, row, col, row, col)


def test_tsv_round_trip():
    rows = [["a", "1"], ["", "=B2"]]
    assert from_tsv(to_tsv(rows)) == rows
    assert from_tsv("x\ty\r\nz\n") == [["x", "y"], ["z"]]


def test_copy_paste_block(window):
    model = window.model
    model.set_cell(0, 0, "a")
    model.set_cell(0, 1, "b")
    model.set_cell(1, 0, "1")
    model.set_cell(1, 1, "2")
    select(window, 0, 0, 1, 1)
    press(window, COPY)
    assert QApplication.clipboard().text() == "a\tb\n1\t2"
    assert window.view.marquee == (0, 0, 1, 1)
    go(window, 5, 3)
    press(window, PASTE)
    assert [model.get_cell(r, c) for r in (5, 6) for c in (3, 4)] == ["a", "b", "1", "2"]
    assert model.get_cell(0, 0) == "a"  # copy leaves the source alone
    assert window.view.marquee == (0, 0, 1, 1)  # can paste again


def test_paste_shifts_relative_references(window):
    model = window.model
    model.set_cell(0, 0, "2")         # A1
    model.set_cell(1, 0, "3")         # A2
    model.set_cell(0, 1, "=A1*10")    # B1
    model.set_cell(0, 2, "=$A$1*10")  # C1
    select(window, 0, 1, 0, 2)
    press(window, COPY)
    go(window, 1, 1)
    press(window, PASTE)
    assert model.get_cell(1, 1) == "=A2*10"
    assert model.get_cell(1, 2) == "=$A$1*10"
    assert model.display_text(1, 1) == "30"
    assert model.display_text(1, 2) == "20"


def test_single_cell_fills_selection(window):
    model = window.model
    model.set_cell(0, 0, "1")
    model.set_cell(0, 1, "=A1+1")
    go(window, 0, 1)
    press(window, COPY)
    select(window, 1, 1, 3, 1)
    press(window, PASTE)
    assert [model.get_cell(r, 1) for r in (1, 2, 3)] == ["=A2+1", "=A3+1", "=A4+1"]


def test_cut_moves_cells_on_paste(window):
    model = window.model
    model.set_cell(0, 0, "5")
    model.set_cell(0, 1, "=A1*2")
    select(window, 0, 0, 0, 1)
    press(window, CUT)
    assert model.get_cell(0, 0) == "5"  # nothing removed until pasted
    go(window, 4, 0)
    press(window, PASTE)
    assert model.get_cell(0, 0) == "" and model.get_cell(0, 1) == ""
    assert model.get_cell(4, 0) == "5"
    assert model.get_cell(4, 1) == "=A1*2"  # moved formulas keep their references
    assert window.view.marquee is None


def test_cut_and_paste_overlapping(window):
    model = window.model
    for r, text in enumerate("abc"):
        model.set_cell(r, 0, text)
    select(window, 0, 0, 2, 0)
    press(window, CUT)
    go(window, 1, 0)
    press(window, PASTE)
    assert [model.get_cell(r, 0) for r in range(4)] == ["", "a", "b", "c"]


def test_escape_cancels_cut(window):
    model = window.model
    model.set_cell(0, 0, "x")
    go(window, 0, 0)
    press(window, CUT)
    press(window, (Qt.Key_Escape, Qt.NoModifier))
    assert window.view.marquee is None
    go(window, 3, 3)
    press(window, PASTE)  # pastes the clipboard text; the source stays
    assert model.get_cell(0, 0) == "x"
    assert model.get_cell(3, 3) == "x"


def test_editing_abandons_cut(window):
    model = window.model
    model.set_cell(0, 0, "x")
    go(window, 0, 0)
    press(window, CUT)
    model.set_cell(5, 5, "edit")
    assert window.view.marquee is None
    go(window, 3, 3)
    press(window, PASTE)
    assert model.get_cell(0, 0) == "x"


def test_paste_external_text(window):
    model = window.model
    QApplication.clipboard().setText("name\tqty\nbolt\t=B3*2\n")
    go(window, 1, 1)
    press(window, PASTE)
    assert model.get_cell(1, 1) == "name"
    assert model.get_cell(2, 2) == "=B3*2"  # outside text is pasted as-is
    selected = {(i.row(), i.column()) for i in window.view.selectedIndexes()}
    assert selected == {(1, 1), (1, 2), (2, 1), (2, 2)}


def test_copy_puts_displayed_values_on_clipboard(window):
    model = window.model
    model.set_cell(0, 0, "=6*7")
    go(window, 0, 0)
    press(window, COPY)
    assert QApplication.clipboard().text() == "42"
    go(window, 0, 1)
    press(window, PASTE)
    assert model.get_cell(0, 1) == "=6*7"  # but internally the formula is kept


def test_paste_is_clipped_at_sheet_edge(window):
    model = window.model
    QApplication.clipboard().setText("a\tb\tc")
    go(window, 0, model.columnCount() - 1)
    press(window, PASTE)
    assert model.get_cell(0, model.columnCount() - 1) == "a"


def test_shortcuts_in_cell_editor_act_on_text(window, app):
    model = window.model
    view = window.view
    model.set_cell(0, 1, "keep")
    QTest.keyClick(view, "h")
    editor = view.viewport().findChild(type(window.edit_bar))
    QTest.keyClicks(editor, "ello")
    editor.selectAll()
    QTest.keyClick(editor, Qt.Key_C, Qt.ControlModifier)
    assert QApplication.clipboard().text() == "hello"
    assert view.marquee is None
