import math

import pytest

from ezsheet.formula import (
    CellError,
    FormulaError,
    evaluate,
    format_number,
    parse,
    parse_number,
    replace_function,
    shift_references,
)
from ezsheet.references import column_index
from ezsheet.functions import DEGREES
from ezsheet.model import SheetModel


class EmptySheet:
    angle_unit = DEGREES

    def cell(self, row, col):
        return None

    def cells_in(self, top, left, bottom, right):
        return []


def calc(text):
    return evaluate(parse(text), EmptySheet())


@pytest.mark.parametrize("text, expected", [
    ("1+2*3", 7),
    ("(1+2)*3", 9),
    ("10-4-3", 3),
    ("12/4/3", 1),
    ("2^3", 8),
    ("2^3^2", 512),
    ("-2^2", -4),
    ("(-2)^2", 4),
    ("2*-3", -6),
    ("--4", 4),
    ("+5", 5),
    ("2^-1", 0.5),
    (" 1.5e2 + .5 ", 150.5),
    ("((2))*(3+(4-1))", 12),
])
def test_arithmetic(text, expected):
    assert calc(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "1+", "(1+2", "1+2)", "1 2", "*3", "1..2", "A1:B2", "SUM()",
                                  "SUM(A1", "SUM(A1:)", "SUM(A1:3)", "SUM(A1,)", "SUM(A1 B1)"])
def test_parse_errors(text):
    with pytest.raises(FormulaError) as e:
        calc(text)
    assert e.value.code == "#ERROR!"


@pytest.mark.parametrize("text, code", [("1/0", "#DIV/0!"), ("0^-1", "#DIV/0!"), ("10^400", "#NUM!"), ("(-8)^(1/3)", "#NUM!")])
def test_evaluation_errors(text, code):
    with pytest.raises(FormulaError) as e:
        calc(text)
    assert e.value.code == code


def test_parse_number():
    assert parse_number(" 42 ") == 42
    assert parse_number("-1.5e3") == -1500
    assert parse_number("abc") is None
    assert parse_number("nan") is None
    assert parse_number("1_000") is None


def test_format_number():
    assert format_number(3.0) == "3"
    assert format_number(-0.0) == "0"
    assert format_number(0.1 + 0.2) == "0.3"
    assert format_number(1 / 3) == "0.3333333333"


def test_cell_references(app):
    model = SheetModel(rows=10, cols=5)
    model.set_cell(0, 0, "3")          # A1
    model.set_cell(1, 1, "4")          # B2
    model.set_cell(2, 2, "=A1+B2*2")   # C3
    assert model.display_text(2, 2) == "11"
    assert model.get_cell(2, 2) == "=A1+B2*2"


def test_lowercase_and_anchored_references(app):
    model = SheetModel(rows=10, cols=5)
    model.set_cell(0, 0, "6")
    model.set_cell(0, 1, "=a1*$A$1")
    assert model.display_text(0, 1) == "36"


def test_recalculates_when_dependency_changes(app):
    model = SheetModel(rows=10, cols=5)
    model.set_cell(0, 0, "1")
    model.set_cell(0, 1, "=A1*10")
    model.set_cell(0, 2, "=B1+1")
    assert model.display_text(0, 2) == "11"
    model.set_cell(0, 0, "5")
    assert model.display_text(0, 2) == "51"


def test_empty_reference_is_zero(app):
    model = SheetModel(rows=10, cols=5)
    model.set_cell(0, 0, "=B1+2")
    assert model.display_text(0, 0) == "2"


def test_text_reference_is_value_error(app):
    model = SheetModel(rows=10, cols=5)
    model.set_cell(0, 0, "hello")
    model.set_cell(0, 1, "=A1+1")
    assert model.display_text(0, 1) == "#VALUE!"


def test_errors_propagate(app):
    model = SheetModel(rows=10, cols=5)
    model.set_cell(0, 0, "=1/0")
    model.set_cell(0, 1, "=A1+1")
    assert model.value(0, 1) == CellError("#DIV/0!")


def test_out_of_range_reference(app):
    model = SheetModel(rows=10, cols=5)
    model.set_cell(0, 0, "=Z99")
    assert model.display_text(0, 0) == "#REF!"


