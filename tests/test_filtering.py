import json

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from ezsheet.filter_menu import BLANKS, FilterMenu
from ezsheet.filtering import ColumnFilter, SheetFilter, from_json, to_json
from ezsheet.model import SheetModel
from ezsheet.storage import SheetData, SheetFileError, load_sheet, save_sheet
from ezsheet.window import CREATE_FILTER, REMOVE_FILTER, MainWindow


# --- What a column shows ---

@pytest.mark.parametrize("condition, wanted, shown", [
    ("none", "", ["East", "", "12", "3.5", "eastern"]),
    ("empty", "", [""]),
    ("not empty", "", ["East", "12", "3.5", "eastern"]),
    ("contains", "EAST", ["East", "eastern"]),  # ignoring case
    ("not contains", "east", ["", "12", "3.5"]),
    ("starts", "ea", ["East", "eastern"]),
    ("ends", "rn", ["eastern"]),
    ("exactly", "East", ["East"]),  # minding case
    ("greater", "5", ["12"]),  # numbers only
    ("greater or equal", "3.5", ["12", "3.5"]),
    ("less", "12", ["3.5"]),
    ("less or equal", "12", ["12", "3.5"]),
    ("equal", "12.0", ["12"]),  # as numbers
    ("equal", "east", ["East"]),  # as text
    ("not equal", "12", ["East", "", "3.5", "eastern"]),
])
def test_conditions(condition, wanted, shown):
    cells = [("East", "East"), ("", None), ("12", 12.0), ("3.5", 3.5), ("eastern", "eastern")]
    column_filter = ColumnFilter(condition=condition, value=wanted)
    assert [text for text, value in cells if column_filter.shows(text, value)] == shown


def test_hidden_values_and_blanks():
    column_filter = ColumnFilter(frozenset({"West", ""}))
    assert column_filter.active and not ColumnFilter().active
    assert [column_filter.shows(text, text) for text in ("East", "West", "")] == [True, False, False]
    assert not ColumnFilter(frozenset({"East"}), "contains", "a").shows("East", "East")  # both must pass


def test_sheet_filter_columns_and_rows():
    sheet_filter = SheetFilter(0, 0, 2).with_column(1, ColumnFilter(frozenset({"b"})))
    assert sheet_filter.column(1).hidden == {"b"} and not sheet_filter.column(0).active
    assert sheet_filter.with_column(1, ColumnFilter()).columns == ()  # one doing nothing is dropped
    rows = {1: "a", 2: "b", 3: "c", 4: "b"}
    assert sheet_filter.hidden_rows(4, lambda row, _col: rows[row], lambda row, _col: rows[row]) == {2, 4}


def test_moved_with_its_cells():
    sheet_filter = SheetFilter(2, 1, 3, ((2, ColumnFilter(frozenset({"x"}))), (3, ColumnFilter(frozenset({"y"})))))
    down_and_right = lambda row, col: (row + 1, col + 1)
    assert sheet_filter.moved(down_and_right) == SheetFilter(3, 2, 4, ((3, sheet_filter.column(2)),
                                                                       (4, sheet_filter.column(3))))
    lose_c = lambda row, col: None if col == 2 else (row, col - (col > 2))  # column C deleted
    assert sheet_filter.moved(lose_c) == SheetFilter(2, 1, 2, ((2, sheet_filter.column(3)),))
    lose_d = lambda row, col: None if col == 3 else (row, col)  # its last column: it shrinks
    assert sheet_filter.moved(lose_d) == SheetFilter(2, 1, 2, ((2, sheet_filter.column(2)),))
    assert sheet_filter.moved(lambda row, col: None if 1 <= col <= 3 else (row, col)) is None  # all of them
    assert sheet_filter.moved(lambda row, col: None if row == 2 else (row, col)) is None  # its header's row


