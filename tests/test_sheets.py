import json

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from ezsheet.errors import CellError
from ezsheet.filtering import ColumnFilter, SheetFilter
from ezsheet.formula import (
    FormulaError,
    move_references,
    parse,
    rename_sheet,
    sheet_prefix,
    shift_references,
    tokenize,
)
from ezsheet.storage import SheetData, SheetFileError, WorkbookData, load_workbook, save_workbook
from ezsheet.window import MainWindow
from ezsheet.workbook import WorkbookModel


# --- In formulas ---

def test_naming_another_sheet():
    assert tokenize("Sheet2!A1+'Q1 Sales'!$B$2") == [
        ("sheet", "Sheet2!"), ("ref", "A1"), ("op", "+"), ("sheet", "'Q1 Sales'!"), ("ref", "$B$2")]
    assert parse("Sheet2!A1") == ("xref", "Sheet2", 0, 0)
    assert parse("'Ann''s'!B3") == ("xref", "Ann's", 2, 1)
    assert parse("SUM(Data!B9:A2)") == ("call", "SUM", [("xrange", "Data", 1, 0, 8, 1)])
    assert parse("SUM(Data!A1:data!B2)") == ("call", "SUM", [("xrange", "Data", 0, 0, 1, 1)])


@pytest.mark.parametrize("text", ["Sheet2!total", "SUM(Data!A1:Other!B2)", "Sheet2!", "Sheet2!(A1)"])
def test_not_another_sheets_cell(text):
    with pytest.raises(FormulaError):
        parse(text)


@pytest.mark.parametrize("title, prefix", [
    ("Sheet2", "Sheet2!"), ("Data_2024", "Data_2024!"), ("Q1 Sales", "'Q1 Sales'!"), ("Ann's", "'Ann''s'!"),
    ("2024", "'2024'!"), ("Café", "Café!"),
])
def test_sheet_prefix(title, prefix):
    assert sheet_prefix(title) == prefix
    assert parse(f"{prefix}A1") == ("xref", title, 0, 0)


def test_copied_formulas_shift_other_sheets_cells_too():
    assert shift_references("=Sheet2!A1+B2+SUM(Sheet2!A1:$B$2)", 1, 1) == "=Sheet2!B2+C3+SUM(Sheet2!B2:$B$2)"
    # This sheet's names don't apply on another: Sheet2!r1 isn't the name r1.
    assert shift_references("=Sheet2!B2+B2", 1, 0, {"B2": (0, 0)}) == "=Sheet2!B3+B2"


def test_references_follow_their_own_sheets_cells():
    down = lambda row, col: (row + 1, col)
    formula = "=Data!A1+A1+SUM(Data!A1:B2)+SUM(A1:A2)"
    assert move_references(formula, down) == "=Data!A1+A2+SUM(Data!A1:B2)+SUM(A2:A3)"  # this sheet's
    assert move_references(formula, down, sheet="DATA", home=False) == "=Data!A2+A1+SUM(Data!A2:B3)+SUM(A1:A2)"
    assert move_references("=Data!A1+A1", down, sheet="Data") == "=Data!A2+A2"  # on Data itself
    gone = lambda row, col: None if row == 0 else (row - 1, col)
    assert move_references("=Data!A1*2+Data!B5", gone, sheet="Data", home=False) == "=#REF!*2+Data!B4"


def test_renamed_sheets_in_formulas():
    assert rename_sheet("=Sheet2!A1+sheet2!B1+Other!A1+A1", "SHEET2", "Q1 Sales") == (
        "='Q1 Sales'!A1+'Q1 Sales'!B1+Other!A1+A1")
    assert rename_sheet("='Q1 Sales'!A1", "q1 sales", "Ann's") == "='Ann''s'!A1"
    assert rename_sheet("=Sheet2!A1+@", "Sheet2", "X") == "=Sheet2!A1+@"  # (doesn't parse: as it is)


# --- In the workbook ---

