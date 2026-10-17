"""Borders and merged cells, as Google Sheets has them: which sides of which
cells a border choice sets, what merging does, and the menus' icons."""

import dataclasses

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from .textstyle import Border

BORDER_KINDS = (  # the borders menu's choices, in Google Sheets' order: (key, name)
    ("all", "All borders"), ("inner", "Inner borders"), ("horizontal", "Horizontal borders"),
    ("vertical", "Vertical borders"), ("outer", "Outer borders"), ("left", "Left border"), ("top", "Top border"),
    ("right", "Right border"), ("bottom", "Bottom border"), ("clear", "Clear borders"),
)
MERGE_KINDS = (("all", "Merge all"), ("vertically", "Merge vertically"), ("horizontally", "Merge horizontally"),
               ("unmerge", "Unmerge"))
_OPPOSITE = {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}
_STEP = {"top": (-1, 0), "bottom": (1, 0), "left": (0, -1), "right": (0, 1)}


def _edges(block, kind: str) -> list[tuple[int, int, str]]:
    """The edges a choice draws in a block, each as one cell's side: inside
    the block, the upper or left cell's (bottom or right); around it, the
    block's own cells'."""
    top, left, bottom, right = block
    horizontal = [(r, c, "bottom") for r in range(top, bottom) for c in range(left, right + 1)]
    vertical = [(r, c, "right") for r in range(top, bottom + 1) for c in range(left, right)]
    around = {
        "top": [(top, c, "top") for c in range(left, right + 1)],
        "bottom": [(bottom, c, "bottom") for c in range(left, right + 1)],
        "left": [(r, left, "left") for r in range(top, bottom + 1)],
        "right": [(r, right, "right") for r in range(top, bottom + 1)],
    }
    outer = around["top"] + around["bottom"] + around["left"] + around["right"]
    return {
        "all": horizontal + vertical + outer, "inner": horizontal + vertical, "horizontal": horizontal,
        "vertical": vertical, "outer": outer, "clear": horizontal + vertical + outer, **around,
    }[kind]


def border_styles(style_of, block, kind: str, border: Border, rows: int, cols: int) -> dict:
    """The cells' new styles for a border choice in a block (top, left,
    bottom, right): `style_of(row, col)` gives a cell's style now; `border`
    is the line to draw (Clear borders takes them away). Each edge drawn is
    one cell's side; the cell on its other side has that side cleared, so an
    edge is never two lines. Cells outside the sheet are left alone."""
    sides: dict[tuple[int, int], dict] = {}

    def put(row, col, side, value):
        if 0 <= row < rows and 0 <= col < cols:
            sides.setdefault((row, col), {})[side] = value

    value = None if kind == "clear" else border
    for row, col, side in _edges(block, kind):
        put(row, col, side, value)
        d_row, d_col = _STEP[side]
        put(row + d_row, col + d_col, _OPPOSITE[side], None)
    return {key: dataclasses.replace(style_of(*key), **changes) for key, changes in sides.items()}


def _overlaps(a, b) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def merged(merges, block, how: str) -> set:
    """The sheet's merged blocks once a block's merged (how: all, vertically
    (each column of it), horizontally (each row)) or unmerged: merges it
    overlaps are undone first."""
    top, left, bottom, right = block
    kept = {merge for merge in merges if not _overlaps(merge, block)}
    if how == "all":
        new = [block]
    elif how == "vertically":
        new = [(top, c, bottom, c) for c in range(left, right + 1)]
    elif how == "horizontally":
        new = [(r, left, r, right) for r in range(top, bottom + 1)]
    else:
        new = []
    return kept | {b for b in new if (b[0], b[1]) != (b[2], b[3])}


def covered(merges) -> set:
    """The cells merging hides: all but each block's top-left one."""
    return {(r, c) for top, left, bottom, right in merges for r in range(top, bottom + 1)
            for c in range(left, right + 1) if (r, c) != (top, left)}


# --- Icons ---

def _canvas(size: int, ratio: float):
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, False)
    return pixmap, painter


def border_icon(kind: str, ink: QColor, ratio: float = 2.0, size: int = 22) -> QIcon:
    """A 2-by-2 grid, the borders the choice draws solid and the rest dotted, as Google Sheets draws them."""
    pixmap, painter = _canvas(size, ratio)
    lo, hi, mid = 3.5, size - 3.5, size / 2
    lines = {"top": (lo, lo, hi, lo), "bottom": (lo, hi, hi, hi), "left": (lo, lo, lo, hi),
             "right": (hi, lo, hi, hi), "horizontal": (lo, mid, hi, mid), "vertical": (mid, lo, mid, hi)}
    drawn = {
        "all": set(lines), "inner": {"horizontal", "vertical"}, "horizontal": {"horizontal"},
        "vertical": {"vertical"}, "outer": {"top", "bottom", "left", "right"}, "clear": set(),
    }.get(kind, {kind})
    faint = QColor(ink)
    faint.setAlphaF(0.4)
    dotted = QPen(faint, 1, Qt.DotLine)
    solid = QPen(ink, 1.6)
    for name, (x0, y0, x1, y1) in lines.items():
        painter.setPen(solid if name in drawn else dotted)
        painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    painter.end()
    return QIcon(pixmap)


def border_style_icon(style: str, ink: QColor, ratio: float = 2.0) -> QIcon:
    """A line in a border style."""
    width, height = 40, 12
    pixmap = QPixmap(round(width * ratio), round(height * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    pen = QPen(ink, {"medium": 2, "thick": 3}.get(style, 1))
    pen.setStyle({"dashed": Qt.DashLine, "dotted": Qt.DotLine}.get(style, Qt.SolidLine))
    painter.setPen(pen)
    if style == "double":
        painter.drawLine(QPointF(2, 4.5), QPointF(width - 2, 4.5))
        painter.drawLine(QPointF(2, 7.5), QPointF(width - 2, 7.5))
    else:
        painter.drawLine(QPointF(2, height / 2), QPointF(width - 2, height / 2))
    painter.end()
    return QIcon(pixmap)


def merge_icon(ink: QColor, ratio: float = 2.0, size: int = 22) -> QIcon:
    """Google Sheets' merge icon: a box, with arrows pointing in to its middle from each side."""
    pixmap, painter = _canvas(size, ratio)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(ink, 1.4))
    painter.drawRect(QRectF(2.5, 4.5, size - 5, size - 9))
    mid = size / 2
    for start, end, head in ((5.5, mid - 1.5, -2.5), (size - 5.5, mid + 1.5, 2.5)):
        painter.drawLine(QPointF(start, mid), QPointF(end, mid))
        painter.drawLine(QPointF(end, mid), QPointF(end + head, mid - 2.5))
        painter.drawLine(QPointF(end, mid), QPointF(end + head, mid + 2.5))
    painter.drawLine(QPointF(mid, 6.5), QPointF(mid, size - 6.5))  # where they meet
    painter.end()
    return QIcon(pixmap)
