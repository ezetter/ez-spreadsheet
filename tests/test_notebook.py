import base64
import json
import math
import time

import pandas as pd
import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Qt, Signal
from PySide6.QtGui import QImage, QTextDocument, QTextTable
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolBar, QWidget

from py_spread.model import SheetModel
from py_spread.notebook import (
    Notebook,
    NotebookFormatError,
    cells_from_json,
    data_block,
    dataframe_code,
    next_frame_name,
)
from py_spread.notebook_window import NotebookWindow, OutputView
from py_spread.storage import SheetData, SheetFileError, load_sheet, save_sheet
from py_spread.window import MainWindow


def block(top, left, bottom, right):
    return {(r, c) for r in range(top, bottom + 1) for c in range(left, right + 1)}


def frame(code: str, name: str = "df") -> pd.DataFrame:
    namespace = {}
    exec(code, namespace)  # the generated cell, run as the kernel would
    return namespace[name]


@pytest.fixture
def sheet(app):
    model = SheetModel(rows=30, cols=8)
    model.set_cells({
        (0, 0): "Month", (0, 1): "Sales", (0, 2): "Note",
        (1, 0): "Jan", (1, 1): "$1,200", (1, 2): 'say "hi"',
        (2, 0): "Feb", (2, 1): "1450.5",
        (3, 0): "Mar", (3, 1): "=1/0", (3, 2): "x",
    })
    return model


# --- The generated DataFrame code ---

def test_header_row_names_columns(sheet):
    code = dataframe_code(sheet, block(0, 0, 3, 2))
    assert code.startswith("import pandas as pd\n\n# Cells A1:C4 of the sheet, with row 1 as the column names.")
    assert code.endswith("\ndf")
    df = frame(code)
    assert list(df.columns) == ["Month", "Sales", "Note"]
    assert list(df["Month"]) == ["Jan", "Feb", "Mar"]
    assert df["Sales"].tolist()[:2] == [1200, 1450.5]  # $1,200 is a number
    assert math.isnan(df["Sales"][2])  # the error cell is missing
    assert df["Note"][0] == 'say "hi"' and pd.isna(df["Note"][1])


def test_no_header_uses_letters(app):
    model = SheetModel(rows=10, cols=6)
    model.set_cells({(0, 1): "1", (1, 1): "2", (0, 2): "3", (1, 2): "4"})
    df = frame(dataframe_code(model, block(0, 1, 1, 2)))
    assert list(df.columns) == ["B", "C"]
    assert df["B"].dtype == "int64" and df["C"].tolist() == [3, 4]


def test_column_names_label_columns(app):
    model = SheetModel(rows=10, cols=6)
    model.set_cells({(0, 2): "1.5", (1, 2): "2"})
    model.name_column(2, "t")
    df = frame(dataframe_code(model, block(0, 2, 1, 2)))
    assert list(df.columns) == ["t"] and df["t"].tolist() == [1.5, 2.0]


def test_duplicate_and_blank_headers(app):
    model = SheetModel(rows=10, cols=6)
    model.set_cells({(0, 0): "x", (0, 1): "x", (1, 0): "1", (1, 1): "2", (1, 2): "3"})
    df = frame(dataframe_code(model, block(0, 0, 1, 2)))
    assert list(df.columns) == ["x", "x (B)", "C"]


def test_single_row_is_data_not_header(app):
    model = SheetModel(rows=10, cols=6)
    model.set_cells({(0, 0): "a", (0, 1): "b"})
    df = frame(dataframe_code(model, block(0, 0, 0, 1)))
    assert list(df.columns) == ["A", "B"] and df.iloc[0].tolist() == ["a", "b"]


def test_scattered_selection(sheet):
    cells = block(0, 0, 3, 0) | block(0, 2, 3, 2)  # columns A and C
    df = frame(dataframe_code(sheet, cells))
    assert list(df.columns) == ["Month", "Note"]


def test_data_block_trims_empty_edges(sheet):
    whole_columns = block(0, 0, 29, 3)  # A:D clicked in the column headers
    assert data_block(sheet, whole_columns) == block(0, 0, 3, 2)
    assert data_block(sheet, block(5, 0, 9, 3)) == set()
    scattered = block(0, 0, 29, 0) | block(0, 2, 29, 2)
    assert data_block(sheet, scattered) == block(0, 0, 3, 0) | block(0, 2, 3, 2)


