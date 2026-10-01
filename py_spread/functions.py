"""Spreadsheet functions, computed with NumPy.

Each function takes a list of arguments, each a list of cell values (for a
range or a single reference) or a one-item list holding a computed number,
and returns a float or raises FormulaError.
"""

import numpy as np

from .errors import DIV_ZERO_ERROR, NUM_ERROR, CellError, FormulaError


def numbers(args) -> np.ndarray:
    """The numbers among the arguments; empty cells and text are skipped and
    the first error value is raised."""
    found = []
    for values in args:
        for value in values:
            if isinstance(value, float):
                found.append(value)
            elif isinstance(value, CellError):
                raise FormulaError(value.code)
    return np.array(found, dtype=float)


def _aggregate(compute, minimum: int, too_few_error: str):
    """Wrap a NumPy reduction that needs at least `minimum` numbers."""

    def function(args) -> float:
        data = numbers(args)
        if data.size < minimum:
            raise FormulaError(too_few_error)
        with np.errstate(all="ignore"):  # overflow becomes inf, reported as #NUM!
            return float(compute(data))

    return function


FUNCTIONS = {
    "SUM": _aggregate(np.sum, 0, NUM_ERROR),
    "MEAN": _aggregate(np.mean, 1, DIV_ZERO_ERROR),
    "MEDIAN": _aggregate(np.median, 1, NUM_ERROR),
    # Sample standard deviation (n - 1 in the denominator), like STDEV in other spreadsheets.
    "STDDEV": _aggregate(lambda data: np.std(data, ddof=1), 2, DIV_ZERO_ERROR),
}
