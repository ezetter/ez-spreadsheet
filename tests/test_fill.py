import numpy as np
import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel
from PySide6.QtWidgets import QDialogButtonBox, QToolBar, QToolButton

from py_spread.fill import (
    FILL_MODES,
    LetterSequence,
    RandomLetters,
    RandomPattern,
    letter_index,
    letter_sequence_values,
    random_letters,
    random_pattern,
    RandomFill,
    SequenceFill,
    UniformFill,
    check_random,
    check_sequence,
    infer,
    order_cells,
    random_values,
    sequence_values,
    written_as_float,
)
from py_spread.fill_dialogs import RandomDialog, SequenceDialog, UniformDialog
from py_spread.window import MainWindow

MODES = {m.key: m for m in FILL_MODES}


# --- Pure logic ---

def test_order_cells():
    cells = {(0, 0), (0, 1), (1, 0), (1, 1)}
    assert order_cells(cells) == [(0, 0), (1, 0), (0, 1), (1, 1)]  # down, then across
    assert order_cells(cells, across_first=True) == [(0, 0), (0, 1), (1, 0), (1, 1)]


@pytest.mark.parametrize("params, count, expected", [
    (SequenceFill(1, 5, 1), 5, ["1", "2", "3", "4", "5"]),
    (SequenceFill(1, 5, 1, descending=True), 5, ["5", "4", "3", "2", "1"]),
    (SequenceFill(0, 1, 0.25), 5, ["0", "0.25", "0.5", "0.75", "1"]),
    (SequenceFill(0, 1, 0.1), 11, ["0", "0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "1"]),
    (SequenceFill(0, 10), 6, ["0", "2", "4", "6", "8", "10"]),          # blank step: integers fit
    (SequenceFill(0, 1), 3, ["0", "0.5", "1"]),                          # blank step: floats needed
    (SequenceFill(1, 3, 1), 5, ["1", "2", "3"]),                         # ends before the cells do
    (SequenceFill(1, 100, 1), 3, ["1", "2", "3"]),                       # cells end first
    (SequenceFill(0, 10, 3, descending=True), 9, ["10", "7", "4", "1"]),
    (SequenceFill(2, 9), 1, ["2"]),
])
def test_sequence_values(params, count, expected):
    assert sequence_values(params, count) == expected


@pytest.mark.parametrize("text, expected", [
    ("1.0", True), ("2.50", True), ("1e3", True), (".5", True),
    ("1", False), ("-7", False), ("abc", False), ("1.0x", False), ("", False),
])
def test_written_as_float(text, expected):
    assert written_as_float(text) == expected


def test_float_sequences_keep_decimal_point():
    assert sequence_values(SequenceFill(1, 3, 1, floats=True), 3) == ["1.0", "2.0", "3.0"]
    assert sequence_values(SequenceFill(0, 1, 0.5, floats=True), 3) == ["0.0", "0.5", "1.0"]


def test_random_integers_within_inclusive_bounds():
    rng = np.random.default_rng(0)
    values = [int(v) for v in random_values(RandomFill(1, 3, True), 500, rng)]
    assert set(values) == {1, 2, 3}


def test_random_floats_within_bounds():
    rng = np.random.default_rng(0)
    texts = random_values(RandomFill(2.25, 2.75, False), 500, rng)
    assert all("." in t for t in texts)
    values = [float(t) for t in texts]
    assert all(2.25 <= v <= 2.75 for v in values)
    assert len(set(values)) > 400


@pytest.mark.parametrize("params, ok", [
    (RandomFill(1, 6, True), True),
    (RandomFill(2.25, 2.75, False), True),   # floats may lie between consecutive integers
    (RandomFill(2.25, 2.75, True), False),   # integers may not
    (RandomFill(1, 6.5, True), False),
    (RandomFill(5, 5, False), False),
    (RandomFill(6, 1, True), False),
])
def test_check_random(params, ok):
    assert (check_random(params) is None) == ok


@pytest.mark.parametrize("params, ok", [
    (SequenceFill(1, 5, 1), True),
    (SequenceFill(1, 5), True),
    (SequenceFill(1, 5, 0), False),
    (SequenceFill(1, 5, -1), False),
    (SequenceFill(5, 1, 1), False),
])
def test_check_sequence(params, ok):
    assert (check_sequence(params) is None) == ok


@pytest.mark.parametrize("mode, raw, values, count, expected", [
    ("uniform", ["7", ""], [7.0, None], 5, UniformFill("7")),
    ("uniform", ["hello", "3"], ["hello", 3.0], 5, UniformFill("hello")),
    ("uniform", ["", "3"], [None, 3.0], 5, None),
    ("sequence", ["1", "3"], [1.0, 3.0], 5, SequenceFill(1, 9, 2)),
    ("sequence", ["1.0", "2.0"], [1.0, 2.0], 3, SequenceFill(1, 3, 1, floats=True)),
    ("sequence", ["1", "2.0"], [1.0, 2.0], 3, SequenceFill(1, 3, 1, floats=True)),
    ("sequence", ["1e2", "2e2"], [100.0, 200.0], 3, SequenceFill(100, 300, 100, floats=True)),
    ("sequence", ["=1+0", "2"], [1.0, 2.0], 3, SequenceFill(1, 3, 1)),
    ("sequence", ["10", "8"], [10.0, 8.0], 4, SequenceFill(4, 10, 2, descending=True)),
    ("sequence", ["4", "4"], [4.0, 4.0], 4, UniformFill("4")),
    ("sequence", ["1", ""], [1.0, None], 4, None),
    ("sequence", ["1", "x"], [1.0, "x"], 4, None),
    ("random", ["10", "1"], [10.0, 1.0], 4, RandomFill(1, 10, True)),
    ("random", ["0", "0.5"], [0.0, 0.5], 4, RandomFill(0, 0.5, False)),
    ("random", ["1.0", "6.0"], [1.0, 6.0], 4, RandomFill(1, 6, False)),
    ("random", ["1", "6.0"], [1.0, 6.0], 4, RandomFill(1, 6, False)),
    ("random", ["1", ""], [1.0, None], 4, None),
])
def test_infer(mode, raw, values, count, expected):
    assert infer(MODES[mode], raw, values, count) == expected


# --- In the window ---

class StubDialogs:
    """Answers fill dialogs without showing them, and records what was asked."""

    def __init__(self):
        self.answer = None
        self.asked = []

    def random(self, initial, keep_vowels=True):
        self.asked.append(("random", initial))
        self.keep_vowels = keep_vowels
        return self.answer

    def sequence(self, initial, cell_count):
        self.asked.append(("sequence", initial, cell_count))
        return self.answer

    def uniform(self, initial):
        self.asked.append(("uniform", initial))
        return self.answer


@pytest.fixture
def window(app):
    window = MainWindow()
    window.fill.dialogs = StubDialogs()
    window.fill.rng = np.random.default_rng(1)
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def select(window, top, left, bottom, right):
    model = window.model
    selection = window.view.selectionModel()
    selection.setCurrentIndex(model.index(top, left), QItemSelectionModel.NoUpdate)
    selection.select(QItemSelection(model.index(top, left), model.index(bottom, right)),
                     QItemSelectionModel.ClearAndSelect)


def column(window, col, rows):
    return [window.model.get_cell(r, col) for r in rows]


def fill(window, mode):
    window.fill_actions[mode].trigger()


def test_fill_button_follows_sigma(window):
    toolbar = window.findChild(QToolBar)
    buttons = [toolbar.widgetForAction(a) for a in toolbar.actions()]
    assert buttons[:2] == [window.autosum_button, window.fill_button]
    assert window.fill_button.popupMode() == QToolButton.MenuButtonPopup
    assert [a.text() for a in window.fill_button.menu().actions()] == ["Random", "Sequence", "Uniform"]
    assert window.fill_button.text() == "Fill: Sequence"


def test_uniform_uses_first_value_without_dialog(window):
    window.model.set_cell(0, 0, "7")
    select(window, 0, 0, 3, 1)
    fill(window, "uniform")
    assert window.fill.dialogs.asked == []
    assert column(window, 0, range(4)) == ["7"] * 4
    assert column(window, 1, range(4)) == ["7"] * 4
    assert window.fill_button.text() == "Fill: Uniform"
    assert "Filled 8 cells" in window.statusBar().currentMessage()


def test_uniform_formula_references_move(window):
    window.model.set_cell(0, 0, "1")
    window.model.set_cell(1, 0, "2")
    window.model.set_cell(0, 1, "=A1*10")
    select(window, 0, 1, 1, 1)
    fill(window, "uniform")
    assert column(window, 1, range(2)) == ["=A1*10", "=A2*10"]


def test_uniform_asks_when_first_cell_empty(window):
    window.fill.dialogs.answer = UniformFill("x")
    select(window, 0, 0, 2, 0)
    fill(window, "uniform")
    assert window.fill.dialogs.asked == [("uniform", None)]
    assert column(window, 0, range(3)) == ["x"] * 3


def test_sequence_inferred_down_a_column(window):
    window.model.set_cell(0, 0, "5")
    window.model.set_cell(1, 0, "10")
    select(window, 0, 0, 5, 0)
    fill(window, "sequence")
    assert window.fill.dialogs.asked == []
    assert column(window, 0, range(6)) == ["5", "10", "15", "20", "25", "30"]


def test_sequence_inferred_across_a_row(window):
    window.model.set_cell(2, 0, "1")
    window.model.set_cell(2, 1, "0.5")
    select(window, 2, 0, 2, 4)
    fill(window, "sequence")
    assert [window.model.get_cell(2, c) for c in range(5)] == ["1.0", "0.5", "0.0", "-0.5", "-1.0"]


def test_sequence_inferred_continues_into_next_column(window):
    window.model.set_cell(0, 0, "1")
    window.model.set_cell(1, 0, "2")
    select(window, 0, 0, 2, 1)
    fill(window, "sequence")
    assert column(window, 0, range(3)) == ["1", "2", "3"]
    assert column(window, 1, range(3)) == ["4", "5", "6"]


def test_sequence_from_dialog(window):
    window.fill.dialogs.answer = SequenceFill(0, 1, None, descending=True)
    select(window, 0, 0, 4, 0)
    fill(window, "sequence")
    assert window.fill.dialogs.asked == [("sequence", None, 5)]
    assert column(window, 0, range(5)) == ["1", "0.75", "0.5", "0.25", "0"]


def test_sequence_across_first_from_dialog(window):
    window.fill.dialogs.answer = SequenceFill(1, 4, 1, across_first=True)
    select(window, 0, 0, 1, 1)
    fill(window, "sequence")
    assert column(window, 0, range(2)) == ["1", "3"]
    assert column(window, 1, range(2)) == ["2", "4"]


def test_sequence_too_short_leaves_rest_and_says_so(window):
    window.model.set_cell(3, 0, "keep")
    window.fill.dialogs.answer = SequenceFill(1, 3, 1)
    select(window, 0, 0, 3, 0)
    fill(window, "sequence")
    assert column(window, 0, range(4)) == ["1", "2", "3", "keep"]
    assert "1 cells were left unchanged" in window.statusBar().currentMessage()


def test_random_inferred_replaces_the_examples(window):
    window.model.set_cell(0, 0, "1")
    window.model.set_cell(1, 0, "6")
    select(window, 0, 0, 39, 0)
    fill(window, "random")
    assert window.fill.dialogs.asked == []
    values = column(window, 0, range(40))
    assert all(v.isdigit() and 1 <= int(v) <= 6 for v in values)
    assert len(set(values)) > 2  # the two examples were overwritten too


def test_random_inferred_floats(window):
    window.model.set_cell(0, 0, "0")
    window.model.set_cell(1, 0, "0.5")
    select(window, 0, 0, 19, 0)
    fill(window, "random")
    values = [float(v) for v in column(window, 0, range(20))]
    assert all(0 <= v <= 0.5 for v in values)
    assert any(not v.is_integer() for v in values)


def test_random_from_dialog(window):
    window.fill.dialogs.answer = RandomFill(10, 20, True)
    select(window, 0, 0, 9, 0)
    fill(window, "random")
    assert all(10 <= int(v) <= 20 for v in column(window, 0, range(10)))


def test_cancelled_dialog_changes_nothing(window):
    window.model.set_cell(0, 0, "keep me")  # not a pure letter string, so the dialog is asked
    window.setWindowModified(False)
    window.fill.dialogs.answer = None
    select(window, 0, 0, 2, 0)
    fill(window, "random")
    assert column(window, 0, range(3)) == ["keep me", "", ""]
    assert not window.isWindowModified()


def test_dialog_offers_last_settings(window):
    previous = RandomFill(1, 6, True)
    window.fill.dialogs.answer = previous
    select(window, 0, 0, 2, 0)
    fill(window, "random")
    select(window, 0, 2, 2, 2)
    fill(window, "random")
    assert window.fill.dialogs.asked[-1] == ("random", previous)


def test_main_button_repeats_last_mode(window):
    window.model.set_cell(0, 0, "3")
    select(window, 0, 0, 2, 0)
    fill(window, "uniform")
    window.model.set_cell(0, 1, "9")
    select(window, 0, 1, 2, 1)
    window.fill_button.click()
    assert column(window, 1, range(3)) == ["9"] * 3


def test_fill_writes_one_change(window):
    changes = []
    window.model.contents_changed.connect(lambda: changes.append(1))
    window.fill.dialogs.answer = SequenceFill(1, 100)
    select(window, 0, 0, 99, 0)
    fill(window, "sequence")
    assert len(changes) == 1


# --- Dialogs ---

def ok_enabled(dialog):
    return dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()


def test_random_dialog(app):
    dialog = RandomDialog()
    dialog.lower.setText("2.25")
    dialog.upper.setText("2.75")
    assert not ok_enabled(dialog)
    assert "whole numbers" in dialog.note.text()
    dialog.floats.setChecked(True)
    assert ok_enabled(dialog)
    assert dialog.params() == RandomFill(2.25, 2.75, False)
    dialog.upper.setText("abc")
    assert not ok_enabled(dialog)
    assert dialog.params() is None


def test_random_dialog_starts_from_initial(app):
    dialog = RandomDialog(initial=RandomFill(0, 0.5, False))
    assert (dialog.lower.text(), dialog.upper.text()) == ("0", "0.5")
    assert dialog.floats.isChecked()


def test_sequence_dialog_preview(app):
    dialog = SequenceDialog(cell_count=6)
    dialog.lower.setText("0")
    dialog.upper.setText("10")
    assert dialog.params() == SequenceFill(0, 10)
    assert "Fills 6 of 6 cells: 0, 2, … 10" in dialog.note.text()
    dialog.step.setText("5")
    dialog.descending.setChecked(True)
    assert "Fills 3 of 6 cells: 10, 5, 0" in dialog.note.text()
    assert "3 cells stay unchanged" in dialog.note.text()
    dialog.step.setText("0")
    assert not ok_enabled(dialog)


def test_uniform_dialog(app):
    dialog = UniformDialog()
    assert not ok_enabled(dialog)
    dialog.value.setText("=A1+1")
    assert ok_enabled(dialog)
    assert dialog.params() == UniformFill("=A1+1")


def test_sequence_from_float_cells_stays_float(window):
    window.model.set_cell(0, 0, "1.0")
    window.model.set_cell(1, 0, "2.0")
    select(window, 0, 0, 4, 0)
    fill(window, "sequence")
    assert column(window, 0, range(5)) == ["1.0", "2.0", "3.0", "4.0", "5.0"]


def test_random_from_float_cells_is_float(window):
    window.model.set_cell(0, 0, "1.0")
    window.model.set_cell(1, 0, "6.0")
    select(window, 0, 0, 29, 0)
    fill(window, "random")
    values = column(window, 0, range(30))
    assert all("." in v and 1 <= float(v) <= 6 for v in values)
    assert any(not float(v).is_integer() for v in values)


def test_sequence_dialog_floats_from_typed_bounds(app):
    dialog = SequenceDialog(cell_count=3)
    dialog.lower.setText("1.0")
    dialog.upper.setText("3")
    assert dialog.params().floats
    assert "1.0, 2.0, 3.0" in dialog.note.text()
    dialog.lower.setText("1")
    assert not dialog.params().floats
    assert "1, 2, 3" in dialog.note.text()



# --- Letters ---

@pytest.mark.parametrize("params, count, expected", [
    (LetterSequence("A", "C"), 4, ["A", "B", "C", "A"]),               # starts over
    (LetterSequence("A", "C"), 2, ["A", "B"]),                         # as far as the cells go
    (LetterSequence("A", "C", descending=True), 4, ["C", "B", "A", "C"]),
    (LetterSequence("AY", "BB"), 4, ["AY", "AZ", "BA", "BB"]),         # rightmost letter fastest
    (LetterSequence("Y", "AB"), 4, ["Y", "Z", "AA", "AB"]),
    (LetterSequence("a", "e", step=2), 4, ["a", "c", "e", "a"]),
    (LetterSequence("a", "C"), 3, ["A", "B", "C"]),                    # mixed case: uppercase
])
def test_letter_sequence_values(params, count, expected):
    assert letter_sequence_values(params, count) == expected


def test_random_letters_inclusive():
    rng = np.random.default_rng(0)
    assert set(random_letters(RandomLetters("A", "D"), 300, rng)) == {"A", "B", "C", "D"}


def test_random_letter_strings_stay_between_bounds():
    rng = np.random.default_rng(0)
    values = random_letters(RandomLetters("BCD", "DCB"), 2000, rng)
    low, high = letter_index("BCD"), letter_index("DCB")
    assert all(low <= letter_index(v) <= high for v in values)
    assert "DCE" not in values and "ABC" not in values
    assert all(len(v) == 3 for v in values)
    assert len(set(values)) > 500


@pytest.mark.parametrize("mode, raw, expected", [
    ("uniform", ["Q", ""], UniformFill("Q")),
    ("sequence", ["A", "C"], LetterSequence("A", "C")),
    ("sequence", ["C", "A"], LetterSequence("A", "C", descending=True)),
    ("sequence", ["aa", "ad"], LetterSequence("aa", "ad")),
    ("sequence", ["B", "B"], UniformFill("B")),
    ("sequence", ["A", ""], None),
    ("sequence", ["A", "3"], None),
    ("random", ["BCD", ""], RandomPattern("BCD")),
    ("random", ["xy", ""], RandomPattern("xy")),
    ("random", ["D", "A"], RandomLetters("A", "D")),
    ("random", ["BCD", "DCB"], RandomLetters("BCD", "DCB")),
    ("random", ["A", "7"], None),
    ("random", ["ABCDEFGHIJK", ""], None),  # too long to be a letter bound
])
def test_infer_letters(mode, raw, expected):
    assert infer(MODES[mode], raw, raw, 4) == expected


def test_letter_sequence_example_from_cells(window):
    window.model.set_cell(0, 0, "A")
    window.model.set_cell(1, 0, "C")
    select(window, 0, 0, 3, 0)
    fill(window, "sequence")
    assert window.fill.dialogs.asked == []
    assert column(window, 0, range(4)) == ["A", "B", "C", "A"]


def test_letter_sequence_fewer_cells(window):
    window.model.set_cell(0, 0, "A")
    window.model.set_cell(0, 1, "C")
    select(window, 0, 0, 0, 1)
    fill(window, "sequence")
    assert [window.model.get_cell(0, c) for c in range(2)] == ["A", "B"]


def test_random_letters_from_one_cell(window):
    window.model.set_cell(0, 0, "BAD")
    select(window, 0, 0, 39, 0)
    fill(window, "random")
    assert window.fill.dialogs.asked == []
    values = column(window, 0, range(40))
    assert all(is_shaped_like(v, "BAD") for v in values)
    assert len(set(values)) > 20
    assert "shaped like BAD" in window.statusBar().currentMessage()


def test_random_letters_between_two_cells(window):
    window.model.set_cell(0, 0, "A")
    window.model.set_cell(1, 0, "D")
    select(window, 0, 0, 59, 0)
    fill(window, "random")
    assert set(column(window, 0, range(60))) == {"A", "B", "C", "D"}


def test_uniform_letters(window):
    window.model.set_cell(0, 0, "Total")
    select(window, 0, 0, 2, 0)
    fill(window, "uniform")
    assert column(window, 0, range(3)) == ["Total"] * 3


def test_random_dialog_letters(app):
    dialog = RandomDialog()
    dialog.lower.setText("BCD")
    dialog.upper.setText("DCB")
    assert dialog.params() == RandomLetters("BCD", "DCB")
    assert not dialog.integers.isEnabled()
    assert "letter strings from BCD to DCB" in dialog.note.text()
    dialog.upper.setText("7")
    assert dialog.params() is None
    assert "must both be numbers, or both letters" in dialog.note.text()
    dialog.lower.setText("D")
    dialog.upper.setText("A")
    assert dialog.params() is None
    assert "come before" in dialog.note.text()


def test_random_dialog_starts_from_letters(app):
    dialog = RandomDialog(initial=RandomLetters("A", "D"))
    assert (dialog.lower.text(), dialog.upper.text()) == ("A", "D")
    assert not dialog.floats.isEnabled()


def test_sequence_dialog_letters(app):
    dialog = SequenceDialog(cell_count=4)
    dialog.lower.setText("A")
    dialog.upper.setText("C")
    dialog.step.setText("")
    assert dialog.params() == LetterSequence("A", "C")
    assert dialog.note.text() == "Fills 4 cells: A, B, C, A. Starts over after C."
    dialog.step.setText("1.5")
    assert dialog.params() is None
    assert "whole number" in dialog.note.text()
    dialog.step.setText("2")
    dialog.descending.setChecked(True)
    assert dialog.params() == LetterSequence("A", "C", step=2, descending=True)
    assert "C, A, C, A" in dialog.note.text()


def test_letter_dialog_answer_fills_cells(window):
    window.fill.dialogs.answer = LetterSequence("X", "AA", across_first=True)
    select(window, 0, 0, 1, 1)
    fill(window, "sequence")
    assert [window.model.get_cell(0, c) for c in range(2)] == ["X", "Y"]
    assert [window.model.get_cell(1, c) for c in range(2)] == ["Z", "AA"]



VOWELS = set("AEIOUaeiou")


def is_shaped_like(value, template):
    return len(value) == len(template) and all(
        (v in VOWELS) == (t in VOWELS) and v.isupper() == t.isupper() and v.isalpha()
        for v, t in zip(value, template)
    )


def test_random_pattern_keeps_vowels_and_consonants():
    rng = np.random.default_rng(0)
    values = random_pattern(RandomPattern("BCDA"), 1000, rng)
    assert all(is_shaped_like(v, "BCDA") for v in values)
    assert {v[3] for v in values} == set("AEIOU")
    assert len({v[0] for v in values}) == 21  # every consonant, Y included
    assert "Y" in {v[0] for v in values}


def test_random_pattern_keeps_each_positions_case():
    rng = np.random.default_rng(0)
    values = random_pattern(RandomPattern("Bob"), 200, rng)
    assert all(is_shaped_like(v, "Bob") for v in values)
    assert all(v[0].isupper() and v[1:].islower() for v in values)


def test_random_pattern_without_keeping_uses_whole_alphabet():
    rng = np.random.default_rng(0)
    values = random_pattern(RandomPattern("BB", keep_vowels=False), 2000, rng)
    assert {v[0] for v in values} == set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def test_random_letter_range_is_not_a_pattern(window):
    window.model.set_cell(0, 0, "A")
    window.model.set_cell(1, 0, "D")
    select(window, 0, 0, 59, 0)
    fill(window, "random")
    assert set(column(window, 0, range(60))) == {"A", "B", "C", "D"}  # consonants too


def test_random_dialog_pattern(app):
    dialog = RandomDialog()
    dialog.lower.setText("Bob")
    dialog.upper.setText("")
    assert dialog.keep_vowels.isEnabled()
    assert not dialog.integers.isEnabled()
    assert dialog.params() == RandomPattern("Bob", True)
    assert "shaped like Bob" in dialog.note.text()
    dialog.keep_vowels.setChecked(False)
    assert dialog.params() == RandomPattern("Bob", False)
    assert "any letter" in dialog.note.text()
    dialog.upper.setText("Zed")
    assert not dialog.keep_vowels.isEnabled()  # a range isn't a pattern
    assert dialog.params() == RandomLetters("Bob", "Zed")


def test_random_dialog_starts_from_pattern(app):
    dialog = RandomDialog(initial=RandomPattern("abc", keep_vowels=False))
    assert (dialog.lower.text(), dialog.upper.text()) == ("abc", "")
    assert not dialog.keep_vowels.isChecked()


def test_random_dialog_checkbox_default(app):
    assert RandomDialog().keep_vowels.isChecked()
    assert not RandomDialog(keep_vowels=False).keep_vowels.isChecked()


def test_turning_pattern_off_in_dialog_applies_to_cells_later(window):
    window.fill.dialogs.answer = RandomPattern("BAD", keep_vowels=False)
    select(window, 0, 0, 2, 0)
    fill(window, "random")
    assert window.fill.keep_vowels is False

    window.model.set_cell(0, 2, "BB")
    select(window, 0, 2, 299, 2)
    fill(window, "random")
    first_letters = {v[0] for v in column(window, 2, range(300))}
    assert first_letters & set("AEIOU")  # vowels now appear where B was
    assert len(window.fill.dialogs.asked) == 1  # the second fill came from the cells

    window.fill.dialogs.answer = None
    select(window, 0, 4, 2, 4)
    fill(window, "random")
    assert window.fill.dialogs.keep_vowels is False  # the dialog opens with it unchecked


def test_edit_menu_has_fill(window):
    edit = [m for m in window.menuBar().actions() if m.text() == "Edit"][0].menu()
    fill_menu = [a for a in edit.actions() if a.text() == "Fill"][0].menu()
    assert fill_menu.actions() == list(window.fill_actions.values())  # the same actions
    assert [a.text() for a in fill_menu.actions()] == ["Random", "Sequence", "Uniform"]
    window.model.set_cell(0, 0, "7")
    select(window, 0, 0, 2, 0)
    fill_menu.actions()[2].trigger()  # Uniform
    assert column(window, 0, range(3)) == ["7"] * 3
    assert window.fill_button.text() == "Fill: Uniform"
    assert fill_menu.actions()[2].isChecked()


# --- Num. cells ---

def test_num_cells_disabled_with_a_selection(app):
    dialog = SequenceDialog(cell_count=6)
    assert not dialog.cells.isEnabled()
    assert dialog.cells.value() == 6
    dialog.lower.setText("1")
    dialog.upper.setText("6")
    assert dialog.params().cells is None  # the selection decides


def test_num_cells_with_one_cell(app):
    dialog = SequenceDialog(cell_count=1)
    assert dialog.cells.isEnabled()
    assert dialog.cells.value() == 10
    dialog.lower.setText("0")
    dialog.upper.setText("1")
    dialog.step.setText("")
    dialog.cells.setValue(5)
    assert dialog.params() == SequenceFill(0, 1, cells=5)
    assert dialog.note.text() == "Fills 5 of 5 cells: 0, 0.25, … 1"
    dialog.step.setText("0.5")
    assert "Fills 3 of 5 cells" in dialog.note.text()


def test_num_cells_remembered(app):
    dialog = SequenceDialog(initial=SequenceFill(1, 3, cells=3), cell_count=1)
    assert dialog.cells.value() == 3


def test_num_cells_for_letters(app):
    dialog = SequenceDialog(cell_count=1)
    dialog.lower.setText("A")
    dialog.upper.setText("C")
    dialog.step.setText("")
    dialog.cells.setValue(4)
    dialog.across_first.setChecked(True)
    assert dialog.params() == LetterSequence("A", "C", across_first=True, cells=4)
    assert dialog.note.text() == "Fills 4 cells: A, B, C, A. Starts over after C."


def test_num_cells_fills_down_from_one_cell(window):
    window.fill.dialogs.answer = SequenceFill(1, 5, cells=5)
    select(window, 2, 1, 2, 1)
    fill(window, "sequence")
    assert column(window, 1, range(2, 7)) == ["1", "2", "3", "4", "5"]
    assert window.model.get_cell(7, 1) == ""
    assert selected(window) == [(r, 1) for r in range(2, 7)]


def test_num_cells_fills_across_from_one_cell(window):
    window.fill.dialogs.answer = SequenceFill(10, 30, cells=3, across_first=True)
    select(window, 0, 0, 0, 0)
    fill(window, "sequence")
    assert [window.model.get_cell(0, c) for c in range(4)] == ["10", "20", "30", ""]
    assert window.model.get_cell(1, 0) == ""


def test_num_cells_letters_from_one_cell(window):
    window.fill.dialogs.answer = LetterSequence("A", "C", cells=4)
    select(window, 0, 3, 0, 3)
    fill(window, "sequence")
    assert column(window, 3, range(4)) == ["A", "B", "C", "A"]


def test_num_cells_grows_the_sheet(window):
    model = window.model
    window.fill.dialogs.answer = SequenceFill(1, 20, cells=20)
    last = model.rowCount() - 1
    select(window, last - 4, 0, last - 4, 0)
    fill(window, "sequence")
    assert model.rowCount() == last - 4 + 20
    assert model.get_cell(model.rowCount() - 1, 0) == "20"


def test_num_cells_is_one_undo_step(window):
    window.fill.dialogs.answer = SequenceFill(1, 4, cells=4)
    select(window, 0, 0, 0, 0)
    fill(window, "sequence")
    window.undo_action.trigger()
    assert window.model.sheet_data().cells == {}


def selected(window):
    return sorted((i.row(), i.column()) for i in window.view.selectedIndexes())


def test_sequence_of_typed_dates(window):
    window.model.set_cell(0, 0, "1/30/2024")
    window.model.set_cell(1, 0, "1/31/2024")
    select(window, 0, 0, 3, 0)
    fill(window, "sequence")
    assert column(window, 0, range(4)) == ["1/30/2024", "1/31/2024", "2/1/2024", "2/2/2024"]
    assert window.model.value(3, 0) == window.model.value(0, 0) + 3
