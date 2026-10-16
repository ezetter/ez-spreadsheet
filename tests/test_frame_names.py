import pandas as pd
import pytest
import seaborn as sns
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFormLayout

from py_spread.frame_name_dialog import FrameNameDialog, FrameNameField
from py_spread.graph_dialog import GraphDialog
from py_spread.graphs import (
    FrameCell,
    GraphCell,
    find_frames,
    find_graphs,
    frame_labels,
    dependent_cells,
    rename_frame,
    update_frame_code,
    used_names,
)
from py_spread.model import SheetModel
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


# --- Renaming one ---

FRAME_CELL = "# Cells A1:B3 of the sheet.\ndf = pd.DataFrame({\n    'a': [1, 2],\n    'b': [3, 4],\n})\ndf"
CHART_CELL = "# df as a chart: 'b' against 'a'.\nchart = sns.relplot(\n    data=df, x='a', y='b',\n)"


def notebook_of(*sources):
    notebook = Notebook()
    return notebook, [notebook.add_cell(source).id for source in sources]


def test_renames_the_dataframe_where_its_used(app):
    notebook, ids = notebook_of(
        "df = 0  # an older df", "print(df)", FRAME_CELL, CHART_CELL,
        "x = df.describe()\nprint(f'{df.shape} {x.df}')\nf(df=1)\ndf['c'] = df.a\ndf = df.dropna()",
        "def g(df):\n    return df\ndef h(n=df):\n    return df.head(n)\nsquare = lambda df: df ** 2",
        "print(df)")
    renamed, unread = rename_frame(notebook, ids[2], "df", "sales")
    assert set(renamed) == set(ids[2:]) and unread == []  # not the older df, before it
    assert renamed[ids[2]] == FRAME_CELL.replace("df =", "sales =").replace("\ndf", "\nsales")
    assert renamed[ids[3]] == CHART_CELL.replace("df", "sales")  # its comment too, which names it
    assert renamed[ids[4]] == ("x = sales.describe()\nprint(f'{sales.shape} {x.df}')\nf(df=1)\n"
                               "sales['c'] = sales.a\nsales = sales.dropna()")  # not x.df, or df=1
    assert renamed[ids[5]] == ("def g(df):\n    return df\ndef h(n=sales):\n    return sales.head(n)\n"
                               "square = lambda df: df ** 2")  # g's and the lambda's df are their own
    assert renamed[ids[6]] == "print(sales)"


def test_renaming_stops_at_another_dataframe_of_that_name(app):
    notebook, ids = notebook_of(FRAME_CELL, CHART_CELL, "print(df)\ndf = pd.read_csv('other.csv')\ndf",
                                "print(df)", FRAME_CELL)
    renamed, _unread = rename_frame(notebook, ids[0], "df", "sales")
    assert set(renamed) == set(ids[:3])
    assert renamed[ids[2]] == "print(sales)\ndf = pd.read_csv('other.csv')\ndf"
    for fresh in ("import numpy as df", "def df():\n    pass", "for df in frames:\n    pass",
                  "with open('x') as df:\n    pass", "a, df = 1, 2"):
        notebook, ids = notebook_of(FRAME_CELL, fresh, "print(df)")
        assert set(rename_frame(notebook, ids[0], "df", "sales")[0]) == {ids[0]}, fresh


def test_cells_using_the_dataframe(app):
    notebook, ids = notebook_of("print(df)", FRAME_CELL, CHART_CELL, "x = 1", "print(df.a)", "%timeit df.sum()",
                                "df = pd.read_csv('other.csv')", "print(df)")
    assert dependent_cells(notebook, ids[1], "df") == [ids[2], ids[4]]  # not before it, or past another df


