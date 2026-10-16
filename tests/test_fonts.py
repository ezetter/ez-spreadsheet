import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QStyleOptionViewItem

from py_spread.model import SheetModel
from py_spread.storage import SheetData, load_sheet, save_sheet
from py_spread.textstyle import PLAIN, CellStyle, from_json, to_json
from py_spread.window import MainWindow


# --- Styles with fonts ---

def test_json():
    style = CellStyle(True, False, "Georgia", 14.0)
    assert to_json(style) == {"bold": True, "font": "Georgia", "size": 14}
    assert to_json(CellStyle(size=10.5)) == {"size": 10.5}
    assert from_json(to_json(style)) == style and from_json({"size": 10.5}) == CellStyle(size=10.5)


@pytest.mark.parametrize("data", [
    {"font": 3}, {"font": " "}, {"size": "12"}, {"size": 0}, {"size": 401}, {"size": True}, {"color": "red"},
])
def test_bad_fonts(data):
    assert from_json(data) is None


def test_saved_with_the_sheet(tmp_path):
    path = str(tmp_path / "s.ezs")
    sheet = SheetData(rows=10, cols=5, cells={(0, 0): "x"}, styles={(0, 0): CellStyle(font="Georgia", size=18.0)})
    save_sheet(path, sheet)
    assert load_sheet(path).styles == {(0, 0): CellStyle(font="Georgia", size=18.0)}


def test_model_font_and_row_sizes(app):
    model = SheetModel(rows=5, cols=3)
    model.set_styles({(0, 0): CellStyle(font="Georgia"), (1, 0): CellStyle(size=18.0), (1, 2): CellStyle(size=24.0),
                      (2, 1): CellStyle(bold=True)}, "Fonts")
    font = model.data(model.index(0, 0), Qt.FontRole)
    assert font.family() == "Georgia"
    assert model.row_font_sizes() == {1: 24.0}


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def shown_font(window, row, col) -> QFont:
    option = QStyleOptionViewItem()
    window.view.cell_delegate.initStyleOption(option, window.model.index(row, col))
    return QFont(option.font)


def test_choosing_a_font(window):
    model = window.model
    model.set_cells({(0, 0): "a", (0, 1): "b"})
    model.set_styles({(0, 1): CellStyle(bold=True)}, "Bold")
    window.view.select_range(0, 0, 0, 1)
    box = window.font_box
    assert box.itemText(0) == "Default" and box.findData("Georgia") > 1
    assert box.itemData(box.findData("Georgia"), Qt.FontRole).family() == "Georgia"  # shown in itself
    box.setCurrentIndex(box.findData("Georgia"))
    box.activated.emit(box.currentIndex())
    assert model.cell_style(0, 0) == CellStyle(font="Georgia")
    assert model.cell_style(0, 1) == CellStyle(bold=True, font="Georgia")  # bold stays
    assert window.undo_action.text() == "Undo Font"
    box.setCurrentIndex(0)  # Default: the sheet's own font, none of the cell's own
    box.activated.emit(0)
    assert model.cell_style(0, 0) == PLAIN


def test_choosing_a_size(window):
    model = window.model
    window.view.select_range(0, 0, 1, 0)
    window.font_size_box.setCurrentText("18")
    window.font_size_box.textActivated.emit("18")
    assert model.cell_style(0, 0).size == 18.0 and model.cell_style(1, 0).size == 18.0
    assert window.undo_action.text() == "Undo Font Size"
    assert shown_font(window, 0, 0).pointSizeF() == 18.0
    window.set_zoom(150)
    assert shown_font(window, 0, 0).pointSizeF() == 27.0  # zoomed with the grid
    window.font_size_box.setCurrentText("big")
    window.font_size_box.textActivated.emit("big")
    assert "from 1 to 400" in window.statusBar().currentMessage() and model.cell_style(0, 0).size == 18.0
    assert window.font_size_box.currentText() == "18"  # back to the cell's


def test_bigger_and_smaller(window):
    model = window.model
    window.view.setCurrentIndex(model.index(0, 0))
    default = window.default_font_size
    QTest.mouseClick(window.font_size_buttons["bigger"], Qt.LeftButton)
    assert model.cell_style(0, 0).size == round(default) + 1
    window.format_actions["Increase Font Size"].trigger()
    window.format_actions["Decrease Font Size"].trigger()
    QTest.mouseClick(window.font_size_buttons["smaller"], Qt.LeftButton)
    assert model.cell_style(0, 0).size in (None, round(default))  # (the sheet's own, if it's whole)
    assert window.format_actions["Increase Font Size"].shortcut() == QKeySequence("Ctrl+Shift+.")
    assert window.format_actions["Decrease Font Size"].shortcut() == QKeySequence("Ctrl+Shift+,")


