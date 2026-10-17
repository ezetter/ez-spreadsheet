import os

import pytest
from PySide6.QtWidgets import QMessageBox

from ezsheet.recent import MAX_RECENT, add_recent_file, menu_labels, recent_files
from ezsheet.storage import SheetData, save_sheet
from ezsheet.window import MainWindow


@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def items(window) -> list[str]:
    return [action.text() for action in window.recent_menu.actions()]


def sheet(tmp_path, name: str, text: str = "x") -> str:
    """A sheet file with `text` in A1 (not yet in the list)."""
    path = str(tmp_path / name)
    save_sheet(path, SheetData(10, 5, cells={(0, 0): text}))
    return path


def test_in_the_file_menu(window):
    file_menu = [m for m in window.menuBar().actions() if m.text() == "File"][0].menu()
    assert [a.text() for a in file_menu.actions()][:5] == ["New", "Open…", "Open Recent", "Save", "Save As…"]
    assert file_menu.actions()[2].menu() is window.recent_menu


def test_empty_at_first(window):
    assert items(window) == ["Clear Menu"]
    assert not window.recent_menu.actions()[0].isEnabled()


def test_opened_and_saved_sheets_newest_first(window, tmp_path):
    a, b = sheet(tmp_path, "a.ezs"), sheet(tmp_path, "b.ezs")
    window.open_path(a)
    window.save_to(str(tmp_path / "c.ezs"))
    assert items(window) == ["c.ezs", "a.ezs", "", "Clear Menu"]
    window.open_path(b)
    assert items(window)[:3] == ["b.ezs", "c.ezs", "a.ezs"]  # moved to the top, not repeated
    assert window.recent_menu.actions()[0].toolTip() == b
    assert window.recent_menu.actions()[-1].isEnabled()


def test_keeps_the_last_ten(window, tmp_path):
    for number in range(MAX_RECENT + 3):
        window.save_to(str(tmp_path / f"s{number}.ezs"))
    assert len(recent_files()) == MAX_RECENT
    assert items(window)[0] == f"s{MAX_RECENT + 2}.ezs" and items(window)[MAX_RECENT - 1] == "s3.ezs"


def test_choosing_one_opens_it(window, tmp_path, dialogs):
    path = sheet(tmp_path, "data.ezs", "hello")
    window.open_path(path)
    window.new_file()
    window.model.set_cell(5, 5, "unsaved")
    window.recent_menu.actions()[0].trigger()
    assert dialogs.save_prompts == 1  # asked about the unsaved change first (Discard)
    assert window.file_path == path and window.model.get_cell(0, 0) == "hello"


def test_cancel_keeps_the_sheet(window, tmp_path, dialogs):
    path = sheet(tmp_path, "data.ezs")
    window.model.set_cell(5, 5, "unsaved")
    dialogs.save_answer = QMessageBox.Cancel
    assert not window.open_recent(path)
    assert window.file_path is None and window.model.get_cell(5, 5) == "unsaved"


def test_missing_sheet_is_taken_off(window, tmp_path, dialogs):
    gone, kept = sheet(tmp_path, "gone.ezs"), sheet(tmp_path, "kept.ezs")
    window.open_path(gone)
    window.open_path(kept)
    os.remove(gone)
    assert not window.open_recent(gone)
    assert "isn't there anymore" in dialogs.errors[-1]
    assert recent_files() == [kept] and items(window) == ["kept.ezs", "", "Clear Menu"]


def test_damaged_sheet_stays_listed(window, tmp_path, dialogs):
    path = tmp_path / "bad.ezs"
    path.write_text("not json")
    add_recent_file(str(path))
    assert not window.open_recent(str(path))
    assert "isn't an EZ Sheet sheet" in dialogs.errors[-1] and recent_files() == [str(path)]


def test_clear_menu(window, tmp_path):
    window.save_to(str(tmp_path / "a.ezs"))
    window.recent_menu.actions()[-1].trigger()
    assert recent_files() == [] and items(window) == ["Clear Menu"]


def test_remembered_between_launches(app, tmp_path):
    first = MainWindow()
    first.save_to(str(tmp_path / "a.ezs"))
    first.close()
    second = MainWindow()
    assert items(second)[0] == "a.ezs"
    second.close()


def test_new_file_listed_once_saved(window, tmp_path):
    path = str(tmp_path / "new.ezs")
    window.open_or_create(path)  # nothing there yet
    assert recent_files() == []
    window.save()
    assert recent_files() == [path]


def test_same_names_show_their_folders(window, tmp_path):
    (tmp_path / "2024").mkdir()
    (tmp_path / "2025").mkdir()
    window.save_to(str(tmp_path / "2024" / "budget.ezs"))
    window.save_to(str(tmp_path / "2025" / "budget.ezs"))
    window.save_to(str(tmp_path / "R&D.ezs"))
    assert items(window)[:3] == ["R&&D.ezs", f"budget.ezs — {tmp_path / '2025'}",
                                 f"budget.ezs — {tmp_path / '2024'}"]


def test_home_folder_shortened():
    home = os.path.expanduser("~")
    assert menu_labels([f"{home}/Documents/a.ezs", f"{home}/Desktop/a.ezs", "/tmp/b.ezs"]) == [
        "a.ezs — ~/Documents", "a.ezs — ~/Desktop", "b.ezs"]
