"""Degrees or radians for SIN, COS, and TAN: calculation, undo, files, the
window's controls, and what Claude is told."""

import json

import pytest
from PySide6.QtTest import QTest

from py_spread.claude import ClaudeSession, SheetAccess, selection_csv
from py_spread.functions import DEGREES, RADIANS
from py_spread.model import SheetModel
from py_spread.storage import SheetData, SheetFileError, load_sheet, save_sheet
from py_spread.window import MainWindow

from test_claude import FakeClient, FakeStream, Recorder, message, text_event


@pytest.fixture
def sheet(app):
    model = SheetModel(rows=20, cols=6)
    model.set_cell(0, 0, "30")  # A1
    return model


def show(sheet, formula, unit):
    sheet.set_angle_unit(unit)
    sheet.set_cell(0, 2, formula)
    return sheet.display_text(0, 2)


# --- Calculation ---

@pytest.mark.parametrize("formula, expected", [
    ("=SIN(PI/6)", "0.5"),
    ("=SIN(PI/2)", "1"),
    ("=SIN(PI)", "0"),
    ("=SIN(-PI)", "0"),
    ("=SIN(3*PI/2)", "-1"),
    ("=SIN(1)", "0.8414709848"),
    ("=SIN(A1*PI/180)", "0.5"),          # degrees in a cell, converted
    ("=COS(0)", "1"),
    ("=COS(PI/3)", "0.5"),
    ("=COS(PI/2)", "0"),
    ("=COS(PI)", "-1"),
    ("=COS(2*PI)", "1"),
    ("=COS(1000000*PI)", "1"),
    ("=TAN(PI/4)", "1"),
    ("=TAN(-PI/4)", "-1"),
    ("=TAN(PI)", "0"),
    ("=TAN(1)", "1.557407725"),
    ("=TAN(PI/2)", "#DIV/0!"),
    ("=TAN(-3*PI/2)", "#DIV/0!"),
    ("=SIN(1e999)", "#NUM!"),
])
def test_radians(sheet, formula, expected):
    assert show(sheet, formula, RADIANS) == expected


@pytest.mark.parametrize("formula, expected", [
    ("=SIN(30)", "0.5"),
    ("=SIN(180)", "0"),
    ("=COS(-90)", "0"),
    ("=TAN(90)", "#DIV/0!"),
    ("=SIN(PI)", "0.05480366515"),       # PI degrees: a small angle
    ("=SIN(1e999)", "#NUM!"),
])
def test_degrees(sheet, formula, expected):
    assert show(sheet, formula, DEGREES) == expected


def test_exact_multiples_of_pi_are_exactly_zero(sheet):
    sheet.set_angle_unit(RADIANS)
    for formula in ("=SIN(PI)", "=COS(PI/2)", "=TAN(PI)", "=SIN(100*PI)"):
        sheet.set_cell(0, 2, formula)
        assert sheet.value(0, 2) == 0.0


def test_tiny_angles_are_not_rounded_to_zero(sheet):
    show(sheet, "=SIN(1e-12)", RADIANS)
    assert sheet.value(0, 2) == 1e-12


def test_other_functions_ignore_the_unit(sheet):
    sheet.set_cell(1, 2, "=EXP(1)+POW(2, 3)+SUM(A1)")
    before = sheet.value(1, 2)
    sheet.set_angle_unit(RADIANS)
    assert sheet.value(1, 2) == before


# --- Switching ---

def test_sheets_start_in_degrees(sheet):
    assert sheet.angle_unit == DEGREES


def test_switching_recalculates_and_undoes(sheet):
    sheet.set_cell(0, 2, "=SIN(90)")
    assert sheet.display_text(0, 2) == "1"
    sheet.set_angle_unit(RADIANS)
    assert sheet.display_text(0, 2) == "0.8939966636"
    assert sheet.undo_stack.undoText() == "Angles in Radians"
    sheet.undo_stack.undo()
    assert sheet.angle_unit == DEGREES
    assert sheet.display_text(0, 2) == "1"
    sheet.undo_stack.redo()
    assert sheet.angle_unit == RADIANS
    assert sheet.display_text(0, 2) == "0.8939966636"


def test_switching_announces_the_change(sheet):
    units, contents = [], []
    sheet.angle_unit_changed.connect(units.append)
    sheet.contents_changed.connect(lambda: contents.append(1))
    sheet.set_angle_unit(RADIANS)
    assert units == [RADIANS] and contents == [1]


def test_choosing_the_current_unit_is_not_a_step(sheet):
    steps = sheet.undo_stack.count()
    sheet.set_angle_unit(DEGREES)
    assert sheet.undo_stack.count() == steps


# --- Files ---