def test_frame_names(app):
    notebook = Notebook()
    assert next_frame_name(notebook) == "df"
    notebook.add_cell("df = 1")
    assert next_frame_name(notebook) == "df2"
    notebook.add_cell("x = 2\ndf2 = 3\ndf3 == df2")  # a comparison isn't an assignment
    assert next_frame_name(notebook) == "df3"


# --- The notebook ---

def test_notebook_cells(app):
    notebook = Notebook()
    changes = []
    notebook.changed.connect(lambda: changes.append(1))
    a = notebook.add_cell("a = 1")
    b = notebook.add_cell("b = 2", 0)
    assert [c.source for c in notebook.cells] == ["b = 2", "a = 1"]
    notebook.move_cell(b.id, 1)
    assert [c.id for c in notebook.cells] == [a.id, b.id]
    notebook.add_output(a.id, {"output_type": "stream", "name": "stdout", "text": "x"})
    notebook.add_output(a.id, {"output_type": "clear_output"})
    assert notebook.cell(a.id).outputs == []
    notebook.remove_cell(b.id)
    assert len(notebook.cells) == 1 and len(changes) == 6


def test_printed_text_is_one_output_per_stream(app):
    notebook = Notebook()
    cell = notebook.add_cell()
    for name, text in (("stdout", "a\n"), ("stdout", ["b\n", "c\n"]), ("stderr", "oops\n"), ("stdout", "d\n")):
        notebook.add_output(cell.id, {"output_type": "stream", "name": name, "text": text})
    notebook.add_output(cell.id, {"output_type": "display_data", "data": {"text/plain": "x"}, "metadata": {}})
    notebook.add_output(cell.id, {"output_type": "stream", "name": "stdout", "text": "e\n"})
    assert [(o["output_type"], o.get("text")) for o in cell.outputs] == [
        ("stream", "a\nb\nc\n"), ("stream", "oops\n"), ("stream", "d\n"), ("display_data", None), ("stream", "e\n")]


def test_notebook_is_a_jupyter_document(app):
    notebook = Notebook()
    cell = notebook.add_cell("print(1)")
    notebook.add_output(cell.id, {"output_type": "stream", "name": "stdout", "text": "1\n"})
    notebook.set_execution_count(cell.id, 1)
    document = notebook.to_json()
    assert document["nbformat"] == 4 and document["metadata"]["kernelspec"]["name"] == "python3"
    assert document["cells"][0] == {"cell_type": "code", "id": cell.id, "metadata": {},
                                    "source": "print(1)", "execution_count": 1,
                                    "outputs": [{"output_type": "stream", "name": "stdout", "text": "1\n"}]}
    other = Notebook()
    other.load(json.loads(json.dumps(document)))
    assert other.to_json() == document


def test_loads_list_sources(app):
    cells = cells_from_json({"cells": [{"cell_type": "code", "source": ["a = 1\n", "a"], "outputs": []}]})
    assert cells[0].source == "a = 1\na"


@pytest.mark.parametrize("document", [
    [], {"cells": "x"}, {"cells": [{"cell_type": "markdown", "source": ""}]},
    {"cells": [{"cell_type": "code", "source": 5}]},
    {"cells": [{"cell_type": "code", "source": "", "execution_count": "1"}]},
    {"cells": [{"cell_type": "code", "id": "a", "source": ""}, {"cell_type": "code", "id": "a", "source": ""}]},
])
def test_bad_notebooks(document):
    with pytest.raises(NotebookFormatError):
        cells_from_json(document)


def test_saved_with_the_sheet(tmp_path, app):
    notebook = Notebook()
    notebook.add_cell("x = 1")
    path = str(tmp_path / "s.ezs")
    save_sheet(path, SheetData(10, 5, notebook=notebook.to_json()))
    assert load_sheet(path).notebook == notebook.to_json()
    save_sheet(path, SheetData(10, 5))
    assert "notebook" not in json.loads(open(path).read()) and load_sheet(path).notebook is None


def test_damaged_notebook_in_file(tmp_path):
    path = tmp_path / "bad.ezs"
    path.write_text(json.dumps({"format": "ezsheet", "version": 7, "rows": 10, "columns": 5,
                                "cells": {}, "notebook": {"cells": 3}}))
    with pytest.raises(SheetFileError, match="damaged"):
        load_sheet(str(path))


# --- Showing outputs ---

