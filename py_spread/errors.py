"""Error values shown in cells, and the exception that produces them."""

from dataclasses import dataclass

PARSE_ERROR = "#ERROR!"
VALUE_ERROR = "#VALUE!"
DIV_ZERO_ERROR = "#DIV/0!"
REF_ERROR = "#REF!"
NUM_ERROR = "#NUM!"
CIRCULAR_ERROR = "#CIRC!"
NAME_ERROR = "#NAME?"


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
