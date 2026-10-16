"""Custom number formats, written as Google Sheets (and Excel) write them.

A pattern has up to four sections, separated by semicolons: for positive
numbers, negative numbers, zero, and text. With one section, it's for every
number (negatives get a minus sign); with two, the first is for positive
numbers and zero. A section can start with a color, such as [Red], or a
condition, such as [>1000], which then chooses the section instead.

In a number section:
- 0 is a digit, shown even if it's a leading or trailing zero; # is a digit
  shown only if it's needed; ? is one shown as a space if it isn't
- . is the decimal point; a comma between digits separates thousands, and
  one after the last digit divides by a thousand (#,##0,"K")
- % multiplies by 100 and shows the sign; E+00 (or E-00) shows the number in
  scientific notation
- a fraction: # ?/? (1.25 is 1 1/4), # ??/?? (denominators up to 99), # ?/8
  (eighths), ?/? (no whole part: 1.5 is 3/2), 0/100 (hundredths)
- "text" and \\x show text as is; _x shows a space as wide as x; *x is
  ignored; [$€] shows a currency sign; most other characters ($ - + ( ) / :
  and spaces) show as they are; General shows the number plainly

In a date or time section, the number is days from 12/30/1899:
- d, dd, ddd, dddd: the day (1, 01, Mon, Monday); m, mm, mmm, mmmm, mmmmm:
  the month (9, 09, Sep, September, S); yy, yyyy: the year (08, 2008)
- h, hh: the hour; m, mm right after an hour, or right before seconds, are
  minutes; s, ss: seconds, with .0, .00, or .000 for fractions of one
- AM/PM, am/pm, A/P: a 12-hour clock; [h], [m], [s]: elapsed hours, minutes,
  or seconds, which can go beyond 24, 60, and 60

In the text section, @ is the text.
"""

import datetime
import math
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

COLORS = {"black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000", "blue": "#0000ff",
          "yellow": "#ffff00", "magenta": "#ff00ff", "cyan": "#00ffff"}
_EPOCH = datetime.datetime(1899, 12, 30)
_CONDITION = re.compile(r"\[(<=|>=|<>|<|>|=)\s*(-?\d+(?:\.\d+)?)\]")
_OPERATORS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b,
              ">=": lambda a, b: a >= b, "=": lambda a, b: a == b, "<>": lambda a, b: a != b}
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class PatternError(ValueError):
    """A pattern that can't be read; the message says why."""


@dataclass
class _Section:
    tokens: list = field(default_factory=list)  # (kind, text): see _tokenize
    color: str | None = None  # a color name, lowercase
    condition: tuple | None = None  # (operator, number)

    @property
    def kinds(self) -> set:
        return {kind for kind, _text in self.tokens}

    @property
    def is_date(self) -> bool:
        return bool(self.kinds & {"date", "ampm", "elapsed"})

    @property
    def is_number(self) -> bool:
        return bool(self.kinds & {"digit", "general"})


@dataclass
class CustomFormat:
    """A pattern, read into its sections."""

    pattern: str
    sections: list

    def format(self, value) -> tuple[str, str | None]:
        """(the text, the color, if any) showing a number, or text (from the
        text section, if there is one; else as it is)."""
        if isinstance(value, str):
            section = self._text_section()
            if section is None:
                return value, None
            return _render_text(section, value), section.color
        section, signed = self._number_section(value)
        if section is None:
            return _general(value), None
        if section.is_date:
            return _render_date(section, value), section.color
        text = _render_number(section, abs(value))
        if signed and value < 0 and section.is_number and re.search(r"[1-9]", text):
            text = "-" + text  # first, before any $: -$1,000.12
        return text, section.color

    def _number_section(self, value: float):
        """The section for a number, and whether it shows the number's own sign."""
        numbered = [s for s in self.sections if not _is_text_section(s)]
        if not numbered:
            return None, True
        if any(s.condition for s in numbered):
            for section in numbered:
                if section.condition and _OPERATORS[section.condition[0]](value, section.condition[1]):
                    return section, True
            rest = [s for s in numbered if not s.condition]
            return (rest[0] if rest else numbered[-1]), True
        if len(numbered) == 1:
            return numbered[0], True
        if value < 0:
            return numbered[1], False
        if value == 0 and len(numbered) >= 3:
            return numbered[2], True
        return numbered[0], True

    def _text_section(self):
        texts = [s for s in self.sections if _is_text_section(s)]
        if texts:
            return texts[0]
        return self.sections[3] if len(self.sections) == 4 else None


