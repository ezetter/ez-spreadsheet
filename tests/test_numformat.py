import json

import pytest
from PySide6.QtCore import Qt

from py_spread.fill import SequenceFill
from py_spread.formula import parse_number
from py_spread.model import SheetModel
from py_spread.numformat import GENERAL, NumberFormat, format_value, from_json, parse_formatted
from py_spread.storage import SheetData, SheetFileError, load_sheet, save_sheet
from py_spread.window import MainWindow

CURRENCY = NumberFormat("currency")
NUMBER = NumberFormat("number")


# --- Parsing and formatting ---

@pytest.mark.parametrize("text, value", [
    ("$5", 5), ("$1,234.50", 1234.5), ("1,234", 1234), ("1,234,567.891", 1234567.891),
    ("-$5.25", -5.25), ("$-5.25", -5.25), ("+$3", 3), ("$.5", 0.5), (" $10 ", 10),
    ("$1234", 1234), ("12", 12), ("-1e3", -1000),
])
def test_parse_number_accepts(text, value):
    assert parse_number(text) == pytest.approx(value)


@pytest.mark.parametrize("text", [
    "1,5", "12,34", "1,234,5", "1,2345", ",123", "$", "$$1", "-$-1", "$1,234.5.6", "1,234e3",
    "USD 5", "5$", "$ 5", "1 234",
])
def test_parse_number_rejects(text):
    assert parse_number(text) is None


@pytest.mark.parametrize("text, fmt", [
    ("$1,234.50", NumberFormat("currency", 2, True)),
    ("$1234.5", NumberFormat("currency", 1, False)),
    ("$5", NumberFormat("currency", 0, False)),
    ("1,234", NumberFormat("number", 0, True)),
    ("12.5", None),
    ("hello", None),
])
def test_typed_format(text, fmt):
    parsed = parse_formatted(text)
    assert (parsed[1] if parsed else None) == fmt


@pytest.mark.parametrize("value, fmt, text", [
    (1234.5, CURRENCY, "$1,234.50"),
    (-1234.5, CURRENCY, "-$1,234.50"),
    (1234.5, NUMBER, "1,234.50"),
    (1234.567, NumberFormat("number", 1, False), "1234.6"),
    (1234567, NumberFormat("currency", 0), "$1,234,567"),
    (-0.001, CURRENCY, "$0.00"),
    (1234.5, GENERAL, "1234.5"),
    (1234.5, NumberFormat("number", 0), "1,235"),     # halves round up
    (2.675, CURRENCY, "$2.68"),                         # from the decimal form, not the binary
    (-2.5, NumberFormat("number", 0), "-3"),
    (1e20, CURRENCY, "$100,000,000,000,000,000,000.00"),
])
def test_format_value(value, fmt, text):
    assert format_value(value, fmt) == text


@pytest.mark.parametrize("data", [
    {"kind": "percent"}, {"kind": "number", "decimals": -1}, {"kind": "number", "decimals": 11},
    {"kind": "number", "decimals": True}, {"kind": "number", "thousands": "yes"}, "currency",
])
def test_from_json_rejects(data):
    assert from_json(data) is None


# --- In the model ---

@pytest.fixture
def model(app):
    return SheetModel(rows=20, cols=6)


def test_typed_dollars_are_numbers_shown_as_typed(model):
    model.set_cell(0, 0, "$1,234.50")
    assert model.value(0, 0) == 1234.5
    assert model.display_text(0, 0) == "$1,234.50"
    assert model.data(model.index(0, 0), Qt.TextAlignmentRole) == Qt.AlignRight | Qt.AlignVCenter


def test_formula_inherits_typed_format(model):
    model.set_cells({(0, 0): "$1,234.50", (1, 0): "$2,467.50", (2, 0): "=SUM(A1:A2)"})
    assert model.display_text(2, 0) == "$3,702.00"
    model.set_cells({(0, 1): "1,000", (1, 1): "=B1/3"})
    assert model.display_text(1, 1) == "333"


def test_formula_inherits_from_first_formatted_reference(model):
    model.set_cells({(0, 0): "4", (0, 1): "$2.50", (0, 2): "=A1*B1"})
    assert model.display_text(0, 2) == "$10.00"


def test_formula_inherits_through_other_formulas(model):
    model.set_cells({(0, 0): "$1", (1, 0): "$2", (2, 0): "=SUM(A1:A2)", (3, 0): "=A3*2"})
    assert model.display_text(3, 0) == "$6"


