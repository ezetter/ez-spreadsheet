"""Parsing and evaluation of arithmetic formulas such as =(A1+B2)*2^3.

Grammar (lowest to highest precedence):

    expr    := term (('+' | '-') term)*
    term    := unary (('*' | '/') unary)*
    unary   := ('+' | '-') unary | power
    power   := primary ('^' unary)?
    primary := NUMBER | REF | '#REF!' | '(' expr ')'

Exponentiation follows mathematical convention: it binds tighter than unary
minus (-2^2 = -4) and is right-associative (2^3^2 = 512).
"""

import math
import re
from dataclasses import dataclass

from .references import column_index, column_name, parse_cell_name

PARSE_ERROR = "#ERROR!"
VALUE_ERROR = "#VALUE!"
DIV_ZERO_ERROR = "#DIV/0!"
REF_ERROR = "#REF!"
NUM_ERROR = "#NUM!"
CIRCULAR_ERROR = "#CIRC!"


class FormulaError(Exception):
    """Raised while parsing or evaluating; `code` is what the cell displays."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CellError:
    """An error value held by a cell."""

    code: str

    def __str__(self):
        return self.code


_TOKEN = re.compile(
    r"""\s*(?:
        (?P<number>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
      | (?P<ref>(?P<col_anchor>\$?)(?P<col>[A-Za-z]+)(?P<row_anchor>\$?)(?P<row>\d+))
      | (?P<error>\#REF!)
      | (?P<op>[-+*/^()])
    )""",
    re.VERBOSE,
)
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def is_formula(text: str) -> bool:
    return text.startswith("=")


def parse_number(text: str) -> float | None:
    """The numeric value of plain cell text, or None if it isn't a number."""
    text = text.strip()
    return float(text) if _NUMBER.fullmatch(text) else None


def format_number(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.10g}"


def _scan(text: str) -> list[re.Match]:
    matches = []
    text = text.rstrip()
    pos = 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match:
            raise FormulaError(PARSE_ERROR)
        pos = match.end()
        matches.append(match)
    return matches


def _token_kind(match: re.Match) -> str:
    return next(kind for kind in ("number", "ref", "error", "op") if match.group(kind) is not None)


def tokenize(text: str) -> list[tuple[str, str]]:
    return [(_token_kind(m), m.group(_token_kind(m))) for m in _scan(text)]


def shift_references(formula: str, d_row: int, d_col: int) -> str:
    """Move the relative references in a formula (with its leading '=') by an offset,
    as when the formula is pasted elsewhere. $-anchored parts stay put, and a
    reference pushed off the top or left of the sheet becomes #REF!. Text that
    doesn't tokenize is returned unchanged.
    """
    body = formula[1:]
    try:
        matches = _scan(body)
    except FormulaError:
        return formula
    pieces = []
    pos = 0
    for match in matches:
        if match.group("ref") is None:
            continue
        col = column_index(match.group("col"))
        row = int(match.group("row")) - 1
        if not match.group("col_anchor"):
            col += d_col
        if not match.group("row_anchor"):
            row += d_row
        if row < 0 or col < 0:
            shifted = REF_ERROR
        else:
            shifted = f"{match.group('col_anchor')}{column_name(col)}{match.group('row_anchor')}{row + 1}"
        pieces.append(body[pos:match.start("ref")])
        pieces.append(shifted)
        pos = match.end("ref")
    pieces.append(body[pos:])
    return "=" + "".join(pieces)


def parse(text: str):
    """Parse a formula body (without the leading '=') into an AST of tuples:
    ("num", value), ("ref", row, col), ("err", code), ("neg", operand),
    ("bin", op, left, right).
    """
    return _Parser(tokenize(text)).parse()


def references(node) -> set[tuple[int, int]]:
    """All (row, col) cells referenced by an AST."""
    refs = set()
    stack = [node]
    while stack:
        node = stack.pop()
        kind = node[0]
        if kind == "ref":
            refs.add((node[1], node[2]))
        elif kind == "neg":
            stack.append(node[1])
        elif kind == "bin":
            stack.extend(node[2:])
    return refs


def evaluate(node, lookup) -> float:
    """Evaluate an AST; `lookup(row, col)` returns a referenced cell's number."""
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "ref":
        return lookup(node[1], node[2])
    if kind == "err":
        raise FormulaError(node[1])
    if kind == "neg":
        return -evaluate(node[1], lookup)
    _, op, left, right = node
    a = evaluate(left, lookup)
    b = evaluate(right, lookup)
    try:
        if op == "+":
            result = a + b
        elif op == "-":
            result = a - b
        elif op == "*":
            result = a * b
        elif op == "/":
            result = a / b
        else:
            result = a ** b
    except ZeroDivisionError:
        raise FormulaError(DIV_ZERO_ERROR) from None
    except OverflowError:
        raise FormulaError(NUM_ERROR) from None
    # A negative number to a fractional power gives a complex result in Python.
    if isinstance(result, complex) or not math.isfinite(result):
        raise FormulaError(NUM_ERROR)
    return result


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> str | None:
        return self.tokens[self.pos][1] if self.pos < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        if self.pos >= len(self.tokens):
            raise FormulaError(PARSE_ERROR)
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def parse(self):
        node = self.expr()
        if self.pos != len(self.tokens):
            raise FormulaError(PARSE_ERROR)
        return node

    def expr(self):
        node = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.peek() in ("*", "/"):
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self.peek() in ("+", "-"):
            op = self.take()[1]
            operand = self.unary()
            return ("neg", operand) if op == "-" else operand
        return self.power()

    def power(self):
        base = self.primary()
        if self.peek() == "^":
            self.take()
            return ("bin", "^", base, self.unary())
        return base

    def primary(self):
        kind, text = self.take()
        if kind == "number":
            return ("num", float(text))
        if kind == "ref":
            return ("ref", *parse_cell_name(text))
        if kind == "error":
            return ("err", text)
        if text == "(":
            node = self.expr()
            if self.take()[1] != ")":
                raise FormulaError(PARSE_ERROR)
            return node
        raise FormulaError(PARSE_ERROR)
