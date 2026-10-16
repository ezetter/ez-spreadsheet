"""Number formats: how a numeric value is shown, as Google Sheets has them.

Numbers can be typed with a dollar sign and thousands separators ($1,234.50,
1,234, -$5), or as a percentage (12.5% is 0.125), or as a date or time
(9/26/2008, 2008-09-26, 3:59 PM, 9/26/2008 15:59), which is the number of
days from 12/30/1899. They count as numbers and are shown as typed. A cell can also be given an explicit format, which then
decides how its number is shown:

- general:    as plain as possible (1234.5); the menus call it Automatic
- text:       Plain text: what's typed is text, even 123 (formulas still work)
- number:     fixed decimals, optionally with thousands separators (1,234.50)
- percent:    times 100, with a percent sign (10.12%)
- scientific: a mantissa and a power of ten (1.01E+03)
- accounting: a dollar sign apart, negatives in parentheses: $ (1,000.12)
- financial:  negatives in parentheses: (1,000.12)
- currency:   like number, with a dollar sign ($1,234.50)
- date, time, datetime, duration: the number as days, counted from
  12/30/1899 as spreadsheets do (39717.66 is 9/26/2008 3:50:24 PM), or as
  a length of time (1.0007 days is 24:01:00)
"""

import datetime
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

KINDS = ("general", "text", "number", "percent", "scientific", "accounting", "financial", "currency",
         "date", "time", "datetime", "duration")
DATE_KINDS = ("date", "time", "datetime", "duration")  # no decimals to show more or fewer of
MAX_DECIMALS = 10
_EPOCH = datetime.datetime(1899, 12, 30)  # day 0, as spreadsheets count them

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
TEXT = NumberFormat("text")

# The Format menu's number formats, and the toolbar's 123 menu: (name,
# format, an example), None between groups. Currency rounded is just
# currency with no decimals.
MENU_FORMATS = (
    ("Automatic", GENERAL, ""),
    ("Plain text", TEXT, ""),
    None,
    ("Number", NumberFormat("number"), "1,000.12"),
    ("Percent", NumberFormat("percent", thousands=False), "10.12%"),
    ("Scientific", NumberFormat("scientific"), "1.01E+03"),
    None,
    ("Accounting", NumberFormat("accounting"), "$ (1,000.12)"),
    ("Financial", NumberFormat("financial"), "(1,000.12)"),
    ("Currency", NumberFormat("currency"), "$1,000.12"),
    ("Currency rounded", NumberFormat("currency", 0), "$1,000"),
    None,
    ("Date", NumberFormat("date", 0), "9/26/2008"),
    ("Time", NumberFormat("time", 0), "3:59:00 PM"),
    ("Date time", NumberFormat("datetime", 0), "9/26/2008 15:59:00"),
    ("Duration", NumberFormat("duration", 0), "24:01:00"),
)

# A number typed as a percentage: 12.5%, -3%, 1,200%.
# A date (9/26/2008, 9/26/08, 2008-09-26), a time (15:59, 3:59 PM, 15:59:30), or both.
_DATE = r"(?:(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4}|\d{2})|(?P<iso_year>\d{4})-(?P<iso_month>\d{1,2})-(?P<iso_day>\d{1,2}))"
_TIME = r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}(?:\.\d+)?))?(?:\s*(?P<half>[AaPp][Mm]))?"
_DATE_TIMES = (re.compile(rf"{_DATE}(?:[ T]+{_TIME})?"), re.compile(_TIME))
_PERCENT = re.compile(r"(?P<sign>[+-]?)(?P<whole>\d{1,3}(?:,\d{3})+|\d+)?(?:\.(?P<fraction>\d*))?%")


def parse_formatted(text: str) -> tuple[float, NumberFormat] | None:
    """The value and implied format of a number typed with a dollar sign or
    thousands separators, or as a percentage, or None for anything else
    (plain numbers included)."""
    when = parse_date_time(text)
    if when is not None:
        return when
    percent = _PERCENT.fullmatch(text.strip())
    if percent:
        whole, fraction = percent["whole"], percent["fraction"]
        if not (whole or fraction):
            return None
        digits = (whole or "0").replace(",", "") + "." + (fraction or "0")
        value = float(Decimal(digits) / 100)
        fmt = NumberFormat("percent", len(fraction or ""), "," in (whole or ""))
        return (-value if percent["sign"] == "-" else value), fmt
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