def png() -> str:
    image = QImage(40, 20, QImage.Format_RGB32)
    image.fill(0x336699)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return base64.b64encode(bytes(data)).decode()


def test_output_view(app):
    parent = QWidget()  # never shown, so the view isn't a window of its own
    view = OutputView(parent)
    view.show_outputs([
        {"output_type": "stream", "name": "stdout", "text": "hello <world>\n"},
        {"output_type": "execute_result", "data": {"text/html": "<table><tr><td>42</td></tr></table>",
                                                   "text/plain": "42"}, "execution_count": 1},
        {"output_type": "display_data", "data": {"image/png": png(), "text/plain": "<Figure>"}},
        {"output_type": "error", "ename": "ZeroDivisionError", "evalue": "division by zero",
         "traceback": ["\x1b[31mZeroDivisionError\x1b[39m: division by zero"]},
    ])
    text = view.toPlainText()
    assert "hello <world>" in text and "42" in text
    assert "ZeroDivisionError: division by zero" in text and "\x1b" not in text
    assert "<Figure>" not in text  # the image is shown instead of its text
    assert not view.document().resource(QTextDocument.ImageResource, "output:image2").isNull()
    assert not view.isHidden()
    view.show_outputs([])
    assert view.isHidden() and view.toPlainText() == ""


def test_dataframes_look_like_jupyters(app):
    parent = QWidget()  # kept, or it's deleted along with the view
    view = OutputView(parent)
    frame_html = pd.DataFrame({"a": [1, 2]})._repr_html_()
    assert '<table border="1" class="dataframe">' in frame_html
    view.show_outputs([{"output_type": "execute_result", "data": {"text/html": frame_html}, "metadata": {},
                        "execution_count": 1}])
    table = next(frame for frame in view.document().rootFrame().childFrames()
                 if isinstance(frame, QTextTable))
    assert table.format().border() == 0  # no grid
    assert (table.rows(), table.columns()) == (3, 2)


def test_bad_image_shows_its_text(app):
    parent = QWidget()  # kept, or it's deleted along with the view
    view = OutputView(parent)
    view.show_outputs([{"output_type": "display_data", "metadata": {},
                        "data": {"image/png": "not base64!", "text/plain": "<Figure>"}}])
    assert "<Figure>" in view.toPlainText()


# --- In the window, with a stand-in kernel ---

class FakeKernel(QObject):
    state_changed = Signal(str)
    started = Signal(str, int)
    output = Signal(str, dict)
    finished = Signal(str, object, str)
    cancelled = Signal(str)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.runs, self.interrupts, self.restarts, self.shutdowns = [], 0, 0, 0
        self.has_kernel, self.working_dir, self.count = False, None, 0

    def run(self, cell_id, code):
        self.runs.append((cell_id, code))
        self.count += 1
        self.output.emit(cell_id, {"output_type": "execute_result", "metadata": {},
                                   "data": {"text/plain": f"result {self.count}"}, "execution_count": self.count})
        self.finished.emit(cell_id, self.count, "ok")

    def interrupt(self):
        self.interrupts += 1

    def restart(self):
        self.restarts += 1

    def shutdown(self, timeout=5.0):
        self.shutdowns += 1


@pytest.fixture
def window(app, sheet):
    window = MainWindow()
    window.kernel = FakeKernel()
    window.model.set_cells({key: sheet.get_cell(*key) for key in block(0, 0, 3, 2)})
    window.show()
    yield window
    if window.notebook_window is not None:
        window.notebook_window.hide()
    window.setWindowModified(False)
    window.close()


def test_send_to_notebook(window):
    window.view.select_range(0, 0, 3, 2)
    cell_id = window.send_to_notebook()
    notebook_window = window.notebook_window
    assert notebook_window.isVisible()
    assert window.kernel.runs == [(cell_id, window.notebook.cell(cell_id).source)]
    assert "df = pd.DataFrame({" in window.notebook.cell(cell_id).source
    assert window.notebook.cell(cell_id).execution_count == 1
    widget = notebook_window.widgets[cell_id]
    assert widget.prompt.text() == "[1]:" and "result 1" in widget.output_view.toPlainText()
    assert window.isWindowModified()
    assert "as df" in window.statusBar().currentMessage()


