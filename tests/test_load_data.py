import json
import time

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLabel

from ezsheet.load_data import (
    KERNEL_HELPERS,
    MAX_CELLS,
    answer,
    data_request,
    frames,
    frames_request,
    sheet_writes,
)
from ezsheet.load_data_dialog import LoadDataDialog
from ezsheet.window import MainWindow


def run_helpers(namespace: dict, expression: str) -> str:
    """Evaluate a request as the kernel would, giving the value's repr."""
    exec(KERNEL_HELPERS, namespace)
    return repr(eval(expression, namespace))


def frame_data(frame, **more):
    namespace = {"pd": pd, "frame": frame, **more}
    return answer(run_helpers(namespace, data_request("frame")[1]))


# --- In the notebook's Python ---

def test_lists_dataframes_only():
    namespace = {"df": pd.DataFrame({"a": [1, 2]}), "s": pd.Series([1]), "x": 3, "_hidden": pd.DataFrame(),
                 "wide": pd.DataFrame(np.zeros((4, 7)))}
    assert frames(run_helpers(namespace, frames_request()[1])) == [("df", 2, 1), ("wide", 4, 7)]


def test_no_pandas_no_dataframes():
    import sys
    namespace = {}
    exec(KERNEL_HELPERS, namespace)
    pandas = sys.modules.pop("pandas")
    try:
        assert frames(repr(eval("_ezsheet_frames()", namespace))) == []
    finally:
        sys.modules["pandas"] = pandas


def test_values():
    frame = pd.DataFrame({
        "n": [1, 2, None], "x": [1.5, np.nan, 1e-05], "t": ['say "hi"\nthere', None, "café"],
        "b": [True, False, True], "when": pd.to_datetime(["2024-01-02", None, "2024-03-04"]),
        "inf": [np.inf, 0.0, -1.0],
    })
    data = frame_data(frame)
    assert data["columns"] == ["n", "x", "t", "b", "when", "inf"]  # no index: it's just row numbers
    assert data["rows"] == [
        [1.0, 1.5, 'say "hi"\nthere', "True", "2024-01-02 00:00:00", "inf"],
        [2.0, None, None, "False", None, 0.0],
        [None, 1e-05, "café", "True", "2024-03-04 00:00:00", -1.0],
    ]


def test_meaningful_index_becomes_columns():
    sales = pd.DataFrame({"Month": ["Jan", "Jan", "Feb"], "Sales": [1, 2, 3]})
    by_month = sales.groupby("Month").sum()
    assert frame_data(by_month) == {"columns": ["Month", "Sales"], "rows": [["Feb", 3], ["Jan", 3]]}
    described = frame_data(sales.describe())
    assert described["columns"] == ["index", "Sales"] and described["rows"][0] == ["count", 3]
    filtered = frame_data(sales[sales.Sales > 1])  # row numbers 1 and 2: still just row numbers
    assert filtered == {"columns": ["Month", "Sales"], "rows": [["Jan", 2], ["Feb", 3]]}


def test_two_level_columns_and_a_clashing_index():
    frame = pd.DataFrame([[1, 2]], columns=pd.MultiIndex.from_tuples([("Sales", "Q1"), ("Sales", "Q2")]))
    assert frame_data(frame)["columns"] == ["Sales Q1", "Sales Q2"]
    clash = pd.DataFrame({"index": [5]}, index=pd.Index(["a"], name="index"))
    assert frame_data(clash) == {"columns": ["index", "index"], "rows": [["a", 5]]}


def test_writes_for_the_sheet():
    data = {"columns": ["Month", "Sales"], "rows": [["Jan", 1200.0], ["Feb", None], ["Mar", 1e-05]]}
    assert sheet_writes(data, 2, 1) == {
        (2, 1): "Month", (2, 2): "Sales", (3, 1): "Jan", (3, 2): "1200", (4, 1): "Feb", (4, 2): "",
        (5, 1): "Mar", (5, 2): "1e-05"}