def test_default_font(window):
    model = window.model
    model.set_styles({(0, 0): CellStyle(italic=True, font="Georgia", size=20.0)}, "Fonts")
    window.view.select_range(0, 0, 0, 0)
    window.format_actions["Default Font"].trigger()
    assert model.cell_style(0, 0) == CellStyle(italic=True)


def test_toolbar_shows_the_current_cells_font(window):
    model = window.model
    model.set_styles({(1, 0): CellStyle(font="Georgia", size=16.0)}, "Fonts")
    window.view.setCurrentIndex(model.index(1, 0))
    assert window.font_box.currentText() == "Georgia" and window.font_size_box.currentText() == "16"
    window.view.setCurrentIndex(model.index(0, 0))
    assert window.font_box.currentText() == "Default"
    model.set_styles({(2, 0): CellStyle(font="No Such Font")}, "Fonts")  # from another Mac
    window.view.setCurrentIndex(model.index(2, 0))
    assert window.font_box.currentText() == "No Such Font"


def test_rows_fit_their_fonts(window):
    model = window.model
    header = window.view.verticalHeader()
    default = header.defaultSectionSize()
    big = window.default_font_size * 2
    model.set_styles({(2, 1): CellStyle(size=big)}, "Font Size")
    assert header.sectionSize(2) == default * 2 and header.sectionSize(1) == default  # grown to fit
    model.set_styles({(2, 1): CellStyle(size=window.default_font_size / 2)}, "Font Size")
    assert header.sectionSize(2) == default  # and back: (not smaller than the default)
    window.undo_action.trigger()
    assert header.sectionSize(2) == default * 2
    header.resizeSection(2, 100)  # resized by hand: left as it is
    model.set_styles({(2, 1): None}, "Plain")
    assert header.sectionSize(2) == 100
    window.set_zoom(200)
    model.set_styles({(4, 0): CellStyle(size=big)}, "Font Size")
    assert header.sectionSize(4) == header.defaultSectionSize() * 2


def test_editing_uses_the_cells_font(window):
    model = window.model
    model.set_styles({(0, 0): CellStyle(font="Georgia", size=20.0)}, "Fonts")
    window.view.setCurrentIndex(model.index(0, 0))
    window.view.edit(model.index(0, 0))
    [editor] = [e for e in window.view.findChildren(QLineEdit) if e.isVisible()]
    assert editor.font().family() == "Georgia" and editor.font().pointSizeF() == 20.0


def test_fonts_saved_and_opened(window, tmp_path):
    window.model.set_cell(0, 0, "Title")
    window.model.set_styles({(0, 0): CellStyle(bold=True, font="Georgia", size=24.0)}, "Fonts")
    path = str(tmp_path / "s.ezs")
    window.save_to(path)
    other = MainWindow()
    other.open_path(path)
    assert other.model.cell_style(0, 0) == CellStyle(bold=True, font="Georgia", size=24.0)
    header = other.view.verticalHeader()
    assert header.sectionSize(0) > header.defaultSectionSize()  # fitted when it's opened
    other.setWindowModified(False)
    other.close()


def test_copy_and_paste_bring_fonts(window):
    model = window.model
    model.set_cell(0, 0, "x")
    model.set_styles({(0, 0): CellStyle(font="Georgia", size=18.0)}, "Fonts")
    window.view.select_range(0, 0, 0, 0)
    window.clipboard.copy()
    window.view.select_range(3, 3, 3, 3)
    window.clipboard.paste()
    assert model.cell_style(3, 3) == CellStyle(font="Georgia", size=18.0)


def test_size_box_is_as_wide_as_its_digits(window):
    box = window.font_size_box
    digits = box.fontMetrics().horizontalAdvance("00")
    assert digits < box.sizeHint().width() < digits + 45  # two digits and the arrow, not a combo box's usual
    width = box.sizeHint().width()
    window.set_zoom(200)
    assert box.sizeHint().width() > width  # zoomed with the toolbar