def test_whole_columns_send_just_their_data(window):
    window.view.select_range(0, 0, window.model.rowCount() - 1, 4)  # columns A to E
    cell_id = window.send_to_notebook()
    source = window.notebook.cell(cell_id).source
    assert "# Cells A1:C4 of the sheet" in source
    df = frame(source)
    assert df.shape == (3, 3)


def test_empty_selection_makes_nothing(window):
    window.view.select_range(10, 0, 12, 2)
    assert window.send_to_notebook() is None
    assert window.notebook.is_empty and window.notebook_window is None
    assert "empty" in window.statusBar().currentMessage()


def test_second_selection_appends_df2(window):
    window.view.select_range(0, 0, 3, 0)
    window.send_to_notebook()
    window.notebook_window.set_current(window.notebook.cells[0].id)
    window.view.select_range(0, 1, 3, 1)
    second = window.send_to_notebook()
    assert window.notebook.cells[-1].id == second  # new data goes at the end
    assert "df2 = pd.DataFrame" in window.notebook.cell(second).source


def test_tool_in_toolbar_menus_and_context_menu(window):
    toolbar = window.findChild(QToolBar)
    assert window.notebook_action in toolbar.actions()
    insert = [m for m in window.menuBar().actions() if m.text() == "Insert"][0].menu()
    assert window.notebook_action in insert.actions()
    assert window.notebook_action in window.context_menu.actions()
    view_menu = [m for m in window.menuBar().actions() if m.text() == "View"][0].menu()
    assert window.show_notebook_action in view_menu.actions()


def test_notebook_saved_and_opened_with_sheet(window, tmp_path):
    window.view.select_range(0, 0, 3, 2)
    window.send_to_notebook()
    path = str(tmp_path / "s.ezs")
    assert window.save_to(path)
    assert not window.isWindowModified()
    assert window.notebook_window.windowTitle() == "Notebook — s.ezs"
    other = MainWindow()
    other.kernel = FakeKernel()
    other.open_path(path)
    assert [c.source for c in other.notebook.cells] == [c.source for c in window.notebook.cells]
    assert other.notebook.cells[0].outputs  # outputs are kept, like Jupyter
    assert other.kernel.runs == []  # opening runs nothing
    assert other.kernel.shutdowns == 1  # the previous sheet's kernel was stopped
    other.setWindowModified(False)


def test_editing_notebook_marks_sheet_modified(window, tmp_path):
    window.save_to(str(tmp_path / "s.ezs"))
    nb = window.show_notebook()
    nb.add_cell_below("x = 1")
    assert window.isWindowModified()
    window.save_to(str(tmp_path / "s.ezs"))
    window.model.set_cell(9, 0, "a")
    window.model.undo_stack.undo()  # back to the saved sheet...
    assert not window.isWindowModified()
    nb.widgets[nb.current_id].editor.setPlainText("x = 2")
    window.model.set_cell(9, 0, "a")
    window.model.undo_stack.undo()
    assert window.isWindowModified()  # ...but the notebook still has changes


def test_shift_return_runs_and_moves_on(window):
    nb = window.show_notebook()
    first = nb.add_cell_below("1 + 1")
    QTest.keyClick(nb.widgets[first].editor, Qt.Key_Return, Qt.ShiftModifier)
    assert window.kernel.runs[-1] == (first, "1 + 1")
    assert len(window.notebook.cells) == 2 and nb.current_id == window.notebook.cells[1].id
    QTest.keyClick(nb.widgets[first].editor, Qt.Key_Return, Qt.ControlModifier)  # run in place
    assert window.kernel.runs[-1][0] == first and len(window.notebook.cells) == 2


def test_editor_indents(window):
    nb = window.show_notebook()
    cell = nb.add_cell_below()
    editor = nb.widgets[cell].editor
    QTest.keyClicks(editor, "for i in range(3):")
    QTest.keyClick(editor, Qt.Key_Return)
    QTest.keyClicks(editor, "print(i)")
    assert window.notebook.cell(cell).source == "for i in range(3):\n    print(i)"


def test_toolbar_commands(window):
    nb = window.show_notebook()
    a = nb.add_cell_below("a")
    b = nb.add_cell_below("b")
    nb.actions_by_name["Run All"].trigger()
    assert [run[0] for run in window.kernel.runs] == [a, b]
    nb.actions_by_name["↑"].trigger()
    assert [c.id for c in window.notebook.cells] == [b, a]
    nb.actions_by_name["Interrupt"].trigger()
    nb.actions_by_name["Restart"].trigger()
    assert (window.kernel.interrupts, window.kernel.restarts) == (1, 1)
    nb.actions_by_name["Delete"].trigger()
    assert [c.id for c in window.notebook.cells] == [a]


