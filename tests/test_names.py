import json

import pytest

from ezsheet import names
from ezsheet.model import SheetModel
from ezsheet.names_dialog import DELETED, NameCellDialog, NamesDialog
from ezsheet.storage import SheetData, SheetFileError, load_sheet, save_sheet
from ezsheet.window import MainWindow


@pytest.fixture
def model(app):
    model = SheetModel(rows=20, cols=6)
    model.set_cell(1, 1, "3")  # B2
    return model


# --- Rules ---

@pytest.mark.parametrize("name, problem", [
    ("r", None), ("tax_rate", None), ("_x", None), ("Radius2b", None),
    ("", "Enter a name"),
    ("2r", "must start with a letter"),
    ("my rate", "must start with a letter"),
    ("x1", None), ("A1", None), ("AB12", None),   # names may look like cell references
    ("sum", "is a function"),
    ("Pi", "is a constant"),
    ("a" * 65, "at most 64"),
])
def test_syntax(name, problem):
    found = names.syntax_problem(name)
    assert (found is None) if problem is None else (problem in found)


# --- In formulas ---

def test_name_in_formula(model):
    assert model.name_cell(1, 1, "r") is None
    model.set_cell(0, 0, "=PI*r^2")
    assert model.value(0, 0) == pytest.approx(3.141592653589793 * 9)
    model.set_cell(1, 1, "2")  # recalculates through the name
    assert model.value(0, 0) == pytest.approx(3.141592653589793 * 4)


def test_names_are_case_sensitive(model):
    model.set_cell(2, 1, "10")
    assert model.name_cell(1, 1, "r") is None
    assert model.name_cell(2, 1, "R") is None  # a different name
    model.set_cell(0, 0, "=r+R")
    assert model.display_text(0, 0) == "13"
    model.set_cell(0, 1, "=rate")
    assert model.display_text(0, 1) == "#NAME?"
    assert "already names B2" in model.name_problem("r", (4, 4))


def test_name_is_a_fixed_reference_when_copied(app):
    from ezsheet.window import MainWindow
    window = MainWindow()
    model = window.model
    model.set_cells({(1, 1): "3", (0, 0): "=r*2"})
    model.name_cell(1, 1, "r")
    window.view.select_range(0, 0, 0, 0)
    window.clipboard.copy()
    window.view.select_range(5, 3, 5, 3)
    window.clipboard.paste()
    assert model.get_cell(5, 3) == "=r*2" and model.display_text(5, 3) == "6"
    window.setWindowModified(False)


def test_unknown_name_is_name_error(model):
    model.set_cell(0, 0, "=nothing+1")
    assert model.display_text(0, 0) == "#NAME?"


def test_name_can_be_used_in_functions(model):
    model.set_cells({(2, 1): "5"})
    model.name_cell(2, 1, "b")
    model.name_cell(1, 1, "a")
    model.set_cell(0, 0, "=SUM(a, b) + POW(b, 2)")
    assert model.display_text(0, 0) == "33"


def test_one_name_per_cell_and_renaming(model):
    model.set_cell(0, 0, "=r+1")
    model.name_cell(1, 1, "r")
    assert model.name_cell(1, 1, "radius") is None
    assert model.cell_names() == {"radius": (1, 1)}
    assert model.display_text(0, 0) == "#NAME?"  # the old name is gone
    model.name_cell(1, 1, "")
    assert model.cell_names() == {} and model.name_of(1, 1) is None


def test_reusing_a_name_is_refused(model):
    model.name_cell(1, 1, "r")
    assert "already names B2" in model.name_cell(4, 4, "r")
    assert model.cell_names() == {"r": (1, 1)}


def test_naming_is_undoable(model):
    model.set_cell(0, 0, "=r*10")
    model.name_cell(1, 1, "r")
    assert model.display_text(0, 0) == "30"
    assert model.undo_stack.undoText() == "Name Cell"
    model.undo_stack.undo()
    assert model.cell_names() == {} and model.display_text(0, 0) == "#NAME?"
    model.undo_stack.redo()
    assert model.display_text(0, 0) == "30"


def test_names_move_with_inserted_cells(model):
    model.set_cell(0, 3, "=r*2")
    model.name_cell(1, 1, "r")
    model.insert_cells(0, 1, 0, 1, "down")  # B2 moves to B3
    assert model.cell_names() == {"r": (2, 1)}
    assert model.display_text(0, 3) == "6"
    model.undo_stack.undo()
    assert model.cell_names() == {"r": (1, 1)}


