import pytest
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from ezsheet.filtering import ColumnFilter, SheetFilter
from ezsheet.search import Search, cells_in_order
from ezsheet.window import MainWindow


# --- What matches, and what it's replaced with ---

@pytest.mark.parametrize("search, raw, shown, found", [
    (Search("east"), "North East", "North East", True),  # ignoring case
    (Search("east", match_case=True), "North East", "North East", False),
    (Search("East", entire=True), "North East", "North East", False),
    (Search("north east", entire=True), "North East", "North East", True),
    (Search("1200"), "1200", "$1,200.00", True),  # as typed,
    (Search("$1,200"), "1200", "$1,200.00", False),  # not as shown
    (Search("24"), "=B2*2", "24", True),  # but a formula by what it shows
    (Search("B2"), "=B2*2", "24", False),
    (Search("B2", formulas=True), "=B2*2", "24", True),  # or its formula
    (Search(r"^\d+$", regex=True), "1200", "1200", True),
    (Search(r"^\d+$", regex=True), "12a", "12a", False),
    (Search(r"\d+", regex=True, entire=True), "12a", "12a", False),
    (Search("a.c"), "abc", "abc", False),  # not a regular expression unless asked
    (Search(".*", regex=True), "", "", False),  # an empty cell has nothing
])
def test_matches(search, raw, shown, found):
    assert search.matches(raw, shown) is found


@pytest.mark.parametrize("search, raw, result", [
    (Search("east", "West"), "East by eastern", ("West by Western", 2)),
    (Search("east", "West", match_case=True), "East by eastern", ("East by Western", 1)),
    (Search("east by eastern", "x", entire=True), "East by eastern", ("x", 1)),
    (Search("B2", "C2", formulas=True), "=B2*2+B2", ("=C2*2+C2", 2)),
    (Search(r"(\w+), (\w+)", "$2 $1", regex=True), "Smith, Ann", ("Ann Smith", 1)),
    (Search(r"(\d+)", r"\1$1", regex=True), "a7", (r"a\17", 1)),  # (a backslash is just a backslash)
    (Search("a.c", "$1"), "a.c", ("$1", 1)),  # not a group unless a regular expression
])
def test_replaced(search, raw, result):
    assert search.replaced(raw) == result


@pytest.mark.parametrize("search, replacing, problem", [
    (Search(""), False, "Type something to find."),
    (Search("(", regex=True), False, "That's not a regular expression: missing ), unterminated subpattern at position 0."),
    (Search("(", regex=False), False, None),
    (Search(r"(\d)", "$2", regex=True), False, None),
    (Search(r"(\d)", "$2", regex=True), True, "The regular expression has no group $2 to put in its place."),
    (Search(r"(\d)", "$1", regex=True), True, None),
])
def test_problems(search, replacing, problem):
    assert search.problem(replacing) == problem


def test_order_wraps_round():
    cells = [(2, 0), (0, 1), (1, 3), (0, 4)]
    assert cells_in_order(cells, (0, 1)) == [(0, 4), (1, 3), (2, 0), (0, 1)]
    assert cells_in_order(cells, (1, 0)) == [(1, 3), (2, 0), (0, 1), (0, 4)]  # (from a cell that isn't one)
    assert cells_in_order(cells, (0, 4), backward=True) == [(0, 1), (2, 0), (1, 3), (0, 4)]
    assert cells_in_order(cells, None) == [(0, 1), (0, 4), (1, 3), (2, 0)]


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.model.set_cells({
        (0, 0): "Region", (0, 1): "Sales", (0, 2): "Double",
        (1, 0): "East", (1, 1): "1200", (1, 2): "=B2*2",
        (2, 0): "West", (2, 1): "900", (2, 2): "=B3*2",
        (3, 0): "east coast", (3, 1): "2400", (3, 2): "=B4*2",
    })
    window.show()
    yield window
    if window.find_dialog is not None:
        window.find_dialog.close()
    window.setWindowModified(False)
    window.close()


