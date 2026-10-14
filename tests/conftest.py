import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from py_spread.notebook import GraphChoice
from py_spread.window import MainWindow


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
        # The Graph dialog's (kind, marker), or (kind, marker, x, ys[, hue]); None cancels. Columns
        # left out are the defaults (for a new graph) or the graph's own (when changing one).
        self.graph_answer = ("line", None)
        self.graph_prompts = []  # (the column labels, the choices it started with) each time it's shown
        self.graph_change_answer = None  # changing a graph: (which, kind, marker[, x, ys[, hue]]); None cancels
        self.graph_change_prompts = []  # (the graphs offered, the one it started with)
        self.load_answer = None  # Load Data to Sheet: the DataFrame's name; None cancels
        self.load_prompts = []  # (the DataFrames offered, the cell named) each time


@pytest.fixture(autouse=True)
def preferences(monkeypatch, tmp_path):
    """Keep tests away from the user's real saved preferences."""
    from PySide6.QtCore import QSettings

    from py_spread import appearance

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

    def ask_graph_options(window, columns):
        dialogs.graph_prompts.append((list(columns.labels), (window.graph_kind, window.graph_marker)))
        if dialogs.graph_answer is None:
            return None
        kind, marker, *axes = dialogs.graph_answer
        x = axes[0] if axes else columns.default_x(kind)
        return GraphChoice(kind, marker, x, axes[1] if len(axes) > 1 else columns.default_ys(x),
                           axes[2] if len(axes) > 2 else None)

    monkeypatch.setattr(MainWindow, "_ask_graph_options", ask_graph_options)

    def ask_graph_change(window, graphs, current):
        dialogs.graph_change_prompts.append((list(graphs), current))
        if dialogs.graph_change_answer is None:
            return None
        index, kind, marker, *axes = dialogs.graph_change_answer
        graph = graphs[index]
        return index, GraphChoice(kind, marker, axes[0] if axes else graph.x_label,
                                  axes[1] if len(axes) > 1 else graph.y_labels,
                                  axes[2] if len(axes) > 2 else graph.hue)

    monkeypatch.setattr(MainWindow, "_ask_graph_change", ask_graph_change)

    def ask_frame_to_load(window, found, cell):
        dialogs.load_prompts.append((list(found), cell))
        return dialogs.load_answer

    monkeypatch.setattr(MainWindow, "_ask_frame_to_load", ask_frame_to_load)
    monkeypatch.setattr(MainWindow, "_show_error", lambda window, text, detail: dialogs.errors.append(detail))
    return dialogs
