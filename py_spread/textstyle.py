"""Text styles: bold and italic."""

from dataclasses import dataclass

ATTRIBUTES = ("bold", "italic")


@dataclass(frozen=True)
class CellStyle:
    bold: bool = False
    italic: bool = False


PLAIN = CellStyle()


def to_json(style: CellStyle) -> dict:
    """Only the attributes that are on, e.g. {"bold": true}."""
    return {name: True for name in ATTRIBUTES if getattr(style, name)}


def from_json(data) -> CellStyle | None:
    """A style read from a file, or None if it's malformed."""
    if not isinstance(data, dict) or not set(data) <= set(ATTRIBUTES):
        return None
    if not all(isinstance(value, bool) for value in data.values()):
        return None
    return CellStyle(**data)
