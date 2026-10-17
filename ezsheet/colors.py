"""The text color and fill color buttons' palette, as Google Sheets has it,
and their icons: an A, or a paint bucket, over a bar of the color."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGridLayout, QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget, QWidgetAction

PALETTE = (  # Google Sheets' colors: grays, the bright ones, then lighter and darker shades of them
    ("#000000", "#434343", "#666666", "#999999", "#b7b7b7", "#cccccc", "#d9d9d9", "#efefef", "#f3f3f3", "#ffffff"),
    ("#980000", "#ff0000", "#ff9900", "#ffff00", "#00ff00", "#00ffff", "#4a86e8", "#0000ff", "#9900ff", "#ff00ff"),
    ("#e6b8af", "#f4cccc", "#fce5cd", "#fff2cc", "#d9ead3", "#d0e0e3", "#c9daf8", "#cfe2f3", "#d9d2e9", "#ead1dc"),
    ("#dd7e6b", "#ea9999", "#f9cb9c", "#ffe599", "#b6d7a8", "#a2c4c9", "#a4c2f4", "#9fc5e8", "#b4a7d6", "#d5a6bd"),
    ("#cc4125", "#e06666", "#f6b26b", "#ffd966", "#93c47d", "#76a5af", "#6d9eeb", "#6fa8dc", "#8e7cc3", "#c27ba0"),
    ("#a61c00", "#cc0000", "#e69138", "#f1c232", "#6aa84f", "#45818e", "#3c78d8", "#3d85c6", "#674ea7", "#a64d79"),
    ("#85200c", "#990000", "#b45f06", "#bf9000", "#38761d", "#134f5c", "#1155cc", "#0b5394", "#351c75", "#741b47"),
    ("#5b0f00", "#660000", "#783f04", "#7f6000", "#274e13", "#0c343d", "#1c4587", "#073763", "#20124d", "#4c1130"),
)
SWATCH = 18  # each color's square, in points


class ColorMenu(QMenu):
    """The palette, in a menu: Reset (no color of the cell's own), the
    colors, and Custom… (to choose any). `chosen` gives the color (#rrggbb),
    or None for Reset; `custom` asks for Custom… (The palette's made when
    it's first shown: a window has two of them, and 80 colors each.)"""

    chosen = Signal(object)
    custom = Signal()

    def __init__(self, reset_text: str, parent=None):
        super().__init__(parent)
        self.reset_text = reset_text
        self._swatches = None
        self.aboutToShow.connect(self.build)

    @property
    def swatches(self) -> dict:
        """Each color's button, by color."""
        self.build()
        return self._swatches

    def build(self) -> None:
        if self._swatches is not None:
            return
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        self.reset_button = QPushButton(self.reset_text)
        self.reset_button.setFlat(True)
        self.reset_button.clicked.connect(lambda: self._choose(None))
        layout.addWidget(self.reset_button)
        grid = QGridLayout()
        grid.setSpacing(3)
        self._swatches = {}
        for row, colors in enumerate(PALETTE):
            for col, color in enumerate(colors):
                swatch = QToolButton()
                swatch.setFixedSize(SWATCH, SWATCH)
                swatch.setToolTip(color)
                border = "#bbbbbb" if QColor(color).lightnessF() > 0.9 else color
                swatch.setStyleSheet(f"QToolButton {{ background: {color}; border: 1px solid {border}; "
                                     f"border-radius: 9px; }} QToolButton:hover {{ border: 2px solid #4a86e8; }}")
                swatch.clicked.connect(lambda _checked=False, c=color: self._choose(c))
                grid.addWidget(swatch, row + (1 if row >= 2 else 0), col)  # a gap before the shades
                self._swatches[color] = swatch
        grid.setRowMinimumHeight(2, 4)
        layout.addLayout(grid)
        self.custom_button = QPushButton("Custom…")
        self.custom_button.setFlat(True)
        self.custom_button.clicked.connect(self._ask_custom)
        layout.addWidget(self.custom_button)
        action = QWidgetAction(self)
        action.setDefaultWidget(panel)
        self.addAction(action)

    def _choose(self, color) -> None:
        self.close()
        self.chosen.emit(color)

    def _ask_custom(self) -> None:
        self.close()
        self.custom.emit()


def text_color_icon(color: QColor, bar: QColor | None, ratio: float = 2.0) -> QIcon:
    """An A, in the toolbar's text color `color`, over a bar of the text color."""
    width, height = 26, 26
    pixmap, painter = _canvas(width, height, ratio)
    font = QFont()
    font.setPixelSize(17)
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(QRectF(0, -1, width, 20), Qt.AlignHCenter | Qt.AlignTop, "A")
    _bar(painter, width, height, bar, color)
    painter.end()
    return QIcon(pixmap)


def fill_color_icon(color: QColor, bar: QColor | None, ratio: float = 2.0) -> QIcon:
    """A paint bucket, in the toolbar's text color `color`, over a bar of the fill color."""
    width, height = 26, 26
    pixmap, painter = _canvas(width, height, ratio)
    pen = QPen(color, 1.3)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.save()
    painter.translate(11, 10)
    painter.rotate(-45)  # a bucket tipped to pour, as Google Sheets draws it
    bucket = QPainterPath()
    bucket.addRoundedRect(QRectF(-5, -4, 10, 9), 1.5, 1.5)
    painter.drawPath(bucket)
    painter.drawLine(QPointF(-5, -1), QPointF(5, -1))  # its rim
    handle = QPainterPath(QPointF(-3, -4))
    handle.cubicTo(QPointF(-3, -9), QPointF(3, -9), QPointF(3, -4))
    painter.drawPath(handle)
    painter.restore()
    drop = QPainterPath(QPointF(20, 9))  # paint dripping from it
    drop.cubicTo(QPointF(23, 13), QPointF(22, 16), QPointF(20, 16))
    drop.cubicTo(QPointF(18, 16), QPointF(17, 13), QPointF(20, 9))
    painter.fillPath(drop, color)
    _bar(painter, width, height, bar, color)
    painter.end()
    return QIcon(pixmap)


def _canvas(width: int, height: int, ratio: float):
    pixmap = QPixmap(round(width * ratio), round(height * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    return pixmap, painter


def _bar(painter: QPainter, width: int, height: int, bar: QColor | None, outline: QColor) -> None:
    """The color, as a bar under the glyph; no color, an outline of one."""
    rect = QRectF(3, height - 5, width - 6, 4)
    if bar is None:
        painter.setPen(QPen(outline, 0.8))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)
    else:
        painter.fillRect(rect, bar)
        if bar.lightnessF() > 0.9:  # a white bar, still seen
            painter.setPen(QPen(QColor("#bbbbbb"), 0.6))
            painter.drawRect(rect)


ICON_SIZE = QSize(26, 26)