def test_cells_using_whats_worked_out_from_it(app):
    notebook, ids = notebook_of(
        "import numpy as np\nimport pandas as pd\nresults = []", FRAME_CELL + "\nfirst = df.a[0]",
        "total = df.b.sum()", "print(total)", "doubled = total * 2", "print(doubled, np.pi)",
        "results.append(df.a.max())\nmerged = pd.concat([df])", "print(results)", "print(pd, np.e, len([]))",
        "def scaled(k):\n    return df.a * k", "print(scaled(2))", "print(first)",
        "total = 0", "print(total)", "chart.set(title='x')", "chart = sns.relplot(data=df, x='a', y='b')",
        "chart.figure", "def f(df):\n    return df\nprint(f(1))")
    expected = [2, 3, 4, 5, 6, 7, 9, 10, 11, 15, 16]  # not 8: pd and np aren't changed with it; nor 13 or 14
    assert dependent_cells(notebook, ids[1], "df") == [ids[i] for i in expected]


def test_dependents_end_where_its_set_afresh(app):
    notebook, ids = notebook_of(FRAME_CELL, "total = df.b.sum()", "df = pd.read_csv('x.csv')\ntotal = 1",
                                "print(df, total)")
    assert dependent_cells(notebook, ids[0], "df") == [ids[1]]
    notebook, ids = notebook_of(FRAME_CELL, "df = df.dropna()", "print(df)")
    assert dependent_cells(notebook, ids[0], "df") == [ids[1], ids[2]]  # still the same DataFrame


def test_cells_that_arent_plain_python(app):
    notebook, ids = notebook_of(FRAME_CELL, "%timeit df.sum()", "%matplotlib inline", "print(df)")
    renamed, unread = rename_frame(notebook, ids[0], "df", "sales")
    assert set(renamed) == {ids[0], ids[3]} and unread == [ids[1]]  # it mentions df; the other doesn't


def test_renaming_from_where_the_cell_makes_it(app):
    notebook, ids = notebook_of("print(df)\n" + FRAME_CELL)
    [source] = rename_frame(notebook, ids[0], "df", "sales")[0].values()
    assert source.startswith("print(df)\n") and "sales = pd.DataFrame" in source
    notebook, ids = notebook_of("x = 1")
    with pytest.raises(ValueError):
        rename_frame(notebook, ids[0], "df", "sales")


def test_used_names(app):
    notebook, _ids = notebook_of("import numpy as np\nimport os.path\nfrom math import tau\n"
                                 "def f(a, *rest, key=None):\n    return a\nclass C: pass\n"
                                 "try:\n    x = 1\nexcept ValueError as problem:\n    pass",
                                 "%timeit total(df)")
    assert {"np", "os", "tau", "f", "a", "rest", "key", "C", "x", "ValueError", "problem",
            "timeit", "total", "df"} <= used_names(notebook)
    assert "math" not in used_names(notebook)


# --- The notebook's DataFrames, and new data for one ---

def test_finds_the_dataframes(app):
    notebook, ids = notebook_of("import pandas as pd", FRAME_CELL, CHART_CELL, "other = pd.read_csv('x.csv')",
                                FRAME_CELL.replace("df", "sales"), "%timeit x")
    frames = find_frames(notebook)
    assert [(frame.cell_id, frame.name) for frame in frames] == [(ids[1], "df"), (ids[4], "sales")]
    assert frames[0].data.labels == ["a", "b"] and frames[0].data.columns == [[1, 2], [3, 4]]
    assert frame_labels(frames) == ["df: a, b (2 rows)", "sales: a, b (2 rows)"]


def test_frame_labels():
    wide = FrameData(list("abcdef"), [[1]] * 6)
    assert frame_labels([FrameCell("x", "df", wide), FrameCell("y", "df", wide)]) == [
        "df: a, b, c, d, … (1 row) (1)", "df: a, b, c, d, … (1 row) (2)"]


def test_update_frame_code(app):
    model = SheetModel(rows=10, cols=4)
    model.set_cells({(0, 0): "Month", (0, 1): "Sales", (1, 0): "Jan", (1, 1): "5", (2, 0): "Feb", (2, 1): "7"})
    source = "import pandas as pd\n\n" + FRAME_CELL + "\ndf['c'] = df.a * 2  # mine\ndf"
    updated = update_frame_code(source, "df", model, {(r, c) for r in range(3) for c in range(2)})
    assert updated == ("import pandas as pd\n\n# Cells A1:B3 of the sheet, with row 1 as the column names.\n"
                       "df = pd.DataFrame({\n    'Month': ['Jan', 'Feb'],\n    'Sales': [5, 7],\n})\ndf\n"
                       "df['c'] = df.a * 2  # mine\ndf")  # the rest stays


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


