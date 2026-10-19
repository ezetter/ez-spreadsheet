"""Spreadsheet functions and constants, computed with NumPy.

Aggregate functions (SUM, MEAN, …) take a list of arguments, each a list of
cell values (for a range or a single reference) or a one-item list holding a
computed number. Other functions take one number per argument, and those that
take an angle also get the sheet's angle unit. Either kind returns a float or
raises FormulaError.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .errors import DIV_ZERO_ERROR, NUM_ERROR, CellError, FormulaError


DEGREES = "degrees"
RADIANS = "radians"
ANGLE_UNITS = (DEGREES, RADIANS)  # what SIN, COS, and TAN can take angles in

# Named values usable in formulas, such as =2*PI*A1.
CONSTANTS = {"PI": math.pi}


@dataclass(frozen=True)
class Function:
    compute: Callable
    min_args: int
    max_args: int | None  # None for any number
    ranges: bool  # aggregate: takes ranges; otherwise each argument is one number
    angle: bool = False  # takes an angle, so compute also gets the angle unit
    counts: bool = False  # gives a count, not a number in its arguments' units (so not shown in their format)


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


def count(args) -> float:
    """How many numbers there are among the arguments; empty cells, text, and
    errors aren't counted."""
    return float(sum(1 for values in args for value in values if isinstance(value, float)))


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


def _right_angles(angle: float, unit: str) -> int | None:
    """How many right angles `angle` is, if it's a whole number of them.

    In radians that's only ever true to within rounding, since π isn't a float,
    so an angle within a few units in the last place of a multiple of π/2
    counts. That makes SIN(PI) exactly 0 rather than 1.2e-16.
    """
    if not math.isfinite(angle):
        raise FormulaError(NUM_ERROR)
    if unit == DEGREES:
        return int(angle // 90) if angle % 90 == 0 else None
    right_angle = math.pi / 2
    count = round(angle / right_angle)
    if abs(angle - count * right_angle) <= 4 * math.ulp(angle):
        return count
    return None


def _radians(angle: float, unit: str) -> float:
    if unit == DEGREES:
        return np.deg2rad(math.fmod(angle, 360))  # fmod first keeps large angles precise
    return angle


def sine(angle: float, unit: str) -> float:
    right_angles = _right_angles(angle, unit)
    if right_angles is not None:
        return (0.0, 1.0, 0.0, -1.0)[right_angles % 4]  # exactly, not 1.2e-16
    return _clean(np.sin(_radians(angle, unit)))


def cosine(angle: float, unit: str) -> float:
    right_angles = _right_angles(angle, unit)
    if right_angles is not None:
        return (1.0, 0.0, -1.0, 0.0)[right_angles % 4]
    return _clean(np.cos(_radians(angle, unit)))


def tangent(angle: float, unit: str) -> float:
    right_angles = _right_angles(angle, unit)
    if right_angles is not None:
        if right_angles % 2:
            raise FormulaError(DIV_ZERO_ERROR)  # the cosine is zero: no tangent at ±90°
        return 0.0
    return _clean(np.tan(_radians(angle, unit)))


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
    "COUNT": Function(count, 1, None, ranges=True, counts=True),
    # Trigonometry, in the sheet's angle unit.
    "SIN": Function(sine, 1, 1, ranges=False, angle=True),
    "COS": Function(cosine, 1, 1, ranges=False, angle=True),
    "TAN": Function(tangent, 1, 1, ranges=False, angle=True),
    "EXP": Function(exp, 1, 1, ranges=False),  # e raised to the argument
    "POW": Function(power, 2, 2, ranges=False),  # the first argument raised to the second
}
