import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

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
    monkeypatch.setattr(MainWindow, "_show_error", lambda window, text, detail: dialogs.errors.append(detail))
    return dialogs
