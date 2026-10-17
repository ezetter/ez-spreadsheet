import json

import pytest
from PySide6.QtCore import Qt

from ezsheet.borders import border_styles, covered, merged
from ezsheet.model import SheetModel
from ezsheet.storage import SheetData, SheetFileError, load_sheet, save_sheet
from ezsheet.textstyle import PLAIN, Border, CellStyle, from_json, to_json
from ezsheet.window import MainWindow

THIN, THICK = Border(), Border("thick", "#cc0000")


def sides(styles) -> dict:
    """Each cell's sides with borders, from new styles: (row, col) -> {side: style}."""
    return {key: {side: border.style for side, border in style.borders.items()}
            for key, style in styles.items() if style.borders}


def apply(kind, block=(1, 1, 2, 2), styles=None, border=THIN):
    styles = styles or {}
    return border_styles(lambda r, c: styles.get((r, c), PLAIN), block, kind, border, 10, 10)


# --- Which sides ---

def test_all_borders():
    assert sides(apply("all")) == {
        (1, 1): {"top": "thin", "left": "thin", "bottom": "thin", "right": "thin"},
        (1, 2): {"top": "thin", "right": "thin", "bottom": "thin"},
        (2, 1): {"left": "thin", "bottom": "thin", "right": "thin"},
        (2, 2): {"right": "thin", "bottom": "thin"},
    }  # each edge once: inside, the upper or left cell's


def test_outer_inner_and_lines():
    assert sides(apply("outer")) == {(1, 1): {"top": "thin", "left": "thin"}, (1, 2): {"top": "thin", "right": "thin"},
                                     (2, 1): {"bottom": "thin", "left": "thin"},
                                     (2, 2): {"bottom": "thin", "right": "thin"}}
    assert sides(apply("inner")) == {(1, 1): {"bottom": "thin", "right": "thin"}, (1, 2): {"bottom": "thin"},
                                     (2, 1): {"right": "thin"}}
    assert sides(apply("horizontal")) == {(1, 1): {"bottom": "thin"}, (1, 2): {"bottom": "thin"}}
    assert sides(apply("vertical")) == {(1, 1): {"right": "thin"}, (2, 1): {"right": "thin"}}
    assert sides(apply("top")) == {(1, 1): {"top": "thin"}, (1, 2): {"top": "thin"}}
    assert sides(apply("left", (1, 1, 1, 1))) == {(1, 1): {"left": "thin"}}


def test_an_edge_is_never_two_lines():
    neighbor = {(0, 1): CellStyle(bottom=THICK, bold=True)}  # the edge above B2, drawn by the cell above
    new = apply("top", (1, 1, 1, 1), neighbor)
    assert new[(1, 1)].top == THIN and new[(0, 1)] == CellStyle(bold=True)  # its side cleared, its bold kept


def test_clear_borders():
    styles = {(1, 1): CellStyle(top=THIN, left=THIN, italic=True), (0, 1): CellStyle(bottom=THIN),
              (1, 3): CellStyle(left=THICK), (2, 2): CellStyle(right=THIN)}
    new = apply("clear", (1, 1, 2, 2), styles)
    assert not sides(new) and new[(1, 1)] == CellStyle(italic=True)  # and the neighbors' sides facing it


def test_borders_at_the_sheets_edges():
    assert set(apply("all", (0, 0, 0, 0))) == {(0, 0), (0, 1), (1, 0)}  # (none above or left of A1)


def test_merging():
    assert merged(set(), (0, 0, 1, 1), "all") == {(0, 0, 1, 1)}
    assert merged(set(), (0, 0, 1, 2), "horizontally") == {(0, 0, 0, 2), (1, 0, 1, 2)}
    assert merged(set(), (0, 0, 2, 1), "vertically") == {(0, 0, 2, 0), (0, 1, 2, 1)}
    assert merged(set(), (0, 0, 2, 0), "horizontally") == set()  # one cell each: nothing to merge
    assert merged({(0, 0, 1, 1), (5, 5, 6, 6)}, (1, 1, 2, 2), "all") == {(1, 1, 2, 2), (5, 5, 6, 6)}
    assert merged({(0, 0, 1, 1), (5, 5, 6, 6)}, (1, 1, 1, 1), "unmerge") == {(5, 5, 6, 6)}
    assert covered({(0, 0, 1, 1)}) == {(0, 1), (1, 0), (1, 1)}