def test_plain_formula_stays_general(model):
    model.set_cells({(0, 0): "1.5", (0, 1): "=A1*2"})
    assert model.display_text(0, 1) == "3"


def test_explicit_format_wins(model):
    model.set_cells({(0, 0): "$1,234.50", (1, 0): "=A1"})
    model.set_formats({(1, 0): GENERAL, (0, 0): NumberFormat("number", 0)}, "Format")
    assert model.display_text(1, 0) == "1234.5"
    assert model.display_text(0, 0) == "1,235"


def test_format_kept_when_retyping(model):
    model.set_formats({(0, 0): CURRENCY}, "Currency Format")
    model.set_cell(0, 0, "1300")
    assert model.display_text(0, 0) == "$1,300.00"
    model.set_cell(0, 0, "hello")
    assert model.display_text(0, 0) == "hello"  # text is unaffected


def test_format_change_is_undoable(model):
    model.set_cell(0, 0, "5")
    model.set_formats({(0, 0): CURRENCY}, "Currency Format")
    assert model.undo_stack.undoText() == "Currency Format"
    model.undo_stack.undo()
    assert model.display_text(0, 0) == "5"
    model.undo_stack.redo()
    assert model.display_text(0, 0) == "$5.00"


def test_circular_reference_does_not_break_formats(model):
    model.set_cells({(0, 0): "=B1", (0, 1): "=A1"})
    assert model.display_text(0, 0) == "#CIRC!"


# --- Saving ---

def test_formats_saved_and_loaded(tmp_path):
    path = str(tmp_path / "s.pysheet")
    sheet = SheetData(10, 5, {(0, 0): "5"}, {(0, 0): CURRENCY, (3, 3): NumberFormat("number", 1, False)})
    save_sheet(path, sheet)
    document = json.loads(open(path).read())
    assert document["formats"]["A1"] == {"kind": "currency", "decimals": 2, "thousands": True}
    assert load_sheet(path) == sheet


def test_version_1_files_still_open(tmp_path):
    path = tmp_path / "old.pysheet"
    path.write_text(json.dumps({"format": "py-spread", "version": 1, "rows": 10, "columns": 5,
                                "cells": {"A1": "x"}}))
    assert load_sheet(str(path)) == SheetData(10, 5, {(0, 0): "x"})


def test_bad_format_in_file(tmp_path):
    path = tmp_path / "bad.pysheet"
    path.write_text(json.dumps({"format": "py-spread", "version": 2, "rows": 10, "columns": 5,
                                "cells": {}, "formats": {"A1": {"kind": "percent"}}}))
    with pytest.raises(SheetFileError):
        load_sheet(str(path))


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def test_format_menu(window):
    menu = [m for m in window.menuBar().actions() if m.text() == "Format"][0].menu()
    names = [a.text() for a in menu.actions() if a.text()]
    assert names == ["General  (1234.5)", "Number  (1,234.50)", "Currency  ($1,234.50)",
                     "Increase Decimals", "Decrease Decimals", "Bold", "Italic"]


def test_currency_menu_item(window):
    model = window.model
    model.set_cells({(0, 0): "1234.5", (1, 0): "hello", (2, 0): "=A1*2"})
    window.view.select_range(0, 0, 2, 0)
    window.format_actions["Currency"].trigger()
    assert [model.display_text(r, 0) for r in range(3)] == ["$1,234.50", "hello", "$2,469.00"]
    assert window.undo_action.text() == "Undo Currency Format"


def test_general_menu_item_shows_typed_dollars_plainly(window):
    window.model.set_cell(0, 0, "$1,234.50")
    window.view.select_range(0, 0, 0, 0)
    window.format_actions["General"].trigger()
    assert window.model.display_text(0, 0) == "1234.5"
    assert window.edit_bar.text() == "$1,234.50"  # the typed text is kept


def test_increase_and_decrease_decimals(window):
    model = window.model
    model.set_cells({(0, 0): "1.5", (1, 0): "$2.25", (2, 0): "text"})
    window.view.select_range(0, 0, 2, 0)
    window.format_actions["Increase Decimals"].trigger()
    assert [model.display_text(r, 0) for r in range(3)] == ["1.50", "$2.250", "text"]
    for _ in range(5):
        window.format_actions["Decrease Decimals"].trigger()
    assert [model.display_text(r, 0) for r in range(2)] == ["2", "$2"]
    assert model.cell_format(2, 0) is None