@pytest.fixture
def book(app):
    book = WorkbookModel(rows=20, cols=6)
    book.set_cells({(0, 0): "5", (1, 0): "7", (2, 0): "x"})
    book.add_sheet()
    return book


def test_formulas_use_other_sheets(book):
    assert book.titles() == ["Sheet1", "Sheet2"] and book.title == "Sheet2" and book.current_index() == 1
    book.set_cells({(0, 0): "=Sheet1!A1*2", (1, 0): "=SUM(SHEET1!A1:A9)", (2, 0): "=Nowhere!A1",
                    (3, 0): "=Sheet1!A3+1", (4, 0): "=Sheet2!A1+1"})
    assert [book.value(row, 0) for row in range(5)] == [10.0, 12.0, CellError("#REF!"), CellError("#VALUE!"), 11.0]
    book.show_index(0)
    book.set_cell(0, 0, "50")  # the other sheet's formulas follow
    assert book.sheets()[1].value(0, 0) == 100.0 and book.sheets()[1].value(1, 0) == 57.0


def test_circular_across_sheets(book):
    book.set_cell(0, 1, "=Sheet1!B1+1")
    book.show_index(0)
    book.set_cell(0, 1, "=Sheet2!B1*2")
    assert book.value(0, 1) == CellError("#CIRC!") and book.sheets()[1].value(0, 1) == CellError("#CIRC!")
    book.set_cell(0, 1, "3")
    assert book.sheets()[1].value(0, 1) == 4.0


def test_add_delete_move_and_undo(book):
    stack = book.undo_stack
    third = book.add_sheet()
    assert book.titles() == ["Sheet1", "Sheet2", "Sheet3"] and book.current_sheet() is third
    book.move_sheet(2, 0)
    assert book.titles() == ["Sheet3", "Sheet1", "Sheet2"] and stack.undoText() == "Move Sheet"
    stack.undo()
    assert book.titles() == ["Sheet1", "Sheet2", "Sheet3"]
    book.set_cell(0, 0, "=Sheet1!A2")
    assert book.delete_sheet(0) and book.titles() == ["Sheet2", "Sheet3"]
    assert book.value(0, 0) == CellError("#REF!")  # (its sheet's gone)
    stack.undo()
    assert book.titles() == ["Sheet1", "Sheet2", "Sheet3"] and book.sheets()[2].value(0, 0) == 7.0
    book.delete_sheet(1)
    book.delete_sheet(1)
    assert not book.delete_sheet(0) and book.titles() == ["Sheet1"]  # not the last
    assert book.new_title() == "Sheet2"


def test_deleting_the_sheet_shown_shows_the_next(book):
    book.add_sheet()
    book.show_index(1)
    book.delete_sheet(1)
    assert book.title == "Sheet3"
    book.delete_sheet(1)
    assert book.title == "Sheet1"


def test_duplicate(book):
    book.show_index(0)
    copy = book.duplicate_sheet(0)
    assert book.titles() == ["Sheet1", "Copy of Sheet1", "Sheet2"] and book.current_sheet() is copy
    assert copy.get_cell(1, 0) == "7"
    assert book.duplicate_sheet(0).title == "Copy of Sheet1 2"


def test_rename_rewrites_formulas(book):
    book.set_cells({(0, 0): "=Sheet1!A1*2", (1, 0): "=SUM(sheet1!A1:A2)"})
    assert book.rename_sheet(0, "  Q1 Sales ") is None
    assert book.titles() == ["Q1 Sales", "Sheet2"] and book.title == "Q1 Sales"  # (shown)
    second = book.sheets()[1]
    assert [second.get_cell(row, 0) for row in range(2)] == ["='Q1 Sales'!A1*2", "=SUM('Q1 Sales'!A1:A2)"]
    assert second.value(1, 0) == 12.0
    assert book.undo_stack.undoText() == "Rename Sheet"
    book.undo_stack.undo()  # one step
    assert book.titles() == ["Sheet1", "Sheet2"] and second.get_cell(0, 0) == "=Sheet1!A1*2"