def test_unit_is_saved_and_loaded(tmp_path):
    path = str(tmp_path / "s.ezs")
    sheet = SheetData(10, 5, {(0, 0): "=SIN(PI)"}, angle_unit=RADIANS)
    save_sheet(path, sheet)
    assert json.loads(open(path).read())["angles"] == "radians"
    assert load_sheet(path) == sheet


def test_files_without_a_unit_are_degrees(tmp_path):
    path = tmp_path / "old.ezs"
    path.write_text(json.dumps({"format": "ezsheet", "version": 3, "rows": 10, "columns": 5,
                                "cells": {"A1": "=SIN(30)"}}))
    assert load_sheet(str(path)).angle_unit == DEGREES


@pytest.mark.parametrize("angles", ["gradians", "RADIANS", None, 1])
def test_bad_unit_in_file(tmp_path, angles):
    path = tmp_path / "bad.ezs"
    path.write_text(json.dumps({"format": "ezsheet", "version": 4, "rows": 10, "columns": 5,
                                "angles": angles, "cells": {}}))
    with pytest.raises(SheetFileError):
        load_sheet(str(path))


def test_model_round_trips_the_unit(sheet):
    sheet.set_angle_unit(RADIANS)
    other = SheetModel()
    other.load_sheet_data(sheet.sheet_data())
    assert other.angle_unit == RADIANS
    assert other.undo_stack.count() == 0  # loading isn't an undoable step


# --- The window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def shown_unit(window):
    checked = [unit for unit, action in window.angle_actions.items() if action.isChecked()]
    return checked, window.angle_button_action.iconText()


def test_window_shows_degrees_at_first(window):
    assert shown_unit(window) == ([DEGREES], "DEG")
    assert [a.text() for a in window.angle_actions.values()] == ["Angles in Degrees", "Angles in Radians"]


def test_menu_switches_the_unit(window):
    window.model.set_cell(0, 0, "=COS(PI)")
    window.angle_actions[RADIANS].trigger()
    assert window.model.angle_unit == RADIANS
    assert window.model.display_text(0, 0) == "-1"
    assert shown_unit(window) == ([RADIANS], "RAD")
    assert window.isWindowModified()
    window.angle_actions[RADIANS].trigger()  # choosing it again changes nothing
    assert shown_unit(window) == ([RADIANS], "RAD")


def test_toolbar_button_toggles_and_undo_follows(window):
    window.angle_button_action.trigger()
    assert shown_unit(window) == ([RADIANS], "RAD")
    assert "radians" in window.angle_button_action.toolTip()
    window.angle_button_action.trigger()
    assert shown_unit(window) == ([DEGREES], "DEG")
    window.undo_action.trigger()
    assert shown_unit(window) == ([RADIANS], "RAD")
    window.undo_action.trigger()
    assert shown_unit(window) == ([DEGREES], "DEG")
    assert not window.isWindowModified()  # back where it started


def test_save_and_open_keep_the_unit(window, tmp_path):
    path = str(tmp_path / "trig.ezs")
    window.model.set_cell(0, 0, "=SIN(PI/2)")
    window.set_angle_unit(RADIANS)
    assert window.save_to(path)

    other = MainWindow()
    assert shown_unit(other) == ([DEGREES], "DEG")
    assert other.open_path(path)
    assert shown_unit(other) == ([RADIANS], "RAD")
    assert other.model.display_text(0, 0) == "1"
    assert not other.isWindowModified()


def test_new_sheet_keeps_the_unit(window):
    window.set_angle_unit(RADIANS)
    window.new_file()
    assert window.model.angle_unit == RADIANS
    assert shown_unit(window) == ([RADIANS], "RAD")
    assert not window.isWindowModified()


def test_switching_commits_the_cell_being_edited_first(window):
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    window.edit_bar.setFocus()
    QTest.keyClicks(window.edit_bar, "=SIN(PI)")
    window.set_angle_unit(RADIANS)
    assert window.model.get_cell(0, 0) == "=SIN(PI)"
    assert window.model.display_text(0, 0) == "0"
    window.undo_action.trigger()  # the switch and the edit are separate steps
    assert window.model.get_cell(0, 0) == "=SIN(PI)"


# --- Claude ---

def first_text(request, index):
    content = request["messages"][index]["content"]
    return content if isinstance(content, str) else content[0]["text"]


def test_claude_is_told_the_unit_and_when_it_changes(sheet):
    client = FakeClient([FakeStream([text_event(x)], message(x)) for x in "ABC"])
    session = ClaudeSession(client, *selection_csv(sheet, {(0, 0)}), SheetAccess(sheet))
    session.ask("first", Recorder())
    assert "The sheet takes angles in degrees.\n\nfirst" in first_text(client.requests[0], 0)
    session.ask("second", Recorder())
    assert first_text(client.requests[1], 2) == "second"  # not repeated
    sheet.set_angle_unit(RADIANS)
    session.ask("third", Recorder())
    assert first_text(client.requests[2], 4) == "The sheet takes angles in radians.\n\nthird"
