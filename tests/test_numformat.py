import json

import pytest
from PySide6.QtCore import Qt

from py_spread.fill import SequenceFill
from py_spread.formula import parse_number
from py_spread.model import SheetModel
from py_spread.errors import CellError
from py_spread.numformat import GENERAL, NumberFormat, format_value, from_json, parse_formatted, to_json
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
    {"kind": "fraction"}, {"kind": "number", "decimals": -1}, {"kind": "number", "decimals": 11},
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
    path = str(tmp_path / "s.ezs")
    sheet = SheetData(10, 5, {(0, 0): "5"}, {(0, 0): CURRENCY, (3, 3): NumberFormat("number", 1, False)})
    save_sheet(path, sheet)
    document = json.loads(open(path).read())
    assert document["formats"]["A1"] == {"kind": "currency", "decimals": 2, "thousands": True}
    assert load_sheet(path) == sheet


def test_version_1_files_still_open(tmp_path):
    path = tmp_path / "old.ezs"
    path.write_text(json.dumps({"format": "ezsheet", "version": 1, "rows": 10, "columns": 5,
                                "cells": {"A1": "x"}}))
    assert load_sheet(str(path)) == SheetData(10, 5, {(0, 0): "x"})


def test_bad_format_in_file(tmp_path):
    path = tmp_path / "bad.ezs"
    path.write_text(json.dumps({"format": "ezsheet", "version": 2, "rows": 10, "columns": 5,
                                "cells": {}, "formats": {"A1": {"kind": "fraction"}}}))
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
    assert names == ["Number", "Increase Decimals", "Decrease Decimals", "Bold", "Italic"]
    assert menu.actions()[0].menu() is window.number_menu  # Format > Number, as Google Sheets has it
    assert [a.text() for a in window.number_menu.actions() if a.text()] == [
        "Automatic", "Plain text", "Number  (1,000.12)", "Percent  (10.12%)", "Scientific  (1.01E+03)",
        "Accounting  ($ (1,000.12))", "Financial  ((1,000.12))", "Currency  ($1,000.12)",
        "Currency rounded  ($1,000)", "Date  (9/26/2008)", "Time  (3:59:00 PM)",
        "Date time  (9/26/2008 15:59:00)", "Duration  (24:01:00)"]


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
    window.format_actions["Automatic"].trigger()
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
    path = str(tmp_path / "s.ezs")
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
    assert [b.text() for b in buttons[2:]] == ["Notebook", "$", "%", "", "", "123", "B", "I", "DEG"]
    currency = buttons[3]
    assert currency is window.number_buttons["currency"]
    window.model.set_cell(0, 0, "1234.5")
    window.view.select_range(0, 0, 0, 0)
    QTest.mouseClick(currency, Qt.LeftButton)
    assert window.model.display_text(0, 0) == "$1,234.50"
    assert window.format_actions["Currency"].isChecked()  # in the Number menu


# --- Google Sheets' formats ---

@pytest.mark.parametrize("kind, decimals, value, shown", [
    ("percent", 2, 0.1012, "10.12%"), ("percent", 0, -0.256, "-26%"), ("percent", 1, 12.5, "1,250.0%"),
    ("scientific", 2, 1012, "1.01E+03"), ("scientific", 2, -0.000123, "-1.23E-04"), ("scientific", 2, 0, "0.00E+00"),
    ("scientific", 2, 9.996, "1.00E+01"), ("scientific", 0, 2.5e20, "3E+20"),
    ("accounting", 2, -1000.12, "$ (1,000.12)"), ("accounting", 2, 1000.12, "$ 1,000.12 "),
    ("accounting", 2, 0.001, "$ - "), ("financial", 2, -1000.12, "(1,000.12)"), ("financial", 2, 5, "5.00"),
    ("currency", 0, 1000.5, "$1,001"), ("date", 0, 39717.66, "9/26/2008"), ("date", 0, 1, "12/31/1899"),
    ("time", 0, 0.5, "12:00:00 PM"), ("time", 0, 0.0, "12:00:00 AM"), ("time", 0, 39717.6659722222, "3:59:00 PM"),
    ("datetime", 0, 39717.25, "9/26/2008 06:00:00"), ("duration", 0, 1.000694444, "24:01:00"),
    ("duration", 0, -0.5, "-12:00:00"), ("duration", 0, 3.75, "90:00:00"), ("date", 0, 1e9, "1000000000"),
])
def test_google_sheets_formats(kind, decimals, value, shown):
    assert format_value(value, NumberFormat(kind, decimals)) == shown


