import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from py_spread.window import MainWindow


@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    yield window
    window.context_menu.hide()
    window.setWindowModified(False)
    window.close()


def cell_point(window, row, col) -> QPoint:
    return window.view.visualRect(window.model.index(row, col)).center()


def right_click(window, row, col):
    point = cell_point(window, row, col)
    QTest.mouseClick(window.view.viewport(), Qt.RightButton, Qt.NoModifier, point)
    window.view.customContextMenuRequested.emit(point)  # what a real right-click also sends


def selected(window):
    return sorted((i.row(), i.column()) for i in window.view.selectedIndexes())


def test_menu_items(window):
    texts = [a.text() for a in window.context_menu.actions()]
    assert texts == ["Cut", "Copy", "Paste", "", "Insert Cells…", "Delete Cells…", "", "Fill",
                     "Name Cell…", "Name Column…", "", "Notebook", "Ask Claude…"]
    actions = window.context_menu.actions()
    assert actions[0] is window.clipboard_actions["Cut"]  # the Edit menu's own actions
    assert actions[4] is window.insert_cells_action
    assert actions[7].menu() is window.fill_menu
    assert [a.text() for a in window.fill_menu.actions()] == ["Random", "Sequence", "Uniform"]


def test_right_click_shows_menu(window):
    right_click(window, 2, 2)
    assert window.context_menu.isVisible()


def test_right_click_inside_selection_keeps_it(window):
    window.view.select_range(1, 1, 3, 2)
    right_click(window, 2, 2)
    assert selected(window) == [(r, c) for r in range(1, 4) for c in range(1, 3)]


def test_right_click_outside_selection_selects_cell(window):
    window.view.select_range(1, 1, 3, 2)
    right_click(window, 6, 4)
    assert selected(window) == [(6, 4)]
    assert window.view.currentIndex() == window.model.index(6, 4)


def test_menu_actions_work_on_selection(window):
    model = window.model
    model.set_cells({(0, 0): "a", (1, 0): "b"})
    window.view.select_range(0, 0, 0, 0)
    right_click(window, 0, 0)
    window.clipboard_actions["Copy"].trigger()
    window.context_menu.hide()
    right_click(window, 4, 4)
    window.clipboard_actions["Paste"].trigger()
    assert model.get_cell(4, 4) == "a"