def two_frames():
    return [FrameCell("a", "df", FrameData(["x", "y"], [[1], [2]])),
            FrameCell("b", "sales", FrameData(["Month"], [["Jan", "Feb"]]))]


def test_dataframe_dialog_lists_the_dataframes(app):
    dialog = FrameNameDialog(None, "df2", "the whole sheet, A1:C3", {"df", "sales"}, two_frames(), None,
                             used={"df", "sales", "np"})
    assert [dialog.frame_box.itemText(i) for i in range(3)] == [
        "New DataFrame", "df: x, y (1 row)", "sales: Month (2 rows)"]
    assert dialog.chosen_frame() is None and dialog.name() == "df2"
    assert not dialog.form.isRowVisible(dialog.update_box) and not dialog.update()
    assert dialog.summary.text() == "A DataFrame of the whole sheet, A1:C3, in a new notebook cell."
    dialog.frame_box.setCurrentIndex(2)
    assert (dialog.chosen_frame(), dialog.name(), dialog.update()) == (1, "sales", False)
    assert dialog.form.isRowVisible(dialog.update_box) and not dialog.update_box.isChecked()  # unchecked
    assert dialog.update_box.text() == "Update its data from the whole sheet, A1:C3"
    dialog.update_box.setChecked(True)
    dialog.field.edit.setText("revenue")
    assert (dialog.name(), dialog.update()) == ("revenue", True)
    assert "Renames sales to revenue" in dialog.field.note.text() and dialog.ok_button.isEnabled()
    dialog.field.edit.setText("np")  # the notebook uses it
    assert not dialog.ok_button.isEnabled()
    dialog.frame_box.setCurrentIndex(0)
    assert dialog.name() == "df2" and not dialog.update()  # each keeps what was typed for it
    dialog.frame_box.setCurrentIndex(2)
    assert dialog.name() == "np"


def test_dataframe_dialog_without_data(app):
    dialog = FrameNameDialog(None, "df2", "the sheet", (), two_frames(), 0, "The sheet is empty.")
    assert dialog.chosen_frame() == 0 and dialog.ok_button.isEnabled()  # it can still be renamed
    assert not dialog.update_box.isEnabled() and dialog.update_box.toolTip() == "The sheet is empty."
    dialog.frame_box.setCurrentIndex(0)
    assert not dialog.ok_button.isEnabled()
    assert dialog.summary.text() == "A new DataFrame of the sheet can't be made. The sheet is empty."


def test_field_renaming(app):
    field = FrameNameField("df", {"df"}, used={"df", "np", "total"})
    field.set_renaming("df")
    assert field.edit.isEnabled() and field.note.isHidden() and field.problem() is None
    field.edit.setText("sales")
    assert field.problem() is None and field.note.text() == "Renames df to sales in the cells that use it."
    field.edit.setText("np")  # the notebook uses it: renaming df to it would clash
    assert "already uses np" in field.problem() and "already uses np" in field.note.text()
    field.edit.setText("df")
    assert field.problem() is None and field.note.isHidden()
    field.set_renaming("df", typed="costs")
    assert field.name() == "costs" and "Renames df to costs" in field.note.text()


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


def renamable_graph(frame="sales"):
    return GraphCell("a", "line", None, frame, "Month", ["Sales"], FrameData(["Month", "Sales", "Cost"], []),
                     columns(), frame_cell="frame-cell")


def test_chart_dialog_renaming_a_charts_dataframe(app):
    dialog = GraphDialog(None, columns(), graphs=[renamable_graph()], current=0, frame="df",
                         taken={"sales"}, used={"sales", "np"})
    field = dialog.name_field
    assert field.edit.isEnabled() and field.name() == "sales" and dialog.choice().frame == "sales"
    field.edit.setText("revenue")
    assert dialog.choice().frame == "revenue" and dialog.ok_button.isEnabled()
    assert "Renames sales to revenue" in field.note.text()
    dialog.graph_box.setCurrentIndex(0)  # New chart, and back: what was typed for each stays
    assert field.name() == "df" and field.renaming is None
    dialog.graph_box.setCurrentIndex(1)
    assert field.name() == "revenue" and field.renaming == "sales"
    field.edit.setText("np")
    assert not dialog.ok_button.isEnabled()


