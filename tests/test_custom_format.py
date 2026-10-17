import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from ezsheet.custom_format import format_custom, parse_pattern, pattern_problem
from ezsheet.custom_format_dialog import PRESETS, CustomFormatDialog
from ezsheet.numformat import MENU_FORMATS, NumberFormat, format_value, from_json, pattern_of, to_json
from ezsheet.window import CUSTOM_FORMAT, MainWindow


# --- Patterns ---

@pytest.mark.parametrize("pattern, value, shown", [
    ("#,##0.00", 1234.567, "1,234.57"), ("#,##0.00", -1234.567, "-1,234.57"), ("0.0%", 0.1234, "12.3%"),
    ("$#,##0.00", -1000.12, "-$1,000.12"), ("$#,##0.00;($#,##0.00)", -1234.5, "($1,234.50)"),
    ("$#,##0.00;($#,##0.00)", 1234.5, "$1,234.50"), ("0.00E+00", 1234.5, "1.23E+03"),
    ("0.00E+00", 0.000123, "1.23E-04"), ("0.0E+0", 12345, "1.2E+4"), ("##0.0E+0", 12345, "12.3E+3"),
    ('#,##0,"K"', 1234567, "1,235K"), ('#,##0.0,,"M"', 1234567, "1.2M"), ("000-00-0000", 123456789, "123-45-6789"),
    ("(###) ###-####", 5551234567, "(555) 123-4567"), ("#.##", 0.5, ".5"), ("0.###", 2.1, "2.1"),
    ("#,##0", 0, "0"), ("#", 0, ""), ("00000", 42, "00042"), ("0,000", 5, "0,005"), ("0.00", -0.001, "0.00"),
    ('0;-0;"zero"', 0, "zero"), ('0;"minus "0', -7, "minus 7"), ('[>=1000]#,##0,"K";0', 2500, "3K"),
    ('[>=1000]#,##0,"K";0', 999, "999"), ('[<0]"below";[>100]"above";"in range"', 50, "in range"),
    ('"$"#,##0', 1500, "$1,500"), ("[$€]#,##0.00", 3.5, "€3.50"), ("\\$0.00", 2, "$2.00"), ("0.0_)", 3, "3.0 "),
    ("0*-", 4, "4"), ("General", 1234.5, "1234.5"), ('General" kg"', 2, "2 kg"), ("0.00;(0.00);-", 0, "-"),
    ("mm/dd/yyyy", 39717.66, "09/26/2008"), ("m/d/yy", 39717, "9/26/08"),
    ("dddd, mmmm d, yyyy", 39717, "Friday, September 26, 2008"), ("ddd mmm d", 39717, "Fri Sep 26"),
    ("mmmmm", 39717, "S"), ("h:mm AM/PM", 0.6659722222, "3:59 PM"), ("h:mm a/p", 0.25, "6:00 a"),
    ("hh:mm:ss", 0.6659722222, "15:59:00"), ("[h]:mm:ss", 1.5, "36:00:00"), ("[h]:mm", -0.0625, "-1:30"),
    ("[mm]:ss", 0.0625, "90:00"), ("h:mm:ss.00", 0.5000011574, "12:00:00.10"), ("yyyy-mm-dd", 39717, "2008-09-26"),
    ("mm:ss", 0.0006944444, "01:00"),
])
def test_patterns(pattern, value, shown):
    assert format_custom(value, pattern)[0] == shown


@pytest.mark.parametrize("pattern, value, color", [
    ("[Red]0", 5, "red"), ("0;[Red]-0", -5, "red"), ("0;[Red]-0", 5, None), ("[Blue]0;[Red]0;[Green]0", 0, "green"),
    ('[Red][<0]0;0', -1, "red"), ('[magenta]"!"@', "x", "magenta"),
])
def test_colors(pattern, value, color):
    assert format_custom(value, pattern)[1] == color


@pytest.mark.parametrize("pattern, text, shown", [
    ('@" units"', "five", "five units"), ('0.00;-0.00;0;"Text: "@', "x", "Text: x"), ("0.00", "abc", "abc"),
    ("0;0;0;", "hidden", ""),
])
def test_text(pattern, text, shown):
    assert format_custom(text, pattern)[0] == shown


@pytest.mark.parametrize("pattern, problem", [
    ("", "empty"), ('0"open', "quotation mark"), ("[Red0", "[ isn't closed"), ("[Purple]0", "isn't a color"),
    ("0;0;0;@;0", "at most four sections"),
])
def test_patterns_that_cant_be_used(pattern, problem):
    assert problem in pattern_problem(pattern)


@pytest.mark.parametrize("pattern, value, shown", [
    ("# ?/?", 1.25, "1 1/4"), ("# ?/?", 0.5, "1/2"), ("# ?/?", -1.25, "-1 1/4"), ("0 ?/?", 0.5, "0 1/2"),
    ("# ?/?", 3, "3    "), ("# #/#", 4, "4"), ("# ?/?", 0, "0    "), ("# ?/?", 2.999, "3    "),  # whole numbers
    ("# ??/??", 3.14159, "3 14/99"), ("# ??/??", 0.333, " 1/3 "),  # ? places line fractions up with spaces
    ("?/?", 1.5, "3/2"), ("??/??", 0.75, " 3/4 "),  # no whole part: improper
    ("# ?/8", 2.3, "2 2/8"), ("# ?/16", 0.0625, "1/16"), ("0/100", 0.25, "25/100"),  # fixed denominators
    ('# ?/?" in"', 1.5, "1 1/2 in"), ("m/d/yyyy", 39717, "9/26/2008"),  # (a date isn't a fraction)
])
def test_fractions(pattern, value, shown):
    assert format_custom(value, pattern)[0] == shown