def edit_menu(window):
    menu = [m for m in window.menuBar().actions() if m.text() == "Edit"][0].menu()
    return {action.text(): action for action in menu.actions() if action.text()}


def open_find(window, find, replace="", **options):
    dialog = window.find_and_replace()
    dialog.find_edit.setText(find)
    dialog.replace_edit.setText(replace)
    for name, checked in options.items():
        getattr(dialog, f"{name}_box").setChecked(checked)
    return dialog


def current(window):
    return window.view.currentIndex().row(), window.view.currentIndex().column()


def message(window):
    return window.statusBar().currentMessage()


def test_edit_menu(window):
    actions = edit_menu(window)
    assert actions["Find and Replace…"].shortcuts() == [QKeySequence(QKeySequence.Find), QKeySequence("Ctrl+Shift+H")]
    assert actions["Find Next"].shortcut() == QKeySequence(QKeySequence.FindNext)
    assert actions["Find Previous"].shortcut() == QKeySequence(QKeySequence.FindPrevious)
    actions["Find and Replace…"].trigger()
    assert window.find_dialog.isVisible() and window.find_dialog.windowTitle() == "Find and Replace"


def test_find_goes_round(window):
    dialog = open_find(window, "east")
    dialog.find_button.click()
    assert current(window) == (1, 0) and message(window) == "Found “east” in A2 (1 of 2)."
    assert dialog.message.text() == message(window)
    dialog.find_button.click()
    assert current(window) == (3, 0) and message(window) == "Found “east” in A4 (2 of 2)."
    dialog.find_button.click()
    assert current(window) == (1, 0)  # round again
    edit_menu(window)["Find Previous"].trigger()
    assert current(window) == (3, 0)
    edit_menu(window)["Find Next"].trigger()
    assert current(window) == (1, 0)


def test_find_by_what_formulas_show(window):
    dialog = open_find(window, "4800")
    dialog.find_button.click()
    assert current(window) == (3, 2)
    dialog.find_edit.setText("B3")
    dialog.find_button.click()
    assert message(window) == "Couldn't find “B3”."
    dialog.formulas_box.setChecked(True)
    dialog.find_button.click()
    assert current(window) == (2, 2)


def test_find_next_without_a_search_opens_the_window(window):
    assert window.find_next() is None and window.find_dialog.isVisible()


def test_problems_are_shown(window):
    dialog = open_find(window, "(", regex=True)
    dialog.find_button.click()
    assert dialog.message.text().startswith("That's not a regular expression:")
    dialog.find_edit.setText("")
    assert not dialog.find_button.isEnabled() and not dialog.replace_all_button.isEnabled()


def test_selected_range(window):
    window.view.select_range(2, 0, 3, 1)
    dialog = open_find(window, "east")
    assert [dialog.scope_box.itemText(i) for i in range(2)] == ["All cells", "Selected range (A3:B4)"]
    assert dialog.in_range()
    dialog.find_button.click()
    assert current(window) == (3, 0) and message(window) == "Found “east” in A4 (1 of 1)."
    assert len(window.view.selectedIndexes()) == 1  # just the cell found,
    dialog.find_button.click()
    assert current(window) == (3, 0)  # but still in the range
    assert window.find_and_replace().in_range()  # (as it was, while it's open)
    dialog.scope_box.setCurrentIndex(0)
    dialog.find_button.click()
    assert current(window) == (1, 0)
    dialog.close()
    dialog = open_find(window, "east")
    assert dialog.scope_box.count() == 1 and not dialog.in_range()  # just one cell: all of them


def test_skips_rows_the_filter_hides(window):
    window.model.set_filter(SheetFilter(0, 0, 2, ((1, ColumnFilter(frozenset({"1200"}))),)), "Filter")
    dialog = open_find(window, "east")
    dialog.find_button.click()
    assert current(window) == (3, 0) and message(window) == "Found “east” in A4 (1 of 1)."


