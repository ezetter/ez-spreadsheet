"""Parsing and evaluation of formulas such as =(A1+B2)*2^3, =SUM(A1:A9, C4),
or =2*PI*A1.

Grammar (lowest to highest precedence):

    expr    := term (('+' | '-') term)*
    term    := unary (('*' | '/') unary)*
    unary   := ('+' | '-') unary | power
    power   := primary ('^' unary)?
    primary := NUMBER | REF | '#REF!' | CONSTANT ('(' ')')? | NAME '(' args ')'
             | '(' expr ')'
    args    := arg (',' arg)*
    arg     := REF ':' REF | expr

Ranges (A1:B9) appear only as function arguments. A constant such as PI may
be followed by empty parentheses, PI(), as in other spreadsheets.

Exponentiation follows mathematical convention: it binds tighter than unary
minus (-2^2 = -4) and is right-associative (2^3^2 = 512).
"""

import math
import re

from .errors import (  # noqa: F401 -- re-exported for the rest of the app
    CIRCULAR_ERROR,
    DIV_ZERO_ERROR,
    NAME_ERROR,
    NUM_ERROR,
    PARSE_ERROR,
    REF_ERROR,
    VALUE_ERROR,
    CellError,
    FormulaError,
)
from .functions import CONSTANTS, FUNCTIONS, power
from .numformat import format_number, parse_formatted  # noqa: F401 -- format_number re-exported
from .references import column_index, column_name, parse_cell_name

_TOKEN = re.compile(
    r"""\s*(?:
        (?P<number>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
      | (?P<ref>(?P<col_anchor>\$?)(?P<col>[A-Za-z]+)(?P<row_anchor>\$?)(?P<row>\d+))(?![\w.(])
      | (?P<error>\#REF!)
      | (?P<name>[A-Za-z_][\w.]*)
      | (?P<op>[-+*/^(),:])
    )""",
    re.VERBOSE,
)
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def is_formula(text: str) -> bool:
    return text.startswith("=")


def parse_number(text: str) -> float | None:
    """The numeric value of typed cell text, or None if it isn't a number.
    Dollar signs and thousands separators are allowed: $1,234.50 is 1234.5."""
    text = text.strip()
    if _NUMBER.fullmatch(text):
        return float(text)
    formatted = parse_formatted(text)
    return formatted[0] if formatted else None


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
    return next(kind for kind in ("number", "ref", "error", "name", "op") if match.group(kind) is not None)


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


def move_references(formula: str, move, move_range=None) -> str:
    """Rewrite a formula's references for cells that have moved, such as when
    cells are inserted or deleted. `move(row, col)` gives a cell's new (row,
    col), or None if it's gone (that reference becomes #REF!). `move_range`,
    if given, does the same for a range's two corners at once, returning the
    new (start, end) or None; otherwise each corner is moved on its own.
    Unlike shift_references, $ anchors don't matter: a reference follows its
    cell. References to cells that didn't move keep their text exactly."""
    body = formula[1:]
    try:
        matches = _scan(body)
    except FormulaError:
        return formula
    pieces = []
    pos = 0

    def replace(start: int, end: int, text: str) -> None:
        nonlocal pos
        pieces.append(body[pos:start])
        pieces.append(text)
        pos = end

    i = 0
    while i < len(matches):
        match = matches[i]
        if match.group("ref") is None:
            i += 1
            continue
        is_range = (i + 2 < len(matches) and matches[i + 1].group("op") == ":"
                    and matches[i + 2].group("ref") is not None)
        if is_range and move_range is not None:
            last = matches[i + 2]
            old = (_ref_cell(match), _ref_cell(last))
            new = move_range(*old)
            if new is None or min(new[0] + new[1]) < 0:
                replace(match.start("ref"), last.end("ref"), REF_ERROR)
            elif new != old:
                replace(match.start("ref"), last.end("ref"),
                        f"{_ref_text(match, new[0])}:{_ref_text(last, new[1])}")
            i += 3
            continue
        old = _ref_cell(match)
        new = move(*old)
        if new is None or min(new) < 0:
            replace(match.start("ref"), match.end("ref"), REF_ERROR)
        elif new != old:
            replace(match.start("ref"), match.end("ref"), _ref_text(match, new))
        i += 1
    pieces.append(body[pos:])
    return "=" + "".join(pieces)


def _ref_cell(match: re.Match) -> tuple[int, int]:
    return int(match.group("row")) - 1, column_index(match.group("col"))


def _ref_text(match: re.Match, cell: tuple[int, int]) -> str:
    """A reference to `cell`, keeping the $ anchors of the reference matched."""
    return f"{match.group('col_anchor')}{column_name(cell[1])}{match.group('row_anchor')}{cell[0] + 1}"


def replace_function(formula: str, names, new_name: str) -> str | None:
    """If a formula (with its leading '=') is a single call to one of `names`,
    such as =SUM(A1:A9), return it calling `new_name` instead, with the
    arguments untouched. Otherwise return None.
    """
    body = formula[1:]
    try:
        ast = parse(body)
        matches = _scan(body)
    except FormulaError:
        return None
    if ast[0] != "call" or ast[1] not in names or _token_kind(matches[0]) != "name":
        return None
    name = matches[0]
    return "=" + body[: name.start("name")] + new_name + body[name.end("name"):]