def test_kernel_status_and_problems(window):
    nb = window.show_notebook()
    assert nb.status.text() == "Python: stopped"
    window.kernel.state_changed.emit("busy")
    assert nb.status.text() == "Python: running"
    window.kernel.failed.emit("The Python kernel couldn't start: no ipykernel")
    assert not nb.problem.isHidden() and "no ipykernel" in nb.problem.text()
    window.kernel.state_changed.emit("starting")
    assert nb.problem.isHidden() and nb.status.text() == "Starting Python…"
    cell = nb.add_cell_below("x")
    nb.running.add(cell)  # as if waiting its turn
    nb._on_cell_updated(cell)
    assert nb.widgets[cell].prompt.text() == "[*]:"
    window.kernel.cancelled.emit(cell)  # Interrupt dropped it
    assert nb.widgets[cell].prompt.text() == "[ ]:" and not nb.running


def test_closing_notebook_hides_it(window):
    nb = window.show_notebook()
    nb.add_cell_below("x")
    assert nb.close()  # accepted, so it never holds up quitting
    assert not nb.isVisible() and window.show_notebook() is nb and len(window.notebook.cells) == 1


def test_closing_sheet_stops_kernel_and_hides_notebook(app):
    window = MainWindow()
    window.kernel = FakeKernel()
    window.show()
    nb = window.show_notebook()
    window.close()
    assert window.kernel.shutdowns == 1 and not nb.isVisible()


def test_kernel_starts_in_sheets_folder(app, tmp_path):
    window = MainWindow()
    window.save_to(str(tmp_path / "s.ezs"))
    assert window.kernel.working_dir == str(tmp_path)
    window.setWindowModified(False)


# --- With a real kernel ---

def wait_for(predicate, timeout=60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_real_kernel_runs_the_dataframe(app, sheet):
    window = MainWindow()
    window.model.set_cells({key: sheet.get_cell(*key) for key in block(0, 0, 3, 2)})
    try:
        window.view.select_range(0, 0, 3, 2)
        cell_id = window.send_to_notebook()
        cell = window.notebook.cell(cell_id)
        assert wait_for(lambda: cell.execution_count is not None)
        html = "".join(o.get("data", {}).get("text/html", "") for o in cell.outputs)
        assert "<table" in html and "Month" in html and "1200.0" in html
        nb = window.notebook_window
        follow = nb.add_cell_below("print(df['Sales'].sum())\ndf.shape")
        nb.run_cell(follow)
        assert wait_for(lambda: window.notebook.cell(follow).execution_count is not None)
        outputs = window.notebook.cell(follow).outputs
        assert outputs[0]["text"] == "2650.5\n" and outputs[1]["data"]["text/plain"] == "(3, 3)"
    finally:
        if window.notebook_window is not None:
            window.notebook_window.hide()
        window.setWindowModified(False)
        window.close()
    assert not window.kernel.has_kernel


def test_real_kernel_errors_interrupt_and_restart(app):
    from py_spread.kernel import KernelRunner
    runner = KernelRunner()
    notebook = Notebook()
    nb = NotebookWindow(notebook, runner)
    try:
        bad = nb.add_cell_below("1/0")
        after = nb.add_cell_below("print('not run')")
        nb.run_all()
        assert wait_for(lambda: bad not in nb.running and after not in nb.running)
        assert notebook.cell(bad).outputs[-1]["ename"] == "ZeroDivisionError"
        assert notebook.cell(after).outputs == []  # stopped at the error, like Jupyter
        loop = nb.add_cell_below("import time\nx = 1\nwhile True: time.sleep(0.05)")
        nb.run_cell(loop)
        assert wait_for(lambda: nb.status.text() == "Python: running")
        nb.interrupt()
        assert wait_for(lambda: loop not in nb.running)
        assert notebook.cell(loop).outputs[-1]["ename"] == "KeyboardInterrupt"
        nb.restart()
        check = nb.add_cell_below("x")
        nb.run_cell(check)
        assert wait_for(lambda: check not in nb.running)
        assert notebook.cell(check).outputs[-1]["ename"] == "NameError"  # restarting forgot x
    finally:
        runner.shutdown()
    assert not runner.has_kernel