def test_circular_references(app):
    model = SheetModel(rows=10, cols=5)
    model.set_cell(0, 0, "=B1+1")
    model.set_cell(0, 1, "=A1+1")
    model.set_cell(0, 2, "=C1")
    assert model.display_text(0, 0) == "#CIRC!"
    assert model.display_text(0, 1) == "#CIRC!"
    assert model.display_text(0, 2) == "#CIRC!"


def test_diamond_dependencies_are_not_circular(app):
    model = SheetModel(rows=10, cols=5)
    model.set_cell(0, 0, "2")
    model.set_cell(0, 1, "=A1*3")
    model.set_cell(0, 2, "=A1*4")
    model.set_cell(0, 3, "=B1+C1")
    assert model.display_text(0, 3) == "14"


def test_long_dependency_chain(app):
    rows = 5000
    model = SheetModel(rows=rows, cols=1)
    model.set_cell(rows - 1, 0, "1")
    for row in range(rows - 1):
        model.set_cell(row, 0, f"=A{row + 2}+1")
    assert model.display_text(0, 0) == str(rows)


@pytest.mark.parametrize("formula, d_row, d_col, expected", [
    ("=A1+B2", 1, 0, "=A2+B3"),
    ("=A1+B2", 0, 2, "=C1+D2"),
    ("=$A$1+A$1+$A1", 3, 3, "=$A$1+D$1+$A4"),
    ("=(a1 + 2) * Z9", 1, 1, "=(B2 + 2) * AA10"),
    ("=1e3+E3", 1, 0, "=1e3+E4"),
    ("=A2-B1", -1, 0, "=A1-#REF!"),
    ("=A1+", 1, 1, "=B2+"),
    ("=A1 ! bad", 1, 1, "=A1 ! bad"),
])
def test_shift_references(formula, d_row, d_col, expected):
    assert shift_references(formula, d_row, d_col) == expected


def test_ref_error_literal(app):
    model = SheetModel(rows=10, cols=5)
    model.set_cell(0, 0, "=#REF!+1")
    assert model.display_text(0, 0) == "#REF!"


@pytest.mark.parametrize("text", ["A1B", "FOO(1)", "SUM", "SUMX(A1)"])
def test_unknown_names(text):
    with pytest.raises(FormulaError) as e:
        calc(text)
    assert e.value.code == "#NAME?"


@pytest.mark.parametrize("text, expected", [
    ("PI", math.pi),
    ("pi", math.pi),
    ("Pi()", math.pi),          # as typed in other spreadsheets
    ("2*PI", 2 * math.pi),
    ("-PI^2", -math.pi ** 2),
    ("PI()/ 2", math.pi / 2),
    ("SUM(PI, 1)", math.pi + 1),
])
def test_pi(text, expected):
    assert calc(text) == expected


@pytest.mark.parametrize("text, code", [
    ("PI(1)", "#ERROR!"),
    ("PI(", "#ERROR!"),
    ("PI PI", "#ERROR!"),
    ("PIE", "#NAME?"),
])
def test_pi_mistakes(text, code):
    with pytest.raises(FormulaError) as e:
        calc(text)
    assert e.value.code == code


def test_pi_with_digits_is_a_cell_reference():
    assert parse("PI2") == ("ref", 1, column_index("PI"))


def test_pi_in_a_cell_shows_ten_digits(sheet):
    sheet.set_cell(0, 2, "=PI")
    assert sheet.display_text(0, 2) == "3.141592654"
    assert sheet.value(0, 2) == math.pi


def test_parse_sum():
    assert parse("sum(B3:A1, C2, 1+2)") == ("call", "SUM", [
        ("range", 0, 0, 2, 1),
        ("ref", 1, 2),
        ("bin", "+", ("num", 1.0), ("num", 2.0)),
    ])


def test_shift_references_in_ranges_and_functions():
    assert shift_references("=SUM(A1:B2, $C$1)", 2, 1) == "=SUM(B3:C4, $C$1)"
    assert shift_references("=SUM(A1:A3)", -1, 0) == "=SUM(#REF!:A2)"


@pytest.fixture
def sheet(app):
    model = SheetModel(rows=20, cols=6)
    for row, value in enumerate(["10", "20", "30"]):
        model.set_cell(row, 0, value)  # A1:A3
    return model


def test_sum_range(sheet):
    sheet.set_cell(5, 0, "=SUM(A1:A3)")
    assert sheet.display_text(5, 0) == "60"


