import pytest
from PySide6.QtWidgets import QFormLayout

from py_spread.frame_name_dialog import FrameNameDialog, FrameNameField
from py_spread.graph_dialog import GraphDialog
from py_spread.graphs import GraphCell, find_graphs
from py_spread.notebook import FrameData, GraphColumns, Notebook, assigned_names, frame_name_problem
from py_spread.window import MainWindow
from tests.test_notebook import FakeKernel


# --- The names ---

@pytest.mark.parametrize("name", ["sales", "df2", "Sales_2024", "données", "match"])  # (match: a soft keyword)
def test_good_names(name):
    assert frame_name_problem(name) is None


@pytest.mark.parametrize("name, problem", [
    ("", "needs a name"), ("2024", "can't start with a digit"), ("my sales", "letters, digits, and _"),
    ("sales-2", "letters, digits, and _"), ("class", "keywords"), ("_sales", "starting with _"),
    ("pd", "EzSheet's code uses it"), ("data", "EzSheet's code uses it"), ("chart", "EzSheet's code uses it"),
    ("Out", "the notebook's Python uses it"), ("list", "built-in"), ("sum", "built-in"),
])
def test_names_that_wont_do(name, problem):
    assert problem in frame_name_problem(name)


def test_assigned_names(app):
    notebook = Notebook()
    notebook.add_cell("import pandas as pd\nsales = pd.DataFrame({})\nsales")
    notebook.add_cell("total = 1\nx == 2\n    indented = 3")
    assert assigned_names(notebook) == {"sales", "total"}


# --- The DataFrame dialog ---

def test_dataframe_dialog(app):
    dialog = FrameNameDialog(None, "df2", "the selected cells, A1:C4", {"df", "sales"})
    assert dialog.windowTitle() == "DataFrame" and dialog.name() == "df2"
    assert dialog.field.edit.selectedText() == "df2"  # typing replaces it
    assert dialog.ok_button.isEnabled() and dialog.field.note.isHidden()
    dialog.field.edit.setText("  costs ")
    assert dialog.name() == "costs" and dialog.ok_button.isEnabled()
    dialog.field.edit.setText("2 costs")
    assert not dialog.ok_button.isEnabled() and "can't start with a digit" in dialog.field.note.text()
    assert not dialog.field.note.isHidden()
    dialog.field.edit.setText("sales")  # the notebook has one: fine, it's replaced
    assert dialog.ok_button.isEnabled() and "already sets sales" in dialog.field.note.text()


def test_field_showing_a_fixed_name(app):
    field = FrameNameField("df3", {"df"})
    field.set_fixed("df")
    assert not field.edit.isEnabled() and field.name() == "df" and field.problem() is None
    assert field.note.isHidden()  # not "already sets": it's that one
    field.set_fixed(None)
    assert field.edit.text() == "?" and field.problem() is None
    field.set_name("")
    assert field.edit.isEnabled() and field.problem() == "The DataFrame needs a name."


# --- The Chart dialog's name ---

def columns():
    return GraphColumns(["Month", "Sales", "Cost"], [False, True, True], [True, False, False])


def test_chart_dialog_name_at_the_top(app):
    dialog = GraphDialog(None, columns(), frame="df2", taken={"df"})
    assert dialog.form.itemAt(0, QFormLayout.FieldRole).widget() is dialog.name_field
    assert dialog.form.itemAt(0, QFormLayout.LabelRole).widget().text() == "DataFrame name:"
    assert dialog.choice().frame == "df2"
    dialog.name_field.edit.setText("sales")
    assert dialog.choice().frame == "sales" and dialog.ok_button.isEnabled()
    dialog.name_field.edit.setText("data")
    assert not dialog.ok_button.isEnabled() and "EzSheet's code uses it" in dialog.name_field.note.text()


