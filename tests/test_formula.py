import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from py_spread.formula import (
    CellError,
    FormulaError,
    evaluate,
    format_number,
    parse,
    parse_number,
    shift_references,
)
from py_spread.model import SheetModel


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def calc(text):
    return evaluate(parse(text), lambda row, col: 0.0)


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


@pytest.mark.parametrize("text", ["", "1+", "(1+2", "1+2)", "1 2", "*3", "A1B", "1..2", "sum(A1)"])
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