def test_semicolons_in_quotes_and_brackets_arent_sections():
    assert len(parse_pattern('"a;b"0;[<0]0').sections) == 2
    assert format_custom(5, '"a;b"0')[0] == "a;b5"


def test_built_in_formats_as_patterns():
    for name, fmt, _example in filter(None, MENU_FORMATS):
        pattern = pattern_of(fmt)
        if not pattern:
            assert name in ("Automatic", "Plain text")
            continue
        for value in (1000.12, -1000.12, 0, 0.1012, 39717.6659722222, 1.000694444):
            assert format_value(value, NumberFormat("custom", pattern=pattern)) == format_value(value, fmt), name


def test_custom_formats_saved():
    fmt = NumberFormat("custom", pattern='#,##0.0,"K";[Red]-#,##0.0,"K"')
    assert to_json(fmt) == {"kind": "custom", "pattern": '#,##0.0,"K";[Red]-#,##0.0,"K"'}
    assert from_json(to_json(fmt)) == fmt
    assert from_json({"kind": "custom", "pattern": "[Purple]0"}) is None
    assert from_json({"kind": "custom"}) is None


def test_presets_can_all_be_used():
    for pattern, _description in PRESETS:
        assert pattern_problem(pattern) is None, pattern


# --- In the sheet ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def test_custom_format_in_the_sheet(window):
    model = window.model
    model.set_cells({(0, 0): "1234567", (1, 0): "-5", (2, 0): "apples", (3, 0): "=A1*2"})
    fmt = NumberFormat("custom", pattern='#,##0.0,"K";[Red](#,##0.0,"K");0;"Fruit: "@')
    model.set_formats({(r, 0): fmt for r in range(3)}, "Custom Number Format")
    assert [model.display_text(r, 0) for r in range(4)] == ["1,234.6K", "(0.0K)", "Fruit: apples", "2,469.1K"]
    assert model.data(model.index(1, 0), Qt.ForegroundRole) == QColor("#ff0000")
    assert model.data(model.index(0, 0), Qt.ForegroundRole) is None
    assert model.get_cell(0, 0) == "1234567"  # the value's as typed


def test_custom_number_format_menu_item(window, dialogs):
    model = window.model
    model.set_cells({(0, 0): "$1,234.50", (1, 0): "-3"})
    window.view.select_range(0, 0, 1, 0)
    window.view.setCurrentIndex(model.index(0, 0))
    window.view.select_range(0, 0, 1, 0)
    dialogs.custom_format_answer = "#,##0.00;[Red](#,##0.00)"
    window.format_actions[CUSTOM_FORMAT].trigger()
    assert dialogs.custom_format_prompts == [("$#,##0.00", 1234.5)]  # the current cell's format, as a pattern
    assert [model.display_text(r, 0) for r in range(2)] == ["1,234.50", "(3.00)"]
    assert window.undo_action.text() == "Undo Custom Number Format"
    assert window.format_actions[CUSTOM_FORMAT].isChecked()
    window.format_actions["Increase Decimals"].trigger()  # its decimals are in its pattern
    assert model.display_text(0, 0) == "1,234.50"
    dialogs.custom_format_answer = None  # Cancel: unchanged, and the menu shows the format it has
    window.format_actions[CUSTOM_FORMAT].trigger()
    assert dialogs.custom_format_prompts[-1][0] == "#,##0.00;[Red](#,##0.00)"
    assert model.display_text(1, 0) == "(3.00)" and window.format_actions[CUSTOM_FORMAT].isChecked()


def test_custom_format_saved_with_the_sheet(window, tmp_path):
    window.model.set_cell(0, 0, "0.5")
    window.model.set_formats({(0, 0): NumberFormat("custom", pattern="[h]:mm")}, "Custom Number Format")
    window.save_to(str(tmp_path / "s.ezs"))
    other = MainWindow()
    other.open_path(str(tmp_path / "s.ezs"))
    assert other.model.display_text(0, 0) == "12:00"
    other.setWindowModified(False)
    other.close()


# --- The dialog ---

def test_dialog_previews_the_pattern(app):
    dialog = CustomFormatDialog(None, "#,##0.00;[Red](#,##0.00);\"zero\"", 1234.5678)
    assert [dialog.previews[k].text() for k in ("sample", "negative", "zero", "text")] == [
        "1,234.57", "(1,234.57)", "zero", "text"]
    assert "#ff0000" in dialog.previews["negative"].styleSheet() and dialog.ok_button.isEnabled()
    dialog.edit.setText("[Purple]0")
    assert not dialog.ok_button.isEnabled() and "isn't a color" in dialog.note.text()
    dialog.list.itemClicked.emit(dialog.list.topLevelItem(1), 0)  # a preset
    assert dialog.pattern() == "0.0%" and dialog.previews["sample"].text() == "123456.8%"
    assert dialog.ok_button.isEnabled() and dialog.note.isHidden()
