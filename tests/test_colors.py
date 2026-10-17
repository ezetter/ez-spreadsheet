import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from ezsheet.colors import PALETTE, ColorMenu
from ezsheet.model import SheetModel
from ezsheet.numformat import NumberFormat
from ezsheet.textstyle import PLAIN, CellStyle, from_json, to_json
from ezsheet.window import MainWindow


def test_json():
    style = CellStyle(bold=True, color="#ff0000", fill="#fff2cc")
    assert to_json(style) == {"bold": True, "color": "#ff0000", "fill": "#fff2cc"}
    assert from_json(to_json(style)) == style


@pytest.mark.parametrize("data", [{"color": "red"}, {"fill": "#FFF2CC"}, {"color": "#ff00"}, {"fill": 3}])
def test_bad_colors(data):
    assert from_json(data) is None


def test_model_colors(app):
    model = SheetModel(rows=5, cols=3)
    model.set_cells({(0, 0): "a", (1, 0): "b", (2, 0): "c", (3, 0): "-5"})
    model.set_styles({(0, 0): CellStyle(color="#0000ff"), (1, 0): CellStyle(fill="#000000"),
                      (2, 0): CellStyle(fill="#fff2cc"), (3, 0): CellStyle(color="#0000ff")}, "Colors")
    model.set_formats({(3, 0): NumberFormat("custom", pattern="0;[Red]-0")}, "Custom")
    foreground = [model.data(model.index(r, 0), Qt.ForegroundRole) for r in range(4)]
    assert foreground == [QColor("#0000ff"), QColor("#ffffff"), QColor("#000000"), QColor("#ff0000")]
    # (a dark fill gets white text, a light one black; a custom format's color comes first)
    assert model.data(model.index(2, 0), Qt.BackgroundRole) == QColor("#fff2cc")
    assert model.data(model.index(0, 0), Qt.BackgroundRole) is None


def test_palette_is_google_sheets(app):
    assert len(PALETTE) == 8 and all(len(row) == 10 for row in PALETTE)
    menu = ColorMenu("Reset")
    assert len(menu.swatches) == 80 and menu.reset_button.text() == "Reset"
    chosen = []
    menu.chosen.connect(chosen.append)
    menu.swatches["#4a86e8"].click()
    menu.reset_button.click()
    assert chosen == ["#4a86e8", None]


@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def test_text_and_fill_colors(window):
    model = window.model
    model.set_styles({(0, 1): CellStyle(bold=True)}, "Bold")
    window.view.select_range(0, 0, 0, 1)
    window.color_menus["color"].swatches["#ff0000"].click()
    assert model.cell_style(0, 0) == CellStyle(color="#ff0000")
    assert model.cell_style(0, 1) == CellStyle(bold=True, color="#ff0000")  # bold stays
    assert window.undo_action.text() == "Undo Text Color"
    window.color_menus["fill"].swatches["#fff2cc"].click()
    assert model.cell_style(0, 0) == CellStyle(color="#ff0000", fill="#fff2cc")
    assert window.undo_action.text() == "Undo Fill Color"
    window.color_menus["color"].reset_button.click()
    assert model.cell_style(0, 0) == CellStyle(fill="#fff2cc")
    window.undo_action.trigger()
    assert model.cell_style(0, 0).color == "#ff0000"


def test_custom_colors(window, dialogs):
    model = window.model
    model.set_styles({(0, 0): CellStyle(fill="#d9ead3")}, "Fill")
    window.view.select_range(0, 0, 0, 0)
    dialogs.color_answer = "#123456"
    window.color_menus["fill"].build()  # (as it is when it's shown)
    window.color_menus["fill"].custom_button.click()
    assert dialogs.color_prompts == [("#d9ead3", "Fill Color")] and model.cell_style(0, 0).fill == "#123456"
    window.format_actions["Text Color…"].trigger()
    assert dialogs.color_prompts[-1] == (None, "Text Color") and model.cell_style(0, 0).color == "#123456"
    dialogs.color_answer = None  # Cancel
    window.format_actions["Fill Color…"].trigger()
    assert model.cell_style(0, 0).fill == "#123456"


def test_buttons_show_the_current_cells_colors(window):
    model = window.model
    model.set_styles({(1, 0): CellStyle(color="#ff0000", fill="#00ff00")}, "Colors")
    plain = window.color_buttons["fill"].icon().pixmap(26, 26).toImage()
    window.view.setCurrentIndex(model.index(1, 0))
    image = window.color_buttons["fill"].icon().pixmap(26, 26).toImage()
    assert image != plain
    assert QColor(image.pixel(13, 23)) == QColor("#00ff00")  # the bar
    assert QColor(window.color_buttons["color"].icon().pixmap(26, 26).toImage().pixel(13, 23)) == QColor("#ff0000")
    assert window.color_buttons["color"].toolTip() == "Text color"
    assert window.color_buttons["fill"].menu() is window.color_menus["fill"]


def test_colors_saved_and_opened(window, tmp_path):
    window.model.set_cell(0, 0, "x")
    window.model.set_styles({(0, 0): CellStyle(color="#980000", fill="#c9daf8")}, "Colors")
    path = str(tmp_path / "s.ezs")
    window.save_to(path)
    other = MainWindow()
    other.open_path(path)
    assert other.model.cell_style(0, 0) == CellStyle(color="#980000", fill="#c9daf8")
    other.setWindowModified(False)
    other.close()


def test_default_font_keeps_colors(window):
    window.model.set_styles({(0, 0): CellStyle(font="Georgia", color="#ff0000")}, "Styles")
    window.view.select_range(0, 0, 0, 0)
    window.format_actions["Default Font"].trigger()
    assert window.model.cell_style(0, 0) == CellStyle(color="#ff0000")
