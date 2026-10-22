import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from ezsheet.notebook import FACETED, GraphChoice
from ezsheet.window import MainWindow


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


class Dialogs:
    """Stands in for modal dialogs, which would block a test run."""

    def __init__(self):
        self.save_answer = QMessageBox.Discard
        self.save_prompts = 0
        self.errors = []
        self.insert_shift = "down"  # the Insert Cells dialog's answer; None cancels
        self.insert_problems = None  # the choices it was told to disable
        self.delete_shift = "up"  # likewise for the Delete Cells dialog
        self.delete_problems = None
        # The Graph dialog's (kind, marker), or (kind, marker, x, ys[, hue[, y_categories]]); None cancels. Columns
        # left out are the defaults (for a new graph) or the graph's own (when changing one).
        self.graph_answer = ("line", None)
        self.graph_prompts = []  # (the column labels, the choices it started with) each time it's shown
        # With charts in the notebook: (which, kind, marker[, x, ys[, hue[, y_categories[, col[, kde[, rug]]]]]]),
        # which being a chart's index or "new"; None cancels. (graph_answer likewise, without which.)
        self.graph_change_answer = None
        self.chart_prompts = []  # (the new chart's columns, what it's of, why it can't be made) each time
        self.graph_change_prompts = []  # (the graphs offered, the one it started with)
        self.load_answer = None  # Load Data to Sheet: the DataFrame's name; None cancels
        # The name typed for a new DataFrame, in the DataFrame dialog or for a new chart; None keeps the default.
        self.frame_name_answer = None
        self.frame_name_cancel = False  # the DataFrame dialog's Cancel
        self.rename_answer = None  # a new name typed for a chart's DataFrame, when changing it; None keeps it
        self.frame_name_prompts = []  # (the name it started at, what it's of) each time either asks
        # The DataFrame dialog, with DataFrames in the notebook: (which, name, update data), which being a
        # DataFrame's index or "new", and a name of None keeping the default or its own; None: as it starts.
        self.dataframe_answer = None
        self.dataframe_prompts = []  # (the DataFrames offered, the one it started at, why there's no data)
        self.chart_frame_prompts = []  # the notebook's DataFrames (ChartFrames) the Chart dialog offered
        self.custom_format_answer = None  # the Custom number format dialog's pattern; None cancels
        self.color_answer = None  # the color dialog's color, #rrggbb; None cancels
        self.merge_answer = True  # whether to merge though values would be lost
        self.sort_answer = None  # the Sort Range dialog's (sort columns, header row); None cancels
        self.sort_prompts = []  # (the range, its columns, the header row's guess, the first column) each time
        self.merge_prompts = 0
        self.color_prompts = []  # (the color it started at, its title) each time
        self.custom_format_prompts = []  # (the pattern it started with, its sample) each time
        self.load_prompts = []  # (the DataFrames offered, the cell named) each time
        self.sheet_name_answer = None  # the name typed to rename a sheet; None cancels
        self.sheet_name_prompts = []  # the name it started with, each time
        self.delete_sheet_answer = True  # whether to delete a sheet with something in it
        self.delete_sheet_prompts = []  # the sheet's name, each time
        # The Pivot Table dialog's answer: what to change of what it starts with (rows, column, values,
        # filters, totals), as a dict; None cancels.
        self.pivot_answer = {}
        self.pivot_prompts = []  # (what it's of, its columns' labels, the pivot table it started as, editing)