def test_json_round_trip():
    sheet_filter = (SheetFilter(0, 0, 3).with_column(1, ColumnFilter(frozenset({"West", ""})))
                    .with_column(3, ColumnFilter(condition="greater", value="500"))
                    .with_column(2, ColumnFilter(condition="empty")))
    data = to_json(sheet_filter)
    assert data == {"header": "A1:D1", "columns": {"B": {"hidden": ["", "West"]}, "C": {"condition": "empty"},
                                                   "D": {"condition": "greater", "value": "500"}}}
    assert from_json(data, parse) == sheet_filter
    assert to_json(SheetFilter(4, 2, 2)) == {"header": "C5:C5"}


def parse(name):
    letters = name.rstrip("0123456789")
    if not letters or letters == name:
        raise ValueError(name)
    col = 0
    for letter in letters:
        col = col * 26 + ord(letter) - ord("A") + 1
    return int(name[len(letters):]) - 1, col - 1


@pytest.mark.parametrize("data", [
    None, {}, {"header": "A1"}, {"header": "A1:C2"}, {"header": "C1:A1"}, {"header": "A1:1"},
    {"header": "A1:C1", "columns": []}, {"header": "A1:C1", "columns": {"D": {}}},
    {"header": "A1:C1", "columns": {"B": {"condition": "bigger"}}},
    {"header": "A1:C1", "columns": {"B": {"hidden": "x"}}},
    {"header": "A1:C1", "columns": {"B": {"condition": "greater", "value": 5}}},
    {"header": "A1:C1", "columns": {"B1": {}}},
])
def test_bad_json(data):
    assert from_json(data, parse) is None


# --- In the model ---

@pytest.fixture
def model(app):
    model = SheetModel(rows=20, cols=6)
    model.set_cells({(0, 0): "Region", (0, 1): "Sales", (1, 0): "East", (1, 1): "1200", (2, 0): "West",
                     (2, 1): "900", (3, 0): "East", (3, 1): "1500", (4, 0): "", (4, 1): "300"})
    return model


def test_filter_hides_rows_and_undoes(model):
    changes = []
    model.filter_changed.connect(lambda: changes.append(model.sheet_filter()))
    model.set_filter(SheetFilter(0, 0, 1), "Create Filter")
    assert model.filter_rows() == (1, 4) and model.hidden_rows() == set()
    model.set_filter(model.sheet_filter().with_column(0, ColumnFilter(frozenset({"East"}))), "Filter")
    assert model.hidden_rows() == {1, 3}
    model.set_filter(model.sheet_filter().with_column(1, ColumnFilter(condition="greater", value="500")), "Filter")
    assert model.hidden_rows() == {1, 3, 4}
    model.set_cell(4, 1, "800")  # data changes: it shows again
    assert model.hidden_rows() == {1, 3}
    model.undo_stack.undo()
    model.undo_stack.undo()
    assert model.hidden_rows() == {1, 3} and model.undo_stack.undoText() == "Filter"
    model.undo_stack.undo()
    model.undo_stack.undo()
    assert model.sheet_filter() is None and model.hidden_rows() == set()
    model.undo_stack.redo()
    assert model.sheet_filter() == SheetFilter(0, 0, 1) and len(changes) == 7


def test_rows_below_the_data(model):
    model.set_filter(SheetFilter(0, 0, 1, ((0, ColumnFilter(condition="not empty")),)), "Filter")
    assert model.filter_rows() == (1, 4) and model.hidden_rows() == {4}  # not the empty rows past the data


def test_filter_moves_with_inserts_and_deletes(model):
    model.set_filter(SheetFilter(0, 0, 1, ((1, ColumnFilter(frozenset({"900"}))),)), "Filter")
    model.insert_rows(0)
    model.insert_columns(0)
    assert model.sheet_filter() == SheetFilter(1, 1, 2, ((2, ColumnFilter(frozenset({"900"}))),))
    assert model.hidden_rows() == {3}
    model.delete_columns(2)  # the filtered one, its last
    assert model.sheet_filter() == SheetFilter(1, 1, 1) and model.hidden_rows() == set()
    model.delete_rows(1)  # its header
    assert model.sheet_filter() is None
    model.undo_stack.undo()
    assert model.sheet_filter() == SheetFilter(1, 1, 1)


