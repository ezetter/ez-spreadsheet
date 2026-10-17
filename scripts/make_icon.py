"""Draw EZ Sheet's icon, a spreadsheet's grid, as py_spread/resources/ezsheet.png
(1024 pixels), and, on a Mac, ezsheet.icns for the app bundle (see make_app.py).

Run it again after changing the drawing:  .venv/bin/python scripts/make_icon.py
"""

import os
import shutil
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

HERE = os.path.dirname(os.path.abspath(__file__))
RESOURCES = os.path.join(HERE, os.pardir, "py_spread", "resources")
GREEN, DARK_GREEN, LIGHT_GREEN = QColor("#1e9e5a"), QColor("#137a43"), QColor("#d7f0e1")


def draw(size: int = 1024) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 1024  # (drawn at 1024, scaled)

    # A rounded square, as Mac app icons are, in green.
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(100 * s, 100 * s, 824 * s, 824 * s), 185 * s, 185 * s)
    shade = QLinearGradient(0, 100 * s, 0, 924 * s)
    shade.setColorAt(0, GREEN.lighter(112))
    shade.setColorAt(1, DARK_GREEN)
    p.fillPath(tile, shade)

    # A sheet on it: white, its corner folded.
    left, top, right, bottom, fold = 230 * s, 200 * s, 794 * s, 824 * s, 110 * s
    sheet = QPainterPath()
    sheet.moveTo(left, top)
    sheet.lineTo(right - fold, top)
    sheet.lineTo(right, top + fold)
    sheet.lineTo(right, bottom)
    sheet.lineTo(left, bottom)
    sheet.closeSubpath()
    p.fillPath(sheet.translated(0, 12 * s), QColor(0, 0, 0, 60))  # its shadow
    p.fillPath(sheet, QColor("#ffffff"))
    corner = QPainterPath()
    corner.moveTo(right - fold, top)
    corner.lineTo(right - fold, top + fold)
    corner.lineTo(right, top + fold)
    corner.closeSubpath()
    p.fillPath(corner, QColor("#c9d6ce"))

    # The grid: a header row and column, in green, and cells, some filled.
    grid_left, grid_top, grid_right, grid_bottom = left + 50 * s, top + 150 * s, right - 50 * s, bottom - 55 * s
    cols, rows = 4, 6
    header_w, header_h = 70 * s, 70 * s
    cell_w = (grid_right - grid_left - header_w) / (cols - 1)
    cell_h = (grid_bottom - grid_top - header_h) / (rows - 1)
    p.fillRect(QRectF(grid_left, grid_top, grid_right - grid_left, header_h), GREEN)
    p.fillRect(QRectF(grid_left, grid_top, header_w, grid_bottom - grid_top), GREEN)
    p.fillRect(QRectF(grid_left, grid_top, header_w, header_h), DARK_GREEN)
    for row, col in ((1, 1), (2, 2), (3, 1), (4, 3), (2, 3)):
        p.fillRect(QRectF(grid_left + header_w + (col - 1) * cell_w, grid_top + header_h + (row - 1) * cell_h,
                          cell_w, cell_h), LIGHT_GREEN)
    pen = QPen(QColor("#9fb5a7"), 6 * s)
    p.setPen(pen)
    for col in range(cols):
        x = grid_left + header_w + col * cell_w if col else grid_left + header_w
        p.drawLine(int(x), int(grid_top), int(x), int(grid_bottom))
    for row in range(rows):
        y = grid_top + header_h + row * cell_h if row else grid_top + header_h
        p.drawLine(int(grid_left), int(y), int(grid_right), int(y))
    p.setPen(QPen(DARK_GREEN, 8 * s))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(grid_left, grid_top, grid_right - grid_left, grid_bottom - grid_top))
    # The selected cell, outlined as a spreadsheet does.
    p.setPen(QPen(QColor("#1a73e8"), 14 * s))
    p.drawRect(QRectF(grid_left + header_w + cell_w, grid_top + header_h + 2 * cell_h, cell_w, cell_h))
    p.end()
    return image


def main() -> int:
    QGuiApplication(sys.argv)
    os.makedirs(RESOURCES, exist_ok=True)
    png = os.path.join(RESOURCES, "ezsheet.png")
    draw().save(png)
    print("wrote", os.path.relpath(png))
    if sys.platform == "darwin" and shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as folder:
            iconset = os.path.join(folder, "ezsheet.iconset")
            os.makedirs(iconset)
            for points in (16, 32, 128, 256, 512):
                for scale in (1, 2):
                    name = f"icon_{points}x{points}{'@2x' if scale == 2 else ''}.png"
                    draw(points * scale).save(os.path.join(iconset, name))
            icns = os.path.join(RESOURCES, "ezsheet.icns")
            subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns], check=True)
            print("wrote", os.path.relpath(icns))
    return 0


if __name__ == "__main__":
    sys.exit(main())
