import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit

from ezsheet.fill import SequenceFill
from ezsheet.model import SheetModel
from ezsheet.storage import SheetData
from ezsheet.window import MainWindow

UNDO = (Qt.Key_Z, Qt.ControlModifier)  # Cmd+Z on macOS
REDO = (Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)


@pytest.fixture
def model(app):
    return SheetModel(rows=20, cols=5)


def test_undo_and_redo_one_cell(model):
    model.set_cell(0, 0, "1")
    model.set_cell(0, 0, "2")
    model.undo_stack.undo()
    assert model.get_cell(0, 0) == "1"
    model.undo_stack.undo()
    assert model.get_cell(0, 0) == ""
    model.undo_stack.redo()
    model.undo_stack.redo()
    assert model.get_cell(0, 0) == "2"


def test_set_cells_is_one_step(model):
    model.set_cells({(r, 0): str(r) for r in range(10)}, "Fill")
    assert model.undo_stack.count() == 1
    assert model.undo_stack.undoText() == "Fill"
    model.undo_stack.undo()
    assert model.sheet_data().cells == {}


def test_no_change_records_nothing(model):
    model.set_cell(0, 0, "x")
    model.set_cell(0, 0, "x")
    model.set_cell(1, 1, "")
    assert model.undo_stack.count() == 1


def test_undo_recalculates_formulas(model):
    model.set_cell(0, 0, "2")
    model.set_cell(0, 1, "=A1*10")
    model.set_cell(0, 0, "5")
    assert model.display_text(0, 1) == "50"
    model.undo_stack.undo()
    assert model.display_text(0, 1) == "20"


def test_history_signal_only_for_undo_and_redo(model):
    seen = []
    model.history_applied.connect(lambda cells: seen.append(sorted(cells)))
    model.set_cells({(0, 0): "a", (2, 1): "b"})
    assert seen == []
    model.undo_stack.undo()
    model.undo_stack.redo()
    assert seen == [[(0, 0), (2, 1)], [(0, 0), (2, 1)]]


def test_loading_clears_history(model):
    model.set_cell(0, 0, "x")
    model.load_sheet_data(SheetData(20, 5, {(1, 1): "loaded"}))
    assert not model.undo_stack.canUndo()


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    window.view.setFocus()
    yield window
    window.setWindowModified(False)
    window.close()


def press(window, key):
    QTest.keyClick(window.view, *key)


def select(window, top, left, bottom, right):
    window.view.select_range(top, left, bottom, right)


def selected(window):
    return sorted((i.row(), i.column()) for i in window.view.selectedIndexes())


def test_cmd_z_undoes_typing(window, app):
    view, model = window.view, window.model
    QTest.keyClick(view, "h")
    editor = view.viewport().findChild(QLineEdit)
    QTest.keyClicks(editor, "i")
    QTest.keyClick(editor, Qt.Key_Return)
    app.processEvents()
    assert model.get_cell(0, 0) == "hi"
    assert window.undo_action.text() == "Undo Typing"
    press(window, UNDO)
    assert model.get_cell(0, 0) == ""
    assert window.redo_action.text() == "Redo Typing"
    press(window, REDO)
    assert model.get_cell(0, 0) == "hi"


def test_menu_items_enable_and_name_the_step(window):
    assert not window.undo_action.isEnabled()
    assert not window.redo_action.isEnabled()
    edit_menu = [m for m in window.menuBar().actions() if m.text() == "Edit"][0].menu()
    assert edit_menu.actions()[:2] == [window.undo_action, window.redo_action]
    window.model.set_cell(0, 0, "x", "Typing")
    assert window.undo_action.isEnabled()
    window.undo_action.trigger()
    assert window.model.get_cell(0, 0) == ""
    assert not window.undo_action.isEnabled()
    assert window.redo_action.isEnabled()


