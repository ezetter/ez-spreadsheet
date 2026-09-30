import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from py_spread.model import SheetModel, cell_name, column_name
from py_spread.window import MainWindow


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


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