@pytest.fixture(autouse=True)
def preferences(monkeypatch, tmp_path):
    """Keep tests away from the user's real saved preferences."""
    from PySide6.QtCore import QSettings

    from ezsheet import appearance

    path = str(tmp_path / "preferences.ini")
    monkeypatch.setattr(appearance, "settings", lambda: QSettings(path, QSettings.IniFormat))
    return path


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    dialogs = Dialogs()

    def ask_to_save(window):
        dialogs.save_prompts += 1
        return dialogs.save_answer

    monkeypatch.setattr(MainWindow, "_ask_to_save", ask_to_save)
    def ask_insert_shift(window, problems):
        dialogs.insert_problems = problems
        return dialogs.insert_shift

    monkeypatch.setattr(MainWindow, "_ask_insert_shift", ask_insert_shift)

    def ask_delete_shift(window, problems):
        dialogs.delete_problems = problems
        return dialogs.delete_shift

    monkeypatch.setattr(MainWindow, "_ask_delete_shift", ask_delete_shift)

    def ask_sheet_name(window, current):
        dialogs.sheet_name_prompts.append(current)
        return dialogs.sheet_name_answer

    monkeypatch.setattr(MainWindow, "_ask_sheet_name", ask_sheet_name)

    def ask_delete_sheet(window, title):
        dialogs.delete_sheet_prompts.append(title)
        return dialogs.delete_sheet_answer

    monkeypatch.setattr(MainWindow, "_ask_delete_sheet", ask_delete_sheet)

    def ask_pivot(window, where, labels, values_of, start, editing):
        dialogs.pivot_prompts.append((where, labels, start, editing))
        if dialogs.pivot_answer is None:
            return None
        choice = {"rows": start.rows, "column": start.column, "values": start.values, "filters": start.filters,
                  "totals": start.totals}
        return {**choice, **dialogs.pivot_answer}

    monkeypatch.setattr(MainWindow, "_ask_pivot", ask_pivot)

    def ask_dataframe(window, frames, current, name, source, problem):
        dialogs.frame_name_prompts.append((name, source))
        dialogs.dataframe_prompts.append((list(frames), current, problem))
        if dialogs.frame_name_cancel:
            return None
        which, typed, update = dialogs.dataframe_answer or ("new" if current is None else current, None, False)
        if which == "new":  # as the dialog for a new one, which has no OK if there's no data
            return None if problem is not None else (None, typed or dialogs.frame_name_answer or name, False)
        return which, typed or frames[which].name, update

    monkeypatch.setattr(MainWindow, "_ask_dataframe", ask_dataframe)

    def ask_custom_format(window, pattern, sample):
        dialogs.custom_format_prompts.append((pattern, sample))
        return dialogs.custom_format_answer

    monkeypatch.setattr(MainWindow, "_ask_custom_format", ask_custom_format)

    def ask_color(window, start, title):
        dialogs.color_prompts.append((start, title))
        return dialogs.color_answer

    monkeypatch.setattr(MainWindow, "_ask_color", ask_color)

    def ask_merge_anyway(window):
        dialogs.merge_prompts += 1
        return dialogs.merge_answer

    monkeypatch.setattr(MainWindow, "_ask_merge_anyway", ask_merge_anyway)

    def ask_sort(window, where, left, right, labels, header, col):
        dialogs.sort_prompts.append((where, [labels(c) for c in range(left, right + 1)], header, col))
        return dialogs.sort_answer

    monkeypatch.setattr(MainWindow, "_ask_sort", ask_sort)

    def new_chart(columns, problem, frame, chart_frames, answer):
        """A new chart's choices, as the dialog makes them: of the cells, or a DataFrame named in it."""
        name = dialogs.frame_name_answer or frame
        option = {option.frame.name: option for option in chart_frames}.get(name)
        if option is not None:
            columns, problem = option.columns, option.problem
        if problem is not None:  # (no OK)
            return None
        kind, marker, *axes = answer
        x = axes[0] if axes else columns.default_x(kind)
        return GraphChoice(kind, marker, x, axes[1] if len(axes) > 1 else columns.default_ys(x, kind),
                           axes[2] if len(axes) > 2 else None, axes[3] if len(axes) > 3 else False,
                           axes[4] if len(axes) > 4 else None, name, axes[5] if len(axes) > 5 else False,
                           axes[6] if len(axes) > 6 else False)

    def ask_graph_options(window, columns, source, frame, chart_frames=(), problem=None):
        dialogs.graph_prompts.append((list(columns.labels) if columns else [], (window.graph_kind, window.graph_marker)))
        dialogs.frame_name_prompts.append((frame, source))
        dialogs.chart_frame_prompts.append(list(chart_frames))
        if dialogs.graph_answer is None:
            return None
        return new_chart(columns, problem, frame, chart_frames, dialogs.graph_answer)

    monkeypatch.setattr(MainWindow, "_ask_graph_options", ask_graph_options)

    def ask_chart(window, graphs, current, columns, source, problem, frame, chart_frames=()):
        dialogs.graph_change_prompts.append((list(graphs), current))
        dialogs.chart_prompts.append((columns, source, problem))
        dialogs.frame_name_prompts.append((frame, source))
        dialogs.chart_frame_prompts.append(list(chart_frames))
        if dialogs.graph_change_answer is None:
            return None
        index, kind, marker, *axes = dialogs.graph_change_answer
        if index == "new":  # New chart: as the dialog for one, which has no OK if there's a problem
            choice = new_chart(columns, problem, frame, chart_frames, (kind, marker, *axes))
            return None if choice is None else (None, choice)
        graph = graphs[index]
        return index, GraphChoice(kind, marker, axes[0] if axes else graph.x_label,
                                  axes[1] if len(axes) > 1 else graph.y_labels,
                                  axes[2] if len(axes) > 2 else graph.hue,
                                  axes[3] if len(axes) > 3 else graph.y_categories,
                                  axes[4] if len(axes) > 4 else graph.col if kind in FACETED else None,
                                  dialogs.rename_answer, axes[5] if len(axes) > 5 else graph.kde,
                                  axes[6] if len(axes) > 6 else graph.rug)

    monkeypatch.setattr(MainWindow, "_ask_chart", ask_chart)

    def ask_frame_to_load(window, found, cell):
        dialogs.load_prompts.append((list(found), cell))
        return dialogs.load_answer

    monkeypatch.setattr(MainWindow, "_ask_frame_to_load", ask_frame_to_load)
    monkeypatch.setattr(MainWindow, "_show_error", lambda window, text, detail: dialogs.errors.append(detail))
    return dialogs