def test_chart_dialog_name_for_a_chart_being_changed(app):
    graph = GraphCell("a", "line", None, "sales", "Month", ["Sales"], FrameData(["Month", "Sales", "Cost"], []),
                      columns())
    dialog = GraphDialog(None, columns(), graphs=[graph], current=None, frame="df", taken={"sales"})
    dialog.name_field.edit.setText("costs")
    dialog.graph_box.setCurrentIndex(1)  # the chart: its own DataFrame, shown
    assert dialog.name_field.edit.text() == "sales" and not dialog.name_field.edit.isEnabled()
    assert dialog.choice().frame is None and dialog.name_field.note.isHidden()
    dialog.graph_box.setCurrentIndex(0)  # New chart again: the name typed for it
    assert dialog.name_field.edit.isEnabled() and dialog.choice().frame == "costs"
    dialog.name_field.edit.setText("")
    assert not dialog.ok_button.isEnabled()
    dialog.graph_box.setCurrentIndex(1)  # a chart to change doesn't need it
    assert dialog.ok_button.isEnabled()


def test_chart_dialog_name_when_a_new_chart_cant_be_made(app):
    graph = GraphCell("a", "line", None, "df", "Month", ["Sales"])
    dialog = GraphDialog(None, None, graphs=[graph], current=None, new_source="the sheet",
                         new_problem="The sheet is empty.")
    assert not dialog.name_field.isEnabled() and not dialog.ok_button.isEnabled()
    dialog.graph_box.setCurrentIndex(1)
    assert dialog.name_field.isEnabled() and dialog.ok_button.isEnabled()


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.kernel = FakeKernel()
    window.model.set_cells({(0, 0): "Month", (0, 1): "Sales", (0, 2): "Cost", (1, 0): "Jan", (1, 1): "100",
                            (1, 2): "60", (2, 0): "Feb", (2, 1): "120", (2, 2): "70"})
    window.show()
    yield window
    if window.notebook_window is not None:
        window.notebook_window.hide()
    window.setWindowModified(False)
    window.close()


def test_naming_a_dataframe(window, dialogs):
    window.view.select_range(0, 0, 2, 2)
    dialogs.frame_name_answer = "sales"
    cell_id = window.send_to_notebook()
    assert dialogs.frame_name_prompts == [("df", "the selected cells, A1:C3")]
    source = window.notebook.cell(cell_id).source
    assert "sales = pd.DataFrame({" in source and source.endswith("\nsales")
    assert window.statusBar().currentMessage() == "Sent the selection to the notebook as sales."
    dialogs.frame_name_answer = None
    window.send_to_notebook()
    assert dialogs.frame_name_prompts[-1][0] == "df"  # sales isn't one of df, df2, ...: df is still free


def test_cancelling_the_dataframe_dialog(window, dialogs):
    window.view.select_range(0, 0, 2, 2)
    dialogs.frame_name_cancel = True
    assert window.send_to_notebook() is None
    assert len(dialogs.frame_name_prompts) == 1 and window.kernel.runs == []
    assert window.notebook_window is None or not window.notebook_window.isVisible()


def test_no_dialog_for_an_empty_selection(window, dialogs):
    window.view.select_range(5, 5, 6, 6)
    assert window.send_to_notebook() is None and dialogs.frame_name_prompts == []


def test_naming_a_charts_dataframe(window, dialogs):
    window.view.select_range(0, 0, 2, 2)
    dialogs.frame_name_answer = "sales"
    graph_id = window.send_graph_to_notebook()
    assert dialogs.frame_name_prompts == [("df", "the selected cells, A1:C3")]
    frame_cell, graph_cell = window.notebook.cells[-2:]
    assert "sales = pd.DataFrame({" in frame_cell.source and graph_cell.id == graph_id
    assert "# sales as a chart:" in graph_cell.source and "long = sales.melt(" in graph_cell.source  # All
    [graph] = find_graphs(window.notebook)
    assert graph.frame == "sales" and graph.data.labels == ["Month", "Sales", "Cost"]
    dialogs.frame_name_answer = None
    dialogs.graph_change_answer = (0, "line", None, "Month", ["Cost"])  # new columns: written afresh
    window.send_graph_to_notebook()
    assert "data=sales, x='Month', y='Cost'" in window.notebook.cell(graph_id).source
    assert dialogs.frame_name_prompts[-1] == ("df", "the selected cells, A1:C3")  # offered for a new one


def test_next_name_offered(window, dialogs):
    window.view.select_range(0, 0, 2, 2)
    window.send_to_notebook()  # df
    window.send_graph_to_notebook()
    assert [name for name, _source in dialogs.frame_name_prompts] == ["df", "df2"]