def test_undo_selects_changed_cells(window):
    window.model.set_cells({(5, 1): "a", (7, 2): "b"})
    select(window, 0, 0, 0, 0)
    press(window, UNDO)
    assert window.view.currentIndex() == window.model.index(5, 1)
    assert selected(window) == [(r, c) for r in range(5, 8) for c in range(1, 3)]


def test_undo_delete(window):
    window.model.set_cells({(0, 0): "a", (1, 0): "b"})
    select(window, 0, 0, 1, 0)
    press(window, (Qt.Key_Delete, Qt.NoModifier))
    assert window.model.sheet_data().cells == {}
    assert window.undo_action.text() == "Undo Clear"
    press(window, UNDO)
    assert window.model.sheet_data().cells == {(0, 0): "a", (1, 0): "b"}


def test_undo_paste_and_move(window):
    model = window.model
    model.set_cell(0, 0, "x")
    select(window, 0, 0, 0, 0)
    press(window, (Qt.Key_C, Qt.ControlModifier))
    select(window, 3, 3, 3, 3)
    press(window, (Qt.Key_V, Qt.ControlModifier))
    assert window.undo_action.text() == "Undo Paste"
    press(window, UNDO)
    assert model.get_cell(3, 3) == ""

    select(window, 0, 0, 0, 0)
    press(window, (Qt.Key_X, Qt.ControlModifier))
    select(window, 4, 4, 4, 4)
    press(window, (Qt.Key_V, Qt.ControlModifier))
    assert (model.get_cell(0, 0), model.get_cell(4, 4)) == ("", "x")
    assert window.undo_action.text() == "Undo Move"
    press(window, UNDO)  # one step puts the cut cells back too
    assert (model.get_cell(0, 0), model.get_cell(4, 4)) == ("x", "")


def test_undo_autosum(window):
    model = window.model
    model.set_cells({(0, 0): "1", (1, 0): "2"})
    select(window, 2, 0, 2, 0)
    window.autosum_action.trigger()
    assert model.get_cell(2, 0) == "=SUM(A1:A2)"
    assert window.undo_action.text() == "Undo Sum"
    press(window, UNDO)
    assert model.get_cell(2, 0) == ""


def test_undo_fill(window):
    class Dialogs:
        def sequence(self, initial, count):
            return SequenceFill(1, 5)

    window.fill.dialogs = Dialogs()
    select(window, 0, 0, 4, 0)
    window.fill_actions["sequence"].trigger()
    assert window.model.get_cell(4, 0) == "5"
    assert window.undo_action.text() == "Undo Sequence Fill"
    press(window, UNDO)
    assert window.model.sheet_data().cells == {}


def test_undo_back_to_saved_state_is_unmodified(window, tmp_path):
    model = window.model
    model.set_cell(0, 0, "saved")
    assert window.save_to(str(tmp_path / "s.ezs"))
    assert not window.isWindowModified()
    model.set_cell(0, 0, "changed")
    assert window.isWindowModified()
    press(window, UNDO)
    assert not window.isWindowModified()
    press(window, UNDO)  # before the save
    assert window.isWindowModified()
    press(window, REDO)
    assert not window.isWindowModified()


def test_cmd_z_while_typing_undoes_text_not_cells(window, app):
    view, model = window.view, window.model
    model.set_cell(5, 5, "earlier")
    select(window, 0, 0, 0, 0)
    QTest.keyClick(view, "a")
    editor = view.viewport().findChild(QLineEdit)
    QTest.keyClicks(editor, "bc")
    QTest.keyClick(editor, *UNDO)
    assert model.get_cell(5, 5) == "earlier"
    assert editor.text() != "abc"


def test_open_clears_history(window, tmp_path):
    from ezsheet.storage import save_sheet
    path = str(tmp_path / "s.ezs")
    save_sheet(path, SheetData(1000, 52, {(0, 0): "file"}))
    window.model.set_cell(0, 0, "x")
    window.setWindowModified(False)
    window.open_path(path)
    assert not window.undo_action.isEnabled()