def test_deleting_the_named_cell_gives_ref_error(model):
    model.set_cell(0, 3, "=r*2")
    model.name_cell(1, 1, "r")
    model.delete_cells(1, 1, 1, 1, "up")
    assert model.cell_names() == {"r": None}
    assert model.display_text(0, 3) == "#REF!"


def test_replace_names(model):
    model.set_cells({(2, 2): "10", (0, 0): "=a+b"})
    model.name_cell(1, 1, "a")
    model.replace_names({"a": (2, 2), "b": (1, 1)}, "Edit Names")
    assert model.display_text(0, 0) == "13"
    model.undo_stack.undo()
    assert model.cell_names() == {"a": (1, 1)}


# --- Saving ---

def test_names_saved_and_loaded(tmp_path):
    path = str(tmp_path / "s.ezs")
    sheet = SheetData(10, 5, {(1, 1): "3"}, names={"r": (1, 1), "gone": None})
    save_sheet(path, sheet)
    assert json.loads(open(path).read())["names"] == {"gone": None, "r": "B2"}
    assert load_sheet(path) == sheet


@pytest.mark.parametrize("bad", [{"sum": "A1"}, {"2r": "B2"}, {"a": "A1", "b": "A1"}, {"r": "nowhere"}])
def test_bad_names_in_file(tmp_path, bad):
    path = tmp_path / "bad.ezs"
    path.write_text(json.dumps({"format": "ezsheet", "version": 5, "rows": 10, "columns": 5,
                                "cells": {}, "names": bad}))
    with pytest.raises(SheetFileError):
        load_sheet(str(path))


def test_loading_restores_names(app, tmp_path):
    path = str(tmp_path / "s.ezs")
    save_sheet(path, SheetData(10, 5, {(1, 1): "4", (0, 0): "=r^2"}, names={"r": (1, 1)}))
    model = SheetModel()
    model.load_sheet_data(load_sheet(path))
    assert model.display_text(0, 0) == "16"


# --- Dialogs ---

def test_name_cell_dialog(model):
    dialog = NameCellDialog(model, 1, 1)
    ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
    assert not ok.isEnabled()
    dialog.name.setText("Sum")
    assert not ok.isEnabled() and "is a function" in dialog.note.text()
    dialog.name.setText("radius")
    assert ok.isEnabled() and dialog.chosen_name() == "radius"


def test_name_cell_dialog_existing_name(model):
    model.name_cell(1, 1, "r")
    model.name_cell(2, 2, "taken")
    dialog = NameCellDialog(model, 1, 1)
    assert dialog.name.text() == "r"
    dialog.name.setText("")
    assert "removes the name r" in dialog.note.text()
    dialog.name.setText("taken")
    assert "already names C3" in dialog.note.text()


def test_names_dialog_lists_and_edits(model):
    model.set_cell(2, 2, "7")
    model.name_cell(1, 1, "r")
    model.name_cell(2, 2, "h")
    dialog = NamesDialog(model)
    rows = [[dialog.table.item(r, c).text() for c in range(3)] for r in range(dialog.table.rowCount())]
    assert rows == [["h", "C3", "7"], ["r", "B2", "3"]]
    dialog.table.item(1, NamesDialog.CELL).setText("C3")
    assert "C3 has two names" in dialog.note.text()
    dialog.table.item(1, NamesDialog.CELL).setText("D1")
    assert dialog.table.item(1, NamesDialog.VALUE).text() == ""
    dialog.table.selectRow(0)
    dialog.delete_selected()
    assert dialog.chosen_names() == ({"r": (0, 3)}, {})


def test_names_dialog_add_and_duplicates(model):
    model.name_cell(1, 1, "r")
    dialog = NamesDialog(model)
    dialog.add_name()
    assert "Enter a name" in dialog.note.text()
    row = dialog.table.rowCount() - 1
    dialog.table.item(row, NamesDialog.NAME).setText("r")
    dialog.table.item(row, NamesDialog.CELL).setText("E5")
    assert "used twice" in dialog.note.text()
    dialog.table.item(row, NamesDialog.NAME).setText("s")
    assert dialog.chosen_names() == ({"r": (1, 1), "s": (4, 4)}, {})


