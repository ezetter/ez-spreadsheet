"""Text styles: bold, italic, the font (its family and size), and colors:
the text's and the cell's fill."""

import re
from dataclasses import dataclass

ATTRIBUTES = ("bold", "italic")
MIN_SIZE, MAX_SIZE = 1, 400  # font sizes, in points
SIZES = (6, 7, 8, 9, 10, 11, 12, 13, 14, 18, 24, 36, 48, 72)  # the size box's list, as Google Sheets has
_COLOR = re.compile(r"#[0-9a-f]{6}")  # colors are written #rrggbb, in lowercase


@dataclass(frozen=True)
class CellStyle:
    bold: bool = False
    italic: bool = False
    font: str | None = None  # a font family, such as "Georgia"; None is the sheet's own
    size: float | None = None  # in points (at 100% zoom); None is the sheet's own
    color: str | None = None  # the text's color, #rrggbb; None is the sheet's own
    fill: str | None = None  # the cell's background, #rrggbb; None is none


PLAIN = CellStyle()


def to_json(style: CellStyle) -> dict:
    """Only what's set, e.g. {"bold": true, "font": "Georgia", "size": 14}."""
    data = {name: True for name in ATTRIBUTES if getattr(style, name)}
    if style.font is not None:
        data["font"] = style.font
    if style.size is not None:
        data["size"] = int(style.size) if float(style.size).is_integer() else style.size
    for name in ("color", "fill"):
        if getattr(style, name) is not None:
            data[name] = getattr(style, name)
    return data


def is_color(text) -> bool:
    """Whether it's a color as styles write them: #rrggbb."""
    return isinstance(text, str) and bool(_COLOR.fullmatch(text))


def from_json(data) -> CellStyle | None:
    """A style read from a file, or None if it's malformed."""
    if not isinstance(data, dict) or not set(data) <= {*ATTRIBUTES, "font", "size", "color", "fill"}:
        return None
    if not all(isinstance(data[name], bool) for name in ATTRIBUTES if name in data):
        return None
    font, size = data.get("font"), data.get("size")
    if font is not None and (not isinstance(font, str) or not font.strip()):
        return None
    if size is not None and (isinstance(size, bool) or not isinstance(size, (int, float))
                             or not MIN_SIZE <= size <= MAX_SIZE):
        return None
    if any(name in data and not is_color(data[name]) for name in ("color", "fill")):
        return None
    return CellStyle(data.get("bold", False), data.get("italic", False), font,
                     float(size) if size is not None else None, data.get("color"), data.get("fill"))
