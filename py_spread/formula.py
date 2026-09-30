"""Parsing and evaluation of arithmetic formulas such as =(A1+B2)*2^3.

Grammar (lowest to highest precedence):

    expr    := term (('+' | '-') term)*
    term    := unary (('*' | '/') unary)*
    unary   := ('+' | '-') unary | power
    power   := primary ('^' unary)?
    primary := NUMBER | REF | '(' expr ')'

Exponentiation follows mathematical convention: it binds tighter than unary
minus (-2^2 = -4) and is right-associative (2^3^2 = 512).
"""

import math
import re
from dataclasses import dataclass

from .references import parse_cell_name

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
      | (?P<ref>\$?[A-Za-z]+\$?\d+)
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


def tokenize(text: str) -> list[tuple[str, str]]:
    tokens = []
    text = text.rstrip()
    pos = 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match:
            raise FormulaError(PARSE_ERROR)
        pos = match.end()
        tokens.append((match.lastgroup, match.group(match.lastgroup)))
    return tokens


def parse(text: str):
    """Parse a formula body (without the leading '=') into an AST of tuples:
    ("num", value), ("ref", row, col), ("neg", operand), ("bin", op, left, right).
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
        if text == "(":
            node = self.expr()
            if self.take()[1] != ")":
                raise FormulaError(PARSE_ERROR)
            return node
        raise FormulaError(PARSE_ERROR)