def test_chart_dialog_name_for_a_chart_that_cant_be_renamed(app):
    graph = renamable_graph()
    graph.data = None  # its DataFrame's cell isn't written as EzSheet writes it
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
    assert window.statusBar().currentMessage() == "Sent the selected cells, A1:C3 to the notebook as sales."
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


def chart_with_a_cell_using_it(window, dialogs) -> tuple[str, str, str]:
    """A chart of A1:C3 (df), and a cell after it using df: (the DataFrame's cell, the chart's, the other's)."""
    window.view.select_range(0, 0, 2, 2)
    graph_id = window.send_graph_to_notebook()
    frame_id = window.notebook.cells[-2].id
    other = window.notebook_window.add_cell_below("print(df.shape)")
    return frame_id, graph_id, other


def test_renaming_a_charts_dataframe(window, dialogs):
    frame_id, graph_id, other = chart_with_a_cell_using_it(window, dialogs)
    dialogs.rename_answer = "sales"
    dialogs.graph_change_answer = (0, "scatter", "o")  # the type too: just the kind changes in the code
    window.send_graph_to_notebook()
    notebook = window.notebook
    assert "sales = pd.DataFrame({" in notebook.cell(frame_id).source
    chart = notebook.cell(graph_id).source
    assert chart.startswith("# sales as a chart:") and "long = sales.melt(" in chart and "kind='scatter'" in chart
    assert notebook.cell(other).source == "print(sales.shape)"
    assert [run[0] for run in window.kernel.runs[-2:]] == [frame_id, graph_id]  # Python gets the new name first
    assert window.statusBar().currentMessage() == (
        "Renamed df to sales in 3 cells. Redrawing the chart sales: Sales and Cost against Month.")
    [graph] = find_graphs(notebook)
    assert (graph.frame, graph.frame_cell) == ("sales", frame_id) and graph.renamable
    window.notebook_window.widgets[other].editor.undo()  # each cell's change is an edit in it
    assert notebook.cell(other).source == "print(df.shape)"


def test_renaming_and_new_columns_at_once(window, dialogs):
    frame_id, graph_id, _other = chart_with_a_cell_using_it(window, dialogs)
    dialogs.rename_answer = "sales"
    dialogs.graph_change_answer = (0, "line", None, "Month", ["Cost"])  # written afresh, for sales
    window.send_graph_to_notebook()
    chart = window.notebook.cell(graph_id).source
    assert chart.startswith("# sales as a chart: 'Cost' against 'Month'.") and "data=sales, x='Month'" in chart


def test_keeping_the_name_renames_nothing(window, dialogs):
    frame_id, graph_id, other = chart_with_a_cell_using_it(window, dialogs)
    runs = len(window.kernel.runs)
    dialogs.rename_answer = "df"  # as the dialog gives it, unchanged
    dialogs.graph_change_answer = (0, "scatter", "o")
    window.send_graph_to_notebook()
    assert window.notebook.cell(other).source == "print(df.shape)"
    assert [run[0] for run in window.kernel.runs[runs:]] == [graph_id]  # the DataFrame's ran already
    assert window.statusBar().currentMessage().startswith("Redrawing the chart df:")


def test_renaming_with_a_cell_that_isnt_plain_python(window, dialogs):
    frame_id, graph_id, other = chart_with_a_cell_using_it(window, dialogs)
    magic = window.notebook_window.add_cell_below("%timeit df.sum()")
    dialogs.rename_answer = "sales"
    dialogs.graph_change_answer = (0, "line", None)
    window.send_graph_to_notebook()
    assert window.notebook.cell(magic).source == "%timeit df.sum()"
    assert window.statusBar().currentMessage().endswith(
        "1 cell using df couldn't be read as Python (such as one with a %magic), so it still says df.")


