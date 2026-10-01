"""Number formats: how a numeric value is shown.

Numbers can be typed with a dollar sign and thousands separators ($1,234.50,
1,234, -$5). They count as numbers and are shown as typed. A cell can also be
given an explicit format, which then decides how its number is shown:

- general:  as plain as possible (1234.5)
- number:   fixed decimals, optionally with thousands separators (1,234.50)
- currency: like number, with a dollar sign ($1,234.50)
"""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

KINDS = ("general", "number", "currency")
MAX_DECIMALS = 10

# A number with a dollar sign or thousands separators. Commas must separate
# groups of three digits, so 1,5 (a decimal comma) isn't taken for 15.
_FORMATTED = re.compile(
    r"""(?P<sign>[+-]?)(?P<dollar>\$?)(?P<sign_after>[+-]?)
        (?P<whole>\d{1,3}(?:,\d{3})+|\d+)?
        (?:\.(?P<fraction>\d*))?""",
    re.VERBOSE,
)


@dataclass(frozen=True)
class NumberFormat:
    kind: str  # one of KINDS
    decimals: int = 2
    thousands: bool = True


GENERAL = NumberFormat("general")


def parse_formatted(text: str) -> tuple[float, NumberFormat] | None:
    """The value and implied format of a number typed with a dollar sign or
    thousands separators, or None for anything else (plain numbers included)."""
    match = _FORMATTED.fullmatch(text.strip())
    if not match:
        return None
    whole, fraction = match["whole"], match["fraction"]
    has_dollar, has_commas = bool(match["dollar"]), "," in (whole or "")
    if not (has_dollar or has_commas) or not (whole or fraction):
        return None
    if match["sign"] and match["sign_after"]:
        return None  # two signs
    negative = "-" in (match["sign"] + match["sign_after"])
    value = float((whole or "0").replace(",", "") + "." + (fraction or "0"))
    fmt = NumberFormat("currency" if has_dollar else "number", len(fraction or ""), has_commas)
    return (-value if negative else value), fmt


def format_number(value: float) -> str:
    """General format: whole numbers as integers, others to 10 significant digits."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.10g}"


def format_value(value: float, fmt: NumberFormat) -> str:
    if fmt.kind == "general":
        return format_number(value)
    # Round halves up, as spreadsheets do, from the shortest decimal form of
    # the value: 2.675 shows as 2.68 even though its binary value is 2.67499….
    rounded = Decimal(repr(abs(value))).quantize(Decimal(1).scaleb(-fmt.decimals), ROUND_HALF_UP)
    digits = f"{rounded:{',' if fmt.thousands else ''}f}"
    negative = value < 0 and any(d not in "0.," for d in digits)  # no "-0.00"
    return ("-" if negative else "") + ("$" if fmt.kind == "currency" else "") + digits


def to_json(fmt: NumberFormat) -> dict:
    return {"kind": fmt.kind, "decimals": fmt.decimals, "thousands": fmt.thousands}


def from_json(data) -> NumberFormat | None:
    """A format read from a file, or None if it's malformed."""
    if not isinstance(data, dict) or data.get("kind") not in KINDS:
        return None
    decimals = data.get("decimals", 2)
    thousands = data.get("thousands", True)
    if (not isinstance(decimals, int) or isinstance(decimals, bool)
            or not 0 <= decimals <= MAX_DECIMALS or not isinstance(thousands, bool)):
        return None
    return NumberFormat(data["kind"], decimals, thousands)