def test_saved_and_opened(model, tmp_path):
    path = str(tmp_path / "f.ezs")
    sheet_filter = SheetFilter(0, 0, 1, ((0, ColumnFilter(frozenset({"West"}))),))
    save_sheet(path, SheetData(rows=10, cols=5, filter=sheet_filter))
    assert json.loads(open(path).read())["filter"] == {"header": "A1:B1", "columns": {"A": {"hidden": ["West"]}}}
    assert load_sheet(path).filter == sheet_filter
    model.set_filter(sheet_filter, "Filter")
    loaded = SheetModel(rows=5, cols=5)
    loaded.load_sheet_data(model.sheet_data())
    assert loaded.sheet_filter() == sheet_filter and loaded.hidden_rows() == {2}


def test_damaged_filter(tmp_path):
    path = tmp_path / "f.ezs"
    path.write_text(json.dumps({"format": "ezsheet", "version": 9, "rows": 5, "columns": 5, "cells": {},
                                "filter": {"header": "A1:B2"}}), encoding="utf-8")
    with pytest.raises(SheetFileError, match="bad filter"):
        load_sheet(str(path))


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.model.set_cells({
        (0, 0): "Region", (0, 1): "Month", (0, 2): "Sales",
        (1, 0): "East", (1, 1): "Jan", (1, 2): "1200",
        (2, 0): "West", (2, 1): "Jan", (2, 2): "900",
        (3, 0): "East", (3, 1): "Feb", (3, 2): "1500",
        (4, 0): "North", (4, 1): "Feb",
        (5, 0): "West", (5, 1): "Mar", (5, 2): "700",
    })
    window.resize(900, 400)
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def filter_action(window):
    menu = [m for m in window.menuBar().actions() if m.text() == "Data"][0].menu()
    return [a for a in menu.actions() if a.text() in (CREATE_FILTER, REMOVE_FILTER)][0]


def hidden(window):
    return {row for row in range(10) if window.view.isRowHidden(row)}


def test_create_and_remove_from_the_data_menu(window):
    window.view.setCurrentIndex(window.model.index(2, 1))
    filter_action(window).trigger()  # no selection: the sheet's data
    assert window.model.sheet_filter() == SheetFilter(0, 0, 2)
    assert filter_action(window).text() == REMOVE_FILTER
    assert window.statusBar().currentMessage() == (
        "Made a filter on A1:C1. Click a header's filter button to choose what shows.")
    window._filter_column(0, ColumnFilter(frozenset({"West"})))
    assert hidden(window) == {2, 5} and window.statusBar().currentMessage() == "Showing 3 of 5 rows."
    window._filter_column(0, ColumnFilter())
    assert hidden(window) == set() and window.statusBar().currentMessage() == "Showing all 5 rows."
    window._filter_column(2, ColumnFilter(condition="less", value="1000"))
    assert hidden(window) == {1, 3, 4}
    filter_action(window).trigger()
    assert window.model.sheet_filter() is None and hidden(window) == set()
    assert filter_action(window).text() == CREATE_FILTER
    assert window.statusBar().currentMessage() == "Removed the filter: every row shows."
    window.undo_action.trigger()
    assert hidden(window) == {1, 3, 4} and filter_action(window).text() == REMOVE_FILTER


def test_create_on_the_selection(window):
    window.view.select_range(1, 1, 3, 2)
    window.toggle_filter()
    assert window.model.sheet_filter() == SheetFilter(1, 1, 2)


def test_nothing_to_filter(app):
    window = MainWindow()
    assert not window.toggle_filter() and window.model.sheet_filter() is None
    assert window.statusBar().currentMessage() == "There's nothing to filter. Put some data in the sheet first."
    window.close()


def test_filter_button_opens_its_menu(window):
    window.toggle_filter()
    view = window.view
    rect = view.filter_button_rect(0, 1)
    assert view.filter_button_at(rect.center()) == 1
    assert view.filter_button_at(view.visualRect(window.model.index(0, 1)).topLeft() + QPoint(2, 2)) is None
    assert view.filter_button_at(view.filter_button_rect(1, 1).center()) is None  # (not the header row)
    clicked = []
    view.filter_button_clicked.connect(lambda col, _where: clicked.append(col))
    QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=rect.center())
    assert clicked == [1]
    window.filter_menu.hide()


