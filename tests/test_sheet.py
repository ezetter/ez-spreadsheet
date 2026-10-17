import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit

from ezsheet.model import SheetModel
from ezsheet.references import cell_name, column_index, column_name, parse_cell_name
from ezsheet.window import MainWindow


@pytest.mark.parametrize("col, name", [(0, "A"), (25, "Z"), (26, "AA"), (51, "AZ"), (701, "ZZ"), (702, "AAA")])
def test_column_name(col, name):
    assert column_name(col) == name


def test_cell_name():
    assert cell_name(0, 0) == "A1"
    assert cell_name(9, 27) == "AB10"


def test_model_stores_and_clears_text(app):
    model = SheetModel(rows=10, cols=5)
    model.setData(model.index(2, 3), "hello 42")
    assert model.data(model.index(2, 3)) == "hello 42"
    assert model.data(model.index(0, 0)) == ""
    model.setData(model.index(2, 3), "")
    assert model._cells == {}


def test_typing_into_grid_commits_and_moves_down(app):
    window = MainWindow()
    window.show()
    view = window.view
    window.model.set_cell(0, 0, "old")
    QTest.keyClick(view, "a")  # first keystroke opens the editor, replacing the old text
    editor = view.viewport().findChild(QLineEdit)
    QTest.keyClicks(editor, "bc123")
    QTest.keyClick(editor, Qt.Key_Return)
    app.processEvents()  # the delegate commits via a queued call
    assert window.model.get_cell(0, 0) == "abc123"
    assert view.currentIndex().row() == 1


def test_edit_bar_commits_to_current_cell(app):
    window = MainWindow()
    window.show()
    window.view.setCurrentIndex(window.model.index(4, 2))
    assert window.cell_label.text() == "C5"
    window.edit_bar.setText("Widget")
    QTest.keyClick(window.edit_bar, Qt.Key_Return)
    assert window.model.get_cell(4, 2) == "Widget"


def test_delete_clears_selection(app):
    window = MainWindow()
    window.show()
    window.model.set_cell(0, 0, "x")
    window.model.set_cell(1, 0, "y")
    window.view.selectColumn(0)
    QTest.keyClick(window.view, Qt.Key_Delete)
    assert window.model._cells == {}


@pytest.mark.parametrize("name", ["A", "Z", "AA", "AZ", "ZZ", "AAA"])
def test_column_index_round_trips(name):
    assert column_name(column_index(name)) == name


def test_parse_cell_name():
    assert parse_cell_name("B3") == (2, 1)
    assert parse_cell_name("$ab$10") == (9, 27)


def cell_center(view, row, col):
    return view.visualRect(view.model().index(row, col)).center()


def click_cell(view, row, col):
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, cell_center(view, row, col))


@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    yield window
    window.close()


def open_cell_editor(window, text):
    """Type into the current cell, as a user would, and return the editor."""
    view = window.view
    QTest.keyClick(view, text[0])
    editor = view.viewport().findChild(QLineEdit)
    QTest.keyClicks(editor, text[1:])
    return editor


def test_clicking_cells_builds_formula_in_cell_editor(window, app):
    view, model = window.view, window.model
    model.set_cell(0, 0, "2")   # A1
    model.set_cell(1, 1, "5")   # B2
    view.setCurrentIndex(model.index(3, 3))  # D4
    editor = open_cell_editor(window, "=")
    click_cell(view, 0, 0)
    assert editor.text() == "=A1"
    QTest.keyClicks(editor, "+")
    click_cell(view, 1, 1)
    assert editor.text() == "=A1+B2"
    assert window.edit_bar.text() == "=A1+B2"
    assert view.currentIndex() == model.index(3, 3)
    QTest.keyClick(editor, Qt.Key_Return)
    app.processEvents()
    assert model.get_cell(3, 3) == "=A1+B2"
    assert model.display_text(3, 3) == "7"
    assert view.currentIndex() == model.index(4, 3)


def test_clicking_again_replaces_inserted_reference(window):
    view = window.view
    editor = open_cell_editor(window, "=1+")
    click_cell(view, 1, 1)
    click_cell(view, 2, 2)
    assert editor.text() == "=1+C3"


def test_clicking_after_operand_commits_and_moves(window, app):
    view, model = window.view, window.model
    open_cell_editor(window, "=1+2")
    click_cell(view, 5, 2)
    app.processEvents()
    assert model.display_text(0, 0) == "3"
    assert view.currentIndex() == model.index(5, 2)


def test_parentheses_accept_references(window, app):
    view, model = window.view, window.model
    model.set_cell(0, 1, "3")   # B1
    model.set_cell(0, 2, "4")   # C1
    view.setCurrentIndex(model.index(1, 0))
    editor = open_cell_editor(window, "=(")
    click_cell(view, 0, 1)
    QTest.keyClicks(editor, "+")
    click_cell(view, 0, 2)
    QTest.keyClicks(editor, ")*2")
    QTest.keyClick(editor, Qt.Key_Return)
    app.processEvents()
    assert model.display_text(1, 0) == "14"


def test_clicking_cells_builds_formula_in_edit_bar(window):
    view, model, bar = window.view, window.model, window.edit_bar
    model.set_cell(0, 0, "10")
    view.setCurrentIndex(model.index(2, 2))
    bar.setFocus()
    QTest.keyClicks(bar, "=")
    click_cell(view, 0, 0)
    QTest.keyClicks(bar, "/4")
    assert bar.text() == "=A1/4"
    assert bar.hasFocus()
    QTest.keyClick(bar, Qt.Key_Return)
    assert model.display_text(2, 2) == "2.5"


def test_leaving_edit_bar_commits(window, app):
    view, model, bar = window.view, window.model, window.edit_bar
    bar.setFocus()
    QTest.keyClicks(bar, "=6*7")
    click_cell(view, 4, 4)
    app.processEvents()
    assert model.display_text(0, 0) == "42"
    assert view.currentIndex() == model.index(4, 4)


def test_escape_in_cell_editor_reverts(window, app):
    view, model = window.view, window.model
    model.set_cell(0, 0, "keep")
    editor = open_cell_editor(window, "=1+")
    QTest.keyClick(editor, Qt.Key_Escape)
    app.processEvents()
    assert model.get_cell(0, 0) == "keep"
    assert window.edit_bar.text() == "keep"
    assert view.focusPolicy() == Qt.StrongFocus
