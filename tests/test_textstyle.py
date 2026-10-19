import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QToolBar

from ezsheet.model import SheetModel
from ezsheet.storage import VERSION, SheetData, SheetFileError, load_sheet, save_sheet
from ezsheet.textstyle import PLAIN, CellStyle, from_json, to_json
from ezsheet.window import MainWindow

BOLD = CellStyle(bold=True)
ITALIC = CellStyle(italic=True)


def test_json():
    assert to_json(CellStyle(True, True)) == {"bold": True, "italic": True}
    assert to_json(BOLD) == {"bold": True}
    assert from_json({"italic": True}) == ITALIC
    assert from_json({}) == PLAIN
    assert from_json({"underline": True}) is None
    assert from_json({"bold": 1}) is None
    assert from_json("bold") is None


@pytest.fixture
def model(app):
    return SheetModel(rows=20, cols=5)


def test_font_role(model):
    model.set_cell(0, 0, "x")
    assert model.data(model.index(0, 0), Qt.FontRole) is None
    model.set_styles({(0, 0): CellStyle(True, True)}, "Bold")
    font = model.data(model.index(0, 0), Qt.FontRole)
    assert font.bold() and font.italic()


def test_plain_style_is_removed(model):
    model.set_styles({(0, 0): BOLD}, "Bold")
    model.set_styles({(0, 0): PLAIN}, "Bold")
    assert model.sheet_data().styles == {}


def test_style_is_undoable(model):
    model.set_styles({(0, 0): BOLD}, "Bold")
    model.undo_stack.undo()
    assert model.cell_style(0, 0) == PLAIN
    model.undo_stack.redo()
    assert model.cell_style(0, 0) == BOLD


def test_styles_saved_and_loaded(tmp_path):
    path = str(tmp_path / "s.ezs")
    sheet = SheetData(10, 5, {(0, 0): "x"}, styles={(0, 0): BOLD, (2, 3): CellStyle(True, True)})
    save_sheet(path, sheet)
    document = json.loads(open(path).read())
    assert document["version"] == VERSION
    assert document["sheets"][0]["styles"] == {"A1": {"bold": True}, "D3": {"bold": True, "italic": True}}
    assert load_sheet(path) == sheet


def test_bad_style_in_file(tmp_path):
    path = tmp_path / "bad.ezs"
    path.write_text(json.dumps({"format": "ezsheet", "version": 3, "rows": 10, "columns": 5,
                                "cells": {}, "styles": {"A1": {"underline": True}}}))
    with pytest.raises(SheetFileError):
        load_sheet(str(path))


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


def toolbar_button(window, text):
    toolbar = window.findChild(QToolBar)
    return next(toolbar.widgetForAction(a) for a in toolbar.actions()
                if not a.isSeparator() and getattr(toolbar.widgetForAction(a), "text", lambda: None)() == text)


def test_bold_button_toggles_selection(window):
    model = window.model
    window.view.select_range(0, 0, 1, 1)
    QTest.mouseClick(toolbar_button(window, "B"), Qt.LeftButton)
    assert all(model.cell_style(r, c).bold for r in range(2) for c in range(2))
    assert window.format_actions["Bold"].isChecked()
    assert window.undo_action.text() == "Undo Bold"
    QTest.mouseClick(toolbar_button(window, "B"), Qt.LeftButton)
    assert model.sheet_data().styles == {}
    assert not window.format_actions["Bold"].isChecked()


def test_toggle_follows_current_cell(window):
    model = window.model
    model.set_styles({(1, 0): BOLD}, "Bold")
    window.view.select_range(0, 0, 1, 0)  # current cell A1 isn't bold, so bold is added
    window.format_actions["Bold"].trigger()
    assert model.cell_style(0, 0).bold and model.cell_style(1, 0).bold


def test_bold_and_italic_combine(window):
    window.view.select_range(0, 0, 0, 0)
    window.format_actions["Bold"].trigger()
    window.format_actions["Italic"].trigger()
    assert window.model.cell_style(0, 0) == CellStyle(True, True)
    window.format_actions["Bold"].trigger()
    assert window.model.cell_style(0, 0) == ITALIC


def test_shortcuts(window):
    assert window.format_actions["Bold"].shortcut() == QKeySequence(QKeySequence.Bold)
    window.view.select_range(2, 2, 2, 2)
    QTest.keyClick(window.view, Qt.Key_B, Qt.ControlModifier)  # Cmd+B on macOS
    QTest.keyClick(window.view, Qt.Key_I, Qt.ControlModifier)
    assert window.model.cell_style(2, 2) == CellStyle(True, True)


def test_buttons_show_current_cell_style(window):
    window.model.set_styles({(3, 3): ITALIC}, "Italic")
    window.view.select_range(3, 3, 3, 3)
    assert window.format_actions["Italic"].isChecked()
    assert not window.format_actions["Bold"].isChecked()
    window.view.select_range(0, 0, 0, 0)
    assert not window.format_actions["Italic"].isChecked()