def parse(text: str, names: dict | None = None):
    """Parse a formula body (without the leading '=') into an AST of tuples:
    ("num", value), ("ref", row, col), ("range", top, left, bottom, right),
    ("err", code), ("neg", operand), ("bin", op, left, right),
    ("call", name, [args]).

    `names` maps cell names (in upper case) to the (row, col) they name, or
    to None if that cell was deleted (#REF!). A name becomes a reference to
    its cell.
    """
    return _Parser(tokenize(text), names or {}).parse()


def references(node) -> tuple[set[tuple[int, int]], list[tuple[int, int, int, int]]]:
    """The single cells and the (top, left, bottom, right) ranges an AST refers to."""
    cells = set()
    ranges = []
    stack = [node]
    while stack:
        node = stack.pop()
        kind = node[0]
        if kind == "ref":
            cells.add((node[1], node[2]))
        elif kind == "range":
            ranges.append(node[1:])
        elif kind == "neg":
            stack.append(node[1])
        elif kind == "bin":
            stack.extend(node[2:])
        elif kind == "call":
            stack.extend(node[2])
    return cells, ranges


def ordered_references(node) -> list:
    """The ("ref", row, col) and ("range", top, left, bottom, right) nodes of
    an AST, in the order they appear in the formula."""
    found = []
    stack = [node]
    while stack:
        node = stack.pop()
        kind = node[0]
        if kind in ("ref", "range"):
            found.append(node)
        elif kind == "neg":
            stack.append(node[1])
        elif kind == "bin":
            stack.extend(reversed(node[2:]))
        elif kind == "call":
            stack.extend(reversed(node[2]))
    return found


def to_number(value) -> float:
    """Coerce a cell value for arithmetic: empty is 0, text is an error."""
    if value is None:
        return 0.0
    if isinstance(value, float):
        return value
    if isinstance(value, CellError):
        raise FormulaError(value.code)
    raise FormulaError(VALUE_ERROR)


def evaluate(node, sheet) -> float:
    """Evaluate an AST against `sheet`, which provides `cell(row, col)` and
    `cells_in(top, left, bottom, right)` returning cell values (None, float,
    str, or CellError) and raising FormulaError(REF_ERROR) off the sheet, and
    `angle_unit`, which SIN, COS, and TAN take angles in (DEGREES or RADIANS).
    """
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "ref":
        return to_number(sheet.cell(node[1], node[2]))
    if kind == "err":
        raise FormulaError(node[1])
    if kind == "neg":
        return -evaluate(node[1], sheet)
    if kind == "call":
        function = FUNCTIONS[node[1]]
        if function.ranges:
            return _finite(function.compute([_argument(arg, sheet) for arg in node[2]]))
        if any(arg[0] == "range" for arg in node[2]):
            raise FormulaError(VALUE_ERROR)  # takes single numbers, not ranges
        args = [evaluate(arg, sheet) for arg in node[2]]
        if function.angle:
            args.append(sheet.angle_unit)
        return _finite(function.compute(*args))
    _, op, left, right = node
    a = evaluate(left, sheet)
    b = evaluate(right, sheet)
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
            result = power(a, b)
    except ZeroDivisionError:
        raise FormulaError(DIV_ZERO_ERROR) from None
    except OverflowError:
        raise FormulaError(NUM_ERROR) from None
    return _finite(result)


def _finite(result) -> float:
    # A negative number to a fractional power gives a complex result in Python.
    if isinstance(result, complex) or not math.isfinite(result):
        raise FormulaError(NUM_ERROR)
    return result


def _argument(node, sheet) -> list:
    if node[0] == "range":
        return sheet.cells_in(*node[1:])
    if node[0] == "ref":
        return [sheet.cell(node[1], node[2])]
    return [evaluate(node, sheet)]


class _Parser:
    def __init__(self, tokens, names: dict):
        self.tokens = tokens
        self.names = names
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
        if kind == "name":
            return self.named(text)
        if text == "(":
            node = self.expr()
            self.expect(")")
            return node
        raise FormulaError(PARSE_ERROR)

    def expect(self, text: str) -> None:
        if self.take()[1] != text:
            raise FormulaError(PARSE_ERROR)

    def named(self, name: str):
        """A cell name, a constant, or a function call."""
        name = name.upper()
        if name in self.names and self.peek() != "(":
            cell = self.names[name]
            return ("err", REF_ERROR) if cell is None else ("ref", *cell)
        if name not in CONSTANTS:
            return self.call(name)
        if self.peek() == "(":
            self.take()
            self.expect(")")
        return ("num", CONSTANTS[name])

    def call(self, name: str):
        if name not in FUNCTIONS or self.peek() != "(":
            raise FormulaError(NAME_ERROR)
        self.take()
        args = [self.argument()]
        while self.peek() == ",":
            self.take()
            args.append(self.argument())
        self.expect(")")
        function = FUNCTIONS[name]
        if len(args) < function.min_args or (function.max_args is not None and len(args) > function.max_args):
            raise FormulaError(PARSE_ERROR)  # wrong number of arguments
        return ("call", name, args)

    def argument(self):
        is_endpoint = self.pos < len(self.tokens) and self.tokens[self.pos][0] in ("ref", "error")
        if is_endpoint and self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1][1] == ":":
            first = self.take()
            self.take()
            second = self.take()
            if second[0] not in ("ref", "error"):
                raise FormulaError(PARSE_ERROR)
            if "error" in (first[0], second[0]):
                return ("err", REF_ERROR)  # a range end was pushed off the sheet
            (r1, c1), (r2, c2) = parse_cell_name(first[1]), parse_cell_name(second[1])
            return ("range", min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))
        return self.expr()