def test_dataframe_of_the_whole_sheet_with_no_selection(window, dialogs):
    window.view.setCurrentIndex(window.model.index(5, 5))
    cell_id = window.send_to_notebook()
    assert dialogs.frame_name_prompts == [("df", "the whole sheet, A1:C3")]
    assert window.notebook.cell(cell_id).source.startswith("# Cells A1:C3 of the sheet")


def test_no_dataframe_of_an_empty_sheet(app, dialogs):
    window = MainWindow()
    window.kernel = FakeKernel()
    assert window.send_to_notebook() is None and dialogs.frame_name_prompts == []
    assert "the sheet is empty" in window.statusBar().currentMessage()
    window.setWindowModified(False)
    window.close()


def dataframe_and_chart(window):
    """df of A1:C3, and a chart of it (df2) too: (df's cell, a cell using it, the chart's cell)."""
    window.view.select_range(0, 0, 2, 2)
    frame_id = window.send_to_notebook()
    other = window.notebook_window.add_cell_below("print(df.shape)")
    chart = window.send_graph_to_notebook()
    return frame_id, other, chart


def test_dataframe_dialog_offers_the_notebooks_dataframes(window, dialogs):
    frame_id, _other, _chart = dataframe_and_chart(window)
    window.send_to_notebook()
    frames, current, problem = dialogs.dataframe_prompts[-1]
    assert [frame.name for frame in frames] == ["df", "df2"] and current is None and problem is None
    window.notebook_window.set_current(frame_id)
    window.view.setCurrentIndex(window.model.index(0, 0))  # one cell: the notebook's current DataFrame
    window.send_to_notebook()
    assert dialogs.dataframe_prompts[-1][1] == 0


def test_renaming_from_the_dataframe_dialog(window, dialogs):
    frame_id, other, _chart = dataframe_and_chart(window)
    dialogs.dataframe_answer = (0, "sales", False)  # just a rename: just its cell runs again
    runs = len(window.kernel.runs)
    assert window.send_to_notebook() == frame_id
    assert "sales = pd.DataFrame({" in window.notebook.cell(frame_id).source
    assert window.notebook.cell(other).source == "print(sales.shape)"
    assert [run[0] for run in window.kernel.runs[runs:]] == [frame_id]  # Python gets the new name
    assert window.statusBar().currentMessage() == "Renamed df to sales in 2 cells."


def test_updating_a_dataframes_data(window, dialogs):
    window.view.select_range(0, 0, 2, 1)  # Month and Sales
    frame_id = window.send_graph_to_notebook()
    frame_id, chart = window.notebook.cells[-2].id, frame_id
    window.model.set_cells({(1, 1): "999", (3, 0): "Mar", (3, 1): "130", (3, 2): "80"})
    window.view.select_range(0, 0, 3, 1)
    dialogs.dataframe_answer = (0, None, True)
    runs = len(window.kernel.runs)
    window.send_to_notebook()
    source = window.notebook.cell(frame_id).source
    assert source.startswith("# Cells A1:B4 of the sheet") and "'Sales': [999, 120, 130]," in source
    assert [run[0] for run in window.kernel.runs[runs:]] == [frame_id, chart]  # and its chart is redrawn
    assert window.statusBar().currentMessage() == (
        "Updated df with the selected cells, A1:B4. Running the 1 cell depending on it again.")


def test_renaming_and_updating_at_once(window, dialogs):
    frame_id, other, _chart = dataframe_and_chart(window)
    window.view.setCurrentIndex(window.model.index(9, 9))  # no selection: the whole sheet
    dialogs.dataframe_answer = (0, "sales", True)
    runs = len(window.kernel.runs)
    window.send_to_notebook()
    source = window.notebook.cell(frame_id).source
    assert source.startswith("# Cells A1:C3 of the sheet") and "sales = pd.DataFrame({" in source
    assert window.notebook.cell(other).source == "print(sales.shape)"
    assert [run[0] for run in window.kernel.runs[runs:]] == [frame_id, other]  # not the chart: it's of df2
    assert window.statusBar().currentMessage() == (
        "Renamed df to sales in 2 cells. Updated sales with the whole sheet, A1:C3. "
        "Running the 1 cell depending on it again.")