def test_menu_examples_are_what_the_formats_show():
    from py_spread.numformat import MENU_FORMATS
    samples = {"Number": 1000.12, "Percent": 0.1012, "Scientific": 1012, "Accounting": -1000.12,
               "Financial": -1000.12, "Currency": 1000.12, "Currency rounded": 1000.12, "Date": 39717,
               "Time": 0.6659722222, "Date time": 39717.6659722222, "Duration": 1.000694444}
    for name, fmt, example in filter(None, MENU_FORMATS):
        if example:
            assert format_value(samples[name], fmt) == example, name


@pytest.mark.parametrize("typed, value, fmt", [
    ("10%", 0.1, NumberFormat("percent", 0, False)), ("12.5%", 0.125, NumberFormat("percent", 1, False)),
    ("-3%", -0.03, NumberFormat("percent", 0, False)), ("1,200%", 12.0, NumberFormat("percent", 0, True)),
    ("33.3%", 0.333, NumberFormat("percent", 1, False)),
])
def test_typed_percentages(typed, value, fmt):
    assert parse_formatted(typed) == (value, fmt)


@pytest.mark.parametrize("typed", ["%", "10 %", "$10%", "10%%", "1,2%"])
def test_not_percentages(typed):
    assert parse_formatted(typed) is None


def test_typed_percentage_in_the_sheet(window):
    model = window.model
    model.set_cells({(0, 0): "12.5%", (1, 0): "=A1*2"})
    assert model.value(0, 0) == 0.125 and model.display_text(0, 0) == "12.5%"  # as typed
    assert model.display_text(1, 0) == "25.0%"  # a formula of it: shown as it is


def test_plain_text(window):
    model = window.model
    model.set_cells({(0, 0): "007", (1, 0): "=A1+1", (2, 0): "=1+2"})
    window.view.select_range(0, 0, 0, 0)
    window.format_actions["Plain text"].trigger()
    assert model.value(0, 0) == "007" and model.display_text(0, 0) == "007"  # text, as typed
    assert model.data(model.index(0, 0), Qt.TextAlignmentRole) != Qt.AlignRight | Qt.AlignVCenter
    assert isinstance(model.value(1, 0), CellError)  # text + 1
    window.view.select_range(2, 0, 2, 0)
    window.format_actions["Plain text"].trigger()
    assert model.value(2, 0) == 3.0  # formulas still work
    window.undo_action.trigger()
    window.undo_action.trigger()
    assert model.value(0, 0) == 7.0  # a number again


def test_dates_and_times_have_no_decimals_to_change(window):
    model = window.model
    model.set_cells({(0, 0): "39717.66", (1, 0): "0.1234"})
    model.set_formats({(0, 0): NumberFormat("date", 0), (1, 0): NumberFormat("percent")}, "Formats")
    window.view.select_range(0, 0, 1, 0)
    window.format_actions["Increase Decimals"].trigger()
    assert [model.display_text(r, 0) for r in range(2)] == ["9/26/2008", "12.340%"]