@pytest.mark.parametrize("title, problem", [
    ("", "A sheet needs a name."), ("   ", "A sheet needs a name."),
    ("sheet2", "There's a sheet named sheet2 already."), ("x" * 101, "A sheet's name can be at most 100 characters."),
])
def test_names_that_wont_do(book, title, problem):
    assert book.rename_sheet(0, title) == problem and book.titles() == ["Sheet1", "Sheet2"]


def test_case_of_its_own_name(book):
    assert book.rename_sheet(0, "SHEET1") is None and book.titles() == ["SHEET1", "Sheet2"]


def test_moving_cells_moves_other_sheets_references(book):
    book.set_cells({(0, 0): "=Sheet1!A2", (1, 0): "=SUM(Sheet1!A1:A2)", (2, 0): "=A1"})
    book.show_index(0)
    book.insert_rows(0)
    second = book.sheets()[1]
    assert [second.get_cell(row, 0) for row in range(3)] == ["=Sheet1!A3", "=SUM(Sheet1!A2:A3)", "=A1"]
    assert second.value(0, 0) == 7.0
    assert book.undo_stack.undoText() == "Insert Row"
    book.undo_stack.undo()  # one step, on this sheet
    assert book.title == "Sheet1" and second.get_cell(0, 0) == "=Sheet1!A2"
    book.delete_rows(1)
    assert second.get_cell(0, 0) == "=#REF!" and second.get_cell(1, 0) == "=SUM(Sheet1!A1:A1)"


def test_undo_goes_to_the_sheet(book):
    changed = []
    book.history_applied.connect(changed.append)
    book.show_index(0)
    book.set_cell(4, 2, "here")
    book.show_index(1)
    book.undo_stack.undo()
    assert book.title == "Sheet1" and book.get_cell(4, 2) == "" and changed == [[(4, 2)]]


def test_each_sheets_signals(book):
    names = []
    book.names_changed.connect(lambda: names.append(book.title))
    book.sheets()[0].name_cell(0, 0, "far")  # not the sheet shown: not passed on
    assert names == []
    book.show_index(0)
    assert names == ["Sheet1"]  # (another sheet shown: its names)


def test_saved_and_opened(book, tmp_path):
    book.set_cell(0, 0, "=Sheet1!A1")
    book.rename_sheet(1, "Totals")
    path = str(tmp_path / "book.ezs")
    save_workbook(path, book.workbook_data())
    document = json.loads(open(path).read())
    assert [sheet["name"] for sheet in document["sheets"]] == ["Sheet1", "Totals"] and document["active"] == 1
    assert document["sheets"][1]["cells"] == {"A1": "=Sheet1!A1"}
    opened = WorkbookModel()
    opened.load_workbook_data(load_workbook(path))
    assert opened.titles() == ["Sheet1", "Totals"] and opened.title == "Totals" and opened.value(0, 0) == 5.0
    assert not opened.undo_stack.canUndo()


def test_older_files_are_one_sheet(tmp_path):
    path = tmp_path / "old.ezs"
    path.write_text(json.dumps({"format": "ezsheet", "version": 9, "rows": 5, "columns": 5, "cells": {"A1": "x"}}))
    book = load_workbook(str(path))
    assert [(sheet.name, sheet.cells) for sheet in book.sheets] == [("Sheet1", {(0, 0): "x"})] and book.active == 0


@pytest.mark.parametrize("document, problem", [
    ({"sheets": []}, "bad sheets"),
    ({"sheets": [{"name": "A", "rows": 5, "columns": 5}], "active": 1}, "bad sheet shown"),
    ({"sheets": [{"name": "A", "rows": 5, "columns": 5}, {"name": "a", "rows": 5, "columns": 5}]},
     "There's a sheet named a already."),
    ({"sheets": [{"name": "", "rows": 5, "columns": 5}]}, "A sheet needs a name."),
])
def test_damaged(tmp_path, document, problem):
    path = tmp_path / "bad.ezs"
    path.write_text(json.dumps({"format": "ezsheet", "version": 10, **document}))
    with pytest.raises(SheetFileError, match=problem):
        load_workbook(str(path))


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.model.set_cells({(0, 0): "Item", (1, 0): "5", (2, 0): "7"})
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def tabs(window):
    bar = window.sheet_tabs
    return [bar.tabText(i) for i in range(bar.count())], bar.currentIndex()