def test_updating_runs_the_cells_using_it_again(window, dialogs):
    window.view.select_range(0, 0, 2, 2)
    frame_id = window.send_to_notebook()
    nb = window.notebook_window
    first = nb.add_cell_below("total = df.Sales.sum()")
    nb.add_cell_below("x = 1")
    second = nb.add_cell_below("print(total, df.shape)")
    third = nb.add_cell_below("print(total * 2)")  # just what's worked out from it
    nb.add_cell_below("df = pd.read_csv('other.csv')\ndf")
    nb.add_cell_below("print(df)")  # the other df
    dialogs.dataframe_answer = (0, None, True)
    runs = len(window.kernel.runs)
    window.send_to_notebook()
    assert [run[0] for run in window.kernel.runs[runs:]] == [frame_id, first, second, third]


def test_nothing_to_change(window, dialogs):
    frame_id, _other, _chart = dataframe_and_chart(window)
    dialogs.dataframe_answer = (0, None, False)
    assert window.send_to_notebook() is None
    assert window.statusBar().currentMessage() == "df is unchanged: give it a new name, or check Update data."


def test_renaming_with_no_data_to_update_from(window, dialogs):
    frame_id, _other, _chart = dataframe_and_chart(window)
    window.model.set_cells({(r, c): "" for r in range(3) for c in range(3)})
    window.view.setCurrentIndex(window.model.index(0, 0))
    dialogs.dataframe_answer = (0, "sales", False)
    window.send_to_notebook()
    assert dialogs.dataframe_prompts[-1][2] == "The sheet is empty."
    assert "sales = pd.DataFrame({" in window.notebook.cell(frame_id).source



# --- DataFrames of your own, from the notebook's Python ---

class RunningKernel(QObject):
    """Stands in for the notebook's Python, running cells and questions here, in one namespace."""

    evaluated = Signal(str, object, str)
    state_changed = Signal(str)
    started = Signal(str, int)
    output = Signal(str, dict)
    finished = Signal(str, object, str)
    cancelled = Signal(str)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.namespace = {}
        self.has_kernel, self.working_dir, self.count = False, None, 0
        self.runs, self.questions = [], []

    def run(self, cell_id, code):
        self.has_kernel = True
        self.runs.append(cell_id)
        self.count += 1
        try:
            exec(code, self.namespace)
        except Exception as e:  # noqa: BLE001 -- as the kernel reports it
            self.output.emit(cell_id, {"output_type": "error", "ename": type(e).__name__, "evalue": str(e),
                                       "traceback": []})
            self.finished.emit(cell_id, self.count, "error")
            return
        self.finished.emit(cell_id, self.count, "ok")

    def evaluate(self, request_id, code, expression):
        self.questions.append(expression)
        if not self.has_kernel:
            self.evaluated.emit(request_id, None, "Python isn't running.")
            return
        exec(code, self.namespace)
        self.evaluated.emit(request_id, repr(eval(expression, self.namespace)), "")

    def interrupt(self):
        pass

    def restart(self):
        pass

    def shutdown(self, timeout=5.0):
        pass


TIPS = pd.DataFrame({"total_bill": [16.99, 10.34], "tip": [1.01, 1.66], "day": ["Sun", "Sun"]})


@pytest.fixture
def tips_window(app, monkeypatch, tmp_path):
    """A sheet whose notebook loads the tips DataFrame by its own code, opened afresh: nothing's run."""
    monkeypatch.setattr(sns, "load_dataset", lambda name: TIPS.copy())  # (no download)
    window = MainWindow()
    window.notebook.load({"cells": [
        {"cell_type": "code", "source": "import pandas as pd\nimport seaborn as sns", "outputs": []},
        {"cell_type": "code", "source": "tips = sns.load_dataset('tips')\ntips.head()", "outputs": []},
        {"cell_type": "code", "source": "train, test = tips[:1], tips[1:]", "outputs": []},
        {"cell_type": "code", "source": "average = tips.tip.mean()", "outputs": []},
        {"cell_type": "code", "source": "print(average)", "outputs": []},
    ]})
    window.kernel = RunningKernel()
    window.model.set_cells({(0, 0): "total_bill", (0, 1): "tip", (1, 0): "20", (1, 1): "3",
                            (2, 0): "30", (2, 1): "5", (3, 0): "40", (3, 1): "6"})
    window.show()
    yield window
    if window.notebook_window is not None:
        window.notebook_window.hide()
    window.setWindowModified(False)
    window.close()