def test_percent_and_decimal_toolbar_buttons(window):
    from PySide6.QtTest import QTest
    model = window.model
    model.set_cell(0, 0, "0.1234")
    window.view.select_range(0, 0, 0, 0)
    QTest.mouseClick(window.number_buttons["percent"], Qt.LeftButton)
    assert model.display_text(0, 0) == "12.34%" and window.format_actions["Percent"].isChecked()
    QTest.mouseClick(window.number_buttons["fewer"], Qt.LeftButton)
    assert model.display_text(0, 0) == "12.3%"
    QTest.mouseClick(window.number_buttons["more"], Qt.LeftButton)
    QTest.mouseClick(window.number_buttons["more"], Qt.LeftButton)
    assert model.display_text(0, 0) == "12.340%"
    assert window.number_buttons["formats"].menu() is window.number_menu  # 123: all of them
    assert not window.number_buttons["fewer"].icon().isNull() and window.number_buttons["fewer"].toolTip() == (
        "Decrease decimal places")


def test_number_menu_checks_the_current_cells_format(window):
    model = window.model
    model.set_cells({(0, 0): "$5.00", (1, 0): "5", (2, 0): "1,234.567"})
    model.set_formats({(1, 0): NumberFormat("currency", 0)}, "Currency rounded")
    for row, name in ((0, "Currency"), (1, "Currency rounded"), (2, "Number"), (5, "Automatic")):
        window.view.setCurrentIndex(model.index(row, 0))
        assert window.format_actions[name].isChecked(), name


@pytest.mark.parametrize("fmt", [NumberFormat(kind) for kind in
                                 ("text", "percent", "scientific", "accounting", "financial", "date", "time",
                                  "datetime", "duration")])
def test_new_formats_saved(fmt):
    assert from_json(to_json(fmt)) == fmt


# --- Typed dates and times ---

@pytest.mark.parametrize("typed, value, kind", [
    ("9/26/2008", 39717, "date"), ("9/26/08", 39717, "date"), ("2008-09-26", 39717, "date"),
    ("1/1/29", 47119, "date"), ("1/1/30", 10959, "date"), ("12/31/1899", 1, "date"), ("2/29/2024", 45351, "date"),
    ("3:59 PM", 0.6659722222222222, "time"), ("12:00 AM", 0, "time"), ("12:30 pm", 0.5208333333333334, "time"),
    ("15:59:30", 0.6663194444444445, "time"), ("9/26/2008 15:59", 39717.665972222225, "datetime"),
    ("9/26/2008 3:59 PM", 39717.665972222225, "datetime"), ("2008-09-26T10:00", 39717.416666666664, "datetime"),
])
def test_typed_dates_and_times(typed, value, kind):
    parsed = parse_formatted(typed)
    assert parsed == (pytest.approx(value), NumberFormat(kind, 0))


@pytest.mark.parametrize("typed", ["2/30/2024", "13/1/2024", "1/2", "9/26/2008x", "25:00", "13:00 PM", "0:00 AM",
                                   "12:60", "9/26/200815:59", "1:2", "2008-13-01"])
def test_not_dates_or_times(typed):
    assert parse_formatted(typed) is None


def test_typed_dates_in_the_sheet(window):
    model = window.model
    model.set_cells({(0, 0): "9/26/2008", (1, 0): "10/3/2008", (2, 0): "=A1+7", (3, 0): "=A2-A1",
                     (4, 0): "=(A2-A1)*24", (5, 0): "3:59 PM", (6, 0): "=A6+0.5", (7, 0): "$5", (8, 0): "=A8-A8"})
    assert model.value(0, 0) == 39717 and model.display_text(0, 0) == "9/26/2008"  # a number, shown as typed
    assert [model.display_text(r, 0) for r in range(2, 9)] == [
        "10/3/2008",  # a date and days: a date
        "7", "168",  # one date from another: days, not a date
        "3:59 PM", "3:59:00 AM", "$5", "$0"]
    assert model.data(model.index(0, 0), Qt.TextAlignmentRole) == Qt.AlignRight | Qt.AlignVCenter
    window.view.setCurrentIndex(model.index(0, 0))
    assert window.format_actions["Date"].isChecked()
    model.set_formats({(0, 0): NumberFormat("number", 0, False)}, "Number")
    assert model.display_text(0, 0) == "39717"  # its day number