def test_whats_in_the_columns():
    from ezsheet.load_data import columns_request, frame_columns
    namespace = {"pd": pd, "tips": pd.DataFrame({
        "bill": [1.5, 2.0], "size": [2, None], "day": pd.Categorical(["Sun", "Sat"]), "paid": [True, False],
        "note": [1, "a"]}), "unnamed": pd.DataFrame([[1]]), "twice": pd.DataFrame([[1, 2]], columns=["a", "a"])}
    found = frame_columns(run_helpers(namespace, columns_request(["tips", "unnamed", "twice", "gone"])[1]))
    tips = found["tips"]
    assert tips.labels == ["bill", "size", "day", "paid", "note"]
    assert tips.columns == [[1.5], [1, None], ["text"], [], [1, "text"]]  # numbers (whole?), text, missing
    assert found["unnamed"] == "Its column names aren't all text."
    assert found["twice"] == "Two of its columns have the same name."
    assert found["gone"] == "It's no longer in the notebook's Python."


def test_answer_survives_quotes_and_newlines():
    text = json.dumps({"columns": ["it's \"quoted\""], "rows": [["line\nbreak", "\\"]]})
    assert answer(repr(text)) == json.loads(text)


# --- The dialog ---

def test_dialog(app):
    dialog = LoadDataDialog(None, [("huge", MAX_CELLS, 2), ("df", 3, 2), ("df2", 1, 1)], "B3")
    texts = [dialog.list.item(i).text() for i in range(3)]
    assert texts == ["huge: 100,000 rows × 2 columns", "df: 3 rows × 2 columns", "df2: 1 row × 1 column"]
    assert dialog.chosen() == "df"  # the first that can be loaded
    assert not dialog.list.item(0).flags() & Qt.ItemIsEnabled and "Too big" in dialog.list.item(0).toolTip()
    dialog.list.setCurrentRow(2)
    assert dialog.chosen() == "df2"
    assert "starting at B3" in dialog.findChild(QLabel).text()


def test_dialog_with_only_huge_ones(app):
    dialog = LoadDataDialog(None, [("huge", MAX_CELLS + 1, 1)], "A1")
    assert dialog.chosen() is None
    assert not dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()


# --- In the window ---

class LocalKernel(QObject):
    """Stands in for the notebook's Python, running the questions here."""

    evaluated = Signal(str, object, str)
    state_changed = Signal(str)
    started = Signal(str, int)
    output = Signal(str, dict)
    finished = Signal(str, object, str)
    cancelled = Signal(str)
    failed = Signal(str)

    def __init__(self, namespace=None):
        super().__init__()
        self.namespace = {"pd": pd, **(namespace or {})}
        self.has_kernel = True
        self.working_dir = None
        self.questions = []

    def evaluate(self, request_id, code, expression):
        self.questions.append(expression)
        try:
            exec(code, self.namespace)
            value = repr(eval(expression, self.namespace))
        except Exception as e:  # noqa: BLE001 -- as the kernel reports it
            self.evaluated.emit(request_id, None, f"{type(e).__name__}: {e}")
            return
        self.evaluated.emit(request_id, value, "")

    def shutdown(self, timeout=5.0):
        pass


@pytest.fixture
def window(app):
    window = MainWindow()
    window.kernel = LocalKernel({"df": pd.DataFrame({"Month": ["Jan", "Feb"], "Sales": [1200, 1450.5]}),
                                 "totals": pd.DataFrame({"Sales": [2650.5]}, index=pd.Index(["all"], name="Span"))})
    window.model.set_cells({(2, 2): "old", (5, 5): "keep"})
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def test_load_a_dataframe_at_the_current_cell(window, dialogs):
    window.view.setCurrentIndex(window.model.index(2, 1))  # B3
    dialogs.load_answer = "df"
    window.load_data_action.trigger()
    [(offered, cell)] = dialogs.load_prompts
    assert offered == [("df", 2, 2), ("totals", 1, 1)] and cell == "B3"
    model = window.model
    assert [[model.get_cell(r, c) for c in (1, 2)] for r in (2, 3, 4)] == [
        ["Month", "Sales"], ["Jan", "1200"], ["Feb", "1450.5"]]
    assert model.value(4, 2) == 1450.5 and model.get_cell(5, 5) == "keep"
    assert window.view.selection_bounds() == (2, 1, 4, 2)
    assert window.statusBar().currentMessage() == (
        "Loaded df at B3: 2 rows × 2 columns, with its column names above.")
    assert window.undo_action.text() == "Undo Load Data"
    window.undo_action.trigger()
    assert model.get_cell(2, 2) == "old" and model.get_cell(3, 1) == ""