def test_filter_menu_lists_the_values(window):
    window.toggle_filter()
    window._filter_column(2, ColumnFilter(frozenset({"900"})))
    window._show_filter_menu(2, QPoint(0, 0))
    menu = window.filter_menu
    items = [menu.list.item(i) for i in range(menu.list.count())]
    assert [item.text() for item in items] == ["700", "900", "1200", "1500", BLANKS]  # as sorted
    assert [item.checkState() == Qt.Checked for item in items] == [True, False, True, True, True]
    menu.hide()


def test_filter_menu_choices(app):
    menu = FilterMenu(["apple", "pear", ""], ColumnFilter(frozenset({"pear"}), "contains", "x"))
    assert menu.column_filter() == ColumnFilter(frozenset({"pear"}), "contains", "x")
    applied = []
    menu.applied.connect(applied.append)
    menu.search.setText("PP")  # Select all and Clear: just what the search shows
    menu._check_all(False)
    menu.search.setText("")
    menu.condition_box.setCurrentIndex(menu.condition_box.findData("empty"))
    assert not menu.value_edit.isEnabled()
    menu.ok_button.click()
    assert applied == [ColumnFilter(frozenset({"apple", "pear"}), "empty", "")]
    menu._check_all(True)
    menu.condition_box.setCurrentIndex(0)
    assert not menu.column_filter().active


def test_sort_from_the_filter_menu(window):
    window.toggle_filter()
    menu_sorts = []
    window._show_filter_menu(2, QPoint(0, 0))
    window.filter_menu.sort.connect(menu_sorts.append)
    window.filter_menu._sort(False)  # Z → A
    assert menu_sorts == [False]
    assert [window.model.get_cell(row, 2) for row in range(6)] == ["Sales", "1500", "1200", "900", "700", ""]
    assert window.model.get_cell(0, 0) == "Region"  # the header stays


def test_moving_skips_hidden_rows(window):
    window.toggle_filter()
    window._filter_column(0, ColumnFilter(frozenset({"West"})))
    window.view.setCurrentIndex(window.model.index(1, 0))
    window.view.move_current(1, 0)
    assert window.view.currentIndex().row() == 3
    window.view.move_current(1, 0)
    window.view.move_current(1, 0)
    assert window.view.currentIndex().row() == 6
    window.view.move_current(-1, 0)
    assert window.view.currentIndex().row() == 4


def test_opened_sheet_hides_its_rows(window, tmp_path):
    window.toggle_filter()
    window._filter_column(1, ColumnFilter(frozenset({"Jan"})))
    path = str(tmp_path / "f.ezs")
    sheet = window.model.sheet_data()
    save_sheet(path, sheet)
    other = MainWindow()
    other.open_document(path)
    assert {row for row in range(10) if other.view.isRowHidden(row)} == {1, 2}
    assert filter_action(other).text() == REMOVE_FILTER
    other.setWindowModified(False)
    other.close()


class PaintSpy(QObject):
    """The parts of a widget repainted."""

    def __init__(self, widget):
        super().__init__()
        self.region = QRegion()
        widget.installEventFilter(self)

    def eventFilter(self, _obj, event):
        if event.type() == QEvent.Paint:
            self.region += event.region()
        return False


@pytest.mark.parametrize("change", [
    lambda window: window.toggle_filter(),  # create
    lambda window: (window.toggle_filter(), QApplication.processEvents(), window.toggle_filter()),  # remove
    lambda window: (window.toggle_filter(), QApplication.processEvents(),
                    window._filter_column(2, ColumnFilter(frozenset({"900"})))),  # a button turns green
])
def test_header_buttons_repainted(window, change):
    window.view.setCurrentIndex(window.model.index(3, 1))
    QApplication.processEvents()
    spy = PaintSpy(window.view.viewport())
    change(window)
    QApplication.processEvents()
    for col in range(3):
        assert spy.region.contains(window.view.filter_button_rect(0, col)), col