def test_dataframe_dialog_lists_your_own_dataframes(tips_window, dialogs):
    window = tips_window
    window.view.setCurrentIndex(window.model.index(0, 0))
    dialogs.frame_name_cancel = True
    window.send_to_notebook()
    assert len(window.kernel.runs) == 5  # the notebook ran first: it hadn't
    frames, current, problem = dialogs.dataframe_prompts[-1]
    assert [(frame.name, frame.shape, frame.updatable) for frame in frames] == [
        ("tips", (2, 3), True), ("train", (1, 3), False), ("test", (1, 3), False)]
    assert frames[0].code == "tips = sns.load_dataset('tips')"
    assert frame_labels(frames) == ["tips: 2 rows × 3 columns", "train: 1 row × 3 columns",
                                    "test: 1 row × 3 columns"]
    window.send_to_notebook()
    assert len(window.kernel.runs) == 5  # it's run now: not again


def test_renaming_your_own_dataframe(tips_window, dialogs):
    window = tips_window
    dialogs.dataframe_answer = (0, "restaurant", False)
    window.send_to_notebook()
    sources = [cell.source for cell in window.notebook.cells]
    assert sources[1] == "restaurant = sns.load_dataset('tips')\nrestaurant.head()"
    assert sources[2:4] == ["train, test = restaurant[:1], restaurant[1:]", "average = restaurant.tip.mean()"]
    assert "restaurant" in window.kernel.namespace


def test_updating_your_own_dataframe(tips_window, dialogs):
    window = tips_window
    window.view.select_range(0, 0, 3, 1)
    dialogs.dataframe_answer = (0, None, True)
    window.send_to_notebook()
    source = window.notebook.cells[1].source
    assert source.startswith("# Cells A1:B4 of the sheet, with row 1 as the column names.\ntips = pd.DataFrame({")
    assert source.endswith("})\ntips.head()") and "load_dataset" not in source
    assert list(window.kernel.namespace["tips"].tip) == [3, 5, 6]
    assert window.kernel.namespace["average"] == pytest.approx(14 / 3)  # what depends on it ran again
    assert window.statusBar().currentMessage() == (
        "Updated tips with the selected cells, A1:B4. Running the 3 cells depending on it again.")


def test_dataframe_dialog_for_your_own_dataframes(app):
    frames = [FrameCell("a", "tips", shape=(244, 7), code="tips = sns.load_dataset('tips')"),
              FrameCell("b", "train", shape=(10, 7), code="train, test = split(tips)", updatable=False)]
    dialog = FrameNameDialog(None, "df", "the whole sheet, A1:B4", (), frames, 0)
    assert "replaces tips = sns.load_dataset('tips') with the sheet's" in dialog.summary.text()
    assert dialog.update_box.isEnabled()
    dialog.frame_box.setCurrentIndex(2)
    assert not dialog.update_box.isEnabled() and "made along with others" in dialog.update_box.toolTip()


def test_load_data_runs_the_notebook_first(tips_window, dialogs):
    window = tips_window
    dialogs.load_answer = "tips"
    window.view.setCurrentIndex(window.model.index(10, 0))
    window.load_data_to_sheet()
    assert len(window.kernel.runs) == 5 and dialogs.load_prompts[0][0][0] == ("tips", 2, 3)
    assert window.model.get_cell(10, 0) == "total_bill" and window.model.get_cell(11, 2) == "Sun"


def test_python_that_cant_answer(window, dialogs):
    window.view.select_range(0, 0, 2, 2)
    window.send_to_notebook()  # FakeKernel can't evaluate: just the DataFrames the cells write out
    window.send_to_notebook()
    assert [frame.name for frame in dialogs.dataframe_prompts[-1][0]] == ["df"]
