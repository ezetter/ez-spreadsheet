"""Parsing and evaluation of formulas such as =(A1+B2)*2^3, =SUM(A1:A9, C4),
or =2*PI*A1.

Grammar (lowest to highest precedence):

    expr    := term (('+' | '-') term)*
    term    := unary (('*' | '/') unary)*
    unary   := ('+' | '-') unary | power
    power   := primary ('^' unary)?
    primary := NUMBER | SHEET? REF | '#REF!' | CONSTANT ('(' ')')? | NAME '(' args ')'
             | '(' expr ')'
    args    := arg (',' arg)*
    arg     := SHEET? REF ':' SHEET? REF | expr

Ranges (A1:B9) appear only as function arguments. A constant such as PI may
be followed by empty parentheses, PI(), as in other spreadsheets.

A reference may name another sheet of the spreadsheet: Sheet2!A1, or
'Q1 Sales'!B2:B9 for a name that isn't a single word (a ' inside it is
doubled: 'Ann''s'!A1). Names and column aliases are each sheet's own, so
after a sheet's name come only cells.

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
from .names import Names, as_names, cell_text
from .numformat import format_number, parse_formatted  # noqa: F401 -- format_number re-exported
from .references import column_index, column_name, parse_cell_name

_TOKEN = re.compile(
    r"""\s*(?:
        (?P<sheet>(?:'(?:[^']|'')+'|[A-Za-z_][\w.]*)!)
      | (?P<number>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
      | (?P<ref>(?P<col_anchor>\$?)(?P<col>[A-Za-z]+)(?P<row_anchor>\$?)(?P<row>\d+))(?![\w.(])
      | (?P<error>\#REF!)
      | (?P<name>[A-Za-z_][\w.]*)
      | (?P<op>[-+*/^(),:])
    )""",
    re.VERBOSE,
)
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_BARE_SHEET = re.compile(r"[A-Za-z_][\w.]*")  # a sheet name that needn't be quoted
_KINDS = ("sheet", "number", "ref", "error", "name", "op")
_NO_NAMES = as_names({})  # (another sheet's cells: this sheet's names don't apply)


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
    return next(kind for kind in _KINDS if match.group(kind) is not None)


def sheet_prefix(name: str) -> str:
    """How a formula names a sheet before a reference: Sheet2!, or 'Q1 Sales'!."""
    return (name if _BARE_SHEET.fullmatch(name) else "'" + name.replace("'", "''") + "'") + "!"


def _sheet_name(token: str) -> str:
    """The sheet a sheet token (Sheet2!, 'Q1 Sales'!) names."""
    name = token[:-1]
    return name[1:-1].replace("''", "'") if name.startswith("'") else name


def same_sheet(a: str, b: str) -> bool:
    """Whether two sheet names are the same sheet's (case doesn't matter)."""
    return a.casefold() == b.casefold()


def _prefixes(matches: list) -> dict[int, str]:
    """The reference tokens after a sheet's name (both corners of a range
    after one, as in Sheet2!A1:B9), and the sheet each names."""
    found = {}
    for i, match in enumerate(matches):
        if match.group("sheet") is None or i + 1 >= len(matches) or matches[i + 1].group("ref") is None:
            continue
        sheet = _sheet_name(match.group("sheet"))
        found[i + 1] = sheet
        if i + 3 < len(matches) and matches[i + 2].group("op") == ":":
            j = i + 3
            if matches[j].group("sheet") is not None and j + 1 < len(matches):
                j += 1  # Sheet2!A1:Sheet2!B9
            if matches[j].group("ref") is not None:
                found[j] = sheet
    return found


def rename_sheet(formula: str, old: str, new: str) -> str:
    """A formula (with its leading '=') naming sheet `new` wherever it named `old`."""
    body = formula[1:]
    try:
        matches = _scan(body)
    except FormulaError:
        return formula
    pieces, pos = [], 0
    for match in matches:
        token = match.group("sheet")
        if token is not None and same_sheet(_sheet_name(token), old):
            pieces += [body[pos:match.start("sheet")], sheet_prefix(new)]
            pos = match.end("sheet")
    return "=" + "".join(pieces) + body[pos:]


def tokenize(text: str) -> list[tuple[str, str]]:
    return [(_token_kind(m), m.group(_token_kind(m))) for m in _scan(text)]


def shift_references(formula: str, d_row: int, d_col: int, names=()) -> str:
    """Move the relative references in a formula (with its leading '=') by an offset,
    as when the formula is pasted elsewhere. $-anchored parts stay put, and a
    reference pushed off the top or left of the sheet becomes #REF!. Text that
    doesn't tokenize is returned unchanged.

    `names` (a names.Names, or cell names): a cell name doesn't move. A column
    alias (t1) moves like $C1: its row number changes and its column doesn't.
    A shifted reference that would be spelled like a name gets a $ so it
    still means the cell (see names.cell_text). References to other sheets
    (Sheet2!A1) shift too, as plain cells.
    """
    names = as_names(names)
    body = formula[1:]
    try:
        matches = _scan(body)
    except FormulaError:
        return formula
    endpoints = _range_endpoints(matches)
    prefixed = _prefixes(matches)
    pieces = []
    pos = 0
    for i, match in enumerate(matches):
        corner = i in endpoints
        found = _token_cell(match, _NO_NAMES if i in prefixed else names, corner)
        if found is None:
            continue
        (row, col), alias = found
        if alias is not None:
            row += d_row  # a column alias: the row is relative, the column fixed
        else:
            if not match.group("col_anchor"):
                col += d_col
            if not match.group("row_anchor"):
                row += d_row
        if row < 0 or col < 0:
            shifted = REF_ERROR
        else:
            shifted = _cell_token_text(match, (row, col), alias, _NO_NAMES if i in prefixed else names, corner)
        start, stop = _token_span(match)
        pieces.append(body[pos:start])
        pieces.append(shifted)
        pos = stop
    pieces.append(body[pos:])
    return "=" + "".join(pieces)


def move_references(formula: str, move, move_range=None, names=(), columns_after=None,
                    sheet: str | None = None, home: bool = True) -> str:
    """Rewrite a formula's references for cells that have moved, such as when
    cells are inserted or deleted. `move(row, col)` gives a cell's new (row,
    col), or None if it's gone (that reference becomes #REF!). `move_range`,
    if given, does the same for a range's two corners at once, returning the
    new (start, end) or None; otherwise each corner is moved on its own.
    Unlike shift_references, $ anchors don't matter: a reference follows its
    cell. References to cells that didn't move keep their text exactly.
    `names` are handled as in shift_references: cell names don't move (their
    definitions do), a column alias follows its cell (staying an alias while
    the cell stays in the named column), and a moved reference spelled like a
    name gets a $. `columns_after` gives the column names' columns once
    they've moved too (inserting whole columns), if they have.

    The cells that moved are sheet `sheet`'s: references naming it
    (Sheet2!A1) follow them, and so do plain ones (A1) if the formula is on
    that sheet (`home`); references to other sheets stay as they are."""
    names = as_names(names)
    body = formula[1:]
    try:
        matches = _scan(body)
    except FormulaError:
        return formula
    endpoints = _range_endpoints(matches)
    prefixed = _prefixes(matches)
    pieces = []
    pos = 0

    def replace(start: int, stop: int, text: str) -> None:
        nonlocal pos
        pieces.append(body[pos:start])
        pieces.append(text)
        pos = stop

    i = 0
    while i < len(matches):
        match = matches[i]
        prefix = prefixed.get(i)
        here = _NO_NAMES if prefix is not None else names
        found = _token_cell(match, here, i in endpoints)
        if found is None or min(found[0]) < 0:
            i += 1
            continue
        named = prefix is not None and matches[i - 1].group("sheet") is not None
        start = _token_span(matches[i - 1] if named else match, "sheet")[0]  # (from its sheet's name)
        last_index = None
        if i + 2 < len(matches) and matches[i + 1].group("op") == ":":
            last_index = i + 3 if prefix is not None and matches[i + 2].group("sheet") is not None else i + 2
        last_found = _token_cell(matches[last_index], here, True) if last_index is not None else None
        if prefix is None and not home or prefix is not None and (sheet is None or not same_sheet(prefix, sheet)):
            i = last_index + 1 if last_found is not None else i + 1  # another sheet's cells: not moved
            continue
        if last_found is not None and move_range is not None:
            last = matches[last_index]
            old = (found[0], last_found[0])
            new = move_range(*old)
            if new is None or min(new[0] + new[1]) < 0:
                replace(start, _token_span(last)[1], REF_ERROR)
            elif new != old:
                replace(_token_span(match)[0], _token_span(last)[1],
                        f"{_cell_token_text(match, new[0], found[1], here, True, columns_after)}:"
                        f"{_cell_token_text(last, new[1], last_found[1], here, True, columns_after)}")
            i = last_index + 1
            continue
        old, alias = found
        new = move(*old)
        if new is None or min(new) < 0:
            replace(start, _token_span(match)[1], REF_ERROR)
        elif new != old:
            replace(*_token_span(match), _cell_token_text(match, new, alias, here, i in endpoints, columns_after))
        i += 1
    pieces.append(body[pos:])
    return "=" + "".join(pieces)


def _token_cell(match: re.Match, names, corner: bool):
    """The cell a token refers to, as ((row, col), alias), where alias is the
    column name if it's a column alias (t5). None if the token isn't a
    reference here: not a reference at all, or a cell name."""
    text = match.group("ref") or match.group("name")
    if text and "$" not in text:
        alias = names.alias(text)
        if alias is not None:
            return (alias[1], alias[2]), alias[0]
    if match.group("ref") is None:
        return None
    if not corner and "$" not in text and text in names.cells:
        return None  # a cell name spelled like a reference
    return _ref_cell(match), None


def _cell_token_text(match: re.Match, cell: tuple[int, int], alias, names, corner: bool,
                     columns_after=None) -> str:
    """How to write a reference to `cell` in place of the token matched.
    (`columns_after`: where the column names are once moved, if they have.)"""
    if alias is not None:
        named = (columns_after or names.columns).get(alias, names.columns[alias])
        if cell[1] == named:
            return f"{alias}{cell[0] + 1}"  # still in the named column
        return f"${column_name(cell[1])}{cell[0] + 1}"  # moved out of it: like $C1
    return _ref_text(match, cell, names, corner)


def _token_span(match: re.Match, *groups: str) -> tuple[int, int]:
    group = next(g for g in (*groups, "ref", "name") if match.group(g) is not None)
    return match.start(group), match.end(group)


def _ref_cell(match: re.Match) -> tuple[int, int]:
    return int(match.group("row")) - 1, column_index(match.group("col"))


def _ref_text(match: re.Match, cell: tuple[int, int], names=(), corner: bool = False) -> str:
    """A reference to `cell`, keeping the $ anchors of the reference matched.
    A bare one spelled like a name gets a $ before its column."""
    text = f"{match.group('col_anchor')}{column_name(cell[1])}{match.group('row_anchor')}{cell[0] + 1}"
    return cell_text(text, names, corner) if "$" not in text else text


def _range_endpoints(matches: list) -> set[int]:
    """Indexes of the tokens that are a range's corners (A1 in A1:B9). Those
    mean cells or column aliases, never cell names."""
    endpoints = set()
    for i, match in enumerate(matches):
        if match.group("op") == ":":
            endpoints.update({i - 1, i + 1})
    return endpoints


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
    ("call", name, [args]); and another sheet's cells, ("xref", sheet, row,
    col) and ("xrange", sheet, top, left, bottom, right).

    `names` (a names.Names, or a dict of cell names to cells) says what names
    mean; a name becomes a reference to its cell, or #REF! if that cell was
    deleted. A bare reference spelled like a name (A1) is the name; with a $
    ($A1) it's the cell. Range corners are cells or column aliases.
    """
    return _Parser(tokenize(text), as_names(names or {})).parse()