def test_bold_while_typing_keeps_the_typing(window, app):
    view = window.view
    window.view.select_range(0, 0, 0, 0)
    QTest.keyClick(view, "h")
    editor = view.viewport().findChild(QLineEdit)
    QTest.keyClicks(editor, "i")
    window.format_actions["Bold"].trigger()
    app.processEvents()
    assert window.model.get_cell(0, 0) == "hi"
    assert window.model.cell_style(0, 0).bold


def test_style_survives_retyping_and_delete(window):
    model = window.model
    model.set_styles({(0, 0): BOLD}, "Bold")
    model.set_cell(0, 0, "new")
    window.view.select_range(0, 0, 0, 0)
    QTest.keyClick(window.view, Qt.Key_Delete)
    assert model.cell_style(0, 0).bold


def test_paste_and_move_carry_style(window):
    model = window.model
    model.set_cell(0, 0, "x")
    model.set_styles({(0, 0): BOLD}, "Bold")
    window.view.select_range(0, 0, 0, 0)
    window.clipboard.copy()
    window.view.select_range(2, 2, 2, 2)
    window.clipboard.paste()
    assert model.cell_style(2, 2) == BOLD
    window.view.select_range(0, 0, 0, 0)
    window.clipboard.cut()
    window.view.select_range(4, 4, 4, 4)
    window.clipboard.paste()
    assert model.cell_style(0, 0) == PLAIN
    assert model.cell_style(4, 4) == BOLD


def test_fill_copies_first_cells_style(window):
    model = window.model
    model.set_cell(0, 0, "7")
    model.set_styles({(0, 0): ITALIC}, "Italic")
    window.view.select_range(0, 0, 2, 0)
    window.fill_actions["uniform"].trigger()
    assert all(model.cell_style(r, 0) == ITALIC for r in range(3))


def test_save_and_open_keeps_styles(window, tmp_path):
    window.model.set_cell(0, 0, "x")
    window.model.set_styles({(0, 0): BOLD}, "Bold")
    path = str(tmp_path / "s.ezs")
    window.save_to(path)
    other = MainWindow()
    other.open_path(path)
    assert other.model.cell_style(0, 0) == BOLD
    assert other.format_actions["Bold"].isChecked()


def test_view_menu_shows_and_hides_the_toolbar(window):
    view_menu = [m for m in window.menuBar().actions() if m.text() == "View"][0].menu()
    action = view_menu.actions()[0]
    assert action is window.toolbar_action and action.text() == "Toolbar" and action.isChecked()
    assert view_menu.actions()[1].isSeparator()
    action.trigger()
    assert not window.toolbar.isVisible() and not action.isChecked()
    action.trigger()
    assert window.toolbar.isVisible() and action.isChecked()
    window.toolbar.hide()  # as unchecking it in the toolbar's own right-click menu does
    assert not action.isChecked()
    action.trigger()
    assert window.toolbar.isVisible()


# --- Strikethrough ---

def test_strikethrough_json():
    style = CellStyle(bold=True, strikethrough=True)
    assert to_json(style) == {"bold": True, "strikethrough": True}
    assert from_json(to_json(style)) == style
    assert from_json({"strikethrough": "yes"}) is None


def test_strikethrough_font(app):
    model = SheetModel(rows=3, cols=3)
    model.set_styles({(0, 0): CellStyle(strikethrough=True)}, "Strikethrough")
    assert model.data(model.index(0, 0), Qt.FontRole).strikeOut()


def test_strikethrough_button_and_menu(window):
    model = window.model
    window.view.select_range(0, 0, 1, 0)
    button = toolbar_button(window, "S")
    assert button.font().strikeOut() and button.defaultAction() is window.format_actions["Strikethrough"]
    QTest.mouseClick(button, Qt.LeftButton)
    assert model.cell_style(0, 0).strikethrough and model.cell_style(1, 0).strikethrough
    assert window.format_actions["Strikethrough"].isChecked() and button.isChecked()
    assert window.undo_action.text() == "Undo Strikethrough"
    window.format_actions["Strikethrough"].trigger()  # the current cell has it: off again
    assert model.cell_style(0, 0) == PLAIN
    assert window.format_actions["Strikethrough"].shortcut() == QKeySequence("Ctrl+Shift+X")  # ⇧⌘X


def test_strikethrough_keeps_other_styles(window):
    window.model.set_styles({(0, 0): CellStyle(bold=True, font="Georgia")}, "Styles")
    window.view.select_range(0, 0, 0, 0)
    window.format_actions["Strikethrough"].trigger()
    assert window.model.cell_style(0, 0) == CellStyle(bold=True, font="Georgia", strikethrough=True)
