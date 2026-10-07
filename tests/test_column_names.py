import json

import pytest
from PySide6.QtCore import QPoint, Qt

from py_spread.fill import UniformFill
from py_spread.formula import move_references, shift_references
from py_spread.model import SheetModel
from py_spread.names import Names, column_syntax_problem, conflict
from py_spread.names_dialog import NameColumnDialog, NamesDialog
from py_spread.storage import SheetData, SheetFileError, load_sheet, save_sheet
from py_spread.window import MainWindow

C = 2  # column C


@pytest.fixture
def model(app):
    """Column C, named t, holds 10, 20, 30; B1 is named x and holds 2."""
    model = SheetModel(rows=20, cols=6)
    model.set_cells({(0, C): "10", (1, C): "20", (2, C): "30", (0, 1): "2"})
    assert model.name_column(C, "t") is None
    assert model.name_cell(0, 1, "x") is None
    return model


# --- Rules ---

@pytest.mark.parametrize("name, ok", [("t", True), ("price", True), ("t_2x", True),
                                      ("t2", False), ("2t", False), ("sum", False)])
def test_column_syntax(name, ok):
    assert (column_syntax_problem(name) is None) == ok


@pytest.mark.parametrize("cells, columns, problem", [
    ({"t": (0, 0)}, {"t": 2}, "names both a cell and a column"),
    ({"t5": (0, 0)}, {"t": 2}, "would mean row 5 of the column named t"),
    ({}, {"t": 2, "u": 2}, "Column C has two names"),
    ({"T5": (0, 0)}, {"t": 2}, None),  # case-sensitive: T5 isn't t's alias
])
def test_conflicts(cells, columns, problem):
    found = conflict(cells, columns)
    assert (found is None) if problem is None else (problem in found)


def test_alias():
    names = Names(columns={"t": 2})
    assert names.alias("t5") == ("t", 4, 2)
    assert names.alias("t12") == ("t", 11, 2)
    assert names.alias("t0") == ("t", -1, 2)
    assert names.alias("tt5") is None and names.alias("T5") is None
    assert "t5" in names and "u5" not in names


# --- In formulas ---

@pytest.mark.parametrize("formula, expected", [
    ("=t1", "10"),
    ("=t3*x", "60"),
    ("=SUM(t1:t3)", "60"),     # aliases as range corners
    ("=MEAN(t1:t2, x)", "10.66666667"),
    ("=$T1", ""),              # with a $, T1 is the cell T1 (outside the sheet's 6 columns: #REF!)
    ("=t0", "#REF!"),
    ("=t", "#NAME?"),          # a bare column name isn't a value
])
def test_aliases_in_formulas(model, formula, expected):
    model.set_cell(5, 4, formula)
    if expected:
        assert model.display_text(5, 4) == expected
    else:
        assert model.display_text(5, 4) == "#REF!"


def test_recalculates_through_alias(model):
    model.set_cell(5, 4, "=x*t2")
    model.set_cell(1, C, "100")
    assert model.display_text(5, 4) == "200"


def test_shift_moves_alias_rows_only():
    names = Names(cells={"x": (0, 1)}, columns={"t": 2})
    assert shift_references("=x*t1", 1, 0, names) == "=x*t2"
    assert shift_references("=x*t1", 3, 5, names) == "=x*t4"         # the column doesn't move
    assert shift_references("=SUM(t1:t3)", 2, 1, names) == "=SUM(t3:t5)"
    assert shift_references("=t1", -1, 0, names) == "=#REF!"
    assert shift_references("=A1+t1", 1, 1, names) == "=B2+t2"


def test_collision_with_alias_gets_a_dollar():
    names = Names(columns={"T": 2})  # column C named T: a bare T5 means $C5
    assert shift_references("=S4", 1, 1, names) == "=$T5"           # the cell, not the alias
    assert shift_references("=SUM(S1:S3)", 0, 1, names) == "=SUM($T1:$T3)"


def test_insert_moves_alias_rows():
    names = Names(columns={"t": 2})

    def move(row, col):  # one cell inserted at C2, shifting column C down
        return (row + 1, col) if col == 2 and row >= 1 else (row, col)

    assert move_references("=t1+t2+t3", move, names=names) == "=t1+t3+t4"


def test_fill_down_continues_aliases(app):
    window = MainWindow()
    model = window.model
    model.set_cells({(0, C): "1", (1, C): "2", (2, C): "3", (0, 1): "10", (0, 4): "=x*t1"})
    model.name_column(C, "t")
    model.name_cell(0, 1, "x")
    window.view.select_range(0, 4, 2, 4)
    window.fill_actions["uniform"].trigger()
    assert [model.get_cell(r, 4) for r in range(3)] == ["=x*t1", "=x*t2", "=x*t3"]
    assert [model.display_text(r, 4) for r in range(3)] == ["10", "20", "30"]
    window.setWindowModified(False)


def test_paste_continues_aliases(app):
    window = MainWindow()
    model = window.model
    model.set_cells({(0, C): "1", (1, C): "2", (0, 4): "=t1*2"})
    model.name_column(C, "t")
    window.view.select_range(0, 4, 0, 4)
    window.clipboard.copy()
    window.view.select_range(1, 5, 1, 5)
    window.clipboard.paste()
    assert model.get_cell(1, 5) == "=t2*2"  # down a row: t2; across a column: still t
    window.setWindowModified(False)