def references(node) -> tuple[set[tuple[int, int]], list[tuple[int, int, int, int]]]:
    """The single cells and the (top, left, bottom, right) ranges an AST refers
    to, on its own sheet (not those naming a sheet: Sheet2!A1)."""
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
    `angle_unit`, which SIN, COS, and TAN take angles in (DEGREES or RADIANS);
    and `on(name)`, another sheet by its name, likewise (raising
    FormulaError(REF_ERROR) if there's none).
    """
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "ref":
        return to_number(sheet.cell(node[1], node[2]))
    if kind == "xref":
        return to_number(sheet.on(node[1]).cell(node[2], node[3]))
    if kind == "err":
        raise FormulaError(node[1])
    if kind == "neg":
        return -evaluate(node[1], sheet)
    if kind == "call":
        function = FUNCTIONS[node[1]]
        if function.ranges:
            return _finite(function.compute([_argument(arg, sheet) for arg in node[2]]))
        if any(arg[0] in ("range", "xrange") for arg in node[2]):
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
    if node[0] == "xrange":
        return sheet.on(node[1]).cells_in(*node[2:])
    if node[0] == "xref":
        return [sheet.on(node[1]).cell(node[2], node[3])]
    return [evaluate(node, sheet)]


class _Parser:
    def __init__(self, tokens, names: Names):
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
            if "$" not in text:
                if text in self.names.cells:
                    return self._name_node(text)  # a name spelled like a cell; $A1 is the cell
                alias = self.names.alias(text)
                if alias is not None:
                    return self._alias_node(alias)
            return ("ref", *parse_cell_name(text))
        if kind == "error":
            return ("err", text)
        if kind == "sheet":
            kind, text = self.take()
            if kind != "ref":
                raise FormulaError(PARSE_ERROR)  # (after a sheet's name: just a cell)
            return ("xref", _sheet_name(self.tokens[self.pos - 2][1]), *parse_cell_name(text))
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
        """A cell name (matched exactly), a constant, or a function call
        (matched in any case)."""
        if self.peek() != "(":
            if name in self.names.cells:
                return self._name_node(name)
            alias = self.names.alias(name)
            if alias is not None:
                return self._alias_node(alias)
        name = name.upper()
        if name not in CONSTANTS:
            return self.call(name)
        if self.peek() == "(":
            self.take()
            self.expect(")")
        return ("num", CONSTANTS[name])

    def _name_node(self, name: str):
        cell = self.names.cells[name]
        return ("err", REF_ERROR) if cell is None else ("ref", *cell)

    def _alias_node(self, alias):
        _, row, col = alias
        return ("err", REF_ERROR) if row < 0 else ("ref", row, col)  # t0 names no cell

    def _corner(self, token):
        """A range corner: a cell, or a column alias. None for #REF!."""
        kind, text = token
        if kind == "error":
            return None
        if "$" not in text:
            alias = self.names.alias(text)
            if alias is not None:
                return (alias[1], alias[2]) if alias[1] >= 0 else None
        if kind != "ref":
            raise FormulaError(PARSE_ERROR)
        return parse_cell_name(text)

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
        if self._at_sheet_range():
            return self._sheet_range()
        is_endpoint = self.pos < len(self.tokens) and self.tokens[self.pos][0] in ("ref", "error", "name")
        if is_endpoint and self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1][1] == ":":
            first = self._corner(self.take())
            self.take()
            second = self._corner(self.take())
            if first is None or second is None:
                return ("err", REF_ERROR)  # a range end was pushed off the sheet
            (r1, c1), (r2, c2) = first, second
            return ("range", min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))
        return self.expr()

    def _at_sheet_range(self) -> bool:
        kinds = [kind for kind, _text in self.tokens[self.pos:self.pos + 3]]
        return kinds[:2] == ["sheet", "ref"] and len(kinds) == 3 and self.tokens[self.pos + 2][1] == ":"

    def _sheet_range(self):
        """Sheet2!A1:B9 (or Sheet2!A1:Sheet2!B9)."""
        sheet = _sheet_name(self.take()[1])
        r1, c1 = parse_cell_name(self.take()[1])
        self.take()
        kind, text = self.take()
        if kind == "sheet":
            if not same_sheet(_sheet_name(text), sheet):
                raise FormulaError(PARSE_ERROR)  # a range is on one sheet
            kind, text = self.take()
        if kind == "error":
            return ("err", REF_ERROR)
        if kind != "ref":
            raise FormulaError(PARSE_ERROR)
        r2, c2 = parse_cell_name(text)
        return ("xrange", sheet, min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))