# --- Saved ---

def test_border_json():
    style = CellStyle(top=THIN, right=THICK)
    assert to_json(style) == {"borders": {"top": "thin #000000", "right": "thick #cc0000"}}
    assert from_json(to_json(style)) == style


@pytest.mark.parametrize("borders", [3, {"up": "thin #000000"}, {"top": "wavy #000000"}, {"top": "thin red"},
                                     {"top": "thin"}])
def test_bad_borders(borders):
    assert from_json({"borders": borders}) is None


def test_merges_saved(tmp_path):
    path = str(tmp_path / "s.ezs")
    save_sheet(path, SheetData(rows=10, cols=5, merges=[(0, 0, 0, 2), (3, 1, 5, 1)]))
    assert json.loads(open(path).read())["merges"] == ["A1:C1", "B4:B6"]
    assert load_sheet(path).merges == [(0, 0, 0, 2), (3, 1, 5, 1)]


@pytest.mark.parametrize("merges", ["A1:B2", ["A1"], ["B2:A1"], ["A1:A1"], ["A1:B2", "B2:C3"], [3]])
def test_bad_merges(tmp_path, merges):
    path = tmp_path / "bad.ezs"
    path.write_text(json.dumps({"format": "ezsheet", "version": 8, "rows": 10, "columns": 5, "cells": {},
                                "merges": merges}))
    with pytest.raises(SheetFileError):
        load_sheet(str(path))


# --- Merges in the model ---

def test_model_merges(app):
    model = SheetModel(rows=10, cols=5)
    model.set_cells({(0, 0): "keep", (0, 1): "lost"})
    model.set_merges({(0, 0, 1, 2)}, {(0, 1): ""})
    assert model.merges() == [(0, 0, 1, 2)] and model.merge_at(1, 2) == (0, 0, 1, 2) and model.merge_at(2, 0) is None
    assert model.get_cell(0, 1) == ""
    model.undo_stack.undo()  # one step: the merge and the value
    assert model.merges() == [] and model.get_cell(0, 1) == "lost"
    model.undo_stack.redo()
    assert model.sheet_data().merges == [(0, 0, 1, 2)]


def test_merges_move_with_rows_and_columns(app):
    model = SheetModel(rows=10, cols=5)
    model.set_merges({(1, 1, 2, 2), (5, 0, 5, 3)})
    model.insert_rows(2)  # inside the first: it grows
    assert model.merges() == [(1, 1, 3, 2), (6, 0, 6, 3)]
    model.insert_columns(0)
    assert model.merges() == [(1, 2, 3, 3), (6, 1, 6, 4)]
    model.delete_rows(1, 2)  # two of its three rows: one's left, so it's two cells across
    assert model.merges() == [(1, 2, 1, 3), (4, 1, 4, 4)]
    model.delete_columns(2)  # down to one cell: not merged now
    assert model.merges() == [(4, 1, 4, 3)]


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def test_borders_menu(window):
    model = window.model
    window.view.select_range(1, 1, 2, 2)
    actions = {action.text(): action for action in window.borders_button.menu().actions() if action.text()}
    assert list(actions)[:10] == ["All borders", "Inner borders", "Horizontal borders", "Vertical borders",
                                  "Outer borders", "Left border", "Top border", "Right border", "Bottom border",
                                  "Clear borders"]
    actions["Outer borders"].trigger()
    assert model.cell_style(1, 1).top == THIN and model.cell_style(2, 2).right == THIN
    assert window.undo_action.text() == "Undo Borders"
    window._set_border_style("thick")
    window._set_border_color("#cc0000")
    actions["Bottom border"].trigger()
    assert model.cell_style(2, 1).bottom == THICK
    actions["Clear borders"].trigger()
    assert not model.bordered_cells()