def test_tabs_and_the_add_button(window):
    assert tabs(window) == (["Sheet1"], 0) and not window.sheet_actions["Next Sheet"].isEnabled()
    window.add_sheet_button.click()
    assert tabs(window) == (["Sheet1", "Sheet2"], 1) and window.model.title == "Sheet2"
    assert window.statusBar().currentMessage() == "Added Sheet2. Refer to its cells from other sheets as Sheet2!A1."
    assert window.model.get_cell(0, 0) == "" and window.isWindowModified()
    window.sheet_tabs.setCurrentIndex(0)  # clicking a tab
    assert window.model.title == "Sheet1" and window.model.get_cell(0, 0) == "Item"
    window.add_sheet_action.trigger()  # Insert > Sheet
    assert tabs(window) == (["Sheet1", "Sheet2", "Sheet3"], 2)
    assert window.add_sheet_action.shortcut() == QKeySequence("Shift+F11")


def test_next_and_previous(window):
    window.add_sheet()
    window.sheet_actions["Next Sheet"].trigger()
    assert tabs(window)[1] == 0  # round to the first
    window.sheet_actions["Previous Sheet"].trigger()
    assert tabs(window)[1] == 1
    assert window.sheet_actions["Next Sheet"].shortcut() == QKeySequence(QKeySequence.NextChild)


def test_formula_typed_on_another_sheet(window):
    window.add_sheet()
    window.model.set_cell(0, 0, "=SUM(Sheet1!A1:A9)")
    assert window.model.display_text(0, 0) == "12"
    window.sheet_tabs.setCurrentIndex(0)
    window.model.set_cell(1, 0, "10")
    window.sheet_tabs.setCurrentIndex(1)
    assert window.model.display_text(0, 0) == "17"


def test_each_sheet_keeps_how_it_looks(window):
    view = window.view
    view.horizontalHeader().resizeSection(1, 250)
    view.select_range(1, 0, 2, 0)
    window.add_sheet()
    assert view.horizontalHeader().sectionSize(1) == view.horizontalHeader().defaultSectionSize()
    assert (view.currentIndex().row(), view.currentIndex().column()) == (0, 0)
    view.setCurrentIndex(window.model.index(5, 3))
    window.sheet_tabs.setCurrentIndex(0)
    assert view.horizontalHeader().sectionSize(1) == 250
    assert view.currentIndex().row() == 1 and len(view.selectedIndexes()) == 2
    assert window.cell_label.text() == "A2"
    window.sheet_tabs.setCurrentIndex(1)
    assert (view.currentIndex().row(), view.currentIndex().column()) == (5, 3)


def test_filters_and_merges_stay_on_their_sheets(window):
    model, view = window.model, window.view
    model.set_filter(SheetFilter(0, 0, 0, ((0, ColumnFilter(frozenset({"5"}))),)), "Filter")
    model.set_merges({(5, 0, 5, 2)})
    assert view.isRowHidden(1) and view.columnSpan(5, 0) == 3
    window.add_sheet()
    assert not view.isRowHidden(1) and view.columnSpan(5, 0) == 1 and window.filter_action.text() == "Create a Filter"
    window.sheet_tabs.setCurrentIndex(0)
    assert view.isRowHidden(1) and view.columnSpan(5, 0) == 3 and window.filter_action.text() == "Remove Filter"


