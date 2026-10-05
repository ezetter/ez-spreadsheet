"""Spreadsheet functions, computed with NumPy.

Aggregate functions (SUM, MEAN, …) take a list of arguments, each a list of
cell values (for a range or a single reference) or a one-item list holding a
computed number. Other functions take one number per argument. Either kind
returns a float or raises FormulaError.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .errors import DIV_ZERO_ERROR, NUM_ERROR, CellError, FormulaError


@dataclass(frozen=True)
class Function:
    compute: Callable
    min_args: int
    max_args: int | None  # None for any number
    ranges: bool  # aggregate: takes ranges; otherwise each argument is one number


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


def power(base: float, exponent: float):
    """base ** exponent, for both the ^ operator and POW. A complex or infinite
    result (such as (-8)^(1/3)) is reported as #NUM! by the caller."""
    try:
        return base ** exponent
    except ZeroDivisionError:
        raise FormulaError(DIV_ZERO_ERROR) from None
    except OverflowError:
        raise FormulaError(NUM_ERROR) from None


def _clean(value: float) -> float:
    """Round to 15 significant digits, the precision spreadsheets calculate
    with, so SIN(30) is 0.5 rather than 0.49999999999999994."""
    return float(f"{value:.15g}")


def sin_degrees(angle: float) -> float:
    angle = math.fmod(angle, 360)
    if angle % 180 == 0:
        return 0.0  # exactly, not 1.2e-16
    return _clean(np.sin(np.deg2rad(angle)))


def cos_degrees(angle: float) -> float:
    angle = math.fmod(angle, 360)
    if (angle - 90) % 180 == 0:
        return 0.0
    return _clean(np.cos(np.deg2rad(angle)))


def tan_degrees(angle: float) -> float:
    angle = math.fmod(angle, 360)
    if angle % 180 == 0:
        return 0.0
    if angle % 90 == 0:
        raise FormulaError(DIV_ZERO_ERROR)  # the cosine is zero: no tangent at ±90°
    return _clean(np.tan(np.deg2rad(angle)))


def exp(exponent: float) -> float:
    with np.errstate(all="ignore"):  # overflow becomes inf, reported as #NUM!
        return float(np.exp(exponent))


FUNCTIONS = {
    "SUM": Function(_aggregate(np.sum, 0, NUM_ERROR), 1, None, ranges=True),
    "MEAN": Function(_aggregate(np.mean, 1, DIV_ZERO_ERROR), 1, None, ranges=True),
    "MEDIAN": Function(_aggregate(np.median, 1, NUM_ERROR), 1, None, ranges=True),
    # Sample standard deviation (n - 1 in the denominator), like STDEV in other spreadsheets.
    "STDDEV": Function(_aggregate(lambda data: np.std(data, ddof=1), 2, DIV_ZERO_ERROR),
                       1, None, ranges=True),
    # Trigonometry in degrees.
    "SIN": Function(sin_degrees, 1, 1, ranges=False),
    "COS": Function(cos_degrees, 1, 1, ranges=False),
    "TAN": Function(tan_degrees, 1, 1, ranges=False),
    "EXP": Function(exp, 1, 1, ranges=False),  # e raised to the argument
    "POW": Function(power, 2, 2, ranges=False),  # the first argument raised to the second
}