def parse_pattern(pattern: str) -> CustomFormat:
    """The pattern read into sections; PatternError if it can't be."""
    if not pattern.strip():
        raise PatternError("The format is empty.")
    sections = [_parse_section(text) for text in _split_sections(pattern)]
    if len(sections) > 4:
        raise PatternError("A format has at most four sections: positive; negative; zero; text.")
    return CustomFormat(pattern, sections)


def format_custom(value, pattern: str) -> tuple[str, str | None]:
    """(text, color) for a value in a pattern (which has to be readable)."""
    return parse_pattern(pattern).format(value)


def pattern_problem(pattern: str) -> str | None:
    """Why a pattern can't be used, or None if it can."""
    try:
        parse_pattern(pattern)
    except PatternError as e:
        return str(e)
    return None


# --- Reading a pattern ---

def _split_sections(pattern: str) -> list[str]:
    sections, current, i = [], "", 0
    while i < len(pattern):
        char = pattern[i]
        if char == '"':
            end = pattern.find('"', i + 1)
            if end < 0:
                raise PatternError("A quotation mark isn't closed.")
            current += pattern[i:end + 1]
            i = end + 1
            continue
        if char in "\\_*" and i + 1 < len(pattern):
            current += pattern[i:i + 2]
            i += 2
            continue
        if char == "[":
            end = pattern.find("]", i)
            if end < 0:
                raise PatternError("A [ isn't closed with ].")
            current += pattern[i:end + 1]
            i = end + 1
            continue
        if char == ";":
            sections.append(current)
            current = ""
        else:
            current += char
        i += 1
    sections.append(current)
    return sections


def _parse_section(text: str) -> _Section:
    section = _Section()
    i = 0
    while i < len(text):
        char = text[i]
        lower = text[i:].lower()
        if char == '"':
            end = text.index('"', i + 1)
            section.tokens.append(("literal", text[i + 1:end]))
            i = end + 1
        elif char == "\\" and i + 1 < len(text):
            section.tokens.append(("literal", text[i + 1]))
            i += 2
        elif char == "_" and i + 1 < len(text):
            section.tokens.append(("literal", " "))
            i += 2
        elif char == "*" and i + 1 < len(text):
            i += 2  # a fill character: the cell is as wide as its text, so there's nothing to fill
        elif char == "[":
            end = text.index("]", i)
            inside = text[i + 1:end]
            condition = _CONDITION.fullmatch(text[i:end + 1])
            if inside.lower() in COLORS:
                section.color = inside.lower()
            elif condition:
                section.condition = (condition[1], float(condition[2]))
            elif re.fullmatch(r"h+|m+|s+", inside, re.I):
                section.tokens.append(("elapsed", inside.lower()))
            elif inside.startswith("$"):
                section.tokens.append(("literal", inside[1:].split("-")[0]))
            else:
                raise PatternError(f"[{inside}] isn't a color, a condition, or elapsed time.")
            i = end + 1
        elif lower.startswith("general"):
            section.tokens.append(("general", ""))
            i += 7
        elif lower.startswith("am/pm") or lower.startswith("a/p"):
            length = 5 if lower.startswith("am/pm") else 3
            section.tokens.append(("ampm", text[i:i + length]))
            i += length
        elif char.lower() in "ydhs" or char.lower() == "m":
            run = re.match(rf"{re.escape(char)}+", text[i:], re.I)[0]
            section.tokens.append(("date", run.lower()))
            i += len(run)
        elif char in "0#?":
            section.tokens.append(("digit", char))
            i += 1
        elif char in "Ee" and re.match(r"[Ee][+-][0#?]", text[i:]):
            section.tokens.append(("exponent", text[i + 1]))
            i += 2
        elif char == ".":
            section.tokens.append(("point", "."))
            i += 1
        elif char == ",":
            section.tokens.append(("comma", ","))
            i += 1
        elif char == "%":
            section.tokens.append(("percent", "%"))
            i += 1
        elif char == "@":
            section.tokens.append(("text", "@"))
            i += 1
        else:
            section.tokens.append(("literal", char))
            i += 1
    if section.is_date:
        section.tokens = _date_tokens(section.tokens)
    return section