# --- Naming ---

def test_naming_rules(model):
    assert "already names column C" in model.column_name_problem("t", 3)
    assert "already names B1" in model.column_name_problem("x", 3)
    assert "would mean row 4" in model.name_problem("t4", (9, 0))
    assert "already names column C" in model.name_problem("t", (9, 0))


def test_rename_and_remove_column_name(model):
    model.set_cell(5, 4, "=t1")
    model.name_column(C, "u")
    assert model.column_names() == {"u": C}
    assert model.display_text(5, 4) == "#REF!"  # t1 is now cell T1, off this 6-column sheet
    model.name_column(C, "")
    assert model.column_names() == {}


def test_column_naming_is_undoable(app):
    model = SheetModel(rows=20, cols=30)
    model.set_cells({(0, C): "10", (0, 19): "5", (5, 4): "=t1"})  # T1 holds 5
    model.name_column(C, "t")
    assert model.display_text(5, 4) == "10"
    assert model.undo_stack.undoText() == "Name Column"
    model.undo_stack.undo()
    assert model.column_names() == {} and model.display_text(5, 4) == "5"  # back to cell T1
    model.undo_stack.redo()
    assert model.display_text(5, 4) == "10"


def test_dialog_says_what_names_will_mean_afterwards(model):
    dialog = NameColumnDialog(model, C)
    dialog.name.setText("")
    assert "will then mean cells T1, T2" in dialog.note.text()
    from py_spread.names_dialog import NameCellDialog
    cell_dialog = NameCellDialog(model, 0, 1)  # B1, named x
    cell_dialog.name.setText("")
    assert "will then mean #NAME?" in cell_dialog.note.text()


def test_header_shows_name(model):
    assert model.headerData(C, Qt.Horizontal) == "C (t)"
    assert model.headerData(1, Qt.Horizontal) == "B"
    assert model.alias_of(4, C) == "t5"
    assert model.alias_of(0, 1) == "x"


def test_column_names_saved_and_loaded(tmp_path):
    path = str(tmp_path / "s.ezs")
    sheet = SheetData(10, 5, {(0, 2): "1"}, names={"x": (0, 1)}, column_names={"t": 2})
    save_sheet(path, sheet)
    assert json.loads(open(path).read())["column_names"] == {"t": "C"}
    assert load_sheet(path) == sheet


def test_conflicting_names_in_file(tmp_path):
    path = tmp_path / "bad.ezs"
    path.write_text(json.dumps({"format": "ezsheet", "version": 6, "rows": 10, "columns": 5,
                                "cells": {}, "names": {"t5": "A1"}, "column_names": {"t": "C"}}))
    with pytest.raises(SheetFileError, match="don't work together"):
        load_sheet(str(path))


# --- Dialogs and window ---

def test_name_column_dialog(model):
    dialog = NameColumnDialog(model, 3)
    dialog.name.setText("d2")
    assert "can't end with a digit" in dialog.note.text()
    dialog.name.setText("t")
    assert "already names column C" in dialog.note.text()
    dialog.name.setText("d")
    assert "d1 will mean $D1" in dialog.note.text()
    assert dialog.chosen_name() == "d"


def test_names_dialog_includes_columns(model):
    dialog = NamesDialog(model)
    rows = {dialog.table.item(r, 0).text(): (dialog.table.item(r, 1).text(), dialog.table.item(r, 2).text())
            for r in range(dialog.table.rowCount())}
    assert rows == {"x": ("B1", "2"), "t": ("C:C", "Column C")}
    t_row = [r for r in range(dialog.table.rowCount()) if dialog.table.item(r, 0).text() == "t"][0]
    dialog.table.item(t_row, 1).setText("D")
    assert dialog.chosen_names() == ({"x": (0, 1)}, {"t": 3})
    dialog.table.item(t_row, 0).setText("x")
    assert "used twice" in dialog.note.text()


def test_window_names_a_column(app, monkeypatch):
    window = MainWindow()
    window.show()
    monkeypatch.setattr(window, "_ask_column_name", lambda col: "t")
    window.view.select_range(4, C, 4, C)
    assert window.name_column()
    assert window.model.column_names() == {"t": C}
    assert window.cell_label.text() == "C5 (t5)"
    window._show_header_menu(QPoint(window.view.columnViewportPosition(3) + 5, 5))
    assert [a.text() for a in window.header_menu.actions()] == ["Name Column…"]
    assert {i.column() for i in window.view.selectedIndexes()} == {3}
    window.header_menu.hide()
    window.setWindowModified(False)
    window.close()


def test_edit_names_applies_columns(app, monkeypatch):
    window = MainWindow()
    window.model.set_cells({(0, 3): "4", (5, 0): "=d1*2"})
    monkeypatch.setattr(window, "_ask_names", lambda: ({}, {"d": 3}))
    window.edit_names()
    assert window.model.display_text(5, 0) == "8"
    window.setWindowModified(False)
