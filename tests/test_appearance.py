import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QStyle

from py_spread import appearance
from py_spread.appearance import GridStyle, blend, error_color, is_dark
from py_spread.window import MainWindow


def palette(window, base, text):
    p = QPalette()
    p.setColor(QPalette.Window, QColor(window))
    p.setColor(QPalette.Base, QColor(base))
    p.setColor(QPalette.Text, QColor(text))
    return p


DARK = ("#323232", "#1e1e1e", "#ffffff")
LIGHT = ("#ececec", "#ffffff", "#000000")


@pytest.fixture
def window(app):
    window = MainWindow()
    yield window
    window.set_appearance("system")
    window.setWindowModified(False)
    window.close()


def test_appearance_menu(window):
    view_menu = [m for m in window.menuBar().actions() if m.text() == "View"][0].menu()
    submenu = [a for a in view_menu.actions() if a.text() == "Appearance"][0].menu()
    assert [a.text() for a in submenu.actions()] == ["Match System", "Light", "Dark"]
    assert window.appearance_actions["system"].isChecked()  # the default


def test_choosing_an_appearance(window, monkeypatch, preferences):
    schemes = []
    monkeypatch.setattr(appearance.QGuiApplication, "styleHints",
                        lambda: type("Hints", (), {"setColorScheme": lambda self, s: schemes.append(s)})())
    window.appearance_actions["dark"].trigger()
    assert schemes == [Qt.ColorScheme.Dark]
    assert window.appearance_actions["dark"].isChecked()
    assert QSettings(preferences, QSettings.IniFormat).value("appearance") == "dark"
    window.appearance_actions["system"].trigger()
    assert schemes[-1] == Qt.ColorScheme.Unknown  # follow the Mac again


def test_choice_is_remembered(app, monkeypatch, preferences):
    QSettings(preferences, QSettings.IniFormat).setValue("appearance", "light")
    calls = []
    monkeypatch.setattr(appearance, "apply_appearance", lambda key, save=True: calls.append((key, save)))
    monkeypatch.setattr("py_spread.window.apply_appearance", appearance.apply_appearance)
    window = MainWindow()
    assert calls == [("light", False)]
    assert window.appearance_actions["light"].isChecked()
    window.setWindowModified(False)


def test_unknown_saved_value_means_system(app, preferences):
    QSettings(preferences, QSettings.IniFormat).setValue("appearance", "purple")
    assert appearance.saved_appearance() == "system"


def test_is_dark_and_error_color():
    assert is_dark(palette(*DARK)) and not is_dark(palette(*LIGHT))
    assert error_color(palette(*DARK)) != error_color(palette(*LIGHT))


def test_grid_lines_are_soft_in_both(app):
    light = blend(palette(*LIGHT), 0.18)
    dark = blend(palette(*DARK), 0.18)
    assert 200 < light.lightness() < 225  # a soft grey on white
    assert 50 < dark.lightness() < 90     # dim on near-black, not white


def test_grid_style_reports_line_color(app):
    from PySide6.QtWidgets import QTableView
    view = QTableView()
    view.setPalette(palette(*DARK))
    value = GridStyle().styleHint(QStyle.SH_Table_GridLineColor, None, view)
    assert QColor.fromRgba(value & 0xFFFFFFFF).name() == blend(palette(*DARK), 0.18).name()


def test_sheet_uses_grid_style(window):
    assert isinstance(window.view.style(), GridStyle)


def test_chart_follows_appearance(window):
    from PySide6.QtWidgets import QApplication
    from py_spread.chart import ChartWindow

    window.model.set_cells({(0, 0): "1", (0, 1): "2", (1, 0): "2", (1, 1): "4"})
    chart = ChartWindow(window.model, {(r, c) for r in range(2) for c in range(2)}, parent=window)
    light_line = chart.axes.get_lines()[0].get_color()
    chart.setPalette(palette(*DARK))
    QApplication.processEvents()
    assert chart.figure.get_facecolor()[:3] == pytest.approx(QColor(DARK[0]).getRgbF()[:3])
    assert chart.axes.get_facecolor()[:3] == pytest.approx(QColor(DARK[1]).getRgbF()[:3])
    assert chart.axes.get_lines()[0].get_color() != light_line  # the dark style's colors
    chart.close()


def test_fill_dialog_error_color(app):
    from py_spread.fill_dialogs import RandomDialog
    dialog = RandomDialog()
    dialog.setPalette(palette(*DARK))
    dialog.lower.setText("5")
    dialog.upper.setText("1")
    assert error_color(palette(*DARK)) in dialog.note.styleSheet()