def test_sum_mixed_arguments(sheet):
    sheet.set_cell(0, 1, "5")
    sheet.set_cell(5, 0, "=sum(A1:A2, B1, 100, A3*2)")
    assert sheet.display_text(5, 0) == "195"


def test_sum_in_expressions(sheet):
    sheet.set_cell(5, 0, "=SUM(A1:A3)/3 - -SUM(A1)")
    assert sheet.display_text(5, 0) == "30"


def test_sum_skips_text_and_empty_cells(sheet):
    sheet.set_cell(3, 0, "total")
    sheet.set_cell(5, 0, "=SUM(A1:A5, A4)")
    assert sheet.display_text(5, 0) == "60"


def test_sum_propagates_errors(sheet):
    sheet.set_cell(3, 0, "=1/0")
    sheet.set_cell(5, 0, "=SUM(A1:A4)")
    assert sheet.display_text(5, 0) == "#DIV/0!"


def test_sum_recalculates_when_range_cell_changes(sheet):
    sheet.set_cell(5, 0, "=SUM(A1:A4)")
    sheet.set_cell(3, 0, "40")
    assert sheet.display_text(5, 0) == "100"


def test_sum_depends_on_formulas_in_range(sheet):
    sheet.set_cell(3, 0, "=A1*10")      # A4 = 100
    sheet.set_cell(5, 0, "=SUM(A1:A4)")
    assert sheet.display_text(5, 0) == "160"


def test_sum_over_itself_is_circular(sheet):
    sheet.set_cell(3, 0, "=SUM(A1:A4)")
    assert sheet.display_text(3, 0) == "#CIRC!"


def test_sum_range_off_sheet(sheet):
    sheet.set_cell(0, 1, "=SUM(A1:A99)")
    assert sheet.display_text(0, 1) == "#REF!"


def test_sum_large_range(app):
    model = SheetModel(rows=1000, cols=52)
    model.set_cell(999, 51, "7")
    model.set_cell(0, 0, "=SUM(B1:AZ1000)")
    assert model.display_text(0, 0) == "7"


@pytest.mark.parametrize("formula, expected", [
    ("=MEAN(A1:A3)", "20"),
    ("=mean(A1:A3, 50)", "27.5"),
    ("=MEDIAN(A1:A3)", "20"),
    ("=MEDIAN(A1:A3, 100)", "25"),
    ("=STDDEV(A1:A3)", "10"),
    ("=STDDEV(A1:A2)", "7.071067812"),
    ("=COUNT(A1:A3)", "3"),
    ("=COUNT(A1:A3, 7, B1:B5)", "4"),  # (empty cells aren't counted)
    ("=SUM(A1:A3)*2", "120"),
])
def test_aggregate_functions(sheet, formula, expected):
    sheet.set_cell(0, 2, formula)
    assert sheet.display_text(0, 2) == expected


@pytest.mark.parametrize("formula, error", [
    ("=MEAN(B1:B5)", "#DIV/0!"),
    ("=MEDIAN(B1:B5)", "#NUM!"),
    ("=STDDEV(A1)", "#DIV/0!"),
    ("=SUM(1e308, 1e308)", "#NUM!"),
])
def test_aggregate_errors(sheet, formula, error):
    sheet.set_cell(0, 2, formula)
    assert sheet.display_text(0, 2) == error


def test_count_counts_only_numbers(sheet):
    sheet.set_cells({(5, 0): "text", (6, 0): "=1/0", (7, 0): "$4.50", (8, 0): "=COUNT(A6:A8, B1:B5)"})
    assert sheet.display_text(8, 0) == "1"  # (not text, errors, or empty cells)
    sheet.set_cell(8, 0, "=COUNT(B1:B5)")
    assert sheet.display_text(8, 0) == "0"


def test_a_count_isnt_shown_in_its_cells_format(sheet):
    sheet.set_cells({(5, 0): "$4.50", (6, 0): "$1.25", (7, 0): "=COUNT(A6:A7)", (8, 0): "=SUM(A6:A7)/COUNT(A6:A7)"})
    assert sheet.display_text(7, 0) == "2" and sheet.display_text(8, 0) == "$2.88"


def test_empty_sum_is_zero(sheet):
    sheet.set_cell(0, 2, "=SUM(B1:B5)")
    assert sheet.display_text(0, 2) == "0"