def _date_tokens(tokens: list) -> list:
    """In a date or time section: m and mm right after an hour, or before
    seconds, are minutes; .0 after seconds is a fraction of one; digits and
    points elsewhere are just characters."""
    out = []
    for index, (kind, text) in enumerate(tokens):
        if kind == "date" and text in ("m", "mm"):
            before = [t for t in tokens[:index] if t[0] in ("date", "elapsed")]
            after = [t for t in tokens[index + 1:] if t[0] in ("date", "elapsed")]
            if (before and before[-1][1][0] == "h") or (after and after[0][1][0] == "s"):
                kind = "minutes"
        elif kind == "point" and out and out[-1][0] in ("date", "elapsed") and out[-1][1][0] == "s":
            zeros = 0
            while index + 1 + zeros < len(tokens) and tokens[index + 1 + zeros] == ("digit", "0"):
                zeros += 1
            if zeros:
                out.append(("fraction", zeros))
                continue
        elif kind == "digit" and out and out[-1][0] == "fraction":
            continue  # (part of the fraction)
        elif kind in ("digit", "point", "comma", "percent"):
            kind = "literal"
        out.append((kind, text))
    return out


def _is_text_section(section: _Section) -> bool:
    return "text" in section.kinds


# --- Showing a value ---

def _general(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.10g}"


def _render_text(section: _Section, text: str) -> str:
    return "".join(text if kind == "text" else part for kind, part in section.tokens
                   if kind in ("text", "literal"))