def test_replace_one_at_a_time(window):
    dialog = open_find(window, "east", "North")
    dialog.replace_button.click()  # first, it finds
    assert current(window) == (1, 0) and window.model.get_cell(1, 0) == "East"
    dialog.replace_button.click()
    assert window.model.get_cell(1, 0) == "North" and current(window) == (3, 0)
    assert message(window) == "Replaced “east” in A2. Next: A4."
    dialog.replace_button.click()
    assert window.model.get_cell(3, 0) == "North coast" and message(window) == "Replaced “east” in A4. There are no more."
    assert window.undo_action.text() == "Undo Replace"
    window.undo_action.trigger()
    assert window.model.get_cell(3, 0) == "east coast"


def test_replace_wont_change_a_formulas_result(window):
    dialog = open_find(window, "4800", "1")
    dialog.find_button.click()
    dialog.replace_button.click()
    assert window.model.get_cell(3, 2) == "=B4*2"
    assert message(window) == ("C4 shows “4800” from its formula, so it can't be replaced there. "
                               "Check Also search within formulas to change formulas.")


def test_replace_all(window):
    dialog = open_find(window, "e", "E", case=True)
    assert window.replace_all() == 5  # (not East's: case)
    assert [window.model.get_cell(row, 0) for row in range(4)] == ["REgion", "East", "WEst", "East coast"]
    assert [window.model.get_cell(0, col) for col in (1, 2)] == ["SalEs", "DoublE"]
    assert message(window) == "Replaced 5 instances of “e” with “E” in 5 cells."
    assert window.undo_action.text() == "Undo Replace All"
    window.undo_action.trigger()  # one step
    assert [window.model.get_cell(row, 0) for row in range(4)] == ["Region", "East", "West", "east coast"]
    dialog.case_box.setChecked(False)
    dialog.find_edit.setText("zzz")
    dialog.replace_all_button.click()
    assert message(window) == "Couldn't find “zzz”."


def test_replace_all_in_formulas(window):
    dialog = open_find(window, "*2", "*3", formulas=True)
    dialog.replace_all_button.click()
    assert [window.model.get_cell(row, 2) for row in range(1, 4)] == ["=B2*3", "=B3*3", "=B4*3"]
    assert window.model.value(1, 2) == 3600.0
    assert message(window) == "Replaced 3 instances of “*2” with “*3” in 3 cells."


def test_replace_all_skips_formula_results(window):
    open_find(window, r"^\d+00$", "0", regex=True)
    assert window.replace_all() == 3  # B2:B4, not C's results
    assert message(window) == ("Replaced 3 instances of “^\\d+00$” with “0” in 3 cells. "
                               "3 cells showed it from formulas; check Also search within formulas to change formulas.")


def test_replace_all_in_the_range_with_groups(window):
    window.view.select_range(1, 0, 2, 0)
    open_find(window, r"(\w)(\w+)", "$2$1", regex=True, entire=True)
    window.replace_all()
    assert [window.model.get_cell(row, 0) for row in range(4)] == ["Region", "astE", "estW", "east coast"]
    assert message(window) == "Replaced 2 instances of “(\\w)(\\w+)” with “$2$1” in 2 cells in A2:A3."
    open_find(window, r"(\w)", "$3", regex=True).replace_all_button.click()
    assert message(window) == "The regular expression has no group $3 to put in its place."


def test_includes_the_cell_being_edited(window):
    window.view.setCurrentIndex(window.model.index(0, 1))
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    window.edit_bar.setFocus()
    window.edit_bar.selectAll()
    QTest.keyClicks(window.edit_bar, "Eastern sales")
    open_find(window, "eastern").find_button.click()
    assert window.model.get_cell(0, 1) == "Eastern sales" and current(window) == (0, 1)