def test_function_results_are_plain_floats(sheet):
    sheet.set_cell(0, 2, "=MEAN(A1:A3)")
    assert type(sheet.value(0, 2)) is float


@pytest.mark.parametrize("formula, expected", [
    ("=SUM(A1:A9)", "=MEAN(A1:A9)"),
    ("=sum(A1:A3, C1, 2*B1)", "=MEAN(A1:A3, C1, 2*B1)"),
    ("= SUM( A1 )", "= MEAN( A1 )"),
    ("=MEDIAN(A1:B2)", "=MEAN(A1:B2)"),
    ("=SUM(A1)*2", None),
    ("=(SUM(A1))", None),
    ("=-SUM(A1)", None),
    ("=A1+1", None),
    ("=SUM(A1", None),
    ("=FOO(A1)", None),
])
def test_replace_function(formula, expected):
    names = {"SUM", "MEAN", "MEDIAN", "STDDEV"}
    assert replace_function(formula, names, "MEAN") == expected


@pytest.mark.parametrize("formula, expected", [
    ("=SIN(30)", "0.5"),
    ("=SIN(90)", "1"),
    ("=SIN(180)", "0"),
    ("=SIN(-90)", "-1"),
    ("=SIN(390)", "0.5"),
    ("=sin(45)", "0.7071067812"),
    ("=COS(60)", "0.5"),
    ("=COS(90)", "0"),
    ("=COS(270)", "0"),
    ("=COS(180)", "-1"),
    ("=TAN(45)", "1"),
    ("=TAN(-45)", "-1"),
    ("=TAN(180)", "0"),
    ("=TAN(60)", "1.732050808"),
    ("=EXP(0)", "1"),
    ("=EXP(1)", "2.718281828"),
    ("=EXP(-1)", "0.3678794412"),
    ("=POW(2, 10)", "1024"),
    ("=POW(2, -1)", "0.5"),
    ("=POW(9, 0.5)", "3"),
    ("=POW(A1, 2)", "100"),                      # A1 is 10
    ("=SIN(POW(A1, 2) - 70) * 2", "1"),          # nesting: SIN(30) * 2
    ("=POW(SUM(A1:A3), 0.5) + EXP(0)", "8.745966692"),
])
def test_scalar_functions(sheet, formula, expected):
    sheet.set_cell(0, 2, formula)
    assert sheet.display_text(0, 2) == expected


def test_exact_angles_give_exact_values(sheet):
    sheet.set_cell(0, 2, "=SIN(30)")
    sheet.set_cell(1, 2, "=TAN(45)")
    sheet.set_cell(2, 2, "=SIN(180)")
    assert (sheet.value(0, 2), sheet.value(1, 2), sheet.value(2, 2)) == (0.5, 1.0, 0.0)


@pytest.mark.parametrize("formula, error", [
    ("=TAN(90)", "#DIV/0!"),
    ("=TAN(-270)", "#DIV/0!"),
    ("=EXP(1000)", "#NUM!"),
    ("=POW(0, -1)", "#DIV/0!"),
    ("=POW(-8, 1/3)", "#NUM!"),
    ("=POW(10, 400)", "#NUM!"),
    ("=SIN(A1:A3)", "#VALUE!"),
    ("=POW(B1, 2)", "#VALUE!"),                  # B1 is text
    ("=SIN()", "#ERROR!"),
    ("=SIN(1, 2)", "#ERROR!"),
    ("=POW(2)", "#ERROR!"),
    ("=POW(1, 2, 3)", "#ERROR!"),
    ("=EXP", "#NAME?"),
])
def test_scalar_function_errors(sheet, formula, error):
    sheet.set_cell(0, 1, "text")
    sheet.set_cell(0, 2, formula)
    assert sheet.display_text(0, 2) == error


def test_pow_matches_caret(sheet):
    for base, exponent in [("2", "8"), ("-2", "3"), ("1.5", "2.5"), ("0", "0")]:
        sheet.set_cell(5, 3, f"=POW({base}, {exponent})")
        sheet.set_cell(5, 4, f"=({base})^({exponent})")
        assert sheet.value(5, 3) == sheet.value(5, 4)


def test_empty_cell_argument_is_zero(sheet):
    sheet.set_cell(0, 2, "=COS(E9)")
    assert sheet.display_text(0, 2) == "1"