def test_rename_by_double_click(window, dialogs):
    window.add_sheet()
    window.model.set_cell(0, 0, "=Sheet1!A2")
    dialogs.sheet_name_answer = "Inputs"
    window.sheet_tabs.tabBarDoubleClicked.emit(0)
    assert dialogs.sheet_name_prompts == ["Sheet1"] and tabs(window) == (["Inputs", "Sheet2"], 0)
    assert window.statusBar().currentMessage() == "Renamed Sheet1 to Inputs."
    assert window.model.sheets()[1].get_cell(0, 0) == "=Inputs!A2"
    dialogs.sheet_name_answer = "sheet2"
    assert not window.rename_sheet(0)
    assert dialogs.errors[-1] == "There's a sheet named sheet2 already."
    dialogs.sheet_name_answer = None  # Cancel
    assert not window.rename_sheet(0) and tabs(window)[0] == ["Inputs", "Sheet2"]


def test_delete(window, dialogs):
    assert not window.delete_sheet()
    assert window.statusBar().currentMessage() == "A spreadsheet needs a sheet, so its only one can't be deleted."
    window.add_sheet()
    assert window.delete_sheet() and dialogs.delete_sheet_prompts == []  # (empty: no asking)
    window.add_sheet()
    dialogs.delete_sheet_answer = False
    assert not window.delete_sheet(0) and dialogs.delete_sheet_prompts == ["Sheet1"]
    dialogs.delete_sheet_answer = True
    assert window.delete_sheet(0) and tabs(window) == (["Sheet2"], 0)
    assert window.statusBar().currentMessage() == (
        "Deleted Sheet1. Formulas that refer to it show #REF!; Undo brings it back.")
    window.undo_action.trigger()
    assert tabs(window) == (["Sheet1", "Sheet2"], 0) and window.model.get_cell(0, 0) == "Item"


def test_tab_menu(window):
    window.add_sheet()
    bar = window.sheet_tabs
    window._show_tab_menu(bar.tabRect(0).center())
    actions = {a.text(): a for a in window.tab_menu.actions() if a.text()}
    assert list(actions) == ["Rename…", "Duplicate", "Delete", "Move Left", "Move Right"]
    assert not actions["Move Left"].isEnabled() and actions["Move Right"].isEnabled()
    actions["Move Right"].trigger()
    window.tab_menu.hide()
    assert tabs(window)[0] == ["Sheet2", "Sheet1"]
    window._show_tab_menu(bar.tabRect(1).center())
    {a.text(): a for a in window.tab_menu.actions()}["Duplicate"].trigger()
    window.tab_menu.hide()
    assert tabs(window) == (["Sheet2", "Sheet1", "Copy of Sheet1"], 2) and window.model.get_cell(1, 0) == "5"


def test_dragging_a_tab_moves_its_sheet(window):
    window.add_sheet()
    window.sheet_tabs.moveTab(1, 0)  # as dragging does
    assert window.model.titles() == ["Sheet2", "Sheet1"] and tabs(window)[0] == ["Sheet2", "Sheet1"]


def test_undo_on_another_sheet_goes_there(window):
    window.view.setCurrentIndex(window.model.index(4, 1))
    window.model.set_cell(4, 1, "new")
    window.add_sheet()
    window.model.undo_stack.undo()  # Add Sheet
    window.model.undo_stack.undo()  # the edit
    assert tabs(window) == (["Sheet1"], 0) and window.model.get_cell(4, 1) == ""
    assert window.view.currentIndex().row() == 4


def test_save_and_open(window, tmp_path):
    window.add_sheet()
    window.model.set_cell(0, 0, "=Sheet1!A2*3")
    path = str(tmp_path / "two.ezs")
    assert window.save_to(path)
    other = MainWindow()
    assert other.open_path(path)
    assert tabs(other) == (["Sheet1", "Sheet2"], 1) and other.model.display_text(0, 0) == "15"
    other.new_file()
    assert tabs(other) == (["Sheet1"], 0) and other.model.get_cell(0, 0) == ""
    other.close()


def test_editing_when_switching_is_kept(window):
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    window.view.setCurrentIndex(window.model.index(3, 0))
    window.edit_bar.setFocus()
    QTest.keyClicks(window.edit_bar, "typed")
    window.add_sheet()
    assert window.model.sheets()[0].get_cell(3, 0) == "typed"