def test_names_dialog_shows_deleted(model):
    model.name_cell(1, 1, "r")
    model.delete_cells(1, 1, 1, 1, "up")
    dialog = NamesDialog(model)
    assert dialog.table.item(0, NamesDialog.CELL).text() == DELETED
    assert "deleted" in dialog.note.text()
    assert dialog.chosen_names() == ({"r": None}, {})


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def test_menus(window):
    formulas = [m for m in window.menuBar().actions() if m.text() == "Formulas"][0].menu()
    texts = [a.text() for a in formulas.actions()]
    assert "Name Cell…" in texts and "Names…" in texts
    assert window.name_cell_action in window.context_menu.actions()


def test_naming_from_the_window(window, monkeypatch):
    window.model.set_cell(1, 1, "3")
    window.view.select_range(1, 1, 1, 1)
    monkeypatch.setattr(window, "_ask_cell_name", lambda row, col: "r")
    assert window.name_cell()
    assert window.model.cell_names() == {"r": (1, 1)}
    assert window.cell_label.text() == "B2 (r)"
    window.model.undo_stack.undo()
    assert window.cell_label.text() == "B2"


def test_cancelled_dialogs_change_nothing(window, monkeypatch):
    monkeypatch.setattr(window, "_ask_cell_name", lambda row, col: None)
    monkeypatch.setattr(window, "_ask_names", lambda: None)
    assert not window.name_cell() and not window.edit_names()
    assert not window.model.undo_stack.canUndo()


def test_editing_names_from_the_window(window, monkeypatch):
    window.model.set_cells({(0, 0): "2", (5, 0): "=k*3"})
    monkeypatch.setattr(window, "_ask_names", lambda: ({"k": (0, 0)}, {}))
    window.edit_names()
    assert window.model.display_text(5, 0) == "6"
    assert window.undo_action.text() == "Undo Edit Names"



# --- Names spelled like cells ---

@pytest.fixture
def a1_named(app):
    """A1 holds 100; the name A1 means C5, which holds 7."""
    model = SheetModel(rows=20, cols=6)
    model.set_cells({(0, 0): "100", (4, 2): "7"})
    assert model.name_cell(4, 2, "A1") is None
    return model


@pytest.mark.parametrize("formula, expected", [
    ("=A1", "7"),            # bare: the name
    ("=$A1", "100"),         # any $: the cell
    ("=A$1", "100"),
    ("=$A$1", "100"),
    ("=a1", "100"),          # names are case-sensitive, so a1 is the cell
    ("=SUM(A1:A1)", "100"),  # ranges are always cells
    ("=SUM(A1)", "7"),       # a single argument is the name
])
def test_name_spelled_like_a_cell(a1_named, formula, expected):
    a1_named.set_cell(9, 5, formula)
    assert a1_named.display_text(9, 5) == expected


def test_copying_keeps_names_and_escapes_collisions(app):
    window = MainWindow()
    model = window.model
    model.set_cells({(0, 0): "100", (4, 2): "7", (1, 1): "=A2+A1"})  # B2: A2 is a cell, A1 the name
    model.name_cell(4, 2, "A1")
    window.view.select_range(1, 1, 1, 1)
    window.clipboard.copy()
    window.view.select_range(0, 1, 0, 1)  # one row up: A2 becomes A1, which is a name
    window.clipboard.paste()
    assert model.get_cell(0, 1) == "=$A1+A1"   # so the cell gets a $; the name stays put
    assert model.display_text(0, 1) == "107"
    window.setWindowModified(False)


def test_inserting_cells_keeps_names_and_escapes_collisions(a1_named):
    model = a1_named
    model.set_cells({(3, 3): "=A2*A1"})          # D4: cell A2 times name A1
    model.delete_cells(0, 0, 0, 0, "up")          # A2 moves up to A1
    assert model.get_cell(3, 3) == "=$A1*A1"


def test_clicking_a_shadowed_cell_inserts_it_with_a_dollar(app):
    window = MainWindow()
    window.model.name_cell(4, 2, "B2")
    assert window.model.reference_text(1, 1) == "$B2"
    assert window.model.reference_text(1, 2) == "C2"
    window.setWindowModified(False)


def test_autosum_single_cell_escapes_collision(a1_named):
    from ezsheet.autosum import aggregate_formula
    assert aggregate_formula("SUM", [(0, 0, 0, 0)], a1_named.name_set()) == "=SUM($A1)"
    assert aggregate_formula("SUM", [(0, 0, 2, 0)], a1_named.name_set()) == "=SUM(A1:A3)"
