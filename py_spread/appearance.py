"""Light and dark appearance.

The app follows the Mac's appearance, or the user can pick light or dark in
View > Appearance; the choice is remembered between launches. Qt switches
the native widgets itself (Qt 6.8 and later); this module also supplies the
colors Qt doesn't pick for us, such as the grid lines.
"""

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QProxyStyle, QStyle

APPEARANCES = {  # key -> (menu label, Qt color scheme)
    "system": ("Match System", Qt.ColorScheme.Unknown),  # Unknown: follow the Mac
    "light": ("Light", Qt.ColorScheme.Light),
    "dark": ("Dark", Qt.ColorScheme.Dark),
}
SETTINGS_KEY = "appearance"


def settings() -> QSettings:
    """Where app preferences are kept (not per sheet)."""
    return QSettings("Py-Spread", "Py-Spread")


def saved_appearance() -> str:
    value = settings().value(SETTINGS_KEY, "system")
    return value if value in APPEARANCES else "system"


def apply_appearance(key: str, save: bool = True) -> None:
    QGuiApplication.styleHints().setColorScheme(APPEARANCES[key][1])
    if save:
        settings().setValue(SETTINGS_KEY, key)


def is_dark(palette: QPalette) -> bool:
    return palette.color(QPalette.Window).lightness() < 128


def blend(palette: QPalette, amount: float) -> QColor:
    """The cells' background moved `amount` of the way toward their text color."""
    base, text = palette.color(QPalette.Base), palette.color(QPalette.Text)
    return QColor.fromRgbF(*(b + (t - b) * amount for b, t in zip(base.getRgbF()[:3], text.getRgbF()[:3])))


def error_color(palette: QPalette) -> str:
    """A red that reads well on the current background."""
    return "#ff6b6b" if is_dark(palette) else "#c0392b"


class GridStyle(QProxyStyle):
    """The app's style, with grid lines a soft blend of the cells' background
    and text colors. (The Mac style draws them white in dark mode.)"""

    def styleHint(self, hint, option=None, widget=None, return_data=None):
        if hint == QStyle.SH_Table_GridLineColor:
            palette = widget.palette() if widget is not None else QGuiApplication.palette()
            rgba = blend(palette, 0.18).rgba()
            return rgba - (1 << 32) if rgba >= 1 << 31 else rgba  # as a signed int
        return super().styleHint(hint, option, widget, return_data)