def test_autosum_over_dollars_shows_dollars(window):
    model = window.model
    model.set_cells({(0, 0): "$19.99", (1, 0): "$5.01"})
    window.view.select_range(2, 0, 2, 0)
    window.autosum_action.trigger()
    assert model.display_text(2, 0) == "$25.00"


def test_paste_brings_format(window):
    model = window.model
    model.set_cell(0, 0, "7")
    model.set_formats({(0, 0): CURRENCY}, "Currency Format")
    window.view.select_range(0, 0, 0, 0)
    window.clipboard.copy()
    window.view.select_range(3, 3, 3, 3)
    window.clipboard.paste()
    assert model.display_text(3, 3) == "$7.00"
    window.view.select_range(0, 0, 0, 0)
    window.clipboard.cut()
    window.view.select_range(5, 5, 5, 5)
    window.clipboard.paste()
    assert model.cell_format(0, 0) is None
    assert model.display_text(5, 5) == "$7.00"


def test_fill_sequence_keeps_typed_style(window):
    model = window.model
    model.set_cells({(0, 0): "$1.00", (1, 0): "$1.50"})
    window.view.select_range(0, 0, 3, 0)
    window.fill_actions["sequence"].trigger()
    assert [model.get_cell(r, 0) for r in range(4)] == ["$1.00", "$1.50", "$2.00", "$2.50"]
    assert model.value(3, 0) == 2.5


def test_fill_sequence_thousands(window):
    model = window.model
    model.set_cells({(0, 0): "1,000", (1, 0): "2,000"})
    window.view.select_range(0, 0, 2, 0)
    window.fill_actions["sequence"].trigger()
    assert model.get_cell(2, 0) == "3,000"


def test_fill_random_keeps_typed_style(window):
    model = window.model
    model.set_cells({(0, 0): "$1", (1, 0): "$6"})
    window.view.select_range(0, 0, 19, 0)
    window.fill_actions["random"].trigger()
    values = [model.get_cell(r, 0) for r in range(20)]
    assert all(v.startswith("$") and 1 <= parse_number(v) <= 6 and "." not in v for v in values)


def test_fill_copies_first_cells_format(window):
    model = window.model

    class Dialogs:
        def sequence(self, initial, count):
            return SequenceFill(1, 3)

    window.fill.dialogs = Dialogs()
    model.set_formats({(0, 0): CURRENCY}, "Currency Format")
    window.view.select_range(0, 0, 2, 0)
    window.fill_actions["sequence"].trigger()
    assert [model.display_text(r, 0) for r in range(3)] == ["$1.00", "$2.00", "$3.00"]


def test_csv_round_trip_keeps_dollars(window, tmp_path):
    model = window.model
    model.set_cells({(0, 0): "$1,234.50", (1, 0): "=A1*2"})
    path = str(tmp_path / "money.csv")
    window.export_csv_to(path)
    assert open(path).read() == '"$1,234.50"\n"$2,469.00"\n'
    other = MainWindow()
    other.import_csv_from(path)
    assert other.model.value(1, 0) == 2469.0
    assert other.model.display_text(1, 0) == "$2,469.00"
    other.setWindowModified(False)


def test_save_and_open_keeps_formats(window, tmp_path):
    window.model.set_cell(0, 0, "5")
    window.model.set_formats({(0, 0): CURRENCY}, "Currency Format")
    path = str(tmp_path / "s.pysheet")
    window.save_to(path)
    other = MainWindow()
    other.open_path(path)
    assert other.model.display_text(0, 0) == "$5.00"


def toolbar_buttons(window):
    from PySide6.QtWidgets import QToolBar
    toolbar = window.findChild(QToolBar)
    return [toolbar.widgetForAction(a) for a in toolbar.actions() if not a.isSeparator()]


def test_currency_toolbar_button(window):
    from PySide6.QtTest import QTest
    buttons = toolbar_buttons(window)
    assert buttons[:2] == [window.autosum_button, window.fill_button]
    assert [b.text() for b in buttons[2:]] == ["$", "B", "I"]  # no decimal buttons
    currency = buttons[2]
    assert currency.defaultAction() is window.format_actions["Currency"]  # same action as the menu
    assert window.format_actions["Currency"].text() == "Currency  ($1,234.50)"  # menu text unchanged
    window.model.set_cell(0, 0, "1234.5")
    window.view.select_range(0, 0, 0, 0)
    QTest.mouseClick(currency, Qt.LeftButton)
    assert window.model.display_text(0, 0) == "$1,234.50"