def test_named_index_comes_too(window, dialogs):
    dialogs.load_answer = "totals"
    window.load_data_to_sheet()
    assert [window.model.get_cell(r, c) for r in (0, 1) for c in (0, 1)] == ["Span", "Sales", "all", "2650.5"]


def test_cancel_loads_nothing(window, dialogs):
    window.load_data_to_sheet()
    assert len(dialogs.load_prompts) == 1 and window.model.get_cell(0, 0) == ""
    assert len(window.kernel.questions) == 1  # just the list


def test_nothing_to_run_and_python_not_running(window, dialogs):
    window.kernel.has_kernel = False
    window.load_data_to_sheet()
    assert "no DataFrames to load" in window.statusBar().currentMessage()
    assert dialogs.load_prompts == [] and window.kernel.questions == []


def test_no_dataframes(window, dialogs):
    window.kernel.namespace = {"x": 1}
    window.load_data_to_sheet()
    assert "no DataFrames" in window.statusBar().currentMessage() and dialogs.load_prompts == []


def test_dataframe_gone_by_then(window, dialogs):
    dialogs.load_answer = "df"
    original = window.kernel.evaluate

    def forget_then_evaluate(request_id, code, expression):
        if "_ezsheet_frame(" in expression:
            window.kernel.namespace.pop("df")  # say, the kernel restarted in between
        original(request_id, code, expression)

    window.kernel.evaluate = forget_then_evaluate
    window.load_data_to_sheet()
    assert dialogs.errors and "KeyError" in dialogs.errors[-1]
    assert window.model.get_cell(0, 0) == ""


def test_in_the_notebook_menus(window):
    from tests.test_notebook import notebook_submenu
    insert = [m for m in window.menuBar().actions() if m.text() == "Insert"][0].menu()
    for menu in (window.notebook_button.menu(), notebook_submenu(insert), notebook_submenu(window.context_menu)):
        assert window.load_data_action in menu.actions()


# --- With a real kernel ---

def wait_for(predicate, timeout=60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_real_kernel_loads_data(app, dialogs):
    window = MainWindow()
    try:
        nb = window.show_notebook()
        cell = nb.add_cell_below(
            "import pandas as pd\n"
            "sales = pd.DataFrame({'Month': ['Jan', 'Feb', 'Jan'], 'Sales': [1, 2.5, 3], 'Note': ['a\"b', None, 'é']})\n"
            "by_month = sales.groupby('Month')[['Sales']].sum()")
        nb.run_cell(cell)
        assert wait_for(lambda: cell in nb.ran)
        dialogs.load_answer = "by_month"
        window.view.setCurrentIndex(window.model.index(1, 1))
        window.load_data_to_sheet()
        assert wait_for(lambda: window.model.get_cell(1, 1) == "Month")
        model = window.model
        assert [[model.get_cell(r, c) for c in (1, 2)] for r in (1, 2, 3)] == [
            ["Month", "Sales"], ["Feb", "2.5"], ["Jan", "4"]]
        assert dialogs.load_prompts[0][0] == [("sales", 3, 3), ("by_month", 2, 1)]
        dialogs.load_answer = "sales"
        window.view.setCurrentIndex(window.model.index(10, 0))
        window.load_data_to_sheet()
        assert wait_for(lambda: model.get_cell(10, 0) == "Month")
        assert [model.get_cell(11, c) for c in range(3)] == ["Jan", "1", 'a"b'] and model.get_cell(13, 2) == "é"
        assert nb.widgets[cell].prompt.text() == "[2]:"  # after the imports; the questions didn't count
    finally:
        window.notebook_window.hide()
        window.setWindowModified(False)
        window.close()
    assert not window.kernel.has_kernel


def test_real_kernel_evaluate_without_a_kernel(app):
    from ezsheet.kernel import KernelRunner
    runner = KernelRunner()
    answers = []
    runner.evaluated.connect(lambda request_id, value, error: answers.append((request_id, value, error)))
    runner.evaluate("q", "", "1 + 1")
    assert wait_for(lambda: answers, timeout=5)
    assert answers == [("q", None, "Python isn't running.")] and not runner.has_kernel
    runner.shutdown()