def test_border_style_and_color_choices(window, dialogs):
    menu = window.borders_button.menu()
    style_menu = [a.menu() for a in menu.actions() if a.text() == "Border style"][0]
    assert [a.text() for a in style_menu.actions()] == ["Thin", "Medium", "Thick", "Dashed", "Dotted", "Double"]
    style_menu.actions()[3].trigger()
    assert window.border_style == "dashed" and style_menu.actions()[3].isChecked()
    color_menu = [a.menu() for a in menu.actions() if a.text() == "Border color"][0]
    color_menu.swatches["#0000ff"].click()
    assert window.border_color == "#0000ff"
    dialogs.color_answer = "#123456"
    window._custom_border_color()  # (Custom…, and Format > Borders > Border Color…)
    assert window.border_color == "#123456"
    format_menu = [m for m in window.menuBar().actions() if m.text() == "Format"][0].menu()
    borders = [a.menu() for a in format_menu.actions() if a.text() == "Borders"][0]
    assert "Border Color…" in [a.text() for a in borders.actions()]


def test_merge_button(window, dialogs):
    model = window.model
    model.set_cells({(0, 0): "Title", (0, 1): "x"})
    window.view.select_range(0, 0, 1, 2)
    window.merge_button.click()
    assert model.merges() == [(0, 0, 1, 2)] and dialogs.merge_prompts == 1  # x would be lost: asked
    assert model.get_cell(0, 0) == "Title" and model.get_cell(0, 1) == ""
    assert window.view.rowSpan(0, 0) == 2 and window.view.columnSpan(0, 0) == 3  # shown as one cell
    assert window.undo_action.text() == "Undo Merge Cells"
    window.view.setCurrentIndex(model.index(0, 0))
    window.merge_button.click()  # a merged cell: unmerged
    assert model.merges() == [] and window.view.columnSpan(0, 0) == 1


def test_merge_cancelled(window, dialogs):
    model = window.model
    model.set_cells({(0, 0): "a", (1, 0): "b"})
    dialogs.merge_answer = False
    window.view.select_range(0, 0, 1, 0)
    window._merge("all")
    assert model.merges() == [] and model.get_cell(1, 0) == "b"


def test_merge_kinds_and_nothing_to_merge(window, dialogs):
    model = window.model
    window.view.select_range(0, 0, 1, 2)
    window._merge("horizontally")
    assert model.merges() == [(0, 0, 0, 2), (1, 0, 1, 2)] and dialogs.merge_prompts == 0  # nothing lost
    window.view.select_range(0, 0, 1, 2)
    window._merge("vertically")  # (the blocks it touches give way)
    assert model.merges() == [(0, 0, 1, 0), (0, 1, 1, 1), (0, 2, 1, 2)]
    window.view.select_range(5, 5, 5, 5)
    window._merge("all")
    assert "more than one cell" in window.statusBar().currentMessage()


def test_moving_through_a_merged_cell(window):
    model = window.model
    model.set_merges({(1, 1, 2, 3)})
    window.view.setCurrentIndex(model.index(1, 0))
    window.view.move_current(0, 1)
    assert (window.view.currentIndex().row(), window.view.currentIndex().column()) == (1, 1)  # into it
    window.view.move_current(0, 1)
    assert window.view.currentIndex().column() == 4  # out its far side
    window.view.setCurrentIndex(model.index(3, 2))
    window.view.move_current(-1, 0)
    assert (window.view.currentIndex().row(), window.view.currentIndex().column()) == (1, 1)  # its top-left


def test_borders_of_a_merged_cell(window):
    model = window.model
    model.set_merges({(0, 0, 1, 1)})
    window.view.setCurrentIndex(model.index(0, 0))
    window.view.select_range(0, 0, 0, 0)  # (the merged cell: all of it)
    window._apply_borders("outer")
    assert model.cell_style(1, 1).bottom == THIN and model.cell_style(1, 1).right == THIN


def test_merges_saved_and_opened(window, tmp_path):
    window.model.set_merges({(0, 0, 0, 3)})
    path = str(tmp_path / "s.ezs")
    window.save_to(path)
    other = MainWindow()
    other.open_path(path)
    assert other.model.merges() == [(0, 0, 0, 3)] and other.view.columnSpan(0, 0) == 4
    other.setWindowModified(False)
    other.close()


def test_borders_are_drawn(window):
    window.model.set_styles({(1, 1): CellStyle(bottom=Border("thick", "#ff0000"))}, "Borders")
    window.view.scrollToTop()
    image = window.view.viewport().grab().toImage()
    x = window.view.columnViewportPosition(1) + window.view.columnWidth(1) // 2
    y = window.view.rowViewportPosition(1) + window.view.rowHeight(1) - 1
    assert image.pixelColor(x, y).name() == "#ff0000"