def _render_number(section: _Section, value: float) -> str:
    tokens = section.tokens
    if not section.is_number:  # all text: "zero", or -
        return "".join(part for kind, part in tokens if kind == "literal")
    if "general" in section.kinds:
        return "".join(_general(value) if kind == "general" else part for kind, part in tokens
                       if kind in ("general", "literal"))
    fraction = _fraction_parts(tokens)
    if fraction is not None:
        return _render_fraction(tokens, fraction, value)
    digits = [i for i, (kind, _) in enumerate(tokens) if kind == "digit"]
    first, last = digits[0], digits[-1]
    exponent_at = next((i for i, (kind, _) in enumerate(tokens) if kind == "exponent"), None)
    mantissa_end = exponent_at if exponent_at is not None else last + 1
    point_at = next((i for i in range(first, mantissa_end) if tokens[i][0] == "point"), None)
    # Commas: between the integer digits, separating thousands; right after the last digit (before the
    # point, or at the end), each a thousand fewer.
    integer_end = point_at if point_at is not None else mantissa_end
    integer_digits = [i for i in digits if i < integer_end]
    mantissa_digits = [i for i in digits if i < mantissa_end]
    scale_commas = 0
    for after in {mantissa_digits[-1] + 1, *([integer_digits[-1] + 1] if integer_digits else [])}:
        j = after
        while j < len(tokens) and tokens[j][0] == "comma":
            scale_commas += 1
            j += 1
    grouped = any(tokens[i][0] == "comma" for i in range(first, integer_digits[-1])) if integer_digits else False
    spaced = any(tokens[i][0] == "literal" for i in range(first, integer_digits[-1])) if integer_digits else False
    percents = sum(1 for kind, _ in tokens if kind == "percent")
    number = Decimal(repr(value)) * (Decimal(100) ** percents) / (Decimal(1000) ** scale_commas)
    negative = number < 0
    number = abs(number)
    fraction_places = [i for i in digits if point_at is not None and point_at < i < mantissa_end]
    exponent_text = ""
    if exponent_at is not None:
        whole_places = max(len(integer_digits), 1)
        if whole_places > 1 and tokens[integer_digits[0]][1] == "#":  # ##0.0E+0: powers a multiple of 3
            power = (number.adjusted() // whole_places) * whole_places if number else 0
        else:
            power = (number.adjusted() - (whole_places - 1)) if number else 0
        mantissa = number.scaleb(-power).quantize(Decimal(1).scaleb(-len(fraction_places)), ROUND_HALF_UP)
        if mantissa >= Decimal(10) ** whole_places:
            power += 1
            mantissa = number.scaleb(-power).quantize(Decimal(1).scaleb(-len(fraction_places)), ROUND_HALF_UP)
        number = mantissa
        exponent_digits = [i for i in digits if i > exponent_at]
        sign = "-" if power < 0 else ("+" if tokens[exponent_at][1] == "+" else "")
        exponent_text = "E" + sign + _fill_integer(str(abs(power)), [tokens[i][1] for i in exponent_digits])
    rounded = number.quantize(Decimal(1).scaleb(-len(fraction_places)), ROUND_HALF_UP)
    whole, _, fraction = f"{rounded:f}".partition(".")
    whole = whole.lstrip("0")
    places = [tokens[i][1] for i in integer_digits]
    if spaced:  # characters among the digits (000-00-0000): a digit (or more, at the start) in each place
        integer_texts = dict(zip(integer_digits, _fill_places(whole, places)))
    else:
        integer_text = _fill_integer(whole, places)
        integer_texts = {integer_digits[0]: _group(integer_text) if grouped else integer_text} if integer_digits else {}
    fraction_text = _fill_fraction(fraction, [tokens[i][1] for i in fraction_places])
    sign = "-" if negative and any(c not in "0 .," for c in whole + fraction) else ""
    out = []
    signed = False
    placed_point = False
    for index, (kind, part) in enumerate(tokens):
        if index in integer_digits:
            if not signed:
                out.append(sign)
                signed = True
            out.append(integer_texts.get(index, ""))
        elif kind == "point" and index == point_at:
            if not signed:  # no integer digits: the sign goes before the point
                out.append(sign)
                signed = True
            out.append(".")
            placed_point = True
        elif index in fraction_places:
            if placed_point and fraction_text is not None:
                out.append(fraction_text)
                fraction_text = None
        elif kind == "exponent":
            out.append(exponent_text)
        elif kind == "digit":  # an exponent's digits: shown with it
            continue
        elif kind in ("literal", "percent"):
            out.append(part)
    return "".join(out)


def _fraction_parts(tokens: list):
    """For a fraction (# ?/?): (the whole number's digit indexes, the
    numerator's, the slash's, the denominator's, and its fixed value, if
    it's written as digits: ?/8, 0/100), or None if it isn't one."""
    for slash, token in enumerate(tokens):
        if token != ("literal", "/") or slash == 0 or tokens[slash - 1][0] != "digit":
            continue
        after = slash + 1
        while after < len(tokens) and (tokens[after][0] == "digit" or
                                       tokens[after][0] == "literal" and tokens[after][1].isdigit()):
            after += 1
        denominator = list(range(slash + 1, after))
        if not denominator:
            continue
        start = slash - 1
        while start > 0 and tokens[start - 1][0] == "digit":
            start -= 1
        numerator = list(range(start, slash))
        whole = [i for i in range(start) if tokens[i][0] == "digit"]
        written = "".join(tokens[i][1] for i in denominator)
        fixed = int(written.replace("?", "0").replace("#", "0")) if any(
            tokens[i][0] == "literal" for i in denominator) else None
        return whole, numerator, slash, denominator, fixed
    return None


def _render_fraction(tokens: list, parts, value: float) -> str:
    whole_at, numerator_at, slash, denominator_at, fixed = parts
    whole = math.floor(value) if whole_at else 0
    rest = value - whole
    if fixed:
        numerator, denominator = round(rest * fixed), fixed
    else:
        best = Fraction(rest).limit_denominator(10 ** len(denominator_at) - 1)
        numerator, denominator = best.numerator, best.denominator
    if whole_at and numerator == denominator:  # 2.999 in ?/? is 3
        whole, numerator = whole + 1, 0
    places = {kind: [tokens[i][1] for i in at]
              for kind, at in (("whole", whole_at), ("numerator", numerator_at), ("denominator", denominator_at))}
    blank = whole_at and numerator == 0  # a whole number: no fraction, just spaces where it goes (for ?)
    whole_text = _fill_integer(str(whole) if whole else ("0" if blank or value == 0 else ""), places["whole"])
    width = len(numerator_at) + 1 + len(denominator_at)
    blank_text = " " * width if "?" in places["numerator"] + places["denominator"] else ""
    numerator_text = _fill_integer(str(numerator), places["numerator"])
    if fixed:
        denominator_text = str(fixed)
    else:
        written = str(denominator)
        pad = places["denominator"][len(written):] if len(written) < len(places["denominator"]) else []
        denominator_text = written + "".join(" " if place == "?" else "0" if place == "0" else "" for place in pad)
    out = []
    first_part = (whole_at or numerator_at)[0]
    for index, (kind, part) in enumerate(tokens):
        if index in whole_at:
            if index == whole_at[0]:
                out.append(whole_text)
        elif whole_at and whole_at[-1] < index < numerator_at[0]:
            if whole_text.strip() and (blank_text or not blank):  # the space between: with both of them
                out.append(part)
        elif index in numerator_at or index == slash or index in denominator_at:
            if blank:
                if index == numerator_at[0]:
                    out.append(blank_text)
            elif index == numerator_at[0]:
                out.append(numerator_text)
            elif index == slash:
                out.append("/")
            elif index == denominator_at[0]:
                out.append(denominator_text)
        elif kind in ("literal", "percent") and (index < first_part or index > denominator_at[-1]):
            out.append(part)
    return "".join(out)


def _fill_integer(digits: str, places: list[str]) -> str:
    """Digits put in their places from the right: a 0 place with no digit
    shows 0, ? a space, # nothing; digits left over go before."""
    out = []
    remaining = digits
    for place in reversed(places):
        if remaining:
            out.append(remaining[-1])
            remaining = remaining[:-1]
        else:
            out.append("0" if place == "0" else " " if place == "?" else "")
    return remaining + "".join(reversed(out))


def _fill_places(digits: str, places: list[str]) -> list[str]:
    """As _fill_integer, but each place's text apart, so characters can go between them."""
    out = []
    remaining = digits
    for place in reversed(places):
        if remaining:
            out.append(remaining[-1])
            remaining = remaining[:-1]
        else:
            out.append("0" if place == "0" else " " if place == "?" else "")
    out.reverse()
    if out:
        out[0] = remaining + out[0]
    return out


def _fill_fraction(digits: str, places: list[str]) -> str:
    """Decimals in their places from the left: trailing zeros in # places
    are left out, and in ? places shown as spaces."""
    out = list(digits.ljust(len(places), "0"))
    for index in range(len(places) - 1, -1, -1):
        if out[index] != "0" or places[index] == "0":
            break
        out[index] = " " if places[index] == "?" else ""
    return "".join(out)


def _group(text: str) -> str:
    """Thousands separators in a run of digits (after any spaces or sign)."""
    match = re.fullmatch(r"(\s*-?)(\d+)", text)
    if not match:
        return text
    digits, groups = match[2], []
    while len(digits) > 3:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    return match[1] + ",".join([digits, *groups])


def _render_date(section: _Section, value: float) -> str:
    places = max((part for kind, part in section.tokens if kind == "fraction"), default=0)
    seconds = round(value * 86400, places)
    sign = ""
    if "elapsed" in section.kinds and seconds < 0:  # a length of time: -1:30:00
        sign, seconds = "-", -seconds
    try:
        moment = _EPOCH + datetime.timedelta(seconds=seconds)
    except OverflowError:
        return _general(value)
    twelve = "ampm" in section.kinds
    out = []
    for kind, part in section.tokens:
        if kind == "literal":
            out.append(part)
        elif kind == "minutes":
            out.append(f"{moment.minute:0{len(part)}d}")
        elif kind == "fraction":
            fraction = round(seconds - int(seconds), part)
            out.append("." + f"{fraction:.{part}f}"[2:])
        elif kind == "ampm":
            morning = moment.hour < 12
            if part.lower() == "a/p":
                text = "A" if morning else "P"
                out.append(text if part[0].isupper() else text.lower())
            else:
                text = "AM" if morning else "PM"
                out.append(text if part[0].isupper() else text.lower())
        elif kind == "elapsed":
            unit = {"h": 3600, "m": 60, "s": 1}[part[0]]
            out.append(f"{int(seconds // unit):0{len(part)}d}")
        elif kind == "date":
            out.append(_date_part(part, moment, twelve))
    return sign + "".join(out)


def _date_part(part: str, moment: datetime.datetime, twelve: bool) -> str:
    letter, count = part[0], len(part)
    if letter == "y":
        return f"{moment.year % 100:02d}" if count <= 2 else f"{moment.year:04d}"
    if letter == "m":
        if count <= 2:
            return f"{moment.month:0{count}d}"
        name = _MONTHS[moment.month - 1]
        return name[:3] if count == 3 else name[0] if count >= 5 else name
    if letter == "d":
        if count <= 2:
            return f"{moment.day:0{count}d}"
        name = _DAYS[moment.weekday()]
        return name[:3] if count == 3 else name
    if letter == "h":
        hour = (moment.hour % 12 or 12) if twelve else moment.hour
        return f"{hour:0{min(count, 2)}d}"
    if letter == "s":
        return f"{moment.second:0{min(count, 2)}d}"
    return part