def parse_date_time(text: str) -> tuple[float, NumberFormat] | None:
    """The day number (days from 12/30/1899, with the time of day as a
    fraction) and the Date, Time, or Date time format of a typed date, time,
    or both, or None if it isn't one (or isn't a real date: 2/30/2024).
    Two-digit years are 2000-2029 below 30, else 1930-1999, as Google
    Sheets takes them."""
    match = next(filter(None, (pattern.fullmatch(text.strip()) for pattern in _DATE_TIMES)), None)
    if not match:
        return None
    groups = match.groupdict()
    days = 0
    has_date = groups.get("year") is not None or groups.get("iso_year") is not None
    if has_date:
        if match["year"] is not None:
            year, month, day = int(match["year"]), int(match["month"]), int(match["day"])
            if len(match["year"]) == 2:
                year += 2000 if year < 30 else 1900
        else:
            year, month, day = int(match["iso_year"]), int(match["iso_month"]), int(match["iso_day"])
        try:
            days = (datetime.datetime(year, month, day) - _EPOCH).days
        except ValueError:
            return None
    has_time = match["hour"] is not None
    if has_time:
        hour, minute = int(match["hour"]), int(match["minute"])
        second = float(match["second"] or 0)
        if match["half"]:  # 12 AM is midnight, 12 PM noon
            if not 1 <= hour <= 12:
                return None
            hour = hour % 12 + (12 if match["half"].lower() == "pm" else 0)
        if hour > 23 or minute > 59 or second >= 60:
            return None
        days += (hour * 3600 + minute * 60 + second) / 86400
    kind = "datetime" if has_date and has_time else "date" if has_date else "time"
    return float(days), NumberFormat(kind, 0)


def format_number(value: float) -> str:
    """General format: whole numbers as integers, others to 10 significant digits."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.10g}"


def format_value(value: float, fmt: NumberFormat) -> str:
    kind = fmt.kind
    if kind in ("general", "text"):
        return format_number(value)
    if kind == "scientific":
        return _scientific(value, fmt.decimals)
    if kind in DATE_KINDS:
        return _date_time(value, kind)
    if kind == "percent":
        value = float(Decimal(repr(value)) * 100)
    digits, negative = _fixed(value, fmt)
    if kind == "accounting":  # the $ apart; a space after, where a negative's ) goes, so the digits line up
        if not any(d not in "0.," for d in digits):
            return "$ - "
        return f"$ ({digits})" if negative else f"$ {digits} "
    if kind == "financial":
        return f"({digits})" if negative else digits
    sign = "-" if negative else ""
    if kind == "percent":
        return f"{sign}{digits}%"
    return sign + ("$" if kind == "currency" else "") + digits


def _fixed(value: float, fmt: NumberFormat) -> tuple[str, bool]:
    """The value's digits to fmt's decimals (and thousands separators), and
    whether it's negative (not if they round to zero: no "-0.00")."""
    # Round halves up, as spreadsheets do, from the shortest decimal form of
    # the value: 2.675 shows as 2.68 even though its binary value is 2.67499….
    rounded = Decimal(repr(abs(value))).quantize(Decimal(1).scaleb(-fmt.decimals), ROUND_HALF_UP)
    digits = f"{rounded:{',' if fmt.thousands else ''}f}"
    return digits, value < 0 and any(d not in "0.," for d in digits)


def _scientific(value: float, decimals: int) -> str:
    """1.01E+03: one digit before the point, halves rounded up."""
    number = Decimal(repr(abs(value)))
    exponent = number.adjusted() if number else 0
    mantissa = number.scaleb(-exponent).quantize(Decimal(1).scaleb(-decimals), ROUND_HALF_UP)
    if mantissa >= 10:  # 9.996 to two decimals: 1.00E+01
        exponent += 1
        mantissa = number.scaleb(-exponent).quantize(Decimal(1).scaleb(-decimals), ROUND_HALF_UP)
    sign = "-" if value < 0 and mantissa else ""
    return f"{sign}{mantissa}E{'-' if exponent < 0 else '+'}{abs(exponent):02d}"


def _date_time(value: float, kind: str) -> str:
    """The value as days from 12/30/1899 (a date, a time of day, or both),
    or as a length of time in hours, minutes, and seconds."""
    seconds = round(value * 86400)
    if kind == "duration":
        sign, seconds = ("-" if seconds < 0 else ""), abs(seconds)
        return f"{sign}{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"
    try:
        moment = _EPOCH + datetime.timedelta(seconds=seconds)
    except OverflowError:
        return format_number(value)  # before year 1 or after 9999: no date to show
    date = f"{moment.month}/{moment.day}/{moment.year}"
    if kind == "date":
        return date
    if kind == "time":
        hour = moment.hour % 12 or 12
        return f"{hour}:{moment.minute:02d}:{moment.second:02d} {'AM' if moment.hour < 12 else 'PM'}"
    return f"{date} {moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}"


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
