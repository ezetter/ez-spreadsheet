import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyleOptionViewItem

from py_spread.textstyle import CellStyle
from py_spread.window import COLUMN_WIDTH, ROW_HEIGHT, MainWindow


@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    window.view.setFocus()
    yield window
    window.setWindowModified(False)
    window.close()


def size(widget):
    return widget.font().pointSizeF()


def test_view_menu(window):
    menu = [m for m in window.menuBar().actions() if m.text() == "View"][0].menu()
    assert [a.text() for a in menu.actions()] == ["Zoom In", "Zoom Out", "Actual Size", "", "Notebook", "",
                                                  "Appearance"]
    zoom_in_keys = [k.toString() for k in window.zoom_actions["Zoom In"].shortcuts()]
    assert "Ctrl++" in zoom_in_keys and "Ctrl+=" in zoom_in_keys  # Cmd+ with or without Shift
    assert window.zoom_actions["Zoom Out"].shortcuts()[0] == QKeySequence(QKeySequence.ZoomOut)


def test_zoom_in_scales_everything(window):
    base = {w: size(w) for w in window._zoomable_widgets()}
    sigma = size(window.autosum_button)
    window.zoom_in()
    assert window.zoom == 110
    window.zoom_in()
    assert window.zoom == 125
    for widget, points in base.items():
        assert size(widget) == pytest.approx(points * 1.25)
    assert size(window.autosum_button) == pytest.approx(sigma * 1.25)  # the large Σ too
    assert window.view.horizontalHeader().defaultSectionSize() == round(COLUMN_WIDTH * 1.25)
    assert window.view.verticalHeader().defaultSectionSize() == round(ROW_HEIGHT * 1.25)
    assert window.statusBar().currentMessage() == "Zoom 125%"


def test_toolbar_buttons_grow(window):
    before = window.fill_button.sizeHint().height()
    window.set_zoom(200)
    assert window.fill_button.sizeHint().height() > before * 1.5


def test_zoom_out_and_actual_size(window):
    base = size(window.view)
    window.zoom_out()
    window.zoom_out()
    assert window.zoom == 80
    assert size(window.view) == pytest.approx(base * 0.8)
    window.zoom_actions["Actual Size"].trigger()
    assert window.zoom == 100
    assert size(window.view) == pytest.approx(base)
    assert window.view.horizontalHeader().defaultSectionSize() == COLUMN_WIDTH


def test_limits(window):
    for _ in range(20):
        window.zoom_in()
    assert window.zoom == 300 and not window.zoom_actions["Zoom In"].isEnabled()
    for _ in range(20):
        window.zoom_out()
    assert window.zoom == 50 and not window.zoom_actions["Zoom Out"].isEnabled()
    assert window.zoom_actions["Zoom In"].isEnabled()


def test_keyboard_shortcuts(window):
    QTest.keyClick(window.view, Qt.Key_Equal, Qt.ControlModifier)  # Cmd= on macOS
    assert window.zoom == 110
    QTest.keyClick(window.view, Qt.Key_Minus, Qt.ControlModifier)
    assert window.zoom == 100


def test_resized_column_keeps_its_proportion(window):
    header = window.view.horizontalHeader()
    header.resizeSection(2, 250)
    window.set_zoom(200)
    assert header.sectionSize(2) == 500
    assert header.sectionSize(1) == 200
    window.set_zoom(100)
    assert header.sectionSize(2) == 250 and header.sectionSize(1) == 100


def test_bold_cells_scale_and_stay_bold(window):
    window.model.set_cell(0, 0, "x")
    window.model.set_styles({(0, 0): CellStyle(bold=True)}, "Bold")
    window.set_zoom(150)
    option = QStyleOptionViewItem()
    option.font = window.view.font()
    window.view.itemDelegate().initStyleOption(option, window.model.index(0, 0))
    assert option.font.bold()
    assert option.font.pointSizeF() == pytest.approx(window.view.font().pointSizeF())


def test_new_columns_use_zoomed_size(window):
    window.set_zoom(150)
    window.model.ensure_size(10, 60)
    assert window.view.horizontalHeader().sectionSize(59) == round(COLUMN_WIDTH * 1.5)


def test_cell_editor_uses_zoomed_font(window):
    from PySide6.QtWidgets import QLineEdit
    window.set_zoom(200)
    QTest.keyClick(window.view, "a")
    editor = window.view.viewport().findChild(QLineEdit)
    assert editor.font().pointSizeF() == pytest.approx(window.view.font().pointSizeF())
